import base64
import hashlib
import time

import pytest

from app.oauth.state import StateError, pkce_pair, sign_state, verify_state

SECRET = "x" * 40


def test_roundtrip():
    s = sign_state(SECRET, "u1", "slack")
    p = verify_state(SECRET, s, "slack")
    assert p["u"] == "u1" and p["p"] == "slack" and len(p["n"]) >= 16


def test_unique_nonce():
    assert sign_state(SECRET, "u", "slack") != sign_state(SECRET, "u", "slack")


def test_tampered_payload_rejected():
    s = sign_state(SECRET, "u1", "slack")
    body, sig = s.split(".")
    forged = base64.urlsafe_b64encode(b'{"u":"attacker","p":"slack","n":"x","t":9999999999}').rstrip(b"=").decode()
    with pytest.raises(StateError):
        verify_state(SECRET, f"{forged}.{sig}", "slack")


def test_wrong_secret_rejected():
    with pytest.raises(StateError):
        verify_state("y" * 40, sign_state(SECRET, "u", "slack"), "slack")


def test_provider_mismatch_rejected():
    with pytest.raises(StateError):
        verify_state(SECRET, sign_state(SECRET, "u", "slack"), "notion")


def test_expired_rejected():
    s = sign_state(SECRET, "u", "slack", now=time.time() - 601)
    with pytest.raises(StateError):
        verify_state(SECRET, s, "slack")


@pytest.mark.parametrize("bad", ["", "abc", "a.b.c"])
def test_malformed(bad):
    with pytest.raises(StateError):
        verify_state(SECRET, bad, "slack")


def test_short_secret_refused():
    with pytest.raises(StateError):
        sign_state("short", "u", "slack")


def test_pkce_s256():
    verifier, challenge = pkce_pair()
    assert 43 <= len(verifier) <= 128
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    assert challenge == expected
