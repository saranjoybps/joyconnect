"""POST /api/nodes/{type}/options: the choices for one node parameter, loaded from the connected account."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.core.security import UserDep
from app.workflows.options import OptionsError, OptionsService

router = APIRouter(prefix="/api", tags=["workflows"])


def get_options(request: Request) -> OptionsService:
    return request.app.state.options


OptionsDep = Annotated[OptionsService, Depends(get_options)]


class OptionsBody(BaseModel):
    parameter: str = Field(min_length=1, max_length=100)
    connection_id: str = Field(min_length=1, max_length=100)
    parameters: dict[str, Any] = Field(default_factory=dict)       # the node's current parameters
    query: str | None = Field(default=None, max_length=200)        # type-ahead text
    refresh: bool = False                                          # bypass the short cache


@router.post("/nodes/{node_type}/options")
async def node_options(node_type: str, body: OptionsBody, user: UserDep, svc: OptionsDep) -> dict[str, Any]:
    try:
        return await svc.load(user.id, node_type, body.parameter, body.connection_id, body.parameters,
                              body.query, body.refresh)
    except OptionsError as exc:
        raise HTTPException(exc.status, {"code": exc.code, "message": exc.message}) from exc
