"""Slack, Notion and GitHub end to end with mocked HTTP: setup help matches the official docs, health
checks, error mapping and GitHub's rotating refresh tokens."""

import time
from urllib.parse import parse_qs

import httpx
import respx

from app.connectors.base import TokenSet
from app.connectors.registry import get_manifest
from tests.conftest import USER_A, auth
from tests.test_agent import connect, make_client  # noqa: F401  (fixture)
from tests.test_oauth_flow import start


# ------------------------------------------------------------------ setup help vs the official docs

def test_slack_setup_matches_docs():
    m = get_manifest("slack")
    assert m.scopes == ["chat:write", "channels:read", "users:read"]   # users:read: slack__list_users
    assert m.scope_separator == "," and m.token_auth_style == "basic" and m.localhost_redirect == "no"
    guide = " ".join(m.setup_guide)
    assert "HTTPS" in guide and "/invite" in guide and "chat:write" in guide


def test_github_setup_asks_only_for_permissions_the_tools_use():
    guide = " ".join(get_manifest("github").setup_guide)
    assert "Issues read & write" in guide and "Expire user authorization tokens" in guide
    assert "Contents" not in guide and "Pull requests" not in guide


def test_notion_setup_uses_the_capability_names_in_the_docs():
    guide = " ".join(get_manifest("notion").setup_guide)
    for cap in ("Read content", "Insert content", "Update content"):
        assert cap in guide


def test_authorize_urls_follow_each_providers_docs(client):
    _, slack = start(client, "slack")
    assert slack["scope"] == "chat:write,channels:read,users:read" and "code_challenge" not in slack
    _, notion = start(client, "notion")
    assert notion["owner"] == "user" and notion["response_type"] == "code"
    _, gh = start(client, "github")
    assert gh["code_challenge_method"] == "S256" and len(gh["code_challenge"]) == 43 and "scope" not in gh


# ------------------------------------------------------------------ health checks through the real route

@respx.mock
async def test_slack_notion_github_health_checks_pass(make_client, db, store):
    client = make_client(None)
    respx.post("https://slack.com/api/conversations.list").respond(json={"ok": True, "channels": [{"id": "C1", "name": "general"}]})
    respx.post("https://api.notion.com/v1/search").respond(json={"results": []})
    respx.get("https://api.github.com/user/installations").respond(json={"installations": []})
    for provider in ("slack", "notion", "github"):
        conn = await connect(db, store, provider)
        r = client.post(f"/api/connections/{conn['id']}/test", headers=auth()).json()
        assert r["ok"] is True, (provider, r)


@respx.mock
async def test_notion_sends_the_version_header_and_maps_not_found(make_client, db, store, settings):
    client = make_client(None)
    conn = await connect(db, store, "notion")
    route = respx.post("https://api.notion.com/v1/search").respond(404, json={"message": "Could not find"})
    r = client.post(f"/api/connections/{conn['id']}/test", headers=auth()).json()
    assert r["ok"] is False and "not found" in r["message"]
    assert route.calls[0].request.headers["notion-version"] == settings.notion_version


@respx.mock
async def test_github_403_and_rate_limit_messages(make_client, db, store):
    client = make_client(None)
    conn = await connect(db, store, "github")
    respx.get("https://api.github.com/user/installations").respond(403, json={"message": "Resource not accessible by integration"})
    r = client.post(f"/api/connections/{conn['id']}/test", headers=auth()).json()
    assert not r["ok"] and "not allowed" in r["message"] and "Resource not accessible" in r["message"]
    respx.get("https://api.github.com/user/installations").respond(429, headers={"Retry-After": "5"})
    r = client.post(f"/api/connections/{conn['id']}/test", headers=auth()).json()
    assert not r["ok"] and "rate limited" in r["message"]


# ------------------------------------------------------------------ GitHub refresh tokens rotate

@respx.mock
async def test_github_refresh_stores_the_new_refresh_token(client, db, store):
    t = TokenSet(access_token="ghu_old", refresh_token="ghr_old", expires_at=int(time.time()) - 5)
    sid = await store.put(USER_A, t.payload())
    conn = await db.insert("connections", {"user_id": USER_A, "provider": "github", "account_label": "octo",
                                           "scopes": [], "secret_id": sid})
    route = respx.post("https://github.com/login/oauth/access_token").respond(json={
        "access_token": "ghu_new", "expires_in": 28800, "refresh_token": "ghr_new",
        "refresh_token_expires_in": 15897600, "scope": "", "token_type": "bearer"})
    respx.get("https://api.github.com/user").respond(json={"login": "octo"})      # /check re-reads the label
    assert client.post(f"/api/connections/{conn['id']}/check", headers=auth()).json() == {"status": "active"}
    sent = parse_qs(route.calls[0].request.content.decode())
    assert sent["grant_type"] == ["refresh_token"] and sent["refresh_token"] == ["ghr_old"]
    stored = await store.get((await db.select("connections", {"id": conn["id"]}))[0]["secret_id"])
    assert stored["access_token"] == "ghu_new" and stored["refresh_token"] == "ghr_new"   # old one is dead
