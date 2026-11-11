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
