"""Workflow storage, versioning and the patch API's optimistic concurrency.

A workflow row holds the current draft (`definition`, `settings`, `version`). Every successful change bumps
`version` and writes an immutable snapshot to `workflow_versions`. Publishing records which version runs
unattended (`published_version`); schedule and webhook triggers run that snapshot, never the draft.

Concurrency: the write is a compare-and-swap on `version` (`UPDATE ... WHERE id = ? AND version = ?`), so two
editors, or chat and the canvas, can never silently overwrite each other: the loser gets a Conflict carrying the
latest workflow and re-applies its edit on top.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from app.db.client import Database
from app.workflows.patch import PatchError, apply_operations, parse_operations, patch_risk
from app.workflows.registry import NodeRegistry, get_registry
from app.workflows.schema import publish_errors

Doc = dict[str, Any]
TriggerHook = Callable[[Doc, Doc], Awaitable[None]]   # (workflow row, published document)


class WorkflowError(Exception):
    def __init__(self, status: int, message: str, errors: list[str] | None = None, **extra: Any):
        super().__init__(message)
        self.status, self.message, self.errors, self.extra = status, message, errors or [message], extra


class Conflict(WorkflowError):
    def __init__(self, current: Doc, message: str = "The workflow changed since you loaded it."):
        super().__init__(409, message, current=current)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def to_document(row: Doc) -> Doc:
    """The schema-shaped workflow document for a stored row."""
    d = row.get("definition") or {}
    return {"id": row["id"], "name": row["name"], "status": row["status"], "version": row["version"],
            "nodes": copy.deepcopy(d.get("nodes", [])), "edges": copy.deepcopy(d.get("edges", [])),
            "settings": copy.deepcopy(row.get("settings") or {})}


def meta(row: Doc) -> Doc:
    return {"published_version": row.get("published_version"), "updated_at": row.get("updated_at"),
            "created_at": row.get("created_at")}


class WorkflowService:
    def __init__(self, db: Database, registry: NodeRegistry | None = None,
                 on_publish: TriggerHook | None = None, on_unpublish: Callable[[str], Awaitable[None]] | None = None):
        self.db = db
        self.registry = registry or get_registry()
        self.on_publish, self.on_unpublish = on_publish, on_unpublish

    # ------------------------------------------------------------------ reads

    async def row(self, user_id: str, workflow_id: str) -> Doc:
        rows = await self.db.select("workflows", {"id": workflow_id, "user_id": user_id})
        if not rows:
            raise WorkflowError(404, "workflow not found")
        return rows[0]

    async def get(self, user_id: str, workflow_id: str) -> Doc:
        return to_document(await self.row(user_id, workflow_id))

    async def get_with_meta(self, user_id: str, workflow_id: str) -> Doc:
        row = await self.row(user_id, workflow_id)
        return {"workflow": to_document(row), **meta(row)}

    async def list(self, user_id: str) -> list[Doc]:
        rows = await self.db.select("workflows", {"user_id": user_id}, order="updated_at.desc", limit=200)
        return [{"id": r["id"], "name": r["name"], "status": r["status"], "version": r["version"],
                 "published_version": r.get("published_version"), "updated_at": r.get("updated_at"),
                 "node_count": len((r.get("definition") or {}).get("nodes", []))} for r in rows]

    async def versions(self, user_id: str, workflow_id: str) -> list[Doc]:
        await self.row(user_id, workflow_id)
        rows = await self.db.select("workflow_versions", {"workflow_id": workflow_id, "user_id": user_id},
                                    order="version.desc", limit=200)
        return [{"version": r["version"], "name": r["name"], "created_at": r.get("created_at")} for r in rows]

    async def version_document(self, user_id: str, workflow_id: str, version: int) -> Doc:
        rows = await self.db.select("workflow_versions",
                                    {"workflow_id": workflow_id, "user_id": user_id, "version": version})
        if not rows:
            raise WorkflowError(404, "version not found")
        r = rows[0]
        status = "published" if (await self.row(user_id, workflow_id)).get("published_version") == version else "draft"
        return {"id": workflow_id, "name": r["name"], "status": status, "version": version,
                "nodes": r["definition"].get("nodes", []), "edges": r["definition"].get("edges", []),
                "settings": r.get("settings") or {}}

    async def published_document(self, user_id: str, workflow_id: str) -> Doc | None:
        """The snapshot unattended runs execute, or None if the workflow is not published."""
        row = await self.row(user_id, workflow_id)
        if row.get("published_version") is None:
            return None
        return await self.version_document(user_id, workflow_id, row["published_version"])

    # ------------------------------------------------------------------ writes

    async def create(self, user_id: str, name: str, operations: list[Doc] | None = None) -> Doc:
        empty: Doc = {"id": "pending", "name": name, "status": "draft", "version": 1, "nodes": [], "edges": [],
                      "settings": {}}
        doc, _log = (apply_operations(empty, parse_operations(operations or []), self.registry)
                     if operations else (empty, []))
        await self._check_connections(user_id, doc)
        row = await self.db.insert("workflows", {
            "user_id": user_id, "name": doc["name"], "status": "draft", "version": 1, "published_version": None,
            "definition": {"nodes": doc["nodes"], "edges": doc["edges"]}, "settings": doc["settings"],
            "updated_at": _now()})
        await self._snapshot(row)
        return to_document(row)

    async def patch(self, user_id: str, workflow_id: str, base_version: int,
                    raw_operations: list[Doc]) -> tuple[Doc, list[Doc], str]:
        """Apply operations atomically. Returns (new document, change log, risk)."""
        row = await self.row(user_id, workflow_id)
        if row["version"] != base_version:
            raise Conflict(to_document(row))
        ops = parse_operations(raw_operations)
        before = to_document(row)
        after, log = apply_operations(before, ops, self.registry)
        await self._check_connections(user_id, after)
        won = await self.db.update(
            "workflows", {"id": workflow_id, "user_id": user_id, "version": base_version},
            {"name": after["name"], "definition": {"nodes": after["nodes"], "edges": after["edges"]},
             "settings": after["settings"], "version": base_version + 1, "updated_at": _now()})
        if not won:  # someone else committed between our read and our write
            raise Conflict(await self.get(user_id, workflow_id))
        await self._snapshot(won[0])
        return to_document(won[0]), log, patch_risk(before, ops, row.get("published_version") is not None)

    async def publish(self, user_id: str, workflow_id: str) -> Doc:
        row = await self.row(user_id, workflow_id)
        doc = to_document(row)
        errors = publish_errors(doc, self.registry)
        errors += await self._publish_reference_errors(user_id, doc)
        if errors:
            raise WorkflowError(422, "This workflow is not ready to publish: " + "; ".join(errors[:5]), errors)
        won = await self.db.update("workflows", {"id": workflow_id, "user_id": user_id, "version": row["version"]},
                                   {"status": "published", "published_version": row["version"], "updated_at": _now()})
        if not won:
            raise Conflict(await self.get(user_id, workflow_id))
        if self.on_publish:
            await self.on_publish(won[0], doc)
        return to_document(won[0])

    async def unpublish(self, user_id: str, workflow_id: str) -> Doc:
        await self.row(user_id, workflow_id)
        won = await self.db.update("workflows", {"id": workflow_id, "user_id": user_id},
                                   {"status": "draft", "published_version": None, "updated_at": _now()})
        if self.on_unpublish:
            await self.on_unpublish(workflow_id)
        return to_document(won[0])

    async def delete(self, user_id: str, workflow_id: str) -> None:
        await self.row(user_id, workflow_id)
        if self.on_unpublish:
            await self.on_unpublish(workflow_id)
        for table in ("node_executions", "executions", "triggers", "workflow_versions"):
            await self.db.delete(table, {"workflow_id": workflow_id})
        await self.db.delete("workflows", {"id": workflow_id, "user_id": user_id})

    # ------------------------------------------------------------------ helpers

    async def _snapshot(self, row: Doc) -> None:
        await self.db.insert("workflow_versions", {
            "workflow_id": row["id"], "user_id": row["user_id"], "version": row["version"], "name": row["name"],
            "definition": copy.deepcopy(row["definition"]), "settings": copy.deepcopy(row.get("settings") or {})})

    async def _check_connections(self, user_id: str, doc: Doc) -> None:
        """A node may only use the user's own connection of the right app."""
        problems = []
        for n in doc["nodes"]:
            cid, nt = n.get("connection_id"), self.registry.get(n["type"])
            if not cid or nt is None or nt.connector is None:
                continue
            rows = await self.db.select("connections", {"id": cid, "user_id": user_id})
            if not rows:
                problems.append(f"node '{n['name']}': connection {cid} was not found")
            elif rows[0]["provider"] != nt.connector:
                problems.append(f"node '{n['name']}': that connection is for {rows[0]['provider']}, not {nt.connector}")
        if problems:
            raise PatchError("; ".join(problems), None, problems)

    async def _publish_reference_errors(self, user_id: str, doc: Doc) -> list[str]:
        errs = []
        for n in doc["nodes"]:
            nt = self.registry.get(n["type"])
            if nt and nt.connector and n.get("connection_id"):
                rows = await self.db.select("connections", {"id": n["connection_id"], "user_id": user_id})
                if rows and rows[0].get("status") != "active":
                    errs.append(f"node '{n['name']}': its {nt.connector.replace('_', ' ')} connection needs to be reconnected")
            if n["type"] == "execute_sub_workflow" and n["parameters"].get("workflow_id") \
                    and "{{" not in str(n["parameters"]["workflow_id"]):
                if not await self.db.select("workflows", {"id": n["parameters"]["workflow_id"], "user_id": user_id}):
                    errs.append(f"node '{n['name']}': the sub-workflow does not exist")
        target = (doc.get("settings") or {}).get("error_workflow_id")
        if target and not await self.db.select("workflows", {"id": target, "user_id": user_id}):
            errs.append("the error workflow does not exist")
        return errs
