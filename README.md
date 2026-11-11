# Connect — chat-driven app connector

Connect your apps once, then ask in plain language ("add this lead to my sheet and post it in #sales").
See `CLAUDE.md` for the full spec and `docs/decisions.md` for where we deviated and why.

## Layout

```
apps/web   Next.js 16 (App Router, Tailwind, Supabase Auth)
apps/api   FastAPI (OAuth broker, connectors, agent)
supabase/migrations   SQL migrations (RLS on every table)
```

## Local setup

Requirements: Python 3.11+, Node 20+.

1. `cp .env.example .env` (repo root) and fill in Supabase values. Generate keys:
   ```
   python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"   # TOKEN_ENCRYPTION_KEY
   python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"   # OAUTH_STATE_SECRET
   ```
2. Create `apps/web/.env.local` with `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`,
   `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000`.
3. Database: `supabase db reset` (local stack) **or** against a hosted project:
   `cd apps/api && python scripts/apply_migrations.py` (uses `SUPABASE_DB_URL`).
4. API:
   ```
   cd apps/api
   python -m venv .venv && .venv/Scripts/pip install -e ".[dev]"     # bin/pip on macOS/Linux
   uvicorn app.main:app --reload --port 8000
   ```
5. Web: `cd apps/web && npm install && npm run dev` → http://localhost:3000

### Supabase Auth settings
- Authentication → URL Configuration: Site URL `http://localhost:3000`, redirect URL
  `http://localhost:3000/auth/callback`.
- Google sign-in: Authentication → Providers → Google (needs a Google OAuth client whose redirect URI
  is `https://<project-ref>.supabase.co/auth/v1/callback`).

## Tests

```
cd apps/api && pytest -q                       # unit + mocked provider tests
cd apps/api && RUN_DB_TESTS=1 pytest -q tests/test_rls_live.py   # RLS against the real DB
cd apps/web && npm test && npm run typecheck
```
