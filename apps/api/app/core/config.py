from functools import lru_cache
from pathlib import Path
from typing import Literal

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

    google_client_id: str = ""
    google_client_secret: str = ""
    slack_client_id: str = ""
    slack_client_secret: str = ""
    notion_client_id: str = ""
    notion_client_secret: str = ""
    notion_version: str = "2026-03-11"
    github_app_client_id: str = ""
    github_app_client_secret: str = ""
    meta_app_id: str = ""
    meta_app_secret: str = ""
    meta_graph_version: str = ""
    google_ads_api_version: str = ""

    allow_private_db_hosts: bool = False

    def redirect_uri(self, provider_id: str) -> str:
        return f"{self.api_base_url.rstrip('/')}/api/oauth/callback/{provider_id}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
