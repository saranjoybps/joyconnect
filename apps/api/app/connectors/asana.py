"""Asana with a personal access token (developers.asana.com/docs).

Auth: `Authorization: Bearer <PAT>`. Responses wrap data in {"data": ...}; errors are {"errors":[{"message"}]}.
Rate limits: 429 with a Retry-After header.
"""

from __future__ import annotations

import re

from app.connectors._apikey import api_key_manifest, checked_get
from app.connectors.base import (CredentialField, Settings, TokenSet, ToolContext, ToolDef, ToolError,
                                 _retry_after, object_schema, provider_error)

API = "https://app.asana.com/api/1.0"
_GID_RE = re.compile(r"^[0-9]{1,30}$")


def _gid(value: str, what: str) -> str:
    if not _GID_RE.match(value or ""):
        raise ToolError(f"{what} must be a numeric Asana gid.")
    return value


def _check(resp, what: str) -> dict:
    if resp.status_code >= 400:
        try:
            msg = resp.json()["errors"][0]["message"]
        except Exception:  # noqa: BLE001
            msg = ""
        raise provider_error(what, resp.status_code, msg, _retry_after(resp))
    return resp.json()


async def validate(http, values: dict[str, str], settings: Settings):
    data = await checked_get(http, f"{API}/users/me", "Asana", headers={"Authorization": f"Bearer {values['api_key']}"})
    me = data.get("data", {})
    return TokenSet(access_token=values["api_key"]), me.get("email") or me.get("name")


async def list_workspaces(ctx: ToolContext) -> dict:
    d = _check(await ctx.http.get(f"{API}/workspaces", headers=ctx.bearer), "Listing workspaces")
    return {"workspaces": [{"gid": w["gid"], "name": w.get("name")} for w in d["data"]]}


async def list_projects(ctx: ToolContext, workspace_gid: str) -> dict:
    d = _check(await ctx.http.get(f"{API}/projects", headers=ctx.bearer, params={
        "workspace": _gid(workspace_gid, "workspace_gid"), "archived": "false", "limit": 100}), "Listing projects")
    return {"projects": [{"gid": p["gid"], "name": p.get("name")} for p in d["data"]]}


async def list_tasks(ctx: ToolContext, project_gid: str) -> dict:
    d = _check(await ctx.http.get(f"{API}/tasks", headers=ctx.bearer, params={
        "project": _gid(project_gid, "project_gid"), "limit": 100,
        "opt_fields": "name,completed,due_on,assignee.name"}), "Listing tasks")
    return {"tasks": [{"gid": t["gid"], "name": t.get("name"), "completed": t.get("completed"),
                       "due_on": t.get("due_on"), "assignee": (t.get("assignee") or {}).get("name")}
                      for t in d["data"]]}


async def create_task(ctx: ToolContext, project_gid: str, name: str, notes: str | None, due_on: str | None) -> dict:
    if not name.strip():
        raise ToolError("name must not be empty")
    data: dict = {"name": name, "projects": [_gid(project_gid, "project_gid")]}
    if notes:
        data["notes"] = notes
    if due_on:
        data["due_on"] = due_on
    d = _check(await ctx.http.post(f"{API}/tasks", headers=ctx.bearer, json={"data": data}), "Creating the task")
    t = d["data"]
    return {"gid": t.get("gid"), "name": t.get("name"), "url": t.get("permalink_url")}


MANIFEST = api_key_manifest(
    id="asana", name="Asana",
    description="List workspaces, projects and tasks, and create tasks in Asana.",
    credential_fields=[CredentialField(
        key="api_key", label="Personal access token", secret=True,
        help_text="Asana > Profile photo > Settings > Apps > Developer apps > Personal access tokens.")],
    validate=validate, console_url="https://app.asana.com/0/my-apps",
    setup_guide=["Open Asana > Settings > Apps > Manage Developer Apps > Create new token.",
                 "Copy the token (shown once) and paste it here."],
    health_tool="asana__list_workspaces",
    tools=[
        ToolDef(name="asana__list_workspaces", description="List the user's Asana workspaces.",
                parameters=object_schema({}), risk="read", handler=list_workspaces),
        ToolDef(name="asana__list_projects", description="List active projects in a workspace.",
                parameters=object_schema({"workspace_gid": {"type": "string", "description": "From list_workspaces."}}),
                risk="read", handler=list_projects),
        ToolDef(name="asana__list_tasks", description="List tasks in a project (up to 100).",
                parameters=object_schema({"project_gid": {"type": "string", "description": "From list_projects."}}),
                risk="read", handler=list_tasks),
        ToolDef(name="asana__create_task", description="Create a task in a project.",
                parameters=object_schema({"project_gid": {"type": "string", "description": "From list_projects."},
                                          "name": {"type": "string"}, "notes": {"type": ["string", "null"]},
                                          "due_on": {"type": ["string", "null"], "description": "YYYY-MM-DD or null."}}),
                risk="write", handler=create_task),
    ],
)
