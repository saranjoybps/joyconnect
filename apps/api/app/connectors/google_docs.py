from __future__ import annotations

from app.connectors._google import (DRIVE_METADATA, DRIVE_METADATA_LABEL, MIME_DOC, google_manifest,
                                    parse_google_file_id, search_tool)
from app.connectors.base import ToolContext, ToolDef, ToolError, object_schema, raise_for_status

API = "https://docs.googleapis.com/v1/documents"
MAX_CHARS = 20_000

DOCUMENT_ID = {"type": "string", "description": "Document ID (from google_docs__search_documents) or a Google Docs URL the user already gave."}


def _did(value: str) -> str:
    try:
        return parse_google_file_id(value)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc


async def _insert_at_end(ctx: ToolContext, document_id: str, text: str) -> None:
    resp = await ctx.http.post(
        f"{API}/{document_id}:batchUpdate",
        json={"requests": [{"insertText": {"text": text, "endOfSegmentLocation": {}}}]},
        headers=ctx.bearer,
    )
    raise_for_status(resp, "Writing to the document")


async def create_document(ctx: ToolContext, title: str, content: str | None) -> dict:
    resp = await ctx.http.post(API, json={"title": title}, headers=ctx.bearer)
    raise_for_status(resp, "Creating the document")
    doc_id = resp.json()["documentId"]
    if content:
        await _insert_at_end(ctx, doc_id, content)
    return {"document_id": doc_id, "url": f"https://docs.google.com/document/d/{doc_id}/edit"}


def _plain_text(doc: dict) -> str:
    out: list[str] = []
    for block in doc.get("body", {}).get("content", []):
        for el in block.get("paragraph", {}).get("elements", []):
            out.append(el.get("textRun", {}).get("content", ""))
    return "".join(out)


async def get_document(ctx: ToolContext, document_id: str) -> dict:
    resp = await ctx.http.get(f"{API}/{_did(document_id)}", headers=ctx.bearer)
    raise_for_status(resp, "Reading the document")
    doc = resp.json()
    text = _plain_text(doc)
    return {"title": doc.get("title"), "text": text[:MAX_CHARS], "truncated": len(text) > MAX_CHARS}


async def append_text(ctx: ToolContext, document_id: str, text: str) -> dict:
    did = _did(document_id)
    await _insert_at_end(ctx, did, text if text.startswith("\n") else f"\n{text}")
    return {"document_id": did, "appended_chars": len(text)}


async def _batch(ctx: ToolContext, did: str, requests: list[dict], what: str) -> dict:
    resp = await ctx.http.post(f"{API}/{did}:batchUpdate", json={"requests": requests}, headers=ctx.bearer)
    raise_for_status(resp, what)
    return resp.json()


async def replace_text(ctx: ToolContext, document_id: str, find: str, replace_with: str, match_case: bool) -> dict:
    if not find:
        raise ToolError("find must not be empty")
    did = _did(document_id)
    data = await _batch(ctx, did, [{"replaceAllText": {
        "containsText": {"text": find, "matchCase": match_case}, "replaceText": replace_with}}],
        "Replacing text")
    changed = (data.get("replies") or [{}])[0].get("replaceAllText", {}).get("occurrencesChanged", 0)
    return {"document_id": did, "occurrences_changed": changed}


async def insert_table(ctx: ToolContext, document_id: str, rows: int, columns: int) -> dict:
    if not (1 <= rows <= 50 and 1 <= columns <= 20):
        raise ToolError("rows must be 1-50 and columns 1-20")
    did = _did(document_id)
    await _batch(ctx, did, [{"insertTable": {"rows": rows, "columns": columns, "endOfSegmentLocation": {}}}],
                 "Inserting the table")
    return {"document_id": did, "rows": rows, "columns": columns}


MANIFEST = google_manifest(
    id="google_docs",
    name="Google Docs",
    description="Find your documents by name, read them, create new ones and append or replace text.",
    scopes=["https://www.googleapis.com/auth/documents", DRIVE_METADATA],
    core_scopes=["https://www.googleapis.com/auth/documents"],
    scope_labels={DRIVE_METADATA: DRIVE_METADATA_LABEL},
    api_to_enable="Google Docs API",
    tools=[
        search_tool("google_docs__search_documents", "Google Docs documents", MIME_DOC),
        ToolDef(
            name="google_docs__create_document",
            description="Create a new Google Doc with a title and optional starting text.",
            parameters=object_schema({
                "title": {"type": "string"},
                "content": {"type": ["string", "null"], "description": "Initial body text, or null."},
            }),
            risk="write", handler=create_document,
        ),
        ToolDef(
            name="google_docs__get_document",
            description="Read the title and plain text of a Google Doc.",
            parameters=object_schema({"document_id": DOCUMENT_ID}),
            risk="read", handler=get_document,
        ),
        ToolDef(
            name="google_docs__append_text",
            description="Append text as a new paragraph at the end of a Google Doc.",
            parameters=object_schema({"document_id": DOCUMENT_ID, "text": {"type": "string"}}),
            risk="write", handler=append_text,
        ),
        ToolDef(
            name="google_docs__replace_text",
            description="Replace every occurrence of some text in a Google Doc with other text.",
            parameters=object_schema({
                "document_id": DOCUMENT_ID,
                "find": {"type": "string", "description": "Text to find."},
                "replace_with": {"type": "string", "description": "Replacement text (may be empty to remove)."},
                "match_case": {"type": "boolean"},
            }),
            risk="write", handler=replace_text,
        ),
        ToolDef(
            name="google_docs__insert_table",
            description="Insert an empty table at the end of a Google Doc.",
            parameters=object_schema({
                "document_id": DOCUMENT_ID,
                "rows": {"type": "integer", "description": "1 to 50."},
                "columns": {"type": "integer", "description": "1 to 20."},
            }),
            risk="write", handler=insert_table,
        ),
    ],
)
