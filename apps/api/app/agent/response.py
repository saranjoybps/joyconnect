"""The assistant's response contract.

A turn ends with (a) a short summary in Markdown, streamed as `token` events, and (b) a list of
actions, one per tool call, built HERE from the audited tool result and never from the model's own
claims. Both are validated; if validation fails the caller falls back to plain text. Raw JSON is
never shown to the user.
"""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

from app.agent.policy import scrub
from app.connectors.registry import get_manifest

LINK_KEYS = ("spreadsheetUrl", "url", "html_url", "htmlLink", "webViewLink", "edit_url", "permalink_url",
             "meeting_link", "responder_url")
ErrorKind = Literal["auth", "scope", "server", "other"]


class Action(BaseModel):
    """What one tool call did. This is the structured half of the response."""

    id: str
    connector: str
    connector_name: str
    tool: str
    label: str
    ok: bool
    result: str = Field(max_length=300)          # one readable line, secrets scrubbed
    link: str | None = None                       # http(s) URL of the created/changed item
    error_kind: ErrorKind | None = None           # drives Reconnect vs Retry in the UI

    @field_validator("link")
    @classmethod
    def _http_only(cls, v: str | None) -> str | None:
        return v if v is None or re.match(r"^https?://", v) else None


def find_link(result: Any) -> str | None:
    if isinstance(result, list) and len(result) == 1:
        result = result[0]
    if not isinstance(result, dict):
        return None
    for key in LINK_KEYS:
        v = result.get(key)
        if isinstance(v, str) and re.match(r"^https?://", v):
            return v
    return None


def _readable(result: Any) -> str:
    if isinstance(result, dict):
        for key in ("title", "name", "summary", "message", "updatedRange", "updated_range"):
            v = result.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()
        return "Done"
    if isinstance(result, list):
        return f"{len(result)} item{'s' if len(result) != 1 else ''}"
    return "Done"


def _kind(result: Any) -> ErrorKind:
    k = result.get("kind") if isinstance(result, dict) else None
    text = str(result.get("error", "")).lower() if isinstance(result, dict) else ""
    if k in ("auth", "scope", "server"):
        return k
    if "reconnect" in text or "permission" in text:
        return "scope" if "permission" in text else "auth"
    return "other"


def build_action(call_id: str, tool: str, ok: bool, result: Any) -> Action | None:
    """Validated Action for a tool result, or None if it cannot be validated (caller falls back)."""
    connector, _, name = tool.partition("__")
    manifest = get_manifest(connector)
    label = (name or tool).replace("_", " ")
    text = scrub(str(result.get("error", "Something went wrong")) if not ok and isinstance(result, dict)
                 else _readable(result))
    try:
        return Action(
            id=call_id, connector=connector, connector_name=manifest.name if manifest else connector, tool=tool,
            label=label[:1].upper() + label[1:], ok=ok, result=text[:300],
            link=find_link(result) if ok else None, error_kind=None if ok else _kind(result))
    except ValidationError:
        return None


def action_from_message(call_id: str, tool: str, content: str | None) -> Action | None:
    """Rebuild an Action from a stored tool message (used when a conversation is reopened)."""
    try:
        result = json.loads(content or "null")
    except json.JSONDecodeError:
        result = content
    ok = not (isinstance(result, dict) and "error" in result)
    return build_action(call_id, tool, ok, result)


_JSON_LIKE = re.compile(r"^\s*[\[{]")


def plain_summary(text: str) -> str:
    """Fallback for a final message that is raw JSON instead of readable Markdown: never show it."""
    if not _JSON_LIKE.match(text or ""):
        return text
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return text
    if isinstance(data, dict):
        for key in ("summary", "message", "text", "answer"):
            if isinstance(data.get(key), str) and data[key].strip():
                return data[key]
    return "Done. See the actions above for details."
