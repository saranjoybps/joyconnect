"""Builds the workflow services (shared by the API process and the worker process)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import httpx

from app.agent.tools import ToolExecutor
from app.core.config import Settings
from app.core.secrets import SecretStore
from app.db.client import Database
from app.workflows.engine import Engine, EngineServices
from app.workflows.runner import ExecutionService
from app.workflows.service import WorkflowService


@dataclass
class WorkflowRuntime:
    workflows: WorkflowService
    engine: Engine
    executions: ExecutionService
    triggers: Any = None


def build_workflow_runtime(db: Database, store: SecretStore, http: httpx.AsyncClient, settings: Settings,
                           llm_factory: Callable[[], Any] | None = None, now: Callable[..., Any] | None = None
                           ) -> WorkflowRuntime:
    workflows = WorkflowService(db)
    svc = EngineServices(db=db, settings=settings, http=http, executor=ToolExecutor(db, store, http, settings),
                         workflows=workflows, llm_factory=llm_factory)
    if now is not None:
        svc.now = now
    engine = Engine(svc)
    return WorkflowRuntime(workflows, engine, ExecutionService(db, workflows, engine, settings))
