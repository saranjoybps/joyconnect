"""Linear with a personal API key (linear.app/developers/graphql).

Auth: `Authorization: <API_KEY>` (no "Bearer" prefix for personal keys). One GraphQL endpoint; errors can
arrive as HTTP 200 with an `errors` array. Rate limiting returns an error with code RATELIMITED.
Skipped: comments and issue updates (their mutation shapes were not confirmed from the docs).
"""

from __future__ import annotations

from typing import Any

from app.connectors._apikey import api_key_manifest
from app.connectors.base import (CredentialField, Settings, TokenSet, ToolContext, ToolDef, ToolError,
                                 object_schema, raise_for_status)

API = "https://api.linear.app/graphql"


async def gql(http, key: str, query: str, variables: dict | None = None) -> dict[str, Any]:
    resp = await http.post(API, json={"query": query, "variables": variables or {}},
                           headers={"Authorization": key, "Content-Type": "application/json"})
    if resp.status_code in (401, 403):
        raise ToolError(f"Linear rejected the API key ({resp.status_code}).")
    if resp.status_code != 400:
        raise_for_status(resp, "Linear request")
    body = resp.json()
    if body.get("errors"):
        err = body["errors"][0]
        code = (err.get("extensions") or {}).get("code")
        if code == "RATELIMITED":
            raise ToolError("Linear rate limited the request. Try again in a minute.")
        raise ToolError(f"Linear error: {err.get('message', 'request failed')}")
    return body["data"]


async def validate(http, values: dict[str, str], settings: Settings):
    data = await gql(http, values["api_key"], "query { viewer { name email } organization { name } }")
    return TokenSet(access_token=values["api_key"]), data["organization"]["name"]


async def list_teams(ctx: ToolContext) -> dict:
    data = await gql(ctx.http, ctx.token.access_token, "query { teams { nodes { id key name } } }")
    return {"teams": data["teams"]["nodes"]}


async def list_issues(ctx: ToolContext, team_id: str | None, first: int) -> dict:
    flt = {"team": {"id": {"eq": team_id}}} if team_id else {}
    data = await gql(ctx.http, ctx.token.access_token,
                     "query($first:Int,$filter:IssueFilter){ issues(first:$first, filter:$filter){ nodes "
                     "{ id identifier title url state { name } assignee { name } } } }",
                     {"first": max(1, min(first, 50)), "filter": flt})
    return {"issues": [{"id": i["id"], "identifier": i["identifier"], "title": i["title"], "url": i["url"],
                        "state": (i.get("state") or {}).get("name"),
                        "assignee": (i.get("assignee") or {}).get("name")} for i in data["issues"]["nodes"]]}


async def create_issue(ctx: ToolContext, team_id: str, title: str, description: str | None) -> dict:
    if not title.strip():
        raise ToolError("title must not be empty")
    data = await gql(ctx.http, ctx.token.access_token,
                     "mutation($input:IssueCreateInput!){ issueCreate(input:$input){ success issue "
                     "{ id identifier title url } } }",
                     {"input": {"teamId": team_id, "title": title, **({"description": description} if description else {})}})
    res = data["issueCreate"]
    if not res.get("success"):
        raise ToolError("Linear did not create the issue.")
    return res["issue"]


MANIFEST = api_key_manifest(
    id="linear", name="Linear",
    description="List teams and issues and create issues in Linear.",
    credential_fields=[CredentialField(
        key="api_key", label="Personal API key", secret=True, pattern=r"lin_api_[A-Za-z0-9]{20,}",
        pattern_hint="Starts with lin_api_.", help_text="Linear > Settings > Security & access > Personal API keys.")],
    validate=validate, console_url="https://linear.app/settings/account/security",
    setup_guide=["Open Linear > Settings > Security & access > Personal API keys.",
                 "Create a key (read and create access is enough) and paste it here."],
    tools=[
        ToolDef(name="linear__list_teams", description="List Linear teams (id, key, name). Needed to create issues.",
                parameters=object_schema({}), risk="read", handler=list_teams),
        ToolDef(name="linear__list_issues", description="List recent issues, optionally for one team.",
                parameters=object_schema({"team_id": {"type": ["string", "null"], "description": "Team id from list_teams, or null."},
                                          "first": {"type": "integer", "description": "1 to 50."}}),
                risk="read", handler=list_issues),
        ToolDef(name="linear__create_issue", description="Create an issue in a team.",
                parameters=object_schema({"team_id": {"type": "string", "description": "Team id from list_teams."},
                                          "title": {"type": "string"},
                                          "description": {"type": ["string", "null"], "description": "Markdown or null."}}),
                risk="write", handler=create_issue),
    ],
)
