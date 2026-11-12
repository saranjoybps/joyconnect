"""Connector health checks ("Test connection"): one cheap read-only call per connection, no LLM involved.

Uses the same executor as the agent, so token refresh, scope checks and friendly provider errors behave
identically. The result is stored on the connection row (last_checked_at / last_check_ok / last_check_message).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from app.agent.tools import BoundTool, ToolExecutor
from app.connectors.base import ConnectorManifest, ToolDef, object_schema
from app.connectors.registry import get_manifest
from app.core.config import Settings
from app.core.secrets import SecretStore
from app.db.client import Database
from app.oauth.tokens import missing_for


def health_tool_for(manifest: ConnectorManifest) -> tuple[ToolDef, dict[str, Any]] | None:
    if manifest.health_tool:
        return manifest.tool(manifest.health_tool), dict(manifest.health_args)
    if manifest.health:
        # Identity scope only: this check proves the token works, whatever else was granted.
        tool = ToolDef(name=f"{manifest.id}__health_check", description="Check the connection token.",
                       parameters=object_schema({}), risk="read", handler=manifest.health, scopes=["openid"])
        return tool, {}
    return None


async def run_health_check(db: Database, store: SecretStore, http: httpx.AsyncClient, settings: Settings,
                           connection: dict[str, Any]) -> dict[str, Any]:
    manifest = get_manifest(connection["provider"])
    if manifest is None:
        ok, message = False, "This connector no longer exists."
    elif connection.get("status") != "active":
        ok, message = False, f"{manifest.name} needs to be reconnected on the Connections page."
    elif (picked := health_tool_for(manifest)) is None:
        ok, message = False, f"{manifest.name} has no health check defined."
    else:
        tool, args = picked
        bound = BoundTool(manifest, tool, connection, connection)
        ok, result = await ToolExecutor(db, store, http, settings).execute(bound, args)
        if ok:
            message = "Working: the provider answered normally."
            if missing_for(connection):
                names = ", ".join(dict.fromkeys(manifest.scope_name(s) for s in missing_for(connection)))
                message += f" Partial access: missing {names}. Reconnect and tick every permission."
        else:
            message = str(result.get("error", "The check failed."))
    now = datetime.now(timezone.utc).isoformat()
    await db.update("connections", {"id": connection["id"]},
                    {"last_checked_at": now, "last_check_ok": ok, "last_check_message": message[:500]})
    return {"ok": ok, "message": message, "checked_at": now, "connection_id": connection["id"],
            "provider": connection["provider"]}
