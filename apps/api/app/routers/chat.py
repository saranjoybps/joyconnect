from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.agent.modes import Mode, aliases, slug
from app.agent.response import action_from_message, plain_summary
from app.connectors.registry import get_manifest
from app.agent.runtime import AgentRuntime
from app.core.ratelimit import chat_rate_limit
from app.core.security import UserDep
from app.deps import DbDep
from app.routers._sse import sse_response

router = APIRouter(prefix="/api", tags=["chat"])


def get_runtime(request: Request) -> AgentRuntime:
    return request.app.state.runtime


RuntimeDep = Annotated[AgentRuntime, Depends(get_runtime)]


class ChatBody(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    conversation_id: str | None = None
    mode: str | None = Field(default=None, max_length=60)     # "custom" | "workflow" | a connector command


@router.post("/chat", dependencies=[Depends(chat_rate_limit)])
async def chat(body: ChatBody, user: UserDep, runtime: RuntimeDep):
    return await sse_response(runtime.chat(user.id, body.conversation_id, body.message, body.mode))


@router.get("/chat/modes")
async def chat_modes(user: UserDep, db: DbDep) -> list[dict[str, Any]]:
    """What typing / offers: /custom, /workflow and one command per connected app."""
    out: list[dict[str, Any]] = [
        {"command": "custom", "kind": "custom", "label": "Custom",
         "description": "Chat with all your connected apps (default)."},
        {"command": "workflow", "kind": "workflow", "label": "Workflow", "description": "Plan and build workflows."},
    ]
    apps: dict[str, dict[str, Any]] = {}
    for c in await db.select("connections", {"user_id": user.id, "status": "active"}, order="created_at.desc"):
        m = get_manifest(c["provider"])
        if m is not None and m.id not in apps:
            apps[m.id] = {"command": slug(m.id), "kind": "connector", "connector": m.id, "label": m.name,
                          "aliases": aliases(m.id), "description": f"Only use {m.name}."}
    return out + sorted(apps.values(), key=lambda a: a["label"].lower())


@router.get("/conversations")
async def list_conversations(user: UserDep, db: DbDep) -> list[dict[str, Any]]:
    rows = await db.select("conversations", {"user_id": user.id}, order="created_at.desc", limit=100)
    # One query for the one-line preview in the history panel: the newest assistant reply per conversation.
    previews: dict[str, str] = {}
    for m in await db.select("messages", {"user_id": user.id, "role": "assistant"}, order="created_at.desc", limit=400):
        cid = m.get("conversation_id")
        if cid and cid not in previews and m.get("content"):
            previews[cid] = plain_summary(m["content"])[:140]
    return [{"id": r["id"], "title": r.get("title"), "created_at": r["created_at"], "preview": previews.get(r["id"], "")}
            for r in rows]


def _tool_name(content: str | None) -> Any:
    try:
        return json.loads(content or "null")
    except json.JSONDecodeError:
        return content


@router.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: str, user: UserDep, db: DbDep) -> dict[str, Any]:
    convs = await db.select("conversations", {"id": conversation_id, "user_id": user.id})
    if not convs:
        raise HTTPException(404, "conversation not found")
    rows = await db.select("messages", {"conversation_id": conversation_id, "user_id": user.id}, order="seq.asc")
    calls: dict[str, str] = {}
    items: list[dict[str, Any]] = []
    for r in rows:
        if r["role"] == "user":
            items.append({"kind": "user", "text": r.get("content") or ""})
        elif r["role"] == "assistant":
            if r.get("content"):
                items.append({"kind": "assistant", "text": plain_summary(r["content"])})
            for c in r.get("tool_calls") or []:
                calls[c["id"]] = c["function"]["name"]
        elif r["role"] == "tool":
            result = _tool_name(r.get("content"))
            ok = not (isinstance(result, dict) and "error" in result)
            tool = calls.get(r.get("tool_call_id"), "")
            action = action_from_message(str(r.get("tool_call_id")), tool, r.get("content")) if tool else None
            items.append({"kind": "tool", "id": r.get("tool_call_id"), "tool": tool,
                          "ok": ok, "summary": None if ok else str(result.get("error")),
                          "action": action.model_dump() if action else None})
    approvals = [
        {"approval_id": a["id"], **a["preview"]}
        for a in await db.select("approvals", {"user_id": user.id, "status": "pending"})
        if a["preview"].get("conversation_id") == conversation_id
    ]
    mode = Mode.from_row(convs[0])
    return {"id": conversation_id, "title": convs[0].get("title"), "items": items, "pending_approvals": approvals,
            "mode": {"command": mode.command, "kind": mode.kind, "connector": mode.connector}}


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str, user: UserDep, db: DbDep) -> dict[str, Any]:
    """Delete a conversation and its messages (cascade). tool_runs stay as an audit trail; any approval
    still pending for it is rejected so it can no longer be used to resume the deleted chat."""
    if not await db.select("conversations", {"id": conversation_id, "user_id": user.id}):
        raise HTTPException(404, "conversation not found")
    for a in await db.select("approvals", {"user_id": user.id, "status": "pending"}):
        if (a.get("preview") or {}).get("conversation_id") == conversation_id:
            await db.update("approvals", {"id": a["id"]}, {"status": "rejected"})
    await db.delete("messages", {"conversation_id": conversation_id, "user_id": user.id})
    await db.delete("conversations", {"id": conversation_id, "user_id": user.id})
    return {"ok": True}


class RenameBody(BaseModel):
    title: str = Field(min_length=1, max_length=120)


@router.patch("/conversations/{conversation_id}")
async def rename_conversation(conversation_id: str, body: RenameBody, user: UserDep, db: DbDep) -> dict[str, Any]:
    if not await db.select("conversations", {"id": conversation_id, "user_id": user.id}):
        raise HTTPException(404, "conversation not found")
    title = body.title.strip()
    if not title:
        raise HTTPException(422, "The title cannot be empty.")
    await db.update("conversations", {"id": conversation_id, "user_id": user.id}, {"title": title})
    return {"id": conversation_id, "title": title}


class RewindBody(BaseModel):
    user_index: int = Field(ge=0)


@router.post("/conversations/{conversation_id}/rewind")
async def rewind_conversation(conversation_id: str, body: RewindBody, user: UserDep, db: DbDep) -> dict[str, Any]:
    """Drop the n-th user message (0-based) and everything after it, so the UI can regenerate the reply or
    resend an edited message. Refused while an approval is pending: that action must be decided first."""
    if not await db.select("conversations", {"id": conversation_id, "user_id": user.id}):
        raise HTTPException(404, "conversation not found")
    for a in await db.select("approvals", {"user_id": user.id, "status": "pending"}):
        if (a.get("preview") or {}).get("conversation_id") == conversation_id:
            raise HTTPException(409, "Approve or reject the pending action first.")
    rows = await db.select("messages", {"conversation_id": conversation_id, "user_id": user.id}, order="seq.asc")
    users = [i for i, r in enumerate(rows) if r["role"] == "user"]
    if body.user_index >= len(users):
        raise HTTPException(404, "message not found")
    start = users[body.user_index]
    text = rows[start].get("content") or ""
    for r in rows[start:]:
        await db.delete("messages", {"id": r["id"], "user_id": user.id})
    return {"ok": True, "text": text, "removed": len(rows) - start}
