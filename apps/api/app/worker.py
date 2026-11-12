"""Execution worker: `python -m app.worker`.

Claims queued runs from Postgres (FOR UPDATE SKIP LOCKED), runs them, and (step 3) fires due schedule triggers.
Run as many as you like; each job is claimed by exactly one. Ctrl+C stops after the current node.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import socket
import time

import httpx

from app.agent.llm import OpenAIChat
from app.core.config import Settings, get_settings
from app.core.logging import setup_logging
from app.core.secrets import build_secret_store
from app.db.client import SupabaseRestDatabase
from app.workflows.runtime import WorkflowRuntime, build_workflow_runtime

log = logging.getLogger("worker")


async def tick(runtime: WorkflowRuntime, worker_id: str) -> bool:
    """One pass: fire due schedules, then run one queued job. Returns True if a job ran."""
    if runtime.triggers is not None:
        await runtime.triggers.fire_due_schedules()
    return await runtime.executions.process_one(worker_id)


async def run_forever(runtime: WorkflowRuntime, settings: Settings, worker_id: str, stop: asyncio.Event | None = None,
                      once: bool = False) -> None:
    stop = stop or asyncio.Event()
    last_sweep = 0.0
    while not stop.is_set():
        try:
            did = await tick(runtime, worker_id)
            if time.monotonic() - last_sweep > 60:
                last_sweep = time.monotonic()
                await runtime.executions.expire_stale_approvals()
        except Exception as exc:  # noqa: BLE001 — keep the worker alive
            log.exception("worker tick failed: %s", type(exc).__name__)
            did = False
        if once and not did:
            return
        if not did:
            try:
                await asyncio.wait_for(stop.wait(), settings.worker_poll_seconds)
            except asyncio.TimeoutError:
                pass


async def main(once: bool = False) -> None:
    settings = get_settings()
    setup_logging()
    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0)) as http:
        db = SupabaseRestDatabase(settings.supabase_url, settings.supabase_service_role_key, http)
        store = build_secret_store(settings.secret_store, db, settings.token_encryption_key)
        runtime = build_workflow_runtime(db, store, http, settings, llm_factory=lambda: OpenAIChat(settings))
        worker_id = f"{socket.gethostname()}-{os.getpid()}"
        log.info("worker %s started", worker_id)
        await run_forever(runtime, settings, worker_id, once=once)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Workflow execution worker")
    parser.add_argument("--once", action="store_true", help="drain the queue, then exit")
    args = parser.parse_args()
    try:
        asyncio.run(main(once=args.once))
    except KeyboardInterrupt:
        pass
