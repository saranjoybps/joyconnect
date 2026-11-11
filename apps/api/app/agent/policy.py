"""Approval policy. Enforced here, never delegated to the model or MCP hints."""

from __future__ import annotations

from typing import Any, Literal

from app.connectors.base import ConnectorManifest, Risk, ToolDef

Decision = Literal["run", "ask"]

_SENSITIVE_KEY_PARTS = ("token", "secret", "password", "passwd", "api_key", "apikey", "authorization", "cookie")
_REDACT_STR_LEN = 60
_PREVIEW_STR_LEN = 4000


def decide(risk: Risk, auto_approve_writes: bool) -> Decision:
    if risk == "read":
        return "run"
    if risk == "write":
        return "run" if auto_approve_writes else "ask"
    return "ask"  # destructive: always ask, even with auto-approve


def _is_sensitive(key: str) -> bool:
    k = key.lower()
    return any(p in k for p in _SENSITIVE_KEY_PARTS)


def redact_args(value: Any, key: str = "") -> Any:
    """Shape-preserving redaction for the audit log (tool_runs.args_redacted)."""
    if key and _is_sensitive(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {k: redact_args(v, k) for k, v in value.items()}
    if isinstance(value, list):
        head = [redact_args(v) for v in value[:5]]
        return head + ([f"…(+{len(value) - 5} items)"] if len(value) > 5 else [])
    if isinstance(value, str) and len(value) > _REDACT_STR_LEN:
        return f"{value[:_REDACT_STR_LEN]}…({len(value)} chars)"
    return value


def _clip(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: "[REDACTED]" if _is_sensitive(k) else _clip(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clip(v) for v in value[:200]]
    if isinstance(value, str) and len(value) > _PREVIEW_STR_LEN:
        return value[:_PREVIEW_STR_LEN] + "…"
    return value


def build_preview(manifest: ConnectorManifest, tool: ToolDef, args: dict[str, Any], *,
                  tool_call_id: str, conversation_id: str, account_label: str | None) -> dict[str, Any]:
    """What the user sees on the approval card (their own data, lightly clipped)."""
    return {
        "tool_call_id": tool_call_id,
        "conversation_id": conversation_id,
        "tool": tool.name,
        "connector": manifest.id,
        "connector_name": manifest.name,
        "account": account_label,
        "action": tool_label(tool),
        "description": tool.description,
        "risk": tool.risk,
        "args": _clip(args),
    }


def tool_label(tool: ToolDef) -> str:
    """'google_sheets__append_row' -> 'Append row'."""
    action = tool.name.split("__", 1)[-1].replace("_", " ")
    return action[:1].upper() + action[1:]
