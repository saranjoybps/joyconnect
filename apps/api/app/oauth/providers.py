"""Provider-agnostic OAuth2 HTTP flows, driven by the manifest and a resolved app."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

import httpx

from app.connectors.base import (
    ConnectorManifest, OAuthError, ResolvedApp, TokenSet, default_parse_token_response,
)
from app.core.config import Settings


def build_authorize_url(m: ConnectorManifest, settings: Settings, app: ResolvedApp, state: str,
                        code_challenge: str | None) -> str:
    client_id, _ = m.client_credentials(app)
    params: dict[str, str] = {
        "client_id": client_id,
        "redirect_uri": settings.redirect_uri(m.id),
        "response_type": "code",
        "state": state,
    }
    if m.scopes:
        params[m.scope_param] = m.scope_separator.join(m.scopes)
    if m.pkce and code_challenge:
        params["code_challenge"] = code_challenge
        params["code_challenge_method"] = "S256"
    params.update(m.extra_authorize_params)
    return f"{m.authorize_url}?{urlencode(params)}"


async def _post_token(http: httpx.AsyncClient, m: ConnectorManifest, app: ResolvedApp,
                      data: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    client_id, client_secret = m.client_credentials(app)
    headers = {"Accept": "application/json", **m.token_request_headers}
    auth = None
    if m.token_auth_style == "basic":
        auth = httpx.BasicAuth(client_id, client_secret)
    else:
        data = {**data, "client_id": client_id, "client_secret": client_secret}
    if m.token_body_format == "json":
        resp = await http.post(m.token_url, json=data, headers=headers, auth=auth)
    else:
        resp = await http.post(m.token_url, data=data, headers=headers, auth=auth)
    try:
        body = resp.json()
    except ValueError as exc:
        raise OAuthError("invalid_response", f"token endpoint returned {resp.status_code}") from exc
    if not isinstance(body, dict):
        raise OAuthError("invalid_response", "unexpected token response")
    return resp.status_code, body


async def _token_request(http: httpx.AsyncClient, m: ConnectorManifest, app: ResolvedApp,
                         data: dict[str, Any]) -> TokenSet:
    status, body = await _post_token(http, m, app, data)
    if status >= 400 and "error" not in body:
        raise OAuthError("http_error", f"token endpoint returned {status}")
    return (m.parse_token_response or default_parse_token_response)(body)


async def exchange_code(http: httpx.AsyncClient, m: ConnectorManifest, settings: Settings, app: ResolvedApp,
                        code: str, verifier: str | None) -> TokenSet:
    data = {"grant_type": "authorization_code", "code": code, "redirect_uri": settings.redirect_uri(m.id)}
    if m.pkce and verifier:
        data["code_verifier"] = verifier
    return await _token_request(http, m, app, data)


async def refresh_tokens(http: httpx.AsyncClient, m: ConnectorManifest, app: ResolvedApp,
                         current: TokenSet) -> TokenSet:
    if not current.refresh_token:
        raise OAuthError("no_refresh_token")
    new = await _token_request(http, m, app, {"grant_type": "refresh_token", "refresh_token": current.refresh_token})
    # Providers like Google omit the refresh token on refresh: keep the old one.
    return new.model_copy(update={
        "refresh_token": new.refresh_token or current.refresh_token,
        "scopes": new.scopes or current.scopes,
        "extra": {**current.extra, **new.extra},
    })


async def revoke_tokens(http: httpx.AsyncClient, m: ConnectorManifest, settings: Settings, app: ResolvedApp,
                        token: TokenSet) -> None:
    if m.revoke:
        await m.revoke(http, m, token, settings, app)
    elif m.revoke_url:
        await http.post(m.revoke_url, data={"token": token.refresh_token or token.access_token})


async def probe_client_credentials(http: httpx.AsyncClient, m: ConnectorManifest, settings: Settings,
                                   app: ResolvedApp) -> tuple[bool, str]:
    """Harmless check: redeem a made-up code. The provider rejects the *code*
    (invalid_grant and friends) when the client id/secret are right, and rejects
    the *client* (invalid_client and friends) when they are wrong."""
    data = {"grant_type": "authorization_code", "code": "connect-credential-check",
            "redirect_uri": settings.redirect_uri(m.id)}
    try:
        status, body = await _post_token(http, m, app, data)
    except OAuthError:
        return False, "The provider gave an unexpected response. Check the client ID."
    except httpx.HTTPError:
        return False, "Could not reach the provider. Try again shortly."
    error = str(body.get("error") or "")
    if error in m.invalid_client_errors or (status == 401 and not error):
        return False, "The provider rejected the client ID or secret."
    if error:
        return True, "The provider accepted the client ID and secret."
    return False, "The provider gave an unexpected response."
