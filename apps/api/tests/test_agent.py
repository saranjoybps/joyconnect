"""Agent loop, approvals, policy and auditing with a scripted LLM and mocked providers."""

import json
import time

import pytest
import respx
from fastapi.testclient import TestClient

from app.agent.llm import LLMError, LLMResult
from app.agent.policy import decide, redact_args
from app.agent.tools import available_tools, to_openai_tool
from app.connectors.base import TokenSet
from app.connectors.registry import all_tools
from tests.conftest import USER_A, USER_B, auth

SHEET = "1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"


def call(name, args, id="call_1"):
    return LLMResult(tool_calls=[{"id": id, "type": "function",
                                  "function": {"name": name, "arguments": json.dumps(args)}}])


class FakeLLM:
    def __init__(self, *script):
        self.script = list(script)
        self.calls: list[tuple[list, list]] = []

    async def stream(self, messages, tools):
        self.calls.append((messages, tools))
        step = self.script.pop(0) if self.script else LLMResult(content="(end)")
        if callable(step):
            step = step(messages)
        if step.content:
            yield step.content
        yield step


def events(resp):
    out = []
    for block in resp.text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        out.append((lines["event"], json.loads(lines["data"])))
    return out


def names(evs):
    return [e for e, _ in evs]


@pytest.fixture
def make_client(settings, db, store):
    clients = []

    def _make(llm):
        from app.main import create_app

        c = TestClient(create_app(settings=settings, db=db, secret_store=store, llm=llm), follow_redirects=False)
        c.__enter__()
        clients.append(c)
        return c

    yield _make
    for c in clients:
        c.__exit__(None, None, None)


async def connect(db, store, provider, user=USER_A, auto=False, status="active"):
    t = TokenSet(access_token="tok", expires_at=int(time.time()) + 3600)
    sid = await store.put(user, t.payload())
    return await db.insert("connections", {"user_id": user, "provider": provider, "account_label": "acct",
                                           "scopes": [], "secret_id": sid, "status": status,
                                           "auto_approve_writes": auto})


# ------------------------------------------------------------------ policy / tools

@pytest.mark.parametrize("risk,auto,expected", [
    ("read", False, "run"), ("read", True, "run"),
    ("write", False, "ask"), ("write", True, "run"),
    ("destructive", False, "ask"), ("destructive", True, "ask"),
])
def test_policy_table(risk, auto, expected):
    assert decide(risk, auto) == expected


def test_redact_args():
    out = redact_args({"text": "x" * 500, "api_key": "sk-123", "values": list(range(10)), "n": 3})
    assert out["api_key"] == "[REDACTED]" and out["n"] == 3
    assert len(out["text"]) < 100 and "500 chars" in out["text"]
    assert out["values"][-1] == "…(+5 items)"


def test_openai_tool_shape():
    t = to_openai_tool(all_tools()["slack__post_message"][1])
    assert t["type"] == "function" and t["function"]["strict"] is True
    assert t["function"]["parameters"]["additionalProperties"] is False


async def test_tools_only_from_active_connections(db, store):
    await connect(db, store, "slack")
    await connect(db, store, "notion", status="needs_reauth")
    await connect(db, store, "github", user=USER_B)
    tools = await available_tools(db, USER_A, "hi", 24)
    assert {b.manifest.id for b in tools.values()} == {"slack"}


async def test_tool_cap_prefers_mentioned_connectors(db, store):
    for p in ("google_sheets", "google_docs", "google_calendar", "slack", "notion", "github"):
        await connect(db, store, p)
    tools = await available_tools(db, USER_A, "post the summary in slack and make a notion page", 6)
    assert {b.manifest.id for b in tools.values()} == {"slack", "notion"}
    assert len(tools) <= 6


# ------------------------------------------------------------------ loop

@respx.mock
async def test_read_tool_runs_without_approval(make_client, db, store):
    await connect(db, store, "notion")
    respx.post("https://api.notion.com/v1/search").respond(json={"results": [
        {"object": "page", "id": "p1", "url": "https://notion.so/p1",
         "properties": {"Name": {"type": "title", "title": [{"plain_text": "Roadmap"}]}}}]})
    llm = FakeLLM(call("notion__search", {"query": "Roadmap"}), LLMResult(content="Found 1 page: Roadmap."))
    resp = make_client(llm).post("/api/chat", json={"message": "list my Notion pages matching Roadmap"},
                                 headers=auth())
    evs = events(resp)
    assert names(evs) == ["tool_call", "tool_result", "token", "done"]
    assert evs[0][1]["label"] == "Search" and evs[1][1]["ok"] is True
    run = db.tables["tool_runs"][0]
    assert run["status"] == "ok" and run["tool"] == "notion__search" and run["args_redacted"] == {"query": "Roadmap"}
    # The model saw the tool result on its second call.
    second_messages = llm.calls[1][0]
    assert second_messages[-1]["role"] == "tool" and "Roadmap" in second_messages[-1]["content"]
    assert [m["role"] for m in db.tables["messages"]] == ["user", "assistant", "tool", "assistant"]


@respx.mock
async def test_write_requires_approval_then_runs(make_client, db, store):
    await connect(db, store, "google_sheets")
    args = {"spreadsheet_id": SHEET, "range": "Sheet1!A:B", "values": ["Ada", "ada@x.com"]}
    llm = FakeLLM(call("google_sheets__append_row", args), LLMResult(content="Added Ada to your sheet."))
    client = make_client(llm)

    evs = events(client.post("/api/chat", json={"message": "append a row with Ada"}, headers=auth()))
    assert names(evs) == ["approval_required", "done"]
    approval = evs[0][1]
    assert approval["args"] == args and approval["connector_name"] == "Google Sheets" and approval["risk"] == "write"
    conv_id = evs[1][1]["conversation_id"]
    assert db.tables["tool_runs"][0]["status"] == "pending"
    assert db.tables["approvals"][0]["status"] == "pending"
    assert len(llm.calls) == 1  # loop stopped

    # Chatting again while an approval is pending is refused.
    assert client.post("/api/chat", json={"message": "hi", "conversation_id": conv_id},
                       headers=auth()).status_code == 409
    # Pending approval shows on reload; other users cannot see the conversation.
    conv = client.get(f"/api/conversations/{conv_id}", headers=auth()).json()
    assert conv["pending_approvals"][0]["approval_id"] == approval["approval_id"]
    assert client.get(f"/api/conversations/{conv_id}", headers=auth(USER_B)).status_code == 404

    route = respx.post(url__regex=r".*/values/.*:append").respond(
        json={"updates": {"updatedRange": "Sheet1!A2:B2", "updatedCells": 2}})
    url = f"/api/approvals/{approval['approval_id']}/decision"
    assert client.post(url, json={"approve": True}, headers=auth(USER_B)).status_code == 404
    evs = events(client.post(url, json={"approve": True}, headers=auth()))
    assert names(evs) == ["tool_call", "tool_result", "token", "done"]
    assert evs[1][1]["ok"] is True and route.called
    assert db.tables["tool_runs"][0]["status"] == "ok"
    assert db.tables["approvals"][0]["status"] == "approved"
    # Double submit is refused.
    assert client.post(url, json={"approve": True}, headers=auth()).status_code == 409


@respx.mock
async def test_rejected_approval_is_reported_to_model(make_client, db, store):
    await connect(db, store, "slack")
    llm = FakeLLM(
        call("slack__post_message", {"channel": "C1", "text": "hello"}),
        lambda msgs: LLMResult(content="OK, I did not post it." if "declined" in msgs[-1]["content"] else "??"),
    )
    client = make_client(llm)
    evs = events(client.post("/api/chat", json={"message": "post hello in #general"}, headers=auth()))
    approval_id = evs[0][1]["approval_id"]
    route = respx.post("https://slack.com/api/chat.postMessage")
    evs = events(client.post(f"/api/approvals/{approval_id}/decision", json={"approve": False}, headers=auth()))
    assert names(evs) == ["tool_result", "token", "done"]
    assert evs[0][1]["ok"] is False
    assert evs[1][1]["text"] == "OK, I did not post it."
    assert not route.called
    assert db.tables["tool_runs"][0]["status"] == "rejected"


@respx.mock
async def test_auto_approve_writes_runs_immediately(make_client, db, store):
    await connect(db, store, "slack", auto=True)
    respx.post("https://slack.com/api/chat.postMessage").respond(json={"ok": True, "channel": "C1", "ts": "1"})
    llm = FakeLLM(call("slack__post_message", {"channel": "C1", "text": "hi"}), LLMResult(content="Posted."))
    evs = events(make_client(llm).post("/api/chat", json={"message": "post hi"}, headers=auth()))
    assert names(evs) == ["tool_call", "tool_result", "token", "done"]
    assert "approvals" not in db.tables or db.tables["approvals"] == []


async def test_destructive_always_asks_even_with_auto_approve(make_client, db, store, monkeypatch):
    await connect(db, store, "slack", auto=True)
    monkeypatch.setattr(all_tools()["slack__post_message"][1], "risk", "destructive")
    llm = FakeLLM(call("slack__post_message", {"channel": "C1", "text": "hi"}))
    evs = events(make_client(llm).post("/api/chat", json={"message": "post hi"}, headers=auth()))
    assert names(evs) == ["approval_required", "done"]


async def test_unconnected_or_unknown_tool_is_refused(make_client, db, store):
    await connect(db, store, "slack")
    llm = FakeLLM(call("github__create_issue", {"repo": "o/r", "title": "t", "body": "b"}),
                  LLMResult(content="GitHub is not connected."))
    evs = events(make_client(llm).post("/api/chat", json={"message": "open an issue"}, headers=auth()))
    assert names(evs) == ["tool_result", "token", "done"]
    assert evs[0][1]["ok"] is False and "unavailable" in evs[0][1]["summary"]
    assert "tool_runs" not in db.tables


async def test_bad_arguments_are_refused(make_client, db, store):
    await connect(db, store, "slack")
    llm = FakeLLM(call("slack__post_message", {"channel": "C1"}), LLMResult(content="Need text."))
    evs = events(make_client(llm).post("/api/chat", json={"message": "post"}, headers=auth()))
    assert evs[0][1]["ok"] is False and "missing" in evs[0][1]["summary"]


@respx.mock
async def test_max_steps(make_client, db, store, settings):
    settings.max_tool_steps = 2
    await connect(db, store, "slack")
    respx.post("https://slack.com/api/conversations.list").respond(json={"ok": True, "channels": []})
    llm = FakeLLM(call("slack__list_channels", {}, "a"), call("slack__list_channels", {}, "b"),
                  call("slack__list_channels", {}, "c"))
    evs = events(make_client(llm).post("/api/chat", json={"message": "loop"}, headers=auth()))
    assert len(llm.calls) == 2
    assert evs[-2][0] == "token" and "stopped after 2 steps" in evs[-2][1]["text"]


async def test_needs_reauth_reported(make_client, db, store):
    conn = await connect(db, store, "slack")
    db.tables["secrets"].clear()  # token vanished -> needs reauth
    llm = FakeLLM(call("slack__list_channels", {}), LLMResult(content="Please reconnect Slack."))
    evs = events(make_client(llm).post("/api/chat", json={"message": "channels?"}, headers=auth()))
    assert evs[1][1]["ok"] is False and "reconnected" in evs[1][1]["summary"]
    assert db.tables["connections"][0]["status"] == "needs_reauth"


def test_llm_failure_reported(make_client):
    async def gen(*a):
        raise LLMError("down")
        yield  # pragma: no cover

    class Down:
        def stream(self, messages, tools):
            return gen()

    evs = events(make_client(Down()).post("/api/chat", json={"message": "hi"}, headers=auth()))
    assert names(evs) == ["error", "done"]


def test_rate_limit(make_client, settings):
    settings.chat_rate_limit_per_minute = 2
    client = make_client(FakeLLM())
    codes = [client.post("/api/chat", json={"message": "hi"}, headers=auth()).status_code for _ in range(3)]
    assert codes == [200, 200, 429]
    assert client.post("/api/chat", json={"message": "hi"}, headers=auth(USER_B)).status_code == 200


def test_chat_requires_auth_and_valid_conversation(make_client):
    client = make_client(FakeLLM())
    assert client.post("/api/chat", json={"message": "hi"}).status_code == 401
    assert client.post("/api/chat", json={"message": "hi", "conversation_id": "nope"},
                       headers=auth()).status_code == 404


def test_conversation_list_and_history(make_client):
    client = make_client(FakeLLM(LLMResult(content="Hello!")))
    evs = events(client.post("/api/chat", json={"message": "hi there"}, headers=auth()))
    conv_id = evs[-1][1]["conversation_id"]
    convs = client.get("/api/conversations", headers=auth()).json()
    assert convs[0]["id"] == conv_id and convs[0]["title"] == "hi there"
    assert client.get("/api/conversations", headers=auth(USER_B)).json() == []
    items = client.get(f"/api/conversations/{conv_id}", headers=auth()).json()["items"]
    assert items == [{"kind": "user", "text": "hi there"}, {"kind": "assistant", "text": "Hello!"}]
