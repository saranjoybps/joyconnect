from __future__ import annotations

import re
from urllib.parse import quote

from app.connectors._google import (DRIVE_METADATA, DRIVE_METADATA_LABEL, MIME_SHEET, google_manifest,
                                    parse_google_file_id, search_tool)
from app.connectors.base import ToolContext, ToolDef, ToolError, object_schema, raise_for_status

API = "https://sheets.googleapis.com/v4/spreadsheets"

SPREADSHEET_ID = {"type": "string", "description": "Spreadsheet ID (from google_sheets__search_spreadsheets) or a Google Sheets URL the user already gave."}
RANGE = {"type": "string", "description": "A1 range, e.g. 'Sheet1!A1:D20' or 'Sheet1'."}


def _sid(value: str) -> str:
    try:
        return parse_google_file_id(value)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc


async def get_values(ctx: ToolContext, spreadsheet_id: str, range: str) -> dict:
    resp = await ctx.http.get(f"{API}/{_sid(spreadsheet_id)}/values/{quote(range, safe='')}", headers=ctx.bearer)
    raise_for_status(resp, "Reading the sheet")
    data = resp.json()
    values = data.get("values", [])
    return {"range": data.get("range"), "rows": values[:500], "truncated": len(values) > 500}


async def append_row(ctx: ToolContext, spreadsheet_id: str, range: str, values: list[str]) -> dict:
    resp = await ctx.http.post(
        f"{API}/{_sid(spreadsheet_id)}/values/{quote(range, safe='')}:append",
        params={"valueInputOption": "USER_ENTERED", "insertDataOption": "INSERT_ROWS"},
        json={"values": [values]},
        headers=ctx.bearer,
    )
    raise_for_status(resp, "Appending the row")
    updates = resp.json().get("updates", {})
    return {"updated_range": updates.get("updatedRange"), "updated_cells": updates.get("updatedCells")}


async def update_values(ctx: ToolContext, spreadsheet_id: str, range: str, values: list[list[str]]) -> dict:
    resp = await ctx.http.put(
        f"{API}/{_sid(spreadsheet_id)}/values/{quote(range, safe='')}",
        params={"valueInputOption": "USER_ENTERED"},
        json={"values": values},
        headers=ctx.bearer,
    )
    raise_for_status(resp, "Updating the sheet")
    data = resp.json()
    return {"updated_range": data.get("updatedRange"), "updated_cells": data.get("updatedCells")}


async def create_spreadsheet(ctx: ToolContext, title: str) -> dict:
    resp = await ctx.http.post(API, json={"properties": {"title": title}}, headers=ctx.bearer)
    raise_for_status(resp, "Creating the spreadsheet")
    data = resp.json()
    return {"spreadsheet_id": data["spreadsheetId"], "url": data.get("spreadsheetUrl")}


async def list_tabs(ctx: ToolContext, spreadsheet_id: str) -> dict:
    resp = await ctx.http.get(f"{API}/{_sid(spreadsheet_id)}", headers=ctx.bearer,
                              params={"fields": "properties.title,sheets.properties"})
    raise_for_status(resp, "Listing the tabs")
    data = resp.json()
    return {"title": data.get("properties", {}).get("title"), "tabs": [
        {"sheet_id": p.get("sheetId"), "title": p.get("title"), "index": p.get("index"),
         "rows": p.get("gridProperties", {}).get("rowCount"), "columns": p.get("gridProperties", {}).get("columnCount")}
        for p in (s.get("properties", {}) for s in data.get("sheets", []))]}


async def add_tab(ctx: ToolContext, spreadsheet_id: str, title: str) -> dict:
    if not title.strip():
        raise ToolError("title must not be empty")
    resp = await ctx.http.post(f"{API}/{_sid(spreadsheet_id)}:batchUpdate", headers=ctx.bearer,
                               json={"requests": [{"addSheet": {"properties": {"title": title}}}]})
    raise_for_status(resp, "Adding the tab")
    props = (resp.json().get("replies") or [{}])[0].get("addSheet", {}).get("properties", {})
    return {"sheet_id": props.get("sheetId"), "title": props.get("title", title)}


async def clear_range(ctx: ToolContext, spreadsheet_id: str, range: str) -> dict:
    resp = await ctx.http.post(f"{API}/{_sid(spreadsheet_id)}/values/{quote(range, safe='')}:clear",
                               headers=ctx.bearer, json={})
    raise_for_status(resp, "Clearing the range")
    return {"cleared_range": resp.json().get("clearedRange")}


from app.connectors._google import drive_search  # noqa: E402
from app.connectors.base import LoaderDef, option  # noqa: E402


def _quote_tab(tab: str) -> str:
    return "'" + tab.replace("'", "''") + "'"


def tab_of(range_: str | None) -> str | None:
    """The tab named in an A1 range: "'My tab'!A:B" -> "My tab", "Sheet1" -> "Sheet1", "A1:B2" stays a tab-less range."""
    if not range_ or not range_.strip():
        return None
    head = range_.rsplit("!", 1)[0] if "!" in range_ else range_
    if "!" not in range_ and re.fullmatch(r"\$?[A-Za-z]{1,3}\$?\d*(:\$?[A-Za-z]{1,3}\$?\d*)?", head):
        return None                                  # a bare cell range such as A1:B2 names no tab
    if head.startswith("'") and head.endswith("'") and len(head) >= 2:
        head = head[1:-1].replace("''", "'")
    return head or None


def _column_name(i: int) -> str:
    n, out = i + 1, ""
    while n:
        n, r = divmod(n - 1, 26)
        out = chr(65 + r) + out
    return out


async def load_spreadsheets(ctx: ToolContext, params: dict, query: str | None) -> list[dict]:
    found = await drive_search(ctx, MIME_SHEET, query, 25)      # the same call the chat tool makes
    return [option(m["id"], m["name"], f"Edited {m['modified'][:10]}" if m.get("modified") else None, m.get("url"))
            for m in found["matches"]]


async def load_tabs(ctx: ToolContext, params: dict, query: str | None) -> list[dict]:
    out = await list_tabs(ctx, params["spreadsheet_id"])
    return [option(t["title"], t["title"], f"{t['rows']} rows, {t['columns']} columns") for t in out["tabs"]]


async def load_columns(ctx: ToolContext, params: dict, query: str | None) -> list[dict]:
    """Header row (row 1) of the chosen tab: the columns a row has, in order."""
    sid, tab = params["spreadsheet_id"], tab_of(params.get("range"))
    if tab is None:
        tabs = (await list_tabs(ctx, sid))["tabs"]
        if not tabs:
            return []
        tab = tabs[0]["title"]
    rows = (await get_values(ctx, sid, f"{_quote_tab(tab)}!1:1"))["rows"]
    header = rows[0] if rows else []
    return [option(str(h).strip() or f"Column {_column_name(i)}", str(h).strip() or f"Column {_column_name(i)}",
                   f"Column {_column_name(i)}") for i, h in enumerate(header)]


LOADERS = [
    LoaderDef(name="spreadsheets", description="Your spreadsheets, newest first (type to search by name).",
              handler=load_spreadsheets, scopes=[DRIVE_METADATA]),
    LoaderDef(name="tabs", description="The tabs of a spreadsheet.", handler=load_tabs, needs=["spreadsheet_id"]),
    LoaderDef(name="columns", description="The column headers (row 1) of a tab.", handler=load_columns,
              needs=["spreadsheet_id"]),
]
_SS = {"kind": "locator", "loader": "spreadsheets", "modes": ["list", "url", "id"], "url_pattern": r"/d/([A-Za-z0-9_-]{20,})"}
_TAB = {"kind": "range", "loader": "tabs", "depends_on": ["spreadsheet_id"]}
PARAM_UI = {
    "google_sheets__get_values": {"spreadsheet_id": _SS, "range": _TAB},
    "google_sheets__append_row": {
        "spreadsheet_id": _SS, "range": _TAB,
        "values": {"kind": "columns", "loader": "columns", "depends_on": ["spreadsheet_id", "range"], "output": "array"}},
    "google_sheets__update_values": {"spreadsheet_id": _SS, "range": _TAB},
    "google_sheets__list_tabs": {"spreadsheet_id": _SS},
    "google_sheets__add_tab": {"spreadsheet_id": _SS},
    "google_sheets__clear_range": {"spreadsheet_id": _SS, "range": _TAB},
}


MANIFEST = google_manifest(
    id="google_sheets",
    name="Google Sheets",
    description="Find your spreadsheets by name, read them, and add or change rows.",
    scopes=["https://www.googleapis.com/auth/spreadsheets", DRIVE_METADATA],
    core_scopes=["https://www.googleapis.com/auth/spreadsheets"],
    scope_labels={DRIVE_METADATA: DRIVE_METADATA_LABEL},
    api_to_enable="Google Sheets API",
    loaders=LOADERS, param_ui=PARAM_UI,
    tools=[
        search_tool("google_sheets__search_spreadsheets", "Google Sheets spreadsheets", MIME_SHEET),
        ToolDef(
            name="google_sheets__get_values",
            description="Read cell values from a range of a Google Sheet. Use to look up or list rows.",
            parameters=object_schema({"spreadsheet_id": SPREADSHEET_ID, "range": RANGE}),
            risk="read", handler=get_values,
        ),
        ToolDef(
            name="google_sheets__append_row",
            description="Append one row after the last row of a table in a Google Sheet.",
            parameters=object_schema({
                "spreadsheet_id": SPREADSHEET_ID,
                "range": {**RANGE, "description": "Sheet or table range to append to, e.g. 'Sheet1!A:D'."},
                "values": {"type": "array", "items": {"type": "string"}, "description": "Cell values, left to right."},
            }),
            risk="write", handler=append_row,
        ),
        ToolDef(
            name="google_sheets__update_values",
            description="Overwrite cells in an exact range of a Google Sheet.",
            parameters=object_schema({
                "spreadsheet_id": SPREADSHEET_ID,
                "range": RANGE,
                "values": {"type": "array", "items": {"type": "array", "items": {"type": "string"}},
                           "description": "Rows of cell values."},
            }),
            risk="write", handler=update_values,
        ),
        ToolDef(
            name="google_sheets__create_spreadsheet",
            description="Create a new, empty Google Sheet and return its ID and URL.",
            parameters=object_schema({"title": {"type": "string"}}),
            risk="write", handler=create_spreadsheet,
        ),
        ToolDef(
            name="google_sheets__list_tabs",
            description="List the tabs (sheets) of a spreadsheet with their names and sizes. Use to find the "
                        "exact tab name before reading or writing a range.",
            parameters=object_schema({"spreadsheet_id": SPREADSHEET_ID}),
            risk="read", handler=list_tabs,
        ),
        ToolDef(
            name="google_sheets__add_tab",
            description="Add a new empty tab (sheet) to a spreadsheet.",
            parameters=object_schema({"spreadsheet_id": SPREADSHEET_ID, "title": {"type": "string"}}),
            risk="write", handler=add_tab,
        ),
        ToolDef(
            name="google_sheets__clear_range",
            description="Erase the values in a range (formatting is kept). Use only when the user asks to "
                        "clear or empty cells.",
            parameters=object_schema({"spreadsheet_id": SPREADSHEET_ID, "range": RANGE}),
            risk="destructive", handler=clear_range,
        ),
    ],
)
