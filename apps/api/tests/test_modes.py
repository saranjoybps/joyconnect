"""Step 5: chat modes (/custom, /workflow, /<connector>) and server-side tool scoping.
The LLM is scripted (FakeLLM) and every provider call is mocked; nothing reaches OpenAI."""

import pytest
import respx

from app.agent.llm import LLMResult
from app.agent.modes import CONNECTOR, CUSTOM, WORKFLOW, Mode, allowed, resolve, split_command
from app.agent.tools import available_tools
from tests.conftest import USER_A, USER_B, auth
from tests.test_agent import SHEET, FakeLLM, call, connect, events, make_client, names  # noqa: F401


def tool_names(llm: FakeLLM, n: int = 0) -> list[str]:
    return [t["function"]["name"] for t in llm.calls[n][1]]


# ------------------------------------------------------------------ parsing

def test_resolve_commands_and_aliases():
    assert resolve("custom") == Mode(CUSTOM)
    assert resolve("/workflow") == Mode(WORKFLOW)
    assert resolve("google-docs") == Mode(CONNECTOR, "google_docs")
    assert resolve("docs") == Mode(CONNECTOR, "google_docs")          # short form
    assert resolve("sheets") == Mode(CONNECTOR, "google_sheets")
    assert resolve("TRELLO") == Mode(CONNECTOR, "trello")
    assert resolve("nope") is None


def test_split_command():
    assert split_command("/trello list my boards") == (Mode(CONNECTOR, "trello"), "list my boards", None)
    assert split_command("/sheets") == (Mode(CONNECTOR, "google_sheets"), "", None)
    assert split_command("hello /trello") == (None, "hello /trello", None)
    assert split_command("/etc/passwd is a path") == (None, "/etc/passwd is a path", None)
    assert split_command("/nope") == (None, "/nope", "nope")


def test_allowed_is_decided_from_the_tool_name():
    trello = Mode(CONNECTOR, "trello")
    assert allowed(trello, "trello__list_boards") and not allowed(trello, "notion__search")
    assert not allowed(trello, "trello_evil__x")                       # prefix tricks do not match
    assert allowed(Mode(CUSTOM), "notion__search")
    assert not allowed(Mode(WORKFLOW), "notion__search")


# ------------------------------------------------------------------ the mode list

async def test_modes_endpoint_lists_custom_workflow_and_only_connected_apps(make_client, db, store):
    await connect(db, store, "google_docs")
    await connect(db, store, "trello")
    await connect(db, store, "slack", status="needs_reauth")             # not usable, so not offered
    await connect(db, store, "notion", user=USER_B)                      # someone else's
    c = make_client(None)
    modes = c.get("/api/chat/modes", headers=auth()).json()
    assert [m["command"] for m in modes] == ["custom", "workflow", "google-docs", "trello"]
    docs = modes[2]
    assert docs["aliases"] == ["docs"] and docs["connector"] == "google_docs" and docs["label"] == "Google Docs"
    assert c.get("/api/chat/modes").status_code in (401, 403)


# ------------------------------------------------------------------ tool scoping, when the list is built

async def test_available_tools_are_scoped_by_mode(db, store):
    await connect(db, store, "notion")
    await connect(db, store, "trello")
    everything = await available_tools(db, USER_A, "", 200)
    only_trello = await available_tools(db, USER_A, "", 200, Mode(CONNECTOR, "trello"))
    assert {n.split("__")[0] for n in everything} == {"notion", "trello"}
    assert only_trello and {n.split("__")[0] for n in only_trello} == {"trello"}
    assert await available_tools(db, USER_A, "", 200, Mode(WORKFLOW)) == {}


async def test_scoped_mode_sends_only_that_connectors_tools_to_the_model(make_client, db, store):
    await connect(db, store, "notion")
    await connect(db, store, "trello")
    llm = FakeLLM(LLMResult(content="ok"), LLMResult(content="ok"))
    c = make_client(llm)
    c.post("/api/chat", json={"message": "hi", "mode": "trello"}, headers=auth())
    assert tool_names(llm) and all(n.startswith("trello__") for n in tool_names(llm))
    assert "/trello mode" in llm.calls[0][0][0]["content"]                 # the model is also told, but that is not the guard

    llm2 = FakeLLM(LLMResult(content="ok"))
    make_client(llm2).post("/api/chat", json={"message": "hi"}, headers=auth())
    assert {n.split("__")[0] for n in tool_names(llm2)} == {"notion", "trello"}      # /custom is unchanged


async def test_workflow_mode_gives_the_model_no_app_tools(make_client, db, store):
    await connect(db, store, "notion")
    llm = FakeLLM(LLMResult(content="Here is a plan."))
    make_client(llm).post("/api/chat", json={"message": "plan a daily report", "mode": "workflow"}, headers=auth())
    assert tool_names(llm) == []
    assert "/workflow mode" in llm.calls[0][0][0]["content"]


# ------------------------------------------------------------------ tool scoping, when a call is dispatched

@respx.mock
async def test_a_tool_outside_the_scope_is_refused_even_if_the_model_asks_for_it(make_client, db, store):
    await connect(db, store, "notion")
    await connect(db, store, "trello")
    notion = respx.post("https://api.notion.com/v1/search").respond(json={"results": []})
    llm = FakeLLM(call("notion__search", {"query": "x"}), LLMResult(content="I can't do that here."))
    evs = events(make_client(llm).post("/api/chat", json={"message": "search notion", "mode": "trello"}, headers=auth()))
    result = next(d for e, d in evs if e == "tool_result")
    assert result["ok"] is False and "not available in the current chat mode" in result["summary"]
    assert not notion.called                                               # the provider was never contacted
    assert db.tables.get("tool_runs", []) == []                            # nothing was even recorded as run
    # The model saw the refusal as the tool's result, so the exchange stays valid for the next turn.
    assert llm.calls[1][0][-1]["role"] == "tool"


@respx.mock
async def test_workflow_mode_refuses_every_app_tool(make_client, db, store):
    await connect(db, store, "notion")
    notion = respx.post("https://api.notion.com/v1/search").respond(json={"results": []})
    llm = FakeLLM(call("notion__search", {"query": "x"}), LLMResult(content="done"))
    evs = events(make_client(llm).post("/api/chat", json={"message": "go", "mode": "workflow"}, headers=auth()))
    assert next(d for e, d in evs if e == "tool_result")["ok"] is False and not notion.called


@respx.mock
async def test_an_approved_call_is_checked_against_the_scope_again_when_resumed(make_client, db, store):
    await connect(db, store, "google_sheets")
    args = {"spreadsheet_id": SHEET, "range": "Sheet1!A:B", "values": ["Ada", "ada@x.com"]}
    llm = FakeLLM(call("google_sheets__append_row", args), LLMResult(content="ok"))
    c = make_client(llm)
    evs = events(c.post("/api/chat", json={"message": "append a row"}, headers=auth()))
    approval_id = evs[0][1]["approval_id"]
    # The conversation's scope changes while the approval is pending (for instance edited directly in the database).
    db.tables["conversations"][0].update(mode="connector", tool_scope="trello")
    sheets = respx.post(url__regex=r".*/values/.*:append").respond(json={"updates": {}})
    evs = events(c.post(f"/api/approvals/{approval_id}/decision", json={"approve": True}, headers=auth()))
    assert not sheets.called
    assert next(d for e, d in evs if e == "tool_result")["ok"] is False


# ------------------------------------------------------------------ the mode is part of the session

async def test_mode_is_saved_on_the_conversation_and_sticks(make_client, db, store):
    await connect(db, store, "notion")
    await connect(db, store, "trello")
    llm = FakeLLM(LLMResult(content="a"), LLMResult(content="b"), LLMResult(content="c"))
    c = make_client(llm)
    evs = events(c.post("/api/chat", json={"message": "hi", "mode": "trello"}, headers=auth()))
    assert ("mode", {"command": "trello", "kind": "connector", "connector": "trello"}) in evs
    conv = db.tables["conversations"][0]
    assert conv["mode"] == "connector" and conv["tool_scope"] == "trello"
    cid = evs[-1][1]["conversation_id"]

    # A follow-up without a mode stays scoped.
    c.post("/api/chat", json={"message": "and then?", "conversation_id": cid}, headers=auth())
    assert all(n.startswith("trello__") for n in tool_names(llm, 1))
    # Opening the conversation later restores the mode.
    assert c.get(f"/api/conversations/{cid}", headers=auth()).json()["mode"] == {
        "command": "trello", "kind": "connector", "connector": "trello"}
    # Switching back changes it for the rest of the chat.
    c.post("/api/chat", json={"message": "all apps now", "conversation_id": cid, "mode": "custom"}, headers=auth())
    assert {n.split("__")[0] for n in tool_names(llm, 2)} == {"notion", "trello"}
    assert db.tables["conversations"][0]["mode"] == "custom"


async def test_a_typed_slash_command_switches_mode_and_is_not_sent_to_the_model(make_client, db, store):
    await connect(db, store, "trello")
    llm = FakeLLM(LLMResult(content="Your boards: ..."))
    c = make_client(llm)
    evs = events(c.post("/api/chat", json={"message": "/trello list my boards"}, headers=auth()))
    assert ("mode", {"command": "trello", "kind": "connector", "connector": "trello"}) in evs
    assert [m["content"] for m in db.tables["messages"] if m["role"] == "user"] == ["list my boards"]
    assert all(n.startswith("trello__") for n in tool_names(llm))


async def test_a_lone_command_only_switches_mode_without_calling_the_model(make_client, db, store):
    await connect(db, store, "google_sheets")
    llm = FakeLLM()
    evs = events(make_client(llm).post("/api/chat", json={"message": "/sheets"}, headers=auth()))
    assert names(evs) == ["mode", "done"] and evs[0][1]["command"] == "google-sheets"
    assert llm.calls == [] and db.tables.get("messages", []) == []


async def test_scoped_mode_for_an_app_that_is_not_connected_explains_and_stops(make_client, db, store):
    await connect(db, store, "notion")
    llm = FakeLLM()
    evs = events(make_client(llm).post("/api/chat", json={"message": "/trello boards"}, headers=auth()))
    assert names(evs) == ["error", "done"] and "Trello is not connected" in evs[0][1]["message"]
    assert llm.calls == []


async def test_unknown_modes_are_rejected(make_client, db, store):
    c = make_client(FakeLLM())
    assert c.post("/api/chat", json={"message": "hi", "mode": "bogus"}, headers=auth()).status_code == 422
    r = c.post("/api/chat", json={"message": "/bogus"}, headers=auth())
    assert r.status_code == 422 and "Unknown command /bogus" in r.json()["detail"]
    # Text that merely starts with a slash is still a normal message.
    llm = FakeLLM(LLMResult(content="ok"))
    assert make_client(llm).post("/api/chat", json={"message": "/tmp/report.csv is attached"}, headers=auth()).status_code == 200


async def test_default_conversations_do_not_need_the_mode_columns(make_client, db, store):
    """Migration 0007 adds mode/tool_scope. /custom (the default) must not write them, so chat keeps working on a
    database that has not been migrated yet."""
    llm = FakeLLM(LLMResult(content="ok"))
    make_client(llm).post("/api/chat", json={"message": "hi"}, headers=auth())
    conv = db.tables["conversations"][0]
    assert "mode" not in conv and "tool_scope" not in conv
