import sys
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from app.core import security
from app.core.logging import redact
from tests.conftest import USER_A, auth, make_token


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_me_requires_token(client):
    assert client.get("/api/me").status_code == 401


def test_me_with_valid_token(client):
    resp = client.get("/api/me", headers=auth())
    assert resp.status_code == 200
    assert resp.json() == {"id": USER_A, "email": "a@example.com"}


@pytest.mark.parametrize("token", [
    make_token(exp_in=-10),
    make_token(aud="anon"),
    make_token(secret="wrong-secret-wrong-secret-wrong-secret-xx"),
    "garbage",
])
def test_me_rejects_bad_tokens(client, token):
    assert client.get("/api/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_hs256_rejected_when_no_secret_configured(client, settings):
    settings.supabase_jwt_secret = ""
    assert client.get("/api/me", headers=auth()).status_code == 401


def test_es256_via_jwks(client, monkeypatch):
    key = ec.generate_private_key(ec.SECP256R1())
    now = int(time.time())
    token = jwt.encode({"sub": USER_A, "aud": "authenticated", "exp": now + 60}, key,
                       algorithm="ES256", headers={"kid": "k1"})

    class FakeJwk:
        def get_signing_key_from_jwt(self, _):
            return type("K", (), {"key": key.public_key()})()

    monkeypatch.setattr(security, "_jwk_client", lambda s: FakeJwk())
    resp = client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200 and resp.json()["id"] == USER_A

    other = ec.generate_private_key(ec.SECP256R1())
    forged = jwt.encode({"sub": USER_A, "aud": "authenticated", "exp": now + 60}, other,
                        algorithm="ES256", headers={"kid": "k1"})
    assert client.get("/api/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401


def test_alg_none_rejected(client):
    token = jwt.encode({"sub": USER_A, "aud": "authenticated"}, None, algorithm="none")
    assert client.get("/api/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


@pytest.mark.parametrize("raw,leak", [
    ("Authorization: Bearer abc.def.ghi", "abc.def.ghi"),
    ('{"access_token": "ya29.xyz"}', "ya29.xyz"),
    ("code=4/0Abc&state=s1", "4/0Abc"),
    ("token xoxb-123-456-abc", "123-456-abc"),
    ("ghu_ABCdef123 used", "ABCdef123"),
    ("postgresql://postgres:hunter2@db.x.supabase.co:5432/postgres", "hunter2"),
])
def test_redaction(raw, leak):
    assert leak not in redact(raw)


def test_traceback_is_redacted():
    import logging

    from app.core.logging import RedactingFilter

    try:
        raise ValueError("refresh_token=1//secretvalue")
    except ValueError:
        record = logging.LogRecord("x", logging.ERROR, __file__, 1, "failed", None, sys.exc_info())
    RedactingFilter().filter(record)
    assert "secretvalue" not in record.getMessage() and record.exc_info is None
