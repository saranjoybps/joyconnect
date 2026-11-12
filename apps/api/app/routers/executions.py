"""Running workflows: start runs, test a node, read executions, decide approvals, cancel."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.core.security import UserDep
from app.workflows.runner import ExecutionError, ExecutionService

router = APIRouter(prefix="/api", tags=["executions"])


def get_executions(request: Request) -> ExecutionService:
    return request.app.state.executions


ExecDep = Annotated[ExecutionService, Depends(get_executions)]


def _http(exc: ExecutionError) -> HTTPException:
    return HTTPException(exc.status, {"message": exc.message, **exc.extra})


class RunBody(BaseModel):
    start_node_id: str | None = None          # "run from here"
    trigger_node_id: str | None = None
    trigger_data: Any = None                  # the payload a webhook/schedule would have delivered


class TestNodeBody(BaseModel):
    input: list[dict[str, Any]] | None = Field(default=None, max_length=200)   # items; default: upstream data
    confirm: bool = False                     # required for nodes that change data in an app


class DecisionBody(BaseModel):
    approve: bool


@router.post("/workflows/{workflow_id}/run", status_code=202)
async def run_workflow(workflow_id: str, body: RunBody, user: UserDep, svc: ExecDep) -> dict[str, Any]:
    """Queue a manual run of the current draft. A worker (python -m app.worker) executes it."""
    try:
        row = await svc.start(user.id, workflow_id, mode="manual", trigger_node_id=body.trigger_node_id,
                              trigger_data=body.trigger_data, start_node_id=body.start_node_id)
    except ExecutionError as exc:
        raise _http(exc) from exc
    return {"execution": svc._public(row)}


@router.post("/workflows/{workflow_id}/nodes/{node_id}/test")
async def test_node(workflow_id: str, node_id: str, body: TestNodeBody, user: UserDep, svc: ExecDep) -> dict[str, Any]:
    try:
        return await svc.test_node(user.id, workflow_id, node_id, body.input, body.confirm)
    except ExecutionError as exc:
        raise _http(exc) from exc


@router.get("/executions")
async def list_executions(user: UserDep, svc: ExecDep, workflow_id: str | None = None, status: str | None = None,
                          limit: int = 50) -> list[dict[str, Any]]:
    return await svc.list(user.id, workflow_id, status, max(1, min(limit, 200)))


@router.get("/executions/{execution_id}")
async def get_execution(execution_id: str, user: UserDep, svc: ExecDep) -> dict[str, Any]:
    try:
        return await svc.get(user.id, execution_id)
    except ExecutionError as exc:
        raise _http(exc) from exc


@router.post("/executions/{execution_id}/cancel")
async def cancel_execution(execution_id: str, user: UserDep, svc: ExecDep) -> dict[str, Any]:
    try:
        return await svc.cancel(user.id, execution_id)
    except ExecutionError as exc:
        raise _http(exc) from exc


@router.get("/execution-approvals")
async def pending_approvals(user: UserDep, svc: ExecDep) -> list[dict[str, Any]]:
    return await svc.pending_approvals(user.id)


@router.post("/execution-approvals/{approval_id}/decision")
async def decide(approval_id: str, body: DecisionBody, user: UserDep, svc: ExecDep) -> dict[str, Any]:
    try:
        return await svc.decide_approval(user.id, approval_id, body.approve)
    except ExecutionError as exc:
        raise _http(exc) from exc
