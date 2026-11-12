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


async def search(ctx: ToolContext, workspace_gid: str, resource_type: str, query: str | None, count: int | None) -> dict:
    """Asana typeahead: find projects, tasks, users, tags... by name in one workspace."""
    d = _check(await ctx.http.get(f"{API}/workspaces/{_gid(workspace_gid, 'workspace_gid')}/typeahead",
                                  headers=ctx.bearer, params={
        "resource_type": resource_type, "query": query or "", "count": max(1, min(count or 10, 25)),
        "opt_fields": "name"}), "Searching Asana")
    return {"matches": [{"gid": r.get("gid"), "name": r.get("name"), "type": r.get("resource_type")}
                        for r in d["data"]]}


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


from app.connectors.base import LoaderDef, option  # noqa: E402


async def load_workspaces(ctx: ToolContext, params: dict, query: str | None) -> list[dict]:
    out = await list_workspaces(ctx)
    return [option(w["gid"], w["name"]) for w in out["workspaces"]]


async def load_projects(ctx: ToolContext, params: dict, query: str | None) -> list[dict]:
    """Projects of one workspace, or (none chosen) of every workspace, labelled "Workspace > Project"."""
    if params.get("workspace_gid"):
        return [option(p["gid"], p["name"]) for p in (await list_projects(ctx, params["workspace_gid"]))["projects"]]
    out: list[dict] = []
    for w in (await list_workspaces(ctx))["workspaces"][:10]:
        out += [option(p["gid"], f"{w['name']} > {p['name']}") for p in (await list_projects(ctx, w["gid"]))["projects"]]
    return out


LOADERS = [
    LoaderDef(name="workspaces", description="Your Asana workspaces.", handler=load_workspaces),
    LoaderDef(name="projects", description="Projects of a workspace (or of every workspace).", handler=load_projects),
]
_WS = {"kind": "options", "loader": "workspaces"}
_PROJECT = {"kind": "options", "loader": "projects"}
PARAM_UI = {
    "asana__list_projects": {"workspace_gid": _WS},
    "asana__search": {"workspace_gid": _WS},
    "asana__list_tasks": {"project_gid": _PROJECT},
    "asana__create_task": {"project_gid": _PROJECT},
}


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
    loaders=LOADERS, param_ui=PARAM_UI,
    tools=[
        ToolDef(name="asana__list_workspaces", description="List the user's Asana workspaces.",
                parameters=object_schema({}), risk="read", handler=list_workspaces),
        ToolDef(name="asana__list_projects", description="List active projects in a workspace.",
                parameters=object_schema({"workspace_gid": {"type": "string", "description": "From list_workspaces."}}),
                risk="read", handler=list_projects),
        ToolDef(name="asana__search",
                description="Find projects, tasks, users, tags, portfolios or teams by name in a workspace (up to "
                            "25 matches). Use to turn a name into a gid; never ask the user for a gid.",
                parameters=object_schema({
                    "workspace_gid": {"type": "string", "description": "From list_workspaces."},
                    "resource_type": {"enum": ["project", "task", "user", "tag", "portfolio", "team"]},
                    "query": {"type": ["string", "null"], "description": "Part of the name, or null."},
                    "count": {"type": ["integer", "null"], "description": "1 to 25, or null for 10."}}),
                risk="read", handler=search),
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
