"""Connector manifest: the one declarative description of an app.

Adding an app = one module in app/connectors/ exposing `MANIFEST`.
Nothing provider-specific belongs anywhere else.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.config import Settings

Risk = Literal["read", "write", "destructive"]
TOOL_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


class OAuthError(Exception):
    """Provider returned an OAuth error (e.g. invalid_grant)."""

    def __init__(self, code: str, description: str | None = None):
        super().__init__(code if not description else f"{code}: {description}")
        self.code = code
        self.description = description


class ToolError(Exception):
    """A tool failed in a way that should be reported back to the model."""


class TokenSet(BaseModel):
    access_token: str
    refresh_token: str | None = None
    expires_at: int | None = None          # epoch seconds
    token_type: str = "bearer"
    scopes: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)   # stored, non-secret metadata
    raw: dict[str, Any] = Field(default_factory=dict, exclude=True)  # full response; never stored

    def payload(self) -> dict[str, Any]:
        """Shape persisted in the SecretStore."""
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at,
            "token_type": self.token_type,
            "extra": {**self.extra, "scopes": self.scopes},
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "TokenSet":
        extra = dict(payload.get("extra") or {})
        scopes = extra.pop("scopes", [])
        return cls(
            access_token=payload["access_token"],
            refresh_token=payload.get("refresh_token"),
            expires_at=payload.get("expires_at"),
            token_type=payload.get("token_type") or "bearer",
            scopes=scopes,
            extra=extra,
        )

    def expires_within(self, seconds: int) -> bool:
        return self.expires_at is not None and self.expires_at - seconds <= time.time()


@dataclass
class ToolContext:
    http: httpx.AsyncClient
    token: TokenSet
    settings: "Settings"
    connection: dict[str, Any] = field(default_factory=dict)

    @property
    def bearer(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token.access_token}"}


ToolHandler = Callable[..., Awaitable[Any]]


class ToolDef(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    description: str
    parameters: dict[str, Any]
    risk: Risk
    handler: ToolHandler

    @field_validator("name")
    @classmethod
    def _valid_name(cls, v: str) -> str:
        if not TOOL_NAME_RE.match(v):
            raise ValueError(f"invalid tool name: {v}")
        return v

    @field_validator("parameters")
    @classmethod
    def _strict_schema(cls, v: dict[str, Any]) -> dict[str, Any]:
        # OpenAI strict mode: closed objects, every property listed as required.
        if v.get("type") != "object" or v.get("additionalProperties") is not False:
            raise ValueError("parameters must be an object schema with additionalProperties: false")
        if sorted(v.get("required", [])) != sorted(v.get("properties", {})):
            raise ValueError("strict mode: every property must be required (use a null type for optional)")
        return v


class CredentialField(BaseModel):
    """One input on the connector's Set up form."""

    key: str                                   # e.g. 'client_id'
    label: str
    secret: bool = False                       # stored encrypted, never returned to the browser
    help_text: str = ""
    required: bool = True
    pattern: str | None = None                 # format check (regex, full match)
    pattern_hint: str = ""                     # shown when the pattern does not match


@dataclass
class ResolvedApp:
    """Credentials for one connector flow: the user's provider_app or a platform default."""

    provider: str                              # credential group, e.g. 'google'
    source: Literal["user", "platform"]
    values: dict[str, str]                     # every field, secrets included; never serialize
    id: str | None = None                      # provider_apps.id (None for platform)

    @property
    def state_ref(self) -> str:
        return self.id or "platform"

    def __repr__(self) -> str:  # never leak secrets through repr/logging
        return f"ResolvedApp(provider={self.provider!r}, source={self.source!r}, id={self.id!r})"


def oauth_client_fields(*, id_help: str, secret_help: str, id_pattern: str | None = None,
                        id_hint: str = "", extra: list[CredentialField] | None = None) -> list[CredentialField]:
    return [
        CredentialField(key="client_id", label="Client ID", help_text=id_help, pattern=id_pattern,
                        pattern_hint=id_hint),
        CredentialField(key="client_secret", label="Client secret", secret=True, help_text=secret_help),
        *(extra or []),
    ]


class SetupRequired(Exception):
    def __init__(self, connector_name: str):
        super().__init__(f"{connector_name} is not set up yet. Add your app credentials on the Connections page.")


# Hook signatures
ParseTokenResponse = Callable[[dict[str, Any]], TokenSet]
AccountLabel = Callable[[httpx.AsyncClient, TokenSet, Settings], Awaitable[str | None]]
Revoke = Callable[[httpx.AsyncClient, "ConnectorManifest", TokenSet, Settings, ResolvedApp], Awaitable[None]]
ValidateCredentials = Callable[[httpx.AsyncClient, dict[str, str], Settings], Awaitable[tuple[TokenSet, str | None]]]


class ConnectorManifest(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: str
    name: str
    icon: str                                  # path under the web app's /public/icons
    description: str = ""
    auth_type: Literal["oauth2", "api_key", "connection_string"]
    authorize_url: str | None = None
    token_url: str | None = None
    scopes: list[str] = Field(default_factory=list)
    extra_authorize_params: dict[str, str] = Field(default_factory=dict)
    token_auth_style: Literal["body", "basic"] = "body"
    pkce: bool = True
    revoke_url: str | None = None
    tools: list[ToolDef] = Field(default_factory=list)

    # Credentials the user enters on the Set up form (or PLATFORM_<APP>_<FIELD> env defaults).
    credential_fields: list[CredentialField] = Field(default_factory=list)
    app_provider: str | None = None            # shared credential group (defaults to id)
    client_id_field: str = "client_id"         # which fields are the OAuth client id/secret
    client_secret_field: str = "client_secret"
    console_url: str | None = None             # provider developer console
    setup_guide: list[str] = Field(default_factory=list)
    invalid_client_errors: frozenset[str] = frozenset({"invalid_client", "unauthorized_client"})

    # Generic knobs for providers that deviate from plain OAuth2.
    scope_param: str = "scope"
    scope_separator: str = " "
    token_body_format: Literal["form", "json"] = "form"
    token_request_headers: dict[str, str] = Field(default_factory=dict)
    reauth_errors: frozenset[str] = frozenset({"invalid_grant"})
    # Does the provider accept an http://localhost redirect URI?  Only "yes"/"no" when the
    # provider's own docs say so (see docs/decisions.md); otherwise "unverified".
    localhost_redirect: Literal["yes", "no", "unverified"] = "unverified"
    redirect_note: str | None = None             # shown under the redirect URI in the Set up panel
    setup_url: str | None = None               # e.g. GitHub App install page; {field} placeholders

    # Optional hooks.
    parse_token_response: ParseTokenResponse | None = None
    account_label: AccountLabel | None = None
    revoke: Revoke | None = None
    validate_credentials: ValidateCredentials | None = None

    @property
    def credentials_key(self) -> str:
        return self.app_provider or self.id

    def client_credentials(self, app: ResolvedApp) -> tuple[str, str]:
        return app.values.get(self.client_id_field, ""), app.values.get(self.client_secret_field, "")

    def field(self, key: str) -> CredentialField | None:
        return next((f for f in self.credential_fields if f.key == key), None)

    def platform_app(self, settings: Settings) -> ResolvedApp | None:
        """Platform default app from env, if every required field is present."""
        if not self.credential_fields:
            return None
        values = {f.key: settings.platform_value(self.credentials_key, f.key) for f in self.credential_fields}
        if any(f.required and not values[f.key] for f in self.credential_fields):
            return None
        return ResolvedApp(provider=self.credentials_key, source="platform",
                           values={k: v for k, v in values.items() if v})

    def tool(self, name: str) -> ToolDef:
        for t in self.tools:
            if t.name == name:
                return t
        raise KeyError(name)


def default_parse_token_response(data: dict[str, Any]) -> TokenSet:
    """RFC 6749 token response -> TokenSet. Raises OAuthError on error bodies."""
    if "error" in data:
        raise OAuthError(str(data["error"]), data.get("error_description"))
    if not data.get("access_token"):
        raise OAuthError("invalid_response", "no access_token in token response")
    expires_in = data.get("expires_in")
    scope = data.get("scope") or ""
    scopes = [s for s in re.split(r"[ ,]+", scope) if s]
    return TokenSet(
        access_token=data["access_token"],
        refresh_token=data.get("refresh_token"),
        expires_at=int(time.time()) + int(expires_in) if expires_in else None,
        token_type=data.get("token_type") or "bearer",
        scopes=scopes,
        raw=data,
    )


def object_schema(properties: dict[str, Any]) -> dict[str, Any]:
    """Strict-mode JSON Schema helper: all properties required, closed object."""
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def raise_for_status(resp: httpx.Response, what: str) -> None:
    if resp.status_code >= 400:
        detail = ""
        try:
            body = resp.json()
            detail = (body.get("error") or {}).get("message") if isinstance(body.get("error"), dict) else (
                body.get("message") or body.get("error") or "")
        except Exception:  # noqa: BLE001
            pass
        raise ToolError(f"{what} failed ({resp.status_code}){': ' + str(detail) if detail else ''}")
