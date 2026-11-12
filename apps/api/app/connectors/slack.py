from __future__ import annotations

from typing import Any

import httpx

from app.connectors.base import (
    ConnectorManifest, OAuthError, ResolvedApp, TokenSet, ToolContext, ToolDef, ToolError,
    ProviderError, _retry_after, default_parse_token_response, oauth_client_fields, object_schema, provider_error,
)

SLACK_AUTH_ERRORS = {"invalid_auth", "not_authed", "token_revoked", "token_expired", "account_inactive"}

API = "https://slack.com/api"


def parse_token_response(data: dict[str, Any]) -> TokenSet:
    # Slack returns HTTP 200 with {"ok": false, "error": ...} on failure.
    if not data.get("ok", False):
        raise OAuthError(str(data.get("error") or "slack_error"))
    token = default_parse_token_response({k: v for k, v in data.items() if k != "error"})
    team = data.get("team") or {}
    token.extra = {"team_id": team.get("id"), "team_name": team.get("name"), "bot_user_id": data.get("bot_user_id")}
    return token


async def account_label(http: httpx.AsyncClient, token: TokenSet, settings) -> str | None:
    if token.extra.get("team_name"):
        return token.extra["team_name"]
    resp = await http.post(f"{API}/auth.test", headers={"Authorization": f"Bearer {token.access_token}"})
    data = resp.json()
    if not data.get("ok"):
        raise ToolError(f"Slack auth.test failed: {data.get('error')}")
    return data.get("team")


async def revoke(http: httpx.AsyncClient, m: ConnectorManifest, token: TokenSet, settings,
                 app: ResolvedApp) -> None:
    await http.post(f"{API}/auth.revoke", headers={"Authorization": f"Bearer {token.access_token}"})


async def _call(ctx: ToolContext, method: str, **kwargs: Any) -> dict:
    resp = await ctx.http.post(f"{API}/{method}", headers=ctx.bearer, **kwargs)
    if resp.status_code == 429:  # Slack: HTTP 429 + Retry-After
        raise provider_error(f"Slack {method}", 429, retry_after=_retry_after(resp))
    if resp.status_code >= 500:
        raise provider_error(f"Slack {method}", resp.status_code)
    data = resp.json()
    if not data.get("ok"):
        err = data.get("error", "unknown_error")
        if err in SLACK_AUTH_ERRORS:
            raise ProviderError(f"Slack {method} failed ({err}): Slack rejected the bot token. "
                                "Reconnect Slack on the Connections page.", "auth", 200)
        if err in ("missing_scope", "no_permission", "restricted_action"):
            raise ProviderError(f"Slack {method} failed ({err}): the app is missing a permission. Add the bot "
                                "scope in your Slack app, then reconnect Slack.", "scope", 200)
        if err in ("channel_not_found", "not_in_channel", "is_archived"):
            hint = " Invite the bot to the channel first (/invite @YourApp)." if err == "not_in_channel" else ""
            raise ProviderError(f"Slack {method} failed ({err}): channel not found or the bot is not in it.{hint}",
                                "not_found", 200)
        if err in ("ratelimited", "rate_limited"):
            raise ProviderError("Slack rate limited the request (429). Try again in a minute.", "rate_limit", 429)
        raise ToolError(f"Slack {method} failed: {err}.")
    return data


async def list_channels(ctx: ToolContext) -> dict:
    data = await _call(ctx, "conversations.list",
                       data={"types": "public_channel", "exclude_archived": "true", "limit": "200"})
    return {"channels": [
        {"id": c["id"], "name": c.get("name"), "is_member": c.get("is_member", False)}
        for c in data.get("channels", [])
    ]}


async def post_message(ctx: ToolContext, channel: str, text: str) -> dict:
    data = await _call(ctx, "chat.postMessage", json={"channel": channel.lstrip("#"), "text": text})
    return {"channel": data.get("channel"), "ts": data.get("ts")}


MANIFEST = ConnectorManifest(
    id="slack",
    name="Slack",
    icon="/icons/slack.svg",
    description="List channels and post messages as your workspace bot.",
    auth_type="oauth2",
    authorize_url="https://slack.com/oauth/v2/authorize",
    token_url=f"{API}/oauth.v2.access",
    scopes=["chat:write", "channels:read", "users:read"],
    scope_separator=",",
    token_auth_style="basic",
    pkce=False,
    credential_fields=oauth_client_fields(
        id_help="api.slack.com/apps > your app > Basic Information > App Credentials.",
        secret_help="Same page, next to the client ID.",
        id_pattern=r"[0-9]+\.[0-9]+", id_hint="Slack client IDs look like 1234567890.1234567890",
    ),
    console_url="https://api.slack.com/apps",
    localhost_redirect="no",
    redirect_note="Slack requires HTTPS redirect URLs (its docs: \"A Redirect URL must also use HTTPS\"). "
                  "http://localhost is not accepted: start the public HTTPS tunnel and register that URL.",
    setup_guide=[
        "Create an app at api.slack.com/apps (From scratch) in your workspace.",
        "OAuth & Permissions > Redirect URLs: add the redirect URI below. Slack requires HTTPS, "
        "so use the tunnel (scripts/dev-tunnel) for local development.",
        "OAuth & Permissions > Bot Token Scopes: add the scopes listed below.",
        "Basic Information > App Credentials: copy the client ID and client secret here.",
    ],
    invalid_client_errors=frozenset({"invalid_client_id", "bad_client_secret", "invalid_client"}),
    reauth_errors=frozenset({"invalid_grant", "invalid_refresh_token", "token_revoked", "token_expired"}),
    parse_token_response=parse_token_response,
    account_label=account_label,
    revoke=revoke,
    health_tool="slack__list_channels", health_args={},
    tools=[
        ToolDef(
            name="slack__list_channels",
            description="List public Slack channels (id, name, whether the bot is a member). "
                        "Use to find a channel ID before posting.",
            parameters=object_schema({}),
            risk="read", handler=list_channels,
        ),
        ToolDef(
            name="slack__post_message",
            description="Post a message to a Slack channel the bot is a member of.",
            parameters=object_schema({
                "channel": {"type": "string", "description": "Channel ID (preferred) or name without '#'."},
                "text": {"type": "string", "description": "Message text (Slack mrkdwn)."},
            }),
            risk="write", handler=post_message,
        ),
    ],
)
