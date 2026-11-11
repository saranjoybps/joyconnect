"""Generic connect flow for every connector.

oauth2: start -> provider consent -> callback (code exchange server-side).
api_key / connection_string: start validates the saved credentials and connects directly.
The provider_app used is resolved once at start and carried in the signed state.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Annotated
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse

from app.connectors.base import OAuthError, SetupRequired, ToolError
from app.connectors.registry import all_manifests, get_manifest
from app.core.config import Settings, get_settings
from app.core.security import UserDep
from app.deps import DbDep, HttpDep, StoreDep
from app.oauth.apps import ProviderAppService
from app.oauth.providers import build_authorize_url, exchange_code
from app.oauth.state import STATE_TTL_SECONDS, StateError, pkce_pair, sign_state, verify_state
from app.oauth.tokens import TokenService, missing_for, public_view

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["oauth"])
SettingsDep = Annotated[Settings, Depends(get_settings)]


def setup_required(exc: SetupRequired) -> HTTPException:
    return HTTPException(409, {"code": "setup_required", "message": str(exc)})


@router.post("/connections/{provider}/start")
async def start(provider: str, user: UserDep, db: DbDep, store: StoreDep, http: HttpDep,
                settings: SettingsDep) -> dict:
    m = get_manifest(provider)
    if m is None:
        raise HTTPException(404, "unknown provider")
    try:
        app = await ProviderAppService(db, store, settings).resolve(user.id, m)
    except SetupRequired as exc:
        raise setup_required(exc) from exc

    if m.auth_type != "oauth2":
        if m.validate_credentials is None:
            raise HTTPException(500, "connector cannot validate credentials")
        try:
            token, label = await m.validate_credentials(http, app.values, settings)
        except (ValueError, ToolError) as exc:
            raise HTTPException(400, str(exc)) from exc
        row = await TokenService(db, store, http, settings).save_connection(user.id, m, token, label, app)
        return {"connected": True, "connection": public_view(row)}

    cutoff = datetime.now(timezone.utc) - timedelta(seconds=STATE_TTL_SECONDS)
    await db.delete_older_than("oauth_states", "created_at", cutoff)
    state = sign_state(settings.oauth_state_secret, user.id, m.id, app.state_ref)
    verifier, challenge = pkce_pair() if m.pkce else (None, None)
    await db.insert("oauth_states", {"state": state, "user_id": user.id, "provider": m.id, "code_verifier": verifier})
    url = build_authorize_url(m, settings, app, state, challenge)
    log.info("authorize connector=%s app=%s scopes=%s", m.id, app.source, m.scopes)
    return {"authorize_url": url}


def _back_to_web(settings: Settings, **params: str) -> RedirectResponse:
    return RedirectResponse(f"{settings.web_base_url.rstrip('/')}/connections?{urlencode(params)}", status_code=303)


def _callback_names() -> set[str]:
    """Route names that accept a callback: every provider family (the URI we hand to providers)
    plus every legacy per-connector id (older registrations and flows already in flight)."""
    ms = [m for m in all_manifests().values() if m.auth_type == "oauth2"]
    return {m.id for m in ms} | {m.credentials_key for m in ms}


@router.get("/oauth/callback/{provider}")
async def callback(
    provider: str,
    db: DbDep,
    store: StoreDep,
    http: HttpDep,
    settings: SettingsDep,
    code: Annotated[str | None, Query()] = None,
    state: Annotated[str | None, Query()] = None,
    error: Annotated[str | None, Query()] = None,
) -> RedirectResponse:
    # `provider` is the route the provider called: a family ('google') or a legacy connector id.
    # The connector that started the flow is in the signed state.
    if provider not in _callback_names():
        raise HTTPException(404, "unknown provider")
    if not state:
        return _back_to_web(settings, error="invalid_state", provider=provider)

    try:
        payload = verify_state(settings.oauth_state_secret, state)
    except StateError:
        return _back_to_web(settings, error="invalid_state", provider=provider)
    m = get_manifest(payload.get("p", ""))
    if m is None or m.auth_type != "oauth2" or provider not in {m.id, m.credentials_key}:
        return _back_to_web(settings, error="invalid_state", provider=provider)
    connector = m.id

    # Single use: consume the row before anything else can fail.
    rows = await db.delete("oauth_states", {"state": state})
    if not rows or rows[0]["user_id"] != payload["u"] or rows[0]["provider"] != connector:
        return _back_to_web(settings, error="invalid_state", provider=connector)
    created = datetime.fromisoformat(str(rows[0]["created_at"]).replace("Z", "+00:00"))
    if datetime.now(timezone.utc) - created > timedelta(seconds=STATE_TTL_SECONDS):
        return _back_to_web(settings, error="invalid_state", provider=connector)

    if error or not code:
        # User denied consent, or provider error.
        return _back_to_web(settings, error=error or "missing_code", provider=connector)

    user_id = payload["u"]
    try:
        app = await ProviderAppService(db, store, settings).by_ref(user_id, m, payload.get("a"))
    except SetupRequired:
        return _back_to_web(settings, error="setup_required", provider=connector)
    try:
        token = await exchange_code(http, m, settings, app, code, rows[0].get("code_verifier"),
                                    redirect_uri=settings.redirect_uri(provider))
        label = await m.account_label(http, token, settings) if m.account_label else None
    except OAuthError as exc:
        log.info("code exchange failed for %s: %s", connector, exc.code)
        return _back_to_web(settings, error=exc.code, provider=connector)
    except (ToolError, httpx.HTTPError) as exc:
        log.warning("provider call failed during %s callback: %s", connector, type(exc).__name__)
        return _back_to_web(settings, error="provider_unavailable", provider=connector)

    row = await TokenService(db, store, http, settings).save_connection(user_id, m, token, label, app)
    missing = missing_for(row)
    log.info("callback saved connection=%s connector=%s granted=%s requested=%s missing=%s",
             row["id"], connector, sorted(row["scopes"] or []), m.scopes, missing)
    if missing:
        # Connected, but the provider granted less than the connector needs (user unticked a box).
        return _back_to_web(settings, connected=connector, partial=m.permission_name)
    return _back_to_web(settings, connected=connector)
