import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", Path(__file__).resolve().parents[2] / ".env"),
        extra="ignore",
    )

    app_env: str = "local"
    web_base_url: str = "http://localhost:3000"
    api_base_url: str = "http://localhost:8000"

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

    # API versions (not credentials).
    notion_version: str = "2026-03-11"
    meta_graph_version: str = ""
    google_ads_api_version: str = ""

    # Optional platform-default provider apps, read from env as PLATFORM_<APP>_<FIELD>
    # (e.g. PLATFORM_GOOGLE_CLIENT_ID). Users' own apps always take precedence.
    platform_defaults: dict[str, str] = Field(default_factory=dict)  # explicit overrides (tests)
    read_platform_env: bool = True

    allow_private_db_hosts: bool = False

    def platform_value(self, app_provider: str, field_key: str) -> str:
        name = f"PLATFORM_{app_provider}_{field_key}".upper()
        if name in self.platform_defaults:
            return self.platform_defaults[name]
        if not self.read_platform_env:
            return ""
        return os.environ.get(name) or _env_file_values().get(name) or ""

    def redirect_uri(self, provider_id: str) -> str:
        return f"{self.api_base_url.rstrip('/')}/api/oauth/callback/{provider_id}"


@lru_cache
def _env_file_values() -> dict[str, str]:
    from dotenv import dotenv_values

    out: dict[str, str] = {}
    for path in (REPO_ROOT / ".env", Path(__file__).resolve().parents[2] / ".env"):
        if path.exists():
            out.update({k: v for k, v in dotenv_values(path).items() if v})
    return out


@lru_cache
def get_settings() -> Settings:
    return Settings()
