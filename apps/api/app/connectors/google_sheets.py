from __future__ import annotations

from urllib.parse import quote

from app.connectors._google import google_manifest, parse_google_file_id
from app.connectors.base import ToolContext, ToolDef, ToolError, object_schema, raise_for_status

API = "https://sheets.googleapis.com/v4/spreadsheets"

SPREADSHEET_ID = {"type": "string", "description": "Spreadsheet ID or full Google Sheets URL pasted by the user."}
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


MANIFEST = google_manifest(
    id="google_sheets",
    name="Google Sheets",
    description="Read and write rows in spreadsheets you share by link or ID.",
    scopes=["https://www.googleapis.com/auth/spreadsheets"],
    tools=[
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
    ],
)
