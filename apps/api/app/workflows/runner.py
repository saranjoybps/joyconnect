"""Execution service: queue, worker loop, approvals, "run from here", "test this node", error workflows.

The queue is the `executions` table. A worker claims one job at a time through the `claim_next_execution` RPC
(`FOR UPDATE SKIP LOCKED`), runs the engine until the run finishes or pauses, and saves the result. Paused runs
(approval, Wait) go back to `waiting`; a decision or the Wait deadline makes them claimable again.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from app.agent.policy import scrub
from app.core.config import Settings
from app.db.client import Database
from app.workflows.engine import Engine, Item, NodeError, Outcome
from app.workflows.registry import MAIN
from app.workflows.schema import document_errors
from app.workflows.service import WorkflowError, WorkflowService

log = logging.getLogger(__name__)
Doc = dict[str, Any]
UNATTENDED = ("schedule", "webhook", "error")


class ExecutionError(Exception):
    def __init__(self, status: int, message: str, **extra: Any):
        super().__init__(message)
        self.status, self.message, self.extra = status, message, extra


class ExecutionService:
    def __init__(self, db: Database, workflows: WorkflowService, engine: Engine, settings: Settings):
        self.db, self.workflows, self.engine, self.settings = db, workflows, engine, settings

    def _now(self) -> datetime:
        return self.engine.svc.now()

    # ------------------------------------------------------------------ starting runs

    async def _document(self, user_id: str, workflow_id: str, mode: str, allow_draft: bool = False) -> Doc:
        try:
            if mode in UNATTENDED and not allow_draft:
                doc = await self.workflows.published_document(user_id, workflow_id)
                if doc is None:
                    raise ExecutionError(409, "Publish this workflow first: schedules and webhooks run the "
                                              "published version.")
                return doc
            return await self.workflows.get(user_id, workflow_id)
        except WorkflowError as exc:
            raise ExecutionError(exc.status, exc.message) from exc

    async def start(self, user_id: str, workflow_id: str, *, mode: str = "manual", trigger_node_id: str | None = None,
                    trigger_data: Any = None, start_node_id: str | None = None,
                    allow_draft: bool = False) -> Doc:
        """Queue a run and return the execution row. A worker picks it up."""
        doc = await self._document(user_id, workflow_id, mode, allow_draft)
        errors = document_errors(doc)
        if errors:
            raise ExecutionError(422, "This workflow has errors: " + "; ".join(errors[:3]))
        try:
            if start_node_id:
                prefill, start_inputs = await self.assemble_inputs(user_id, doc, start_node_id, trigger_data)
                state = self.engine.initial_state(doc, start_node_id=start_node_id, prefill=prefill,
                                                  start_inputs=start_inputs, trigger_data=trigger_data)
            else:
                state = self.engine.initial_state(doc, trigger_node_id=trigger_node_id, trigger_data=trigger_data)
        except NodeError as exc:
            raise ExecutionError(422, exc.message) from exc
        cap = (doc.get("settings") or {}).get("cost_cap_usd")
        return await self.db.insert("executions", {
            "user_id": user_id, "workflow_id": workflow_id, "workflow_version": doc["version"], "mode": mode,
            "status": "queued", "trigger_node_id": (state.get("trigger") or {}).get("node_id") or start_node_id,
            "trigger_data": trigger_data, "state": state,
            "cost_cap_usd": cap if cap is not None else (self.settings.default_run_cost_cap_usd or None)})

    async def assemble_inputs(self, user_id: str, doc: Doc, node_id: str, override: Any = None
                              ) -> tuple[dict[str, dict[str, list[Item]]], dict[str, list[Item]]]:
        """Inputs for starting at `node_id`: what its upstream nodes produced in their latest successful run, or
        their pinned test data. Returns (outputs of upstream nodes, the node's input slots)."""
        node = next((n for n in doc["nodes"] if n["id"] == node_id), None)
        if node is None:
            raise ExecutionError(404, "node not found")
        incoming = [e for e in doc["edges"] if e["to"] == node_id]
        if not incoming:
            from app.workflows.engine import to_items
            return {}, {MAIN: to_items(override)}
        by_id = {n["id"]: n for n in doc["nodes"]}
        prefill: dict[str, dict[str, list[Item]]] = {}
        slots: dict[str, list[Item]] = {}
        missing = []
        for src_id in dict.fromkeys(e["from"] for e in incoming):
            src = by_id[src_id]
            outs = await self._stored_output(doc["id"], src)
            if outs is None:
                missing.append(src["name"])
                continue
            prefill[src_id] = outs
        if missing:
            raise ExecutionError(422, "There is no saved data for " + ", ".join(f"'{m}'" for m in missing) +
                                 ". Run the workflow once, or pin test data on that step.")
        for e in incoming:
            items = prefill[e["from"]].get(e["output"]) or []
            slots.setdefault(e.get("input", MAIN), []).extend(items)
        return prefill, slots

    async def _stored_output(self, workflow_id: str, node: Doc) -> dict[str, list[Item]] | None:
        if node.get("pinned_data"):
            from app.workflows.registry import get_registry
            nt = get_registry().get(node["type"])
            outs = nt.output_names(node["parameters"]) if nt else [MAIN]
            return {(outs or [MAIN])[0]: node["pinned_data"]}
        rows = await self.db.select("node_executions", {"workflow_id": workflow_id, "node_id": node["id"],
                                                        "status": "success"}, order="created_at.desc", limit=1)
        if not rows or not isinstance(rows[0].get("output"), dict):
            return None
        return {k: [i for i in v if isinstance(i, dict) and "json" in i] for k, v in rows[0]["output"].items()}

    # ------------------------------------------------------------------ the worker side

    async def process_one(self, worker_id: str) -> bool:
        """Claim one job and run it. Returns False when there is nothing to do."""
        rows = await self.db.rpc("claim_next_execution", {"p_worker": worker_id,
                                                          "p_lease_seconds": self.settings.worker_lease_seconds})
        if not rows:
            return False
        await self.run_row(rows[0])
        return True

    async def run_row(self, row: Doc) -> Outcome:
        doc: Doc | None = None
        try:
            doc = await self.workflows.version_document(row["user_id"], row["workflow_id"], row["workflow_version"])
            outcome = await self.engine.run(row, doc)
        except WorkflowError as exc:
            outcome = Outcome("error", error={"message": f"workflow unavailable: {exc.message}", "kind": "not_found"})
        except NodeError as exc:
            outcome = Outcome("error", error={"message": scrub(exc.message), "kind": exc.kind})
        except Exception as exc:  # noqa: BLE001 — never lose a job to a bug
            log.exception("execution %s crashed: %s", row["id"], type(exc).__name__)
            outcome = Outcome("error", error={"message": "The run hit an unexpected internal error.", "kind": "internal"})
        await self._finalize(row, doc, outcome)
        return outcome

    async def _finalize(self, row: Doc, doc: Doc | None, outcome: Outcome) -> None:
        now = self._now().isoformat()
        values: Doc = {"status": outcome.status, "locked_by": None, "cost_usd": outcome.cost_usd}
        if outcome.status == "waiting":
            values["resume_at"] = outcome.resume_at.isoformat() if outcome.resume_at else None
        else:
            values["finished_at"] = now
        if outcome.error:
            values["error"] = outcome.error
        response = outcome.response
        if doc is not None and row["mode"] == "webhook" and response is None:
            response = self._default_response(doc, row, outcome)
        if response is not None:
            values["response"] = response
        if outcome.status == "canceled":
            values.pop("status")      # the canceller already set it; do not overwrite
        await self.db.update("executions", {"id": row["id"]}, values)
        if outcome.status == "error" and doc is not None and row["mode"] in ("schedule", "webhook"):
            await self._error_workflow(row, doc, outcome.error or {})

    @staticmethod
    def _default_response(doc: Doc, row: Doc, outcome: Outcome) -> Doc | None:
        trig = next((n for n in doc["nodes"] if n["id"] == row.get("trigger_node_id")), None)
        mode = (trig or {}).get("parameters", {}).get("response_mode", "immediately")
        code = int((trig or {}).get("parameters", {}).get("response_code") or 200)
        if outcome.status == "error":
            return {"status": 500, "body": {"error": "The workflow failed."}}
        if mode == "last_node":
            first = outcome.last_output[0]["json"] if outcome.last_output else {}
            return {"status": code, "body": first}
        return {"status": code, "body": {"message": "Workflow was started"}}

    async def _error_workflow(self, row: Doc, doc: Doc, error: Doc) -> None:
        """Run the workflow named in settings.error_workflow_id (its Error Trigger gets n8n's payload shape)."""
        target = (doc.get("settings") or {}).get("error_workflow_id")
        if not target or target == doc["id"]:
            return
        payload = {"execution": {"id": row["id"], "error": {"message": error.get("message")},
                                 "lastNodeExecuted": error.get("node"), "mode": row["mode"]},
                   "workflow": {"id": doc["id"], "name": doc["name"]}}
        try:
            tdoc = await self.workflows.get(row["user_id"], target)
            trigger = next((n for n in tdoc["nodes"] if n["type"] == "error_trigger"), None)
            if trigger is None:
                log.warning("error workflow %s has no Error Trigger node", target)
                return
            await self.start(row["user_id"], target, mode="error", trigger_node_id=trigger["id"],
                             trigger_data=payload, allow_draft=True)
        except (ExecutionError, WorkflowError) as exc:
            log.warning("could not start error workflow %s: %s", target, getattr(exc, "message", exc))

    # ------------------------------------------------------------------ test a single node

    async def test_node(self, user_id: str, workflow_id: str, node_id: str, input_items: list[Item] | None = None,
                        confirm: bool = False) -> Doc:
        """Run ONE node now, inline, with its upstream data (latest run or pinned) or the items you give.
        Nodes that change data in an app need confirm=True; nothing downstream runs."""
        doc = await self._document(user_id, workflow_id, "manual")
        node = next((n for n in doc["nodes"] if n["id"] == node_id), None)
        if node is None:
            raise ExecutionError(404, "node not found")
        nt = self.engine.svc.registry.get(node["type"])
        if nt is None:
            raise ExecutionError(422, f"unknown node type {node['type']}")
        risk = nt.risk_of(node["parameters"]) if not callable(nt.risk) else "write"
        if callable(nt.risk):
            risk = "read" if str(node["parameters"].get("method", "GET")).upper() in ("GET", "HEAD", "OPTIONS") \
                else "write"
        if risk != "read" and not confirm:
            raise ExecutionError(409, f"{nt.name} changes data in the connected app. Confirm to run it for real.",
                                 requires_confirmation=True, risk=risk)
        try:
            if input_items is not None:
                prefill, start_inputs = {}, {MAIN: input_items}
            else:
                prefill, start_inputs = await self.assemble_inputs(user_id, doc, node_id)
            state = self.engine.initial_state(doc, start_node_id=node_id, prefill=prefill, start_inputs=start_inputs,
                                              only_node=True, approved_nodes=[node_id])
        except NodeError as exc:
            raise ExecutionError(422, exc.message) from exc
        row = await self.db.insert("executions", {
            "user_id": user_id, "workflow_id": workflow_id, "workflow_version": doc["version"], "mode": "test_node",
            "status": "running", "trigger_node_id": node_id, "state": state, "started_at": self._now().isoformat()})
        outcome = await self.run_row(row)
        rows = await self.db.select("node_executions", {"execution_id": row["id"], "node_id": node_id},
                                    order="created_at.desc", limit=1)
        rec = rows[0] if rows else {}
        return {"execution_id": row["id"], "status": outcome.status, "error": outcome.error,
                "output": rec.get("output"), "input": rec.get("input"), "duration_ms": rec.get("duration_ms")}

    # ------------------------------------------------------------------ approvals, cancel, reads

    async def decide_approval(self, user_id: str, approval_id: str, approve: bool) -> Doc:
        rows = await self.db.select("execution_approvals", {"id": approval_id, "user_id": user_id})
        if not rows:
            raise ExecutionError(404, "approval not found")
        a = rows[0]
        if a["status"] != "pending":
            raise ExecutionError(409, f"this approval is already {a['status']}")
        created = a.get("created_at")
        if created and self._now() - datetime.fromisoformat(str(created).replace("Z", "+00:00")) > timedelta(
                hours=self.settings.approval_ttl_hours):
            await self._expire(a)
            raise ExecutionError(410, "This approval expired.")
        won = await self.db.update("execution_approvals", {"id": approval_id, "status": "pending"},
                                   {"status": "approved" if approve else "rejected",
                                    "decided_at": self._now().isoformat()})
        if not won:
            raise ExecutionError(409, "this approval was already decided")
        ex = (await self.db.select("executions", {"id": a["execution_id"]}))[0]
        state = ex["state"]
        if state.get("waiting") and state["waiting"].get("approval_id") == approval_id:
            state["waiting"]["decision"] = "approved" if approve else "rejected"
            await self.db.update("executions", {"id": ex["id"], "status": "waiting"},
                                 {"state": state, "status": "queued", "resume_at": None})
        return {"execution_id": ex["id"], "decision": "approved" if approve else "rejected", "status": "queued"}

    async def _expire(self, a: Doc) -> None:
        await self.db.update("execution_approvals", {"id": a["id"], "status": "pending"}, {"status": "expired"})
        await self.db.update("executions", {"id": a["execution_id"], "status": "waiting"}, {
            "status": "error", "finished_at": self._now().isoformat(),
            "error": {"message": "The approval expired before anyone answered.", "kind": "approval"}})

    async def expire_stale_approvals(self) -> int:
        cutoff = self._now() - timedelta(hours=self.settings.approval_ttl_hours)
        n = 0
        for a in await self.db.select("execution_approvals", {"status": "pending"}):
            if datetime.fromisoformat(str(a["created_at"]).replace("Z", "+00:00")) < cutoff:
                await self._expire(a)
                n += 1
        return n

    async def cancel(self, user_id: str, execution_id: str) -> Doc:
        rows = await self.db.select("executions", {"id": execution_id, "user_id": user_id})
        if not rows:
            raise ExecutionError(404, "execution not found")
        if rows[0]["status"] not in ("queued", "waiting", "running"):
            raise ExecutionError(409, f"this run already {rows[0]['status']}")
        await self.db.update("executions", {"id": execution_id}, {"status": "canceled",
                                                                  "finished_at": self._now().isoformat()})
        for a in await self.db.select("execution_approvals", {"execution_id": execution_id, "status": "pending"}):
            await self.db.update("execution_approvals", {"id": a["id"]}, {"status": "expired"})
        return {"execution_id": execution_id, "status": "canceled"}

    @staticmethod
    def _public(row: Doc) -> Doc:
        return {k: v for k, v in row.items() if k not in ("state", "locked_by", "locked_at", "trigger_data")}

    async def get(self, user_id: str, execution_id: str) -> Doc:
        rows = await self.db.select("executions", {"id": execution_id, "user_id": user_id})
        if not rows:
            raise ExecutionError(404, "execution not found")
        nodes = await self.db.select("node_executions", {"execution_id": execution_id, "user_id": user_id},
                                     order="created_at.asc")
        approvals = [a for a in await self.db.select("execution_approvals", {"execution_id": execution_id,
                                                                              "user_id": user_id})
                     if a["status"] == "pending"]
        return {"execution": self._public(rows[0]), "nodes": nodes,
                "pending_approvals": [{"approval_id": a["id"], **a["preview"]} for a in approvals]}

    async def list(self, user_id: str, workflow_id: str | None = None, status: str | None = None,
                   limit: int = 50) -> list[Doc]:
        filters: Doc = {"user_id": user_id}
        if workflow_id:
            filters["workflow_id"] = workflow_id
        if status:
            filters["status"] = status
        rows = await self.db.select("executions", filters, order="created_at.desc", limit=limit)
        return [self._public(r) for r in rows]

    async def pending_approvals(self, user_id: str) -> list[Doc]:
        rows = await self.db.select("execution_approvals", {"user_id": user_id, "status": "pending"},
                                    order="created_at.desc")
        return [{"approval_id": a["id"], "created_at": a["created_at"], **a["preview"]} for a in rows]
