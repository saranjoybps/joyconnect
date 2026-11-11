"""Auto-discovers connector modules (any module in this package exposing MANIFEST)."""

from __future__ import annotations

import importlib
import pkgutil
from functools import lru_cache

from app.connectors.base import ConnectorManifest, ToolDef

_SKIP = {"base", "registry"}


@lru_cache
def all_manifests() -> dict[str, ConnectorManifest]:
    import app.connectors as pkg

    found: dict[str, ConnectorManifest] = {}
    for info in pkgutil.iter_modules(pkg.__path__):
        if info.name in _SKIP or info.name.startswith("_"):
            continue
        module = importlib.import_module(f"{pkg.__name__}.{info.name}")
        manifest = getattr(module, "MANIFEST", None)
        if isinstance(manifest, ConnectorManifest):
            if manifest.id in found:
                raise RuntimeError(f"duplicate connector id: {manifest.id}")
            if manifest.auth_type == "oauth2" and not {manifest.client_id_field, manifest.client_secret_field} <= {
                    f.key for f in manifest.credential_fields}:
                raise RuntimeError(f"{manifest.id}: oauth2 connectors must declare client id/secret credential_fields")
            if manifest.auth_type != "oauth2" and manifest.validate_credentials is None:
                raise RuntimeError(f"{manifest.id}: {manifest.auth_type} connectors need validate_credentials")
            for tool in manifest.tools:
                if not tool.name.startswith(f"{manifest.id}__"):
                    raise RuntimeError(f"tool {tool.name} must be prefixed with {manifest.id}__")
            found[manifest.id] = manifest
    return dict(sorted(found.items()))


def get_manifest(provider_id: str) -> ConnectorManifest | None:
    return all_manifests().get(provider_id)


def all_tools() -> dict[str, tuple[ConnectorManifest, ToolDef]]:
    return {t.name: (m, t) for m in all_manifests().values() for t in m.tools}
