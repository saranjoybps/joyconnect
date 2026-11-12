"""Triggers: manual (the run endpoint), schedule and webhook.

Publishing a workflow registers one `triggers` row per Schedule/Webhook node of the published version;
unpublishing deactivates them. Schedules are fired by the worker's scheduler tick; webhooks are served by
`/api/hooks/{path}` on the API. Both only ever run the PUBLISHED snapshot.

Webhook security: the path is a random 192-bit token. Header authentication uses a secret that the SERVER
generates (shown once, stored encrypted in the SecretStore, rotatable), so no secret ever sits in the workflow
JSON, its versions, or a chat transcript.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import secrets as pysecrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qs

from app.core.config import Settings
from app.core.ratelimit import SlidingWindowLimiter
from app.core.secrets import SecretStore
from app.db.client import Database
from app.workflows.runner import ExecutionError, ExecutionService
from app.workflows.schedule import ScheduleError, compute_next
from app.workflows.service import WorkflowService

log = logging.getLogger(__name__)
Doc = dict[str, Any]
DEFAULT_SECRET_HEADER = "X-Webhook-Secret"
HIDDEN_HEADERS = {"authorization", "cookie", "proxy-authorization"}
BLOCKED_RESPONSE_HEADERS = {"set-cookie", "content-type", "content-length", "transfer-encoding", "connection",
                            "host", "location"} | {"access-control-allow-origin", "access-control-allow-credentials"}


async def _sleep(seconds: float) -> None:           # module-level so tests can replace it
    await asyncio.sleep(seconds)


@dataclass
class WebhookResult:
    status: int
    body: Any = None
    headers: dict[str, str] = field(default_factory=dict)
    redirect: str | None = None
    text: bool = False
    allow: str | None = None


class TriggerService:
    def __init__(self, db: Database, workflows: WorkflowService, executions: ExecutionService, store: SecretStore,
                 settings: Settings):
        self.db, self.workflows, self.executions, self.store, self.settings = db, workflows, executions, store, settings
        self._limiter = SlidingWindowLimiter()

    def _now(self) -> datetime:
        return self.executions.engine.svc.now()

    def webhook_url(self, path: str) -> str:
        base = (self.settings.public_api_base_url or self.settings.api_base_url).rstrip("/")
        return f"{base}/api/hooks/{path}"

    # ------------------------------------------------------------------ publish / unpublish

    async def sync(self, row: Doc, doc: Doc) -> Doc:
        """Make the triggers table match the published document. Returns {'webhook_secrets': {node_id: secret}}
        for secrets generated just now: the only time they are ever shown."""
        user_id, wid = row["user_id"], row["id"]
        existing = {t["node_id"]: t for t in await self.db.select("triggers", {"workflow_id": wid})}
        wanted = {n["id"]: n for n in doc["nodes"]
                  if n["type"] in ("schedule_trigger", "webhook_trigger") and not n.get("disabled")}
        for node_id, t in existing.items():
            if node_id not in wanted:
                await self._remove(t)
        new_secrets: dict[str, str] = {}
        for node_id, node in wanted.items():
            params, t = node["parameters"], existing.get(node_id)
            if node["type"] == "schedule_trigger":
                nxt = compute_next(params, self._now())
                values = {"config": params, "active": True, "next_run_at": nxt.isoformat() if nxt else None}
                if t:
                    await self.db.update("triggers", {"id": t["id"]}, values)
                else:
                    await self.db.insert("triggers", {"user_id": user_id, "workflow_id": wid, "node_id": node_id,
                                                      "type": "schedule", **values})
                continue
            cfg = {k: params.get(k) for k in ("http_method", "authentication", "header_name", "response_mode",
                                              "response_code")}
            needs_secret = cfg["authentication"] == "header"
            values = {"config": cfg, "active": True}
            if t is None:
                t = await self.db.insert("triggers", {
                    "user_id": user_id, "workflow_id": wid, "node_id": node_id, "type": "webhook",
                    "path": pysecrets.token_urlsafe(24), "secret_id": None, **values})
            else:
                await self.db.update("triggers", {"id": t["id"]}, values)
            if needs_secret and not t.get("secret_id"):
                secret = pysecrets.token_urlsafe(32)
                sid = await self.store.put(user_id, {"secret": secret})
                await self.db.update("triggers", {"id": t["id"]}, {"secret_id": sid})
                new_secrets[node_id] = secret
            elif not needs_secret and t.get("secret_id"):
                await self.store.delete(t["secret_id"])
                await self.db.update("triggers", {"id": t["id"]}, {"secret_id": None})
        return {"webhook_secrets": new_secrets}

    async def _remove(self, t: Doc) -> None:
        if t.get("secret_id"):
            await self.store.delete(t["secret_id"])
        await self.db.delete("triggers", {"id": t["id"]})

    async def deactivate(self, workflow_id: str) -> None:
        for t in await self.db.select("triggers", {"workflow_id": workflow_id}):
            await self.db.update("triggers", {"id": t["id"]}, {"active": False})

    async def list(self, user_id: str, workflow_id: str) -> list[Doc]:
        await self.workflows.row(user_id, workflow_id)
        out = []
        for t in await self.db.select("triggers", {"workflow_id": workflow_id, "user_id": user_id}):
            item = {"node_id": t["node_id"], "type": t["type"], "active": t["active"], "config": t["config"]}
            if t["type"] == "webhook":
                item.update(url=self.webhook_url(t["path"]), has_secret=bool(t.get("secret_id")),
                            secret_header=(t["config"].get("header_name") or DEFAULT_SECRET_HEADER))
            else:
                item.update(next_run_at=t.get("next_run_at"), last_run_at=t.get("last_run_at"))
            out.append(item)
        return out

    async def rotate_secret(self, user_id: str, workflow_id: str, node_id: str) -> str:
        await self.workflows.row(user_id, workflow_id)
        rows = await self.db.select("triggers", {"workflow_id": workflow_id, "node_id": node_id, "user_id": user_id,
                                                 "type": "webhook"})
        if not rows or rows[0]["config"].get("authentication") != "header":
            raise ExecutionError(404, "that webhook does not use header authentication")
        t = rows[0]
        if t.get("secret_id"):
            await self.store.delete(t["secret_id"])
        secret = pysecrets.token_urlsafe(32)
        await self.db.update("triggers", {"id": t["id"]}, {"secret_id": await self.store.put(user_id, {"secret": secret})})
        return secret

    # ------------------------------------------------------------------ schedules

    async def fire_due_schedules(self) -> int:
        """Start a run for every due schedule. The next_run_at update is a compare-and-swap, so with several
        workers each due schedule fires exactly once. Missed runs are discarded: the next time is computed from now."""
        now = self._now()
        fired = 0
        for t in await self.db.select("triggers", {"type": "schedule", "active": True}):
            due = t.get("next_run_at")
            if due is None:
                nxt = compute_next(t["config"], now)
                await self.db.update("triggers", {"id": t["id"], "next_run_at": None},
                                     {"next_run_at": nxt.isoformat() if nxt else None})
                continue
            if datetime.fromisoformat(str(due).replace("Z", "+00:00")) > now:
                continue
            try:
                nxt = compute_next(t["config"], now)
            except ScheduleError:
                nxt = None
            won = await self.db.update("triggers", {"id": t["id"], "next_run_at": due},
                                       {"next_run_at": nxt.isoformat() if nxt else None,
                                        "last_run_at": now.isoformat()})
            if not won:
                continue                       # another worker took it
            try:
                await self.executions.start(
                    t["user_id"], t["workflow_id"], mode="schedule", trigger_node_id=t["node_id"],
                    trigger_data={"timestamp": now.isoformat(timespec="seconds")})
                fired += 1
            except (ExecutionError, Exception) as exc:  # noqa: BLE001
                log.warning("schedule %s could not start: %s", t["id"], getattr(exc, "message", type(exc).__name__))
                if isinstance(exc, ExecutionError) and exc.status in (404, 409):
                    await self.db.update("triggers", {"id": t["id"]}, {"active": False})   # unpublished or deleted
        return fired

    # ------------------------------------------------------------------ webhooks

    async def handle_webhook(self, path: str, method: str, headers: dict[str, str], query: dict[str, str],
                             raw_body: bytes) -> WebhookResult:
        rows = await self.db.select("triggers", {"path": path, "type": "webhook"})
        t = rows[0] if rows and rows[0].get("active") else None
        if t is None:
            return WebhookResult(404, {"error": "not found"})
        if not self._limiter.allow(path, self.settings.webhook_rate_limit_per_minute):
            return WebhookResult(429, {"error": "too many requests"}, {"Retry-After": "60"})
        cfg = t["config"]
        expected = (cfg.get("http_method") or "POST").upper()
        if method.upper() != expected:
            return WebhookResult(405, {"error": f"use {expected}"}, allow=expected)
        lower = {k.lower(): v for k, v in headers.items()}
        header_name = (cfg.get("header_name") or DEFAULT_SECRET_HEADER)
        if cfg.get("authentication") == "header":
            stored = (await self.store.get(t["secret_id"])).get("secret", "") if t.get("secret_id") else None
            given = lower.get(header_name.lower(), "")
            if not stored or not hmac.compare_digest(stored.encode(), given.encode()):
                return WebhookResult(401, {"error": "unauthorized"})
        if len(raw_body) > self.settings.webhook_max_body_bytes:
            return WebhookResult(413, {"error": "payload too large"})
        try:
            body = self._parse_body(lower.get("content-type", ""), raw_body)
        except ValueError:
            return WebhookResult(400, {"error": "the body is not valid JSON"})
        shown = {k: v for k, v in lower.items() if k not in HIDDEN_HEADERS and k != header_name.lower()}
        data = {"headers": shown, "params": {}, "query": query, "body": body}
        try:
            ex = await self.executions.start(t["user_id"], t["workflow_id"], mode="webhook",
                                             trigger_node_id=t["node_id"], trigger_data=data)
        except ExecutionError as exc:
            if exc.status in (404, 409):
                await self.db.update("triggers", {"id": t["id"]}, {"active": False})
                return WebhookResult(404, {"error": "not found"})
            return WebhookResult(500, {"error": "could not start the workflow"})
        await self.db.update("triggers", {"id": t["id"]}, {"last_run_at": self._now().isoformat()})
        code = int(cfg.get("response_code") or 200)
        mode = cfg.get("response_mode") or "immediately"
        if mode == "immediately":
            return WebhookResult(code, {"message": "Workflow was started"})
        return await self._wait_for_response(ex["id"], code)

    @staticmethod
    def _parse_body(content_type: str, raw: bytes) -> Any:
        if not raw:
            return None
        ctype = content_type.split(";")[0].strip().lower()
        text = raw.decode("utf-8", errors="replace")
        if ctype == "application/json" or ctype.endswith("+json"):
            try:
                return json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError("bad json") from exc
        if ctype == "application/x-www-form-urlencoded":
            return {k: v[0] if len(v) == 1 else v for k, v in parse_qs(text, keep_blank_values=True).items()}
        return text

    async def _wait_for_response(self, execution_id: str, code: int) -> WebhookResult:
        """Wait (up to webhook_wait_seconds) for the run to finish and answer with its response."""
        for _ in range(int(self.settings.webhook_wait_seconds / 0.2)):
            row = (await self.db.select("executions", {"id": execution_id}))[0]
            status = row["status"]
            if status == "waiting":
                return WebhookResult(202, {"message": "The workflow is waiting (for approval or a timer)."})
            if status in ("success", "error", "canceled"):
                r = row.get("response") or {"status": 500 if status != "success" else code, "body": None}
                return self._to_result(r)
            await _sleep(0.2)
        return WebhookResult(202, {"message": "The workflow is still running."})

    @staticmethod
    def _to_result(r: Doc) -> WebhookResult:
        headers = {str(k): str(v) for k, v in (r.get("headers") or {}).items()
                   if str(k).lower() not in BLOCKED_RESPONSE_HEADERS and "\n" not in str(v) and "\r" not in str(v)}
        if r.get("redirect"):
            return WebhookResult(int(r.get("status") or 302), None, headers, redirect=r["redirect"])
        return WebhookResult(int(r.get("status") or 200), r.get("body"), headers, text=bool(r.get("text")))
