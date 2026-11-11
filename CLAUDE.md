# CLAUDE.md — AI Integration Platform (chat-driven app connector)

> Read this whole file before writing code. Build phase by phase. Do not skip ahead.
> Last researched: 2026-11-11. Items marked **VERIFY** must be checked against the provider's live docs before you code against them.

## 1. What we are building

A chat-first integration platform. A user connects their apps in one click (like n8n, Zapier, Activepieces), then types a request in plain language ("add this lead to my sheet and post it in #sales"). An AI agent runs it across the connected apps.

- The integration layer is the product foundation. Everything else (saved workflows, scheduling, teams) comes later.
- Every app is a **connector** defined by one declarative manifest. Adding an app = add a manifest + tool functions. **Never** add per-app UI or per-app auth code outside the connector module.

## 2. Stack (fixed, do not change)

| Layer | Choice |
| --- | --- |
| Frontend | Next.js (App Router), TypeScript, Tailwind CSS |
| Backend | FastAPI (Python 3.11+), httpx, pydantic v2 |
| Database / Auth | Supabase (Postgres, Auth, RLS) |
| LLM | OpenAI `gpt-4o-mini` via tool calling (model name in env `OPENAI_MODEL`, never hard-coded) |
| Tools protocol | MCP (official `mcp` Python SDK, `FastMCP`), in-process in Phase 1 |
| Tests | pytest + respx (API), Vitest (web) |

## 3. Architecture

```
Browser (Next.js)  <->  FastAPI  <->  Supabase (Postgres + Auth)
                          |  \
                          |   `-> OpenAI gpt-4o-mini (tool calling)
                          `-> Connected apps (Google, Slack, Notion, GitHub, Meta, Google Ads, Postgres)
```

FastAPI contains four parts:
1. **OAuth broker** — start/callback/refresh/revoke for every connector.
2. **Agent runtime** — builds the tool list from the user's connections, runs the OpenAI tool-calling loop.
3. **MCP tool registry** — one tool per connector action, tagged by risk.
4. **Approval gate** — pauses write/destructive tool calls until the user approves.

Hard rules:
- The browser never sees a provider token. All OAuth code exchange happens in FastAPI.
- Only FastAPI uses the Supabase **service role** key. It must never reach the web app or the repo.
- Risk policy is enforced in our code, never delegated to the model or to MCP annotations (they are hints only).

## 4. Repo layout (monorepo)

```
/
├─ CLAUDE.md
├─ README.md                      # setup + provider checklist (you write this)
├─ .env.example                   # every env var, no secrets
├─ apps/
│  ├─ web/                        # Next.js
│  │  ├─ app/(auth)/login
│  │  ├─ app/(app)/chat
│  │  ├─ app/(app)/connections
│  │  ├─ components/ (ChatWindow, ConnectionCard, ApprovalPrompt)
│  │  └─ lib/ (api client, supabase client)
│  └─ api/                        # FastAPI
│     ├─ app/main.py
│     ├─ app/core/ (config.py, security.py, secrets.py, logging.py)
│     ├─ app/db/ (client.py, models.py)
│     ├─ app/oauth/ (router.py, state.py, providers.py, apps.py, tokens.py)
│     ├─ app/connectors/ (base.py, registry.py, google_sheets.py, google_docs.py,
│     │                    google_calendar.py, gmail.py, slack.py, notion.py,
│     │                    github.py, postgres.py, meta_ads.py, google_ads.py)
│     ├─ app/agent/ (runtime.py, policy.py, prompts.py, tools.py)
│     ├─ app/mcp/ (server.py)
│     ├─ app/routers/ (chat.py, connections.py, provider_apps.py, approvals.py, health.py)
│     └─ tests/
└─ supabase/migrations/           # SQL, numbered
```

## 5. Environment variables (`.env.example` must list all)

```
# App
APP_ENV=local
WEB_BASE_URL=http://localhost:3000
API_BASE_URL=http://localhost:8000          # what the browser calls (chat, SSE)
PUBLIC_API_BASE_URL=                        # what providers redirect to; defaults to API_BASE_URL

# Supabase
SUPABASE_URL=
SUPABASE_ANON_KEY=
SUPABASE_SERVICE_ROLE_KEY=        # server only
SUPABASE_JWT_SECRET=              # or use JWKS; verify user JWT in FastAPI

# Secrets storage
SECRET_STORE=aesgcm               # aesgcm | vault
TOKEN_ENCRYPTION_KEY=             # 32 bytes, base64; required for aesgcm
OAUTH_STATE_SECRET=               # HMAC key for signing OAuth state

# OpenAI
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4o-mini
MAX_TOOL_STEPS=8
MAX_TOOLS_PER_REQUEST=24

# API versions (not credentials)
NOTION_VERSION=2026-03-11
META_GRAPH_VERSION=               # VERIFY latest in Meta docs
GOOGLE_ADS_API_VERSION=           # VERIFY latest in Google Ads docs

# OPTIONAL platform-default provider apps: PLATFORM_<APP>_<FIELD>
# Used only when a user has not entered their own app on the Connections page.
# PLATFORM_GOOGLE_CLIENT_ID=      PLATFORM_GOOGLE_CLIENT_SECRET=
# PLATFORM_SLACK_CLIENT_ID=       PLATFORM_SLACK_CLIENT_SECRET=
# PLATFORM_NOTION_CLIENT_ID=      PLATFORM_NOTION_CLIENT_SECRET=
# PLATFORM_GITHUB_CLIENT_ID=      PLATFORM_GITHUB_CLIENT_SECRET=      PLATFORM_GITHUB_APP_SLUG=
# PLATFORM_META_APP_ID=           PLATFORM_META_APP_SECRET=

# Safety
ALLOW_PRIVATE_DB_HOSTS=false      # Postgres connector SSRF guard
```

Only server keys (Supabase, OpenAI, encryption, state secret) are required. **Provider app credentials
(client id/secret, app id/secret, API keys, connection strings) are entered by each user in the UI** and
stored encrypted in `provider_apps`; `PLATFORM_*` env defaults are an optional fallback.

Redirect URIs are **one per provider family**, always built from `PUBLIC_API_BASE_URL` (falling back to
`API_BASE_URL` when unset), never from `API_BASE_URL` directly: `{PUBLIC_API_BASE_URL}/api/oauth/callback/{family}`
with family = `google` (Sheets, Docs, Calendar, later Gmail and Google Ads), `slack`, `notion`, `github`, `meta`.
The Set up form shows exactly that URI ready to copy. `PUBLIC_API_BASE_URL` points at a public HTTPS tunnel
only for providers that reject `http://localhost`; the browser keeps calling `API_BASE_URL` for chat and SSE
(quick tunnels do not carry SSE). `apps/api/.env.local` (git-ignored, written by `scripts/dev-tunnel.*`) overrides `.env`.

## 6. Database (Supabase migrations)

Create `supabase/migrations/0001_init.sql`. RLS **on for every table**. Users read only their own rows. Writes to `connections`, `oauth_states`, `tool_runs`, `approvals` happen through the service role in FastAPI.

```sql
create table public.connections (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  provider text not null,                       -- connector id, e.g. 'google_sheets'
  status text not null default 'active',        -- active | needs_reauth | revoked
  account_label text,                           -- e.g. email or workspace name
  scopes text[] not null default '{}',
  secret_id text not null,                      -- pointer to encrypted token blob
  expires_at timestamptz,
  auto_approve_writes boolean not null default false,
  created_at timestamptz not null default now(),
  unique (user_id, provider, account_label)
);

create table public.oauth_states (
  state text primary key,
  user_id uuid not null,
  provider text not null,
  code_verifier text,
  created_at timestamptz not null default now()
);                                              -- delete after callback or after 10 minutes

create table public.conversations (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  title text,
  created_at timestamptz not null default now()
);

create table public.messages (
  id uuid primary key default gen_random_uuid(),
  conversation_id uuid not null references public.conversations(id) on delete cascade,
  user_id uuid not null,
  role text not null,                           -- user | assistant | tool | system
  content text,
  tool_calls jsonb,
  tool_call_id text,
  created_at timestamptz not null default now()
);

create table public.tool_runs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null,
  conversation_id uuid,
  connection_id uuid,
  tool text not null,
  args_redacted jsonb,
  status text not null,                         -- pending | approved | rejected | ok | error
  result_summary text,
  created_at timestamptz not null default now()
);

create table public.provider_apps (             -- user-entered provider app credentials
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  provider text not null,                       -- credential group, e.g. 'google' (Sheets/Docs/Calendar)
  client_id text,                               -- primary non-secret id; shown to the browser masked only
  secret_id text,                               -- SecretStore pointer to the encrypted secret fields
  extra jsonb not null default '{}',            -- other non-secret fields (e.g. GitHub app slug)
  created_at timestamptz not null default now(),
  unique (user_id, provider)
);
-- connections.provider_app_id uuid references provider_apps(id): the app that made the
-- connection (null = platform default). Refresh and revoke always use that same app.

create table public.approvals (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null,
  tool_run_id uuid not null references public.tool_runs(id) on delete cascade,
  preview jsonb not null,
  status text not null default 'pending',       -- pending | approved | rejected | expired
  decided_at timestamptz
);
```

RLS policies: `select using (user_id = auth.uid())` on all tables; `connections` exposed to the client through a **view that omits `secret_id`**. `provider_apps`: RLS on, clients may select only `id, user_id, provider, created_at` (never `client_id`, `secret_id`, `extra`); all writes via FastAPI.

## 7. Secrets and tokens

- `SecretStore` interface: `put(user_id, payload) -> secret_id`, `get(secret_id) -> payload`, `delete(secret_id)`.
- Implement `AesGcmSecretStore` first (cryptography lib, key from `TOKEN_ENCRYPTION_KEY`, ciphertext stored in a `secrets` table with RLS and no client policies).
- Implement `VaultSecretStore` (Supabase Vault via SQL functions callable only by service role) behind the same interface. Selected by `SECRET_STORE`.
- Payload = `{access_token, refresh_token, expires_at, token_type, extra}`.
- Refresh on demand, 60 seconds before expiry. On `invalid_grant`, set `status='needs_reauth'`.
- Disconnect = revoke at the provider (when supported) then delete the secret and mark the connection `revoked`.
- Never log tokens, auth codes, or full tool arguments. Redact before writing `tool_runs.args_redacted`.

## 8. Connector manifest (the core abstraction)

```python
class ToolDef(BaseModel):
    name: str                      # 'google_sheets__append_row' (letters, digits, _ and - only)
    description: str               # written for the model; say when to use it
    parameters: dict               # JSON Schema; additionalProperties: false
    risk: Literal['read','write','destructive']
    handler: Callable[..., Awaitable[Any]]   # (ctx, **args) -> JSON-serializable result

class ConnectorManifest(BaseModel):
    id: str                        # 'google_sheets'
    name: str
    icon: str
    auth_type: Literal['oauth2','api_key','connection_string']
    authorize_url: str | None
    token_url: str | None
    scopes: list[str]
    extra_authorize_params: dict[str, str] = {}
    token_auth_style: Literal['body','basic'] = 'body'
    pkce: bool = True
    revoke_url: str | None = None
    tools: list[ToolDef]
    credential_fields: list[CredentialField]   # the Set up form, e.g. client_id + client_secret
    app_provider: str | None = None            # shared credential group (Google connectors: 'google')
    console_url: str | None = None             # provider developer console link
    setup_guide: list[str] = []                # short steps shown on the Set up form
    # Optional hooks for providers that deviate from plain OAuth2:
    # parse_token_response(), account_label(), revoke(), validate_credentials()

class CredentialField(BaseModel):
    key: str                       # 'client_id', 'client_secret', 'app_id', 'api_key', 'connection_string'
    label: str
    secret: bool                   # encrypted via SecretStore, never returned to the browser
    help_text: str
```

Examples: Google, Slack, Notion and GitHub take `client_id` + `client_secret` (GitHub adds an optional
`app_slug`); Meta takes `app_id` + `app_secret`; API-key connectors take the key; Postgres takes the
connection string. Every connector, including `api_key` and `connection_string`, uses the same
form-driven flow: **Set up → Save → Test → Connect**.

Credential resolution for every flow: the user's `provider_app` → `PLATFORM_<APP>_<FIELD>` env
defaults → a clear `setup_required` error.

`registry.py` auto-discovers manifests. One **generic OAuth router** serves all `oauth2` connectors:

- `POST|GET|DELETE /api/provider-apps/{provider}` → save, view (masked client id, never secrets), remove. Removing refuses with `409 has_connections` (listing them) unless `?confirm=true`, then disconnects those connections and deletes the credentials.
- `POST /api/provider-apps/{provider}/test` → format check plus a harmless provider call (OAuth: redeem a dummy code; `invalid_client` = bad credentials, `invalid_grant` = good).
- `POST /api/connections/{provider}/start` → resolves the provider app. OAuth: returns `{authorize_url}` and builds a signed `state` (user id, provider, provider_app id, nonce) stored in `oauth_states` with the PKCE verifier. Non-OAuth: validates the saved credentials and connects (`{connected: true}`).
- `GET /api/oauth/callback/{family}` → one route per provider family; the signed state carries the **connector id** that started the flow, so the shared Google URI routes to the right connector. Legacy per-connector routes (`/callback/google_sheets`, ...) keep working and exchange the code with the redirect URI they were called on. Verifies state, loads **the provider_app named in the state**, exchanges code **server-side**, stores tokens via `SecretStore`, upserts `connections` (with `provider_app_id`), redirects to `{WEB_BASE_URL}/connections?connected={provider}`. Token refresh and revoke use the same app.
- `POST /api/connections/{id}/disconnect`
- `GET /api/connections` → list for the current user (no secrets).

## 9. Agent runtime

Per chat message (`POST /api/chat`, streams Server-Sent Events):

1. Load the user's active connections. Build the tool list **only** from those connectors. If more than `MAX_TOOLS_PER_REQUEST`, keep the connectors mentioned in the message plus the most recently used.
2. Convert each `ToolDef` to an OpenAI tool: `{"type":"function","function":{name, description, parameters, "strict": true}}`.
3. Call the model. If it returns tool calls: for each, run the **policy check**, then execute the handler with that user's token (refresh first if needed).
4. Append the tool result (`role:"tool"`, `tool_call_id`) and call the model again. Stop when the reply has no tool calls or after `MAX_TOOL_STEPS`.
5. Persist every message and a `tool_runs` row per call.

SSE events: `token`, `tool_call`, `approval_required`, `tool_result`, `error`, `done`.

System prompt rules (`prompts.py`): act only through tools; never invent IDs, ranges, or channel names; ask a short question when a required argument is missing; summarize what was done in plain words; never reveal tokens.

### Approval policy (`policy.py`)

| Risk | Examples | Behavior |
| --- | --- | --- |
| read | list rows, search Notion, run SELECT, read ad insights | Run immediately |
| write | append row, create doc/page/event/issue, post Slack message | Show preview and wait, unless `connections.auto_approve_writes` is true |
| destructive | delete, bulk send, any email send, change budget | **Always** ask, even with auto-approve |

Flow when approval is needed: create `tool_runs(status=pending)` + `approvals(status=pending, preview)`, emit `approval_required`, stop the loop. `POST /api/approvals/{id}/decision {approve: bool}` resumes: on approve run the tool and continue the loop; on reject send the model a tool result saying the user declined.

## 10. MCP layer

- `app/mcp/server.py`: a `FastMCP` server built from the registry. Each `ToolDef` becomes an MCP tool with annotations (`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint=true`) derived from `risk`.
- Phase 1: **in-process only**, no public MCP endpoint. The agent runtime calls the same handlers.
- Later (not now): expose it over HTTP with OAuth Protected Resource Metadata (RFC 9728) per the MCP authorization spec.

## 11. Connector specs

Use the **minimum scopes**. Add scopes only when a tool needs them. Each user creates the provider app
below in their own developer account and enters its credentials on the connector's Set up form; no
provider credentials live in env (except optional `PLATFORM_*` defaults).

### Google (Sheets, Docs, Calendar; Gmail later)
- Authorize: `https://accounts.google.com/o/oauth2/v2/auth` · Token: `https://oauth2.googleapis.com/token` · Revoke: `https://oauth2.googleapis.com/revoke`
- Credentials: one Google OAuth client (`client_id`, `client_secret`) shared by Sheets, Docs and Calendar (`app_provider='google'`); register the single redirect URI `{PUBLIC_API_BASE_URL}/api/oauth/callback/google`. Google accepts `http://localhost` redirects for web clients (verified in Google's OAuth docs).
- Extra params: `access_type=offline`, `prompt=consent`, `include_granted_scopes=true`. A refresh token is only returned on first authorization, so keep `prompt=consent`.
- Scopes: `https://www.googleapis.com/auth/spreadsheets`, `.../documents`, `.../calendar.events`, Gmail later: `.../gmail.send` only.
- **VERIFY** each scope's sensitivity in Google's scope table. Sheets `spreadsheets` is sensitive; full `drive` and `gmail.readonly` are restricted (annual security assessment). Do **not** request restricted scopes.
- Without a Drive scope the app cannot list files. Tools take a spreadsheet/document ID or URL pasted by the user (parse the ID). A Google Picker flow with `drive.file` is a later improvement.
- Tools:
  - `google_sheets__get_values(spreadsheet_id, range)` read
  - `google_sheets__append_row(spreadsheet_id, range, values)` write
  - `google_sheets__update_values(spreadsheet_id, range, values)` write
  - `google_sheets__create_spreadsheet(title)` write
  - `google_docs__create_document(title, content)` write
  - `google_docs__get_document(document_id)` read
  - `google_docs__append_text(document_id, text)` write
  - `google_calendar__list_events(time_min, time_max)` read
  - `google_calendar__create_event(summary, start, end, attendees?)` write
  - Phase 4: `gmail__send_email(to, subject, body)` destructive

### Slack
- Authorize: `https://slack.com/oauth/v2/authorize` (bot scopes in `scope`, comma-separated) · Token: `https://slack.com/api/oauth.v2.access` (POST form).
- Credentials: Slack app `client_id`, `client_secret` (HTTP Basic on the token endpoint).
- Redirect URI `.../callback/slack`. **Slack requires HTTPS redirect URLs** (verified in Slack's docs): use the tunnel in local dev.
- Bot scopes: `chat:write`, `channels:read`, `users:read`. Store the `xoxb-` bot token from the top level of the response. Bot tokens do not expire unless token rotation is enabled.
- Tools: `slack__list_channels` read, `slack__post_message(channel, text)` write.

### Notion
- Authorize: `https://api.notion.com/v1/oauth/authorize` (`client_id`, `redirect_uri`, `response_type=code`, `owner=user`, `state`) · Token: `https://api.notion.com/v1/oauth/token` with **HTTP Basic** auth (`client_id:client_secret`) → `token_auth_style='basic'`.
- Credentials: public integration `client_id`, `client_secret`. Redirect URI `.../callback/notion`. Notion's docs do not state a localhost rule (unverified): try localhost, use the tunnel if rejected.
- Users choose which pages to share in Notion's page picker. Each user authorizes individually. Support refresh (`grant_type=refresh_token`). Header `Notion-Version` must be sent; **VERIFY** the current value.
- Tools: `notion__search(query)` read, `notion__get_page(page_id)` read, `notion__query_database(database_id, filter?)` read, `notion__create_page(parent_id, title, content?)` write.

### GitHub (use a GitHub App, not an OAuth App)
- GitHub Apps give fine-grained permissions and per-repo installation. User access tokens expire after 8 hours with a 6-month refresh token. **VERIFY** endpoints and the install flow in the GitHub Apps docs.
- Credentials: GitHub App `client_id` (not the App ID), `client_secret`, optional `app_slug` (install link). Redirect URI `.../callback/github`. GitHub's docs do not state a localhost rule (unverified; its own tutorials use localhost): try localhost, use the tunnel if rejected.
- Permissions: Issues (read/write), Pull requests (read), Contents (read), Metadata (read).
- Tools: `github__list_repos`, `github__list_issues(repo, state?)` read; `github__create_issue(repo, title, body)`, `github__comment_on_issue(repo, number, body)` write.

### Postgres (user's own database)
- `auth_type='connection_string'`; credential field `connection_string` (secret). UI copy tells the user to create a **read-only role**.
- On save: parse the URL, require SSL, connect, run `select 1`, list tables.
- SSRF guard: reject hosts that resolve to loopback, link-local (incl. `169.254.169.254`), or private ranges unless `ALLOW_PRIVATE_DB_HOSTS=true`.
- Tools: `postgres__list_tables`, `postgres__describe_table(table)`, `postgres__run_select(sql)` all **read**.
- `run_select` rules: single statement, must start with `SELECT` or `WITH`, reject anything containing DDL/DML keywords, run inside `BEGIN READ ONLY`, `statement_timeout=10s`, cap at 500 rows.

### Meta (Phase 5)
- Credentials: Meta app `app_id`, `app_secret` (`client_id_field='app_id'`, `client_secret_field='app_secret'`). Redirect URI `.../callback/meta` (`app_provider='meta'`). Meta enforces HTTPS for OAuth redirects by default and only exempts localhost in development mode per an old announcement (**VERIFY** in the App Dashboard): use the tunnel.
- Facebook Login, code exchange on the server, then exchange for a **long-lived user token** (about 60 days) via `grant_type=fb_exchange_token`. An expired token cannot be extended, so on expiry set `needs_reauth`.
- Start with `ads_read`. `ads_management` and the full Marketing API Access Tier need App Review. The tier was renamed from "Ads Management Standard Access" on 2026-05-04.
- Graph API version from `META_GRAPH_VERSION`. **VERIFY** current version and permission names.
- Tools: `meta_ads__list_ad_accounts` read, `meta_ads__get_insights(account_id, date_range, level)` read.

### Google Ads (Phase 5)
- OAuth scope `https://www.googleapis.com/auth/adwords`, same Google endpoints and the user's Google app credentials.
- **Developer tokens were sunset on 2026-09-09.** Access levels (Test, Explorer, Basic, Standard) now belong to the **Google Cloud project**, and you apply on the project's Google Ads API page in Cloud Console. Do **not** build around a developer token. Explorer allows 2,880 production operations a day, Basic 15,000. **VERIFY** on the live page.
- Tools: `google_ads__list_accessible_customers` read, `google_ads__run_gaql_query(customer_id, query)` read (reject mutate operations).

## 12. Frontend requirements

- Auth with Supabase Auth (email + Google sign-in). Protected routes.
- **/connections**: grid of connector cards (icon, name, status badge). Buttons: Connect, Reconnect, Disconnect. Postgres and API-key cards open a small form. A per-card toggle "Auto-approve writes".
- **/chat**: message list with streaming, tool-call chips ("Appending row to Sheets…"), an inline **approval card** (preview + Approve / Reject), conversation sidebar.
- Empty state on chat: if no apps are connected, show a prompt to connect one.
- Accessible, responsive, no secrets in client bundles.

## 13. Security checklist (must pass before any phase is "done")

- [ ] RLS enabled on every table; tested that user A cannot read user B's rows.
- [ ] `SUPABASE_SERVICE_ROLE_KEY` and provider secrets appear only in server env.
- [ ] OAuth `state` is signed, single-use, expires in 10 minutes; PKCE where supported.
- [ ] Tokens encrypted at rest; `secret_id` never returned to the client.
- [ ] Logs contain no tokens, codes, or raw tool args.
- [ ] Postgres SSRF guard and read-only enforcement tested.
- [ ] Approval policy enforced in code for write and destructive tools.
- [ ] Rate limit `/api/chat` per user.

## 14. Build phases (do them in order, commit after each)

**Phase 0 — Foundations.** Monorepo scaffold, `.env.example`, Supabase migration, FastAPI health route, Supabase JWT verification dependency, Next.js shell with login and protected layout, `SecretStore` (aesgcm) with unit tests.
*Done when:* user can sign up, log in, and `GET /api/health` and an authenticated `GET /api/me` work.

**Phase 1 — OAuth broker + first connectors.** Manifest model, registry, generic OAuth router, state signing, refresh/revoke, `/connections` UI. Connectors: Google (Sheets, Docs, Calendar), Slack, Notion, GitHub.
*Done when:* each connector connects end to end (against real dev apps) and shows Connected; disconnect revokes and deletes; a forced `invalid_grant` shows Reconnect. Tests use mocked token endpoints.

**Phase 2 — Agent + approvals.** Tool registry, MCP server, OpenAI loop with SSE, policy, approval card, tool_runs audit.
*Done when:* "append a row with X to my sheet" works with an approval prompt; "list my Notion pages matching Y" runs without one; a rejected approval is reported back by the model.

**Phase 3 — Data.** Postgres connector (read-only, guarded), Gmail send-only.
*Done when:* natural-language question about a connected DB returns a `SELECT` result; destructive keywords are refused; email send always asks.

**Phase 4 — Ads (only after approvals clear).** Meta and Google Ads read tools.
*Done when:* insights for a test/own account are returned in chat.

## 15. How to work (rules for Claude Code)

1. Start every phase with a short plan, then implement. Commit at the end of each phase with a clear message.
2. Write tests with each feature. Run them (`pytest`, `vitest`) and fix failures before moving on.
3. Never hard-code secrets, model names, or API versions. Everything configurable goes in env.
4. Never skip a **VERIFY** item: open the provider's current docs and follow them. If docs and this file disagree, the docs win; note the difference in `docs/decisions.md`.
5. Keep connectors isolated: one file per connector, no provider-specific code in routers, runtime, or UI.
6. When you need real credentials (Google, Slack, Notion, GitHub apps), stop, list exactly what to create and which redirect URI and scopes to use, and continue with mocked tests meanwhile.
7. Prefer small, typed, boring code. No new dependencies without a one-line reason in the commit message.
8. Maintain `README.md` with: local setup, how to create each provider app (redirect URI, scopes), how to run tests, and how to add a new connector in under 10 steps.
9. **No paid external API calls without approval (permanent rule).** Never call the OpenAI API, or any other
   paid external API, for testing, debugging or verification without the user's explicit approval in the chat
   first.
   - Tests must mock or stub the LLM: fake clients and recorded fixtures only (see `FakeLLM` in
     `apps/api/tests/test_agent.py`).
   - Do not run app flows that trigger real OpenAI calls (chat, agent runs, evals) unless the user says
     "approved".
   - If a real call seems necessary, stop, explain why, estimate the cost, and wait for approval.
   - Never read or print `OPENAI_API_KEY` (or any other secret from `.env`).

## 16. Commands (create these scripts)

```
# api
cd apps/api && uvicorn app.main:app --reload --port 8000
cd apps/api && pytest -q

# web
cd apps/web && npm run dev
cd apps/web && npm test

# db
supabase db reset        # applies supabase/migrations
```
