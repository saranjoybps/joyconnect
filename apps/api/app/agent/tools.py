"""Tool selection (per user's connections) and execution with that user's token."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

import httpx

from app.connectors.base import ConnectorManifest, ToolContext, ToolDef, ToolError
from app.connectors.registry import get_manifest
from app.core.config import Settings
from app.core.secrets import SecretStore
from app.db.client import Database
from app.oauth.tokens import NeedsReauth, TokenService

log = logging.getLogger(__name__)
MAX_RESULT_CHARS = 12_000


@dataclass
class BoundTool:
    manifest: ConnectorManifest
    tool: ToolDef
    connection: dict[str, Any]


def to_openai_tool(tool: ToolDef) -> dict[str, Any]:
    return {"type": "function", "function": {
        "name": tool.name, "description": tool.description, "parameters": tool.parameters, "strict": True}}


def _mentioned(manifest: ConnectorManifest, text: str) -> bool:
    text = text.lower()
    words = {manifest.name.lower(), manifest.id.replace("_", " ")}
    words |= {w for w in re.split(r"[\s_]+", manifest.name.lower()) if len(w) > 3 and w != "google"}
    return any(w in text for w in words)


async def available_tools(db: Database, user_id: str, message: str, max_tools: int) -> dict[str, BoundTool]:
    """Tools from the user's active connections only, capped at max_tools."""
    conns = [c for c in await db.select("connections", {"user_id": user_id, "status": "active"},
                                        order="created_at.desc")]
    by_provider: dict[str, dict[str, Any]] = {}
    for c in conns:  # most recent connection per provider wins
        by_provider.setdefault(c["provider"], c)

    manifests = [m for p in by_provider if (m := get_manifest(p))]
    total = sum(len(m.tools) for m in manifests)
    if total > max_tools:
        recent = await db.select("tool_runs", {"user_id": user_id}, order="created_at.desc", limit=50)
        recent_rank: dict[str, int] = {}
        for i, r in enumerate(recent):
            recent_rank.setdefault(r["tool"].split("__", 1)[0], i)
        manifests.sort(key=lambda m: (not _mentioned(m, message), recent_rank.get(m.id, 10_000), m.id))

    out: dict[str, BoundTool] = {}
    for m in manifests:
        if len(out) + len(m.tools) > max_tools:
            continue
        for t in m.tools:
            out[t.name] = BoundTool(m, t, by_provider[m.id])
    return out


def validate_args(tool: ToolDef, args: Any) -> str | None:
    if not isinstance(args, dict):
        return "arguments must be a JSON object"
    expected = set(tool.parameters.get("properties", {}))
    if set(args) != expected:
        missing, extra = expected - set(args), set(args) - expected
        return f"argument mismatch (missing: {sorted(missing)}, unexpected: {sorted(extra)})"
    return None


class ToolExecutor:
    def __init__(self, db: Database, store: SecretStore, http: httpx.AsyncClient, settings: Settings):
        self.tokens = TokenService(db, store, http, settings)
        self.http, self.settings = http, settings

    async def execute(self, bound: BoundTool, args: dict[str, Any]) -> tuple[bool, Any]:
        """Returns (ok, JSON-serializable result). Never raises for provider errors."""
        name = bound.manifest.name
        try:
            token = await self.tokens.get_token(bound.connection)
            ctx = ToolContext(http=self.http, token=token, settings=self.settings, connection=bound.connection)
            return True, await bound.tool.handler(ctx, **args)
        except NeedsReauth:
            return False, {"error": f"{name} needs to be reconnected on the Connections page."}
        except ToolError as exc:
            return False, {"error": str(exc)}
        except httpx.HTTPError as exc:
            log.warning("network error calling %s: %s", bound.tool.name, type(exc).__name__)
            return False, {"error": f"Could not reach {name}. Try again shortly."}
        except Exception as exc:  # noqa: BLE001 — report, never crash the loop
            log.exception("tool %s failed: %s", bound.tool.name, type(exc).__name__)
            return False, {"error": f"{name} returned an unexpected error."}
