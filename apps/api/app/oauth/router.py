"""Generic OAuth2 broker serving every `oauth2` connector."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Annotated
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse

from app.connectors.base import OAuthError, ToolError
from app.connectors.registry import get_manifest
from app.core.config import Settings, get_settings
from app.core.security import UserDep
from app.deps import DbDep, HttpDep, StoreDep
from app.oauth.providers import build_authorize_url, exchange_code
from app.oauth.state import STATE_TTL_SECONDS, StateError, pkce_pair, sign_state, verify_state
from app.oauth.tokens import TokenService

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["oauth"])
SettingsDep = Annotated[Settings, Depends(get_settings)]


def _oauth_manifest(provider: str, settings: Settings):
    m = get_manifest(provider)
    if m is None or m.auth_type != "oauth2":
        raise HTTPException(404, "unknown provider")
    if not m.is_configured(settings):
        raise HTTPException(400, f"{m.name} is not configured on the server")
    return m


@router.post("/connections/{provider}/start")
async def start(provider: str, user: UserDep, db: DbDep, settings: SettingsDep) -> dict:
    m = _oauth_manifest(provider, settings)
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=STATE_TTL_SECONDS)
    await db.delete_older_than("oauth_states", "created_at", cutoff)

    state = sign_state(settings.oauth_state_secret, user.id, m.id)
    verifier, challenge = pkce_pair() if m.pkce else (None, None)
    await db.insert("oauth_states", {"state": state, "user_id": user.id, "provider": m.id, "code_verifier": verifier})
    return {"authorize_url": build_authorize_url(m, settings, state, challenge)}


def _back_to_web(settings: Settings, **params: str) -> RedirectResponse:
    return RedirectResponse(f"{settings.web_base_url.rstrip('/')}/connections?{urlencode(params)}", status_code=303)


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
    m = get_manifest(provider)
    if m is None or m.auth_type != "oauth2":
        raise HTTPException(404, "unknown provider")
    if not state:
        return _back_to_web(settings, error="invalid_state", provider=provider)

    try:
        payload = verify_state(settings.oauth_state_secret, state, provider)
    except StateError:
        return _back_to_web(settings, error="invalid_state", provider=provider)
    # Single use: consume the row before anything else can fail.
    rows = await db.delete("oauth_states", {"state": state})
    if not rows or rows[0]["user_id"] != payload["u"] or rows[0]["provider"] != provider:
        return _back_to_web(settings, error="invalid_state", provider=provider)
    created = datetime.fromisoformat(str(rows[0]["created_at"]).replace("Z", "+00:00"))
    if datetime.now(timezone.utc) - created > timedelta(seconds=STATE_TTL_SECONDS):
        return _back_to_web(settings, error="invalid_state", provider=provider)

    if error or not code:
        # User denied consent, or provider error.
        return _back_to_web(settings, error=error or "missing_code", provider=provider)

    user_id = payload["u"]
    try:
        token = await exchange_code(http, m, settings, code, rows[0].get("code_verifier"))
        label = await m.account_label(http, token, settings) if m.account_label else None
    except OAuthError as exc:
        log.info("code exchange failed for %s: %s", provider, exc.code)
        return _back_to_web(settings, error=exc.code, provider=provider)
    except (ToolError, httpx.HTTPError) as exc:
        log.warning("provider call failed during %s callback: %s", provider, type(exc).__name__)
        return _back_to_web(settings, error="provider_unavailable", provider=provider)

    await TokenService(db, store, http, settings).save_connection(user_id, m, token, label)
    return _back_to_web(settings, connected=provider)
