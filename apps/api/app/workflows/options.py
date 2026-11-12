"""Load options for node parameters ("load options" / resource locators, as in n8n).

`POST /api/nodes/{type}/options` resolves which loader a parameter uses (from the connector's `param_ui`), runs it
with the chosen connected account through the same executor the chat agent uses (token refresh, scope check,
retries for reads, classified errors), and caches the result briefly per user, account and inputs.
"""

from __future__ import annotations

import json
import time
from typing import Any

from app.agent.tools import BoundTool, ToolExecutor
from app.connectors.base import ToolDef, object_schema
from app.connectors.registry import get_manifest
from app.db.client import Database
from app.workflows.registry import get_registry

CACHE_TTL_SECONDS = 60
CACHE_MAX_ENTRIES = 500


class OptionsError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def is_expression(value: Any) -> bool:
    return isinstance(value, str) and "{{" in value


class OptionsService:
    def __init__(self, db: Database, executor: ToolExecutor, ttl: int = CACHE_TTL_SECONDS,
                 clock=time.monotonic):
        self.db, self.executor, self.ttl, self._clock = db, executor, ttl, clock
        self._cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}

    def _prune(self) -> None:
        now = self._clock()
        for k in [k for k, (exp, _) in self._cache.items() if exp <= now]:
            del self._cache[k]
        while len(self._cache) > CACHE_MAX_ENTRIES:
            self._cache.pop(next(iter(self._cache)))

    async def load(self, user_id: str, node_type: str, parameter: str, connection_id: str,
                   parameters: dict[str, Any], query: str | None = None, refresh: bool = False) -> dict[str, Any]:
        nt = get_registry().get(node_type)
        if nt is None or nt.connector is None:
            raise OptionsError(404, "unknown_node", "That node type does not load options.")
        manifest = get_manifest(nt.connector)
        spec = (manifest.param_ui.get(nt.tool or "", {}) if manifest else {}).get(parameter)
        if manifest is None or spec is None:
            raise OptionsError(404, "no_loader", f"'{parameter}' has no list to load.")
        loader = manifest.loader(spec["loader"])

        conns = await self.db.select("connections", {"id": connection_id, "user_id": user_id})
        if not conns or conns[0]["provider"] != manifest.id or conns[0].get("status") != "active":
            raise OptionsError(409, "no_connection", f"Choose a connected {manifest.name} account first.")
        connection = conns[0]

        inputs: dict[str, Any] = {}
        for dep in spec.get("depends_on", []):
            value = parameters.get(dep)
            if is_expression(value):
                return {"options": [], "cached": False, "loader": loader.name, "unresolved": True,
                        "message": f"“{dep.replace('_', ' ')}” is an expression, so its choices cannot be listed. "
                                   "Type the value instead."}
            if value not in (None, ""):
                inputs[dep] = value
        for need in loader.needs:
            if inputs.get(need) in (None, ""):
                raise OptionsError(422, "missing_dependency", f"Choose “{need.replace('_', ' ')}” first.")

        key = json.dumps([user_id, connection_id, loader.name, inputs, query or ""], sort_keys=True, default=str)
        self._prune()
        hit = self._cache.get(key)
        if hit and not refresh and hit[0] > self._clock():
            return {"options": hit[1], "cached": True, "loader": loader.name}

        options = await self._run(manifest, loader, connection, inputs, query)
        self._cache[key] = (self._clock() + self.ttl, options)
        return {"options": options, "cached": False, "loader": loader.name}

    async def _run(self, manifest, loader, connection, inputs, query) -> list[dict[str, Any]]:
        async def handler(ctx):
            return {"options": (await loader.handler(ctx, inputs, query))[:200]}

        tool = ToolDef(name=f"{manifest.id}__options_{loader.name}", description=loader.description,
                       parameters=object_schema({}), risk="read", handler=handler, scopes=list(loader.scopes))
        bound = BoundTool(manifest, tool, connection, connection)
        if bound.missing:
            raise OptionsError(409, "reconnect", bound.scope_error())
        ok, result = await self.executor.execute(bound, {})
        if ok:
            return result["options"]
        message = str(result.get("error", "Could not load the list."))
        kind = result.get("kind")
        if kind in ("auth", "scope"):
            raise OptionsError(409, "reconnect", message)
        raise OptionsError(404 if kind == "not_found" else 502, kind or "provider_error", message)
