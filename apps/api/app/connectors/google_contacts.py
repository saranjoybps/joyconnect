"""Google Contacts via the People API (docs: developers.google.com/people).

Scope: contacts (read and write; covers connections.list, searchContacts and createContact).
NOT used: contacts.other.readonly, directory.readonly, user.* (personal data scopes).
searchContacts: the docs advise a warm-up request with an empty query so the cache is populated.
"""

from __future__ import annotations

from app.connectors._google import google_manifest
from app.connectors.base import ToolContext, ToolDef, ToolError, object_schema, raise_for_status

API = "https://people.googleapis.com/v1"
SCOPE = "https://www.googleapis.com/auth/contacts"
READ_MASK = "names,emailAddresses,phoneNumbers"


def _person(p: dict) -> dict:
    return {"resource_name": p.get("resourceName"),
            "name": (p.get("names") or [{}])[0].get("displayName"),
            "emails": [e.get("value") for e in p.get("emailAddresses", [])],
            "phones": [e.get("value") for e in p.get("phoneNumbers", [])]}


async def list_contacts(ctx: ToolContext, page_size: int) -> dict:
    resp = await ctx.http.get(f"{API}/people/me/connections", headers=ctx.bearer, params={
        "personFields": READ_MASK, "pageSize": max(1, min(page_size, 200)), "sortOrder": "LAST_NAME_ASCENDING"})
    raise_for_status(resp, "Listing contacts")
    d = resp.json()
    return {"contacts": [_person(p) for p in d.get("connections", [])], "more_available": bool(d.get("nextPageToken"))}


async def search_contacts(ctx: ToolContext, query: str) -> dict:
    if not query.strip():
        raise ToolError("query must not be empty")
    await ctx.http.get(f"{API}/people:searchContacts", headers=ctx.bearer, params={"query": "", "readMask": READ_MASK})
    resp = await ctx.http.get(f"{API}/people:searchContacts", headers=ctx.bearer,
                              params={"query": query, "readMask": READ_MASK, "pageSize": 10})
    raise_for_status(resp, "Searching contacts")
    return {"contacts": [_person(r.get("person", {})) for r in resp.json().get("results", [])]}


async def create_contact(ctx: ToolContext, given_name: str, family_name: str | None, email: str | None,
                         phone: str | None) -> dict:
    if not given_name.strip():
        raise ToolError("given_name must not be empty")
    body: dict = {"names": [{"givenName": given_name, **({"familyName": family_name} if family_name else {})}]}
    if email:
        body["emailAddresses"] = [{"value": email}]
    if phone:
        body["phoneNumbers"] = [{"value": phone}]
    resp = await ctx.http.post(f"{API}/people:createContact", json=body, headers=ctx.bearer,
                               params={"personFields": READ_MASK})
    raise_for_status(resp, "Creating the contact")
    return _person(resp.json())


MANIFEST = google_manifest(
    id="google_contacts",
    name="Google Contacts",
    description="List, search and create contacts.",
    scopes=[SCOPE],
    api_to_enable="People API",
    tools=[
        ToolDef(name="google_contacts__list_contacts", description="List the user's contacts (name, emails, phones).",
                parameters=object_schema({"page_size": {"type": "integer", "description": "1 to 200."}}),
                risk="read", handler=list_contacts),
        ToolDef(name="google_contacts__search_contacts",
                description="Search contacts by name, email or phone prefix.",
                parameters=object_schema({"query": {"type": "string"}}), risk="read", handler=search_contacts),
        ToolDef(name="google_contacts__create_contact", description="Create a new contact.",
                parameters=object_schema({
                    "given_name": {"type": "string"}, "family_name": {"type": ["string", "null"]},
                    "email": {"type": ["string", "null"]}, "phone": {"type": ["string", "null"]}}),
                risk="write", handler=create_contact),
    ],
)
