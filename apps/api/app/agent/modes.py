"""Chat modes and their tool scope.

  /custom      (default) every connected app
  /workflow    builder mode: only workflow tools (no app tools), so the agent plans and edits workflows
  /<connector> only that connector's tools, e.g. /google-docs, /sheets, /trello

The scope is enforced by the server in two places, never by the prompt:
  1. when the tool list for a model call is built (`available_tools(..., mode)`), and
  2. when a call is dispatched or an approved call is resumed (`allowed(mode, tool_name)`).
A model that asks for a tool outside the scope gets "not available in this mode"; the provider is never called.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.connectors.registry import all_manifests

CUSTOM, WORKFLOW, CONNECTOR = "custom", "workflow", "connector"
# Tools of the workflow builder (added in step 6: create/get/list/update/run/delete_workflow).
WORKFLOW_TOOLS: frozenset[str] = frozenset()

_CMD = re.compile(r"^/([A-Za-z][A-Za-z0-9_-]*)(?:\s+(.*))?$", re.S)


@dataclass(frozen=True)
class Mode:
    kind: str = CUSTOM                  # custom | workflow | connector
    connector: str | None = None        # manifest id when kind == connector

    @property
    def command(self) -> str:
        return {CUSTOM: "custom", WORKFLOW: "workflow"}.get(self.kind) or slug(self.connector or "")

    @property
    def row(self) -> dict[str, Any]:
        """What is stored on the conversation: `mode` and `tool_scope`."""
        return {"mode": self.kind, "tool_scope": self.connector}

    @staticmethod
    def from_row(row: dict[str, Any] | None) -> "Mode":
        kind = (row or {}).get("mode") or CUSTOM
        if kind == CONNECTOR and (row or {}).get("tool_scope") in all_manifests():
            return Mode(CONNECTOR, row["tool_scope"])
        return Mode(WORKFLOW) if kind == WORKFLOW else Mode(CUSTOM)


def slug(manifest_id: str) -> str:
    return manifest_id.replace("_", "-")


def aliases(manifest_id: str) -> list[str]:
    """Short forms accepted as well: /sheets for /google-sheets."""
    s = slug(manifest_id)
    return [s[len("google-"):]] if s.startswith("google-") else []


def _lookup() -> dict[str, str]:
    out: dict[str, str] = {}
    for mid in all_manifests():
        out[slug(mid)] = mid
        for a in aliases(mid):
            out.setdefault(a, mid)
    return out


def resolve(command: str) -> Mode | None:
    """A command word (without the slash) to a Mode, or None if it is not one."""
    c = command.strip().lstrip("/").lower()
    if c in ("custom", "workflow"):
        return Mode(c)
    mid = _lookup().get(c)
    return Mode(CONNECTOR, mid) if mid else None


def split_command(text: str) -> tuple[Mode | None, str, str | None]:
    """`/trello list my boards` -> (Mode(trello), 'list my boards', None). A leading word that is not a known
    command is left alone as the message, except that a lone `/word` is reported as unknown (third item)."""
    m = _CMD.match(text.strip())
    if not m:
        return None, text, None
    mode = resolve(m.group(1))
    if mode is None:
        return None, text, m.group(1)
    return mode, (m.group(2) or "").strip(), None


def allowed(mode: Mode, tool_name: str) -> bool:
    """May this tool be offered or run in this mode? Decided from the tool's name alone."""
    if mode.kind == WORKFLOW:
        return tool_name in WORKFLOW_TOOLS
    if mode.kind == CONNECTOR:
        return tool_name.split("__", 1)[0] == mode.connector
    return True


def describe(mode: Mode) -> str:
    if mode.kind == WORKFLOW:
        return ("You are in /workflow mode, the workflow builder. You can only plan and discuss workflows; you have "
                "no tools for the user's apps here. If the user wants an action performed in an app, tell them to "
                "switch with /custom or /<app>.")
    if mode.kind == CONNECTOR:
        name = all_manifests()[mode.connector].name  # type: ignore[index]
        return (f"You are in /{mode.command} mode: you only have {name} tools. If the user asks for something "
                f"outside {name}, say so and tell them to switch with /custom.")
    return ""
