"""The Memory page: view, add, edit and delete what the assistant remembers, and turn memory off."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.agent.memory import KINDS, MemoryService
from app.core.security import UserDep

router = APIRouter(prefix="/api", tags=["memory"])


def get_memory(request: Request) -> MemoryService:
    return request.app.state.runtime.memory


MemoryDep = Annotated[MemoryService, Depends(get_memory)]


class NewMemory(BaseModel):
    content: str = Field(min_length=1, max_length=500)
    kind: str = "fact"


class MemoryPatch(BaseModel):
    content: str | None = Field(default=None, min_length=1, max_length=500)
    kind: str | None = None


class MemorySettings(BaseModel):
    memory_enabled: bool


async def _guard(call):
    try:
        return await call
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 — most likely migration 0008 is not applied
        raise HTTPException(503, "Memory is not available yet. Ask the owner to apply the latest database "
                                 "migration (0008).") from exc


@router.get("/memories")
async def list_memories(user: UserDep, memory: MemoryDep) -> dict[str, Any]:
    items = await _guard(memory.list(user.id))
    return {"enabled": await memory.enabled(user.id), "kinds": list(KINDS), "memories": items}


@router.post("/memories", status_code=201)
async def add_memory(body: NewMemory, user: UserDep, memory: MemoryDep) -> dict[str, Any]:
    return await _guard(memory.add(user.id, body.kind, body.content))


@router.patch("/memories/{memory_id}")
async def edit_memory(memory_id: str, body: MemoryPatch, user: UserDep, memory: MemoryDep) -> dict[str, Any]:
    row = await _guard(memory.update(user.id, memory_id, body.content, body.kind))
    if row is None:
        raise HTTPException(404, "memory not found")
    return row


@router.delete("/memories/{memory_id}", status_code=204)
async def delete_memory(memory_id: str, user: UserDep, memory: MemoryDep) -> None:
    if not await _guard(memory.delete(user.id, memory_id)):
        raise HTTPException(404, "memory not found")


@router.delete("/memories", status_code=200)
async def delete_all_memories(user: UserDep, memory: MemoryDep) -> dict[str, int]:
    return {"deleted": await _guard(memory.delete_all(user.id))}


@router.get("/memory/settings")
async def get_settings_(user: UserDep, memory: MemoryDep) -> dict[str, bool]:
    return {"memory_enabled": await memory.enabled(user.id)}


@router.put("/memory/settings")
async def put_settings(body: MemorySettings, user: UserDep, memory: MemoryDep) -> dict[str, bool]:
    return {"memory_enabled": await _guard(memory.set_enabled(user.id, body.memory_enabled))}
