from __future__ import annotations

import re

from app.connectors._google import google_manifest
from app.connectors.base import ToolContext, ToolDef, ToolError, object_schema, raise_for_status

API = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
RFC3339 = ("RFC 3339 timestamp with offset, e.g. '2026-11-12T09:00:00+05:30', "
           "or a date 'YYYY-MM-DD' for all-day events.")


def _when(value: str) -> dict:
    return {"date": value} if DATE_RE.match(value) else {"dateTime": value}


def _summarize(ev: dict) -> dict:
    return {
        "id": ev.get("id"),
        "summary": ev.get("summary"),
        "start": ev.get("start", {}).get("dateTime") or ev.get("start", {}).get("date"),
        "end": ev.get("end", {}).get("dateTime") or ev.get("end", {}).get("date"),
        "location": ev.get("location"),
        "attendees": [a.get("email") for a in ev.get("attendees", [])],
        "url": ev.get("htmlLink"),
    }


async def list_events(ctx: ToolContext, time_min: str, time_max: str) -> dict:
    resp = await ctx.http.get(API, headers=ctx.bearer, params={
        "timeMin": time_min, "timeMax": time_max, "singleEvents": "true",
        "orderBy": "startTime", "maxResults": 50,
    })
    raise_for_status(resp, "Listing events")
    return {"events": [_summarize(e) for e in resp.json().get("items", [])]}


async def create_event(ctx: ToolContext, summary: str, start: str, end: str, attendees: list[str] | None) -> dict:
    if bool(DATE_RE.match(start)) != bool(DATE_RE.match(end)):
        raise ToolError("start and end must both be dates or both be timestamps")
    body: dict = {"summary": summary, "start": _when(start), "end": _when(end)}
    if attendees:
        body["attendees"] = [{"email": a} for a in attendees]
    resp = await ctx.http.post(API, json=body, headers=ctx.bearer)
    raise_for_status(resp, "Creating the event")
    return _summarize(resp.json())


MANIFEST = google_manifest(
    id="google_calendar",
    name="Google Calendar",
    description="See and create events on your primary calendar.",
    scopes=["https://www.googleapis.com/auth/calendar.events"],
    tools=[
        ToolDef(
            name="google_calendar__list_events",
            description="List events on the user's primary calendar between two times.",
            parameters=object_schema({
                "time_min": {"type": "string", "description": f"Start of window. {RFC3339}"},
                "time_max": {"type": "string", "description": f"End of window. {RFC3339}"},
            }),
            risk="read", handler=list_events,
        ),
        ToolDef(
            name="google_calendar__create_event",
            description="Create an event on the user's primary calendar. Attendees get invitations.",
            parameters=object_schema({
                "summary": {"type": "string", "description": "Event title."},
                "start": {"type": "string", "description": RFC3339},
                "end": {"type": "string", "description": RFC3339},
                "attendees": {"type": ["array", "null"], "items": {"type": "string"},
                              "description": "Attendee emails, or null."},
            }),
            risk="write", handler=create_event,
        ),
    ],
)
