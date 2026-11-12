from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.agent.response import action_from_message, plain_summary
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


@router.post("/chat", dependencies=[Depends(chat_rate_limit)])
async def chat(body: ChatBody, user: UserDep, runtime: RuntimeDep):
    return await sse_response(runtime.chat(user.id, body.conversation_id, body.message))


@router.get("/conversations")
async def list_conversations(user: UserDep, db: DbDep) -> list[dict[str, Any]]:
    rows = await db.select("conversations", {"user_id": user.id}, order="created_at.desc", limit=100)
    return [{"id": r["id"], "title": r.get("title"), "created_at": r["created_at"]} for r in rows]


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
    return {"id": conversation_id, "title": convs[0].get("title"), "items": items, "pending_approvals": approvals}


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
