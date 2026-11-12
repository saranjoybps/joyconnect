"""Response contract: validated actions built from tool results, and the plain-text fallback."""
import json

import respx

from app.agent.llm import LLMResult
from app.agent.response import Action, action_from_message, build_action, find_link, plain_summary
from tests.conftest import auth
from tests.test_agent import SHEET, FakeLLM, call, connect, events, make_client, names  # noqa: F401


def test_find_link_prefers_known_keys_and_http_only():
    assert find_link({"spreadsheetUrl": "https://docs.google.com/spreadsheets/d/x", "id": "x"}).startswith("https://")
    assert find_link({"url": "javascript:alert(1)"}) is None
    assert find_link([{"html_url": "https://github.com/o/r/issues/1"}]) == "https://github.com/o/r/issues/1"
    assert find_link([{"url": "https://a"}, {"url": "https://b"}]) is None     # ambiguous
    assert find_link("nope") is None


def test_build_action_success_has_link_and_readable_result():
    a = build_action("c1", "google_sheets__create_spreadsheet", True,
                     {"title": "Leads", "spreadsheetUrl": "https://docs.google.com/spreadsheets/d/abc"})
    assert isinstance(a, Action) and a.ok and a.connector_name == "Google Sheets"
    assert a.label == "Create spreadsheet" and a.result == "Leads" and a.link.endswith("/abc") and a.error_kind is None


def test_build_action_error_kinds_and_secret_scrub():
    a = build_action("c1", "slack__post_message", False,
                     {"error": "Reconnect Slack: token xoxb-1234567890-abcdefghij rejected", "kind": "auth"})
    assert not a.ok and a.error_kind == "auth" and a.link is None and "xoxb-" not in a.result
    b = build_action("c2", "google_sheets__get_values", False, {"error": "Google did not grant the Sheets permission"})
    assert b.error_kind == "scope"
    assert build_action("c3", "notion__search", False, {"error": "boom"}).error_kind == "other"


def test_action_from_message_roundtrip_and_bad_content():
    a = action_from_message("c1", "notion__search", json.dumps([{"id": 1}, {"id": 2}]))
    assert a.ok and a.result == "2 items"
    assert action_from_message("c1", "notion__search", "not json at all").ok is True   # plain string is fine


def test_plain_summary_never_returns_raw_json():
    assert plain_summary("**Done**\n- one") == "**Done**\n- one"
    assert plain_summary('{"summary": "Added a row."}') == "Added a row."
    out = plain_summary('{"rows": [1, 2, 3], "x": {"y": 1}}')
    assert "{" not in out and "[" not in out
    assert plain_summary("[1, 2") == "[1, 2"          # not valid JSON: left alone


@respx.mock
async def test_tool_result_event_carries_validated_action(make_client, db, store):
    await connect(db, store, "google_sheets", auto=True)
    respx.post("https://sheets.googleapis.com/v4/spreadsheets").respond(
        json={"spreadsheetId": "abc", "spreadsheetUrl": "https://docs.google.com/spreadsheets/d/abc/edit",
              "properties": {"title": "Leads"}})
    llm = FakeLLM(call("google_sheets__create_spreadsheet", {"title": "Leads"}), LLMResult(content="**Created** Leads."))
    evs = events(make_client(llm).post("/api/chat", json={"message": "make a sheet"}, headers=auth()))
    result = next(d for e, d in evs if e == "tool_result")
    assert result["ok"] and result["action"]["connector"] == "google_sheets"
    assert result["action"]["link"].startswith("https://docs.google.com/spreadsheets/d/abc")
    conv = evs[-1][1]["conversation_id"]
    detail = make_client(llm).get(f"/api/conversations/{conv}", headers=auth()).json()
    tool_item = next(i for i in detail["items"] if i["kind"] == "tool")
    assert tool_item["action"]["link"] == result["action"]["link"]


async def test_failed_tool_action_marks_reconnect_kind(make_client, db, store):
    await connect(db, store, "google_sheets", auto=True, scopes=[])
    llm = FakeLLM(call("google_sheets__get_values", {"spreadsheet_id": SHEET, "range": "A1"}),
                  LLMResult(content="Please reconnect."))
    evs = events(make_client(llm).post("/api/chat", json={"message": "read"}, headers=auth()))
    res = next(d for e, d in evs if e == "tool_result")
    assert res["ok"] is False and res["action"]["error_kind"] in ("scope", "auth")
