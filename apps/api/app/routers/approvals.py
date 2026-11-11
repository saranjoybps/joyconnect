from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.ratelimit import chat_rate_limit
from app.core.security import UserDep
from app.routers._sse import sse_response
from app.routers.chat import RuntimeDep

router = APIRouter(prefix="/api", tags=["approvals"])


class Decision(BaseModel):
    approve: bool


@router.post("/approvals/{approval_id}/decision", dependencies=[Depends(chat_rate_limit)])
async def decide(approval_id: str, body: Decision, user: UserDep, runtime: RuntimeDep):
    """Approve or reject a pending tool call; streams the resumed agent loop as SSE."""
    return await sse_response(runtime.decide_approval(user.id, approval_id, body.approve))
