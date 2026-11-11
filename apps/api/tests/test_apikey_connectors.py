"""Airtable, Trello, Linear, Asana, Stripe: credential flow, tool happy/error paths (all HTTP mocked)."""

import json

import httpx
import pytest
import respx

from app.connectors.base import TokenSet, ToolContext, ToolError
from app.connectors.registry import all_manifests, all_tools
from tests.conftest import auth

AT = "pat" + "A" * 14 + "." + "a" * 64
TRELLO_KEY, TRELLO_TOKEN = "a" * 32, "T" * 40
ID24 = "5" * 24
LIN = "lin_api_" + "x" * 30
STRIPE = "rk_test_" + "A" * 20


@pytest.fixture
async def http():
    async with httpx.AsyncClient() as h:
        yield h


def make_ctx(http, settings, token="tok", **extra):
    return ToolContext(http=http, token=TokenSet(access_token=token, extra=extra), settings=settings)


def tool(name):
    return all_tools()[name][1]


# ------------------------------------------------------------------ manifests
def test_connectors_are_api_key_with_ui_credentials_and_no_env():
    for cid in ("airtable", "trello", "linear", "asana", "stripe"):
        m = all_manifests()[cid]
        assert m.auth_type == "api_key" and m.credential_fields and m.validate_credentials
        assert any(f.secret for f in m.credential_fields)
        assert m.scopes == []     # no OAuth scopes: the token's permissions are not introspectable


def test_stripe_is_read_only_and_no_other_connector_deletes():
    assert all(t.risk == "read" for t in all_manifests()["stripe"].tools)
    for cid in ("airtable", "trello", "linear", "asana"):
        assert {t.risk for t in all_manifests()[cid].tools} <= {"read", "write"}


# ------------------------------------------------------------------ Set up -> Save -> Connect (real routes)
@respx.mock
def test_linear_save_and_connect_flow(client):
    r = client.post("/api/provider-apps/linear", json={"values": {"api_key": LIN}}, headers=auth())
    assert r.status_code < 300 and LIN not in r.text
    route = respx.post("https://api.linear.app/graphql").respond(
        json={"data": {"viewer": {"name": "A"}, "organization": {"name": "Acme"}}})
    s = client.post("/api/connections/linear/start", headers=auth())
    assert s.status_code == 200 and s.json()["connected"] is True
    assert route.calls[0].request.headers["authorization"] == LIN        # no Bearer prefix for Linear
    assert LIN not in s.text


@respx.mock
def test_bad_credentials_are_rejected_at_connect(client):
    client.post("/api/provider-apps/linear", json={"values": {"api_key": LIN}}, headers=auth())
    respx.post("https://api.linear.app/graphql").respond(401, json={})
    assert client.post("/api/connections/linear/start", headers=auth()).status_code == 400


@respx.mock
def test_stripe_publishable_key_refused(client):
    r = client.post("/api/provider-apps/stripe", json={"values": {"api_key": "pk_test_" + "A" * 20}}, headers=auth())
    assert r.status_code >= 400          # format check: only rk_/sk_ accepted


# ------------------------------------------------------------------ Airtable
@respx.mock
async def test_airtable_happy(http, settings):
    ctx = make_ctx(http, settings, AT)
    respx.get("https://api.airtable.com/v0/meta/bases").respond(json={"bases": [{"id": "appAAAAAAAAAAAAAA", "name": "CRM"}]})
    assert (await tool("airtable__list_bases").handler(ctx))["bases"][0]["name"] == "CRM"
    r = respx.get(url__regex=r"https://api.airtable.com/v0/appAAAAAAAAAAAAAA/Leads.*").respond(
        json={"records": [{"id": "rec1", "fields": {"Name": "Ada"}}]})
    out = await tool("airtable__list_records").handler(ctx, base_id="appAAAAAAAAAAAAAA", table="Leads", max_records=5, filter_formula=None)
    assert out["records"][0]["fields"]["Name"] == "Ada" and r.calls[0].request.headers["authorization"] == f"Bearer {AT}"
    c = respx.post("https://api.airtable.com/v0/appAAAAAAAAAAAAAA/Leads").respond(json={"records": [{"id": "rec2", "fields": {"Name": "Bo"}}]})
    await tool("airtable__create_record").handler(ctx, base_id="appAAAAAAAAAAAAAA", table="Leads", fields_json='{"Name": "Bo"}')
    assert json.loads(c.calls[0].request.content) == {"records": [{"fields": {"Name": "Bo"}}]}


@respx.mock
async def test_airtable_errors(http, settings):
    ctx = make_ctx(http, settings, AT)
    with pytest.raises(ToolError):
        await tool("airtable__list_records").handler(ctx, base_id="../x", table="t", max_records=1, filter_formula=None)
    with pytest.raises(ToolError):
        await tool("airtable__create_record").handler(ctx, base_id="appAAAAAAAAAAAAAA", table="t", fields_json="nope")
    respx.post("https://api.airtable.com/v0/appAAAAAAAAAAAAAA/t").respond(422, json={"error": {"type": "INVALID", "message": "Unknown field"}})
    with pytest.raises(ToolError, match="Unknown field"):
        await tool("airtable__create_record").handler(ctx, base_id="appAAAAAAAAAAAAAA", table="t", fields_json='{"x":1}')


# ------------------------------------------------------------------ Trello
@respx.mock
async def test_trello_happy(http, settings):
    ctx = make_ctx(http, settings, TRELLO_TOKEN, api_key=TRELLO_KEY)
    b = respx.get("https://api.trello.com/1/members/me/boards").respond(json=[{"id": ID24, "name": "Roadmap", "url": "u"}])
    assert (await tool("trello__list_boards").handler(ctx))["boards"][0]["name"] == "Roadmap"
    q = b.calls[0].request.url.params
    assert q["key"] == TRELLO_KEY and q["token"] == TRELLO_TOKEN
    respx.get(f"https://api.trello.com/1/boards/{ID24}/lists").respond(json=[{"id": ID24, "name": "To do"}])
    assert (await tool("trello__list_lists").handler(ctx, board_id=ID24))["lists"][0]["name"] == "To do"
    respx.get(f"https://api.trello.com/1/lists/{ID24}/cards").respond(json=[{"id": ID24, "name": "c"}])
    assert len((await tool("trello__list_cards").handler(ctx, list_id=ID24))["cards"]) == 1
    respx.post("https://api.trello.com/1/cards").respond(json={"id": ID24, "name": "New", "url": "u"})
    assert (await tool("trello__create_card").handler(ctx, list_id=ID24, name="New", description=None))["name"] == "New"


@respx.mock
async def test_trello_errors(http, settings):
    ctx = make_ctx(http, settings, TRELLO_TOKEN, api_key=TRELLO_KEY)
    with pytest.raises(ToolError):
        await tool("trello__list_lists").handler(ctx, board_id="not-an-id")
    respx.post("https://api.trello.com/1/cards").respond(429)
    with pytest.raises(ToolError, match="rate limited"):
        await tool("trello__create_card").handler(ctx, list_id=ID24, name="x", description=None)


# ------------------------------------------------------------------ Linear
@respx.mock
async def test_linear_happy(http, settings):
    ctx = make_ctx(http, settings, LIN)
    respx.post("https://api.linear.app/graphql").mock(side_effect=[
        httpx.Response(200, json={"data": {"teams": {"nodes": [{"id": "t1", "key": "ENG", "name": "Eng"}]}}}),
        httpx.Response(200, json={"data": {"issues": {"nodes": [{"id": "i1", "identifier": "ENG-1", "title": "Bug", "url": "u", "state": {"name": "Todo"}, "assignee": None}]}}}),
        httpx.Response(200, json={"data": {"issueCreate": {"success": True, "issue": {"id": "i2", "identifier": "ENG-2", "title": "New", "url": "u"}}}}),
    ])
    assert (await tool("linear__list_teams").handler(ctx))["teams"][0]["key"] == "ENG"
    assert (await tool("linear__list_issues").handler(ctx, team_id="t1", first=5))["issues"][0]["state"] == "Todo"
    assert (await tool("linear__create_issue").handler(ctx, team_id="t1", title="New", description=None))["identifier"] == "ENG-2"


@respx.mock
async def test_linear_errors(http, settings):
    ctx = make_ctx(http, settings, LIN)
    respx.post("https://api.linear.app/graphql").respond(200, json={"errors": [{"message": "Rate limit exceeded", "extensions": {"code": "RATELIMITED"}}]})
    with pytest.raises(ToolError, match="rate limited"):
        await tool("linear__list_teams").handler(ctx)
    respx.post("https://api.linear.app/graphql").respond(400, json={"errors": [{"message": "Argument Validation Error"}]})
    with pytest.raises(ToolError, match="Argument Validation"):
        await tool("linear__create_issue").handler(ctx, team_id="t1", title="x", description=None)


# ------------------------------------------------------------------ Asana
@respx.mock
async def test_asana_happy(http, settings):
    ctx = make_ctx(http, settings, "pat")
    respx.get("https://api.asana.com/api/1.0/workspaces".replace("api.asana", "app.asana")).respond(json={"data": [{"gid": "1", "name": "W"}]})
    assert (await tool("asana__list_workspaces").handler(ctx))["workspaces"][0]["gid"] == "1"
    respx.get("https://app.asana.com/api/1.0/projects").respond(json={"data": [{"gid": "2", "name": "P"}]})
    assert (await tool("asana__list_projects").handler(ctx, workspace_gid="1"))["projects"][0]["gid"] == "2"
    respx.get("https://app.asana.com/api/1.0/tasks").respond(json={"data": [{"gid": "3", "name": "T", "completed": False, "assignee": None}]})
    assert (await tool("asana__list_tasks").handler(ctx, project_gid="2"))["tasks"][0]["name"] == "T"
    c = respx.post("https://app.asana.com/api/1.0/tasks").respond(json={"data": {"gid": "4", "name": "N", "permalink_url": "u"}})
    await tool("asana__create_task").handler(ctx, project_gid="2", name="N", notes=None, due_on=None)
    assert json.loads(c.calls[0].request.content) == {"data": {"name": "N", "projects": ["2"]}}


@respx.mock
async def test_asana_errors(http, settings):
    ctx = make_ctx(http, settings, "pat")
    with pytest.raises(ToolError):
        await tool("asana__list_tasks").handler(ctx, project_gid="abc")
    respx.post("https://app.asana.com/api/1.0/tasks").respond(403, json={"errors": [{"message": "Not Authorized"}]})
    with pytest.raises(ToolError, match="Not Authorized"):
        await tool("asana__create_task").handler(ctx, project_gid="2", name="N", notes=None, due_on=None)


# ------------------------------------------------------------------ Stripe
@respx.mock
async def test_stripe_happy_and_only_get(http, settings):
    ctx = make_ctx(http, settings, STRIPE)
    respx.get("https://api.stripe.com/v1/balance").respond(json={"livemode": False, "available": [{"currency": "usd", "amount": 1250}], "pending": []})
    assert (await tool("stripe__get_balance").handler(ctx))["available"][0]["amount_minor_units"] == 1250
    respx.get("https://api.stripe.com/v1/customers").respond(json={"data": [{"id": "cus_1", "email": "a@x.com"}], "has_more": False})
    assert (await tool("stripe__list_customers").handler(ctx, limit=5, email=None))["customers"][0]["id"] == "cus_1"
    inv = respx.get("https://api.stripe.com/v1/invoices").respond(json={"data": [{"id": "in_1", "status": "paid", "amount_due": 500}], "has_more": True})
    out = await tool("stripe__list_invoices").handler(ctx, limit=5, status="paid", customer_id="cus_1")
    assert out["more_available"] and inv.calls[0].request.url.params["status"] == "paid"
    assert inv.calls[0].request.headers["authorization"] == f"Bearer {STRIPE}"
    assert all(c.request.method == "GET" for c in respx.calls)


@respx.mock
async def test_stripe_errors(http, settings):
    ctx = make_ctx(http, settings, STRIPE)
    with pytest.raises(ToolError):
        await tool("stripe__list_invoices").handler(ctx, limit=5, status="bogus", customer_id=None)
    respx.get("https://api.stripe.com/v1/balance").respond(403, json={"error": {"message": "key lacks permission"}})
    with pytest.raises(ToolError, match="key lacks permission"):
        await tool("stripe__get_balance").handler(ctx)


@respx.mock
def test_trello_two_field_credentials_connect(client):
    r = client.post("/api/provider-apps/trello", json={"values": {"api_key": TRELLO_KEY, "token": TRELLO_TOKEN}}, headers=auth())
    assert r.status_code < 300 and TRELLO_TOKEN not in r.text
    respx.get("https://api.trello.com/1/members/me").respond(json={"username": "ada"})
    s = client.post("/api/connections/trello/start", headers=auth())
    assert s.status_code == 200 and s.json()["connected"] is True
    assert TRELLO_TOKEN not in s.text
