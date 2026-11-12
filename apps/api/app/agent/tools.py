"""Tool selection (per user's connections) and execution with that user's token."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.agent.modes import Mode, allowed
from app.connectors.base import (ConnectorManifest, OAuthError, ProviderError, ToolContext, ToolDef, ToolError,
                                 missing_scopes)
from app.connectors.registry import get_manifest
from app.core.config import Settings
from app.core.secrets import SecretStore
from app.db.client import Database
from app.oauth.tokens import NeedsReauth, TokenService

log = logging.getLogger(__name__)
MAX_RESULT_CHARS = 12_000


async def _sleep(seconds: float) -> None:   # module-level so tests can replace it
    await asyncio.sleep(seconds)


@dataclass
class BoundTool:
    manifest: ConnectorManifest
    tool: ToolDef
    connection: dict[str, Any]                      # the connection whose token will be used
    own_connection: dict[str, Any] | None = None    # the tool's own connector's connection (its card)

    @property
    def missing(self) -> list[str]:
        """Scopes this tool needs that the chosen connection was not granted ([] = fine or not checked)."""
        if not self.manifest.verifies_scopes:
            return []
        return missing_scopes(self.connection.get("scopes"), self.manifest.required_scopes(self.tool))

    @property
    def auto_approve(self) -> bool:
        """Auto-approve only if the card the user toggled AND the connection used both allow it."""
        own = self.own_connection or self.connection
        return bool(own.get("auto_approve_writes")) and bool(self.connection.get("auto_approve_writes"))

    def scope_error(self) -> str:
        names = list(dict.fromkeys(self.manifest.scope_name(s) for s in self.missing)) or [
            self.manifest.permission_name]
        label = " and ".join(names)
        return (f"{self.manifest.name} is connected, but Google did not grant the {label} permission, "
                f"so this can't run. Reconnect {self.manifest.name} and tick the {label} permission.")


def pick_connection(manifest: ConnectorManifest, tool: ToolDef, own: dict[str, Any],
                    active: list[dict[str, Any]]) -> dict[str, Any]:
    """The connection a tool should run with: one whose granted scopes cover the tool's scopes.

    Order: the connector's own connections (newest first), then other connections of the same
    credential group (e.g. a Docs connection whose token also carries the Sheets scope because
    Google merges earlier grants). A connection that lacks the scope is never chosen over one that
    has it; if none has it we return the connector's own so the caller can report what is missing.
    """
    required = manifest.required_scopes(tool)
    if not manifest.verifies_scopes or not required:
        return own
    group = manifest.credentials_key
    candidates = [c for c in active if c["provider"] == manifest.id]
    for c in active:
        m = get_manifest(c["provider"])
        if m is not None and c["provider"] != manifest.id and m.credentials_key == group \
                and c.get("account_label") == own.get("account_label"):
            candidates.append(c)
    for c in candidates:
        if not missing_scopes(c.get("scopes"), required):
            return c
    return own


def to_openai_tool(tool: ToolDef) -> dict[str, Any]:
    return {"type": "function", "function": {
        "name": tool.name, "description": tool.description, "parameters": tool.parameters, "strict": True}}


def _mentioned(manifest: ConnectorManifest, text: str) -> bool:
    text = text.lower()
    words = {manifest.name.lower(), manifest.id.replace("_", " ")}
    words |= {w for w in re.split(r"[\s_]+", manifest.name.lower()) if len(w) > 3 and w != "google"}
    return any(w in text for w in words)


async def available_tools(db: Database, user_id: str, message: str, max_tools: int,
                          mode: Mode | None = None) -> dict[str, BoundTool]:
    """Tools from the user's active connections only, capped at max_tools, and only those the chat mode allows
    (the scope is applied here, when the list is built, not in the prompt)."""
    conns = [c for c in await db.select("connections", {"user_id": user_id, "status": "active"},
                                        order="created_at.desc")]
    by_provider: dict[str, dict[str, Any]] = {}
    for c in conns:  # most recent connection per provider wins
        by_provider.setdefault(c["provider"], c)

    manifests = [m for p in by_provider if (m := get_manifest(p))]
    if mode is not None:
        manifests = [m for m in manifests if any(allowed(mode, t.name) for t in m.tools)]
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
        own = by_provider[m.id]
        for t in m.tools:
            if mode is None or allowed(mode, t.name):
                out[t.name] = BoundTool(m, t, pick_connection(m, t, own, conns), own)
    return out


def validate_args(tool: ToolDef, args: Any) -> str | None:
    if not isinstance(args, dict):
        return "arguments must be a JSON object"
    expected = set(tool.parameters.get("properties", {}))
    if set(args) != expected:
        missing, extra = expected - set(args), set(args) - expected
        return f"argument mismatch (missing: {sorted(missing)}, unexpected: {sorted(extra)})"
    return None


def log_scope_mismatch(bound: BoundTool) -> None:
    c = bound.connection
    log.warning(
        "scope check: tool=%s connector=%s connection=%s used_connector=%s granted=%s required=%s missing=%s",
        bound.tool.name, bound.manifest.id, c.get("id"), c.get("provider"), sorted(c.get("scopes") or []),
        bound.manifest.required_scopes(bound.tool), bound.missing)


class ToolExecutor:
    def __init__(self, db: Database, store: SecretStore, http: httpx.AsyncClient, settings: Settings):
        self.db = db
        self.tokens = TokenService(db, store, http, settings)
        self.http, self.settings = http, settings

    async def execute(self, bound: BoundTool, args: dict[str, Any]) -> tuple[bool, Any]:
        """Returns (ok, JSON-serializable result). Never raises for provider errors."""
        ok, result, _ms = await self.execute_timed(bound, args)
        return ok, result

    async def execute_timed(self, bound: BoundTool, args: dict[str, Any]) -> tuple[bool, Any, int]:
        started = time.monotonic()
        ok, result = await self._run(bound, args)
        return ok, result, int((time.monotonic() - started) * 1000)

    async def _call_with_retries(self, bound: BoundTool, ctx: ToolContext, args: dict[str, Any]) -> Any:
        """Run the handler. READ tools are retried with backoff on 429 / 5xx / network errors; write and
        destructive tools run exactly once (a retry could duplicate the action)."""
        attempts = self.settings.retry_max_attempts if bound.tool.risk == "read" else 1
        for attempt in range(1, max(attempts, 1) + 1):
            try:
                return await bound.tool.handler(ctx, **args)
            except (ProviderError, httpx.TransportError) as exc:
                retryable = exc.retryable if isinstance(exc, ProviderError) else True
                if not retryable or attempt >= attempts:
                    raise
                hint = exc.retry_after if isinstance(exc, ProviderError) else None
                delay = min(hint if hint is not None else self.settings.retry_base_delay_seconds * 2 ** (attempt - 1),
                            self.settings.retry_max_delay_seconds)
                log.info("retrying %s (attempt %d/%d) in %.1fs", bound.tool.name, attempt + 1, attempts, delay)
                await _sleep(delay)

    async def _run(self, bound: BoundTool, args: dict[str, Any]) -> tuple[bool, Any]:
        name = bound.manifest.name
        if bound.missing:
            # Never call the provider with a token we know lacks the scope (it would be a raw 403).
            log_scope_mismatch(bound)
            return False, {"error": bound.scope_error()}
        try:
            token = await self.tokens.get_token(bound.connection)
            ctx = ToolContext(http=self.http, token=token, settings=self.settings, connection=bound.connection)
            return True, await self._call_with_retries(bound, ctx, args)
        except ProviderError as exc:
            if exc.kind == "scope" and bound.manifest.verifies_scopes:
                # The token claimed the scope but Google refused (stale record, revoked grant...).
                log_scope_mismatch(bound)   # diagnostics only: ids and scope names, never tokens
                return False, {"error": bound.scope_error()}
            if exc.kind == "auth":
                # The provider no longer accepts this credential: show Reconnect on the card.
                await self.tokens.mark(bound.connection["id"], "needs_reauth")
            return False, {"error": str(exc), "kind": exc.kind}
        except ToolError as exc:
            return False, {"error": str(exc)}
        except NeedsReauth:
            return False, {"error": f"{name} needs to be reconnected on the Connections page.", "kind": "auth"}
        except OAuthError as exc:
            log.warning("token refresh failed for %s: %s", bound.manifest.id, exc.code)
            return False, {"error": f"Could not refresh the {name} connection ({exc.code}). "
                                    "Try again shortly, or reconnect it on the Connections page.", "kind": "auth"}
        except httpx.HTTPError as exc:
            log.warning("network error calling %s: %s", bound.tool.name, type(exc).__name__)
            return False, {"error": f"Could not reach {name}. Next step: try again in a minute.", "kind": "server"}
        except Exception as exc:  # noqa: BLE001 — report, never crash the loop
            log.exception("tool %s failed: %s", bound.tool.name, type(exc).__name__)
            return False, {"error": f"{name} returned an unexpected error. Next step: try again, or tell me what you were doing."}
