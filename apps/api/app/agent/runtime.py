"""Agent runtime: OpenAI tool-calling loop with approvals and auditing.

Events yielded (sent as SSE): token, tool_call, approval_required, tool_result, error, done.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator, Callable

import httpx

from app.agent.llm import LLM, LLMError, LLMResult
from app.agent.policy import build_preview, decide, redact_args, tool_label
from app.agent.prompts import system_prompt
from app.agent.tools import MAX_RESULT_CHARS, BoundTool, ToolExecutor, available_tools, to_openai_tool, validate_args
from app.connectors.registry import get_manifest
from app.core.config import Settings
from app.core.secrets import SecretStore
from app.db.client import Database

log = logging.getLogger(__name__)
Event = dict[str, Any]
HISTORY_LIMIT = 40
DECLINED = {"error": "The user declined this action."}


class AgentError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _ev(event: str, **data: Any) -> Event:
    return {"event": event, "data": data}


def _result_text(result: Any) -> str:
    text = json.dumps(result, default=str, ensure_ascii=False)
    return text if len(text) <= MAX_RESULT_CHARS else text[:MAX_RESULT_CHARS] + '…"(truncated)"'


def _summary(ok: bool, result: Any) -> str:
    if not ok and isinstance(result, dict):
        return str(result.get("error", "error"))[:200]
    return _result_text(result)[:200]


class AgentRuntime:
    def __init__(self, db: Database, store: SecretStore, http: httpx.AsyncClient, settings: Settings,
                 llm_factory: Callable[[], LLM]):
        self.db, self.settings = db, settings
        self.executor = ToolExecutor(db, store, http, settings)
        self._llm_factory = llm_factory

    # ------------------------------------------------------------------ public entry points

    async def chat(self, user_id: str, conversation_id: str | None, text: str) -> AsyncIterator[Event]:
        if conversation_id:
            if not await self.db.select("conversations", {"id": conversation_id, "user_id": user_id}):
                raise AgentError(404, "conversation not found")
        else:
            conv = await self.db.insert("conversations", {"user_id": user_id, "title": text.strip()[:60]})
            conversation_id = conv["id"]
        if await self._pending_approvals(user_id, conversation_id):
            raise AgentError(409, "Approve or reject the pending action first.")
        await self._save_message(user_id, conversation_id, "user", content=text)
        async for ev in self._loop(user_id, conversation_id, text):
            yield ev

    async def decide_approval(self, user_id: str, approval_id: str, approve: bool) -> AsyncIterator[Event]:
        rows = await self.db.select("approvals", {"id": approval_id, "user_id": user_id})
        if not rows:
            raise AgentError(404, "approval not found")
        approval = rows[0]
        if approval["status"] != "pending":
            raise AgentError(409, f"approval already {approval['status']}")
        preview = approval["preview"]
        conversation_id = preview["conversation_id"]

        created = approval.get("created_at")
        if created and datetime.now(timezone.utc) - datetime.fromisoformat(str(created).replace("Z", "+00:00")) \
                > timedelta(hours=self.settings.approval_ttl_hours):
            await self.db.update("approvals", {"id": approval_id}, {"status": "expired"})
            await self._finish_call(user_id, conversation_id, approval["tool_run_id"], preview["tool_call_id"],
                                    False, {"error": "The approval expired."}, "rejected")
            raise AgentError(410, "approval expired")

        # Conditional update makes double-submits safe: only one caller wins.
        now = datetime.now(timezone.utc).isoformat()
        won = await self.db.update("approvals", {"id": approval_id, "status": "pending"},
                                   {"status": "approved" if approve else "rejected", "decided_at": now})
        if not won:
            raise AgentError(409, "approval already decided")

        tool_call_id = preview["tool_call_id"]
        if not approve:
            await self._finish_call(user_id, conversation_id, approval["tool_run_id"], tool_call_id,
                                    False, DECLINED, "rejected")
            yield _ev("tool_result", id=tool_call_id, tool=preview["tool"], ok=False, summary="Declined by you")
        else:
            await self.db.update("tool_runs", {"id": approval["tool_run_id"]}, {"status": "approved"})
            bound = await self._bind(user_id, preview["tool"])
            args = await self._call_args(conversation_id, tool_call_id)
            if bound is None or args is None:
                ok, result = False, {"error": "This app is no longer connected."}
            else:
                yield self._tool_call_event(tool_call_id, bound)
                ok, result = await self.executor.execute(bound, args)
            await self._finish_call(user_id, conversation_id, approval["tool_run_id"], tool_call_id, ok, result,
                                    "ok" if ok else "error")
            yield _ev("tool_result", id=tool_call_id, tool=preview["tool"], ok=ok, summary=_summary(ok, result))

        if await self._pending_approvals(user_id, conversation_id):
            yield _ev("done", conversation_id=conversation_id)
            return
        async for ev in self._loop(user_id, conversation_id, ""):
            yield ev

    # ------------------------------------------------------------------ loop

    async def _loop(self, user_id: str, conversation_id: str, latest_text: str) -> AsyncIterator[Event]:
        try:
            llm = self._llm_factory()
        except LLMError as exc:
            yield _ev("error", message=f"The assistant is not configured: {exc}")
            yield _ev("done", conversation_id=conversation_id)
            return

        for _step in range(self.settings.max_tool_steps):
            tools = await available_tools(self.db, user_id, latest_text, self.settings.max_tools_per_request)
            messages = await self._history(conversation_id, tools)
            result: LLMResult | None = None
            try:
                async for part in llm.stream(messages, [to_openai_tool(b.tool) for b in tools.values()]):
                    if isinstance(part, LLMResult):
                        result = part
                    else:
                        yield _ev("token", text=part)
            except LLMError as exc:
                log.warning("LLM call failed: %s", exc)
                yield _ev("error", message="The assistant is unavailable right now. Please try again.")
                yield _ev("done", conversation_id=conversation_id)
                return
            assert result is not None

            await self._save_message(user_id, conversation_id, "assistant", content=result.content or None,
                                     tool_calls=result.tool_calls or None)
            if not result.tool_calls:
                yield _ev("done", conversation_id=conversation_id)
                return

            paused = False
            for call in result.tool_calls:
                async for ev in self._handle_call(user_id, conversation_id, call, tools):
                    paused = paused or ev["event"] == "approval_required"
                    yield ev
            if paused:
                yield _ev("done", conversation_id=conversation_id)
                return

        note = f"I stopped after {self.settings.max_tool_steps} steps. Tell me how you'd like to continue."
        await self._save_message(user_id, conversation_id, "assistant", content=note)
        yield _ev("token", text=note)
        yield _ev("done", conversation_id=conversation_id)

    def _tool_call_event(self, call_id: str, bound: BoundTool) -> Event:
        return _ev("tool_call", id=call_id, tool=bound.tool.name, connector=bound.manifest.id,
                   connector_name=bound.manifest.name, risk=bound.tool.risk, label=tool_label(bound.tool))

    async def _handle_call(self, user_id: str, conversation_id: str, call: dict[str, Any],
                           tools: dict[str, BoundTool]) -> AsyncIterator[Event]:
        call_id, name = call["id"], call["function"]["name"]
        bound = tools.get(name)
        try:
            args = json.loads(call["function"]["arguments"] or "{}")
        except json.JSONDecodeError:
            args = None

        problem = None
        if bound is None:
            problem = f"Unknown or unavailable tool: {name}"
        elif args is None:
            problem = "Tool arguments were not valid JSON."
        else:
            problem = validate_args(bound.tool, args)
        if problem:
            await self._save_message(user_id, conversation_id, "tool", content=_result_text({"error": problem}),
                                     tool_call_id=call_id)
            yield _ev("tool_result", id=call_id, tool=name, ok=False, summary=problem)
            return

        run = await self.db.insert("tool_runs", {
            "user_id": user_id, "conversation_id": conversation_id, "connection_id": bound.connection["id"],
            "tool": name, "args_redacted": redact_args(args), "status": "pending",
        })

        if decide(bound.tool.risk, bool(bound.connection.get("auto_approve_writes"))) == "ask":
            preview = build_preview(bound.manifest, bound.tool, args, tool_call_id=call_id,
                                    conversation_id=conversation_id,
                                    account_label=bound.connection.get("account_label"))
            approval = await self.db.insert("approvals", {
                "user_id": user_id, "tool_run_id": run["id"], "preview": preview, "status": "pending"})
            yield _ev("approval_required", approval_id=approval["id"], **preview)
            return

        yield self._tool_call_event(call_id, bound)
        ok, result = await self.executor.execute(bound, args)
        await self._finish_call(user_id, conversation_id, run["id"], call_id, ok, result, "ok" if ok else "error")
        yield _ev("tool_result", id=call_id, tool=name, ok=ok, summary=_summary(ok, result))

    # ------------------------------------------------------------------ persistence helpers

    async def _finish_call(self, user_id, conversation_id, run_id, call_id, ok, result, status) -> None:
        await self.db.update("tool_runs", {"id": run_id}, {"status": status, "result_summary": _summary(ok, result)})
        await self._save_message(user_id, conversation_id, "tool", content=_result_text(result), tool_call_id=call_id)

    async def _save_message(self, user_id, conversation_id, role, content=None, tool_calls=None,
                            tool_call_id=None) -> None:
        await self.db.insert("messages", {
            "conversation_id": conversation_id, "user_id": user_id, "role": role, "content": content,
            "tool_calls": tool_calls, "tool_call_id": tool_call_id})

    async def _pending_approvals(self, user_id: str, conversation_id: str) -> list[dict[str, Any]]:
        rows = await self.db.select("approvals", {"user_id": user_id, "status": "pending"})
        return [r for r in rows if r["preview"].get("conversation_id") == conversation_id]

    async def _bind(self, user_id: str, tool_name: str) -> BoundTool | None:
        provider = tool_name.split("__", 1)[0]
        manifest = get_manifest(provider)
        if manifest is None:
            return None
        conns = await self.db.select("connections", {"user_id": user_id, "provider": provider, "status": "active"},
                                     order="created_at.desc")
        if not conns:
            return None
        try:
            return BoundTool(manifest, manifest.tool(tool_name), conns[0])
        except KeyError:
            return None

    async def _call_args(self, conversation_id: str, call_id: str) -> dict[str, Any] | None:
        for m in await self.db.select("messages", {"conversation_id": conversation_id, "role": "assistant"},
                                      order="seq.desc"):
            for c in m.get("tool_calls") or []:
                if c["id"] == call_id:
                    try:
                        return json.loads(c["function"]["arguments"] or "{}")
                    except json.JSONDecodeError:
                        return None
        return None

    async def _history(self, conversation_id: str, tools: dict[str, BoundTool]) -> list[dict[str, Any]]:
        rows = await self.db.select("messages", {"conversation_id": conversation_id}, order="seq.asc")
        rows = rows[-HISTORY_LIMIT:]
        while rows and rows[0]["role"] != "user":  # never start mid tool-exchange
            rows = rows[1:]
        names = sorted({b.manifest.name for b in tools.values()})
        out: list[dict[str, Any]] = [{"role": "system", "content": system_prompt(names)}]
        for r in rows:
            if r["role"] == "assistant":
                msg: dict[str, Any] = {"role": "assistant", "content": r.get("content")}
                if r.get("tool_calls"):
                    msg["tool_calls"] = r["tool_calls"]
                out.append(msg)
            elif r["role"] == "tool":
                out.append({"role": "tool", "tool_call_id": r["tool_call_id"], "content": r.get("content") or ""})
            elif r["role"] == "user":
                out.append({"role": "user", "content": r.get("content") or ""})
        return out
