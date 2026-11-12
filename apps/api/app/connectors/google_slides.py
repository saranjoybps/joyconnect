"""Google Slides.

Scope: presentations (Sensitive; docs: developers.google.com/workspace/slides/api/scopes). It lets the
connector work on decks the user pastes by link, like the Docs and Sheets connectors. The narrower
drive.file would only cover decks this app created. NOT used: drive (RESTRICTED).
Endpoints and request shapes: slides/api/reference/rest/v1/presentations (create, batchUpdate) and
.../presentations/request (CreateSlideRequest, CreateShapeRequest, InsertTextRequest).
"""

from __future__ import annotations

import re
import uuid

from app.connectors._google import DRIVE_METADATA, DRIVE_METADATA_LABEL, MIME_SLIDES, search_tool
from app.connectors._google import google_manifest, path_id
from app.connectors.base import ToolContext, ToolDef, ToolError, object_schema, raise_for_status

API = "https://slides.googleapis.com/v1/presentations"
LAYOUTS = ["BLANK", "TITLE", "TITLE_AND_BODY", "TITLE_ONLY", "SECTION_HEADER", "ONE_COLUMN_TEXT", "MAIN_POINT"]
_URL_ID_RE = re.compile(r"/presentation/d/([a-zA-Z0-9_-]+)")
PRESENTATION_ID = {"type": "string", "description": "Presentation ID or full Google Slides URL."}


def _pid(value: str) -> str:
    m = _URL_ID_RE.search(value or "")
    try:
        return m.group(1) if m else path_id(value, "presentation id")
    except ValueError as exc:
        raise ToolError(str(exc)) from exc


def _object_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


async def _batch(ctx: ToolContext, pid: str, requests: list[dict], what: str) -> dict:
    resp = await ctx.http.post(f"{API}/{pid}:batchUpdate", json={"requests": requests}, headers=ctx.bearer)
    raise_for_status(resp, what)
    return resp.json()


def _slide_text(slide: dict) -> list[str]:
    out = []
    for el in slide.get("pageElements", []):
        for te in el.get("shape", {}).get("text", {}).get("textElements", []):
            text = te.get("textRun", {}).get("content", "").strip()
            if text:
                out.append(text)
    return out


async def create_presentation(ctx: ToolContext, title: str) -> dict:
    if not title.strip():
        raise ToolError("title must not be empty")
    resp = await ctx.http.post(API, json={"title": title}, headers=ctx.bearer)
    raise_for_status(resp, "Creating the presentation")
    data = resp.json()
    pid = data["presentationId"]
    return {"presentation_id": pid, "url": f"https://docs.google.com/presentation/d/{pid}/edit",
            "slide_ids": [s.get("objectId") for s in data.get("slides", [])]}


async def get_presentation(ctx: ToolContext, presentation_id: str) -> dict:
    resp = await ctx.http.get(f"{API}/{_pid(presentation_id)}", headers=ctx.bearer)
    raise_for_status(resp, "Reading the presentation")
    data = resp.json()
    return {"title": data.get("title"), "slides": [
        {"slide_id": s.get("objectId"), "text": _slide_text(s)[:20]} for s in data.get("slides", [])[:100]]}


async def add_slide(ctx: ToolContext, presentation_id: str, layout: str) -> dict:
    if layout not in LAYOUTS:
        raise ToolError(f"layout must be one of {', '.join(LAYOUTS)}")
    pid, slide_id = _pid(presentation_id), _object_id("slide")
    await _batch(ctx, pid, [{"createSlide": {
        "objectId": slide_id, "slideLayoutReference": {"predefinedLayout": layout}}}], "Adding the slide")
    return {"presentation_id": pid, "slide_id": slide_id, "layout": layout}


async def add_text(ctx: ToolContext, presentation_id: str, slide_id: str, text: str,
                   left_pt: float | None, top_pt: float | None) -> dict:
    if not text.strip():
        raise ToolError("text must not be empty")
    pid = _pid(presentation_id)
    try:
        slide = path_id(slide_id, "slide id")
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    box = _object_id("text")
    # One atomic batch: create a text box shape on the slide, then insert the text into it.
    await _batch(ctx, pid, [
        {"createShape": {"objectId": box, "shapeType": "TEXT_BOX", "elementProperties": {
            "pageObjectId": slide,
            "size": {"width": {"magnitude": 500, "unit": "PT"}, "height": {"magnitude": 100, "unit": "PT"}},
            "transform": {"scaleX": 1, "scaleY": 1, "translateX": left_pt if left_pt is not None else 50,
                          "translateY": top_pt if top_pt is not None else 50, "unit": "PT"}}}},
        {"insertText": {"objectId": box, "insertionIndex": 0, "text": text}},
    ], "Adding the text")
    return {"presentation_id": pid, "slide_id": slide, "text_box_id": box}


MANIFEST = google_manifest(
    id="google_slides",
    name="Google Slides",
    description="Find your presentations by name, read them, create decks and add slides or text.",
    scopes=["https://www.googleapis.com/auth/presentations", DRIVE_METADATA],
    core_scopes=["https://www.googleapis.com/auth/presentations"],
    scope_labels={DRIVE_METADATA: DRIVE_METADATA_LABEL},
    api_to_enable="Google Slides API",
    tools=[
        search_tool("google_slides__search_presentations", "Google Slides presentations", MIME_SLIDES),
        ToolDef(
            name="google_slides__create_presentation",
            description="Create a new blank Google Slides presentation with a title.",
            parameters=object_schema({"title": {"type": "string"}}),
            risk="write", handler=create_presentation,
        ),
        ToolDef(
            name="google_slides__get_presentation",
            description="Read a presentation: its title, slide ids and the text on each slide. Use to find a "
                        "slide id before adding text.",
            parameters=object_schema({"presentation_id": PRESENTATION_ID}),
            risk="read", handler=get_presentation,
        ),
        ToolDef(
            name="google_slides__add_slide",
            description="Append a new slide with a predefined layout to the end of a presentation.",
            parameters=object_schema({
                "presentation_id": PRESENTATION_ID,
                "layout": {"type": "string", "enum": LAYOUTS},
            }),
            risk="write", handler=add_slide,
        ),
        ToolDef(
            name="google_slides__add_text",
            description="Add a text box containing the given text to a slide. Use a slide id from "
                        "add_slide, create_presentation or get_presentation.",
            parameters=object_schema({
                "presentation_id": PRESENTATION_ID,
                "slide_id": {"type": "string", "description": "Slide object id."},
                "text": {"type": "string"},
                "left_pt": {"type": ["number", "null"], "description": "Distance from the left in points, or null (50)."},
                "top_pt": {"type": ["number", "null"], "description": "Distance from the top in points, or null (50)."},
            }),
            risk="write", handler=add_text,
        ),
    ],
)
