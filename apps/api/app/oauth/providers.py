"""Provider-agnostic OAuth2 HTTP flows, driven entirely by the manifest."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

import httpx

from app.connectors.base import ConnectorManifest, OAuthError, TokenSet, default_parse_token_response
from app.core.config import Settings


def build_authorize_url(m: ConnectorManifest, settings: Settings, state: str, code_challenge: str | None) -> str:
    client_id, _ = m.client_credentials(settings)
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


async def _token_request(
    http: httpx.AsyncClient, m: ConnectorManifest, settings: Settings, data: dict[str, Any]
) -> TokenSet:
    client_id, client_secret = m.client_credentials(settings)
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
    if resp.status_code >= 400 and "error" not in body:
        raise OAuthError("http_error", f"token endpoint returned {resp.status_code}")
    parse = m.parse_token_response or default_parse_token_response
    return parse(body)


async def exchange_code(
    http: httpx.AsyncClient, m: ConnectorManifest, settings: Settings, code: str, verifier: str | None
) -> TokenSet:
    data = {"grant_type": "authorization_code", "code": code, "redirect_uri": settings.redirect_uri(m.id)}
    if m.pkce and verifier:
        data["code_verifier"] = verifier
    return await _token_request(http, m, settings, data)


async def refresh_tokens(
    http: httpx.AsyncClient, m: ConnectorManifest, settings: Settings, current: TokenSet
) -> TokenSet:
    if not current.refresh_token:
        raise OAuthError("no_refresh_token")
    new = await _token_request(
        http, m, settings, {"grant_type": "refresh_token", "refresh_token": current.refresh_token}
    )
    # Providers like Google omit the refresh token on refresh: keep the old one.
    return new.model_copy(update={
        "refresh_token": new.refresh_token or current.refresh_token,
        "scopes": new.scopes or current.scopes,
        "extra": {**current.extra, **new.extra},
    })


async def revoke_tokens(http: httpx.AsyncClient, m: ConnectorManifest, settings: Settings, token: TokenSet) -> None:
    if m.revoke:
        await m.revoke(http, m, token, settings)
    elif m.revoke_url:
        await http.post(m.revoke_url, data={"token": token.refresh_token or token.access_token})
