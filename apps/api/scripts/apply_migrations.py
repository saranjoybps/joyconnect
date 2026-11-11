"""Apply supabase/migrations/*.sql to SUPABASE_DB_URL, once each, in order.

Alternative to `supabase db push` when the Supabase CLI is not installed.
Usage: python scripts/apply_migrations.py [--rls-check]
"""

import sys
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.config import REPO_ROOT  # noqa: E402

MIGRATIONS = REPO_ROOT / "supabase" / "migrations"


def load_db_url() -> str:
    import os

    if os.environ.get("SUPABASE_DB_URL"):
        return os.environ["SUPABASE_DB_URL"]
    for line in (REPO_ROOT / ".env").read_text().splitlines():
        if line.startswith("SUPABASE_DB_URL="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("SUPABASE_DB_URL is not set")


def main() -> None:
    with psycopg.connect(load_db_url(), autocommit=False, connect_timeout=15) as conn:
        conn.execute("create table if not exists public._app_migrations "
                     "(name text primary key, applied_at timestamptz not null default now())")
        conn.execute("alter table public._app_migrations enable row level security")
        conn.execute("revoke all on public._app_migrations from anon, authenticated")
        conn.commit()
        done = {r[0] for r in conn.execute("select name from public._app_migrations")}
        for path in sorted(MIGRATIONS.glob("*.sql")):
            if path.name in done:
                print(f"skip   {path.name}")
                continue
            with conn.transaction():
                conn.execute(path.read_text(encoding="utf-8"))
                conn.execute("insert into public._app_migrations (name) values (%s)", (path.name,))
            print(f"apply  {path.name}")


if __name__ == "__main__":
    main()
