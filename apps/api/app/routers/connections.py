"""Connection management: catalog (with setup status), list, toggle, check, disconnect."""

from __future__ import annotations

import string
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.connectors.base import OAuthError, ToolError
from app.connectors.registry import all_manifests, get_manifest
from app.core.config import Settings, get_settings
from app.core.security import UserDep
from app.deps import DbDep, HttpDep, StoreDep
from app.oauth.apps import ProviderAppService
from app.oauth.tokens import NeedsReauth, TokenService, public_view

router = APIRouter(prefix="/api", tags=["connections"])
SettingsDep = Annotated[Settings, Depends(get_settings)]


def _svc(db, store, http, settings) -> TokenService:
    return TokenService(db, store, http, settings)


def _setup_url(template: str | None, values: dict[str, str]) -> str | None:
    """Fill {field} placeholders from non-secret app fields; hide the link if any is missing."""
    if not template:
        return None
    fields = [f for _, f, _, _ in string.Formatter().parse(template) if f]
    if not all(values.get(f) for f in fields):
        return None
    return template.format(**{f: values[f] for f in fields})


@router.get("/connectors")
async def list_connectors(user: UserDep, db: DbDep, store: StoreDep, settings: SettingsDep) -> list[dict[str, Any]]:
    """Catalog for the /connections grid. Purely data-driven from manifests."""
    svc = ProviderAppService(db, store, settings)
    rows = {r["provider"]: r for r in await db.select("provider_apps", {"user_id": user.id})}
    manifests = list(all_manifests().values())
    out = []
    for m in manifests:
        row = rows.get(m.credentials_key)
        setup = svc.public_view(row, m)
        if row:
            public_values = dict(row.get("extra") or {})
        elif setup["source"] == "platform":
            app = m.platform_app(settings)
            public_values = {f.key: app.values.get(f.key, "") for f in m.credential_fields if not f.secret} if app else {}
        else:
            public_values = {}
        out.append({
            "id": m.id,
            "name": m.name,
            "icon": m.icon,
            "description": m.description,
            "auth_type": m.auth_type,
            "app_provider": m.credentials_key,
            "configured": setup["source"] != "none",
            "setup": setup,
            "credential_fields": [f.model_dump(exclude={"pattern"}) for f in m.credential_fields],
            "redirect_uri": settings.redirect_uri(m.credentials_key) if m.auth_type == "oauth2" else None,
            "redirect_info": {
                "mode": settings.redirect_mode,
                "localhost_redirect": m.localhost_redirect,
                "note": m.redirect_note,
            },
            "scopes": m.scopes,
            "console_url": m.console_url,
            "setup_guide": m.setup_guide,
            "setup_url": _setup_url(m.setup_url, public_values),
            "tools": [{"name": t.name, "risk": t.risk} for t in m.tools],
        })
    return out


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
