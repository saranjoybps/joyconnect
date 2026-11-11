from __future__ import annotations

from typing import Any

import httpx

from app.connectors.base import (
    ConnectorManifest, OAuthError, TokenSet, ToolContext, ToolDef, ToolError,
    default_parse_token_response, object_schema,
)

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


async def revoke(http: httpx.AsyncClient, m: ConnectorManifest, token: TokenSet, settings) -> None:
    await http.post(f"{API}/auth.revoke", headers={"Authorization": f"Bearer {token.access_token}"})


async def _call(ctx: ToolContext, method: str, **kwargs: Any) -> dict:
    resp = await ctx.http.post(f"{API}/{method}", headers=ctx.bearer, **kwargs)
    data = resp.json()
    if not data.get("ok"):
        err = data.get("error", "unknown_error")
        hint = " Invite the bot to the channel first (/invite @YourApp)." if err == "not_in_channel" else ""
        raise ToolError(f"Slack {method} failed: {err}.{hint}")
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
    client_id_setting="slack_client_id",
    client_secret_setting="slack_client_secret",
    reauth_errors=frozenset({"invalid_grant", "invalid_refresh_token", "token_revoked", "token_expired"}),
    parse_token_response=parse_token_response,
    account_label=account_label,
    revoke=revoke,
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
