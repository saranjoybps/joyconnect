"""End-to-end OAuth broker tests with mocked provider endpoints."""

import base64
import json
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx

from app.connectors.base import TokenSet
from app.connectors.registry import all_manifests
from tests.conftest import USER_A, USER_B, auth


def _id_token(email: str) -> str:
    claims = base64.urlsafe_b64encode(json.dumps({"email": email}).encode()).rstrip(b"=").decode()
    return f"h.{claims}.s"


def start(client, provider, user=USER_A):
    resp = client.post(f"/api/connections/{provider}/start", headers=auth(user))
    assert resp.status_code == 200, resp.text
    url = urlparse(resp.json()["authorize_url"])
    return url, {k: v[0] for k, v in parse_qs(url.query).items()}


def callback(client, provider, **params):
    return client.get(f"/api/oauth/callback/{provider}", params=params)


# ------------------------------------------------------------------ catalog / start

def test_registry_discovers_phase1_connectors():
    assert set(all_manifests()) >= {"google_sheets", "google_docs", "google_calendar", "slack", "notion", "github"}


def test_catalog(client):
    data = client.get("/api/connectors", headers=auth()).json()
    by_id = {c["id"]: c for c in data}
    assert by_id["slack"]["configured"] is True
    assert {"name": "slack__post_message", "risk": "write"} in by_id["slack"]["tools"]
    assert by_id["github"]["setup_url"] is None  # no slug configured


def test_start_requires_auth(client):
    assert client.post("/api/connections/slack/start").status_code == 401


def test_start_unknown_provider(client):
    assert client.post("/api/connections/nope/start", headers=auth()).status_code == 404


def test_start_unconfigured_provider(client, settings):
    settings.platform_defaults.pop("PLATFORM_SLACK_CLIENT_SECRET")
    resp = client.post("/api/connections/slack/start", headers=auth())
    assert resp.status_code == 409 and resp.json()["detail"]["code"] == "setup_required"


def test_google_authorize_url(client, db):
    url, q = start(client, "google_sheets")
    assert f"{url.scheme}://{url.netloc}{url.path}" == "https://accounts.google.com/o/oauth2/v2/auth"
    assert q["access_type"] == "offline" and q["prompt"] == "consent" and q["include_granted_scopes"] == "true"
    assert q["scope"].split(" ") == ["openid", "email", "https://www.googleapis.com/auth/spreadsheets"]
    assert q["redirect_uri"] == "http://localhost:8000/api/oauth/callback/google_sheets"
    assert q["code_challenge_method"] == "S256" and q["code_challenge"]
    row = db.tables["oauth_states"][0]
    assert row["state"] == q["state"] and row["user_id"] == USER_A and row["code_verifier"]
    assert row["code_verifier"] not in url.geturl()


def test_slack_authorize_url(client):
    _, q = start(client, "slack")
    assert q["scope"] == "chat:write,channels:read,users:read"
    assert "code_challenge" not in q


def test_notion_authorize_url(client):
    url, q = start(client, "notion")
    assert url.netloc == "api.notion.com" and q["owner"] == "user" and q["response_type"] == "code"


def test_old_states_are_purged_on_start(client, db):
    old = (datetime.now(timezone.utc) - timedelta(minutes=11)).isoformat()
    db.tables["oauth_states"] = [{"state": "stale", "user_id": USER_A, "provider": "slack", "created_at": old}]
    start(client, "slack")
    assert all(r["state"] != "stale" for r in db.tables["oauth_states"])


# ------------------------------------------------------------------ callbacks

@respx.mock
def test_google_callback_end_to_end(client, db, store):
    _, q = start(client, "google_sheets")
    route = respx.post("https://oauth2.googleapis.com/token").respond(json={
        "access_token": "ya29.A", "refresh_token": "1//R", "expires_in": 3599, "token_type": "Bearer",
        "scope": "openid email https://www.googleapis.com/auth/spreadsheets", "id_token": _id_token("a@gmail.com"),
    })
    resp = callback(client, "google_sheets", code="auth-code", state=q["state"])
    assert resp.status_code == 303
    assert resp.headers["location"] == "http://localhost:3000/connections?connected=google_sheets"

    sent = parse_qs(route.calls[0].request.content.decode())
    assert sent["grant_type"] == ["authorization_code"] and sent["code"] == ["auth-code"]
    assert sent["code_verifier"] and sent["client_secret"] == ["g-secret"]

    conn = db.tables["connections"][0]
    assert conn["provider"] == "google_sheets" and conn["account_label"] == "a@gmail.com"
    assert conn["status"] == "active" and conn["user_id"] == USER_A
    assert "ya29" not in json.dumps(db.tables)  # tokens only in encrypted form
    assert db.tables["oauth_states"] == []


@respx.mock
def test_state_is_single_use(client):
    _, q = start(client, "google_sheets")
    respx.post("https://oauth2.googleapis.com/token").respond(json={
        "access_token": "a", "expires_in": 3600, "id_token": _id_token("a@x.com")})
    assert "connected=" in callback(client, "google_sheets", code="c", state=q["state"]).headers["location"]
    assert "error=invalid_state" in callback(client, "google_sheets", code="c", state=q["state"]).headers["location"]


def test_forged_or_cross_provider_state_rejected(client):
    _, q = start(client, "slack")
    assert "error=invalid_state" in callback(client, "notion", code="c", state=q["state"]).headers["location"]
    assert "error=invalid_state" in callback(client, "slack", code="c", state="forged.state").headers["location"]
    assert "error=invalid_state" in callback(client, "slack", code="c").headers["location"]


def test_expired_state_row_rejected(client, db):
    _, q = start(client, "slack")
    db.tables["oauth_states"][0]["created_at"] = (datetime.now(timezone.utc) - timedelta(minutes=11)).isoformat()
    assert "error=invalid_state" in callback(client, "slack", code="c", state=q["state"]).headers["location"]


def test_user_denied_consent(client, db):
    _, q = start(client, "slack")
    resp = callback(client, "slack", error="access_denied", state=q["state"])
    assert "error=access_denied" in resp.headers["location"]
    assert db.tables.get("connections", []) == []


@respx.mock
def test_slack_callback_basic_auth_and_ok_false(client, db):
    _, q = start(client, "slack")
    route = respx.post("https://slack.com/api/oauth.v2.access").respond(json={"ok": False, "error": "invalid_code"})
    assert "error=invalid_code" in callback(client, "slack", code="c", state=q["state"]).headers["location"]
    assert route.calls[0].request.headers["authorization"] == "Basic " + base64.b64encode(b"s-id:s-secret").decode()
    assert "client_secret" not in route.calls[0].request.content.decode()

    _, q = start(client, "slack")
    route.respond(json={"ok": True, "access_token": "xoxb-1", "token_type": "bot", "scope": "chat:write,channels:read",
                        "bot_user_id": "B1", "team": {"id": "T1", "name": "Acme"}})
    assert "connected=slack" in callback(client, "slack", code="c", state=q["state"]).headers["location"]
    conn = db.tables["connections"][0]
    assert conn["account_label"] == "Acme" and conn["scopes"] == ["chat:write", "channels:read"]
    assert conn["expires_at"] is None


@respx.mock
def test_notion_callback_json_body_basic_auth(client, db):
    _, q = start(client, "notion")
    route = respx.post("https://api.notion.com/v1/oauth/token").respond(json={
        "access_token": "ntn_A", "refresh_token": "ntn_R", "bot_id": "b", "workspace_id": "w1",
        "workspace_name": "My WS", "token_type": "bearer"})
    assert "connected=notion" in callback(client, "notion", code="c", state=q["state"]).headers["location"]
    req = route.calls[0].request
    assert req.headers["content-type"] == "application/json"
    assert json.loads(req.content) == {"grant_type": "authorization_code", "code": "c",
                                       "redirect_uri": "http://localhost:8000/api/oauth/callback/notion"}
    assert req.headers["authorization"].startswith("Basic ")
    assert db.tables["connections"][0]["account_label"] == "My WS"


@respx.mock
def test_github_callback_pkce_and_label(client, db):
    _, q = start(client, "github")
    assert q["code_challenge_method"] == "S256"
    route = respx.post("https://github.com/login/oauth/access_token").respond(json={
        "access_token": "ghu_A", "expires_in": 28800, "refresh_token": "ghr_R",
        "refresh_token_expires_in": 15897600, "scope": "", "token_type": "bearer"})
    respx.get("https://api.github.com/user").respond(json={"login": "octocat"})
    assert "connected=github" in callback(client, "github", code="c", state=q["state"]).headers["location"]
    assert route.calls[0].request.headers["accept"] == "application/json"
    assert "code_verifier=" in route.calls[0].request.content.decode()
    assert db.tables["connections"][0]["account_label"] == "octocat"


@respx.mock
def test_github_error_in_200_body(client):
    _, q = start(client, "github")
    respx.post("https://github.com/login/oauth/access_token").respond(
        json={"error": "bad_verification_code", "error_description": "The code passed is incorrect"})
    assert "error=bad_verification_code" in callback(client, "github", code="c", state=q["state"]).headers["location"]


@respx.mock
def test_reconnect_replaces_secret(client, db):
    respx.post("https://slack.com/api/oauth.v2.access").respond(json={
        "ok": True, "access_token": "xoxb-1", "team": {"name": "Acme"}})
    for _ in range(2):
        _, q = start(client, "slack")
        callback(client, "slack", code="c", state=q["state"])
    assert len(db.tables["connections"]) == 1
    assert len(db.tables["secrets"]) == 1


# ------------------------------------------------------------------ list / disconnect / refresh

async def _seed(db, store, provider="google_sheets", user=USER_A, **token):
    t = TokenSet(access_token="ya29.OLD", refresh_token="1//R", expires_at=int(time.time()) + 3600, **token)
    sid = await store.put(user, t.payload())
    return await db.insert("connections", {"user_id": user, "provider": provider, "account_label": "a@x.com",
                                           "scopes": [], "secret_id": sid, "expires_at": None})


async def test_list_hides_secrets_and_other_users(client, db, store):
    await _seed(db, store)
    await _seed(db, store, user=USER_B)
    rows = client.get("/api/connections", headers=auth(USER_A)).json()
    assert len(rows) == 1 and "secret_id" not in rows[0] and rows[0]["provider"] == "google_sheets"


async def test_toggle_auto_approve(client, db, store):
    conn = await _seed(db, store)
    resp = client.patch(f"/api/connections/{conn['id']}", json={"auto_approve_writes": True}, headers=auth())
    assert resp.json()["auto_approve_writes"] is True
    assert client.patch(f"/api/connections/{conn['id']}", json={"auto_approve_writes": True},
                        headers=auth(USER_B)).status_code == 404


@respx.mock
async def test_disconnect_revokes_and_deletes(client, db, store):
    conn = await _seed(db, store)
    revoke = respx.post("https://oauth2.googleapis.com/revoke").respond(200)
    assert client.post(f"/api/connections/{conn['id']}/disconnect", headers=auth(USER_B)).status_code == 404
    assert client.post(f"/api/connections/{conn['id']}/disconnect", headers=auth()).json() == {"ok": True}
    assert parse_qs(revoke.calls[0].request.content.decode())["token"] == ["1//R"]
    assert db.tables["secrets"] == []
    assert db.tables["connections"][0]["status"] == "revoked"
    assert client.get("/api/connections", headers=auth()).json() == []


@respx.mock
async def test_disconnect_survives_provider_failure(client, db, store):
    conn = await _seed(db, store, provider="slack")
    respx.post("https://slack.com/api/auth.revoke").mock(side_effect=httpx.ConnectError("down"))
    assert client.post(f"/api/connections/{conn['id']}/disconnect", headers=auth()).status_code == 200
    assert db.tables["secrets"] == [] and db.tables["connections"][0]["status"] == "revoked"


@respx.mock
async def test_refresh_before_expiry(client, db, store):
    conn = await _seed(db, store)
    db.tables["secrets"].clear()
    t = TokenSet(access_token="ya29.OLD", refresh_token="1//R", expires_at=int(time.time()) + 30)
    sid = await store.put(USER_A, t.payload())
    db.tables["connections"][0]["secret_id"] = sid
    route = respx.post("https://oauth2.googleapis.com/token").respond(json={"access_token": "ya29.NEW", "expires_in": 3599})
    assert client.post(f"/api/connections/{conn['id']}/check", headers=auth()).json() == {"status": "active"}
    sent = parse_qs(route.calls[0].request.content.decode())
    assert sent["grant_type"] == ["refresh_token"] and sent["refresh_token"] == ["1//R"]
    new = await store.get(db.tables["connections"][0]["secret_id"])
    assert new["access_token"] == "ya29.NEW" and new["refresh_token"] == "1//R"  # old refresh token kept
    assert len(db.tables["secrets"]) == 1  # old secret deleted


@respx.mock
@pytest.mark.parametrize("provider,url,body", [
    ("google_sheets", "https://oauth2.googleapis.com/token", {"error": "invalid_grant"}),
    ("github", "https://github.com/login/oauth/access_token", {"error": "bad_refresh_token"}),
    ("notion", "https://api.notion.com/v1/oauth/token", {"error": "invalid_grant"}),
])
async def test_invalid_grant_marks_needs_reauth(client, db, store, provider, url, body):
    t = TokenSet(access_token="old", refresh_token="r", expires_at=int(time.time()) - 5)
    sid = await store.put(USER_A, t.payload())
    conn = await db.insert("connections", {"user_id": USER_A, "provider": provider, "account_label": "x",
                                           "scopes": [], "secret_id": sid})
    respx.post(url).respond(400 if provider != "github" else 200, json=body)
    assert client.post(f"/api/connections/{conn['id']}/check", headers=auth()).json() == {"status": "needs_reauth"}
    assert client.get("/api/connections", headers=auth()).json()[0]["status"] == "needs_reauth"


async def test_expired_without_refresh_token_needs_reauth(client, db, store):
    t = TokenSet(access_token="old", expires_at=int(time.time()) - 5)
    sid = await store.put(USER_A, t.payload())
    conn = await db.insert("connections", {"user_id": USER_A, "provider": "slack", "account_label": "x",
                                           "scopes": [], "secret_id": sid})
    assert client.post(f"/api/connections/{conn['id']}/check", headers=auth()).json() == {"status": "needs_reauth"}


@respx.mock
def test_label_lookup_failure_redirects_with_error(client, db):
    _, q = start(client, "github")
    respx.post("https://github.com/login/oauth/access_token").respond(json={"access_token": "ghu_A"})
    respx.get("https://api.github.com/user").respond(500)
    resp = callback(client, "github", code="c", state=q["state"])
    assert "error=provider_unavailable" in resp.headers["location"]
    assert db.tables.get("connections", []) == []


@respx.mock
def test_token_endpoint_network_error(client):
    _, q = start(client, "slack")
    respx.post("https://slack.com/api/oauth.v2.access").mock(side_effect=httpx.ConnectTimeout("t"))
    assert "error=provider_unavailable" in callback(client, "slack", code="c", state=q["state"]).headers["location"]
