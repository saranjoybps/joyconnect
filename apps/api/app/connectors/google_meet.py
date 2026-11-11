"""Google Meet REST API (docs: developers.google.com/workspace/meet/api).

Scope: meetings.space.created (create spaces and read/edit spaces this app created).
NOT used: meetings.space.readonly, meetings.space.settings (not needed).
"""

from __future__ import annotations

from app.connectors._google import google_manifest, path_id
from app.connectors.base import ToolContext, ToolDef, ToolError, object_schema, raise_for_status

API = "https://meet.googleapis.com/v2/spaces"
SCOPE = "https://www.googleapis.com/auth/meetings.space.created"


def _space(s: dict) -> dict:
    return {"space_name": s.get("name"), "meeting_code": s.get("meetingCode"), "meeting_link": s.get("meetingUri")}


async def create_space(ctx: ToolContext) -> dict:
    resp = await ctx.http.post(API, json={}, headers=ctx.bearer)
    raise_for_status(resp, "Creating the meeting space")
    return _space(resp.json())


async def get_space(ctx: ToolContext, space_id: str) -> dict:
    sid = space_id.removeprefix("spaces/")
    try:
        sid = path_id(sid, "space id")
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    resp = await ctx.http.get(f"{API}/{sid}", headers=ctx.bearer)
    raise_for_status(resp, "Reading the meeting space")
    return _space(resp.json())


MANIFEST = google_manifest(
    id="google_meet",
    name="Google Meet",
    description="Create meeting spaces and get their join links.",
    scopes=[SCOPE],
    api_to_enable="Google Meet REST API",
    tools=[
        ToolDef(name="google_meet__create_space",
                description="Create a new Google Meet meeting space and return its join link.",
                parameters=object_schema({}), risk="write", handler=create_space),
        ToolDef(name="google_meet__get_space",
                description="Get the join link of a meeting space this app created, by its space id or name.",
                parameters=object_schema({"space_id": {"type": "string", "description": "e.g. 'spaces/abc123' or 'abc123'."}}),
                risk="read", handler=get_space),
    ],
)
