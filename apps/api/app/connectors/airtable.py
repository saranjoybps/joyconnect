"""Airtable via a personal access token (developers: airtable.com/developers/web/api).

Auth: `Authorization: Bearer <PAT>`. PAT scopes needed: schema.bases:read (list bases),
data.records:read, data.records:write. Rate limit: 5 requests/second per base (429 -> wait 30 s).
Create accepts up to 10 records per request; we send one.
"""

from __future__ import annotations

import json
import re
from urllib.parse import quote

from app.connectors._apikey import api_key_manifest, checked_get
from app.connectors.base import (CredentialField, Settings, TokenSet, ToolContext, ToolDef, ToolError,
                                 object_schema, raise_for_status)

API = "https://api.airtable.com/v0"
_ID_RE = re.compile(r"^(app|tbl|rec)[A-Za-z0-9]{14}$")
BASE_ID = {"type": "string", "description": "Base id starting with 'app' (from list_bases)."}
TABLE = {"type": "string", "description": "Table id (tbl...) or exact table name."}


def _base(value: str) -> str:
    if not re.match(r"^app[A-Za-z0-9]{14}$", value or ""):
        raise ToolError("base_id must look like appXXXXXXXXXXXXXX (use list_bases).")
    return value


def _table(value: str) -> str:
    if not value or not value.strip():
        raise ToolError("table is required")
    return quote(value.strip(), safe="")


async def validate(http, values: dict[str, str], settings: Settings):
    data = await checked_get(http, f"{API}/meta/bases", "Airtable",
                             headers={"Authorization": f"Bearer {values['api_key']}"})
    return TokenSet(access_token=values["api_key"]), f"{len(data.get('bases', []))} bases"


async def list_bases(ctx: ToolContext) -> dict:
    resp = await ctx.http.get(f"{API}/meta/bases", headers=ctx.bearer)
    raise_for_status(resp, "Listing bases")
    return {"bases": [{"id": b.get("id"), "name": b.get("name"), "permission": b.get("permissionLevel")}
                      for b in resp.json().get("bases", [])]}


async def list_tables(ctx: ToolContext, base_id: str) -> dict:
    resp = await ctx.http.get(f"{API}/meta/bases/{_base(base_id)}/tables", headers=ctx.bearer)
    raise_for_status(resp, "Listing tables")
    return {"tables": [
        {"id": t.get("id"), "name": t.get("name"), "primary_field": t.get("primaryFieldId"),
         "fields": [{"name": f.get("name"), "type": f.get("type")} for f in t.get("fields", [])][:40],
         "views": [v.get("name") for v in t.get("views", [])][:10]}
        for t in resp.json().get("tables", [])]}


async def list_records(ctx: ToolContext, base_id: str, table: str, max_records: int,
                       filter_formula: str | None) -> dict:
    params: dict = {"maxRecords": max(1, min(max_records, 100))}
    if filter_formula:
        params["filterByFormula"] = filter_formula
    resp = await ctx.http.get(f"{API}/{_base(base_id)}/{_table(table)}", headers=ctx.bearer, params=params)
    raise_for_status(resp, "Listing records")
    d = resp.json()
    return {"records": [{"id": r.get("id"), "fields": r.get("fields", {}), "created": r.get("createdTime")}
                        for r in d.get("records", [])], "more_available": bool(d.get("offset"))}


async def create_record(ctx: ToolContext, base_id: str, table: str, fields_json: str) -> dict:
    try:
        fields = json.loads(fields_json)
    except ValueError as exc:
        raise ToolError("fields_json must be a JSON object such as {\"Name\": \"Ada\"}") from exc
    if not isinstance(fields, dict) or not fields:
        raise ToolError("fields_json must be a non-empty JSON object")
    resp = await ctx.http.post(f"{API}/{_base(base_id)}/{_table(table)}", headers=ctx.bearer,
                               json={"records": [{"fields": fields}]})
    raise_for_status(resp, "Creating the record")
    rec = (resp.json().get("records") or [{}])[0]
    return {"id": rec.get("id"), "fields": rec.get("fields", {})}


MANIFEST = api_key_manifest(
    id="airtable", name="Airtable",
    description="Find your bases and tables, read records and add records.",
    credential_fields=[CredentialField(
        key="api_key", label="Personal access token", secret=True, pattern=r"pat[A-Za-z0-9]{14}\.[a-f0-9]{64}",
        pattern_hint="Starts with 'pat', then a dot and a long hex string.",
        help_text="Airtable > Builder hub > Personal access tokens. Scopes: schema.bases:read, "
                  "data.records:read, data.records:write; grant access to the bases you want.")],
    validate=validate, console_url="https://airtable.com/create/tokens",
    setup_guide=["Open Builder hub > Personal access tokens > Create token.",
                 "Add scopes schema.bases:read, data.records:read and data.records:write.",
                 "Under Access, choose the bases this app may use, create the token and paste it here."],
    health_tool="airtable__list_bases",
    tools=[
        ToolDef(name="airtable__list_bases", description="List the Airtable bases the token can access (names and ids). "
                                                  "Use first; never ask the user for a base id.",
                parameters=object_schema({}), risk="read", handler=list_bases),
        ToolDef(name="airtable__list_tables",
                description="List the tables of a base with their field names and types. Use after list_bases to "
                            "find the exact table name before reading or adding records.",
                parameters=object_schema({"base_id": BASE_ID}), risk="read", handler=list_tables),
        ToolDef(name="airtable__list_records",
                description="List records in a table (up to 100). Optionally filter with an Airtable formula.",
                parameters=object_schema({
                    "base_id": BASE_ID, "table": TABLE,
                    "max_records": {"type": "integer", "description": "1 to 100."},
                    "filter_formula": {"type": ["string", "null"], "description": "Airtable formula, e.g. {Status}='Open', or null."}}),
                risk="read", handler=list_records),
        ToolDef(name="airtable__create_record",
                description="Create one record in a table. Field names must match the table's columns.",
                parameters=object_schema({
                    "base_id": BASE_ID, "table": TABLE,
                    "fields_json": {"type": "string", "description": "JSON object of field name to value."}}),
                risk="write", handler=create_record),
    ],
)
