import base64
import os
import time

import jwt
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.secrets import AesGcmSecretStore
from app.db.client import MemoryDatabase

JWT_SECRET = "test-jwt-secret-with-enough-length-1234567890"
USER_A = "11111111-1111-1111-1111-111111111111"
USER_B = "22222222-2222-2222-2222-222222222222"


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        supabase_url="https://proj.supabase.co",
        supabase_service_role_key="service",
        supabase_jwt_secret=JWT_SECRET,
        token_encryption_key=base64.b64encode(os.urandom(32)).decode(),
        oauth_state_secret=base64.b64encode(os.urandom(32)).decode(),
        google_client_id="g-id",
        google_client_secret="g-secret",
        slack_client_id="s-id",
        slack_client_secret="s-secret",
        notion_client_id="n-id",
        notion_client_secret="n-secret",
        github_app_client_id="gh-id",
        github_app_client_secret="gh-secret",
    )


@pytest.fixture
def db() -> MemoryDatabase:
    return MemoryDatabase()


@pytest.fixture
def store(db, settings) -> AesGcmSecretStore:
    return AesGcmSecretStore(db, settings.token_encryption_key)


def make_token(user_id: str = USER_A, *, aud: str = "authenticated", exp_in: int = 3600,
               secret: str = JWT_SECRET, email: str = "a@example.com") -> str:
    now = int(time.time())
    return jwt.encode({"sub": user_id, "aud": aud, "email": email, "iat": now, "exp": now + exp_in,
                       "role": "authenticated"}, secret, algorithm="HS256")


def auth(user_id: str = USER_A) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token(user_id)}"}


@pytest.fixture
def client(settings, db, store):
    from app.main import create_app

    app = create_app(settings=settings, db=db, secret_store=store)
    with TestClient(app, follow_redirects=False) as c:
        yield c
