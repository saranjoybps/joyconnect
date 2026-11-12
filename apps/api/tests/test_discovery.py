"""Auto-discovery: the agent finds files, boards, bases, repos... itself instead of asking for IDs or links.

The LLM is scripted (FakeLLM) and every provider call is mocked; nothing here is a paid call.
"""

import httpx
import pytest
import respx

from app.agent.llm import LLMResult
from app.connectors.base import TokenSet, ToolContext
from app.connectors.registry import all_manifests, all_tools
from tests.conftest import auth
from tests.test_agent import FakeLLM, SHEET, call, connect, events, make_client, names  # noqa: F401

G = "https://www.googleapis.com/auth/"
DRIVE_FILES = "https://www.googleapis.com/drive/v3/files"
FILES = {"files": [
    {"id": "1LeadsAbCdEfGhIjKlMnOpQrStUv01", "name": "Test Leads", "webViewLink": "https://docs.google.com/spreadsheets/d/1LeadsAbCdEfGhIjKlMnOpQrStUv01",
     "modifiedTime": "2026-11-01T10:00:00Z", "owners": [{"displayName": "Sam"}]},
    {"id": "1SalesAbCdEfGhIjKlMnOpQrStUv02", "name": "Sales 2026", "webViewLink": "https://docs.google.com/spreadsheets/d/1SalesAbCdEfGhIjKlMnOpQrStUv02",
     "modifiedTime": "2026-10-01T10:00:00Z"}]}


@pytest.fixture
async def ctx(settings):
    async with httpx.AsyncClient() as http:
        yield ToolContext(http=http, token=TokenSet(access_token="tok"), settings=settings)


def tool(name):
    return all_tools()[name][1]


# ------------------------------------------------------------------ every connector has a way to find things

DISCOVERY = {
    "google_sheets": "google_sheets__search_spreadsheets", "google_docs": "google_docs__search_documents",
    "google_slides": "google_slides__search_presentations", "google_forms": "google_forms__search_forms",
    "google_drive": "google_drive__search_files", "airtable": "airtable__list_bases",
    "asana": "asana__list_workspaces", "linear": "linear__list_teams", "notion": "notion__search",
    "slack": "slack__list_channels", "github": "github__list_repos", "trello": "trello__list_boards",
    "google_calendar": "google_calendar__list_calendars", "google_tasks": "google_tasks__list_task_lists",
}


@pytest.mark.parametrize("cid,name", DISCOVERY.items())
def test_every_connector_has_a_read_only_discovery_tool(cid, name):
    t = tool(name)
    assert t.risk == "read", name
    assert name.split("__")[0] == cid


def test_discovery_descriptions_tell_the_agent_not_to_ask_for_ids():
    for name in ("google_sheets__search_spreadsheets", "google_drive__search_files", "airtable__list_bases",
                 "trello__list_boards", "slack__list_users", "github__search_repositories"):
        assert "never ask" in tool(name).description.lower(), name


def test_google_file_connectors_request_drive_metadata_scope_and_say_why():
    for cid in ("google_sheets", "google_docs", "google_slides", "google_forms", "google_drive"):
        m = all_manifests()[cid]
        assert G + "drive.metadata.readonly" in m.scopes
        assert G + "drive.metadata.readonly" in m.scope_labels
        assert "metadata" in m.scope_labels[G + "drive.metadata.readonly"].lower()


# ------------------------------------------------------------------ the tools (HTTP mocked)

@respx.mock
@pytest.mark.parametrize("name,mime", [
    ("google_sheets__search_spreadsheets", "application/vnd.google-apps.spreadsheet"),
    ("google_docs__search_documents", "application/vnd.google-apps.document"),
    ("google_slides__search_presentations", "application/vnd.google-apps.presentation"),
    ("google_forms__search_forms", "application/vnd.google-apps.form"),
])
async def test_google_search_tools_query_drive_by_type_and_name(ctx, name, mime):
    route = respx.get(DRIVE_FILES).respond(json=FILES)
    out = await tool(name).handler(ctx, query="Test leads", limit=None)
    q = route.calls[0].request.url.params
    assert f"mimeType = '{mime}'" in q["q"] and "trashed = false" in q["q"]
    assert "name contains 'Test'" in q["q"] and "name contains 'leads'" in q["q"]
    assert q["orderBy"] == "modifiedTime desc" and q["pageSize"] == "10"
    assert [m["id"] for m in out["matches"]] == ["1LeadsAbCdEfGhIjKlMnOpQrStUv01", "1SalesAbCdEfGhIjKlMnOpQrStUv02"] and out["matches"][0]["owner"] == "Sam"


@respx.mock
async def test_search_with_no_query_lists_recent_and_escapes_quotes(ctx):
    route = respx.get(DRIVE_FILES).respond(json={"files": []})
    await tool("google_sheets__search_spreadsheets").handler(ctx, query=None, limit=500)
    q = route.calls[0].request.url.params
    assert "name contains" not in q["q"] and q["pageSize"] == "25"
    await tool("google_sheets__search_spreadsheets").handler(ctx, query="Bob's", limit=3)
    assert "name contains 'Bob\\'s'" in route.calls[1].request.url.params["q"]


@respx.mock
async def test_drive_search_files_any_type(ctx):
    route = respx.get(DRIVE_FILES).respond(json=FILES)
    out = await tool("google_drive__search_files").handler(ctx, query="leads", limit=5)
    assert "mimeType" not in route.calls[0].request.url.params["q"] and out["count"] == 2


@respx.mock
async def test_airtable_list_tables(ctx):
    respx.get("https://api.airtable.com/v0/meta/bases/appAbCdEfGhIjKlMn/tables").respond(json={"tables": [
        {"id": "tbl1", "name": "Leads", "primaryFieldId": "fld1",
         "fields": [{"name": "Name", "type": "singleLineText"}], "views": [{"name": "Grid"}]}]})
    out = await tool("airtable__list_tables").handler(ctx, base_id="appAbCdEfGhIjKlMn")
    assert out["tables"][0]["name"] == "Leads" and out["tables"][0]["fields"][0]["name"] == "Name"


@respx.mock
async def test_asana_search_uses_typeahead(ctx):
    route = respx.get("https://app.asana.com/api/1.0/workspaces/123456/typeahead").respond(
        json={"data": [{"gid": "9", "name": "Launch", "resource_type": "project"}]})
    out = await tool("asana__search").handler(ctx, workspace_gid="123456", resource_type="project",
                                              query="lau", count=None)
    assert route.calls[0].request.url.params["resource_type"] == "project"
    assert out["matches"] == [{"gid": "9", "name": "Launch", "type": "project"}]


@respx.mock
async def test_linear_search_issues_filters_on_title(ctx):
    route = respx.post("https://api.linear.app/graphql").respond(json={"data": {"issues": {"nodes": [
        {"id": "i1", "identifier": "ENG-1", "title": "Fix login", "url": "https://linear.app/x", "state": {"name": "Todo"},
         "assignee": None}]}}})
    out = await tool("linear__search_issues").handler(ctx, query="login", first=None)
    assert b"containsIgnoreCase" in route.calls[0].request.content
    assert out["matches"][0]["identifier"] == "ENG-1"


@respx.mock
async def test_slack_list_users_skips_bots_and_deactivated(ctx):
    respx.post("https://slack.com/api/users.list").respond(json={"ok": True, "members": [
        {"id": "U1", "name": "ada", "real_name": "Ada L", "profile": {"display_name": "ada"}},
        {"id": "U2", "name": "bot", "is_bot": True}, {"id": "U3", "name": "gone", "deleted": True}]})
    out = await tool("slack__list_users").handler(ctx)
    assert [u["id"] for u in out["users"]] == ["U1"]


@respx.mock
async def test_github_searches(ctx):
    repos = respx.get("https://api.github.com/search/repositories").respond(json={"items": [
        {"full_name": "o/api", "private": False, "html_url": "https://github.com/o/api", "description": "d"}]})
    issues = respx.get("https://api.github.com/search/issues").respond(json={"items": [
        {"repository_url": "https://api.github.com/repos/o/api", "number": 3, "title": "Bug", "state": "open",
         "html_url": "https://github.com/o/api/issues/3"}]})
    assert (await tool("github__search_repositories").handler(ctx, query="api", limit=None))["repos"][0]["full_name"] == "o/api"
    out = await tool("github__search_issues").handler(ctx, query="bug repo:o/api", kind="pull_request", limit=None)
    assert "is:pull-request" in issues.calls[0].request.url.params["q"]
    assert out["items"][0] == {"repo": "o/api", "number": 3, "title": "Bug", "state": "open",
                               "url": "https://github.com/o/api/issues/3"}
    assert repos.called


# ------------------------------------------------------------------ Partial access until the user reconnects

OLD_SHEETS_SCOPES = ["openid", "email", G + "spreadsheets"]


@respx.mock
async def test_old_google_connection_shows_partial_access_but_old_tools_still_work(make_client, db, store):
    await connect(db, store, "google_sheets", scopes=OLD_SHEETS_SCOPES)
    shown = make_client(FakeLLM()).get("/api/connections", headers=auth()).json()[0]
    assert shown["partial"] is True and shown["missing_scopes"] == [G + "drive.metadata.readonly"]

    # the old tool (spreadsheets scope only) is unaffected
    respx.get(url__regex=r".*/v4/spreadsheets/.*").respond(json={"sheets": [{"properties": {"title": "Sheet1"}}]})
    llm = FakeLLM(call("google_sheets__list_tabs", {"spreadsheet_id": SHEET}), LLMResult(content="One tab."))
    evs = events(make_client(llm).post("/api/chat", json={"message": "tabs of that sheet"}, headers=auth()))
    assert evs[0][0] == "tool_call" and [e for e in evs if e[0] == "tool_result"][0][1]["ok"] is True

    # the new search tool never calls Google and says exactly what to do
    llm = FakeLLM(call("google_sheets__search_spreadsheets", {"query": None, "limit": None}), LLMResult(content="Reconnect."))
    evs = events(make_client(llm).post("/api/chat", json={"message": "list my sheets"}, headers=auth()))
    res = [e for e in evs if e[0] == "tool_result"][0][1]
    assert res["ok"] is False and "Reconnect Google Sheets" in res["summary"] or "permission" in res["summary"]
    assert not any(e[0] == "approval_required" for e in evs)


# ------------------------------------------------------------------ the agent resolves names by searching first

@respx.mock
async def test_list_my_sheets_searches_and_never_asks_for_a_link(make_client, db, store):
    await connect(db, store, "google_sheets")
    respx.get(DRIVE_FILES).respond(json=FILES)
    llm = FakeLLM(call("google_sheets__search_spreadsheets", {"query": None, "limit": None}),
                  LLMResult(content="You have 2 spreadsheets: **Test Leads** and **Sales 2026**."))
    client = make_client(llm)
    evs = events(client.post("/api/chat", json={"message": "list my Google Sheets", "mode": "sheets"}, headers=auth()))
    assert names(evs)[:2] == ["mode", "tool_call"] and "approval_required" not in names(evs)
    assert "link" not in "".join(e[1].get("text", "") for e in evs).lower()
    # the scoped tool list already contains the discovery tool, and the rules tell the model to find, not ask
    first_msgs, first_tools = llm.calls[0]
    assert "google_sheets__search_spreadsheets" in [t["function"]["name"] for t in first_tools]
    assert "FIND, DON'T ASK" in first_msgs[0]["content"]


@respx.mock
async def test_name_to_id_then_read_in_one_run(make_client, db, store):
    """'read my Test Leads sheet': search, then read the tab with the id the search returned."""
    await connect(db, store, "google_sheets")
    respx.get(DRIVE_FILES).respond(json={"files": [FILES["files"][0]]})
    values = respx.get(url__regex=r".*/v4/spreadsheets/1LeadsAbCdEfGhIjKlMnOpQrStUv01/values/.*").respond(
        json={"range": "Sheet1!A1:B2", "values": [["Name", "Email"], ["Ada", "a@x.com"]]})

    def read(msgs):          # the model uses the id from the tool result it was just shown
        assert "1LeadsAbCdEfGhIjKlMnOpQrStUv01" in msgs[-1]["content"]
        return call("google_sheets__get_values", {"spreadsheet_id": "1LeadsAbCdEfGhIjKlMnOpQrStUv01", "range": "Sheet1!A1:B2"}, "c2")

    llm = FakeLLM(call("google_sheets__search_spreadsheets", {"query": "Test Leads", "limit": None}, "c1"), read,
                  LLMResult(content="Ada is the first lead."))
    evs = events(make_client(llm).post("/api/chat", json={"message": "read my Test Leads sheet"}, headers=auth()))
    assert names(evs).count("tool_result") == 2 and values.called and "approval_required" not in names(evs)


@respx.mock
async def test_ambiguous_match_is_shown_to_the_user(make_client, db, store):
    """Several plausible files: the discovery result carries the instruction to ask, with the candidates."""
    await connect(db, store, "google_sheets")
    respx.get(DRIVE_FILES).respond(json=FILES)
    llm = FakeLLM(call("google_sheets__search_spreadsheets", {"query": "2026", "limit": None}),
                  LLMResult(content="Which one: **Test Leads** or **Sales 2026**?"))
    client = make_client(llm)
    evs = events(client.post("/api/chat", json={"message": "open the 2026 sheet"}, headers=auth()))
    tool_msg = llm.calls[1][0][-1]
    assert "Test Leads" in tool_msg["content"] and "ask the user which one" in tool_msg["content"]
    assert evs[-2][1]["text"].startswith("Which one")


async def test_scoped_modes_expose_discovery_and_action_tools(make_client, db, store):
    for provider, mode, expect in [("google_sheets", "sheets", {"google_sheets__search_spreadsheets",
                                                                 "google_sheets__list_tabs", "google_sheets__append_row"}),
                                   ("trello", "trello", {"trello__list_boards"}),
                                   ("airtable", "airtable", {"airtable__list_bases", "airtable__list_tables"})]:
        await connect(db, store, provider)
        llm = FakeLLM(LLMResult(content="ok"))
        events(make_client(llm).post("/api/chat", json={"message": "hi", "mode": mode}, headers=auth()))
        offered = {t["function"]["name"] for t in llm.calls[0][1]}
        assert expect <= offered and all(n.startswith(provider + "__") for n in offered)
