# Decisions and differences from CLAUDE.md

Each entry: what CLAUDE.md says, what the live docs say (checked 2026-11-11), what we did.

## Platform

- **Python 3.12** is used locally (spec: 3.11+). No 3.11 runtime on the dev machine.
- **Supabase JWT verification.** Supabase now recommends asymmetric signing keys (ES256/RS256)
  verified via `{SUPABASE_URL}/auth/v1/.well-known/jwks.json`; the HS256 JWT secret is legacy.
  FastAPI verifies via JWKS and accepts HS256 only when `SUPABASE_JWT_SECRET` is set. `aud` must be
  `authenticated`.
- **Supabase API keys.** Supports both legacy JWT service-role keys (sent as `apikey` + `Authorization`)
  and new `sb_secret_...` keys (sent as `apikey` only).
- **Next.js 16.** `middleware.ts` is deprecated and renamed `proxy.ts`. The UI guard lives in
  `apps/web/proxy.ts` and uses `supabase.auth.getClaims()` (verifies the JWT), not `getSession()`.
  `cacheComponents` is on, so protected pages are client components that call FastAPI with the user's
  access token; FastAPI is the authority on identity.
- **Migrations without the Supabase CLI.** `apps/api/scripts/apply_migrations.py` applies
  `supabase/migrations/*.sql` once each to `SUPABASE_DB_URL` (tracked in `public._app_migrations`).
  `supabase db reset` still works for a local stack.

## Database / RLS

- **`oauth_states` and `secrets` have no client policies at all** (spec says "select own rows on all
  tables"). State rows hold PKCE verifiers; there is no reason for a browser to read them.
- **`connections`**: a `connections_public` view (security_invoker) omits `secret_id`, *and*
  column-level grants stop clients selecting `secret_id` from the base table.
- Client roles have insert/update/delete revoked on every table; all writes go through FastAPI.

## OAuth

- **PKCE verifier is not in the state.** Spec says the signed state contains the PKCE verifier. The
  state travels through the browser and the provider, which would defeat PKCE. The state carries
  (user, provider, nonce, iat) + HMAC; the verifier is stored only in the `oauth_states` row.
- **Google account label.** With only Sheets/Docs/Calendar scopes we cannot learn the account email,
  and `account_label` is part of the unique key. We add the non-sensitive `openid email` scopes and
  read `email` from the `id_token` returned by the token endpoint (direct TLS response from Google).
- **Google scope sensitivity.** The public scope list no longer labels sensitivity; it is shown on the
  Cloud Console consent screen. `spreadsheets`, `documents`, `calendar.events` show as *sensitive*
  (verification needed for production, not for testing users); none are restricted.
- **Slack.** `oauth.v2.access` docs recommend HTTP Basic client auth → `token_auth_style='basic'`.
  PKCE must be explicitly allowed per app (`pkce_not_allowed`), so PKCE is off (confidential client).
  Errors come back as HTTP 200 `{ok:false,error}`. Revocation via `auth.revoke`.
- **Notion.** Token endpoint takes a **JSON** body with HTTP Basic auth (not form). Current
  `Notion-Version` is **2026-03-11** (configurable via `NOTION_VERSION`). Since 2025-09-03, databases
  are queried through data sources: `GET /v1/databases/{id}` → `data_sources[].id` →
  `POST /v1/data_sources/{id}/query`. Revoke exists: `POST /v1/oauth/revoke` (Basic, JSON `{token}`).
  PKCE is not documented, so it is off.
- **GitHub App.** User tokens via `https://github.com/login/oauth/authorize` and
  `.../access_token` (Accept: application/json). PKCE S256 supported. Access tokens 8 h, refresh 6
  months. Refresh failure error code is `bad_refresh_token` (treated like `invalid_grant`). Errors come
  back as HTTP 200 with an `error` field. Revoke: `DELETE /applications/{client_id}/token` (Basic).
  The app must also be *installed* on repos; `GITHUB_APP_SLUG` builds the install link.

## Phase 2 — agent

- **OpenAI.** Python SDK 3.x; we use Chat Completions (still supported; the guide's examples now favour
  the Responses API, and some newer models require it for tools; `gpt-4o-mini` does not). Tools are sent
  with `strict: true` and `parallel_tool_calls: false` (one call per turn: keeps strict mode reliable and
  makes the approval pause/resume unambiguous). Chat Completions is non-strict by default, so `strict` is
  set explicitly on every tool.
- **MCP SDK 2.x renamed FastMCP to `MCPServer`.** `MCPServer.add_tool` infers schemas from Python
  signatures; our tools are schema-first, so `app/mcp/server.py` uses the SDK's low-level
  `Server(on_list_tools=..., on_call_tool=...)` with explicit `input_schema` and `ToolAnnotations`
  (`read_only_hint`, `destructive_hint`, `idempotent_hint`, `open_world_hint=True`). In-process only.
  Tests connect with `mcp.Client(server)`.
- **Approved arguments come from the stored assistant message**, not from `tool_runs.args_redacted`
  (which is redacted for the audit log). `approvals.preview` holds a lightly clipped copy for display.
- **Pending approvals block new messages** in that conversation (HTTP 409) so the tool-call history sent to
  OpenAI is always complete. Approvals expire after `APPROVAL_TTL_HOURS` (default 24).
- **Decision endpoint streams SSE** (same events as `/api/chat`) because approving resumes the loop.
- **Rate limit** is an in-process sliding window per user (`CHAT_RATE_LIMIT_PER_MINUTE`, default 20) on
  `/api/chat` and decisions. Use a shared store (e.g. Redis/Postgres) when running more than one worker.
- **Migration 0003** adds `messages.seq` (identity) for deterministic ordering and `approvals.created_at`.
- **Tool selection.** Only tools of the user's *active* connections are offered. Above
  `MAX_TOOLS_PER_REQUEST`, whole connectors are kept in order: mentioned in the message, then most
  recently used.

## User-entered provider credentials (provider_apps)

- **Credential groups.** `ConnectorManifest.app_provider` lets connectors share one app: Sheets, Docs and
  Calendar all use the user's single `google` app (one consent screen, three redirect URIs).
- **Storage.** Non-secret fields: `provider_apps.client_id` and `extra`. Secret fields: one SecretStore
  payload `{"secrets": {...}}` referenced by `secret_id`. Clients have column grants only on
  `id, user_id, provider, created_at`; the API returns a masked client ID and never a secret.
- **Same app end to end.** The signed OAuth state carries the provider_app id (`a`), the callback loads
  exactly that app, and `connections.provider_app_id` makes refresh and revoke use it too. `null` means the
  platform default. If the app is deleted, the callback fails with `setup_required` and existing
  connections become `needs_reauth`.
- **Credential test.** No provider offers a "validate client" endpoint, so we redeem a dummy
  authorization code. Wrong credentials → `invalid_client` (Google, Notion), `invalid_client_id` /
  `bad_client_secret` (Slack), `incorrect_client_credentials` (GitHub); right credentials → an invalid-code
  error. Each manifest lists its `invalid_client_errors`. Nothing is created at the provider.
- **Removed endpoints.** `POST /api/connections/api-key` and `/connection-string` are gone; non-OAuth
  connectors save credentials through `/api/provider-apps/{provider}` and connect through the same
  `/api/connections/{provider}/start`, which validates them.
- **Env.** `GOOGLE_CLIENT_ID`/`SLACK_CLIENT_ID`/... and `GITHUB_APP_SLUG` were removed. Optional
  `PLATFORM_<APP>_<FIELD>` defaults replace them (GitHub's slug became a form field).

## Redirect URIs: one per provider family, from PUBLIC_API_BASE_URL

- **PUBLIC_API_BASE_URL** (default `API_BASE_URL`) is the only base for redirect URIs; `API_BASE_URL` stays
  what the browser calls. `apps/api/.env.local` is loaded after `.env` so `scripts/dev-tunnel.*` can set it.
- **One URI per family** (`google`, `slack`, `notion`, `github`, later `meta`), keyed by the manifest's
  `credentials_key`. The signed state already carried the connector id (`p`), so the callback resolves the
  connector from the state and only checks that the route is that connector's id or family.
- **Legacy routes** (`/callback/google_sheets`...) are kept and exchange the code with the redirect URI of
  the route they were called on (it must equal the one sent to `/authorize`). Existing connections need no
  change: refresh and revoke do not send a redirect URI.
- **Changed-URI banner**: `provider_apps.redirect_uri` (migration 0005, not granted to clients) records the URI
  at save time; the catalog reports `redirect_uri_changed` when it differs from the current one; the user
  confirms via `POST /api/provider-apps/{provider}/redirect-uri/ack`. Rows saved before 0005 have no value and
  are not flagged (Google users saved under the old per-connector URIs must register the new shared one).
- **HTTPS vs localhost, checked 2026-11-11.** Slack docs: "The `redirect_uri` must use HTTPS" (localhost
  not accepted). Google docs: localhost exempt from the HTTPS rule. Notion docs and GitHub docs say nothing
  about localhost (third-party guides and GitHub's tutorials use it), so they are `unverified`: try localhost,
  tunnel if rejected. Meta: "Enforce HTTPS" is on by default; localhost is only exempt in development mode per a
  2018 announcement, no current doc found, so use the tunnel (VERIFY in the App Dashboard in Phase 4).
- **Tunnel is optional and local-only**: quick tunnels do not carry SSE, so chat stays on `API_BASE_URL`.

## Granted scopes are stored as returned, and checked per tool

- **Bug (2026-11-11).** Google Sheets `create_spreadsheet` failed with 403 "insufficient authentication
  scopes" although the card said Connected. The database showed the `google_sheets` connection held only
  `openid` + `userinfo.email`: Google had not granted the `spreadsheets` scope (granular consent: the
  checkbox was unticked). Calendar and Docs tokens held their own scopes (merged by
  `include_granted_scopes`) but not Sheets either. Our code stored the token response `scope` honestly but
  never compared it with what the connector needs, so the card showed Connected, the tool ran, and Google
  answered with a raw 403. The tool binding, the authorize URL and the callback were not at fault.
- **Fix.** `ConnectorManifest.verifies_scopes` (Google) turns on three things: the stored scopes are never
  replaced by the requested list when the response omits `scope`; a connection missing a functional scope is
  reported as `partial` (computed, no new status value) with `missing_scopes`; and each tool is bound to a
  connection whose scopes cover `ToolDef.scopes` (default: the connector's functional scopes).
- **Selection order**: the connector's own connections, then another connection of the same credential group
  *and the same Google account label* (Google merges earlier grants, so a Docs token may carry Sheets). Never
  another user's. Auto-approve needs both the card toggled and the connection actually used to allow it.
- **Friendly failure**: a tool whose connection lacks the scope never calls Google and never asks for
  approval; it returns "Reconnect Google Sheets and tick the Sheets permission". A raw 403
  "insufficient" from Google (revoked grant) is mapped to the same message.
- **tokeninfo not used**: the token response `scope` field is authoritative and documented; tokeninfo would
  put the access token in a URL.


## Google Workspace connectors (2026-11-11)

Docs used: developers.google.com/workspace/{gmail,drive,slides,forms,tasks,people,meet,calendar,docs,sheets}
(API references and each service's auth/scopes page); common quota/error behaviour 429 + `Retry-After`.

| Connector | Scopes chosen | Why / skipped |
| --- | --- | --- |
| Gmail | `gmail.send`, `gmail.labels` | `messages.send` is covered by `gmail.send` (sensitive); `labels.list` is not covered by send, so the non-sensitive `gmail.labels` is added. **Skipped: create draft.** `drafts.create` needs `gmail.compose` (restricted, annual security assessment), `gmail.modify` or `readonly`. Send is tagged destructive (always asks). |
| Drive | `drive.file` | Non-sensitive; only files this app created. Full `drive` is restricted. Upload is multipart text up to 5 MB. |
| Slides | `presentations` | Sensitive. Works on decks given by link; `drive.file` would only cover app-created decks. |
| Forms | `forms.body`, `forms.responses.readonly` | create/batchUpdate and responses.list respectively. |
| Tasks | `tasks` | Single read/write scope. Delete is destructive. |
| Contacts | `contacts` | People API connections.list, searchContacts, createContact. |
| Meet | `meetings.space.created` | Create spaces and read spaces the app created. |
| Calendar (extended) | `calendar.events`, `calendar.calendarlist.readonly`, `calendar.freebusy` | Per-tool scopes; existing connections without the new two show "Partial access" until reconnected. |
| Docs / Sheets (extended) | unchanged | replace text, insert table; list tabs, add tab, clear range (destructive). |

Not verified from the docs available: the sensitivity classification of the Forms, Tasks, Contacts and Meet
scopes. Check them under Google Auth Platform > Data access before going beyond test users.


## Token-based connectors (2026-11-11)

Docs: airtable.com/developers/web/api, developer.atlassian.com/cloud/trello/rest, linear.app/developers/graphql,
developers.asana.com/docs, docs.stripe.com/api. Auth is each provider's own documented static credential,
entered on the Set up form and stored encrypted (`provider_apps`); nothing in env.

| Connector | Auth | Tools | Notes / skipped |
| --- | --- | --- | --- |
| Airtable | PAT, Bearer | list bases, list records, create record | 5 req/s per base; one record per create. Update/delete skipped (not needed for the easy tier). |
| Trello | key + token query params | boards, lists, cards, create card | 300/10 s per key. |
| Linear | personal key, `Authorization: <key>` | teams, issues, create issue | **Skipped: comment and issue update** (mutation shapes not confirmed from the docs). Errors arrive as HTTP 200/400 with `errors`. |
| Asana | PAT, Bearer | workspaces, projects, tasks, create task | 429 + Retry-After. |
| Stripe | restricted key, Bearer | balance, customers, invoices | Read-only (GET only); publishable keys refused. |

**Skipped: HubSpot.** The docs do not give a clear static-credential path: legacy private apps are being
discontinued, the API is date-versioned and the scope names for CRM objects were not confirmed. It needs a
public-app OAuth flow, which is not the "easy tier"; decide before building.

**Granted-scopes check / Partial access badge:** not applicable. These providers expose no way to read a
token's permissions, so scopes are not tracked (`scopes=[]`) and a lack of permission surfaces as the provider's
401/403 text. Google connectors keep the full check.

## Slack, Notion, GitHub setup help re-checked against the official docs (2026-11-12)

Docs read: docs.slack.dev (installing-with-oauth, oauth.v2.access, conversations.list, chat.postMessage),
developers.notion.com (authorization, capabilities), docs.github.com (generating a user access token,
refreshing user access tokens, registering a GitHub App, permissions required for GitHub Apps).

| Item | Docs say | Change |
| --- | --- | --- |
| Slack redirect | `redirect_uri` must use HTTPS | none (already: tunnel) |
| Slack scopes | `chat:write` for chat.postMessage; conversations.list lists `channels:read` (plus groups/im/mpim for other types) | **Removed `users:read`**: no tool uses it (minimum scopes). Existing connections keep working. |
| Slack posting | the bot must be a channel member (`not_in_channel`); `chat:write.public` would lift that | Not added (broader scope). Setup help now says `/invite @YourApp` in each channel. |
| Slack client auth | Basic scheme "strongly" recommended | none (already `token_auth_style=basic`) |
| Notion | authorize `owner=user`; token with Basic auth, JSON body; refresh supported; send `Notion-Version: 2026-03-11` | none. Capability names (Read, Insert, Update content) confirmed. Localhost rule still unstated. |
| GitHub flow | PKCE `S256`; user tokens expire in 8 h; refresh token 6 months and **rotates on every refresh** | none (we store the new refresh token; covered by a test) |
| GitHub permissions | create/list/comment issues need Issues write/read; installation repositories need Metadata read | **Setup help no longer asks for Pull requests and Contents**: no tool uses them. Metadata is automatic. |
| GitHub callback | docs do not state a localhost or HTTPS rule | unchanged: try localhost, else tunnel |

Not confirmed: the GitHub error code returned for an invalid refresh token (docs do not give one; we treat
`bad_refresh_token` and `invalid_grant` as needs-reauth, and any 401 from the API also marks Reconnect).

No live end-to-end run was possible: it needs real Slack, Notion and GitHub apps owned by the user.
