"""Save, view (masked), test and remove a user's provider app credentials.

`{provider}` is a credential group (e.g. 'google', shared by Sheets/Docs/Calendar)
or any connector id in that group. Secret values are never returned.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.connectors.base import ConnectorManifest, SetupRequired, ToolError
from app.connectors.registry import all_manifests, get_manifest
from app.core.config import Settings, get_settings
from app.core.security import UserDep
from app.deps import DbDep, HttpDep, StoreDep
from app.oauth.apps import CredentialValidationError, ProviderAppService, validate_values
from app.oauth.providers import probe_client_credentials
from app.oauth.tokens import TokenService

router = APIRouter(prefix="/api/provider-apps", tags=["provider-apps"])
SettingsDep = Annotated[Settings, Depends(get_settings)]


def manifest_for(provider: str) -> ConnectorManifest:
    m = get_manifest(provider)
    if m is None:
        m = next((x for x in all_manifests().values() if x.credentials_key == provider), None)
    if m is None or not m.credential_fields:
        raise HTTPException(404, "unknown provider")
    return m


class SaveBody(BaseModel):
    values: dict[str, str] = Field(default_factory=dict)


@router.get("/{provider}")
async def view(provider: str, user: UserDep, db: DbDep, store: StoreDep, settings: SettingsDep) -> dict:
    m = manifest_for(provider)
    svc = ProviderAppService(db, store, settings)
    return svc.public_view(await svc.get_row(user.id, m.credentials_key), m)


@router.post("/{provider}")
async def save(provider: str, body: SaveBody, user: UserDep, db: DbDep, store: StoreDep,
               settings: SettingsDep) -> dict:
    m = manifest_for(provider)
    svc = ProviderAppService(db, store, settings)
    try:
        row = await svc.save(user.id, m, body.values)
    except CredentialValidationError as exc:
        raise HTTPException(422, {"code": "invalid_credentials", "errors": exc.errors}) from exc
    return svc.public_view(row, m)


@router.post("/{provider}/test")
async def test(provider: str, user: UserDep, db: DbDep, store: StoreDep, http: HttpDep,
               settings: SettingsDep) -> dict[str, Any]:
    """Format check, then a harmless provider call where one exists."""
    m = manifest_for(provider)
    try:
        app = await ProviderAppService(db, store, settings).resolve(user.id, m)
    except SetupRequired as exc:
        raise HTTPException(409, {"code": "setup_required", "message": str(exc)}) from exc
    try:
        validate_values(m, app.values, existing_secrets=set())
    except CredentialValidationError as exc:
        return {"ok": False, "source": app.source, "message": "Some fields have the wrong format.",
                "errors": exc.errors}
    if m.auth_type == "oauth2":
        ok, message = await probe_client_credentials(http, m, settings, app)
    elif m.validate_credentials:
        try:
            await m.validate_credentials(http, app.values, settings)
            ok, message = True, "Connection test succeeded."
        except (ValueError, ToolError) as exc:
            ok, message = False, str(exc)
    else:
        ok, message = True, "Format looks right."
    return {"ok": ok, "source": app.source, "message": message, "errors": {}}


@router.delete("/{provider}")
async def remove(provider: str, user: UserDep, db: DbDep, store: StoreDep, http: HttpDep, settings: SettingsDep,
                 confirm: Annotated[bool, Query()] = False) -> dict[str, Any]:
    """Without confirm=true, refuses (409) and lists the connections that would be disconnected."""
    m = manifest_for(provider)
    svc = ProviderAppService(db, store, settings)
    row = await svc.get_row(user.id, m.credentials_key)
    if row is None:
        raise HTTPException(404, "no saved credentials")
    linked = [c for c in await db.select("connections", {"user_id": user.id, "provider_app_id": row["id"]})
              if c["status"] != "revoked"]
    if linked and not confirm:
        raise HTTPException(409, {
            "code": "has_connections",
            "message": f"Removing these credentials will disconnect {len(linked)} connection(s).",
            "connections": [{"id": c["id"], "provider": c["provider"], "account_label": c.get("account_label")}
                            for c in linked],
        })
    tokens = TokenService(db, store, http, settings)
    for conn in linked:  # revoke with this app's credentials before they are deleted
        await tokens.disconnect(conn)
    await svc.delete(row)
    return {"ok": True, "disconnected": len(linked)}
