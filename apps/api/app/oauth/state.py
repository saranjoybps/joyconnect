"""Signed, single-use OAuth state and PKCE helpers.

The state carries (user id, provider, nonce, issued-at) and an HMAC.
Single use and the 10 minute limit are enforced against the oauth_states
row, which also holds the PKCE verifier (the verifier never leaves the server).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time

STATE_TTL_SECONDS = 600


class StateError(Exception):
    pass


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def _key(secret: str) -> bytes:
    if len(secret) < 32:
        raise StateError("OAUTH_STATE_SECRET must be at least 32 characters")
    return secret.encode()


def sign_state(secret: str, user_id: str, provider: str, now: float | None = None) -> str:
    payload = {"u": user_id, "p": provider, "n": secrets.token_urlsafe(16), "t": int(now or time.time())}
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    sig = _b64(hmac.new(_key(secret), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def verify_state(secret: str, state: str, provider: str, now: float | None = None) -> dict:
    try:
        body, sig = state.split(".")
    except ValueError as exc:
        raise StateError("malformed state") from exc
    expected = _b64(hmac.new(_key(secret), body.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        raise StateError("bad state signature")
    payload = json.loads(_unb64(body))
    if payload.get("p") != provider:
        raise StateError("state provider mismatch")
    if (now or time.time()) - payload.get("t", 0) > STATE_TTL_SECONDS:
        raise StateError("state expired")
    return payload


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)[:96]
    challenge = _b64(hashlib.sha256(verifier.encode()).digest())
    return verifier, challenge
