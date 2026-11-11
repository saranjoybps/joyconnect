import base64
import json
import os

import pytest
from cryptography.exceptions import InvalidTag

from app.core.secrets import AesGcmSecretStore, SecretNotFound, VaultSecretStore, build_secret_store
from app.db.client import MemoryDatabase

PAYLOAD = {"access_token": "ya29.abc", "refresh_token": "1//r", "expires_at": 123,
           "token_type": "Bearer", "extra": {"k": "v"}}


async def test_roundtrip(store, db):
    sid = await store.put("user-1", PAYLOAD)
    assert await store.get(sid) == PAYLOAD
    row = db.tables["secrets"][0]
    assert "ya29" not in json.dumps(row)  # stored encrypted


async def test_unique_nonce_per_put(store, db):
    await store.put("u", PAYLOAD)
    await store.put("u", PAYLOAD)
    n1, n2 = (r["nonce"] for r in db.tables["secrets"])
    assert n1 != n2


async def test_tampered_ciphertext_fails(store, db):
    sid = await store.put("u", PAYLOAD)
    row = db.tables["secrets"][0]
    ct = bytearray(base64.b64decode(row["ciphertext"]))
    ct[0] ^= 1
    row["ciphertext"] = base64.b64encode(bytes(ct)).decode()
    with pytest.raises(InvalidTag):
        await store.get(sid)


async def test_ciphertext_bound_to_user(store, db):
    sid = await store.put("user-1", PAYLOAD)
    db.tables["secrets"][0]["user_id"] = "user-2"
    with pytest.raises(InvalidTag):
        await store.get(sid)


async def test_wrong_key_fails(db):
    a = AesGcmSecretStore(db, base64.b64encode(os.urandom(32)).decode())
    b = AesGcmSecretStore(db, base64.b64encode(os.urandom(32)).decode())
    sid = await a.put("u", PAYLOAD)
    with pytest.raises(InvalidTag):
        await b.get(sid)


async def test_delete(store):
    sid = await store.put("u", PAYLOAD)
    await store.delete(sid)
    with pytest.raises(SecretNotFound):
        await store.get(sid)


@pytest.mark.parametrize("key", ["", "not base64!!", base64.b64encode(b"short").decode()])
def test_bad_key_rejected(key):
    with pytest.raises(ValueError):
        AesGcmSecretStore(MemoryDatabase(), key)


async def test_vault_store_uses_rpcs():
    db = MemoryDatabase()
    vault: dict[str, str] = {}

    def put(p_user_id, p_payload):
        vault["id-1"] = p_payload
        return "id-1"

    db.rpcs = {
        "app_secret_put": put,
        "app_secret_get": lambda p_id: vault.get(p_id),
        "app_secret_delete": lambda p_id: vault.pop(p_id, None),
    }
    store = build_secret_store("vault", db, "")
    assert isinstance(store, VaultSecretStore)
    sid = await store.put("u", PAYLOAD)
    assert await store.get(sid) == PAYLOAD
    await store.delete(sid)
    with pytest.raises(SecretNotFound):
        await store.get(sid)
