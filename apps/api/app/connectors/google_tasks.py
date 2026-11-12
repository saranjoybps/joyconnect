"""Google Tasks (docs: developers.google.com/workspace/tasks). Scope: tasks (read and write)."""

from __future__ import annotations

from app.connectors._google import google_manifest, path_id
from app.connectors.base import ToolContext, ToolDef, ToolError, object_schema, raise_for_status

API = "https://tasks.googleapis.com/tasks/v1"
SCOPE = "https://www.googleapis.com/auth/tasks"
LIST_ID = {"type": "string", "description": "Task list id from list_task_lists (or '@default')."}
TASK_ID = {"type": "string", "description": "Task id from list_tasks or create_task."}


def _id(value: str, what: str) -> str:
    if value == "@default":
        return value
    try:
        return path_id(value, what)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc


def _task(t: dict) -> dict:
    return {"id": t.get("id"), "title": t.get("title"), "status": t.get("status"), "due": t.get("due"),
            "notes": t.get("notes")}


async def list_task_lists(ctx: ToolContext) -> dict:
    resp = await ctx.http.get(f"{API}/users/@me/lists", headers=ctx.bearer, params={"maxResults": 100})
    raise_for_status(resp, "Listing task lists")
    return {"task_lists": [{"id": i.get("id"), "title": i.get("title")} for i in resp.json().get("items", [])]}


async def list_tasks(ctx: ToolContext, task_list_id: str, show_completed: bool) -> dict:
    resp = await ctx.http.get(f"{API}/lists/{_id(task_list_id, 'task list id')}/tasks", headers=ctx.bearer,
                              params={"maxResults": 100, "showCompleted": str(show_completed).lower()})
    raise_for_status(resp, "Listing tasks")
    return {"tasks": [_task(t) for t in resp.json().get("items", [])]}


async def create_task(ctx: ToolContext, task_list_id: str, title: str, notes: str | None, due: str | None) -> dict:
    if not title.strip():
        raise ToolError("title must not be empty")
    body: dict = {"title": title}
    if notes:
        body["notes"] = notes
    if due:
        body["due"] = due  # RFC 3339; Google Tasks only stores the date part
    resp = await ctx.http.post(f"{API}/lists/{_id(task_list_id, 'task list id')}/tasks", json=body, headers=ctx.bearer)
    raise_for_status(resp, "Creating the task")
    return _task(resp.json())


async def complete_task(ctx: ToolContext, task_list_id: str, task_id: str) -> dict:
    resp = await ctx.http.patch(f"{API}/lists/{_id(task_list_id, 'task list id')}/tasks/{_id(task_id, 'task id')}",
                                json={"status": "completed"}, headers=ctx.bearer)
    raise_for_status(resp, "Completing the task")
    return _task(resp.json())


async def delete_task(ctx: ToolContext, task_list_id: str, task_id: str) -> dict:
    resp = await ctx.http.delete(f"{API}/lists/{_id(task_list_id, 'task list id')}/tasks/{_id(task_id, 'task id')}",
                                 headers=ctx.bearer)
    raise_for_status(resp, "Deleting the task")
    return {"deleted": True, "task_id": task_id}


from app.connectors.base import LoaderDef, option  # noqa: E402


async def load_task_lists(ctx: ToolContext, params: dict, query: str | None) -> list[dict]:
    out = await list_task_lists(ctx)
    return [option(t["id"], t["title"]) for t in out["task_lists"]]


async def load_tasks(ctx: ToolContext, params: dict, query: str | None) -> list[dict]:
    out = await list_tasks(ctx, params["task_list_id"], False)
    return [option(t["id"], t.get("title"), t.get("due")) for t in out["tasks"]]


LOADERS = [
    LoaderDef(name="task_lists", description="Your task lists.", handler=load_task_lists,
              scopes_of="google_tasks__list_task_lists"),
    LoaderDef(name="tasks", description="Open tasks of a task list.", handler=load_tasks,
              scopes_of="google_tasks__list_tasks", needs=["task_list_id"]),
]
_LIST = {"kind": "options", "loader": "task_lists"}
_TASK = {"kind": "options", "loader": "tasks", "depends_on": ["task_list_id"]}
PARAM_UI = {
    "google_tasks__list_tasks": {"task_list_id": _LIST},
    "google_tasks__create_task": {"task_list_id": _LIST},
    "google_tasks__complete_task": {"task_list_id": _LIST, "task_id": _TASK},
    "google_tasks__delete_task": {"task_list_id": _LIST, "task_id": _TASK},
}


MANIFEST = google_manifest(
    id="google_tasks",
    name="Google Tasks",
    description="List task lists, and create, complete and delete tasks.",
    scopes=[SCOPE],
    api_to_enable="Google Tasks API",
    health_tool="google_tasks__list_task_lists", health_args={},
    loaders=LOADERS, param_ui=PARAM_UI,
    tools=[
        ToolDef(name="google_tasks__list_task_lists", description="List the user's task lists (id and title).",
                parameters=object_schema({}), risk="read", handler=list_task_lists),
        ToolDef(name="google_tasks__list_tasks", description="List tasks in a task list.",
                parameters=object_schema({"task_list_id": LIST_ID,
                                          "show_completed": {"type": "boolean"}}),
                risk="read", handler=list_tasks),
        ToolDef(name="google_tasks__create_task", description="Create a task in a task list.",
                parameters=object_schema({
                    "task_list_id": LIST_ID, "title": {"type": "string"},
                    "notes": {"type": ["string", "null"]},
                    "due": {"type": ["string", "null"], "description": "RFC 3339 date-time, e.g. 2026-12-01T00:00:00Z, or null."},
                }), risk="write", handler=create_task),
        ToolDef(name="google_tasks__complete_task", description="Mark a task as completed.",
                parameters=object_schema({"task_list_id": LIST_ID, "task_id": TASK_ID}),
                risk="write", handler=complete_task),
        ToolDef(name="google_tasks__delete_task",
                description="Permanently delete a task. Only when the user clearly asks to delete it.",
                parameters=object_schema({"task_list_id": LIST_ID, "task_id": TASK_ID}),
                risk="destructive", handler=delete_task),
    ],
)
