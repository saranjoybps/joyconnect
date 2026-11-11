"""Connection persistence and token lifecycle (store, refresh, revoke)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from app.connectors.base import ConnectorManifest, OAuthError, TokenSet
from app.connectors.registry import get_manifest
from app.core.config import Settings
from app.core.secrets import SecretNotFound, SecretStore
from app.db.client import Database
from app.oauth.providers import refresh_tokens, revoke_tokens

log = logging.getLogger(__name__)
REFRESH_LEEWAY_SECONDS = 60

PUBLIC_FIELDS = ("id", "provider", "status", "account_label", "scopes", "expires_at",
                 "auto_approve_writes", "created_at")


class NeedsReauth(Exception):
    def __init__(self, connection_id: str):
        super().__init__(f"connection {connection_id} needs re-authorization")
        self.connection_id = connection_id


def public_view(row: dict[str, Any]) -> dict[str, Any]:
    return {k: row.get(k) for k in PUBLIC_FIELDS}


def _iso(epoch: int | None) -> str | None:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat() if epoch else None


class TokenService:
    def __init__(self, db: Database, store: SecretStore, http: httpx.AsyncClient, settings: Settings):
        self.db, self.store, self.http, self.settings = db, store, http, settings

    async def get_connection(self, user_id: str, connection_id: str) -> dict[str, Any] | None:
        rows = await self.db.select("connections", {"id": connection_id, "user_id": user_id})
        return rows[0] if rows else None

    async def save_connection(
        self, user_id: str, manifest: ConnectorManifest, token: TokenSet, label: str | None
    ) -> dict[str, Any]:
        """Insert or replace the (user, provider, account_label) connection."""
        secret_id = await self.store.put(user_id, token.payload())
        values = {
            "status": "active",
            "scopes": token.scopes or manifest.scopes,
            "secret_id": secret_id,
            "expires_at": _iso(token.expires_at),
        }
        existing = await self.db.select(
            "connections", {"user_id": user_id, "provider": manifest.id, "account_label": label}
        )
        if existing:
            old = existing[0]
            rows = await self.db.update("connections", {"id": old["id"]}, values)
            await self._delete_secret(old.get("secret_id"))
            return rows[0]
        return await self.db.insert(
            "connections", {"user_id": user_id, "provider": manifest.id, "account_label": label, **values}
        )

    async def _delete_secret(self, secret_id: str | None) -> None:
        if secret_id:
            try:
                await self.store.delete(secret_id)
            except Exception:  # noqa: BLE001
                log.warning("could not delete secret for replaced connection")

    async def mark(self, connection_id: str, status: str) -> None:
        await self.db.update("connections", {"id": connection_id}, {"status": status})

    async def get_token(self, connection: dict[str, Any]) -> TokenSet:
        """Valid token for a connection, refreshing 60 s before expiry."""
        if connection["status"] != "active":
            raise NeedsReauth(connection["id"])
        manifest = get_manifest(connection["provider"])
        if manifest is None:
            raise NeedsReauth(connection["id"])
        try:
            token = TokenSet.from_payload(await self.store.get(connection["secret_id"]))
        except SecretNotFound as exc:
            await self.mark(connection["id"], "needs_reauth")
            raise NeedsReauth(connection["id"]) from exc

        if not token.expires_within(REFRESH_LEEWAY_SECONDS):
            return token
        if not token.refresh_token:
            await self.mark(connection["id"], "needs_reauth")
            raise NeedsReauth(connection["id"])
        try:
            new = await refresh_tokens(self.http, manifest, self.settings, token)
        except OAuthError as exc:
            if exc.code in manifest.reauth_errors or exc.code == "no_refresh_token":
                log.info("refresh rejected for connection %s (%s); needs reauth", connection["id"], exc.code)
                await self.mark(connection["id"], "needs_reauth")
                raise NeedsReauth(connection["id"]) from exc
            raise
        new_secret = await self.store.put(connection["user_id"], new.payload())
        await self.db.update(
            "connections", {"id": connection["id"]},
            {"secret_id": new_secret, "expires_at": _iso(new.expires_at)},
        )
        await self._delete_secret(connection["secret_id"])
        connection["secret_id"] = new_secret
        return new

    async def disconnect(self, connection: dict[str, Any]) -> None:
        """Revoke at the provider (best effort), delete the secret, mark revoked."""
        manifest = get_manifest(connection["provider"])
        secret_id = connection.get("secret_id")
        if manifest and secret_id:
            try:
                token = TokenSet.from_payload(await self.store.get(secret_id))
                await revoke_tokens(self.http, manifest, self.settings, token)
            except Exception as exc:  # noqa: BLE001 — revoke must not block local cleanup
                log.warning("provider revoke failed for %s: %s", connection["provider"], type(exc).__name__)
        await self._delete_secret(secret_id)
        await self.db.update("connections", {"id": connection["id"]}, {"status": "revoked", "secret_id": ""})
