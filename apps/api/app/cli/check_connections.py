"""Run the connector health checks from the terminal: `scripts/check-connections [--user USER_ID] [--provider ID]`.

Same checks as the "Test connection" button. No LLM and no paid API is called. Prints provider, account,
result and the plain-words message; never tokens or secrets. Exit code 1 if any check fails.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

import httpx

from app.core.config import get_settings
from app.core.secrets import build_secret_store
from app.db.client import Database, SupabaseRestDatabase
from app.health import run_health_check


async def run(db: Database, store, http: httpx.AsyncClient, settings, user_id: str | None,
              provider: str | None) -> list[dict]:
    filters: dict = {}
    if user_id:
        filters["user_id"] = user_id
    if provider:
        filters["provider"] = provider
    rows = [r for r in await db.select("connections", filters or None, order="created_at.asc")
            if r.get("status") != "revoked"]
    results = []
    for conn in rows:
        res = await run_health_check(db, store, http, settings, conn)
        results.append({**res, "account": conn.get("account_label")})
    return results


def format_table(results: list[dict]) -> str:
    if not results:
        return "No connected accounts found."
    lines = [f"{'RESULT':<6}  {'CONNECTOR':<16} {'ACCOUNT':<30} MESSAGE"]
    for r in results:
        lines.append(f"{'PASS' if r['ok'] else 'FAIL':<6}  {r['provider']:<16} {str(r['account'] or '-')[:30]:<30} {r['message']}")
    failed = sum(1 for r in results if not r["ok"])
    lines.append(f"\n{len(results) - failed} passed, {failed} failed.")
    return "\n".join(lines)


async def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Health-check connected accounts (no LLM calls).")
    parser.add_argument("--user", help="only this user id (default: every user in this database)")
    parser.add_argument("--provider", help="only this connector id, e.g. google_calendar")
    args = parser.parse_args(argv)
    settings = get_settings()
    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0)) as http:
        db = SupabaseRestDatabase(settings.supabase_url, settings.supabase_service_role_key, http)
        store = build_secret_store(settings.secret_store, db, settings.token_encryption_key)
        results = await run(db, store, http, settings, args.user, args.provider)
    print(format_table(results))
    return 1 if any(not r["ok"] for r in results) else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
