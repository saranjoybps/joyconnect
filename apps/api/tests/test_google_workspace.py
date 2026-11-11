"""New Google Workspace connectors: authorize scopes, tool-to-scope mapping, happy and error paths (HTTP mocked)."""

import base64
import email
import json

import httpx
import pytest
import respx

from app.connectors.base import TokenSet, ToolContext, ToolError
from app.connectors.registry import all_manifests, all_tools
from tests.test_oauth_flow import start

G = "https://www.googleapis.com/auth/"
EXPECTED_SCOPES = {
    "gmail": [G + "gmail.send", G + "gmail.labels"],
    "google_drive": [G + "drive.file"],
    "google_slides": [G + "presentations"],
    "google_forms": [G + "forms.body", G + "forms.responses.readonly"],
    "google_tasks": [G + "tasks"],
    "google_contacts": [G + "contacts"],
    "google_meet": [G + "meetings.space.created"],
    "google_calendar": [G + "calendar.events", G + "calendar.calendarlist.readonly", G + "calendar.freebusy"],
}
RESTRICTED = ("gmail.readonly", "gmail.modify", "gmail.compose", "gmail.metadata",
              "drive.readonly", "drive.metadata", "mail.google.com")


@pytest.fixture
async def ctx(settings):
    async with httpx.AsyncClient() as http:
        yield ToolContext(http=http, token=TokenSet(access_token="tok"), settings=settings)


def tool(name):
    return all_tools()[name][1]


@pytest.mark.parametrize("cid,scopes", EXPECTED_SCOPES.items())
def test_authorize_url_requests_exactly_the_connector_scopes(client, cid, scopes):
    asked = start(client, cid)[1]["scope"].split(" ")
    for s in scopes:
        assert s in asked
    assert not [s for s in asked if s.startswith(G) and s not in scopes and "userinfo" not in s]


def test_no_restricted_scopes_anywhere():
    for m in all_manifests().values():
        for s in m.scopes:
            assert not any(r in s for r in RESTRICTED), (m.id, s)
            assert not s.endswith("/auth/drive"), (m.id, s)
    assert all_manifests()["google_drive"].scopes[-1] == G + "drive.file"
    assert G + "drive" not in all_manifests()["google_drive"].scopes


def test_gmail_has_no_draft_tool_and_send_is_destructive():
    names = [n for n in all_tools() if n.startswith("gmail__")]
    assert sorted(names) == ["gmail__list_labels", "gmail__send_email"]
    assert tool("gmail__send_email").risk == "destructive"


def test_every_new_tool_maps_to_scopes_the_connector_requests():
    for cid in EXPECTED_SCOPES:
        m = all_manifests()[cid]
        for t in m.tools:
            assert set(m.required_scopes(t)) <= set(m.scopes), t.name
    m = all_manifests()["gmail"]
    assert m.required_scopes(tool("gmail__send_email")) == [G + "gmail.send"]
    assert m.required_scopes(tool("gmail__list_labels")) == [G + "gmail.labels"]
    c = all_manifests()["google_calendar"]
    assert c.required_scopes(tool("google_calendar__free_busy")) == [G + "calendar.freebusy"]


def test_calendar_scope_labels_name_the_missing_permission():
    c = all_manifests()["google_calendar"]
    assert c.scope_name(G + "calendar.freebusy") == "Free/busy"
    assert c.scope_name(G + "calendar.events") == "Calendar events"


def test_setup_help_names_the_api_to_enable():
    for cid in EXPECTED_SCOPES:
        m = all_manifests()[cid]
        assert m.api_to_enable and m.api_to_enable in m.setup_guide[0]


# ------------------------------------------------------------------ Gmail
@respx.mock
async def test_gmail_send_happy(ctx):
    route = respx.post("https://gmail.googleapis.com/gmail/v1/users/me/messages/send").respond(
        json={"id": "m1", "threadId": "t1"})
    out = await tool("gmail__send_email").handler(ctx, to=["a@x.com"], subject="Hi", body="Hello", cc=None, bcc=None)
    assert out == {"sent": True, "message_id": "m1", "thread_id": "t1"}
    raw = json.loads(route.calls[0].request.content)["raw"]
    msg = email.message_from_bytes(base64.urlsafe_b64decode(raw))
    assert msg["To"] == "a@x.com" and msg["Subject"] == "Hi"


async def test_gmail_send_rejects_bad_address_and_header_injection(ctx):
    h = tool("gmail__send_email").handler
    with pytest.raises(ToolError):
        await h(ctx, to=["not-an-email"], subject="s", body="b", cc=None, bcc=None)
    with pytest.raises(ToolError):
        await h(ctx, to=["a@x.com"], subject="s\r\nBcc: evil@x.com", body="b", cc=None, bcc=None)


@respx.mock
async def test_gmail_labels_happy_and_rate_limit(ctx):
    route = respx.get("https://gmail.googleapis.com/gmail/v1/users/me/labels")
    route.respond(json={"labels": [{"id": "INBOX", "name": "INBOX", "type": "system"}]})
    assert (await tool("gmail__list_labels").handler(ctx))["labels"][0]["id"] == "INBOX"
    route.respond(429, headers={"Retry-After": "7"})
    with pytest.raises(ToolError, match="rate limited"):
        await tool("gmail__list_labels").handler(ctx)


# ------------------------------------------------------------------ Drive
@respx.mock
async def test_drive_folder_upload_list(ctx):
    respx.post("https://www.googleapis.com/drive/v3/files").respond(json={"id": "f1", "name": "Docs"})
    assert (await tool("google_drive__create_folder").handler(ctx, name="Docs", parent_id=None))["id"] == "f1"
    up = respx.post("https://www.googleapis.com/upload/drive/v3/files").respond(json={"id": "f2", "name": "a.txt"})
    out = await tool("google_drive__upload_text_file").handler(
        ctx, name="a.txt", content="hi", mime_type="text/plain", parent_id=None)
    assert out["id"] == "f2"
    assert up.calls[0].request.headers["content-type"].startswith("multipart/related; boundary=")
    lst = respx.get("https://www.googleapis.com/drive/v3/files").respond(json={"files": [{"id": "f1"}]})
    await tool("google_drive__list_files").handler(ctx, name_contains="O'Neil", folder_id=None, page_size=10)
    assert "name contains 'O\\'Neil'" in lst.calls[0].request.url.params["q"]


@respx.mock
async def test_drive_errors(ctx):
    respx.post("https://www.googleapis.com/drive/v3/files").respond(403, json={"error": {"message": "nope"}})
    with pytest.raises(ToolError):
        await tool("google_drive__create_folder").handler(ctx, name="x", parent_id=None)
    with pytest.raises(ToolError):
        await tool("google_drive__upload_text_file").handler(
            ctx, name="a.exe", content="", mime_type="application/x-msdownload", parent_id=None)


# ------------------------------------------------------------------ Slides
@respx.mock
async def test_slides_create_add_slide_add_text(ctx):
    respx.post("https://slides.googleapis.com/v1/presentations").respond(
        json={"presentationId": "P1", "slides": [{"objectId": "s0"}]})
    assert (await tool("google_slides__create_presentation").handler(ctx, title="T"))["presentation_id"] == "P1"
    b = respx.post("https://slides.googleapis.com/v1/presentations/P1:batchUpdate").respond(json={"replies": [{}]})
    await tool("google_slides__add_slide").handler(ctx, presentation_id="P1", layout="TITLE")
    await tool("google_slides__add_text").handler(
        ctx, presentation_id="P1", slide_id="s0", text="Hello", left_pt=None, top_pt=None)
    reqs = json.loads(b.calls[1].request.content)["requests"]
    assert "createShape" in reqs[0] and reqs[1]["insertText"]["text"] == "Hello"


@respx.mock
async def test_slides_errors(ctx):
    with pytest.raises(ToolError):
        await tool("google_slides__add_slide").handler(ctx, presentation_id="P1", layout="WEIRD")
    respx.post("https://slides.googleapis.com/v1/presentations/P1:batchUpdate").respond(
        404, json={"error": {"message": "gone"}})
    with pytest.raises(ToolError):
        await tool("google_slides__add_slide").handler(ctx, presentation_id="P1", layout="BLANK")


# ------------------------------------------------------------------ Forms
@respx.mock
async def test_forms_create_add_question_list(ctx):
    respx.post("https://forms.googleapis.com/v1/forms").respond(json={"formId": "F1", "responderUri": "https://x/r"})
    assert (await tool("google_forms__create_form").handler(ctx, title="T"))["form_id"] == "F1"
    respx.get("https://forms.googleapis.com/v1/forms/F1").respond(json={"items": [{"itemId": "a"}]})
    b = respx.post("https://forms.googleapis.com/v1/forms/F1:batchUpdate").respond(json={})
    out = await tool("google_forms__add_question").handler(
        ctx, form_id="F1", title="Colour?", question_type="dropdown", options=["Red", "Blue"], required=True)
    assert out["position"] == 2
    assert json.loads(b.calls[0].request.content)["requests"][0]["createItem"]["location"]["index"] == 1
    respx.get("https://forms.googleapis.com/v1/forms/F1/responses").respond(json={"responses": [
        {"responseId": "r1", "answers": {"q1": {"textAnswers": {"answers": [{"value": "Red"}]}}}}]})
    r = await tool("google_forms__list_responses").handler(ctx, form_id="F1", page_size=5)
    assert r["responses"][0]["answers"]["q1"] == ["Red"]


async def test_forms_choice_needs_options(ctx):
    with pytest.raises(ToolError):
        await tool("google_forms__add_question").handler(
            ctx, form_id="F1", title="q", question_type="checkbox", options=["only"], required=False)


# ------------------------------------------------------------------ Tasks
@respx.mock
async def test_tasks_flow_and_error(ctx):
    base = "https://tasks.googleapis.com/tasks/v1"
    respx.get(f"{base}/users/@me/lists").respond(json={"items": [{"id": "L1", "title": "My"}]})
    assert (await tool("google_tasks__list_task_lists").handler(ctx))["task_lists"][0]["id"] == "L1"
    respx.post(f"{base}/lists/L1/tasks").respond(json={"id": "T1", "title": "x"})
    created = await tool("google_tasks__create_task").handler(ctx, task_list_id="L1", title="x", notes=None, due=None)
    assert created["id"] == "T1"
    p = respx.patch(f"{base}/lists/L1/tasks/T1").respond(json={"id": "T1", "status": "completed"})
    await tool("google_tasks__complete_task").handler(ctx, task_list_id="L1", task_id="T1")
    assert json.loads(p.calls[0].request.content) == {"status": "completed"}
    respx.delete(f"{base}/lists/L1/tasks/T1").respond(404, json={"error": {"message": "x"}})
    with pytest.raises(ToolError):
        await tool("google_tasks__delete_task").handler(ctx, task_list_id="L1", task_id="T1")
    assert tool("google_tasks__delete_task").risk == "destructive"


# ------------------------------------------------------------------ Contacts
@respx.mock
async def test_contacts_list_search_create(ctx):
    respx.get("https://people.googleapis.com/v1/people/me/connections").respond(json={"connections": [
        {"resourceName": "people/c1", "names": [{"displayName": "Ada"}], "emailAddresses": [{"value": "a@x.com"}]}]})
    listed = await tool("google_contacts__list_contacts").handler(ctx, page_size=10)
    assert listed["contacts"][0]["name"] == "Ada"
    s = respx.get("https://people.googleapis.com/v1/people:searchContacts").respond(
        json={"results": [{"person": {"resourceName": "people/c1"}}]})
    out = await tool("google_contacts__search_contacts").handler(ctx, query="ada")
    assert len(s.calls) == 2 and out["contacts"][0]["resource_name"] == "people/c1"   # warm-up + real query
    respx.post("https://people.googleapis.com/v1/people:createContact").respond(json={"resourceName": "people/c2"})
    made = await tool("google_contacts__create_contact").handler(
        ctx, given_name="Bo", family_name=None, email=None, phone=None)
    assert made["resource_name"] == "people/c2"


@respx.mock
async def test_contacts_error(ctx):
    respx.post("https://people.googleapis.com/v1/people:createContact").respond(
        403, json={"error": {"message": "denied"}})
    with pytest.raises(ToolError):
        await tool("google_contacts__create_contact").handler(
            ctx, given_name="Bo", family_name=None, email=None, phone=None)


# ------------------------------------------------------------------ Meet
@respx.mock
async def test_meet_create_get_and_error(ctx):
    respx.post("https://meet.googleapis.com/v2/spaces").respond(json={
        "name": "spaces/s1", "meetingCode": "abc-defg-hij", "meetingUri": "https://meet.google.com/abc-defg-hij"})
    made = await tool("google_meet__create_space").handler(ctx)
    assert made["meeting_link"].startswith("https://meet.google.com/")
    respx.get("https://meet.googleapis.com/v2/spaces/s1").respond(
        json={"name": "spaces/s1", "meetingUri": "https://meet.google.com/x"})
    assert (await tool("google_meet__get_space").handler(ctx, space_id="spaces/s1"))["space_name"] == "spaces/s1"
    respx.get("https://meet.googleapis.com/v2/spaces/s2").respond(403, json={"error": {"message": "x"}})
    with pytest.raises(ToolError):
        await tool("google_meet__get_space").handler(ctx, space_id="s2")


# ------------------------------------------------------------------ extended Calendar / Docs / Sheets
@respx.mock
async def test_calendar_update_delete_freebusy(ctx):
    respx.patch(url__regex=r".*/calendars/primary/events/E1").respond(json={"id": "E1", "summary": "New"})
    args = dict(event_id="E1", summary="New", start=None, end=None, description=None, location=None,
                notify_attendees=False)
    await tool("google_calendar__update_event").handler(ctx, **args)
    with pytest.raises(ToolError):
        await tool("google_calendar__update_event").handler(ctx, **{**args, "summary": None})
    respx.delete(url__regex=r".*/calendars/primary/events/E1").respond(204)
    assert (await tool("google_calendar__delete_event").handler(ctx, event_id="E1", notify_attendees=False))["deleted"]
    respx.post("https://www.googleapis.com/calendar/v3/freeBusy").respond(json={"calendars": {"primary": {"busy": []}}})
    fb = await tool("google_calendar__free_busy").handler(
        ctx, time_min="2026-12-01T00:00:00Z", time_max="2026-12-02T00:00:00Z", calendar_ids=None)
    assert "primary" in fb["calendars"]
    respx.get("https://www.googleapis.com/calendar/v3/users/me/calendarList").respond(
        json={"items": [{"id": "c", "summary": "Main", "primary": True}]})
    assert (await tool("google_calendar__list_calendars").handler(ctx))["calendars"][0]["primary"]


@respx.mock
async def test_docs_and_sheets_extensions(ctx):
    respx.post(url__regex=r".*/documents/DOC123456789:batchUpdate").respond(
        json={"replies": [{"replaceAllText": {"occurrencesChanged": 3}}]})
    out = await tool("google_docs__replace_text").handler(
        ctx, document_id="DOC123456789", find="a", replace_with="b", match_case=True)
    assert out["occurrences_changed"] == 3
    with pytest.raises(ToolError):
        await tool("google_docs__insert_table").handler(ctx, document_id="DOC123456789", rows=0, columns=2)
    respx.get(url__regex=r".*/spreadsheets/SHEET123456(\?.*)?$").respond(
        json={"properties": {"title": "S"}, "sheets": [{"properties": {"sheetId": 0, "title": "Sheet1"}}]})
    tabs = await tool("google_sheets__list_tabs").handler(ctx, spreadsheet_id="SHEET123456")
    assert tabs["tabs"][0]["title"] == "Sheet1"
    respx.post(url__regex=r".*/spreadsheets/SHEET123456/values/.*:clear").respond(
        json={"clearedRange": "Sheet1!A1:B2"})
    cleared = await tool("google_sheets__clear_range").handler(
        ctx, spreadsheet_id="SHEET123456", range="Sheet1!A1:B2")
    assert cleared["cleared_range"]
    assert tool("google_sheets__clear_range").risk == "destructive"
