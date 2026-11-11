"""SecretStore: encrypted storage for provider token payloads.

Payload shape: {access_token, refresh_token, expires_at, token_type, extra}.
"""

from __future__ import annotations

import base64
import json
import os
from typing import Any, Protocol

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.db.client import Database


class SecretNotFound(Exception):
    pass


class SecretStore(Protocol):
    async def put(self, user_id: str, payload: dict[str, Any]) -> str: ...
    async def get(self, secret_id: str) -> dict[str, Any]: ...
    async def delete(self, secret_id: str) -> None: ...


def _load_key(key_b64: str) -> bytes:
    try:
        key = base64.b64decode(key_b64, validate=True)
    except Exception as exc:  # noqa: BLE001
        raise ValueError("TOKEN_ENCRYPTION_KEY must be base64") from exc
    if len(key) != 32:
        raise ValueError("TOKEN_ENCRYPTION_KEY must decode to exactly 32 bytes")
    return key


class AesGcmSecretStore:
    """AES-256-GCM; ciphertext lives in the `secrets` table (no client access).

    The row id and user id are bound as associated data, so a ciphertext
    cannot be moved to another row or user without failing authentication.
    """

    TABLE = "secrets"

    def __init__(self, db: Database, key_b64: str):
        self._db = db
        self._aead = AESGCM(_load_key(key_b64))

    @staticmethod
    def _aad(secret_id: str, user_id: str) -> bytes:
        return f"{secret_id}:{user_id}".encode()

    async def put(self, user_id: str, payload: dict[str, Any]) -> str:
        import uuid

        secret_id = str(uuid.uuid4())
        nonce = os.urandom(12)
        ct = self._aead.encrypt(nonce, json.dumps(payload).encode(), self._aad(secret_id, user_id))
        await self._db.insert(
            self.TABLE,
            {
                "id": secret_id,
                "user_id": user_id,
                "nonce": base64.b64encode(nonce).decode(),
                "ciphertext": base64.b64encode(ct).decode(),
            },
        )
        return secret_id

    async def get(self, secret_id: str) -> dict[str, Any]:
        rows = await self._db.select(self.TABLE, {"id": secret_id})
        if not rows:
            raise SecretNotFound(secret_id)
        row = rows[0]
        plain = self._aead.decrypt(
            base64.b64decode(row["nonce"]),
            base64.b64decode(row["ciphertext"]),
            self._aad(secret_id, row["user_id"]),
        )
        return json.loads(plain)

    async def delete(self, secret_id: str) -> None:
        await self._db.delete(self.TABLE, {"id": secret_id})


class VaultSecretStore:
    """Supabase Vault via service-role-only SQL functions (migration 0002)."""

    def __init__(self, db: Database):
        self._db = db

    async def put(self, user_id: str, payload: dict[str, Any]) -> str:
        return str(await self._db.rpc("app_secret_put", {"p_user_id": user_id, "p_payload": json.dumps(payload)}))

    async def get(self, secret_id: str) -> dict[str, Any]:
        raw = await self._db.rpc("app_secret_get", {"p_id": secret_id})
        if raw is None:
            raise SecretNotFound(secret_id)
        return json.loads(raw)

    async def delete(self, secret_id: str) -> None:
        await self._db.rpc("app_secret_delete", {"p_id": secret_id})


def build_secret_store(kind: str, db: Database, key_b64: str) -> SecretStore:
    if kind == "aesgcm":
        return AesGcmSecretStore(db, key_b64)
    if kind == "vault":
        return VaultSecretStore(db)
    raise ValueError(f"unknown SECRET_STORE: {kind}")
