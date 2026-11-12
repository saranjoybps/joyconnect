"""Gmail: send email and list labels.

Scopes (docs: developers.google.com/workspace/gmail/api/auth/scopes):
  gmail.send    Sensitive      authorizes users.messages.send
  gmail.labels  Non-sensitive  authorizes users.labels.list
NOT used: gmail.compose (RESTRICTED; the only scope family that authorizes drafts.create besides the
restricted modify / mail.google.com), gmail.readonly, gmail.modify, gmail.metadata (all RESTRICTED).
So there is deliberately no "create draft" tool.
"""

from __future__ import annotations

import base64
import re
from email.message import EmailMessage

from app.connectors._google import google_manifest
from app.connectors.base import ToolContext, ToolDef, ToolError, object_schema, raise_for_status

API = "https://gmail.googleapis.com/gmail/v1/users/me"
SEND = "https://www.googleapis.com/auth/gmail.send"
LABELS = "https://www.googleapis.com/auth/gmail.labels"
MAX_RECIPIENTS = 50          # Gmail's documented hard limit is 500 per message; stay far below
MAX_BODY_CHARS = 100_000
_EMAIL_RE = re.compile(r"^[^@\s,;<>\"]+@[^@\s,;<>\"]+\.[^@\s,;<>\"]+$")


def _addresses(values: list[str], field: str) -> list[str]:
    out = [v.strip() for v in values or [] if v and v.strip()]
    bad = [v for v in out if not _EMAIL_RE.match(v)]
    if bad:
        raise ToolError(f"Not a valid email address in {field}: {bad[0]}")
    return out


def build_raw_message(to: list[str], subject: str, body: str, cc: list[str], bcc: list[str]) -> str:
    """RFC 2822 message, base64url encoded: the `raw` field of messages.send (Gmail sending guide)."""
    if not to:
        raise ToolError("At least one recipient is required.")
    if len(to) + len(cc) + len(bcc) > MAX_RECIPIENTS:
        raise ToolError(f"At most {MAX_RECIPIENTS} recipients are allowed.")
    if len(body) > MAX_BODY_CHARS:
        raise ToolError("The email body is too long.")
    msg = EmailMessage()
    try:
        msg["To"] = ", ".join(to)
        if cc:
            msg["Cc"] = ", ".join(cc)
        if bcc:
            msg["Bcc"] = ", ".join(bcc)
        msg["Subject"] = subject          # EmailMessage rejects header values containing newlines
        msg.set_content(body)
    except ValueError as exc:
        raise ToolError("The subject or an address contains invalid characters.") from exc
    return base64.urlsafe_b64encode(msg.as_bytes()).decode()


async def send_email(ctx: ToolContext, to: list[str], subject: str, body: str,
                     cc: list[str] | None, bcc: list[str] | None) -> dict:
    raw = build_raw_message(_addresses(to, "to"), subject, body, _addresses(cc or [], "cc"),
                            _addresses(bcc or [], "bcc"))
    resp = await ctx.http.post(f"{API}/messages/send", json={"raw": raw}, headers=ctx.bearer)
    raise_for_status(resp, "Sending the email")
    data = resp.json()
    return {"sent": True, "message_id": data.get("id"), "thread_id": data.get("threadId")}


async def list_labels(ctx: ToolContext) -> dict:
    resp = await ctx.http.get(f"{API}/labels", headers=ctx.bearer)
    raise_for_status(resp, "Listing labels")
    return {"labels": [{"id": l.get("id"), "name": l.get("name"), "type": l.get("type")}
                       for l in resp.json().get("labels", [])]}


MANIFEST = google_manifest(
    id="gmail",
    name="Gmail",
    description="Send email from your account and list your labels. Cannot read your mail.",
    scopes=[SEND, LABELS],
    api_to_enable="Gmail API",
    health_tool="gmail__list_labels", health_args={},
    scope_labels={SEND: "Send email", LABELS: "Gmail labels"},
    tools=[
        ToolDef(
            name="gmail__send_email",
            description="Send a plain-text email from the user's Gmail account. Sending cannot be undone: "
                        "only use when the user explicitly asks to send, with the recipient, subject and body "
                        "they gave.",
            parameters=object_schema({
                "to": {"type": "array", "items": {"type": "string"}, "description": "Recipient email addresses."},
                "subject": {"type": "string"},
                "body": {"type": "string", "description": "Plain-text body."},
                "cc": {"type": ["array", "null"], "items": {"type": "string"}, "description": "Cc addresses or null."},
                "bcc": {"type": ["array", "null"], "items": {"type": "string"}, "description": "Bcc addresses or null."},
            }),
            risk="destructive", handler=send_email, scopes=[SEND],
        ),
        ToolDef(
            name="gmail__list_labels",
            description="List the user's Gmail labels (id, name, type). Label names only; no email content.",
            parameters=object_schema({}),
            risk="read", handler=list_labels, scopes=[LABELS],
        ),
    ],
)
