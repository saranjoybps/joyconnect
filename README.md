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

1. `cp .env.example .env` (repo root) and fill in Supabase and OpenAI values (no provider credentials needed). Generate keys:
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

## Chat agent (Phase 2)

- Set `OPENAI_API_KEY` (and optionally `OPENAI_MODEL`, default `gpt-4o-mini`) in the root `.env`.
- `POST /api/chat` streams Server-Sent Events: `token`, `tool_call`, `approval_required`, `tool_result`,
  `error`, `done`. `POST /api/approvals/{id}/decision {"approve": bool}` resumes with the same events.
- Policy: read tools run immediately; write tools ask unless the connection has *Auto-approve writes*;
  destructive tools always ask. Every call is audited in `tool_runs` (arguments redacted).

## Provider apps: each user brings their own

Provider credentials are **not** server config. Each user creates an app in the provider's developer
console and enters its credentials on **Connections → (card) → Set up**. The form shows the exact
redirect URI to copy, the scopes, and a short guide. Flow: **Set up → Save → Test → Connect**; later
**Edit setup** or **Remove credentials** (removing warns, then disconnects the connections made with it).

- Secrets (client secret, API key, connection string) are encrypted with the SecretStore and never sent
  back to the browser; the client ID is shown masked.
- **Test** checks the format, then redeems a dummy code at the provider's token endpoint: an
  `invalid_client`-type error means the ID/secret are wrong, an invalid-code error means they're right.
- Resolution order: the user's app → optional `PLATFORM_<APP>_<FIELD>` env defaults (e.g.
  `PLATFORM_GOOGLE_CLIENT_ID`) → "set up required".
- A connection keeps using the app it was made with for refresh and revoke.

Redirect URI pattern: **`{API_BASE_URL}/api/oauth/callback/{connector_id}`**
(locally `http://localhost:8000/api/oauth/callback/<id>`).

### Google (one app for Sheets, Docs and Calendar)
1. https://console.cloud.google.com → create a project → APIs & Services → enable **Google Sheets API**,
   **Google Docs API**, **Google Calendar API**.
2. Google Auth Platform → Audience: External; add yourself under **Test users**.
3. Data access → add scopes `openid`, `.../auth/userinfo.email`, `.../auth/spreadsheets`,
   `.../auth/documents`, `.../auth/calendar.events` (sensitive, not restricted; verification only needed
   beyond test users).
4. Clients → Create client → **Web application** → Authorized redirect URIs (all three):
   `http://localhost:8000/api/oauth/callback/google_sheets`, `.../google_docs`, `.../google_calendar`.
5. Paste the client ID (`…apps.googleusercontent.com`) and secret (`GOCSPX-…`) into any Google card's Set up.

### Slack
1. https://api.slack.com/apps → Create New App → From scratch → pick your workspace.
2. OAuth & Permissions → Redirect URLs: `{API_BASE_URL}/api/oauth/callback/slack`. Slack requires
   HTTPS, so for local use run a tunnel (`ngrok http 8000`) and set `API_BASE_URL` to the tunnel URL.
3. Bot Token Scopes: `chat:write`, `channels:read`, `users:read`. Leave token rotation off.
4. Basic Information → App Credentials → paste Client ID and Client Secret into Slack's Set up.

### Notion
1. https://www.notion.so/profile/integrations → New integration → type **Public**.
2. Redirect URI: `http://localhost:8000/api/oauth/callback/notion`. Capabilities: Read, Insert, Update content.
3. Paste the OAuth client ID and secret into Notion's Set up. When connecting, pick the pages to share.

### GitHub (a GitHub App, not an OAuth App)
1. GitHub → Settings → Developer settings → GitHub Apps → New GitHub App.
2. Callback URL: `http://localhost:8000/api/oauth/callback/github`. Tick **Expire user authorization
   tokens**; leave "Request user authorization during installation" off; Webhook inactive.
3. Repository permissions: Issues **Read & write**; Pull requests, Contents, Metadata **Read**.
4. Generate a client secret. In GitHub's Set up paste the **Client ID** (starts with `Iv`, not the App ID),
   the secret, and the app slug (from `github.com/apps/<slug>`).
5. After connecting, use **Choose repositories** on the card to install the app on repos.

### Optional: platform defaults
An operator can provide a shared app for all users by setting `PLATFORM_<APP>_<FIELD>` in the root
`.env` (see `.env.example`). Users who enter their own app always use theirs.

## Adding a connector (under 10 steps)

1. Create `apps/api/app/connectors/<id>.py`.
2. Write each tool as `async def handler(ctx: ToolContext, **args)`; use `ctx.http` and `ctx.bearer`,
   raise `ToolError` for user-facing failures.
3. Describe each tool with `ToolDef(name="<id>__<action>", description, parameters=object_schema({...}), risk=...)`.
   Optional args use a `["type", "null"]` type (OpenAI strict mode).
4. Export `MANIFEST = ConnectorManifest(...)` with auth URLs, minimum scopes, `credential_fields`
   (e.g. `oauth_client_fields(...)`), `console_url` and a short `setup_guide`.
5. If the provider deviates from plain OAuth2, set knobs (`token_auth_style`, `token_body_format`,
   `scope_separator`, `pkce`, `reauth_errors`, `invalid_client_errors`) or hooks (`parse_token_response`,
   `account_label`, `revoke`). Non-OAuth connectors implement `validate_credentials`.
6. No env changes: users enter credentials in the UI (optionally document `PLATFORM_<APP>_<FIELD>`).
7. Add `apps/web/public/icons/<id>.svg`.
8. Add respx tests for the callback and each tool in `apps/api/tests/`.
9. Run `pytest -q`. The registry discovers the module automatically; no router or UI changes.
