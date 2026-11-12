"""Agent hardening: chained tools, retry rules, token refresh failures, error classes, daily limits, run metadata.

The LLM is a FakeLLM and every HTTP call is mocked: no paid API is touched.
"""

import time

import httpx
import pytest
import respx

from app.agent import tools as tools_mod
from app.agent.llm import LLMResult
from app.agent.policy import redact_result, scrub
from app.agent.tools import BoundTool, ToolExecutor
from app.connectors.base import TokenSet, provider_error
from app.connectors.registry import get_manifest
from tests.conftest import USER_A, USER_B, auth
from tests.test_agent import FakeLLM, call, connect, events, make_client, names  # noqa: F401  (fixture)

BALANCE = "https://api.stripe.com/v1/balance"
TRELLO_CARDS = "https://api.trello.com/1/cards"
GMAIL_SEND = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"


@pytest.fixture
def sleeps(monkeypatch):
    """Replace the retry sleep: record the delays, never wait."""
    delays: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        delays.append(seconds)

    monkeypatch.setattr(tools_mod, "_sleep", fake_sleep)
    return delays


def bound_for(manifest_id: str, tool_name: str, conn: dict) -> BoundTool:
    m = get_manifest(manifest_id)
    return BoundTool(m, m.tool(tool_name), conn, conn)


async def executor(db, store, settings):
    http = httpx.AsyncClient()
    return ToolExecutor(db, store, http, settings), http


# ------------------------------------------------------------------ multi-step chaining

@respx.mock
async def test_agent_chains_several_tools_in_one_message(make_client, db, store):
    await connect(db, store, "stripe")
    respx.get(BALANCE).respond(json={"livemode": False, "available": [], "pending": []})
    respx.get("https://api.stripe.com/v1/customers").respond(json={"data": [], "has_more": False})
    llm = FakeLLM(
        call("stripe__get_balance", {}, id="c1"),
        call("stripe__list_customers", {"limit": 3, "email": None}, id="c2"),
        call("stripe__get_balance", {}, id="c3"),
        LLMResult(content="All done."),
    )
    client = make_client(llm)
    evs = events(client.post("/api/chat", json={"message": "check stripe"}, headers=auth()))
    assert names(evs).count("tool_result") == 3 and names(evs)[-1] == "done"
    assert len(llm.calls) == 4                                  # three tool steps + the final answer


@respx.mock
async def test_default_step_cap_is_eight_per_message(make_client, db, store, settings):
    assert settings.max_tool_steps == 8
    await connect(db, store, "stripe")
    respx.get(BALANCE).respond(json={"livemode": False, "available": [], "pending": []})
    llm = FakeLLM(*[call("stripe__get_balance", {}, id=f"c{i}") for i in range(12)])
    client = make_client(llm)
    evs = events(client.post("/api/chat", json={"message": "loop"}, headers=auth()))
    assert names(evs).count("tool_result") == 8
    assert "stopped after 8 steps" in "".join(d["text"] for e, d in evs if e == "token")


# ------------------------------------------------------------------ retries

@respx.mock
async def test_read_tool_retries_429_with_retry_after_then_succeeds(db, store, settings, sleeps):
    conn = await connect(db, store, "stripe")
    route = respx.get(BALANCE).mock(side_effect=[
        httpx.Response(429, headers={"Retry-After": "2"}),
        httpx.Response(200, json={"livemode": False, "available": [], "pending": []}),
    ])
    ex, http = await executor(db, store, settings)
    ok, result = await ex.execute(bound_for("stripe", "stripe__get_balance", conn), {})
    await http.aclose()
    assert ok and route.call_count == 2 and sleeps == [2.0]


@respx.mock
async def test_read_tool_backs_off_exponentially_on_5xx_then_reports_it(db, store, settings, sleeps):
    conn = await connect(db, store, "stripe")
    route = respx.get(BALANCE).respond(503)
    ex, http = await executor(db, store, settings)
    ok, result = await ex.execute(bound_for("stripe", "stripe__get_balance", conn), {})
    await http.aclose()
    assert not ok and route.call_count == settings.retry_max_attempts == 3
    assert sleeps == [0.5, 1.0]
    assert "having trouble" in result["error"]


@respx.mock
async def test_read_tool_retries_network_errors(db, store, settings, sleeps):
    conn = await connect(db, store, "stripe")
    route = respx.get(BALANCE).mock(side_effect=[
        httpx.ConnectTimeout("t"), httpx.Response(200, json={"livemode": True, "available": [], "pending": []})])
    ex, http = await executor(db, store, settings)
    ok, _ = await ex.execute(bound_for("stripe", "stripe__get_balance", conn), {})
    await http.aclose()
    assert ok and route.call_count == 2


@respx.mock
@pytest.mark.parametrize("status", [400, 403, 404])
async def test_client_errors_are_not_retried(db, store, settings, sleeps, status):
    conn = await connect(db, store, "stripe")
    route = respx.get(BALANCE).respond(status, json={"error": {"message": "nope"}})
    ex, http = await executor(db, store, settings)
    ok, _ = await ex.execute(bound_for("stripe", "stripe__get_balance", conn), {})
    await http.aclose()
    assert not ok and route.call_count == 1 and sleeps == []


@respx.mock
async def test_write_tools_are_never_retried(db, store, settings, sleeps):
    conn = await connect(db, store, "trello", token="tok")
    conn_token = TokenSet(access_token="tok", extra={"api_key": "k" * 32}, expires_at=int(time.time()) + 3600)
    await db.update("connections", {"id": conn["id"]}, {"secret_id": await store.put(USER_A, conn_token.payload())})
    conn = (await db.select("connections", {"id": conn["id"]}))[0]
    route = respx.post(TRELLO_CARDS).respond(500)
    ex, http = await executor(db, store, settings)
    ok, result = await ex.execute(bound_for("trello", "trello__create_card", conn),
                                  {"list_id": "a" * 24, "name": "x", "description": None})
    await http.aclose()
    assert not ok and route.call_count == 1 and sleeps == []


@respx.mock
async def test_destructive_tools_are_never_retried(db, store, settings, sleeps):
    conn = await connect(db, store, "gmail")
    route = respx.post(GMAIL_SEND).respond(429)
    ex, http = await executor(db, store, settings)
    ok, result = await ex.execute(bound_for("gmail", "gmail__send_email", conn),
                                  {"to": ["a@x.com"], "subject": "s", "body": "b", "cc": None, "bcc": None})
    await http.aclose()
    assert not ok and route.call_count == 1 and "rate limited" in result["error"]


# ------------------------------------------------------------------ token refresh

@respx.mock
async def test_expired_token_is_refreshed_once_centrally_before_the_call(db, store, settings):
    t = TokenSet(access_token="old", refresh_token="r", expires_at=int(time.time()) - 5)
    sid = await store.put(USER_A, t.payload())
    scopes = list(get_manifest("gmail").scopes)
    conn = await db.insert("connections", {"user_id": USER_A, "provider": "gmail", "account_label": "x",
                                           "scopes": scopes, "secret_id": sid})
    refresh = respx.post(GOOGLE_TOKEN).respond(json={"access_token": "NEW", "expires_in": 3600, "scope": " ".join(scopes)})
    labels = respx.get("https://gmail.googleapis.com/gmail/v1/users/me/labels").respond(json={"labels": []})
    ex, http = await executor(db, store, settings)
    conn = (await db.select("connections", {"id": conn["id"]}))[0]
    ok, _ = await ex.execute(bound_for("gmail", "gmail__list_labels", conn), {})
    await http.aclose()
    assert ok and refresh.call_count == 1
    assert labels.calls[0].request.headers["authorization"] == "Bearer NEW"


async def test_failed_refresh_shows_reconnect_state(db, store, settings):
    t = TokenSet(access_token="old", expires_at=int(time.time()) - 5)          # expired, no refresh token
    sid = await store.put(USER_A, t.payload())
    conn = await db.insert("connections", {"user_id": USER_A, "provider": "slack", "account_label": "x",
                                           "scopes": [], "secret_id": sid})
    ex, http = await executor(db, store, settings)
    ok, result = await ex.execute(bound_for("slack", "slack__list_channels", conn), {})
    await http.aclose()
    assert not ok and "reconnected" in result["error"] and result["kind"] == "auth"
    assert (await db.select("connections", {"id": conn["id"]}))[0]["status"] == "needs_reauth"


@respx.mock
async def test_provider_401_marks_the_connection_for_reconnect(db, store, settings, sleeps):
    conn = await connect(db, store, "stripe")
    respx.get(BALANCE).respond(401, json={"error": {"message": "Invalid API Key"}})
    ex, http = await executor(db, store, settings)
    ok, result = await ex.execute(bound_for("stripe", "stripe__get_balance", conn), {})
    await http.aclose()
    assert not ok and "Reconnect" in result["error"] and "Invalid API Key" in result["error"]
    assert (await db.select("connections", {"id": conn["id"]}))[0]["status"] == "needs_reauth"
    assert sleeps == []


# ------------------------------------------------------------------ error classes

@pytest.mark.parametrize("status,detail,kind,words", [
    (401, "", "auth", "rejected the credentials"),
    (403, "Request had insufficient authentication scopes", "scope", "missing a permission"),
    (403, "forbidden", "permission", "not allowed"),
    (404, "", "not_found", "not found"),
    (429, "", "rate_limit", "rate limited"),
    (500, "", "server", "having trouble"),
    (503, "", "server", "having trouble"),
    (422, "bad field", "invalid", "did not accept"),
])
def test_every_provider_error_class_has_a_plain_message(status, detail, kind, words):
    err = provider_error("Doing X", status, detail)
    assert err.kind == kind and words in str(err) and err.status == status
    assert err.retryable == (kind in ("rate_limit", "server"))


@respx.mock
@pytest.mark.parametrize("code,kind,words", [
    ("invalid_auth", "auth", "Reconnect Slack"),
    ("token_revoked", "auth", "Reconnect Slack"),
    ("missing_scope", "scope", "missing a permission"),
    ("channel_not_found", "not_found", "channel not found"),
    ("not_in_channel", "not_found", "/invite"),
])
async def test_slack_error_codes_are_classified(db, store, settings, code, kind, words):
    conn = await connect(db, store, "slack")
    respx.post("https://slack.com/api/conversations.list").respond(json={"ok": False, "error": code})
    ex, http = await executor(db, store, settings)
    ok, result = await ex.execute(bound_for("slack", "slack__list_channels", conn), {})
    await http.aclose()
    assert not ok and words in result["error"]


@respx.mock
async def test_slack_rate_limit_is_retried_for_reads(db, store, settings, sleeps):
    conn = await connect(db, store, "slack")
    route = respx.post("https://slack.com/api/conversations.list").mock(side_effect=[
        httpx.Response(429, headers={"Retry-After": "1"}), httpx.Response(200, json={"ok": True, "channels": []})])
    ex, http = await executor(db, store, settings)
    ok, _ = await ex.execute(bound_for("slack", "slack__list_channels", conn), {})
    await http.aclose()
    assert ok and route.call_count == 2 and sleeps == [1.0]


# ------------------------------------------------------------------ daily limits

async def test_daily_chat_limit_blocks_with_a_clear_message(make_client, db, store, settings):
    settings.daily_chat_message_limit = 2
    client = make_client(FakeLLM())
    codes = [client.post("/api/chat", json={"message": f"hi {i}"}, headers=auth()) for i in range(3)]
    assert [r.status_code for r in codes] == [200, 200, 429]
    assert "daily limit of 2 chat messages" in codes[2].json()["detail"] and "midnight UTC" in codes[2].json()["detail"]
    assert client.post("/api/chat", json={"message": "hi"}, headers=auth(USER_B)).status_code == 200   # per user


async def test_yesterdays_messages_do_not_count_and_zero_means_unlimited(make_client, db, store, settings):
    settings.daily_chat_message_limit = 1
    client = make_client(FakeLLM())
    old = (__import__("datetime").datetime.now(__import__("datetime").timezone.utc)
           - __import__("datetime").timedelta(days=1)).isoformat()
    await db.insert("messages", {"conversation_id": "c", "user_id": USER_A, "role": "user", "content": "old",
                                 "created_at": old})
    assert client.post("/api/chat", json={"message": "today"}, headers=auth()).status_code == 200
    assert client.post("/api/chat", json={"message": "again"}, headers=auth()).status_code == 429
    settings.daily_chat_message_limit = 0
    assert client.post("/api/chat", json={"message": "again"}, headers=auth()).status_code == 200


@respx.mock
async def test_daily_tool_run_limit_stops_calls_and_tells_the_model(make_client, db, store, settings):
    settings.daily_tool_run_limit = 1
    await connect(db, store, "stripe")
    respx.get(BALANCE).respond(json={"livemode": False, "available": [], "pending": []})
    llm = FakeLLM(call("stripe__get_balance", {}, id="c1"), call("stripe__get_balance", {}, id="c2"),
                  LLMResult(content="Limit hit."))
    client = make_client(llm)
    evs = events(client.post("/api/chat", json={"message": "twice"}, headers=auth()))
    results = [d for e, d in evs if e == "tool_result"]
    assert [r["ok"] for r in results] == [True, False]
    assert "Daily limit of 1 tool runs" in results[1]["summary"]
    assert len(await db.select("tool_runs", {"user_id": USER_A})) == 1       # nothing was executed or logged


# ------------------------------------------------------------------ run metadata and redaction

@respx.mock
async def test_tool_runs_record_connector_risk_duration_and_redacted_output(make_client, db, store):
    await connect(db, store, "stripe")
    leaked = "rk_live_abcdefghijklmnop1234"
    respx.get("https://api.stripe.com/v1/customers").respond(json={"data": [
        {"id": "cus_1", "name": f"Ada {leaked}", "email": "ada@x.com"}], "has_more": False})
    client = make_client(FakeLLM(call("stripe__list_customers", {"limit": 5, "email": None}), LLMResult(content="ok")))
    events(client.post("/api/chat", json={"message": "customers"}, headers=auth()))
    run = (await db.select("tool_runs", {"user_id": USER_A}))[0]
    assert run["connector"] == "stripe" and run["risk"] == "read" and run["status"] == "ok"
    assert isinstance(run["duration_ms"], int) and run["finished_at"]
    out = run["result_redacted"]
    assert out["customers"][0]["email"] == "ada@x.com"            # normal data is kept
    assert out["customers"][0]["name"] == "Ada [REDACTED]"        # the token-shaped value is masked
    assert leaked not in str(run)


def test_redaction_masks_secret_keys_and_token_shapes_and_caps_size():
    out = redact_result({"api_key": "x", "nested": {"authorization": "y"}, "t": "xoxb-1234567890-abcdefghij",
                         "big": ["z" * 100] * 500})
    assert out["api_key"] == "[REDACTED]" and out["nested"]["authorization"] == "[REDACTED]"
    assert out["t"] == "[REDACTED]"
    assert scrub("see rk_live_abcdefghijklmnop1234 now") == "see [REDACTED] now"
    huge = redact_result({"rows": [{"c": "q" * 250} for _ in range(100)], "more": ["w" * 250] * 100})
    assert len(str(huge)) < 7000
