"""Execution engine: runs a workflow document item by item, node by node.

Data between nodes is a list of items (`{"json": {...}}`). The whole run state is plain JSON (`executions.state`)
and is saved after every node, so a run can pause (approval, Wait) and resume in any worker, and a crashed worker's
job can be picked up again.

Scheduling (n8n-style, no cycles except through Loop Over Items):
  * a node runs when data has been delivered to it;
  * a Merge waits until every connected input has data or its source has finished without any;
  * a node whose upstream finished without sending it data is skipped, and that is propagated downstream;
  * when the queue empties while a loop still has batches in flight, the loop is resumed with no returned items.

Approvals: a node whose risk is write or destructive pauses the run for approval unless the workflow's
`auto_approve` setting covers it (writes: "writes" or "all"; destructive: only "all").
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from app.agent.policy import redact_args, redact_result, scrub
from app.connectors.base import Risk
from app.core.config import Settings
from app.db.client import Database
from app.workflows.conditions import ConditionError
from app.workflows.expressions import ExprContext, ExpressionError, resolve
from app.workflows.registry import MAIN, NodeRegistry, NodeType, get_registry

log = logging.getLogger(__name__)
Doc = dict[str, Any]
Item = dict[str, Any]

MAX_STATE_BYTES = 8_000_000
RECORD_MAX_ITEMS = 100


async def _sleep(seconds: float) -> None:     # module-level so tests can replace it
    await asyncio.sleep(seconds)


class NodeError(Exception):
    def __init__(self, message: str, kind: str = "other", retryable: bool = False, details: Any = None):
        super().__init__(message)
        self.message, self.kind, self.retryable, self.details = message, kind, retryable, details


@dataclass
class NodeResult:
    outputs: dict[str, list[Item]]
    wait_until: datetime | None = None          # Wait node: pause the run until then
    response: dict[str, Any] | None = None      # Respond to Webhook


@dataclass
class Outcome:
    status: str                                 # success | error | waiting | canceled
    error: dict[str, Any] | None = None
    response: dict[str, Any] | None = None
    resume_at: datetime | None = None
    last_output: list[Item] = field(default_factory=list)
    cost_usd: float = 0.0


@dataclass
class EngineServices:
    db: Database
    settings: Settings
    http: Any                                   # httpx.AsyncClient
    executor: Any                               # app.agent.tools.ToolExecutor
    workflows: Any = None                       # WorkflowService (sub-workflows)
    registry: NodeRegistry = field(default_factory=get_registry)
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)
    llm_factory: Callable[[], Any] | None = None
    engine: Any = None                          # set by Engine(); sub-workflow nodes call back into it


def auto_decision(risk: Risk, mode: str) -> str:
    """'run' or 'ask' for a node of this risk under the workflow's auto_approve mode (off | writes | all)."""
    if risk == "read" or mode == "all":
        return "run"
    return "run" if risk == "write" and mode == "writes" else "ask"


def clip_items(items: list[Item]) -> Any:
    shown = [redact_result(i) for i in items[:RECORD_MAX_ITEMS]]
    return shown + [{"_truncated": f"+{len(items) - RECORD_MAX_ITEMS} more items"}] if len(items) > RECORD_MAX_ITEMS \
        else shown


class RunCtx:
    """Everything one run shares: who, what, and where the data is."""

    def __init__(self, svc: EngineServices, row: Doc, doc: Doc, state: Doc, depth: int = 0):
        self.svc, self.row, self.doc, self.state, self.depth = svc, row, doc, state, depth
        self.user_id = row["user_id"]
        self.by_id = {n["id"]: n for n in doc["nodes"]}
        self.by_name = {n["name"]: n for n in doc["nodes"]}
        self.incoming: dict[str, list[Doc]] = {}
        self.outgoing: dict[str, list[Doc]] = {}
        for e in doc["edges"]:
            self.incoming.setdefault(e["to"], []).append(e)
            self.outgoing.setdefault(e["from"], []).append(e)
        self.settings = doc.get("settings") or {}
        self.auto_approve = self.settings.get("auto_approve", "off")

    def node_items(self, name: str) -> list[Item] | None:
        """Output items of a node by name (first non-empty output); None if it has not run."""
        node = self.by_name.get(name)
        if node is None or node["id"] not in self.state["outputs"]:
            return None
        outs = self.state["outputs"][node["id"]]
        for items in outs.values():
            if items:
                return items
        return []

    def add_cost(self, usd: float) -> None:
        self.state["cost_usd"] = round(self.state.get("cost_usd", 0.0) + usd, 6)


class NodeCtx:
    def __init__(self, run: RunCtx, node: Doc, nt: NodeType, inputs: dict[str, list[Item]], resumed: bool,
                 approved: bool):
        self.run, self.node, self.nt, self.inputs = run, node, nt, inputs
        self.resumed, self.approved = resumed, approved
        self.state: Doc = run.state["node_state"].setdefault(node["id"], {})
        self.params: Doc = node["parameters"]

    @property
    def items(self) -> list[Item]:
        if MAIN in self.inputs:
            return self.inputs[MAIN]
        return [i for items in self.inputs.values() for i in items]

    def expr_ctx(self, index: int = 0, items: list[Item] | None = None) -> ExprContext:
        r = self.run
        return ExprContext(
            items=self.items if items is None else items, index=index, nodes=r.node_items,
            execution={"id": r.row["id"], "mode": r.row["mode"]}, workflow={"id": r.doc["id"], "name": r.doc["name"]},
            now=r.svc.now().isoformat(timespec="seconds"))

    def eval(self, value: Any, index: int = 0, items: list[Item] | None = None) -> Any:
        return resolve(value, self.expr_ctx(index, items))

    def param(self, name: str, index: int = 0, default: Any = None) -> Any:
        v = self.params.get(name, default)
        return default if v is None else self.eval(v, index)

    def add_cost(self, usd: float) -> None:
        self.run.add_cost(usd)

    @property
    def svc(self) -> EngineServices:
        return self.run.svc


def new_state() -> Doc:
    return {"outputs": {}, "inputs": {}, "queue": [], "done": [], "run_counts": {}, "node_state": {}, "waiting": None,
            "steps": 0, "cost_usd": 0.0, "response": None, "last_output": [], "approved_nodes": [],
            "only_node": False, "trigger": None, "failed": None}


def to_items(data: Any) -> list[Item]:
    if data is None:
        return [{"json": {}}]
    if isinstance(data, list):
        return [d if isinstance(d, dict) and "json" in d else {"json": d if isinstance(d, dict) else {"value": d}}
                for d in data] or []
    return [data if isinstance(data, dict) and set(data) == {"json"} else {"json": data if isinstance(data, dict)
                                                                              else {"value": data}}]


class Engine:
    def __init__(self, svc: EngineServices):
        self.svc = svc
        svc.engine = self

    # ------------------------------------------------------------------ preparing a run

    def find_start(self, doc: Doc, trigger_node_id: str | None) -> str:
        reg = self.svc.registry
        if trigger_node_id:
            if not any(n["id"] == trigger_node_id for n in doc["nodes"]):
                raise NodeError(f"trigger node {trigger_node_id} does not exist")
            return trigger_node_id
        triggers = [n for n in doc["nodes"] if (reg.get(n["type"]) and reg.get(n["type"]).is_trigger)
                    and not n.get("disabled")]
        manual = [n for n in triggers if n["type"] == "manual_trigger"]
        if manual or triggers:
            return (manual or triggers)[0]["id"]
        targets = {e["to"] for e in doc["edges"]}
        roots = [n for n in doc["nodes"] if n["id"] not in targets]
        if not roots:
            raise NodeError("this workflow has no node to start from")
        return roots[0]["id"]

    def initial_state(self, doc: Doc, *, trigger_node_id: str | None = None, trigger_data: Any = None,
                      start_node_id: str | None = None, prefill: dict[str, dict[str, list[Item]]] | None = None,
                      start_inputs: dict[str, list[Item]] | None = None, only_node: bool = False,
                      approved_nodes: list[str] | None = None) -> Doc:
        st = new_state()
        if start_node_id:
            st["outputs"] = {k: v for k, v in (prefill or {}).items()}
            st["done"] = list(st["outputs"])
            st["inputs"][start_node_id] = start_inputs or {MAIN: to_items(trigger_data)}
            st["queue"] = [start_node_id]
        else:
            start = self.find_start(doc, trigger_node_id)
            st["trigger"] = {"node_id": start}
            st["inputs"][start] = {MAIN: to_items(trigger_data)}
            st["queue"] = [start]
        st["only_node"], st["approved_nodes"] = only_node, list(approved_nodes or [])
        return st

    # ------------------------------------------------------------------ running

    async def run(self, row: Doc, doc: Doc, depth: int = 0) -> Outcome:
        """Run (or resume) an execution until it finishes, fails, or pauses. Persists state after every node."""
        st = row.get("state") or new_state()
        if not st.get("queue") and not st.get("waiting") and not st.get("outputs"):
            st = self.initial_state(doc, trigger_node_id=row.get("trigger_node_id"), trigger_data=row.get("trigger_data"))
        for key, default in new_state().items():
            st.setdefault(key, default)
        run = RunCtx(self.svc, row, doc, st, depth)
        started = self.svc.now()
        timeout = int(run.settings.get("timeout_seconds") or self.svc.settings.workflow_timeout_seconds)
        cap = run.settings.get("cost_cap_usd")
        if cap is None:
            cap = row.get("cost_cap_usd")
        if cap is None:
            cap = self.svc.settings.default_run_cost_cap_usd or None

        resume = st["waiting"]
        if resume:
            if resume["kind"] == "approval" and resume.get("decision") is None:
                return Outcome("waiting", cost_usd=st["cost_usd"])
            st["waiting"] = None
            outcome = await self._step(run, resume["node_id"], resume["inputs"], resumed=True,
                                       decision=resume.get("decision"))
            if outcome:
                return outcome

        while True:
            if not st["queue"]:
                if not self._resume_stalled_loop(run):
                    break
            if st["steps"] >= self.svc.settings.workflow_max_node_runs:
                return await self._finish_error(run, None, NodeError(
                    f"stopped after {st['steps']} node runs (is there an endless loop?)", "limit"))
            if (self.svc.now() - started).total_seconds() > timeout:
                return await self._finish_error(run, None, NodeError(f"the run took longer than {timeout}s", "timeout"))
            if cap is not None and st["cost_usd"] > float(cap):
                return await self._finish_error(run, None, NodeError(
                    f"stopped: the run's cost ${st['cost_usd']:.4f} passed the cap of ${float(cap):.4f}", "cost_cap"))
            if await self._canceled(row):
                return Outcome("canceled", cost_usd=st["cost_usd"])
            node_id = st["queue"].pop(0)
            inputs = st["inputs"].pop(node_id, {})
            outcome = await self._step(run, node_id, inputs)
            if outcome:
                return outcome
        return Outcome("success", response=st.get("response"), last_output=st.get("last_output") or [],
                       cost_usd=st["cost_usd"])

    async def _canceled(self, row: Doc) -> bool:
        rows = await self.svc.db.select("executions", {"id": row["id"]})
        return bool(rows) and rows[0]["status"] == "canceled"

    # ------------------------------------------------------------------ one node

    async def _step(self, run: RunCtx, node_id: str, inputs: dict[str, list[Item]], resumed: bool = False,
                    decision: str | None = None) -> Outcome | None:
        """Returns an Outcome when the run must stop here (paused or failed), else None."""
        st, node = run.state, run.by_id[node_id]
        nt = self.svc.registry.get(node["type"])
        name = node["name"]
        started = self.svc.now()
        run_index = st["run_counts"].get(node_id, 0)

        if nt is None:
            return await self._finish_error(run, node, NodeError(f"unknown node type '{node['type']}'"))

        if node.get("disabled"):
            return await self._complete(run, node, nt, inputs, {MAIN: inputs.get(MAIN, [])}, "skipped", started, 0)

        if run.row["mode"] in ("manual", "test_node") and node.get("pinned_data"):
            out_name = nt.output_names(node["parameters"])[0] if nt.output_names(node["parameters"]) else MAIN
            return await self._complete(run, node, nt, inputs, {out_name: node["pinned_data"]}, "pinned", started, 0)

        ctx = NodeCtx(run, node, nt, inputs, resumed, approved=decision == "approved")

        if decision == "rejected":
            return await self._failed(run, node, nt, inputs, NodeError("You declined this action.", "declined"),
                                      started, 1)

        # ---- approval gate for write / destructive nodes
        try:
            risk = self._risk(ctx)
        except (ExpressionError, ConditionError) as exc:
            return await self._failed(run, node, nt, inputs, NodeError(f"expression error: {exc}", "expression"),
                                      started, 1)
        if risk != "read" and decision != "approved" and node_id not in st["approved_nodes"] \
                and auto_decision(risk, run.auto_approve) == "ask":
            if run.depth > 0:
                return await self._failed(run, node, nt, inputs, NodeError(
                    "This step needs approval, which sub-workflows cannot ask for yet. Turn on auto-approve for "
                    "this workflow or run the step outside a sub-workflow.", "approval"), started, 1)
            return await self._pause_for_approval(run, node, nt, inputs, risk, started)

        # ---- run with timeout and (for reads only) retries
        s = node.get("settings") or {}
        attempts = int(s.get("max_tries", 3)) if s.get("retry_on_fail") and risk == "read" else 1
        timeout = (s.get("timeout_ms") or self.svc.settings.node_timeout_seconds * 1000) / 1000
        from app.workflows.handlers import HANDLERS      # deferred: handlers import this module

        handler = HANDLERS.get(node["type"]) or (HANDLERS["__app__"] if nt.connector else None)
        if handler is None:
            return await self._failed(run, node, nt, inputs, NodeError(f"{nt.name} cannot run yet."), started, 1)
        result: NodeResult | None = None
        err: NodeError | None = None
        tries = 0
        for tries in range(1, attempts + 1):
            try:
                result = await asyncio.wait_for(handler(ctx), timeout)
                err = None
                break
            except asyncio.TimeoutError:
                err = NodeError(f"{nt.name} timed out after {timeout:g}s", "timeout", retryable=True)
            except NodeError as exc:
                err = exc
            except (ExpressionError, ConditionError) as exc:
                err = NodeError(f"{'expression' if isinstance(exc, ExpressionError) else 'condition'} error: {exc}",
                                "expression")
            except Exception as exc:  # noqa: BLE001 — a node must never crash the worker
                log.exception("node %s (%s) crashed: %s", name, node["type"], type(exc).__name__)
                err = NodeError(f"{nt.name} hit an unexpected error ({type(exc).__name__}).", "internal")
            if err is None or not err.retryable or tries >= attempts:
                break
            await _sleep((s.get("wait_between_ms") or 0) / 1000)
        if err is not None or result is None:
            return await self._failed(run, node, nt, inputs, err or NodeError("no result"), started, tries)

        if result.response is not None:
            st["response"] = result.response
        if result.wait_until is not None:
            st["waiting"] = {"kind": "wait", "node_id": node["id"], "inputs": inputs}
            await self._save(run, resume_at=result.wait_until)
            return Outcome("waiting", resume_at=result.wait_until, cost_usd=st["cost_usd"])
        return await self._complete(run, node, nt, inputs, result.outputs, "success", started, tries)

    def _risk(self, ctx: NodeCtx) -> Risk:
        nt = ctx.nt
        if not callable(nt.risk):
            return nt.risk
        return nt.risk_of({k: ctx.eval(v, 0) for k, v in ctx.params.items()})

    async def _pause_for_approval(self, run: RunCtx, node: Doc, nt: NodeType, inputs: dict[str, list[Item]],
                                  risk: Risk, started: datetime) -> Outcome:
        st = run.state
        ctx = NodeCtx(run, node, nt, inputs, False, False)
        try:
            args = {k: ctx.eval(v, 0) for k, v in node["parameters"].items()}
        except (ExpressionError, ConditionError):
            args = dict(node["parameters"])        # show the raw expressions
        count = len(ctx.items)
        preview = {
            "workflow_id": run.doc["id"], "execution_id": run.row["id"], "node_id": node["id"],
            "node_name": node["name"], "tool": nt.type, "connector_name": nt.name, "risk": risk,
            "description": nt.description[:200], "items": count, "args": redact_args(args),
            "account": None,
        }
        approval = await self.svc.db.insert("execution_approvals", {
            "user_id": run.user_id, "execution_id": run.row["id"], "node_id": node["id"], "preview": preview,
            "status": "pending"})
        st["waiting"] = {"kind": "approval", "node_id": node["id"], "inputs": inputs, "approval_id": approval["id"],
                         "decision": None}
        await self.svc.db.insert("node_executions", self._record(run, node, nt, 0, "waiting", inputs, None, None,
                                                                 started, 0))
        st["run_counts"][node["id"]] = st["run_counts"].get(node["id"], 0)   # the real run counts when it runs
        await self._save(run)
        return Outcome("waiting", cost_usd=st["cost_usd"])

    # ------------------------------------------------------------------ results

    def _record(self, run: RunCtx, node: Doc, nt: NodeType, tries: int, status: str, inputs, outputs, error,
                started: datetime, duration_ms: int) -> Doc:
        return {
            "execution_id": run.row["id"], "user_id": run.user_id, "workflow_id": run.doc["id"],
            "node_id": node["id"], "node_name": node["name"], "node_type": nt.type,
            "run_index": run.state["run_counts"].get(node["id"], 0), "status": status,
            "input": {k: clip_items(v) for k, v in (inputs or {}).items()},
            "output": None if outputs is None else {k: clip_items(v) for k, v in outputs.items()},
            "error": error, "attempts": max(tries, 1), "started_at": started.isoformat(),
            "finished_at": self.svc.now().isoformat(), "duration_ms": duration_ms,
        }

    async def _complete(self, run: RunCtx, node: Doc, nt: NodeType, inputs, outputs: dict[str, list[Item]],
                        status: str, started: datetime, tries: int) -> Outcome | None:
        st = run.state
        duration = int((self.svc.now() - started).total_seconds() * 1000)
        await self.svc.db.insert("node_executions", self._record(run, node, nt, tries, status, inputs, outputs, None,
                                                                 started, duration))
        st["steps"] += 1
        st["run_counts"][node["id"]] = st["run_counts"].get(node["id"], 0) + 1
        st["outputs"][node["id"]] = outputs
        flat = next((v for v in outputs.values() if v), [])
        st["last_output"] = flat
        self._deliver(run, node, outputs)
        await self._save(run)
        return None

    async def _failed(self, run: RunCtx, node: Doc, nt: NodeType, inputs, err: NodeError, started: datetime,
                      tries: int) -> Outcome | None:
        st = run.state
        duration = int((self.svc.now() - started).total_seconds() * 1000)
        error = {"message": scrub(err.message), "kind": err.kind, "node": node["name"]}
        await self.svc.db.insert("node_executions", self._record(run, node, nt, tries, "error", inputs, None, error,
                                                                 started, duration))
        st["steps"] += 1
        st["run_counts"][node["id"]] = st["run_counts"].get(node["id"], 0) + 1
        if (node.get("settings") or {}).get("on_error") == "continue":
            outs = nt.output_names(node["parameters"]) or [MAIN]
            payload = [{"json": {"error": error}}]
            st["outputs"][node["id"]] = {outs[0]: payload}
            st["last_output"] = payload
            self._deliver(run, node, {outs[0]: payload})
            await self._save(run)
            return None
        return await self._finish_error(run, node, err, recorded=True)

    async def _finish_error(self, run: RunCtx, node: Doc | None, err: NodeError, recorded: bool = False) -> Outcome:
        st = run.state
        error = {"message": scrub(err.message), "kind": err.kind, "node": node["name"] if node else None,
                 "node_id": node["id"] if node else None}
        if err.details is not None:
            error["details"] = err.details
        st["failed"] = error
        await self._save(run)
        return Outcome("error", error=error, cost_usd=st["cost_usd"])

    # ------------------------------------------------------------------ data flow

    def _deliver(self, run: RunCtx, node: Doc, outputs: dict[str, list[Item]]) -> None:
        st = run.state
        if node["id"] not in st["done"]:
            st["done"].append(node["id"])
        if st["only_node"]:
            return
        targets: list[str] = []
        for e in run.outgoing.get(node["id"], []):
            items = outputs.get(e["output"]) or []
            if items:
                slot = st["inputs"].setdefault(e["to"], {}).setdefault(e.get("input", MAIN), [])
                slot.extend(items)
            if e["to"] not in targets:
                targets.append(e["to"])
        for t in targets:
            self._consider(run, t)

    def _consider(self, run: RunCtx, target: str) -> None:
        """Decide whether `target` can run now, must keep waiting, or can be skipped."""
        st = run.state
        if target in st["queue"]:
            return
        node = run.by_id[target]
        nt = self.svc.registry.get(node["type"])
        pending = st["inputs"].get(target, {})
        has_data = any(pending.values())
        incoming = run.incoming.get(target, [])
        done = set(st["done"])
        if nt is not None and nt.wait_for_all_inputs:
            settled = True
            for inp in {e.get("input", MAIN) for e in incoming}:
                srcs = [e["from"] for e in incoming if e.get("input", MAIN) == inp]
                if not pending.get(inp) and not all(s in done for s in srcs):
                    settled = False
            if not settled:
                return
        if has_data:
            st["queue"].append(target)
        elif target not in done and all(e["from"] in done for e in incoming):
            self._skip(run, target)

    def _skip(self, run: RunCtx, node_id: str) -> None:
        """Nothing will ever reach this node: mark it done and let its downstream nodes decide."""
        st = run.state
        if node_id in st["done"]:
            return
        st["done"].append(node_id)
        st["outputs"].setdefault(node_id, {})
        for t in dict.fromkeys(e["to"] for e in run.outgoing.get(node_id, [])):
            self._consider(run, t)

    def _resume_stalled_loop(self, run: RunCtx) -> bool:
        """The queue is empty but a loop still has batches to hand out (its body returned no items)."""
        st = run.state
        for node_id, ns in st["node_state"].items():
            if ns.get("loop_started"):
                st["inputs"][node_id] = {MAIN: []}
                st["queue"].append(node_id)
                return True
        return False

    async def _save(self, run: RunCtx, resume_at: datetime | None = None) -> None:
        st = run.state
        if len(json.dumps(st, default=str)) > MAX_STATE_BYTES:
            raise NodeError("the run's data is too large; limit or aggregate the items", "limit")
        values: Doc = {"state": st, "cost_usd": st["cost_usd"], "locked_at": self.svc.now().isoformat()}
        if resume_at is not None:
            values["resume_at"] = resume_at.isoformat()
        await self.svc.db.update("executions", {"id": run.row["id"]}, values)

    # ------------------------------------------------------------------ sub-workflows

    async def run_nested(self, parent: RunCtx, workflow_id: str, items: list[Item]) -> list[Item]:
        if parent.depth >= self.svc.settings.max_subworkflow_depth:
            raise NodeError("sub-workflows are nested too deeply", "limit")
        if self.svc.workflows is None:
            raise NodeError("sub-workflows are not available here")
        from app.workflows.service import WorkflowError

        try:
            doc = await self.svc.workflows.published_document(parent.user_id, workflow_id) \
                or await self.svc.workflows.get(parent.user_id, workflow_id)
        except WorkflowError as exc:
            raise NodeError(f"sub-workflow not found ({exc.message})", "not_found") from exc
        if doc["id"] == parent.doc["id"]:
            raise NodeError("a workflow cannot call itself", "invalid")
        trigger = self.find_start(doc, None)
        state = self.initial_state(doc, trigger_node_id=trigger, trigger_data=items)
        row = await self.svc.db.insert("executions", {
            "user_id": parent.user_id, "workflow_id": workflow_id, "workflow_version": doc["version"],
            "mode": "sub_workflow", "status": "running", "state": state, "parent_execution_id": parent.row["id"],
            "trigger_node_id": trigger})
        outcome = await self.run(row, doc, depth=parent.depth + 1)
        await self.svc.db.update("executions", {"id": row["id"]}, {
            "status": outcome.status, "error": outcome.error, "finished_at": self.svc.now().isoformat()})
        parent.add_cost(outcome.cost_usd)
        if outcome.status != "success":
            msg = (outcome.error or {}).get("message", outcome.status)
            raise NodeError(f"sub-workflow failed: {msg}", "sub_workflow")
        return outcome.last_output


def new_id() -> str:
    return uuid.uuid4().hex
