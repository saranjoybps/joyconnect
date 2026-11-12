"""Google Drive: drive.file (create, non-sensitive) plus drive.metadata.readonly (search, RESTRICTED).

drive.file (docs: developers.google.com/workspace/drive/api/guides/api-specific-auth) is
non-sensitive: the app can only see files and folders it created (or the user opened with it).
drive.metadata.readonly is classified RESTRICTED by the same page: it lets the agent FIND files by name
(files.list accepts it). Added at the owner's request; see docs/decisions.md.
NOT used: drive, drive.readonly (RESTRICTED, and they expose file contents).
Multipart upload format and the 5 MB limit: .../drive/api/guides/manage-uploads.
"""

from __future__ import annotations

import json
import uuid

from app.connectors._google import DRIVE_METADATA, DRIVE_METADATA_LABEL, google_manifest, path_id
from app.connectors.base import ToolContext, ToolDef, ToolError, object_schema, raise_for_status

API = "https://www.googleapis.com/drive/v3/files"
UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"
FILE_SCOPE = "https://www.googleapis.com/auth/drive.file"
FOLDER = "application/vnd.google-apps.folder"
MAX_UPLOAD_BYTES = 5 * 1024 * 1024          # multipart limit per the upload guide
FIELDS = "id,name,mimeType,webViewLink,createdTime,modifiedTime,parents"
TEXT_TYPES = ["text/plain", "text/csv", "text/markdown", "application/json"]


def _pid(value: str | None, what: str) -> str | None:
    if value is None or not value.strip():
        return None
    try:
        return path_id(value, what)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc


def _file(f: dict) -> dict:
    return {"id": f.get("id"), "name": f.get("name"), "type": f.get("mimeType"), "url": f.get("webViewLink"),
            "created": f.get("createdTime"), "modified": f.get("modifiedTime")}


def _q_literal(value: str) -> str:
    """A Drive query string literal: escape backslash and single quote."""
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


async def create_folder(ctx: ToolContext, name: str, parent_id: str | None) -> dict:
    if not name.strip():
        raise ToolError("name must not be empty")
    body: dict = {"name": name, "mimeType": FOLDER}
    if (parent := _pid(parent_id, "folder id")):
        body["parents"] = [parent]
    resp = await ctx.http.post(API, json=body, params={"fields": FIELDS}, headers=ctx.bearer)
    raise_for_status(resp, "Creating the folder")
    return _file(resp.json())


def multipart_body(metadata: dict, content: str, mime_type: str, boundary: str) -> bytes:
    """multipart/related: JSON metadata part first, then the media part (Drive upload guide)."""
    return (
        f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{json.dumps(metadata)}\r\n"
        f"--{boundary}\r\nContent-Type: {mime_type}; charset=UTF-8\r\n\r\n{content}\r\n--{boundary}--"
    ).encode()


async def upload_text_file(ctx: ToolContext, name: str, content: str, mime_type: str, parent_id: str | None) -> dict:
    if not name.strip():
        raise ToolError("name must not be empty")
    if mime_type not in TEXT_TYPES:
        raise ToolError(f"mime_type must be one of {', '.join(TEXT_TYPES)}")
    metadata: dict = {"name": name}
    if (parent := _pid(parent_id, "folder id")):
        metadata["parents"] = [parent]
    boundary = f"connect-{uuid.uuid4().hex}"
    body = multipart_body(metadata, content, mime_type, boundary)
    if len(body) > MAX_UPLOAD_BYTES:
        raise ToolError("The file is larger than the 5 MB limit for this upload type.")
    resp = await ctx.http.post(
        UPLOAD, content=body, params={"uploadType": "multipart", "fields": FIELDS},
        headers={**ctx.bearer, "Content-Type": f"multipart/related; boundary={boundary}"})
    raise_for_status(resp, "Uploading the file")
    return _file(resp.json())


async def list_files(ctx: ToolContext, name_contains: str | None, folder_id: str | None, page_size: int) -> dict:
    clauses = ["trashed = false"]
    if name_contains and name_contains.strip():
        clauses.append(f"name contains {_q_literal(name_contains.strip())}")
    if (folder := _pid(folder_id, "folder id")):
        clauses.append(f"{_q_literal(folder)} in parents")
    resp = await ctx.http.get(API, headers=ctx.bearer, params={
        "q": " and ".join(clauses), "pageSize": max(1, min(page_size, 100)), "orderBy": "modifiedTime desc",
        "fields": f"files({FIELDS}),nextPageToken"})
    raise_for_status(resp, "Listing files")
    data = resp.json()
    return {"files": [_file(f) for f in data.get("files", [])], "more_available": bool(data.get("nextPageToken")),
            "note": "Only files and folders created by this app are visible (drive.file scope)."}


async def search_files(ctx: ToolContext, query: str | None, limit: int | None) -> dict:
    clauses = ["trashed = false"] + [f"name contains {_q_literal(w)}" for w in (query or "").split()[:6]]
    resp = await ctx.http.get(API, headers=ctx.bearer, params={
        "q": " and ".join(clauses), "pageSize": max(1, min(limit or 10, 25)), "orderBy": "modifiedTime desc",
        "fields": f"files({FIELDS}),nextPageToken"})
    raise_for_status(resp, "Searching Google Drive")
    data = resp.json()
    files = [_file(f) for f in data.get("files", [])]
    return {"matches": files, "count": len(files), "more_available": bool(data.get("nextPageToken")),
            "note": "Newest first. If several look right, ask the user which one."}


from app.connectors._google import MIME_FOLDER, drive_search  # noqa: E402
from app.connectors.base import LoaderDef, option  # noqa: E402


async def load_folders(ctx: ToolContext, params: dict, query: str | None) -> list[dict]:
    found = await drive_search(ctx, MIME_FOLDER, query, 25)
    return [option(m["id"], m["name"], f"Edited {m['modified'][:10]}" if m.get("modified") else None, m.get("url"))
            for m in found["matches"]]


LOADERS = [LoaderDef(name="folders", description="Your folders, newest first (type to search by name).",
                     handler=load_folders, scopes=[DRIVE_METADATA])]
_FOLDER = {"kind": "options", "loader": "folders", "empty_label": "My Drive (top level)"}
PARAM_UI = {
    "google_drive__create_folder": {"parent_id": _FOLDER},
    "google_drive__upload_text_file": {"parent_id": _FOLDER},
    "google_drive__list_files": {"folder_id": _FOLDER},
}


MANIFEST = google_manifest(
    id="google_drive",
    name="Google Drive",
    description="Search your Drive by name, and create folders and text files.",
    scopes=[FILE_SCOPE, DRIVE_METADATA],
    core_scopes=[FILE_SCOPE],
    scope_labels={DRIVE_METADATA: DRIVE_METADATA_LABEL},
    api_to_enable="Google Drive API",
    health_tool="google_drive__list_files", health_args={"name_contains": None, "folder_id": None, "page_size": 1},
    loaders=LOADERS, param_ui=PARAM_UI,
    tools=[
        ToolDef(
            name="google_drive__search_files",
            description="Find any file or folder in the user's Drive by name (newest first) and get its id, type and link. Use this FIRST when the user names a file or asks what is in Drive; never ask for a link or id you can find. Pass null for query to list recent files.",
            parameters=object_schema({
                "query": {"type": ["string", "null"], "description": "Words from the name, or null."},
                "limit": {"type": ["integer", "null"], "description": "1 to 25, or null for 10."}}),
            risk="read", handler=search_files, scopes=[DRIVE_METADATA]),
        ToolDef(
            name="google_drive__create_folder",
            description="Create a folder in the user's Drive (optionally inside a folder this app created).",
            parameters=object_schema({
                "name": {"type": "string"},
                "parent_id": {"type": ["string", "null"], "description": "Parent folder id from this app, or null for My Drive."},
            }),
            risk="write", handler=create_folder,
        ),
        ToolDef(
            name="google_drive__upload_text_file",
            description="Create a text file (txt, csv, markdown or json) with the given content, up to 5 MB.",
            parameters=object_schema({
                "name": {"type": "string", "description": "File name including extension, e.g. notes.txt."},
                "content": {"type": "string"},
                "mime_type": {"type": "string", "enum": TEXT_TYPES},
                "parent_id": {"type": ["string", "null"], "description": "Folder id from this app, or null."},
            }),
            risk="write", handler=upload_text_file,
        ),
        ToolDef(
            name="google_drive__list_files",
            description="List files and folders this app created in the user's Drive (newest first). It "
                        "cannot list anything else in Drive.",
            parameters=object_schema({
                "name_contains": {"type": ["string", "null"], "description": "Filter by part of the name, or null."},
                "folder_id": {"type": ["string", "null"], "description": "Only files in this folder, or null."},
                "page_size": {"type": "integer", "description": "1 to 100."},
            }),
            risk="read", handler=list_files,
        ),
    ],
)
