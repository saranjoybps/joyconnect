"""Regression: follow-up turns in one conversation (mocked LLM, mocked providers)."""
import json

import respx

from app.agent.llm import LLMResult
from tests.test_agent import FakeLLM, SHEET, call, connect, events, make_client, names  # noqa: F401
from tests.conftest import auth


def _valid_for_openai(messages):
    """OpenAI rule: every assistant tool_call needs a following tool message; no orphan tool messages."""
    pending = set()
    for m in messages:
        if m["role"] == "assistant":
            assert not pending, f"unanswered tool calls {pending} before an assistant message"
            pending = {c["id"] for c in m.get("tool_calls") or []}
        elif m["role"] == "tool":
            assert m["tool_call_id"] in pending, "orphan tool message"
            pending.discard(m["tool_call_id"])
        elif m["role"] == "user":
            assert not pending, f"unanswered tool calls {pending} before a user message"
    assert not pending, f"unanswered tool calls at end: {pending}"


@respx.mock
async def test_two_turn_followup_replays_valid_history(make_client, db, store):
    await connect(db, store, "google_sheets", auto=True)
    respx.post(url__regex=r".*/values/.*:append").respond(json={"updates": {"updatedRange": "Sheet1!A2:B2"}})
    args = {"spreadsheet_id": SHEET, "range": "Sheet1!A:B", "values": ["Ada", "a@x.com"]}
    llm = FakeLLM(call("google_sheets__append_row", args, "c1"), LLMResult(content="Added Ada."),
                  call("google_sheets__append_row", {**args, "values": ["Bob", "b@x.com"]}, "c2"),
                  LLMResult(content="Added Bob."))
    client = make_client(llm)
    evs = events(client.post("/api/chat", json={"message": "add Ada"}, headers=auth()))
    conv = evs[-1][1]["conversation_id"]
    evs = events(client.post("/api/chat", json={"message": "now add Bob to that sheet", "conversation_id": conv},
                             headers=auth()))
    assert [m['role'] for m in llm.calls[2][0]] == ['system', 'user', 'assistant', 'tool', 'assistant', 'user']
    for messages, _ in llm.calls:
        _valid_for_openai(messages)
    assert names(evs) == ["tool_call", "tool_result", "token", "done"]


@respx.mock
async def test_followup_after_approval(make_client, db, store):
    await connect(db, store, "google_sheets")
    respx.post(url__regex=r".*/values/.*:append").respond(json={"updates": {"updatedRange": "Sheet1!A2:B2"}})
    args = {"spreadsheet_id": SHEET, "range": "Sheet1!A:B", "values": ["Ada", "a@x.com"]}
    llm = FakeLLM(call("google_sheets__append_row", args, "c1"), LLMResult(content="Added Ada."),
                  call("google_sheets__append_row", {**args, "values": ["Bob", "b@x.com"]}, "c2"),
                  LLMResult(content="Added Bob."))
    client = make_client(llm)
    evs = events(client.post("/api/chat", json={"message": "add Ada"}, headers=auth()))
    conv, aid = evs[-1][1]["conversation_id"], evs[0][1]["approval_id"]
    events(client.post(f"/api/approvals/{aid}/decision", json={"approve": True}, headers=auth()))
    evs = events(client.post("/api/chat", json={"message": "now add Bob to that sheet", "conversation_id": conv},
                             headers=auth()))
    for messages, _ in llm.calls:
        _valid_for_openai(messages)
    assert names(evs) == ["approval_required", "done"]


@respx.mock
async def test_failed_tool_call_does_not_break_next_turn(make_client, db, store, monkeypatch):
    """A crash between saving the assistant tool_call and its tool result must not break later turns."""
    await connect(db, store, "google_sheets", auto=True)
    args = {"spreadsheet_id": SHEET, "range": "Sheet1!A:B", "values": ["Ada", "a@x.com"]}
    llm = FakeLLM(call("google_sheets__append_row", args, "c1"), LLMResult(content="Added Ada."))
    client = make_client(llm)

    real_insert = db.insert

    async def flaky(table, row):
        if table == "tool_runs":
            raise RuntimeError("Supabase POST tool_runs failed with 400: column does not exist")
        return await real_insert(table, row)

    monkeypatch.setattr(db, "insert", flaky)
    evs = events(client.post("/api/chat", json={"message": "add Ada"}, headers=auth()))
    assert names(evs) == ["tool_result", "token", "done"] and evs[0][1]["ok"] is False
    conv = db.tables["conversations"][0]["id"]
    monkeypatch.setattr(db, "insert", real_insert)

    events(client.post("/api/chat", json={"message": "hello again", "conversation_id": conv}, headers=auth()))
    _valid_for_openai(llm.calls[-1][0])


@respx.mock
async def test_five_turn_conversation_with_tool_calls(make_client, db, store):
    await connect(db, store, "google_sheets", auto=True)
    respx.post(url__regex=r".*/values/.*:append").respond(json={"updates": {"updatedRange": "Sheet1!A2:B2"}})
    base = {"spreadsheet_id": SHEET, "range": "Sheet1!A:B"}
    script = []
    for i in range(5):
        script += [call("google_sheets__append_row", {**base, "values": [f"P{i}", "x"]}, f"c{i}"),
                   LLMResult(content=f"Added P{i}.")]
    llm = FakeLLM(*script)
    client = make_client(llm)
    conv = None
    for i in range(5):
        body = {"message": f"add P{i}", **({"conversation_id": conv} if conv else {})}
        evs = events(client.post("/api/chat", json=body, headers=auth()))
        assert names(evs) == ["tool_call", "tool_result", "token", "done"], i
        conv = evs[-1][1]["conversation_id"]
    for messages, _ in llm.calls:
        _valid_for_openai(messages)
    last = llm.calls[-1][0]
    assert [m["content"] for m in last if m["role"] == "user"] == [f"add P{i}" for i in range(5)]
    assert len(db.tables["conversations"]) == 1


def test_history_repair_fills_unanswered_calls_and_drops_orphans():
    from app.agent.runtime import _repair_tool_exchanges

    tc = lambda cid: [{"id": cid, "type": "function", "function": {"name": "n", "arguments": "{}"}}]  # noqa: E731
    rows = [
        {"role": "user", "content": "a"},
        {"role": "assistant", "content": None, "tool_calls": tc("c1")},      # never answered (crash)
        {"role": "user", "content": "b"},
        {"role": "tool", "tool_call_id": "ghost", "content": "{}"},          # orphan
        {"role": "assistant", "content": None, "tool_calls": tc("c2")},
        {"role": "tool", "tool_call_id": "c2", "content": '{"ok": 1}'},
        {"role": "assistant", "content": "done"},
        {"role": "assistant", "content": None, "tool_calls": tc("c3")},      # unanswered at the very end
    ]
    out = _repair_tool_exchanges(rows)
    _valid_for_openai(out)
    assert [m["role"] for m in out] == ["user", "assistant", "tool", "user", "assistant", "tool", "assistant",
                                         "assistant", "tool"]
    assert "did not complete" in out[2]["content"]


@respx.mock
async def test_long_history_is_trimmed_to_a_valid_start(make_client, db, store):
    await connect(db, store, "google_sheets", auto=True)
    respx.post(url__regex=r".*/values/.*:append").respond(json={"updates": {}})
    base = {"spreadsheet_id": SHEET, "range": "Sheet1!A:B"}
    script = []
    for i in range(14):  # 4 messages per turn: well past HISTORY_LIMIT
        script += [call("google_sheets__append_row", {**base, "values": [str(i), "x"]}, f"c{i}"),
                   LLMResult(content=f"ok {i}")]
    llm = FakeLLM(*script)
    client = make_client(llm)
    conv = None
    for i in range(14):
        body = {"message": f"m{i}", **({"conversation_id": conv} if conv else {})}
        conv = events(client.post("/api/chat", json=body, headers=auth()))[-1][1]["conversation_id"]
    for messages, _ in llm.calls:
        _valid_for_openai(messages)
        assert messages[1]["role"] == "user"
