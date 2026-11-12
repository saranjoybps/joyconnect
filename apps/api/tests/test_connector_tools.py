"""Tool handlers against mocked provider APIs, plus manifest invariants."""

import json

import httpx
import pytest
import respx

from app.connectors.base import TokenSet, ToolContext, ToolError
from app.connectors.registry import all_manifests, all_tools
from app.connectors._google import parse_google_file_id

SHEET = "1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"


@pytest.fixture
async def ctx(settings):
    async with httpx.AsyncClient() as http:
        yield ToolContext(http=http, token=TokenSet(access_token="tok"), settings=settings)


def test_all_tool_schemas_are_strict_and_named():
    tools = all_tools()
    assert len(tools) >= 19
    for name, (m, t) in tools.items():
        assert name.startswith(f"{m.id}__")
        assert t.parameters["additionalProperties"] is False
        assert t.risk in ("read", "write", "destructive")


def test_expected_risk_levels():
    tools = all_tools()
    reads = {"google_sheets__get_values", "google_docs__get_document", "google_calendar__list_events",
             "slack__list_channels", "notion__search", "notion__get_page", "notion__query_database",
             "github__list_repos", "github__list_issues"}
    read_suffixes = ("__get_", "__list_", "__search", "__free_busy", "__query_")
    for name, (_, t) in tools.items():
        is_read = name in reads or any(x in name for x in read_suffixes)
        assert (t.risk == "read") == is_read, name
    assert tools["gmail__send_email"][1].risk == "destructive"
    for n in ("google_calendar__delete_event", "google_sheets__clear_range", "google_tasks__delete_task"):
        assert tools[n][1].risk == "destructive", n


def test_manifests_use_minimum_scopes():
    m = all_manifests()
    assert m["google_sheets"].scopes == ["openid", "email", "https://www.googleapis.com/auth/spreadsheets"]
    assert m["google_docs"].scopes[-1] == "https://www.googleapis.com/auth/documents"
    assert "https://www.googleapis.com/auth/calendar.events" in m["google_calendar"].scopes
    assert m["slack"].scopes == ["chat:write", "channels:read"]
    for g in ("google_sheets", "google_docs", "google_calendar"):
        assert not any("drive" in s or "gmail" in s for s in m[g].scopes)


@pytest.mark.parametrize("value,expected", [
    (f"https://docs.google.com/spreadsheets/d/{SHEET}/edit#gid=0", SHEET),
    (f"https://docs.google.com/document/d/{SHEET}/edit", SHEET),
    (SHEET, SHEET),
])
def test_parse_google_id(value, expected):
    assert parse_google_file_id(value) == expected


def test_parse_google_id_rejects_junk():
    with pytest.raises(ValueError):
        parse_google_file_id("not an id!")


@respx.mock
async def test_sheets_append_row(ctx):
    route = respx.post(url__regex=rf".*/spreadsheets/{SHEET}/values/Sheet1%21A%3AC:append").respond(
        json={"updates": {"updatedRange": "Sheet1!A5:C5", "updatedCells": 3}})
    tool = all_tools()["google_sheets__append_row"][1]
    out = await tool.handler(ctx, spreadsheet_id=f"https://docs.google.com/spreadsheets/d/{SHEET}/edit",
                             range="Sheet1!A:C", values=["Ada", "ada@x.com", "Lead"])
    assert out == {"updated_range": "Sheet1!A5:C5", "updated_cells": 3}
    req = route.calls[0].request
    assert json.loads(req.content) == {"values": [["Ada", "ada@x.com", "Lead"]]}
    assert req.url.params["valueInputOption"] == "USER_ENTERED"
    assert req.headers["authorization"] == "Bearer tok"


@respx.mock
async def test_sheets_error_is_tool_error(ctx):
    respx.get(url__regex=r".*/values/.*").respond(403, json={"error": {"message": "The caller does not have permission"}})
    with pytest.raises(ToolError, match="permission"):
        await all_tools()["google_sheets__get_values"][1].handler(ctx, spreadsheet_id=SHEET, range="A1")


@respx.mock
async def test_docs_create_with_content(ctx):
    respx.post("https://docs.googleapis.com/v1/documents").respond(json={"documentId": "D1"})
    upd = respx.post("https://docs.googleapis.com/v1/documents/D1:batchUpdate").respond(json={})
    out = await all_tools()["google_docs__create_document"][1].handler(ctx, title="Notes", content="Hello")
    assert out["document_id"] == "D1"
    assert json.loads(upd.calls[0].request.content)["requests"][0]["insertText"] == {
        "text": "Hello", "endOfSegmentLocation": {}}


@respx.mock
async def test_calendar_create_event_all_day_and_mismatch(ctx):
    route = respx.post("https://www.googleapis.com/calendar/v3/calendars/primary/events").respond(
        json={"id": "e1", "summary": "Off", "start": {"date": "2026-11-12"}, "end": {"date": "2026-11-13"}})
    tool = all_tools()["google_calendar__create_event"][1]
    out = await tool.handler(ctx, summary="Off", start="2026-11-12", end="2026-11-13", attendees=None)
    assert out["start"] == "2026-11-12"
    assert json.loads(route.calls[0].request.content)["start"] == {"date": "2026-11-12"}
    with pytest.raises(ToolError):
        await tool.handler(ctx, summary="x", start="2026-11-12", end="2026-11-12T10:00:00Z", attendees=None)


@respx.mock
async def test_slack_post_not_in_channel(ctx):
    respx.post("https://slack.com/api/chat.postMessage").respond(json={"ok": False, "error": "not_in_channel"})
    with pytest.raises(ToolError, match="Invite the bot"):
        await all_tools()["slack__post_message"][1].handler(ctx, channel="#sales", text="hi")


@respx.mock
async def test_slack_post_strips_hash(ctx):
    route = respx.post("https://slack.com/api/chat.postMessage").respond(json={"ok": True, "channel": "C1", "ts": "1.2"})
    await all_tools()["slack__post_message"][1].handler(ctx, channel="#sales", text="hi")
    assert json.loads(route.calls[0].request.content)["channel"] == "sales"


@respx.mock
async def test_notion_query_database_uses_data_sources(ctx):
    respx.get("https://api.notion.com/v1/databases/DB1").respond(
        json={"object": "database", "data_sources": [{"id": "DS1", "name": "Tasks"}]})
    q = respx.post("https://api.notion.com/v1/data_sources/DS1/query").respond(json={"results": [
        {"id": "p1", "url": "u", "properties": {
            "Name": {"type": "title", "title": [{"plain_text": "Ship it"}]},
            "Status": {"type": "status", "status": {"name": "Done"}}}}], "has_more": False})
    out = await all_tools()["notion__query_database"][1].handler(
        ctx, database_id="DB1", filter='{"property":"Status","status":{"equals":"Done"}}')
    assert out["rows"][0]["properties"] == {"Name": "Ship it", "Status": "Done"}
    assert json.loads(q.calls[0].request.content)["filter"]["property"] == "Status"
    assert q.calls[0].request.headers["notion-version"] == ctx.settings.notion_version


async def test_notion_bad_filter(ctx):
    with respx.mock:
        respx.get("https://api.notion.com/v1/databases/DB1").respond(json={"data_sources": [{"id": "DS1"}]})
        with pytest.raises(ToolError):
            await all_tools()["notion__query_database"][1].handler(ctx, database_id="DB1", filter="{nope")


@respx.mock
async def test_github_list_issues_excludes_prs(ctx):
    respx.get("https://api.github.com/repos/o/r/issues").respond(json=[
        {"number": 1, "title": "Bug", "state": "open", "labels": [{"name": "bug"}]},
        {"number": 2, "title": "PR", "state": "open", "pull_request": {}},
    ])
    out = await all_tools()["github__list_issues"][1].handler(ctx, repo="o/r", state=None)
    assert [i["number"] for i in out["issues"]] == [1]


async def test_github_repo_validation(ctx):
    with pytest.raises(ToolError):
        await all_tools()["github__create_issue"][1].handler(ctx, repo="../../etc", title="t", body="b")


@respx.mock
async def test_github_list_repos_hint_when_not_installed(ctx):
    respx.get("https://api.github.com/user/installations").respond(json={"installations": []})
    out = await all_tools()["github__list_repos"][1].handler(ctx)
    assert out["repos"] == [] and "not installed" in out["hint"]
