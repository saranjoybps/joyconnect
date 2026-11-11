"""User-entered provider credentials: storage, masking, resolution order, full OAuth flow."""

import base64
import json
import logging
import time
from urllib.parse import parse_qs, urlparse

import pytest
import respx

from app.connectors.base import SetupRequired, TokenSet
from app.connectors.registry import get_manifest
from app.oauth.apps import ProviderAppService, mask
from tests.conftest import USER_A, USER_B, auth

SECRET = "ghsecret-SUPER-private-9f8e7d6c5b4a"
GH_ID = "Iv23liAbCdEfGh123456"
GOOGLE_ID = "123456789012-abcdefghijklmnop.apps.googleusercontent.com"
GOOGLE_SECRET = "GOCSPX-user-entered-secret-value"


@pytest.fixture
def no_platform(settings):
    settings.platform_defaults.clear()
    return settings


def save(client, provider, values, user=USER_A):
    return client.post(f"/api/provider-apps/{provider}", json={"values": values}, headers=auth(user))


def all_text(*responses) -> str:
    return "\n".join(r.text for r in responses)


# ------------------------------------------------------------------ storage and masking

def test_save_masks_and_never_returns_secret(client, db, no_platform):
    r1 = save(client, "github", {"client_id": GH_ID, "client_secret": SECRET, "app_slug": "my-connect"})
    assert r1.status_code == 200, r1.text
    body = r1.json()
    assert body["source"] == "user" and body["client_id_masked"] == mask(GH_ID) != GH_ID
    assert body["secrets_set"] == ["client_secret"] and body["fields"] == {"app_slug": "my-connect"}

    r2 = client.get("/api/provider-apps/github", headers=auth())
    r3 = client.get("/api/connectors", headers=auth())
    gh = next(c for c in r3.json() if c["id"] == "github")
    assert gh["configured"] is True
    assert gh["setup_url"] == "https://github.com/apps/my-connect/installations/new"
    assert gh["redirect_uris"] == ["http://localhost:8000/api/oauth/callback/github"]
    assert [f["key"] for f in gh["credential_fields"]] == ["client_id", "client_secret", "app_slug"]
    assert SECRET not in all_text(r1, r2, r3) and GH_ID not in all_text(r1, r2, r3)

    row = db.tables["provider_apps"][0]
    assert SECRET not in json.dumps(row)                         # secret only in the encrypted store
    assert SECRET not in json.dumps(db.tables["secrets"])


def test_google_app_is_shared_by_sheets_docs_calendar(client, no_platform):
    save(client, "google_sheets", {"client_id": GOOGLE_ID, "client_secret": GOOGLE_SECRET})
    catalog = {c["id"]: c for c in client.get("/api/connectors", headers=auth()).json()}
    for cid in ("google_sheets", "google_docs", "google_calendar"):
        assert catalog[cid]["configured"] and catalog[cid]["app_provider"] == "google"
    assert len(catalog["google_docs"]["redirect_uris"]) == 3
    assert catalog["slack"]["configured"] is False


@pytest.mark.parametrize("values,field,error", [
    ({"client_id": GH_ID}, "client_secret", "required"),
    ({"client_id": "not-a-github-id", "client_secret": SECRET}, "client_id", "start with Iv"),
    ({"client_id": GH_ID, "client_secret": SECRET, "evil": "x"}, "evil", "unknown field"),
])
def test_validation_errors(client, no_platform, values, field, error):
    r = save(client, "github", values)
    assert r.status_code == 422
    assert error in r.json()["detail"]["errors"][field]
    assert SECRET not in r.text


async def test_edit_keeps_secret_when_blank_and_replaces_blob(client, db, store, no_platform):
    save(client, "github", {"client_id": GH_ID, "client_secret": SECRET})
    old_secret_id = db.tables["provider_apps"][0]["secret_id"]
    new_id = "Iv23liZZZZZZZZZZZZZZZ"
    assert save(client, "github", {"client_id": new_id, "client_secret": ""}).status_code == 200
    row = db.tables["provider_apps"][0]
    assert row["client_id"] == new_id and row["secret_id"] != old_secret_id
    assert len(db.tables["secrets"]) == 1                       # old blob deleted
    app = await ProviderAppService(db, store, no_platform).resolve(USER_A, get_manifest("github"))
    assert app.values["client_secret"] == SECRET


def test_user_b_cannot_see_or_remove_user_a_app(client, no_platform):
    save(client, "github", {"client_id": GH_ID, "client_secret": SECRET})
    assert client.get("/api/provider-apps/github", headers=auth(USER_B)).json()["source"] == "none"
    gh_b = next(c for c in client.get("/api/connectors", headers=auth(USER_B)).json() if c["id"] == "github")
    assert gh_b["configured"] is False and gh_b["setup"]["client_id_masked"] is None
    assert client.delete("/api/provider-apps/github", headers=auth(USER_B)).status_code == 404
    assert client.post("/api/connections/github/start", headers=auth(USER_B)).status_code == 409


def test_unknown_provider(client):
    assert client.get("/api/provider-apps/nope", headers=auth()).status_code == 404


# ------------------------------------------------------------------ resolution order

async def test_resolution_order(db, store, settings):
    svc = ProviderAppService(db, store, settings)
    m = get_manifest("slack")
    # 1. no user app -> platform default
    app = await svc.resolve(USER_A, m)
    assert app.source == "platform" and app.values["client_id"] == "s-id" and app.state_ref == "platform"
    # 2. user app wins over platform
    await svc.save(USER_A, m, {"client_id": "111.222", "client_secret": "user-secret"})
    app = await svc.resolve(USER_A, m)
    assert app.source == "user" and app.values == {"client_id": "111.222", "client_secret": "user-secret"}
    assert "user-secret" not in repr(app)
    # other users still get the platform default
    assert (await svc.resolve(USER_B, m)).source == "platform"
    # 3. neither -> setup required
    settings.platform_defaults.clear()
    with pytest.raises(SetupRequired):
        await svc.resolve(USER_B, m)


async def test_platform_default_needs_every_required_field(db, store, settings):
    settings.platform_defaults = {"PLATFORM_SLACK_CLIENT_ID": "s-id"}
    with pytest.raises(SetupRequired):
        await ProviderAppService(db, store, settings).resolve(USER_A, get_manifest("slack"))


def test_platform_env_lookup(monkeypatch, settings):
    settings.platform_defaults.clear()
    settings.read_platform_env = True
    monkeypatch.setenv("PLATFORM_NOTION_CLIENT_ID", "env-id")
    assert settings.platform_value("notion", "client_id") == "env-id"


# ------------------------------------------------------------------ full flow with user-entered credentials

@respx.mock
async def test_full_oauth_flow_with_user_credentials(client, db, store, no_platform, caplog):
    caplog.set_level(logging.DEBUG)
    save(client, "github", {"client_id": GH_ID, "client_secret": SECRET, "app_slug": "my-connect"})
    app_id = db.tables["provider_apps"][0]["id"]

    # start: authorize URL carries the user's client id; signed state carries the app id
    r = client.post("/api/connections/github/start", headers=auth())
    q = {k: v[0] for k, v in parse_qs(urlparse(r.json()["authorize_url"]).query).items()}
    assert q["client_id"] == GH_ID and SECRET not in r.text
    state_payload = json.loads(base64.urlsafe_b64decode(q["state"].split(".")[0] + "=="))
    assert state_payload["a"] == app_id

    # callback: code exchanged with the user's secret
    token_route = respx.post("https://github.com/login/oauth/access_token").respond(json={
        "access_token": "ghu_A", "expires_in": 28800, "refresh_token": "ghr_R", "token_type": "bearer"})
    respx.get("https://api.github.com/user").respond(json={"login": "octocat"})
    cb = client.get("/api/oauth/callback/github", params={"code": "c", "state": q["state"]})
    assert cb.headers["location"].endswith("connected=github")
    sent = parse_qs(token_route.calls[0].request.content.decode())
    assert sent["client_id"] == [GH_ID] and sent["client_secret"] == [SECRET]
    conn = db.tables["connections"][0]
    assert conn["provider_app_id"] == app_id and conn["account_label"] == "octocat"

    # refresh uses the same app
    secret_row = await store.get(conn["secret_id"])
    secret_row["expires_at"] = int(time.time()) - 1
    db.tables["secrets"] = [s for s in db.tables["secrets"] if s["id"] != conn["secret_id"]]
    conn["secret_id"] = await store.put(USER_A, secret_row)
    token_route.respond(json={"access_token": "ghu_B", "expires_in": 28800, "refresh_token": "ghr_S"})
    assert client.post(f"/api/connections/{conn['id']}/check", headers=auth()).json() == {"status": "active"}
    refresh = parse_qs(token_route.calls[1].request.content.decode())
    assert refresh["grant_type"] == ["refresh_token"] and refresh["client_secret"] == [SECRET]

    # removing the app warns first, then disconnects (revoking with the user's credentials)
    warn = client.delete("/api/provider-apps/github", headers=auth())
    assert warn.status_code == 409 and warn.json()["detail"]["code"] == "has_connections"
    assert warn.json()["detail"]["connections"][0]["account_label"] == "octocat"
    revoke = respx.delete(f"https://api.github.com/applications/{GH_ID}/token").respond(204)
    done = client.delete("/api/provider-apps/github", params={"confirm": "true"}, headers=auth())
    assert done.json() == {"ok": True, "disconnected": 1}
    expected_basic = "Basic " + base64.b64encode(f"{GH_ID}:{SECRET}".encode()).decode()
    assert revoke.calls[0].request.headers["authorization"] == expected_basic
    assert db.tables["connections"][0]["status"] == "revoked"
    assert db.tables["provider_apps"] == [] and db.tables["secrets"] == []

    # the secret never reached a log line
    assert SECRET not in caplog.text


@respx.mock
def test_callback_fails_cleanly_if_app_removed_mid_flow(client, db, no_platform):
    save(client, "github", {"client_id": GH_ID, "client_secret": SECRET})
    r = client.post("/api/connections/github/start", headers=auth())
    state = parse_qs(urlparse(r.json()["authorize_url"]).query)["state"][0]
    client.delete("/api/provider-apps/github", headers=auth())
    cb = client.get("/api/oauth/callback/github", params={"code": "c", "state": state})
    assert "error=setup_required" in cb.headers["location"]
    assert db.tables.get("connections", []) == []


@respx.mock
async def test_platform_connection_keeps_platform_app(client, db, store, settings):
    """A connection made with the platform app keeps refreshing with it after the user adds their own."""
    r = client.post("/api/connections/notion/start", headers=auth())
    state = parse_qs(urlparse(r.json()["authorize_url"]).query)["state"][0]
    route = respx.post("https://api.notion.com/v1/oauth/token").respond(json={
        "access_token": "ntn_A", "refresh_token": "ntn_R", "expires_in": 3600, "workspace_name": "WS"})
    client.get("/api/oauth/callback/notion", params={"code": "c", "state": state})
    conn = db.tables["connections"][0]
    assert conn["provider_app_id"] is None

    save(client, "notion", {"client_id": "12345678-1234-1234-1234-123456789abc", "client_secret": "user-notion"})
    payload = await store.get(conn["secret_id"])
    payload["expires_at"] = int(time.time()) - 1
    conn["secret_id"] = await store.put(USER_A, payload)
    client.post(f"/api/connections/{conn['id']}/check", headers=auth())
    basic = route.calls[1].request.headers["authorization"]
    assert basic == "Basic " + base64.b64encode(b"n-id:n-secret").decode()


# ------------------------------------------------------------------ test endpoint

@respx.mock
@pytest.mark.parametrize("token_response,ok", [
    ((200, {"error": "bad_verification_code"}), True),
    ((200, {"error": "incorrect_client_credentials"}), False),
])
def test_credentials_probe(client, no_platform, token_response, ok):
    save(client, "github", {"client_id": GH_ID, "client_secret": SECRET})
    status, body = token_response
    route = respx.post("https://github.com/login/oauth/access_token").respond(status, json=body)
    r = client.post("/api/provider-apps/github/test", headers=auth())
    assert r.json()["ok"] is ok and r.json()["source"] == "user"
    assert parse_qs(route.calls[0].request.content.decode())["code"] == ["connect-credential-check"]
    assert SECRET not in r.text


@respx.mock
@pytest.mark.parametrize("provider,url,status,body,ok", [
    ("google", "https://oauth2.googleapis.com/token", 400, {"error": "invalid_grant"}, True),
    ("google", "https://oauth2.googleapis.com/token", 401, {"error": "invalid_client"}, False),
    ("slack", "https://slack.com/api/oauth.v2.access", 200, {"ok": False, "error": "invalid_code"}, True),
    ("slack", "https://slack.com/api/oauth.v2.access", 200, {"ok": False, "error": "bad_client_secret"}, False),
    ("notion", "https://api.notion.com/v1/oauth/token", 400, {"error": "invalid_grant"}, True),
    ("notion", "https://api.notion.com/v1/oauth/token", 401, {"error": "invalid_client"}, False),
])
def test_probe_each_provider(client, settings, provider, url, status, body, ok):
    settings.platform_defaults.update({
        "PLATFORM_GOOGLE_CLIENT_ID": GOOGLE_ID,
        "PLATFORM_SLACK_CLIENT_ID": "1234567890.0987654321",
        "PLATFORM_NOTION_CLIENT_ID": "12345678-1234-1234-1234-123456789abc",
    })
    respx.post(url).respond(status, json=body)
    assert client.post(f"/api/provider-apps/{provider}/test", headers=auth()).json()["ok"] is ok


def test_probe_requires_setup(client, no_platform):
    r = client.post("/api/provider-apps/slack/test", headers=auth())
    assert r.status_code == 409 and r.json()["detail"]["code"] == "setup_required"


def test_start_requires_setup(client, no_platform):
    r = client.post("/api/connections/google_docs/start", headers=auth())
    assert r.status_code == 409 and "not set up" in r.json()["detail"]["message"]


def test_probe_reports_format_errors(client):
    # Fixture platform defaults ("s-id") are not valid Slack client IDs.
    r = client.post("/api/provider-apps/slack/test", headers=auth()).json()
    assert r["ok"] is False and "client_id" in r["errors"]
