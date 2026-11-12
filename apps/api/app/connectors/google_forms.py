"""Google Forms (docs: developers.google.com/workspace/forms/api).

Scopes: forms.body (create forms, batchUpdate questions) and forms.responses.readonly (list responses).
NOT used: drive (RESTRICTED). forms.create only accepts info.title; questions are added via batchUpdate.
"""

from __future__ import annotations

import re

from app.connectors._google import DRIVE_METADATA, DRIVE_METADATA_LABEL, MIME_FORM, search_tool
from app.connectors._google import google_manifest, path_id
from app.connectors.base import ToolContext, ToolDef, ToolError, object_schema, raise_for_status

API = "https://forms.googleapis.com/v1/forms"
BODY = "https://www.googleapis.com/auth/forms.body"
RESPONSES = "https://www.googleapis.com/auth/forms.responses.readonly"
_URL_ID_RE = re.compile(r"/forms/d/(?:e/)?([a-zA-Z0-9_-]+)")
QUESTION_TYPES = ["short_text", "paragraph", "multiple_choice", "checkbox", "dropdown"]
FORM_ID = {"type": "string", "description": "Form ID or full Google Forms edit URL."}


def _fid(value: str) -> str:
    m = _URL_ID_RE.search(value or "")
    try:
        return m.group(1) if m else path_id(value, "form id")
    except ValueError as exc:
        raise ToolError(str(exc)) from exc


def build_question(question_type: str, options: list[str] | None, required: bool) -> dict:
    if question_type in ("short_text", "paragraph"):
        return {"required": required, "textQuestion": {"paragraph": question_type == "paragraph"}}
    if question_type in ("multiple_choice", "checkbox", "dropdown"):
        opts = [o for o in (options or []) if o and o.strip()]
        if len(opts) < 2:
            raise ToolError("Choice questions need at least two options.")
        kind = {"multiple_choice": "RADIO", "checkbox": "CHECKBOX", "dropdown": "DROP_DOWN"}[question_type]
        return {"required": required, "choiceQuestion": {"type": kind, "options": [{"value": o} for o in opts]}}
    raise ToolError(f"question_type must be one of {', '.join(QUESTION_TYPES)}")


async def create_form(ctx: ToolContext, title: str) -> dict:
    if not title.strip():
        raise ToolError("title must not be empty")
    resp = await ctx.http.post(API, json={"info": {"title": title}}, headers=ctx.bearer)
    raise_for_status(resp, "Creating the form")
    d = resp.json()
    return {"form_id": d.get("formId"), "edit_url": f"https://docs.google.com/forms/d/{d.get('formId')}/edit",
            "responder_url": d.get("responderUri")}


async def add_question(ctx: ToolContext, form_id: str, title: str, question_type: str,
                       options: list[str] | None, required: bool) -> dict:
    if not title.strip():
        raise ToolError("title must not be empty")
    fid = _fid(form_id)
    question = build_question(question_type, options, required)
    # Insert at the end: read the current item count (location.index must be <= number of items).
    got = await ctx.http.get(f"{API}/{fid}", headers=ctx.bearer, params={"fields": "items.itemId"})
    raise_for_status(got, "Reading the form")
    index = len(got.json().get("items", []))
    resp = await ctx.http.post(f"{API}/{fid}:batchUpdate", headers=ctx.bearer, json={"requests": [{
        "createItem": {"item": {"title": title, "questionItem": {"question": question}},
                       "location": {"index": index}}}]})
    raise_for_status(resp, "Adding the question")
    return {"form_id": fid, "position": index + 1, "title": title, "type": question_type}


async def list_responses(ctx: ToolContext, form_id: str, page_size: int) -> dict:
    resp = await ctx.http.get(f"{API}/{_fid(form_id)}/responses", headers=ctx.bearer,
                              params={"pageSize": max(1, min(page_size, 100))})
    raise_for_status(resp, "Listing responses")
    d = resp.json()
    out = []
    for r in d.get("responses", []):
        answers = {qid: [a.get("value") for a in ans.get("textAnswers", {}).get("answers", [])]
                   for qid, ans in (r.get("answers") or {}).items()}
        out.append({"response_id": r.get("responseId"), "submitted": r.get("lastSubmittedTime"), "answers": answers})
    return {"responses": out, "more_available": bool(d.get("nextPageToken"))}


from app.connectors._google import drive_search  # noqa: E402
from app.connectors.base import LoaderDef, option  # noqa: E402


async def load_forms(ctx: ToolContext, params: dict, query: str | None) -> list[dict]:
    found = await drive_search(ctx, MIME_FORM, query, 25)
    return [option(m["id"], m["name"], f"Edited {m['modified'][:10]}" if m.get("modified") else None, m.get("url"))
            for m in found["matches"]]


LOADERS = [LoaderDef(name="forms", description="Your forms, newest first (type to search by name).",
                     handler=load_forms, scopes=[DRIVE_METADATA])]
_FORM = {"kind": "locator", "loader": "forms", "modes": ["list", "url", "id"], "url_pattern": r"/d/([A-Za-z0-9_-]{20,})"}
PARAM_UI = {f"google_forms__{t}": {"form_id": _FORM} for t in ("add_question", "list_responses")}


MANIFEST = google_manifest(
    id="google_forms",
    name="Google Forms",
    description="Find your forms by name, create forms, add questions and read responses.",
    scopes=[BODY, RESPONSES, DRIVE_METADATA],
    core_scopes=[BODY, RESPONSES],
    api_to_enable="Google Forms API",
    scope_labels={BODY: "Forms (create and edit)", RESPONSES: "Form responses", DRIVE_METADATA: DRIVE_METADATA_LABEL},
    loaders=LOADERS, param_ui=PARAM_UI,
    tools=[
        search_tool("google_forms__search_forms", "Google Forms", MIME_FORM),
        ToolDef(
            name="google_forms__create_form",
            description="Create a new empty Google Form with a title.",
            parameters=object_schema({"title": {"type": "string"}}),
            risk="write", handler=create_form, scopes=[BODY],
        ),
        ToolDef(
            name="google_forms__add_question",
            description="Add a question at the end of a form. Choice types need at least two options.",
            parameters=object_schema({
                "form_id": FORM_ID,
                "title": {"type": "string", "description": "The question text."},
                "question_type": {"type": "string", "enum": QUESTION_TYPES},
                "options": {"type": ["array", "null"], "items": {"type": "string"},
                            "description": "Choices for multiple_choice, checkbox, dropdown; otherwise null."},
                "required": {"type": "boolean"},
            }),
            risk="write", handler=add_question, scopes=[BODY],
        ),
        ToolDef(
            name="google_forms__list_responses",
            description="List submitted responses of a form (answers keyed by question id).",
            parameters=object_schema({"form_id": FORM_ID,
                                      "page_size": {"type": "integer", "description": "1 to 100."}}),
            risk="read", handler=list_responses, scopes=[RESPONSES],
        ),
    ],
)
