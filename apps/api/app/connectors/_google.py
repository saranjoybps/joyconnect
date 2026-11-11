"""Shared Google OAuth settings for the Google connectors (not a connector itself)."""

from __future__ import annotations

import base64
import json
import re

import httpx

from app.connectors.base import ConnectorManifest, ResolvedApp, TokenSet, ToolDef, oauth_client_fields

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
# openid + email are non-sensitive and give us a stable account label.
IDENTITY_SCOPES = ["openid", "email"]


def _jwt_claims(id_token: str) -> dict:
    # The id_token comes straight from Google's token endpoint over TLS, so per
    # Google's guidance its signature does not need to be re-validated here.
    try:
        part = id_token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
    except Exception:  # noqa: BLE001
        return {}


async def google_account_label(http: httpx.AsyncClient, token: TokenSet, settings) -> str | None:
    if "email" in token.extra:
        return token.extra["email"]
    id_token = token.raw.get("id_token")
    email = _jwt_claims(id_token).get("email") if id_token else None
    if email:
        token.extra["email"] = email
    return email


async def google_revoke(http: httpx.AsyncClient, m: ConnectorManifest, token: TokenSet, settings,
                        app: ResolvedApp) -> None:
    await http.post(REVOKE_URL, data={"token": token.refresh_token or token.access_token},
                    headers={"Content-Type": "application/x-www-form-urlencoded"})


CREDENTIAL_FIELDS = oauth_client_fields(
    id_help="Google Cloud Console > Google Auth Platform > Clients > your Web application client.",
    secret_help="Shown when you create the client (starts with GOCSPX-).",
    id_pattern=r"[0-9]+-[0-9A-Za-z_]+\.apps\.googleusercontent\.com",
    id_hint="Should look like 1234567890-abc123.apps.googleusercontent.com",
)
SETUP_GUIDE = [
    "Create a Google Cloud project, then enable the Google Sheets, Docs and Calendar APIs.",
    "Google Auth Platform > Audience: choose External and add yourself as a test user.",
    "Data access: add the scopes listed below.",
    "Clients > Create client > Web application, and add the redirect URI listed below (one URI for Sheets, Docs and Calendar).",
    "Copy the client ID and secret here. One Google app serves Sheets, Docs and Calendar.",
]


def google_manifest(*, id: str, name: str, description: str, scopes: list[str], tools: list[ToolDef]) -> ConnectorManifest:
    return ConnectorManifest(
        id=id,
        name=name,
        icon=f"/icons/{id}.svg",
        description=description,
        auth_type="oauth2",
        authorize_url=AUTHORIZE_URL,
        token_url=TOKEN_URL,
        revoke_url=REVOKE_URL,
        scopes=IDENTITY_SCOPES + scopes,
        verifies_scopes=True,                  # Google's token response lists the granted scopes
        permission_label=name.removeprefix("Google "),
        extra_authorize_params={"access_type": "offline", "prompt": "consent", "include_granted_scopes": "true"},
        token_auth_style="body",
        pkce=True,
        app_provider="google",
        credential_fields=CREDENTIAL_FIELDS,
        console_url="https://console.cloud.google.com/auth/clients",
        localhost_redirect="yes",
        redirect_note="Google allows http://localhost redirect URIs for web application clients. "
                      "All Google connectors share this one URI.",
        setup_guide=SETUP_GUIDE,
        account_label=google_account_label,
        revoke=google_revoke,
        tools=tools,
    )


_ID_RE = re.compile(r"/(?:spreadsheets|document)/d/([a-zA-Z0-9_-]+)")


def parse_google_file_id(value: str) -> str:
    """Accept a raw ID or a docs.google.com URL."""
    value = value.strip()
    match = _ID_RE.search(value)
    if match:
        return match.group(1)
    if re.fullmatch(r"[a-zA-Z0-9_-]{10,}", value):
        return value
    raise ValueError("Not a Google file ID or URL")
