"""Agent runtime: OpenAI tool-calling loop with approvals and auditing.

Events yielded (sent as SSE): token, tool_call, approval_required, tool_result, error, done.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator, Callable

import httpx

from app.agent.llm import LLM, LLMError, LLMResult
from app.agent.guards import StreamGuard, check_final, looks_injected, validate_arguments, wrap_untrusted
from app.agent.memory import Embedder, MemoryService, Summarizer
from app.agent.modes import CONNECTOR, Mode, allowed, describe, resolve, split_command
from app.agent.policy import build_preview, decide, redact_args, redact_result, scrub, tool_label
from app.agent.prompts import system_prompt
from app.agent.response import Action, build_action
from app.agent.usage import RunBudget, UsageLog, usage_of
from app.agent.tools import (
    MAX_RESULT_CHARS, BoundTool, ToolExecutor, available_tools, log_scope_mismatch, pick_connection,
    to_openai_tool,
)
from app.connectors.registry import get_manifest
from app.core.config import Settings
from app.core.secrets import SecretStore
from app.db.client import Database

log = logging.getLogger(__name__)
Event = dict[str, Any]
HISTORY_LIMIT = 40
DECLINED = {"error": "The user declined this action."}
STOPPED_NOTE = ("I did not do that: you rejected it, so nothing was changed. I stopped here. "
                "Tell me what you would like instead and I will start again.")
MODE_REFUSAL = ("This tool is not available in the current chat mode. "
                "Tell the user to switch mode (typing / lists them).")
INTERRUPTED = {"error": "This action did not complete (it was interrupted). Nothing was confirmed."}


class AgentError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def describe_name(mode: Mode) -> str:
    m = get_manifest(mode.connector or "")
    return m.name if m else (mode.connector or "That app")


def _mode_data(mode: Mode) -> dict[str, Any]:
    return {"command": mode.command, "kind": mode.kind, "connector": mode.connector}


def _ev(event: str, **data: Any) -> Event:
    return {"event": event, "data": data}


MAX_OUTPUT_CHARS = 4000   # the output shown in a tool card; the model sees MAX_RESULT_CHARS


def _result_text(result: Any) -> str:
    text = json.dumps(result, default=str, ensure_ascii=False)
    return text if len(text) <= MAX_RESULT_CHARS else text[:MAX_RESULT_CHARS] + '…"(truncated)"'


def _result_ev(call_id: str, tool: str, ok: bool, result: Any, summary: str | None = None,
               duration_ms: int | None = None) -> Event:
    """tool_result event: the legacy fields plus the validated Action (`action`), when it validates."""
    action = build_action(call_id, tool, ok, result)
    return _ev("tool_result", id=call_id, tool=tool, ok=ok, summary=summary if summary is not None
               else _summary(ok, result), action=action.model_dump() if action else None,
               duration_ms=duration_ms, output=_result_text(result)[:MAX_OUTPUT_CHARS])


def _summary(ok: bool, result: Any) -> str:
    if not ok and isinstance(result, dict):
        return str(result.get("error", "error"))[:200]
    return _result_text(result)[:200]


def _repair_tool_exchanges(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Make the stored history a valid OpenAI conversation: every assistant tool_call gets exactly one
    tool message right after it, and tool messages without a call are dropped.

    A turn can be cut short (server restart, client disconnect, database error) after the assistant
    message with tool_calls was saved but before the tool result was. Replaying that history makes
    OpenAI answer 400 on every later message, so the chat would be dead for good. A call with no
    result becomes a tool message saying it did not complete."""
    out: list[dict[str, Any]] = []
    expected: set[str] = set()
    for r in rows:
        if r["role"] == "tool":
            if r.get("tool_call_id") in expected:
                expected.discard(r["tool_call_id"])
                out.append(r)
            continue  # orphan tool message: drop
        for cid in sorted(expected):  # earlier calls never answered
            out.append({"role": "tool", "tool_call_id": cid, "content": _result_text(INTERRUPTED)})
        expected = set()
        out.append(r)
        if r["role"] == "assistant":
            expected = {c["id"] for c in r.get("tool_calls") or []}
    for cid in sorted(expected):
        out.append({"role": "tool", "tool_call_id": cid, "content": _result_text(INTERRUPTED)})
    return out


class AgentRuntime:
    def __init__(self, db: Database, store: SecretStore, http: httpx.AsyncClient, settings: Settings,
                 llm_factory: Callable[[], LLM], embedder_factory: Callable[[], Embedder] | None = None):
        self.db, self.settings = db, settings
        self.executor = ToolExecutor(db, store, http, settings)
        self._llm_factory = llm_factory
        self.usage = UsageLog(db, settings)
        self.memory = MemoryService(db, embedder_factory, llm_factory, settings)
        self.summarizer = Summarizer(db, llm_factory, settings)
        self._background: set[asyncio.Task[Any]] = set()

    # ------------------------------------------------------------------ public entry points

    async def chat(self, user_id: str, conversation_id: str | None, text: str,
                   mode: str | None = None) -> AsyncIterator[Event]:
        """`mode` is a command word ("workflow", "trello", ...) chosen in the UI; a leading /command in the text
        works too. The mode is saved on the conversation and applies until it is changed."""
        chosen: Mode | None = None
        if mode:
            chosen = resolve(mode)
            if chosen is None:
                raise AgentError(422, f"Unknown mode /{mode.lstrip('/')}.")
        typed, rest, unknown = split_command(text)
        if typed is not None:
            chosen, text = typed, rest
        elif unknown is not None and text.strip() == f"/{unknown}":
            raise AgentError(422, f"Unknown command /{unknown}. Type / to see the available modes.")
        if conversation_id:
            rows = await self.db.select("conversations", {"id": conversation_id, "user_id": user_id})
            if not rows:
                raise AgentError(404, "conversation not found")
            current = previous = Mode.from_row(rows[0])
        else:
            previous = Mode()
            current = chosen or Mode()
            conv = await self.db.insert("conversations", {
                "user_id": user_id, "title": (text or current.command).strip()[:60],
                # custom is the column default; leaving it out keeps chat working on a database that has not
                # had migration 0007 (the mode columns) applied yet.
                **({} if current.kind == "custom" else current.row)})
            conversation_id = conv["id"]
        switched = chosen is not None and chosen != previous
        if switched and chosen != current:         # an existing conversation changes mode
            await self.db.update("conversations", {"id": conversation_id, "user_id": user_id}, chosen.row)
            current = chosen
        if current.kind == CONNECTOR and not await self.db.select(
                "connections", {"user_id": user_id, "provider": current.connector, "status": "active"}):
            yield _ev("error", message=f"{describe_name(current)} is not connected. Connect it on the Connections "
                                       "page, or switch with /custom.")
            yield _ev("done", conversation_id=conversation_id)
            return
        if switched or not text.strip():           # tell the UI which mode is now active
            yield _ev("mode", **_mode_data(current))
        if not text.strip():                       # just a mode switch, e.g. "/trello"
            yield _ev("done", conversation_id=conversation_id)
            return
        if await self._pending_approvals(user_id, conversation_id):
            raise AgentError(409, "Approve or reject the pending action first.")
        limit = self.settings.daily_chat_message_limit
        if limit and await self._used_today("messages", user_id, {"role": "user"}, limit) >= limit:
            raise AgentError(429, f"You have reached the daily limit of {limit} chat messages. "
                                  "It resets at midnight UTC.")
        tokens = self.settings.daily_token_limit
        if tokens and await self.usage.tokens_today(user_id) >= tokens:
            raise AgentError(429, f"You have reached today's usage limit (about {tokens:,} tokens). "
                                  "It resets at midnight UTC.")
        await self._save_message(user_id, conversation_id, "user", content=text)
        memories = await self.memory.retrieve(user_id, text)
        if memories:
            yield _ev("memory", count=len(memories))
        async for ev in self._loop(user_id, conversation_id, text, memories):
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
        actions: list[Action] = []
        if not approve:
            # Reject ends the task: nothing else from this plan runs, the model is not asked to continue.
            await self._finish_call(user_id, conversation_id, approval["tool_run_id"], tool_call_id,
                                    False, DECLINED, "rejected")
            yield _result_ev(tool_call_id, preview["tool"], False, DECLINED, "Declined by you")
            now = datetime.now(timezone.utc).isoformat()
            for other in await self._pending_approvals(user_id, conversation_id):
                if not await self.db.update("approvals", {"id": other["id"], "status": "pending"},
                                            {"status": "rejected", "decided_at": now}):
                    continue
                await self._finish_call(user_id, conversation_id, other["tool_run_id"],
                                        other["preview"]["tool_call_id"], False, DECLINED, "rejected")
                yield _result_ev(other["preview"]["tool_call_id"], other["preview"]["tool"], False, DECLINED,
                                 "Declined by you")
            async for ev in self._stop(user_id, conversation_id, STOPPED_NOTE):
                yield ev
            return
        else:
            await self.db.update("tool_runs", {"id": approval["tool_run_id"]}, {"status": "approved"})
            bound = await self._bind(user_id, preview["tool"])
            args = await self._call_args(conversation_id, tool_call_id)
            ms = None
            if not allowed(await self._mode(user_id, conversation_id), preview["tool"]):
                ok, result = False, {"error": MODE_REFUSAL}      # scope is checked again when the call is resumed
            elif bound is None or args is None:
                ok, result = False, {"error": "This app is no longer connected."}
            else:
                yield self._tool_call_event(tool_call_id, bound, args)
                ok, result, ms = await self.executor.execute_timed(bound, args)
            await self._finish_call(user_id, conversation_id, approval["tool_run_id"], tool_call_id, ok, result,
                                    "ok" if ok else "error", ms)
            ev = _result_ev(tool_call_id, preview["tool"], ok, result, duration_ms=ms)
            if ev["data"].get("action"):
                actions.append(Action(**ev["data"]["action"]))
            yield ev

        if await self._pending_approvals(user_id, conversation_id):
            yield _ev("done", conversation_id=conversation_id)
            return
        # The run resumes exactly where it stopped. Its step/token/cost caps start fresh for the continuation.
        async for ev in self._loop(user_id, conversation_id, "", actions=actions):
            yield ev

    async def _stop(self, user_id: str, conversation_id: str, note: str) -> AsyncIterator[Event]:
        await self._save_message(user_id, conversation_id, "assistant", content=note)
        yield _ev("token", text=note)
        yield _ev("done", conversation_id=conversation_id)

    async def _used_today(self, table: str, user_id: str, extra: dict[str, Any], cap: int) -> int:
        now = datetime.now(timezone.utc)
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        rows = await self.db.select_since(table, {"user_id": user_id, **extra}, "created_at", midnight,
                                          limit=cap + 1)
        return len(rows)

    async def _tool_limit_reached(self, user_id: str) -> bool:
        limit = self.settings.daily_tool_run_limit
        return bool(limit) and await self._used_today("tool_runs", user_id, {}, limit) >= limit

    # ------------------------------------------------------------------ loop

    async def _loop(self, user_id: str, conversation_id: str, latest_text: str, memories: list[str] | None = None,
                    actions: list[Action] | None = None) -> AsyncIterator[Event]:
        try:
            llm = self._llm_factory()
        except LLMError as exc:
            yield _ev("error", message=f"The assistant is not configured: {exc}")
            yield _ev("done", conversation_id=conversation_id)
            return

        budget = RunBudget(self.settings)
        actions = list(actions or [])
        for _step in range(self.settings.max_tool_steps):
            capped = budget.exceeded()
            if capped:
                async for ev in self._stop(user_id, conversation_id, capped + " Tell me how you would like to continue."):
                    yield ev
                return
            mode = await self._mode(user_id, conversation_id)
            tools = await available_tools(self.db, user_id, latest_text, self.settings.max_tools_per_request, mode)
            messages = await self._history(conversation_id, tools, mode, user_id, memories)
            result: LLMResult | None = None
            guard, streamed = StreamGuard(), ""
            try:
                async for part in llm.stream(messages, [to_openai_tool(b.tool) for b in tools.values()]):
                    if isinstance(part, LLMResult):
                        result = part
                    else:
                        out = guard.feed(part)
                        if out:
                            streamed += out
                            yield _ev("token", text=out)
            except LLMError as exc:
                log.warning("LLM call failed: %s", exc)
                yield _ev("error", message="The assistant is unavailable right now. Please try again.")
                yield _ev("done", conversation_id=conversation_id)
                return
            assert result is not None
            used = usage_of(result.usage, messages, result.content, result.tool_calls)
            budget.add(used)
            await self.usage.record(user_id, conversation_id, "chat", used)

            if not result.tool_calls:
                # Final answer: check it against the response contract before it is stored or finished streaming.
                final, fixes = check_final(result.content, actions)
                if fixes:
                    log.info("final answer corrected: %s", ",".join(fixes))
                tail = final[len(streamed):] if final.startswith(streamed) else final
                if tail:
                    yield _ev("token", text=tail)
                await self._save_message(user_id, conversation_id, "assistant", content=final or None)
                yield _ev("done", conversation_id=conversation_id)
                async for _ in self._after_answer(user_id, conversation_id):
                    pass
                return

            await self._save_message(user_id, conversation_id, "assistant", content=result.content or None,
                                     tool_calls=result.tool_calls)

            # Independent read-only calls run side by side; everything else runs one at a time, in order.
            early: dict[str, list[Event]] = {}
            reads = [c for c in result.tool_calls if self._parallel_read(c, tools, mode)]
            if self.settings.llm_parallel_tool_calls and len(reads) > 1:
                sem = asyncio.Semaphore(max(1, self.settings.max_parallel_reads))

                async def run_one(call: dict[str, Any]) -> tuple[str, list[Event]]:
                    async with sem:
                        return call["id"], [e async for e in self._handle_call(user_id, conversation_id, call, tools, mode)]

                early = dict(await asyncio.gather(*(run_one(c) for c in reads)))

            paused = False
            for call in result.tool_calls:
                stream = _replay(early[call["id"]]) if call["id"] in early else \
                    self._handle_call(user_id, conversation_id, call, tools, mode)
                async for ev in stream:
                    paused = paused or ev["event"] == "approval_required"
                    if ev["event"] == "tool_result" and ev["data"].get("action"):
                        actions.append(Action(**ev["data"]["action"]))
                    yield ev
            if paused:
                yield _ev("done", conversation_id=conversation_id)
                return

        note = f"I stopped after {self.settings.max_tool_steps} steps. Tell me how you'd like to continue."
        await self._save_message(user_id, conversation_id, "assistant", content=note)
        yield _ev("token", text=note)
        yield _ev("done", conversation_id=conversation_id)

    @staticmethod
    def _parallel_read(call: dict[str, Any], tools: dict[str, BoundTool], mode: Mode) -> bool:
        name = call["function"]["name"]
        bound = tools.get(name)
        return bool(bound and allowed(mode, name) and bound.tool.risk == "read" and not bound.missing)

    async def _after_answer(self, user_id: str, conversation_id: str) -> AsyncIterator[Event]:
        """Long-term memory extraction. In the background by default so the reply is never delayed."""
        if not self.settings.memory_extraction:
            return
        if self.settings.memory_background:
            task = asyncio.create_task(self.memory.extract(user_id, conversation_id))
            self._background.add(task)
            task.add_done_callback(self._background.discard)
        else:
            await self.memory.extract(user_id, conversation_id)
        return
        yield  # pragma: no cover  (makes this an async generator)

    async def _tainted(self, conversation_id: str) -> bool:
        """Has any tool result since the user's last message tried to give instructions? Then this run loses
        auto-approve: every write asks, so injected text can never change anything on its own."""
        rows = await self.db.select("messages", {"conversation_id": conversation_id}, order="seq.asc")
        last_user = max((i for i, r in enumerate(rows) if r["role"] == "user"), default=-1)
        return any(r["role"] == "tool" and looks_injected(r.get("content")) for r in rows[last_user + 1:])

    def _tool_call_event(self, call_id: str, bound: BoundTool, args: dict[str, Any] | None = None) -> Event:
        return _ev("tool_call", id=call_id, input=redact_args(args or {}), tool=bound.tool.name, connector=bound.manifest.id,
                   connector_name=bound.manifest.name, risk=bound.tool.risk, label=tool_label(bound.tool))

    async def _handle_call(self, user_id: str, conversation_id: str, call: dict[str, Any],
                           tools: dict[str, BoundTool], mode: Mode) -> AsyncIterator[Event]:
        """Run one tool call. Whatever goes wrong inside, the call ends with a tool message (or a pending
        approval): an assistant tool_call without a tool result makes OpenAI reject every later turn."""
        call_id, name = call["id"], call["function"]["name"]
        try:
            async for ev in self._handle_call_inner(user_id, conversation_id, call, tools, mode):
                yield ev
        except Exception as exc:  # noqa: BLE001
            log.exception("tool call %s failed: %s", name, type(exc).__name__)
            problem = {"error": "This action could not be completed because of an internal error."}
            try:
                if not await self._call_settled(conversation_id, call_id):
                    await self._save_message(user_id, conversation_id, "tool", content=_result_text(problem),
                                             tool_call_id=call_id)
            except Exception:  # noqa: BLE001 — _history() repairs it on the next turn
                log.exception("could not record the failed tool call")
            yield _result_ev(call_id, name, False, problem)

    async def _call_settled(self, conversation_id: str, call_id: str) -> bool:
        """True if the call has a tool message, or is waiting on a pending approval."""
        if await self.db.select("messages", {"conversation_id": conversation_id, "tool_call_id": call_id}):
            return True
        return any(a["preview"].get("tool_call_id") == call_id
                   for a in await self.db.select("approvals", {"status": "pending"}))

    async def _handle_call_inner(self, user_id: str, conversation_id: str, call: dict[str, Any],
                                 tools: dict[str, BoundTool], mode: Mode) -> AsyncIterator[Event]:
        call_id, name = call["id"], call["function"]["name"]
        bound = tools.get(name) if allowed(mode, name) else None   # scope is re-checked at dispatch
        try:
            args = json.loads(call["function"]["arguments"] or "{}")
        except json.JSONDecodeError:
            args = None

        problem = None
        if not allowed(mode, name):
            problem = MODE_REFUSAL
        elif bound is None:
            problem = f"Unknown or unavailable tool: {name}"
        elif args is None:
            problem = "Tool arguments were not valid JSON."
        else:
            problem = validate_arguments(bound.tool.parameters, args)
        if problem:
            await self._save_message(user_id, conversation_id, "tool", content=_result_text({"error": problem}),
                                     tool_call_id=call_id)
            yield _result_ev(call_id, name, False, {"error": problem}, problem)
            return

        if await self._tool_limit_reached(user_id):
            limit = self.settings.daily_tool_run_limit
            result = {"error": f"The daily limit of {limit} tool runs has been reached. Tell the user it "
                               "resets at midnight UTC and nothing was done."}
            await self._save_message(user_id, conversation_id, "tool", content=_result_text(result),
                                     tool_call_id=call_id)
            yield _result_ev(call_id, name, False, result,
                             f"Daily limit of {limit} tool runs reached (resets at midnight UTC)")
            return

        run = await self.db.insert("tool_runs", {
            "user_id": user_id, "conversation_id": conversation_id, "connection_id": bound.connection["id"],
            "tool": name, "args_redacted": redact_args(args), "status": "pending",
            "connector": bound.manifest.id, "risk": bound.tool.risk,
        })

        if bound.missing:
            # Nothing to approve: the call cannot succeed. Tell the model (and so the user) how to fix it.
            ok, result = False, {"error": bound.scope_error()}
            log_scope_mismatch(bound)
            await self._finish_call(user_id, conversation_id, run["id"], call_id, ok, result, "error")
            yield _result_ev(call_id, name, ok, result)
            return

        auto = bound.auto_approve and not await self._tainted(conversation_id)
        if decide(bound.tool.risk, auto) == "ask":
            preview = build_preview(bound.manifest, bound.tool, args, tool_call_id=call_id,
                                    conversation_id=conversation_id,
                                    account_label=bound.connection.get("account_label"))
            approval = await self.db.insert("approvals", {
                "user_id": user_id, "tool_run_id": run["id"], "preview": preview, "status": "pending"})
            yield _ev("approval_required", approval_id=approval["id"], **preview)
            return

        yield self._tool_call_event(call_id, bound, args)
        ok, result, ms = await self.executor.execute_timed(bound, args)
        await self._finish_call(user_id, conversation_id, run["id"], call_id, ok, result, "ok" if ok else "error", ms)
        yield _result_ev(call_id, name, ok, result, duration_ms=ms)

    # ------------------------------------------------------------------ persistence helpers

    async def _finish_call(self, user_id, conversation_id, run_id, call_id, ok, result, status,
                           duration_ms: int | None = None) -> None:
        await self.db.update("tool_runs", {"id": run_id}, {
            "status": status, "result_summary": scrub(_summary(ok, result)), "duration_ms": duration_ms,
            "result_redacted": redact_result(result), "finished_at": datetime.now(timezone.utc).isoformat()})
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
            tool = manifest.tool(tool_name)
            all_active = await self.db.select("connections", {"user_id": user_id, "status": "active"},
                                              order="created_at.desc")
            return BoundTool(manifest, tool, pick_connection(manifest, tool, conns[0], all_active), conns[0])
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

    async def _mode(self, user_id: str, conversation_id: str) -> Mode:
        rows = await self.db.select("conversations", {"id": conversation_id, "user_id": user_id})
        return Mode.from_row(rows[0] if rows else None)

    async def _history(self, conversation_id: str, tools: dict[str, BoundTool], mode: Mode | None = None,
                       user_id: str | None = None, memories: list[str] | None = None) -> list[dict[str, Any]]:
        rows = await self.db.select("messages", {"conversation_id": conversation_id}, order="seq.asc")
        summary: str | None = None
        if user_id and self.settings.conversation_summary:
            conv = (await self.db.select("conversations", {"id": conversation_id, "user_id": user_id}) or [None])[0]
            if conv:
                state = await self.summarizer.maybe_summarize(user_id, conv, rows)
                summary = state.get("summary")
                rows = [r for r in rows if int(r.get("seq") or 0) > int(state.get("summary_upto") or 0)]
        rows = rows[-self.settings.history_window:]
        while rows and rows[0]["role"] != "user":  # never start mid tool-exchange
            rows = rows[1:]
        names = sorted({b.manifest.name for b in tools.values()})
        out: list[dict[str, Any]] = [{"role": "system", "content": system_prompt(
            names, describe(mode) if mode else "", memories, summary)}]
        rows = _repair_tool_exchanges(rows)
        for r in rows:
            if r["role"] == "assistant":
                msg: dict[str, Any] = {"role": "assistant", "content": r.get("content")}
                if r.get("tool_calls"):
                    msg["tool_calls"] = r["tool_calls"]
                out.append(msg)
            elif r["role"] == "tool":
                # Tool output is third-party data: the model always sees it wrapped as untrusted.
                out.append({"role": "tool", "tool_call_id": r["tool_call_id"],
                            "content": wrap_untrusted(r.get("content"))})
            elif r["role"] == "user":
                out.append({"role": "user", "content": r.get("content") or ""})
        return out


async def _replay(events: list[Event]) -> AsyncIterator[Event]:
    for ev in events:
        yield ev
