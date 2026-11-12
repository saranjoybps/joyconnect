from __future__ import annotations

import json
from typing import Any

import httpx

from app.connectors.base import (
    ConnectorManifest, ResolvedApp, TokenSet, ToolContext, ToolDef, ToolError, default_parse_token_response,
    oauth_client_fields, object_schema, raise_for_status,
)

API = "https://api.notion.com/v1"
MAX_CHARS = 20_000


def _headers(ctx_or_token: ToolContext | TokenSet, settings) -> dict[str, str]:
    token = ctx_or_token.token if isinstance(ctx_or_token, ToolContext) else ctx_or_token
    return {"Authorization": f"Bearer {token.access_token}", "Notion-Version": settings.notion_version}


def parse_token_response(data: dict[str, Any]) -> TokenSet:
    token = default_parse_token_response(data)
    token.extra = {"workspace_id": data.get("workspace_id"), "workspace_name": data.get("workspace_name"),
                   "bot_id": data.get("bot_id")}
    return token


async def account_label(http: httpx.AsyncClient, token: TokenSet, settings) -> str | None:
    return token.extra.get("workspace_name") or token.extra.get("workspace_id")


async def revoke(http: httpx.AsyncClient, m: ConnectorManifest, token: TokenSet, settings,
                 app: ResolvedApp) -> None:
    client_id, client_secret = m.client_credentials(app)
    await http.post(
        f"{API}/oauth/revoke",
        json={"token": token.access_token},
        auth=httpx.BasicAuth(client_id, client_secret),
        headers={"Notion-Version": settings.notion_version},
    )


def _title(obj: dict) -> str:
    if obj.get("object") in ("database", "data_source"):
        return "".join(t.get("plain_text", "") for t in obj.get("title", []))
    for prop in obj.get("properties", {}).values():
        if prop.get("type") == "title":
            return "".join(t.get("plain_text", "") for t in prop.get("title", []))
    return ""


def _summ(obj: dict) -> dict:
    return {"id": obj.get("id"), "object": obj.get("object"), "title": _title(obj), "url": obj.get("url")}


def _rich_text(rts: list[dict]) -> str:
    return "".join(rt.get("plain_text", "") for rt in rts)


def _prop_value(prop: dict) -> Any:
    t = prop.get("type")
    v = prop.get(t)
    if t in ("title", "rich_text"):
        return _rich_text(v or [])
    if t in ("select", "status"):
        return (v or {}).get("name")
    if t == "multi_select":
        return [o.get("name") for o in v or []]
    if t == "date":
        return v
    if t == "people":
        return [p.get("name") or p.get("id") for p in v or []]
    if t in ("number", "checkbox", "url", "email", "phone_number", "created_time", "last_edited_time"):
        return v
    return f"<{t}>"


async def search(ctx: ToolContext, query: str) -> dict:
    resp = await ctx.http.post(f"{API}/search", json={"query": query, "page_size": 20},
                               headers=_headers(ctx, ctx.settings))
    raise_for_status(resp, "Notion search")
    return {"results": [_summ(r) for r in resp.json().get("results", [])]}


async def get_page(ctx: ToolContext, page_id: str) -> dict:
    h = _headers(ctx, ctx.settings)
    page = await ctx.http.get(f"{API}/pages/{page_id}", headers=h)
    raise_for_status(page, "Reading the Notion page")
    blocks = await ctx.http.get(f"{API}/blocks/{page_id}/children", params={"page_size": 100}, headers=h)
    raise_for_status(blocks, "Reading the Notion page content")
    lines = []
    for b in blocks.json().get("results", []):
        rt = (b.get(b.get("type"), {}) or {}).get("rich_text")
        if rt:
            lines.append(_rich_text(rt))
    text = "\n".join(lines)
    p = page.json()
    return {**_summ(p), "properties": {k: _prop_value(v) for k, v in p.get("properties", {}).items()},
            "text": text[:MAX_CHARS], "truncated": len(text) > MAX_CHARS}


async def query_database(ctx: ToolContext, database_id: str, filter: str | None) -> dict:
    # Since Notion-Version 2025-09-03, rows live in data sources under a database.
    h = _headers(ctx, ctx.settings)
    db = await ctx.http.get(f"{API}/databases/{database_id}", headers=h)
    raise_for_status(db, "Reading the Notion database")
    sources = db.json().get("data_sources") or []
    if not sources:
        raise ToolError("This database has no data sources the integration can access.")
    body: dict[str, Any] = {"page_size": 50}
    if filter:
        try:
            body["filter"] = json.loads(filter)
        except json.JSONDecodeError as exc:
            raise ToolError("filter must be a JSON object in Notion filter format") from exc
    resp = await ctx.http.post(f"{API}/data_sources/{sources[0]['id']}/query", json=body, headers=h)
    raise_for_status(resp, "Querying the Notion database")
    rows = [
        {"id": r.get("id"), "url": r.get("url"),
         "properties": {k: _prop_value(v) for k, v in r.get("properties", {}).items()}}
        for r in resp.json().get("results", [])
    ]
    return {"data_source": sources[0].get("name"), "rows": rows, "has_more": resp.json().get("has_more", False)}


async def create_page(ctx: ToolContext, parent_id: str, title: str, content: str | None) -> dict:
    body: dict[str, Any] = {
        "parent": {"page_id": parent_id},
        "properties": {"title": {"title": [{"text": {"content": title}}]}},
    }
    if content:
        body["children"] = [
            {"object": "block", "type": "paragraph",
             "paragraph": {"rich_text": [{"type": "text", "text": {"content": para[:2000]}}]}}
            for para in content.split("\n\n") if para.strip()
        ][:100]
    resp = await ctx.http.post(f"{API}/pages", json=body, headers=_headers(ctx, ctx.settings))
    raise_for_status(resp, "Creating the Notion page")
    return _summ(resp.json())


ID = {"type": "string", "description": "Notion ID (from search results or a Notion URL)."}

MANIFEST = ConnectorManifest(
    id="notion",
    name="Notion",
    icon="/icons/notion.svg",
    description="Search, read and create pages in the Notion pages you share with the app.",
    auth_type="oauth2",
    authorize_url=f"{API}/oauth/authorize",
    token_url=f"{API}/oauth/token",
    scopes=[],
    extra_authorize_params={"owner": "user"},
    token_auth_style="basic",
    token_body_format="json",
    pkce=False,
    credential_fields=oauth_client_fields(
        id_help="notion.so/profile/integrations > your public integration > Configuration (OAuth Client ID).",
        secret_help="Same page: OAuth Client Secret.",
        id_pattern=r"[0-9a-fA-F-]{32,36}", id_hint="Notion client IDs are UUIDs",
    ),
    console_url="https://www.notion.so/profile/integrations",
    localhost_redirect="unverified",
    redirect_note="Notion's docs do not say whether http://localhost is accepted. Try localhost first; "
                  "if Notion rejects the redirect URI, use the public HTTPS tunnel.",
    setup_guide=[
        "Create a new integration at notion.so/profile/integrations and make it Public.",
        "Add the redirect URI below.",
        "Capabilities: Read content, Insert content, Update content.",
        "Copy the OAuth client ID and secret here. Users pick which pages to share when they connect.",
    ],
    parse_token_response=parse_token_response,
    account_label=account_label,
    revoke=revoke,
    health_tool="notion__search", health_args={"query": ""},
    tools=[
        ToolDef(
            name="notion__search",
            description="Search Notion pages and databases shared with the integration by title.",
            parameters=object_schema({"query": {"type": "string"}}),
            risk="read", handler=search,
        ),
        ToolDef(
            name="notion__get_page",
            description="Read a Notion page's properties and text content.",
            parameters=object_schema({"page_id": ID}),
            risk="read", handler=get_page,
        ),
        ToolDef(
            name="notion__query_database",
            description="List rows of a Notion database, optionally filtered.",
            parameters=object_schema({
                "database_id": ID,
                "filter": {"type": ["string", "null"],
                           "description": "Notion filter object encoded as a JSON string, or null for all rows."},
            }),
            risk="read", handler=query_database,
        ),
        ToolDef(
            name="notion__create_page",
            description="Create a new Notion page under an existing page.",
            parameters=object_schema({
                "parent_id": {**ID, "description": "ID of the parent page."},
                "title": {"type": "string"},
                "content": {"type": ["string", "null"], "description": "Body text; blank lines split paragraphs."},
            }),
            risk="write", handler=create_page,
        ),
    ],
)
