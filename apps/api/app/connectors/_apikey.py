"""Shared helpers for token-based connectors (API key / personal access token entered on the Set up form).

These providers do not report which permissions a token carries, so the granted-scopes check and the
"Partial access" badge cannot apply (see docs/decisions.md). A provider 401/403 is surfaced as a clear
tool error instead.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.connectors.base import (ConnectorManifest, CredentialField, Settings, TokenSet, ToolDef, ToolError,
                                 ValidateCredentials)


def api_key_manifest(*, id: str, name: str, description: str, credential_fields: list[CredentialField],
                     validate: ValidateCredentials, tools: list[ToolDef], console_url: str,
                     setup_guide: list[str]) -> ConnectorManifest:
    return ConnectorManifest(
        id=id, name=name, icon=f"/icons/{id}.svg", description=description, auth_type="api_key",
        credential_fields=credential_fields, validate_credentials=validate, console_url=console_url,
        setup_guide=setup_guide, tools=tools, pkce=False)


async def checked_get(http: httpx.AsyncClient, url: str, what: str, **kw: Any) -> dict:
    """GET used by validate_credentials: map auth failures to a message for the Set up form."""
    resp = await http.get(url, **kw)
    if resp.status_code in (401, 403):
        raise ToolError(f"{what} rejected the credentials ({resp.status_code}). Check them and their permissions.")
    if resp.status_code >= 400:
        raise ToolError(f"{what} could not verify the credentials ({resp.status_code}).")
    return resp.json()


__all__ = ["api_key_manifest", "checked_get", "Settings", "TokenSet"]
