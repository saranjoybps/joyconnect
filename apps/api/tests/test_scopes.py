"""Granted scopes: stored as Google returned them, checked per tool, never borrowed from a token that lacks them."""

import json

import respx

from app.agent.llm import LLMResult
from app.agent.tools import ToolExecutor, available_tools
from app.connectors.registry import get_manifest
from tests.conftest import USER_A, auth
from tests.test_agent import FakeLLM, call, connect, events, make_client, names  # noqa: F401  (fixture)
from tests.test_oauth_flow import _id_token, callback, start

SPREADSHEETS = "https://www.googleapis.com/auth/spreadsheets"
DOCUMENTS = "https://www.googleapis.com/auth/documents"
CALENDAR = "https://www.googleapis.com/auth/calendar.events"
IDENTITY = ["openid", "https://www.googleapis.com/auth/userinfo.email"]
CREATE = "https://sheets.googleapis.com/v4/spreadsheets"
FRIENDLY = "Reconnect Google Sheets and tick the Sheets permission"


def token_response(scope: str) -> dict:
    return {"access_token": "ya29.A", "refresh_token": "1//R", "expires_in": 3599, "token_type": "Bearer",
            "scope": scope, "id_token": _id_token("a@gmail.com")}


# ------------------------------------------------------------------ authorize URLs

def test_sheets_authorize_url_includes_the_spreadsheets_scope(client):
    _, q = start(client, "google_sheets")
    scopes = q["scope"].split(" ")
    assert SPREADSHEETS in scopes
    assert DOCUMENTS not in scopes and CALENDAR not in scopes       # each card asks only for its own
    assert q["include_granted_scopes"] == "true"


def test_docs_and_calendar_authorize_urls_ask_for_their_own_scope(client):
    assert DOCUMENTS in start(client, "google_docs")[1]["scope"].split(" ")
    assert CALENDAR in start(client, "google_calendar")[1]["scope"].split(" ")


def test_manifest_requirements():
    sheets = get_manifest("google_sheets")
    assert sheets.functional_scopes() == [SPREADSHEETS, "https://www.googleapis.com/auth/drive.metadata.readonly"] and sheets.verifies_scopes
    assert sheets.permission_name == "Sheets"
    assert get_manifest("google_calendar").permission_name == "Calendar"


# ------------------------------------------------------------------ callback stores what Google granted

@respx.mock
def test_callback_stores_scopes_google_actually_granted(client, db):
    """The user unticked the Sheets checkbox: Google returns only identity scopes."""
    _, q = start(client, "google_sheets")
    respx.post("https://oauth2.googleapis.com/token").respond(json=token_response(" ".join(IDENTITY)))
    resp = callback(client, "google", code="c", state=q["state"])

    conn = db.tables["connections"][0]
    assert sorted(conn["scopes"]) == sorted(IDENTITY)                 # not the requested list
    assert SPREADSHEETS not in conn["scopes"]
    assert resp.headers["location"] == "http://localhost:3000/connections?connected=google_sheets&partial=Sheets"

    shown = client.get("/api/connections", headers=auth()).json()[0]
    assert shown["partial"] is True and shown["missing_scopes"] == [SPREADSHEETS, "https://www.googleapis.com/auth/drive.metadata.readonly"]
    assert sorted(shown["scopes"]) == sorted(IDENTITY)                # shown on the card


@respx.mock
def test_callback_full_grant_is_not_partial(client, db):
    _, q = start(client, "google_sheets")
    respx.post("https://oauth2.googleapis.com/token").respond(
        json=token_response(" ".join([*IDENTITY, SPREADSHEETS, "https://www.googleapis.com/auth/drive.metadata.readonly"])))
    resp = callback(client, "google", code="c", state=q["state"])
    assert resp.headers["location"] == "http://localhost:3000/connections?connected=google_sheets"
    shown = client.get("/api/connections", headers=auth()).json()[0]
    assert shown["partial"] is False and shown["missing_scopes"] == [] and SPREADSHEETS in shown["scopes"]


@respx.mock
def test_callback_keeps_scopes_merged_by_include_granted_scopes(client, db):
    """Google returns the union of earlier grants; we store exactly that."""
    _, q = start(client, "google_docs")
    respx.post("https://oauth2.googleapis.com/token").respond(
        json=token_response(" ".join([*IDENTITY, DOCUMENTS, CALENDAR])))
    callback(client, "google", code="c", state=q["state"])
    assert set(db.tables["connections"][0]["scopes"]) == {*IDENTITY, DOCUMENTS, CALENDAR}


@respx.mock
def test_token_response_without_scope_field_is_not_assumed_granted(client, db):
    """If Google omitted `scope`, do not fall back to the requested list for Google connectors."""
    _, q = start(client, "google_sheets")
    body = token_response("")
    del body["scope"]
    respx.post("https://oauth2.googleapis.com/token").respond(json=body)
    callback(client, "google", code="c", state=q["state"])
    assert db.tables["connections"][0]["scopes"] == []
    assert client.get("/api/connections", headers=auth()).json()[0]["partial"] is True


# ------------------------------------------------------------------ a Docs-only token is never used for Sheets

@respx.mock
async def test_docs_token_is_never_used_for_sheets_tools(db, store, settings):
    sheets = await connect(db, store, "google_sheets", scopes=IDENTITY, token="sheets-tok")
    docs = await connect(db, store, "google_docs", scopes=[*IDENTITY, DOCUMENTS], token="docs-tok")
    create = respx.post(CREATE).respond(json={"spreadsheetId": "x"})

    tools = await available_tools(db, USER_A, "make a sheet", 24)
    bound = tools["google_sheets__create_spreadsheet"]
    assert bound.connection["id"] != docs["id"]               # not borrowed from the newer Docs connection
    assert bound.connection["id"] == sheets["id"]
    assert bound.missing == [SPREADSHEETS]

    ok, result = await ToolExecutor(db, store, __import__("httpx").AsyncClient(), settings).execute(
        bound, {"title": "Test"})
    assert ok is False and FRIENDLY in result["error"]
    assert "403" not in result["error"] and "insufficient" not in result["error"]
    assert not create.called                                    # Google was never called


async def test_docs_only_connection_exposes_no_sheets_tools(db, store):
    await connect(db, store, "google_docs", scopes=[*IDENTITY, DOCUMENTS])
    tools = await available_tools(db, USER_A, "", 24)
    assert not any(n.startswith("google_sheets__") for n in tools)
    assert "google_docs__create_document" in tools


@respx.mock
async def test_chat_reports_missing_permission_without_asking_for_approval(make_client, db, store):
    await connect(db, store, "google_sheets", scopes=IDENTITY)
    await connect(db, store, "google_docs", scopes=[*IDENTITY, DOCUMENTS])
    create = respx.post(CREATE).respond(json={"spreadsheetId": "x"})
    llm = FakeLLM(call("google_sheets__create_spreadsheet", {"title": "Test Leads"}),
                  LLMResult(content="Please reconnect Google Sheets and tick the Sheets permission."))
    client = make_client(llm)

    evs = events(client.post("/api/chat", json={"message": "create a sheet"}, headers=auth()))
    assert "approval_required" not in names(evs)                # nothing to approve: it cannot succeed
    result = next(d for e, d in evs if e == "tool_result")
    assert result["ok"] is False and FRIENDLY in result["summary"]
    assert not create.called
    tool_msg = next(m for m in db.tables["messages"] if m["role"] == "tool")
    assert FRIENDLY in tool_msg["content"]                       # the model sees the instruction
    assert db.tables["tool_runs"][0]["status"] == "error"
    assert "403" not in json.dumps(db.tables["messages"])


@respx.mock
async def test_raw_403_insufficient_scopes_becomes_a_friendly_message(db, store, settings):
    """The record says the scope was granted but Google disagrees (revoked grant): no raw 403 for the user."""
    await connect(db, store, "google_sheets")                    # claims every requested scope
    respx.post(CREATE).respond(403, json={"error": {"message": "Request had insufficient authentication scopes."}})
    bound = (await available_tools(db, USER_A, "", 24))["google_sheets__create_spreadsheet"]
    ok, result = await ToolExecutor(db, store, __import__("httpx").AsyncClient(), settings).execute(
        bound, {"title": "Test"})
    assert ok is False and FRIENDLY in result["error"] and "403" not in result["error"]


# ------------------------------------------------------------------ choosing a connection that has the scope

@respx.mock
async def test_sheets_tool_uses_another_google_connection_that_has_the_scope(db, store, settings):
    """Google merges earlier grants, so a Docs token can legitimately carry the Sheets scope."""
    await connect(db, store, "google_sheets", scopes=IDENTITY, token="sheets-tok")
    docs = await connect(db, store, "google_docs", scopes=[*IDENTITY, DOCUMENTS, SPREADSHEETS], token="docs-tok")
    create = respx.post(CREATE).respond(json={"spreadsheetId": "x", "spreadsheetUrl": "https://s/x"})

    bound = (await available_tools(db, USER_A, "", 24))["google_sheets__create_spreadsheet"]
    assert bound.connection["id"] == docs["id"] and bound.missing == []
    ok, result = await ToolExecutor(db, store, __import__("httpx").AsyncClient(), settings).execute(
        bound, {"title": "T"})
    assert ok and result["spreadsheet_id"] == "x"
    assert create.calls[0].request.headers["authorization"] == "Bearer docs-tok"


async def test_own_connection_is_preferred_when_it_has_the_scope(db, store):
    sheets = await connect(db, store, "google_sheets", token="sheets-tok")
    await connect(db, store, "google_docs", scopes=[*IDENTITY, DOCUMENTS, SPREADSHEETS], token="docs-tok")  # newer
    bound = (await available_tools(db, USER_A, "", 24))["google_sheets__get_values"]
    assert bound.connection["id"] == sheets["id"]


async def test_other_google_accounts_are_never_borrowed(db, store):
    await connect(db, store, "google_sheets", scopes=IDENTITY, label="me@gmail.com")
    await connect(db, store, "google_docs", scopes=[*IDENTITY, DOCUMENTS, SPREADSHEETS], label="other@gmail.com")
    bound = (await available_tools(db, USER_A, "", 24))["google_sheets__get_values"]
    assert bound.connection["account_label"] == "me@gmail.com" and bound.missing == [SPREADSHEETS]


async def test_other_users_connections_are_never_borrowed(db, store):
    from tests.conftest import USER_B

    await connect(db, store, "google_sheets", scopes=IDENTITY)
    await connect(db, store, "google_sheets", user=USER_B, token="b-tok")
    bound = (await available_tools(db, USER_A, "", 24))["google_sheets__get_values"]
    assert bound.connection["user_id"] == USER_A and bound.missing == [SPREADSHEETS]


async def test_borrowed_connection_cannot_widen_auto_approve(db, store):
    """Auto-approve must be on for the card the user toggled AND the connection actually used."""
    await connect(db, store, "google_sheets", scopes=IDENTITY, auto=False)
    await connect(db, store, "google_docs", scopes=[*IDENTITY, DOCUMENTS, SPREADSHEETS], auto=True)
    bound = (await available_tools(db, USER_A, "", 24))["google_sheets__append_row"]
    assert bound.connection["provider"] == "google_docs" and bound.auto_approve is False


async def test_non_google_connectors_are_not_scope_checked(db, store):
    await connect(db, store, "slack", scopes=[])
    bound = (await available_tools(db, USER_A, "", 24))["slack__post_message"]
    assert bound.missing == []
