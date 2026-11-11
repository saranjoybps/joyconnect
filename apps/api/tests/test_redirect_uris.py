"""Redirect URIs: built from PUBLIC_API_BASE_URL, one per provider family, shared Google callback."""

import json
from datetime import datetime, timezone
from urllib.parse import parse_qs

import pytest
import respx

from app.core.config import Settings
from app.oauth.state import sign_state, verify_state
from tests.conftest import USER_A, auth
from tests.test_oauth_flow import _id_token, callback, start

TUNNEL = "https://random-words.trycloudflare.com"


def google_token(connector: str) -> dict:
    """A token response where Google granted everything the connector asked for."""
    from app.connectors.registry import get_manifest

    return {"access_token": "ya29.A", "refresh_token": "1//R", "expires_in": 3599, "token_type": "Bearer",
            "scope": " ".join(get_manifest(connector).scopes), "id_token": _id_token("a@gmail.com")}


GH_ID = "Iv23liABCDEFGH123456"


# ------------------------------------------------------------------ config

def test_redirect_uri_defaults_to_api_base_url():
    s = Settings(_env_file=None, api_base_url="http://localhost:8000/")
    assert s.redirect_uri("google") == "http://localhost:8000/api/oauth/callback/google"
    assert s.redirect_mode == "localhost"


def test_redirect_uri_uses_public_base_not_api_base():
    s = Settings(_env_file=None, api_base_url="http://localhost:8000", public_api_base_url=TUNNEL + "/")
    assert s.redirect_uri("slack") == f"{TUNNEL}/api/oauth/callback/slack"
    assert "localhost" not in s.redirect_uri("slack")
    assert s.redirect_mode == "tunnel"


@pytest.mark.parametrize("base", ["http://127.0.0.1:8000", "http://localhost:9000", "http://[::1]:8000"])
def test_loopback_hosts_count_as_localhost(base):
    assert Settings(_env_file=None, public_api_base_url=base).redirect_mode == "localhost"


def test_public_base_url_read_from_env_file(tmp_path):
    f = tmp_path / ".env.local"
    f.write_text(f"PUBLIC_API_BASE_URL={TUNNEL}\n")
    assert Settings(_env_file=f).public_api_base_url == TUNNEL


# ------------------------------------------------------------------ one URI per family

def test_catalog_shows_one_redirect_uri_built_from_public_base(client, settings):
    settings.public_api_base_url = TUNNEL
    cat = {c["id"]: c for c in client.get("/api/connectors", headers=auth()).json()}
    for cid in ("google_sheets", "google_docs", "google_calendar"):
        assert cat[cid]["redirect_uri"] == f"{TUNNEL}/api/oauth/callback/google"
        assert "redirect_uris" not in cat[cid]
    for cid in ("slack", "notion", "github"):
        assert cat[cid]["redirect_uri"] == f"{TUNNEL}/api/oauth/callback/{cid}"
    assert cat["slack"]["redirect_info"]["mode"] == "tunnel"
    assert cat["slack"]["redirect_info"]["localhost_redirect"] == "no"      # Slack docs: HTTPS required
    assert cat["google_sheets"]["redirect_info"]["localhost_redirect"] == "yes"


def test_catalog_localhost_mode(client):
    cat = {c["id"]: c for c in client.get("/api/connectors", headers=auth()).json()}
    assert cat["slack"]["redirect_info"]["mode"] == "localhost"
    assert cat["slack"]["redirect_info"]["note"]


@respx.mock
def test_authorize_and_token_exchange_use_public_base(client, settings):
    settings.public_api_base_url = TUNNEL
    _, q = start(client, "slack")
    assert q["redirect_uri"] == f"{TUNNEL}/api/oauth/callback/slack"
    route = respx.post("https://slack.com/api/oauth.v2.access").respond(json={
        "ok": True, "access_token": "xoxb-1", "token_type": "bot", "scope": "chat:write",
        "team": {"name": "Acme"}, "bot_user_id": "U1"})
    resp = callback(client, "slack", code="c", state=q["state"])
    assert resp.headers["location"].endswith("connected=slack")
    assert parse_qs(route.calls[0].request.content.decode())["redirect_uri"] == [f"{TUNNEL}/api/oauth/callback/slack"]


# ------------------------------------------------------------------ shared Google callback

@respx.mock
@pytest.mark.parametrize("connector", ["google_sheets", "google_docs", "google_calendar"])
def test_shared_google_callback_routes_by_state(client, db, settings, connector):
    _, q = start(client, connector)
    assert q["redirect_uri"].endswith("/api/oauth/callback/google")
    assert verify_state(settings.oauth_state_secret, q["state"])["p"] == connector
    route = respx.post("https://oauth2.googleapis.com/token").respond(json=google_token(connector))

    resp = callback(client, "google", code="c", state=q["state"])
    assert resp.status_code == 303
    assert resp.headers["location"] == f"http://localhost:3000/connections?connected={connector}"
    assert [c["provider"] for c in db.tables["connections"]] == [connector]
    assert parse_qs(route.calls[0].request.content.decode())["redirect_uri"] == [
        "http://localhost:8000/api/oauth/callback/google"]


def test_state_for_another_family_is_rejected_on_the_wrong_route(client):
    _, q = start(client, "google_sheets")
    resp = callback(client, "slack", code="c", state=q["state"])
    assert resp.headers["location"].endswith("error=invalid_state&provider=slack")


def test_family_route_rejects_unknown_names_and_bad_state(client):
    assert callback(client, "nope", code="c", state="x").status_code == 404
    assert callback(client, "google", code="c", state="garbage").headers["location"].endswith(
        "error=invalid_state&provider=google")
    assert callback(client, "google", code="c").headers["location"].endswith("error=invalid_state&provider=google")


# ------------------------------------------------------------------ legacy per-connector routes

@respx.mock
def test_legacy_callback_route_still_works_with_its_own_redirect_uri(client, db, settings):
    """A flow whose redirect_uri was the old per-connector URL must still finish on that route."""
    state = sign_state(settings.oauth_state_secret, USER_A, "google_sheets", "platform")
    db.tables.setdefault("oauth_states", []).append({
        "state": state, "user_id": USER_A, "provider": "google_sheets", "code_verifier": "v" * 50,
        "created_at": datetime.now(timezone.utc).isoformat()})
    route = respx.post("https://oauth2.googleapis.com/token").respond(json=google_token("google_sheets"))
    resp = callback(client, "google_sheets", code="c", state=state)
    assert resp.headers["location"] == "http://localhost:3000/connections?connected=google_sheets"
    assert parse_qs(route.calls[0].request.content.decode())["redirect_uri"] == [
        "http://localhost:8000/api/oauth/callback/google_sheets"]


def test_legacy_route_with_state_of_another_connector_is_rejected(client):
    _, q = start(client, "google_docs")
    assert callback(client, "google_sheets", code="c", state=q["state"]).headers["location"].endswith(
        "error=invalid_state&provider=google_sheets")


# ------------------------------------------------------------------ changed-URI banner

def _save_github(client):
    return client.post("/api/provider-apps/github", headers=auth(),
                       json={"values": {"client_id": GH_ID, "client_secret": "s3cret-value"}})


def test_redirect_change_is_flagged_then_acknowledged(client, settings):
    saved = _save_github(client).json()
    assert saved["redirect_uri_changed"] is False
    assert saved["registered_redirect_uri"] == "http://localhost:8000/api/oauth/callback/github"

    settings.public_api_base_url = TUNNEL
    gh = next(c for c in client.get("/api/connectors", headers=auth()).json() if c["id"] == "github")
    assert gh["setup"]["redirect_uri_changed"] is True

    acked = client.post("/api/provider-apps/github/redirect-uri/ack", headers=auth()).json()
    assert acked["redirect_uri_changed"] is False
    assert acked["registered_redirect_uri"] == f"{TUNNEL}/api/oauth/callback/github"
    assert "s3cret-value" not in json.dumps(acked)


def test_ack_without_saved_credentials_is_404(client, settings):
    settings.platform_defaults.clear()
    assert client.post("/api/provider-apps/github/redirect-uri/ack", headers=auth()).status_code == 404
