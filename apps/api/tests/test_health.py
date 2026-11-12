"""Connector health checks: one cheap read-only call per connection, no LLM, plain-words results."""

import httpx
import respx

from app.cli.check_connections import format_table, run
from app.connectors.registry import all_manifests
from app.health import health_tool_for
from tests.conftest import USER_A, USER_B, auth
from tests.test_agent import connect, make_client  # noqa: F401  (fixture)

CAL_LIST = "https://www.googleapis.com/calendar/v3/users/me/calendarList"
USERINFO = "https://openidconnect.googleapis.com/v1/userinfo"
BALANCE = "https://api.stripe.com/v1/balance"


def test_every_connector_has_a_read_only_health_check():
    for m in all_manifests().values():
        picked = health_tool_for(m)
        assert picked is not None, m.id
        tool, _args = picked
        assert tool.risk == "read", m.id


@respx.mock
async def test_calendar_check_passes_and_is_stored(make_client, db, store):
    client = make_client(None)
    conn = await connect(db, store, "google_calendar")
    respx.get(CAL_LIST).respond(json={"items": [{"id": "primary", "summary": "Me", "primary": True}]})
    r = client.post(f"/api/connections/{conn['id']}/test", headers=auth()).json()
    assert r["ok"] is True and "Working" in r["message"]
    assert r["connection"]["last_check_ok"] is True and r["connection"]["last_checked_at"]
    listed = client.get("/api/connections", headers=auth()).json()[0]
    assert listed["last_check_ok"] is True and listed["last_check_message"].startswith("Working")


@respx.mock
async def test_auth_failure_shows_plain_words_and_reconnect_state(make_client, db, store):
    client = make_client(None)
    conn = await connect(db, store, "google_calendar")
    respx.get(CAL_LIST).respond(401, json={"error": {"message": "Invalid Credentials"}})
    r = client.post(f"/api/connections/{conn['id']}/test", headers=auth()).json()
    assert r["ok"] is False and "Reconnect" in r["message"] and "Invalid Credentials" in r["message"]
    assert r["connection"]["status"] == "needs_reauth"           # the card shows Reconnect


@respx.mock
async def test_service_without_cheap_read_tool_checks_the_token(make_client, db, store):
    client = make_client(None)
    conn = await connect(db, store, "google_sheets")
    route = respx.get(USERINFO).respond(json={"email": "a@x.com"})
    r = client.post(f"/api/connections/{conn['id']}/test", headers=auth()).json()
    assert r["ok"] is True and route.called


async def test_missing_permission_is_reported_without_calling_the_provider(make_client, db, store):
    client = make_client(None)
    scopes = ["openid", "email", "https://www.googleapis.com/auth/calendar.events"]
    conn = await connect(db, store, "google_calendar", scopes=scopes)
    with respx.mock(assert_all_called=False) as router:       # any HTTP call would fail the test
        r = client.post(f"/api/connections/{conn['id']}/test", headers=auth()).json()
        assert not router.calls
    assert r["ok"] is False and "Reconnect Google Calendar" in r["message"]


@respx.mock
async def test_permission_denied_and_rate_limit_messages(make_client, db, store):
    client = make_client(None)
    conn = await connect(db, store, "stripe")
    respx.get(BALANCE).respond(403, json={"error": {"message": "key lacks permission"}})
    r = client.post(f"/api/connections/{conn['id']}/test", headers=auth()).json()
    assert not r["ok"] and "not allowed" in r["message"] and "key lacks permission" in r["message"]
    respx.get(BALANCE).respond(429, headers={"Retry-After": "3"})
    r = client.post(f"/api/connections/{conn['id']}/test", headers=auth()).json()
    assert not r["ok"] and "rate limited" in r["message"]


async def test_only_the_owner_can_test_a_connection(make_client, db, store):
    client = make_client(None)
    conn = await connect(db, store, "stripe")
    assert client.post(f"/api/connections/{conn['id']}/test", headers=auth(USER_B)).status_code == 404
    assert client.post(f"/api/connections/{conn['id']}/test").status_code == 401


@respx.mock
async def test_cli_runs_the_same_checks_and_prints_no_secrets(db, store, settings):
    await connect(db, store, "stripe", label="live-acct", token="rk_test_SECRETVALUE123456")
    await connect(db, store, "airtable", label="at")
    respx.get(BALANCE).respond(json={"livemode": False, "available": [], "pending": []})
    respx.get("https://api.airtable.com/v0/meta/bases").respond(500)
    async with httpx.AsyncClient() as http:
        results = await run(db, store, http, settings, USER_A, None)
    text = format_table(results)
    assert "PASS" in text and "FAIL" in text and "1 passed, 1 failed" in text
    assert "SECRETVALUE" not in text
    assert [r["provider"] for r in results] == ["stripe", "airtable"]
    assert format_table([]) == "No connected accounts found."
