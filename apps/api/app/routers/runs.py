"""Run history: every tool call the agent made for the current user, secrets redacted."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query

from app.connectors.registry import all_manifests, get_manifest
from app.core.security import UserDep
from app.deps import DbDep

router = APIRouter(prefix="/api", tags=["runs"])
FETCH_LIMIT = 500            # newest runs considered; filtering is applied on top of these
STATUSES = ("pending", "approved", "rejected", "ok", "error")


def _view(row: dict[str, Any]) -> dict[str, Any]:
    tool = row.get("tool") or ""
    connector = row.get("connector") or tool.split("__", 1)[0]
    manifest = get_manifest(connector)
    risk = row.get("risk")
    if not risk and manifest:
        risk = next((t.risk for t in manifest.tools if t.name == tool), None)
    output = row.get("result_redacted")
    return {
        "id": row["id"],
        "created_at": row.get("created_at"),
        "finished_at": row.get("finished_at"),
        "connector": connector,
        "connector_name": manifest.name if manifest else connector,
        "tool": tool,
        "action": tool.split("__", 1)[-1].replace("_", " ").capitalize(),
        "risk": risk,
        "status": row.get("status"),
        "duration_ms": row.get("duration_ms"),
        "conversation_id": row.get("conversation_id"),
        "input": row.get("args_redacted"),
        "output": output if output is not None else row.get("result_summary"),
    }


@router.get("/runs")
async def list_runs(
    user: UserDep, db: DbDep,
    connector: Annotated[str | None, Query(max_length=64)] = None,
    status: Annotated[str | None, Query(max_length=16)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0, le=FETCH_LIMIT)] = 0,
) -> dict[str, Any]:
    filters: dict[str, Any] = {"user_id": user.id}
    if status in STATUSES:
        filters["status"] = status
    rows = await db.select("tool_runs", filters, order="created_at.desc", limit=FETCH_LIMIT)
    views = [_view(r) for r in rows]
    if connector:
        views = [v for v in views if v["connector"] == connector]
    page = views[offset:offset + limit]
    return {
        "runs": page,
        "total": len(views),
        "connectors": [{"id": m.id, "name": m.name} for m in all_manifests().values()],
        "statuses": list(STATUSES),
    }
