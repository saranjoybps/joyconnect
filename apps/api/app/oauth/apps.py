"""User-entered provider app credentials (provider_apps) and credential resolution.

Resolution order for a connector flow:
  1. the user's own provider_app for the connector's credential group,
  2. the platform default from env (PLATFORM_<APP>_<FIELD>),
  3. SetupRequired.
"""

from __future__ import annotations

import re
from typing import Any

from app.connectors.base import ConnectorManifest, ResolvedApp, SetupRequired
from app.core.config import Settings
from app.core.secrets import SecretNotFound, SecretStore
from app.db.client import Database

TABLE = "provider_apps"
MAX_VALUE_LEN = 4000


class CredentialValidationError(Exception):
    def __init__(self, errors: dict[str, str]):
        super().__init__("; ".join(f"{k}: {v}" for k, v in errors.items()))
        self.errors = errors


def mask(value: str | None) -> str | None:
    """Show just enough of an identifier to recognise it."""
    if not value:
        return None
    if len(value) <= 8:
        return value[:2] + "•" * (len(value) - 2)
    return f"{value[:4]}…{value[-4:]}"


def validate_values(manifest: ConnectorManifest, values: dict[str, str], *, existing_secrets: set[str]) -> dict[str, str]:
    """Clean and check submitted values. Blank secret fields keep the stored secret."""
    known = {f.key for f in manifest.credential_fields}
    errors: dict[str, str] = {k: "unknown field" for k in values if k not in known}
    cleaned: dict[str, str] = {}
    for f in manifest.credential_fields:
        raw = (values.get(f.key) or "").strip()
        if not raw:
            if f.required and not (f.secret and f.key in existing_secrets):
                errors[f.key] = "required"
            continue
        if len(raw) > MAX_VALUE_LEN:
            errors[f.key] = "too long"
        elif f.pattern and not re.fullmatch(f.pattern, raw):
            errors[f.key] = f.pattern_hint or "invalid format"
        else:
            cleaned[f.key] = raw
    if errors:
        raise CredentialValidationError(errors)
    return cleaned


class ProviderAppService:
    def __init__(self, db: Database, store: SecretStore, settings: Settings):
        self.db, self.store, self.settings = db, store, settings

    async def get_row(self, user_id: str, app_provider: str) -> dict[str, Any] | None:
        rows = await self.db.select(TABLE, {"user_id": user_id, "provider": app_provider})
        return rows[0] if rows else None

    async def _secrets(self, row: dict[str, Any]) -> dict[str, str]:
        if not row.get("secret_id"):
            return {}
        try:
            return dict((await self.store.get(row["secret_id"])).get("secrets") or {})
        except SecretNotFound:
            return {}

    async def load(self, row: dict[str, Any], manifest: ConnectorManifest) -> ResolvedApp:
        values: dict[str, str] = {}
        if row.get("client_id"):
            values[manifest.client_id_field] = row["client_id"]
        values.update({k: str(v) for k, v in (row.get("extra") or {}).items()})
        values.update(await self._secrets(row))
        return ResolvedApp(provider=row["provider"], source="user", values=values, id=row["id"])

    def _complete(self, app: ResolvedApp, manifest: ConnectorManifest) -> bool:
        return all(app.values.get(f.key) for f in manifest.credential_fields if f.required)

    async def resolve(self, user_id: str, manifest: ConnectorManifest) -> ResolvedApp:
        row = await self.get_row(user_id, manifest.credentials_key)
        if row:
            app = await self.load(row, manifest)
            if self._complete(app, manifest):
                return app
        platform = manifest.platform_app(self.settings)
        if platform:
            return platform
        raise SetupRequired(manifest.name)

    async def by_ref(self, user_id: str, manifest: ConnectorManifest, ref: str | None) -> ResolvedApp:
        """The exact app that started a flow (id from the signed state, or 'platform')."""
        if ref in (None, "platform"):
            platform = manifest.platform_app(self.settings)
            if platform:
                return platform
            raise SetupRequired(manifest.name)
        rows = await self.db.select(TABLE, {"id": ref, "user_id": user_id, "provider": manifest.credentials_key})
        if not rows:
            raise SetupRequired(manifest.name)
        app = await self.load(rows[0], manifest)
        if not self._complete(app, manifest):
            raise SetupRequired(manifest.name)
        return app

    async def for_connection(self, connection: dict[str, Any], manifest: ConnectorManifest) -> ResolvedApp:
        return await self.by_ref(connection["user_id"], manifest, connection.get("provider_app_id"))

    async def save(self, user_id: str, manifest: ConnectorManifest, values: dict[str, str]) -> dict[str, Any]:
        row = await self.get_row(user_id, manifest.credentials_key)
        old_secrets = await self._secrets(row) if row else {}
        cleaned = validate_values(manifest, values, existing_secrets=set(old_secrets))

        secrets = {f.key: cleaned.get(f.key, old_secrets.get(f.key)) for f in manifest.credential_fields if f.secret}
        secrets = {k: v for k, v in secrets.items() if v}
        public = {f.key: cleaned[f.key] for f in manifest.credential_fields if not f.secret and f.key in cleaned}
        client_id = public.pop(manifest.client_id_field, None)

        secret_id = await self.store.put(user_id, {"secrets": secrets}) if secrets else None
        fields = {"client_id": client_id, "secret_id": secret_id, "extra": public}
        if row:
            saved = (await self.db.update(TABLE, {"id": row["id"]}, fields))[0]
            if row.get("secret_id"):
                await self.store.delete(row["secret_id"])
            return saved
        return await self.db.insert(TABLE, {"user_id": user_id, "provider": manifest.credentials_key, **fields})

    async def delete(self, row: dict[str, Any]) -> None:
        if row.get("secret_id"):
            try:
                await self.store.delete(row["secret_id"])
            except SecretNotFound:
                pass
        await self.db.delete(TABLE, {"id": row["id"]})

    def public_view(self, row: dict[str, Any] | None, manifest: ConnectorManifest) -> dict[str, Any]:
        """Safe for the browser: masked client id, non-secret extras, which secrets are set."""
        platform = manifest.platform_app(self.settings) is not None
        if row is None:
            return {"provider": manifest.credentials_key, "source": "platform" if platform else "none",
                    "client_id_masked": None, "fields": {}, "secrets_set": [], "platform_available": platform,
                    "created_at": None}
        return {
            "provider": manifest.credentials_key,
            "source": "user",
            "client_id_masked": mask(row.get("client_id")),
            "fields": {k: v for k, v in (row.get("extra") or {}).items()},
            "secrets_set": [f.key for f in manifest.credential_fields if f.secret] if row.get("secret_id") else [],
            "platform_available": platform,
            "created_at": row.get("created_at"),
        }
