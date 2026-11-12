import os
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[4]
API_ROOT = Path(__file__).resolve().parents[2]
# Later files win. apps/api/.env.local is written by scripts/dev-tunnel.* (PUBLIC_API_BASE_URL).
_ENV_FILES = (REPO_ROOT / ".env", API_ROOT / ".env", API_ROOT / ".env.local")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILES,
        extra="ignore",
    )

    app_env: str = "local"
    web_base_url: str = "http://localhost:3000"
    api_base_url: str = "http://localhost:8000"      # what the browser calls (chat, SSE)
    public_api_base_url: str = ""                    # what providers redirect to; defaults to api_base_url

    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""
    supabase_jwt_secret: str = ""

    secret_store: Literal["aesgcm", "vault"] = "aesgcm"
    token_encryption_key: str = ""
    oauth_state_secret: str = ""

    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    max_tool_steps: int = 8
    max_tools_per_request: int = 24
    chat_rate_limit_per_minute: int = 20
    approval_ttl_hours: int = 24
    # Per-user daily limits (UTC day). 0 = unlimited.
    daily_chat_message_limit: int = 200
    daily_tool_run_limit: int = 500
    # Retries for READ tools only, on 429 / 5xx / network errors. Write tools are never retried.
    retry_max_attempts: int = 3
    retry_base_delay_seconds: float = 0.5
    retry_max_delay_seconds: float = 8.0

    # API versions (not credentials).
    notion_version: str = "2026-03-11"
    meta_graph_version: str = ""
    google_ads_api_version: str = ""

    # Optional platform-default provider apps, read from env as PLATFORM_<APP>_<FIELD>
    # (e.g. PLATFORM_GOOGLE_CLIENT_ID). Users' own apps always take precedence.
    platform_defaults: dict[str, str] = Field(default_factory=dict)  # explicit overrides (tests)
    read_platform_env: bool = True

    allow_private_db_hosts: bool = False

    # Workflow engine
    allow_private_http_hosts: bool = False           # HTTP Request node SSRF guard (private/loopback/metadata)
    node_timeout_seconds: int = 60
    workflow_timeout_seconds: int = 600
    workflow_max_node_runs: int = 2000               # stops endless loops
    max_subworkflow_depth: int = 5
    default_run_cost_cap_usd: float = 1.0            # per run, AI nodes; 0 = no default cap
    worker_poll_seconds: float = 1.0
    worker_lease_seconds: int = 300
    scheduler_tick_seconds: float = 5.0

    def platform_value(self, app_provider: str, field_key: str) -> str:
        name = f"PLATFORM_{app_provider}_{field_key}".upper()
        if name in self.platform_defaults:
            return self.platform_defaults[name]
        if not self.read_platform_env:
            return ""
        return os.environ.get(name) or _env_file_values().get(name) or ""

    @property
    def oauth_base_url(self) -> str:
        """Base of every redirect URI. PUBLIC_API_BASE_URL, never API_BASE_URL, unless unset."""
        return (self.public_api_base_url or self.api_base_url).rstrip("/")

    def redirect_uri(self, family: str) -> str:
        """One URI per provider family (a connector's `credentials_key`, e.g. 'google', 'slack')."""
        return f"{self.oauth_base_url}/api/oauth/callback/{family}"

    @property
    def redirect_mode(self) -> Literal["localhost", "tunnel"]:
        host = (urlparse(self.oauth_base_url).hostname or "").lower()
        return "localhost" if host in {"localhost", "127.0.0.1", "::1"} else "tunnel"


@lru_cache
def _env_file_values() -> dict[str, str]:
    from dotenv import dotenv_values

    out: dict[str, str] = {}
    for path in _ENV_FILES:
        if path.exists():
            out.update({k: v for k, v in dotenv_values(path).items() if v})
    return out


@lru_cache
def get_settings() -> Settings:
    return Settings()
