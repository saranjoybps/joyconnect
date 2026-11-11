"""Connection management: catalog, list, toggle, check, disconnect, key-based connect."""

from __future__ import annotations

import string
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.connectors.base import OAuthError, ToolError
from app.connectors.registry import all_manifests, get_manifest
from app.core.config import Settings, get_settings
from app.core.security import UserDep
from app.deps import DbDep, HttpDep, StoreDep
from app.oauth.tokens import NeedsReauth, TokenService, public_view

router = APIRouter(prefix="/api", tags=["connections"])
SettingsDep = Annotated[Settings, Depends(get_settings)]


def _svc(db, store, http, settings) -> TokenService:
    return TokenService(db, store, http, settings)


def _setup_url(template: str | None, settings: Settings) -> str | None:
    """Fill {setting_name} placeholders; hide the link if any value is missing."""
    if not template:
        return None
    values = settings.model_dump()
    try:
        url = template.format(**values)
    except KeyError:
        return None
    fields = [f for _, f, _, _ in string.Formatter().parse(template) if f]
    return url if all(values.get(f) for f in fields) else None


@router.get("/connectors")
async def list_connectors(_: UserDep, settings: SettingsDep) -> list[dict[str, Any]]:
    """Catalog for the /connections grid. Purely data-driven from manifests."""
    return [
        {
            "id": m.id,
            "name": m.name,
            "icon": m.icon,
            "description": m.description,
            "auth_type": m.auth_type,
            "configured": m.is_configured(settings),
            "setup_url": _setup_url(m.setup_url, settings),
            "tools": [{"name": t.name, "risk": t.risk} for t in m.tools],
        }
        for m in all_manifests().values()
    ]


@router.get("/connections")
async def list_connections(user: UserDep, db: DbDep) -> list[dict[str, Any]]:
    rows = await db.select("connections", {"user_id": user.id}, order="created_at.asc")
    return [public_view(r) for r in rows if r["status"] != "revoked"]


async def _own(db, user_id: str, connection_id: str) -> dict[str, Any]:
    rows = await db.select("connections", {"id": connection_id, "user_id": user_id})
    if not rows:
        raise HTTPException(404, "connection not found")
    return rows[0]


class ConnectionPatch(BaseModel):
    auto_approve_writes: bool


@router.patch("/connections/{connection_id}")
async def update_connection(connection_id: str, body: ConnectionPatch, user: UserDep, db: DbDep) -> dict:
    await _own(db, user.id, connection_id)
    rows = await db.update("connections", {"id": connection_id, "user_id": user.id},
                           {"auto_approve_writes": body.auto_approve_writes})
    return public_view(rows[0])


@router.post("/connections/{connection_id}/disconnect")
async def disconnect(connection_id: str, user: UserDep, db: DbDep, store: StoreDep, http: HttpDep,
                     settings: SettingsDep) -> dict:
    conn = await _own(db, user.id, connection_id)
    await _svc(db, store, http, settings).disconnect(conn)
    return {"ok": True}


@router.post("/connections/{connection_id}/check")
async def check(connection_id: str, user: UserDep, db: DbDep, store: StoreDep, http: HttpDep,
                settings: SettingsDep) -> dict:
    """Get a valid token (refreshing if needed) and re-read the account label."""
    conn = await _own(db, user.id, connection_id)
    svc = _svc(db, store, http, settings)
    try:
        token = await svc.get_token(conn)
        m = get_manifest(conn["provider"])
        if m and m.account_label:
            await m.account_label(http, token, settings)
    except NeedsReauth:
        return {"status": "needs_reauth"}
    except (OAuthError, ToolError) as exc:
        raise HTTPException(502, f"provider error: {exc}") from exc
    return {"status": "active"}


class CredentialsBody(BaseModel):
    provider: str
    credentials: dict[str, str] = Field(default_factory=dict)


async def _connect_with_credentials(kind: str, body: CredentialsBody, user, db, store, http, settings) -> dict:
    m = get_manifest(body.provider)
    if m is None or m.auth_type != kind or m.validate_credentials is None:
        raise HTTPException(404, "unknown provider")
    try:
        token, label = await m.validate_credentials(http, body.credentials, settings)
    except (ValueError, ToolError) as exc:
        raise HTTPException(400, str(exc)) from exc
    row = await _svc(db, store, http, settings).save_connection(user.id, m, token, label)
    return public_view(row)


@router.post("/connections/api-key")
async def connect_api_key(body: CredentialsBody, user: UserDep, db: DbDep, store: StoreDep, http: HttpDep,
                          settings: SettingsDep) -> dict:
    return await _connect_with_credentials("api_key", body, user, db, store, http, settings)


@router.post("/connections/connection-string")
async def connect_connection_string(body: CredentialsBody, user: UserDep, db: DbDep, store: StoreDep,
                                    http: HttpDep, settings: SettingsDep) -> dict:
    return await _connect_with_credentials("connection_string", body, user, db, store, http, settings)
