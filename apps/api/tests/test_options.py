"""Load options: every loader (HTTP mocked), the POST /api/nodes/{type}/options endpoint, caching, scope and error
states, UI-spec integrity, and the patch operations the canvas uses to switch operation / clear dependent fields.

Nothing here calls a real provider or any paid API.
"""

import httpx
import pytest
import respx

from app.connectors.base import TokenSet, ToolContext
from app.connectors.registry import all_manifests
from app.workflows.patch import PatchError, apply_operations, parse_operations
from app.workflows.registry import get_registry, split_action
from tests.conftest import USER_A, USER_B, auth
from tests.test_agent import SHEET, connect, make_client  # noqa: F401

G = "https://www.googleapis.com/auth/"
DRIVE = "https://www.googleapis.com/drive/v3/files"
ID24 = "a" * 24
BASE = "app" + "A" * 14
DOC = "1DocAbCdEfGhIjKlMnOpQrStUvWx"


@pytest.fixture
async def ctx(settings):
    async with httpx.AsyncClient() as http:
        yield ToolContext(http=http, token=TokenSet(access_token="tok", extra={"api_key": "k"}), settings=settings)


def loader(connector: str, name: str):
    return all_manifests()[connector].loader(name)


async def run(connector, name, ctx, query=None, **params):
    return await loader(connector, name).handler(ctx, params, query)


FILES = {"files": [{"id": DOC, "name": "Test Leads", "webViewLink": "https://docs.google.com/x",
                    "modifiedTime": "2026-11-01T10:00:00Z"}]}


# ------------------------------------------------------------------ every loader, HTTP mocked

@respx.mock
@pytest.mark.parametrize("connector,name,mime", [
    ("google_sheets", "spreadsheets", "spreadsheet"), ("google_docs", "documents", "document"),
    ("google_slides", "presentations", "presentation"), ("google_forms", "forms", "form"),
    ("google_drive", "folders", "folder")])
async def test_google_file_loaders_search_drive_by_type(ctx, connector, name, mime):
    route = respx.get(DRIVE).respond(json=FILES)
    opts = await run(connector, name, ctx, query="Test leads")
    q = route.calls[0].request.url.params["q"]
    assert f"vnd.google-apps.{mime}" in q and "name contains 'Test'" in q and "trashed = false" in q
    assert opts == [{"value": DOC, "name": "Test Leads", "description": "Edited 2026-11-01",
                     "url": "https://docs.google.com/x"}]


@respx.mock
async def test_sheets_tabs_and_columns(ctx):
    respx.get(url__regex=r".*/v4/spreadsheets/" + SHEET + r"\?.*").respond(json={"properties": {"title": "Leads"}, "sheets": [
        {"properties": {"sheetId": 0, "title": "Sheet1", "index": 0, "gridProperties": {"rowCount": 100, "columnCount": 3}}},
        {"properties": {"sheetId": 1, "title": "Q4 data", "index": 1, "gridProperties": {"rowCount": 5, "columnCount": 2}}}]})
    tabs = await run("google_sheets", "tabs", ctx, spreadsheet_id=SHEET)
    assert [t["value"] for t in tabs] == ["Sheet1", "Q4 data"] and tabs[0]["description"] == "100 rows, 3 columns"

    values = respx.get(url__regex=r".*/values/.*").respond(json={"range": "Q4 data!A1:C1", "values": [["Name", "", "Email"]]})
    cols = await run("google_sheets", "columns", ctx, spreadsheet_id=SHEET, range="'Q4 data'!A:C")
    assert [c["value"] for c in cols] == ["Name", "Column B", "Email"]          # blank header keeps its position
    assert "Q4%20data" in str(values.calls[0].request.url) and "1%3A1" in str(values.calls[0].request.url)


@respx.mock
async def test_columns_default_to_the_first_tab_and_a_missing_header_row_is_empty(ctx):
    respx.get(url__regex=r".*/v4/spreadsheets/" + SHEET + r"\?.*").respond(json={"sheets": [
        {"properties": {"title": "First", "gridProperties": {}}}]})
    respx.get(url__regex=r".*/values/.*").respond(json={"range": "First!1:1"})
    assert await run("google_sheets", "columns", ctx, spreadsheet_id=SHEET) == []


def test_tab_of_understands_a1_ranges():
    from app.connectors.google_sheets import tab_of

    assert tab_of("Sheet1!A:B") == "Sheet1" and tab_of("'My tab'!A1:B2") == "My tab"
    assert tab_of("'It''s'!A:A") == "It's" and tab_of("Sheet1") == "Sheet1"
    assert tab_of("A1:B2") is None and tab_of("") is None and tab_of(None) is None


@respx.mock
async def test_slides_loader_lists_slides(ctx):
    respx.get(url__regex=r".*/v1/presentations/.*").respond(json={"title": "Deck", "slides": [
        {"objectId": "s1", "pageElements": [{"shape": {"text": {"textElements": [{"textRun": {"content": "Hello"}}]}}}]},
        {"objectId": "s2"}]})
    opts = await run("google_slides", "slides", ctx, presentation_id=SHEET)
    assert [o["value"] for o in opts] == ["s1", "s2"] and opts[0]["name"] == "Slide 1"


@respx.mock
async def test_gmail_labels(ctx):
    respx.get(url__regex=r".*/labels$").respond(json={"labels": [{"id": "INBOX", "name": "INBOX", "type": "system"}]})
    assert (await run("gmail", "labels", ctx)) == [{"value": "INBOX", "name": "INBOX", "description": "system"}]


@respx.mock
async def test_task_lists_and_tasks(ctx):
    respx.get(url__regex=r".*/users/@me/lists").respond(json={"items": [{"id": "L1", "title": "Home"}]})
    assert (await run("google_tasks", "task_lists", ctx))[0]["value"] == "L1"
    respx.get(url__regex=r".*/lists/L1/tasks").respond(json={"items": [{"id": "T1", "title": "Pay rent", "due": "2026-12-01"}]})
    tasks = await run("google_tasks", "tasks", ctx, task_list_id="L1")
    assert tasks[0]["value"] == "T1" and tasks[0]["name"] == "Pay rent"


@respx.mock
async def test_calendars_and_upcoming_events(ctx):
    respx.get(url__regex=r".*/users/me/calendarList").respond(json={"items": [
        {"id": "primary", "summary": "Sam", "primary": True, "accessRole": "owner"}, {"id": "w@x", "summary": "Work"}]})
    cals = await run("google_calendar", "calendars", ctx)
    assert [c["name"] for c in cals] == ["Sam (primary)", "Work"]
    route = respx.get(url__regex=r".*/calendars/primary/events").respond(json={"items": [
        {"id": "e1", "summary": "Standup", "start": {"dateTime": "2026-11-13T09:00:00Z"}}]})
    events = await run("google_calendar", "events", ctx)
    assert events[0]["value"] == "e1" and "timeMin" in route.calls[0].request.url.params


@respx.mock
async def test_trello_boards_and_lists(ctx):
    respx.get("https://api.trello.com/1/members/me/boards").respond(json=[{"id": ID24, "name": "Roadmap", "url": "u"}])
    assert (await run("trello", "boards", ctx))[0]["name"] == "Roadmap"
    respx.get(f"https://api.trello.com/1/boards/{ID24}/lists").respond(json=[{"id": "b" * 24, "name": "To do"}])
    assert (await run("trello", "lists", ctx, board_id=ID24))[0]["name"] == "To do"
    assert (await run("trello", "lists", ctx))[0]["name"] == "Roadmap > To do"          # no board: every board


@respx.mock
async def test_airtable_bases_tables_fields(ctx):
    respx.get("https://api.airtable.com/v0/meta/bases").respond(json={"bases": [{"id": BASE, "name": "CRM", "permissionLevel": "create"}]})
    assert (await run("airtable", "bases", ctx))[0]["value"] == BASE
    respx.get(f"https://api.airtable.com/v0/meta/bases/{BASE}/tables").respond(json={"tables": [
        {"id": "tbl1", "name": "Leads", "fields": [{"name": "Name", "type": "singleLineText"}, {"name": "Email", "type": "email"}]}]})
    assert (await run("airtable", "tables", ctx, base_id=BASE))[0] == {"value": "tbl1", "name": "Leads", "description": "2 fields"}
    by_id = await run("airtable", "fields", ctx, base_id=BASE, table="tbl1")
    by_name = await run("airtable", "fields", ctx, base_id=BASE, table="Leads")
    assert [f["value"] for f in by_id] == ["Name", "Email"] == [f["value"] for f in by_name]
    assert await run("airtable", "fields", ctx, base_id=BASE, table="nope") == []


@respx.mock
async def test_asana_workspaces_and_projects(ctx):
    respx.get("https://app.asana.com/api/1.0/workspaces").respond(json={"data": [{"gid": "111", "name": "Acme"}]})
    assert (await run("asana", "workspaces", ctx))[0]["value"] == "111"
    respx.get("https://app.asana.com/api/1.0/projects").respond(json={"data": [{"gid": "222", "name": "Launch"}]})
    assert (await run("asana", "projects", ctx, workspace_gid="111"))[0]["name"] == "Launch"
    assert (await run("asana", "projects", ctx))[0]["name"] == "Acme > Launch"


@respx.mock
async def test_linear_teams(ctx):
    respx.post("https://api.linear.app/graphql").respond(json={"data": {"teams": {"nodes": [{"id": "t1", "key": "ENG", "name": "Engineering"}]}}})
    assert (await run("linear", "teams", ctx)) == [{"value": "t1", "name": "Engineering (ENG)"}]


@respx.mock
async def test_slack_channels_and_users(ctx):
    respx.post("https://slack.com/api/conversations.list").respond(json={"ok": True, "channels": [
        {"id": "C1", "name": "general", "is_member": True}, {"id": "C2", "name": "ops"}]})
    chans = await run("slack", "channels", ctx)
    assert [c["name"] for c in chans] == ["#general", "#ops"] and chans[1]["description"] == "invite the bot first"
    respx.post("https://slack.com/api/users.list").respond(json={"ok": True, "members": [{"id": "U1", "name": "ada", "real_name": "Ada L"}]})
    assert (await run("slack", "users", ctx))[0]["name"] == "Ada L"


@respx.mock
async def test_notion_pages_databases_and_parents(ctx):
    respx.post("https://api.notion.com/v1/search").respond(json={"results": [
        {"id": "p1", "object": "page", "url": "u1", "properties": {"title": {"type": "title", "title": [{"plain_text": "Notes"}]}}},
        {"id": "d1", "object": "database", "url": "u2", "title": [{"plain_text": "Tasks"}]}]})
    assert [o["value"] for o in await run("notion", "pages", ctx)] == ["p1"]
    assert [o["value"] for o in await run("notion", "databases", ctx)] == ["d1"]
    assert [o["value"] for o in await run("notion", "parents", ctx)] == ["p1", "d1"]


@respx.mock
async def test_github_repos_and_issues(ctx):
    respx.get("https://api.github.com/user/installations").respond(json={"installations": [{"id": 7}]})
    respx.get("https://api.github.com/user/installations/7/repositories").respond(json={"repositories": [
        {"full_name": "o/api", "private": True, "html_url": "u"}, {"full_name": "o/web", "private": False}]})
    assert [o["value"] for o in await run("github", "repos", ctx)] == ["o/api", "o/web"]
    assert [o["value"] for o in await run("github", "repos", ctx, query="WEB")] == ["o/web"]
    respx.get("https://api.github.com/repos/o/api/issues").respond(json=[
        {"number": 3, "title": "Bug", "state": "open", "html_url": "u", "labels": [], "user": {"login": "x"}}])
    issues = await run("github", "issues", ctx, repo="o/api")
    assert issues[0]["value"] == 3 and issues[0]["name"] == "#3 Bug"


# ------------------------------------------------------------------ the UI specs are consistent

def test_every_connector_with_resources_registers_loaders():
    for cid, m in all_manifests().items():
        if cid in ("stripe", "google_meet", "google_contacts"):      # nothing in these is picked from a list
            assert not m.loaders
        else:
            assert m.loaders, cid


def test_param_ui_points_at_real_loaders_tools_and_earlier_parameters():
    for cid, m in all_manifests().items():
        for tool_name, specs in m.param_ui.items():
            props = list(m.tool(tool_name).parameters["properties"])
            for param, spec in specs.items():
                assert param in props, (tool_name, param)
                assert spec["kind"] in ("locator", "options", "multi", "columns", "range")
                ldr = m.loader(spec["loader"])
                for dep in spec.get("depends_on", []):
                    assert dep in props and props.index(dep) < props.index(param), (tool_name, param, dep)
                for need in ldr.needs:
                    assert need in spec.get("depends_on", []), (tool_name, param, need)


def test_sheets_node_exposes_locator_range_and_column_mapper_in_the_catalog():
    nt = {n["type"]: n for n in get_registry().public()}["google_sheets__append_row"]
    props = nt["parameters"]["properties"]
    assert props["spreadsheet_id"]["x-ui"]["kind"] == "locator" and props["range"]["x-ui"]["depends_on"] == ["spreadsheet_id"]
    assert props["values"]["x-ui"] == {"kind": "columns", "loader": "columns", "depends_on": ["spreadsheet_id", "range"], "output": "array"}
    assert (nt["resource"], nt["operation"]) == ("Row", "Append")
    assert "x-ui" not in {n["type"]: n for n in get_registry().public()}["google_sheets__create_spreadsheet"]["parameters"]["properties"]["title"]


def test_resource_and_operation_are_derived_without_duplicates():
    assert split_action("trello__create_card") == ("Card", "Create")
    assert split_action("github__comment_on_issue") == ("Issue", "Comment on")
    assert split_action("google_calendar__free_busy") == ("Free busy", "Run")
    seen = {}
    for n in get_registry().all():
        if n.tool:
            key = (n.connector, *split_action(n.tool))
            assert key not in seen, (n.tool, seen.get(key))
            seen[key] = n.tool


# ------------------------------------------------------------------ the endpoint

URL = "/api/nodes/google_sheets__append_row/options"


def body(client_conn, parameter="spreadsheet_id", **extra):
    return {"parameter": parameter, "connection_id": client_conn["id"], "parameters": {}, **extra}


@respx.mock
async def test_endpoint_loads_options_and_caches_them_until_refresh(make_client, db, store):
    conn = await connect(db, store, "google_sheets")
    route = respx.get(DRIVE).respond(json=FILES)
    client = make_client(None)
    first = client.post(URL, json=body(conn), headers=auth()).json()
    assert first["cached"] is False and first["options"][0]["value"] == DOC and first["loader"] == "spreadsheets"
    assert client.post(URL, json=body(conn), headers=auth()).json()["cached"] is True and route.call_count == 1
    assert client.post(URL, json=body(conn, refresh=True), headers=auth()).json()["cached"] is False and route.call_count == 2
    assert client.post(URL, json=body(conn, query="sales"), headers=auth()).json()["cached"] is False      # other query
    assert route.call_count == 3


@respx.mock
async def test_cache_expires_and_is_per_connection_and_user(make_client, db, store):
    conn = await connect(db, store, "google_sheets")
    other = await connect(db, store, "google_sheets", label="second")
    route = respx.get(DRIVE).respond(json=FILES)
    client = make_client(None)
    svc = client.app.state.options
    now = [1000.0]
    svc._clock = lambda: now[0]
    client.post(URL, json=body(conn), headers=auth())
    client.post(URL, json=body(other), headers=auth())
    assert route.call_count == 2                                   # another account never shares a cache entry
    now[0] += 61
    assert client.post(URL, json=body(conn), headers=auth()).json()["cached"] is False and route.call_count == 3


@respx.mock
async def test_dependent_parameters_are_required_and_passed_through(make_client, db, store):
    conn = await connect(db, store, "google_sheets")
    client = make_client(None)
    r = client.post(URL, json=body(conn, "range"), headers=auth())
    assert r.status_code == 422 and r.json()["detail"]["code"] == "missing_dependency"
    respx.get(url__regex=r".*/v4/spreadsheets/" + SHEET + r"\?.*").respond(json={"sheets": [{"properties": {"title": "Sheet1", "gridProperties": {}}}]})
    ok = client.post(URL, json=body(conn, "range", parameters={"spreadsheet_id": SHEET}), headers=auth())
    assert ok.status_code == 200 and ok.json()["options"][0]["value"] == "Sheet1"


async def test_expression_dependencies_are_not_listed(make_client, db, store):
    conn = await connect(db, store, "google_sheets")
    r = make_client(None).post(URL, json=body(conn, "range", parameters={"spreadsheet_id": "{{ $json.sheet }}"}), headers=auth())
    assert r.status_code == 200 and r.json()["options"] == [] and r.json()["unresolved"] is True


@respx.mock
async def test_column_mapper_loads_headers(make_client, db, store):
    conn = await connect(db, store, "google_sheets")
    respx.get(url__regex=r".*/values/.*").respond(json={"range": "Sheet1!1:1", "values": [["Name", "Email"]]})
    r = make_client(None).post(URL, json=body(conn, "values", parameters={"spreadsheet_id": SHEET, "range": "Sheet1!A:B"}), headers=auth())
    assert [o["value"] for o in r.json()["options"]] == ["Name", "Email"]


@respx.mock
async def test_missing_scope_says_reconnect_and_never_calls_google(make_client, db, store):
    conn = await connect(db, store, "google_sheets", scopes=["openid", "email", G + "spreadsheets"])     # no Drive metadata
    route = respx.get(DRIVE).respond(json=FILES)
    r = make_client(None).post(URL, json=body(conn), headers=auth())
    assert r.status_code == 409 and r.json()["detail"]["code"] == "reconnect"
    assert "Reconnect Google Sheets" in r.json()["detail"]["message"] and not route.called
    # tabs only needs the Sheets scope, so it still works on that old connection
    respx.get(url__regex=r".*/v4/spreadsheets/" + SHEET + r"\?.*").respond(json={"sheets": []})
    ok = make_client(None).post(URL, json=body(conn, "range", parameters={"spreadsheet_id": SHEET}), headers=auth())
    assert ok.status_code == 200


@respx.mock
async def test_provider_errors_get_a_code_and_a_message(make_client, db, store, monkeypatch):
    conn = await connect(db, store, "google_sheets")
    client = make_client(None)
    import app.agent.tools as tools_mod

    async def no_sleep(_):
        return None

    monkeypatch.setattr(tools_mod, "_sleep", no_sleep)
    route = respx.get(DRIVE).respond(401, json={"error": {"message": "invalid"}})
    r = client.post(URL, json=body(conn), headers=auth())
    assert r.status_code == 409 and r.json()["detail"]["code"] == "reconnect"      # credentials rejected -> Reconnect
    assert db.tables["connections"][0]["status"] == "needs_reauth"                  # the card now shows Reconnect
    conn2 = await connect(db, store, "google_sheets", label="second")
    route.respond(500)
    r = client.post(URL, json=body(conn2), headers=auth())
    assert r.status_code == 502 and "Next step" in r.json()["detail"]["message"]


async def test_endpoint_refuses_foreign_wrong_and_unknown_things(make_client, db, store):
    mine = await connect(db, store, "google_sheets")
    theirs = await connect(db, store, "google_sheets", user=USER_B)
    slack = await connect(db, store, "slack")
    client = make_client(None)
    assert client.post(URL, json=body(theirs), headers=auth()).json()["detail"]["code"] == "no_connection"
    assert client.post(URL, json=body(slack), headers=auth()).json()["detail"]["code"] == "no_connection"
    assert client.post(URL, json=body(mine, "title"), headers=auth()).json()["detail"]["code"] == "no_loader"
    assert client.post("/api/nodes/nope/options", json=body(mine), headers=auth()).status_code == 404
    assert client.post("/api/nodes/manual_trigger/options", json=body(mine), headers=auth()).status_code == 404
    assert client.post(URL, json=body(mine)).status_code in (401, 403)


@respx.mock
async def test_slack_channel_dropdown_end_to_end(make_client, db, store):
    conn = await connect(db, store, "slack")
    respx.post("https://slack.com/api/conversations.list").respond(json={"ok": True, "channels": [{"id": "C1", "name": "general", "is_member": True}]})
    r = make_client(None).post("/api/nodes/slack__post_message/options", json=body(conn, "channel"), headers=auth())
    assert r.json()["options"][0] == {"value": "C1", "name": "#general", "description": "bot is a member"}


# ------------------------------------------------------------------ the chat agent shares the loader code

@respx.mock
async def test_chat_discovery_tool_and_canvas_loader_make_the_same_google_call(ctx):
    from app.connectors.registry import all_tools

    route = respx.get(DRIVE).respond(json=FILES)
    via_tool = await all_tools()["google_sheets__search_spreadsheets"][1].handler(ctx, query="leads", limit=25)
    via_loader = await run("google_sheets", "spreadsheets", ctx, query="leads")
    assert route.calls[0].request.url == route.calls[1].request.url
    assert via_tool["matches"][0]["id"] == via_loader[0]["value"]


# ------------------------------------------------------------------ patch: switch operation, clear dependent fields

def _apply(doc, ops):
    return apply_operations(doc, parse_operations(ops))


def _doc(node):
    return {"id": "w", "name": "w", "status": "draft", "version": 1, "settings": {}, "edges": [], "nodes": [node]}


def test_patch_switches_operation_and_drops_parameters_the_new_operation_lacks():
    node = {"id": "n1", "type": "google_sheets__append_row", "name": "Add", "position": {"x": 0, "y": 0},
            "connection_id": "c1", "parameters": {"spreadsheet_id": SHEET, "range": "Sheet1!A:B", "values": ["a"]}}
    out, _ = _apply(_doc(node), [{"op": "update_node", "id": "n1", "type": "google_sheets__get_values"}])
    n = out["nodes"][0]
    assert n["type"] == "google_sheets__get_values" and n["parameters"] == {"spreadsheet_id": SHEET, "range": "Sheet1!A:B"}
    assert n["connection_id"] == "c1" and n["name"] == "Add"


def test_patch_refuses_to_switch_to_another_app_or_unknown_type():
    node = {"id": "n1", "type": "google_sheets__append_row", "name": "Add", "position": {"x": 0, "y": 0}, "parameters": {}}
    for bad in ("slack__post_message", "if", "nope"):
        with pytest.raises(PatchError):
            _apply(_doc(node), [{"op": "update_node", "id": "n1", "type": bad}])


def test_patch_remove_parameters_clears_children_and_sets_the_parent_in_one_operation():
    node = {"id": "n1", "type": "google_sheets__append_row", "name": "Add", "position": {"x": 0, "y": 0},
            "parameters": {"spreadsheet_id": SHEET, "range": "Sheet1!A:B", "values": ["a"]}}
    out, _ = _apply(_doc(node), [{"op": "update_node", "id": "n1", "parameters": {"spreadsheet_id": "1New" + "x" * 20},
                                            "remove_parameters": ["range", "values"]}])
    assert out["nodes"][0]["parameters"] == {"spreadsheet_id": "1New" + "x" * 20}
