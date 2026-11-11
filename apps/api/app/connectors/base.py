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


# Hook signatures
ParseTokenResponse = Callable[[dict[str, Any]], TokenSet]
AccountLabel = Callable[[httpx.AsyncClient, TokenSet, "Settings"], Awaitable[str | None]]
Revoke = Callable[[httpx.AsyncClient, "ConnectorManifest", TokenSet, "Settings"], Awaitable[None]]
ValidateCredentials = Callable[[httpx.AsyncClient, dict[str, Any], "Settings"], Awaitable[tuple[TokenSet, str]]]


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

    # Generic knobs for providers that deviate from plain OAuth2.
    client_id_setting: str | None = None       # Settings attribute names
    client_secret_setting: str | None = None
    scope_param: str = "scope"
    scope_separator: str = " "
    token_body_format: Literal["form", "json"] = "form"
    token_request_headers: dict[str, str] = Field(default_factory=dict)
    reauth_errors: frozenset[str] = frozenset({"invalid_grant"})
    setup_url: str | None = None               # e.g. GitHub App install page

    # Optional hooks.
    parse_token_response: ParseTokenResponse | None = None
    account_label: AccountLabel | None = None
    revoke: Revoke | None = None
    validate_credentials: ValidateCredentials | None = None

    def client_credentials(self, settings: "Settings") -> tuple[str, str]:
        cid = getattr(settings, self.client_id_setting, "") if self.client_id_setting else ""
        secret = getattr(settings, self.client_secret_setting, "") if self.client_secret_setting else ""
        return cid, secret

    def is_configured(self, settings: "Settings") -> bool:
        if self.auth_type != "oauth2":
            return True
        cid, secret = self.client_credentials(settings)
        return bool(cid and secret)

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
