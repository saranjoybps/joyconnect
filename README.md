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

## Provider apps (Phase 1)

Every OAuth provider uses the redirect URI **`{API_BASE_URL}/api/oauth/callback/{provider_id}`**,
locally `http://localhost:8000/api/oauth/callback/<id>`. Put the client id/secret in the root `.env`.

### Google (Sheets, Docs, Calendar) — one OAuth client for all three
1. Google Cloud Console → create a project → APIs & Services → **Enable** Google Sheets API,
   Google Docs API, Google Calendar API.
2. OAuth consent screen (Google Auth Platform): External, add yourself as a **test user**.
   Data access → add scopes `openid`, `.../auth/userinfo.email`, `.../auth/spreadsheets`,
   `.../auth/documents`, `.../auth/calendar.events` (sensitive, not restricted; verification is only
   needed to go beyond test users).
3. Clients → Create OAuth client → **Web application**. Authorized redirect URIs:
   - `http://localhost:8000/api/oauth/callback/google_sheets`
   - `http://localhost:8000/api/oauth/callback/google_docs`
   - `http://localhost:8000/api/oauth/callback/google_calendar`
4. `.env`: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`.

### Slack
1. https://api.slack.com/apps → Create New App → From scratch.
2. OAuth & Permissions → Redirect URLs: `http://localhost:8000/api/oauth/callback/slack`
   (Slack requires HTTPS for distributed apps; for local dev use an HTTPS tunnel such as
   `ngrok http 8000` and set `API_BASE_URL` to the tunnel URL).
3. Bot Token Scopes: `chat:write`, `channels:read`, `users:read`. Leave token rotation off.
4. `.env`: `SLACK_CLIENT_ID`, `SLACK_CLIENT_SECRET` (Basic Information → App Credentials).

### Notion
1. https://www.notion.so/profile/integrations → New integration → type **Public**.
2. Redirect URI: `http://localhost:8000/api/oauth/callback/notion`. Capabilities: Read content,
   Insert content, Update content (no user info needed).
3. `.env`: `NOTION_CLIENT_ID`, `NOTION_CLIENT_SECRET`. `NOTION_VERSION` defaults to `2026-03-11`.

### GitHub (GitHub App, not an OAuth App)
1. GitHub → Settings → Developer settings → GitHub Apps → New GitHub App.
2. Callback URL: `http://localhost:8000/api/oauth/callback/github`. Tick **Expire user authorization
   tokens**. Leave "Request user authorization during installation" off. Webhook: inactive.
3. Repository permissions: Issues **Read & write**, Pull requests **Read**, Contents **Read**,
   Metadata **Read**.
4. Generate a client secret. `.env`: `GITHUB_APP_CLIENT_ID` (the *Client ID*, not the App ID),
   `GITHUB_APP_CLIENT_SECRET`, `GITHUB_APP_SLUG` (from `github.com/apps/<slug>`).
5. Users connect, then install the app on repos via the "Choose repositories" link on the card.

## Adding a connector (under 10 steps)

1. Create `apps/api/app/connectors/<id>.py`.
2. Write each tool as `async def handler(ctx: ToolContext, **args)`; use `ctx.http` and `ctx.bearer`,
   raise `ToolError` for user-facing failures.
3. Describe each tool with `ToolDef(name="<id>__<action>", description, parameters=object_schema({...}), risk=...)`.
   Optional args use a `["type", "null"]` type (OpenAI strict mode).
4. Export `MANIFEST = ConnectorManifest(...)` with auth URLs, minimum scopes, and
   `client_id_setting` / `client_secret_setting`.
5. If the provider deviates from plain OAuth2, set knobs (`token_auth_style`, `token_body_format`,
   `scope_separator`, `pkce`, `reauth_errors`) or hooks (`parse_token_response`, `account_label`, `revoke`).
6. Add the two settings to `app/core/config.py` and `.env.example`.
7. Add `apps/web/public/icons/<id>.svg`.
8. Add respx tests for the callback and each tool in `apps/api/tests/`.
9. Run `pytest -q`. The registry discovers the module automatically; no router or UI changes.
