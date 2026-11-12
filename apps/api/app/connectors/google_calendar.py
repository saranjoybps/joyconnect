from __future__ import annotations

import re

from app.connectors._google import google_manifest
from app.connectors.base import ToolContext, ToolDef, ToolError, object_schema, raise_for_status

# Scopes (each endpoint's docs list which scopes authorize it; these are the narrowest that do).
EVENTS = "https://www.googleapis.com/auth/calendar.events"                         # events.*
CALENDAR_LIST = "https://www.googleapis.com/auth/calendar.calendarlist.readonly"   # calendarList.list
FREEBUSY = "https://www.googleapis.com/auth/calendar.freebusy"                     # freebusy.query
BASE = "https://www.googleapis.com/calendar/v3"
API = f"{BASE}/calendars/primary/events"
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


def _event_url(event_id: str) -> str:
    from urllib.parse import quote

    if not event_id.strip():
        raise ToolError("event_id is required")
    return f"{API}/{quote(event_id.strip(), safe='')}"


async def update_event(ctx: ToolContext, event_id: str, summary: str | None, start: str | None, end: str | None,
                       description: str | None, location: str | None, notify_attendees: bool) -> dict:
    """events.patch: only the fields given are changed (arrays would be overwritten, none are sent)."""
    body: dict = {}
    if summary is not None:
        body["summary"] = summary
    if description is not None:
        body["description"] = description
    if location is not None:
        body["location"] = location
    if (start is None) != (end is None):
        raise ToolError("Give both start and end to move an event, or neither.")
    if start is not None and end is not None:
        if bool(DATE_RE.match(start)) != bool(DATE_RE.match(end)):
            raise ToolError("start and end must both be dates or both be timestamps")
        body["start"], body["end"] = _when(start), _when(end)
    if not body:
        raise ToolError("Nothing to change: give at least one field.")
    resp = await ctx.http.patch(_event_url(event_id), json=body, headers=ctx.bearer,
                                params={"sendUpdates": "all" if notify_attendees else "none"})
    raise_for_status(resp, "Updating the event")
    return _summarize(resp.json())


async def delete_event(ctx: ToolContext, event_id: str, notify_attendees: bool) -> dict:
    resp = await ctx.http.delete(_event_url(event_id), headers=ctx.bearer,
                                 params={"sendUpdates": "all" if notify_attendees else "none"})
    raise_for_status(resp, "Deleting the event")
    return {"deleted": True, "event_id": event_id}


async def list_calendars(ctx: ToolContext) -> dict:
    resp = await ctx.http.get(f"{BASE}/users/me/calendarList", headers=ctx.bearer, params={"maxResults": 250})
    raise_for_status(resp, "Listing calendars")
    return {"calendars": [
        {"id": c.get("id"), "name": c.get("summary"), "primary": bool(c.get("primary")),
         "access_role": c.get("accessRole"), "time_zone": c.get("timeZone")}
        for c in resp.json().get("items", [])]}


async def free_busy(ctx: ToolContext, time_min: str, time_max: str, calendar_ids: list[str] | None) -> dict:
    ids = calendar_ids or ["primary"]
    if len(ids) > 50:
        raise ToolError("At most 50 calendars can be checked at once.")
    resp = await ctx.http.post(f"{BASE}/freeBusy", headers=ctx.bearer, json={
        "timeMin": time_min, "timeMax": time_max, "items": [{"id": i} for i in ids]})
    raise_for_status(resp, "Checking availability")
    data = resp.json().get("calendars", {})
    return {"calendars": {cid: {"busy": v.get("busy", []), "errors": v.get("errors", [])} for cid, v in data.items()}}


from datetime import datetime, timedelta, timezone  # noqa: E402

from app.connectors.base import LoaderDef, option  # noqa: E402


async def load_calendars(ctx: ToolContext, params: dict, query: str | None) -> list[dict]:
    out = await list_calendars(ctx)
    return [option(c["id"], c["name"] + (" (primary)" if c.get("primary") else ""), c.get("access_role"))
            for c in out["calendars"]]


async def load_events(ctx: ToolContext, params: dict, query: str | None) -> list[dict]:
    """Upcoming events (next 60 days) so an event can be picked instead of typing its id."""
    now = datetime.now(timezone.utc)
    out = await list_events(ctx, now.isoformat(), (now + timedelta(days=60)).isoformat())
    return [option(e["id"], e.get("summary") or "(no title)", e.get("start")) for e in out["events"]]


LOADERS = [
    LoaderDef(name="calendars", description="Your calendars.", handler=load_calendars, scopes_of="google_calendar__list_calendars"),
    LoaderDef(name="events", description="Your upcoming events (next 60 days).", handler=load_events,
              scopes_of="google_calendar__list_events"),
]
_EVENT = {"kind": "options", "loader": "events"}
PARAM_UI = {
    "google_calendar__free_busy": {"calendar_ids": {"kind": "multi", "loader": "calendars"}},
    "google_calendar__update_event": {"event_id": _EVENT},
    "google_calendar__delete_event": {"event_id": _EVENT},
}


MANIFEST = google_manifest(
    id="google_calendar",
    name="Google Calendar",
    description="See and create events on your primary calendar.",
    scopes=[EVENTS, CALENDAR_LIST, FREEBUSY],
    api_to_enable="Google Calendar API",
    health_tool="google_calendar__list_calendars", health_args={},
    scope_labels={EVENTS: "Calendar events", CALENDAR_LIST: "Calendar list", FREEBUSY: "Free/busy"},
    loaders=LOADERS, param_ui=PARAM_UI,
    tools=[
        ToolDef(
            name="google_calendar__list_events",
            description="List events on the user's primary calendar between two times.",
            parameters=object_schema({
                "time_min": {"type": "string", "description": f"Start of window. {RFC3339}"},
                "time_max": {"type": "string", "description": f"End of window. {RFC3339}"},
            }),
            risk="read", handler=list_events, scopes=[EVENTS],
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
            risk="write", handler=create_event, scopes=[EVENTS],
        ),
        ToolDef(
            name="google_calendar__update_event",
            description="Change fields of an existing event on the primary calendar (partial update). Use an id "
                        "returned by list_events or create_event. Give start and end together to move it.",
            parameters=object_schema({
                "event_id": {"type": "string"},
                "summary": {"type": ["string", "null"], "description": "New title, or null to keep."},
                "start": {"type": ["string", "null"], "description": f"New start or null. {RFC3339}"},
                "end": {"type": ["string", "null"], "description": f"New end or null. {RFC3339}"},
                "description": {"type": ["string", "null"], "description": "New description, or null to keep."},
                "location": {"type": ["string", "null"], "description": "New location, or null to keep."},
                "notify_attendees": {"type": "boolean", "description": "Email attendees about the change."},
            }),
            risk="write", handler=update_event, scopes=[EVENTS],
        ),
        ToolDef(
            name="google_calendar__delete_event",
            description="Permanently delete an event from the primary calendar. Use only when the user clearly "
                        "asks to delete or cancel a specific event.",
            parameters=object_schema({
                "event_id": {"type": "string"},
                "notify_attendees": {"type": "boolean", "description": "Email attendees about the cancellation."},
            }),
            risk="destructive", handler=delete_event, scopes=[EVENTS],
        ),
        ToolDef(
            name="google_calendar__list_calendars",
            description="List the calendars the user is subscribed to (ids, names, access role).",
            parameters=object_schema({}),
            risk="read", handler=list_calendars, scopes=[CALENDAR_LIST],
        ),
        ToolDef(
            name="google_calendar__free_busy",
            description="Check when calendars are busy between two times, to find free slots. Returns busy "
                        "intervals only, no event details.",
            parameters=object_schema({
                "time_min": {"type": "string", "description": f"Start of window. {RFC3339}"},
                "time_max": {"type": "string", "description": f"End of window. {RFC3339}"},
                "calendar_ids": {"type": ["array", "null"], "items": {"type": "string"},
                                 "description": "Calendar ids (emails or ids from list_calendars), or null for "
                                                "the primary calendar. At most 50."},
            }),
            risk="read", handler=free_busy, scopes=[FREEBUSY],
        ),
    ],
)
