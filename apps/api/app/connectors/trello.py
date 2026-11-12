"""Trello with an API key + token (developer.atlassian.com/cloud/trello/rest).

Auth: `key` and `token` query parameters on every request. Rate limits: 300 requests / 10 s per API key
and 100 / 10 s per token (429 on excess). The token is created with scope read,write.
"""

from __future__ import annotations

import re

from app.connectors._apikey import api_key_manifest, checked_get
from app.connectors.base import (CredentialField, Settings, TokenSet, ToolContext, ToolDef, ToolError,
                                 object_schema, raise_for_status)

API = "https://api.trello.com/1"
_ID_RE = re.compile(r"^[a-f0-9]{24}$")


def _id(value: str, what: str) -> str:
    if not _ID_RE.match(value or ""):
        raise ToolError(f"{what} must be a 24-character Trello id.")
    return value


def _auth(ctx: ToolContext) -> dict[str, str]:
    return {"key": ctx.token.extra["api_key"], "token": ctx.token.access_token}


async def validate(http, values: dict[str, str], settings: Settings):
    data = await checked_get(http, f"{API}/members/me", "Trello",
                             params={"key": values["api_key"], "token": values["token"], "fields": "username"})
    return TokenSet(access_token=values["token"], extra={"api_key": values["api_key"]}), data.get("username")


async def list_boards(ctx: ToolContext) -> dict:
    resp = await ctx.http.get(f"{API}/members/me/boards", params={**_auth(ctx), "fields": "name,url,closed", "filter": "open"})
    raise_for_status(resp, "Listing boards")
    return {"boards": [{"id": b["id"], "name": b.get("name"), "url": b.get("url")} for b in resp.json()]}


async def list_lists(ctx: ToolContext, board_id: str) -> dict:
    resp = await ctx.http.get(f"{API}/boards/{_id(board_id, 'board_id')}/lists",
                              params={**_auth(ctx), "fields": "name", "filter": "open"})
    raise_for_status(resp, "Listing lists")
    return {"lists": [{"id": x["id"], "name": x.get("name")} for x in resp.json()]}


async def list_cards(ctx: ToolContext, list_id: str) -> dict:
    resp = await ctx.http.get(f"{API}/lists/{_id(list_id, 'list_id')}/cards",
                              params={**_auth(ctx), "fields": "name,desc,url,due"})
    raise_for_status(resp, "Listing cards")
    return {"cards": [{"id": c["id"], "name": c.get("name"), "description": c.get("desc"), "due": c.get("due"),
                       "url": c.get("url")} for c in resp.json()[:100]]}


async def create_card(ctx: ToolContext, list_id: str, name: str, description: str | None) -> dict:
    if not name.strip():
        raise ToolError("name must not be empty")
    params = {**_auth(ctx), "idList": _id(list_id, "list_id"), "name": name}
    if description:
        params["desc"] = description
    resp = await ctx.http.post(f"{API}/cards", params=params)
    raise_for_status(resp, "Creating the card")
    c = resp.json()
    return {"id": c.get("id"), "name": c.get("name"), "url": c.get("url")}


MANIFEST = api_key_manifest(
    id="trello", name="Trello",
    description="List boards, lists and cards, and create cards in Trello.",
    credential_fields=[
        CredentialField(key="api_key", label="API key", pattern=r"[a-f0-9]{32}", pattern_hint="32 hex characters.",
                        help_text="From the Trello Power-Up admin page > API key."),
        CredentialField(key="token", label="Token", secret=True, pattern=r"(ATTA)?[A-Za-z0-9]{32,}",
                        pattern_hint="Generate it from the API key page ('generate a Token').",
                        help_text="Authorize with read and write access."),
    ],
    validate=validate, console_url="https://trello.com/power-ups/admin",
    setup_guide=["Create a Power-Up at trello.com/power-ups/admin to get an API key.",
                 "On the API key page click 'generate a Token' and allow read and write access.",
                 "Paste the key and the token here."],
    health_tool="trello__list_boards",
    tools=[
        ToolDef(name="trello__list_boards", description="List the user's open Trello boards (names and ids). Use first to find a board by name; never ask the user for a board id.",
                parameters=object_schema({}), risk="read", handler=list_boards),
        ToolDef(name="trello__list_lists", description="List the open lists (columns) on a board.",
                parameters=object_schema({"board_id": {"type": "string", "description": "Board id from list_boards."}}),
                risk="read", handler=list_lists),
        ToolDef(name="trello__list_cards", description="List the cards in a list (up to 100).",
                parameters=object_schema({"list_id": {"type": "string", "description": "List id from list_lists."}}),
                risk="read", handler=list_cards),
        ToolDef(name="trello__create_card", description="Create a card at the top of a list.",
                parameters=object_schema({"list_id": {"type": "string", "description": "List id from list_lists."},
                                          "name": {"type": "string"},
                                          "description": {"type": ["string", "null"]}}),
                risk="write", handler=create_card),
    ],
)
