"""Stripe, read-only (docs.stripe.com/api).

Auth: `Authorization: Bearer <secret or restricted key>`. Use a RESTRICTED key (rk_...) with read access to
Balance, Customers and Invoices only. Publishable keys (pk_) are rejected. Only GET requests are made:
no tool can move money or change data. Rate limit: 429 (Stripe's default is 100 read ops/s in live mode).
"""

from __future__ import annotations

import re

from app.connectors._apikey import api_key_manifest, checked_get
from app.connectors.base import (CredentialField, Settings, TokenSet, ToolContext, ToolDef, ToolError,
                                 object_schema, raise_for_status)

API = "https://api.stripe.com/v1"
_ID_RE = re.compile(r"^cus_[A-Za-z0-9]+$")
INVOICE_STATUSES = ["draft", "open", "paid", "uncollectible", "void"]


def _money(items: list[dict]) -> list[dict]:
    return [{"currency": i.get("currency"), "amount_minor_units": i.get("amount")} for i in items]


async def validate(http, values: dict[str, str], settings: Settings):
    key = values["api_key"]
    if key.startswith("pk_"):
        raise ToolError("That is a publishable key. Use a restricted (rk_) or secret (sk_) key.")
    data = await checked_get(http, f"{API}/balance", "Stripe", headers={"Authorization": f"Bearer {key}"})
    return TokenSet(access_token=key), "live" if data.get("livemode") else "test mode"


async def get_balance(ctx: ToolContext) -> dict:
    resp = await ctx.http.get(f"{API}/balance", headers=ctx.bearer)
    raise_for_status(resp, "Reading the balance")
    d = resp.json()
    return {"available": _money(d.get("available", [])), "pending": _money(d.get("pending", [])),
            "livemode": d.get("livemode"), "note": "Amounts are in the smallest currency unit (cents)."}


async def list_customers(ctx: ToolContext, limit: int, email: str | None) -> dict:
    params: dict = {"limit": max(1, min(limit, 100))}
    if email:
        params["email"] = email
    resp = await ctx.http.get(f"{API}/customers", headers=ctx.bearer, params=params)
    raise_for_status(resp, "Listing customers")
    d = resp.json()
    return {"customers": [{"id": c["id"], "name": c.get("name"), "email": c.get("email"), "created": c.get("created")}
                          for c in d.get("data", [])], "more_available": bool(d.get("has_more"))}


async def list_invoices(ctx: ToolContext, limit: int, status: str | None, customer_id: str | None) -> dict:
    params: dict = {"limit": max(1, min(limit, 100))}
    if status:
        if status not in INVOICE_STATUSES:
            raise ToolError(f"status must be one of {', '.join(INVOICE_STATUSES)}")
        params["status"] = status
    if customer_id:
        if not _ID_RE.match(customer_id):
            raise ToolError("customer_id must look like cus_XXXX")
        params["customer"] = customer_id
    resp = await ctx.http.get(f"{API}/invoices", headers=ctx.bearer, params=params)
    raise_for_status(resp, "Listing invoices")
    d = resp.json()
    return {"invoices": [{"id": i["id"], "number": i.get("number"), "status": i.get("status"),
                          "customer": i.get("customer"), "currency": i.get("currency"),
                          "amount_due_minor_units": i.get("amount_due"), "amount_paid_minor_units": i.get("amount_paid"),
                          "created": i.get("created")} for i in d.get("data", [])],
            "more_available": bool(d.get("has_more"))}


MANIFEST = api_key_manifest(
    id="stripe", name="Stripe",
    description="Read-only: account balance, customers and invoices. Cannot change anything.",
    credential_fields=[CredentialField(
        key="api_key", label="Restricted API key", secret=True, pattern=r"(rk|sk)_(test|live)_[A-Za-z0-9]{10,}",
        pattern_hint="Starts with rk_live_, rk_test_, sk_live_ or sk_test_.",
        help_text="Stripe Dashboard > Developers > API keys > Create restricted key, with Read access to "
                  "Balance, Customers and Invoices.")],
    validate=validate, console_url="https://dashboard.stripe.com/apikeys",
    setup_guide=["Open Dashboard > Developers > API keys > Create restricted key.",
                 "Set only Balance, Customers and Invoices to Read; leave everything else None.",
                 "Prefer test mode while trying this out. Paste the key here."],
    health_tool="stripe__get_balance",
    tools=[
        ToolDef(name="stripe__get_balance", description="Get the Stripe account balance (available and pending).",
                parameters=object_schema({}), risk="read", handler=get_balance),
        ToolDef(name="stripe__list_customers", description="List Stripe customers, newest first.",
                parameters=object_schema({"limit": {"type": "integer", "description": "1 to 100."},
                                          "email": {"type": ["string", "null"], "description": "Exact email filter or null."}}),
                risk="read", handler=list_customers),
        ToolDef(name="stripe__list_invoices", description="List Stripe invoices, newest first.",
                parameters=object_schema({"limit": {"type": "integer", "description": "1 to 100."},
                                          "status": {"type": ["string", "null"], "enum": INVOICE_STATUSES + [None]},
                                          "customer_id": {"type": ["string", "null"], "description": "cus_... or null."}}),
                risk="read", handler=list_invoices),
    ],
)
