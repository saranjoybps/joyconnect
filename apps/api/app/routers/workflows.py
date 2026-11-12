"""Workflow API: CRUD, the patch endpoint, publish, versions, and the node catalog."""

from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.core.config import REPO_ROOT
from app.core.security import UserDep
from app.workflows.patch import PatchError
from app.workflows.registry import get_registry
from app.workflows.service import WorkflowError, WorkflowService

router = APIRouter(prefix="/api", tags=["workflows"])


def get_workflows(request: Request) -> WorkflowService:
    return request.app.state.workflows


WorkflowsDep = Annotated[WorkflowService, Depends(get_workflows)]


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, PatchError):
        return HTTPException(422, {"message": str(exc), "errors": exc.errors, "operation_index": exc.index})
    assert isinstance(exc, WorkflowError)
    return HTTPException(exc.status, {"message": exc.message, "errors": exc.errors, **exc.extra})


class CreateBody(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    operations: list[dict[str, Any]] | None = None


class PatchBody(BaseModel):
    base_version: int = Field(ge=1)
    operations: list[dict[str, Any]] = Field(min_length=1, max_length=200)


@router.get("/node-types")
async def node_types(user: UserDep) -> list[dict[str, Any]]:
    """The node registry: the palette and every config panel are generated from this."""
    return get_registry().public()


@router.get("/workflow-schema")
async def workflow_schema() -> dict[str, Any]:
    """The shared JSON Schema; the web app validates against the same file."""
    return json.loads((REPO_ROOT / "schemas" / "workflow.schema.json").read_text(encoding="utf-8"))


@router.get("/workflows")
async def list_workflows(user: UserDep, svc: WorkflowsDep) -> list[dict[str, Any]]:
    return await svc.list(user.id)


@router.post("/workflows", status_code=201)
async def create_workflow(body: CreateBody, user: UserDep, svc: WorkflowsDep) -> dict[str, Any]:
    try:
        doc = await svc.create(user.id, body.name, body.operations)
    except (PatchError, WorkflowError) as exc:
        raise _http(exc) from exc
    return {"workflow": doc}


@router.get("/workflows/{workflow_id}")
async def get_workflow(workflow_id: str, user: UserDep, svc: WorkflowsDep) -> dict[str, Any]:
    try:
        return await svc.get_with_meta(user.id, workflow_id)
    except WorkflowError as exc:
        raise _http(exc) from exc


@router.post("/workflows/{workflow_id}/patch")
async def patch_workflow(workflow_id: str, body: PatchBody, user: UserDep, svc: WorkflowsDep) -> dict[str, Any]:
    try:
        doc, log, risk = await svc.patch(user.id, workflow_id, body.base_version, body.operations)
    except (PatchError, WorkflowError) as exc:
        raise _http(exc) from exc
    return {"workflow": doc, "changes": log, "risk": risk}


@router.post("/workflows/{workflow_id}/publish")
async def publish_workflow(workflow_id: str, user: UserDep, svc: WorkflowsDep) -> dict[str, Any]:
    try:
        doc, extras = await svc.publish(user.id, workflow_id)
    except WorkflowError as exc:
        raise _http(exc) from exc
    return {"workflow": doc, **extras}


@router.post("/workflows/{workflow_id}/unpublish")
async def unpublish_workflow(workflow_id: str, user: UserDep, svc: WorkflowsDep) -> dict[str, Any]:
    try:
        return {"workflow": await svc.unpublish(user.id, workflow_id)}
    except WorkflowError as exc:
        raise _http(exc) from exc


@router.delete("/workflows/{workflow_id}")
async def delete_workflow(workflow_id: str, user: UserDep, svc: WorkflowsDep) -> dict[str, Any]:
    """Destructive. The chat agent must get approval before calling this; the UI confirms first."""
    try:
        await svc.delete(user.id, workflow_id)
    except WorkflowError as exc:
        raise _http(exc) from exc
    return {"ok": True}


@router.get("/workflows/{workflow_id}/versions")
async def list_versions(workflow_id: str, user: UserDep, svc: WorkflowsDep) -> list[dict[str, Any]]:
    try:
        return await svc.versions(user.id, workflow_id)
    except WorkflowError as exc:
        raise _http(exc) from exc


@router.get("/workflows/{workflow_id}/versions/{version}")
async def get_version(workflow_id: str, version: int, user: UserDep, svc: WorkflowsDep) -> dict[str, Any]:
    try:
        return {"workflow": await svc.version_document(user.id, workflow_id, version)}
    except WorkflowError as exc:
        raise _http(exc) from exc


@router.get("/workflows/{workflow_id}/triggers")
async def list_triggers(workflow_id: str, request: Request, user: UserDep) -> list[dict[str, Any]]:
    """Schedules (next run) and webhooks (URL; never the secret) of the published workflow."""
    try:
        return await request.app.state.triggers.list(user.id, workflow_id)
    except WorkflowError as exc:
        raise _http(exc) from exc


@router.post("/workflows/{workflow_id}/triggers/{node_id}/rotate-secret")
async def rotate_webhook_secret(workflow_id: str, node_id: str, request: Request, user: UserDep) -> dict[str, Any]:
    """New header secret for a webhook; shown once."""
    from app.workflows.runner import ExecutionError

    try:
        return {"secret": await request.app.state.triggers.rotate_secret(user.id, workflow_id, node_id)}
    except WorkflowError as exc:
        raise _http(exc) from exc
    except ExecutionError as exc:
        raise HTTPException(exc.status, {"message": exc.message}) from exc
