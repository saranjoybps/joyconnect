# MEMORY.md — project context for future sessions

Keep under 150 lines. Update before finishing every session (state, decisions, issues, next steps).
Last updated: 2026-11-11, after commit `f7d1898` (pushed to origin/main).

## 1. What we are building
A general-purpose AI integration platform: users connect their apps in a few steps (Set up -> Save -> Test ->
Connect) and then control them in plain language in a chat, through an AI agent that calls MCP-style tools.
It is NOT a CRM, a billing app or a voice agent. Every app is one declarative connector manifest
(`apps/api/app/connectors/<id>.py`); never add per-app code in routers, runtime or UI.

## 2. Stack
Next.js 16 (App Router, React 19, Tailwind 4) · FastAPI (Python 3.12, httpx, pydantic v2) · Supabase
(Postgres, Auth, RLS) · OpenAI `gpt-4o-mini` via tool calling (model name from env `OPENAI_MODEL`) ·
MCP (`FastMCP`, in-process only) · tests: pytest + respx (API), Vitest (web).
Repo: https://github.com/saranjoybps/joyconnect (branch `main`).

## 3. Current state (2026-11-11)
- Phases 0-2 done (auth, OAuth broker, connectors, agent + approval gate + SSE). Phase 3 (Postgres connector,
  Gmail send) and Phase 4 (Meta / Google Ads) are NOT built; Gmail send exists, Postgres/Meta/Google Ads do not.
- **18 connectors, 67 tools.**
- Tests: API **216 passed, 2 skipped**; web **40 passed**. All HTTP and the LLM are mocked.
- Chat has conversation delete (DELETE /api/conversations/{id}).

| Connector | Tools | Auth | Status |
| --- | --- | --- | --- |
| Google Sheets | 7 | OAuth (shared Google app) | Connected and used by the owner |
| Google Docs | 5 | OAuth | Connected by the owner |
| Google Calendar | 6 | OAuth | Connected; shows Partial until reconnected for the 2 new scopes |
| Gmail | 2 (send, list labels) | OAuth | Built, unit-tested, never connected live. No drafts (see 4) |
| Google Drive | 3 | OAuth | Built, unit-tested, not connected live |
| Google Slides | 4 | OAuth | Built, unit-tested, not connected live |
| Google Forms | 3 | OAuth | Built, unit-tested, not connected live |
| Google Tasks | 5 | OAuth | Built, unit-tested, not connected live |
| Google Contacts (People API) | 3 | OAuth | Built, unit-tested, not connected live |
| Google Meet | 2 | OAuth | Built, unit-tested, not connected live |
| Slack | 2 | OAuth | Needs setup (Slack requires an HTTPS redirect: use the tunnel) |
| Notion | 4 | OAuth | Needs setup |
| GitHub (GitHub App) | 4 | OAuth | Needs setup |
| Airtable | 3 | PAT | Built, unit-tested, not connected live |
| Trello | 4 | key + token | Built, unit-tested, not connected live |
| Linear | 3 | API key | Built, unit-tested; comment/update skipped (mutations not confirmed in docs) |
| Asana | 4 | PAT | Built, unit-tested, not connected live |
| Stripe | 3 (read-only) | restricted key | Built, unit-tested, not connected live |

Skipped: **HubSpot** (docs unclear: legacy private apps discontinued, date-versioned API, CRM scope names not
confirmed; needs an OAuth app, not the easy tier), **Gmail drafts** (need restricted `gmail.compose`),
Postgres, Meta Ads, Google Ads (later phases).

## 4. Key decisions (details in docs/decisions.md)
- **Credentials are entered by each user in the UI** and stored encrypted in `provider_apps` (AES-GCM
  SecretStore). Env only holds server keys; `PLATFORM_<APP>_<FIELD>` env defaults are an optional fallback.
- **One redirect URI per provider family**: `{PUBLIC_API_BASE_URL}/api/oauth/callback/{family}` (google, slack,
  notion, github, meta). All Google connectors share one OAuth client and one URI. The signed state carries the
  connector id. Legacy per-connector callback routes still work.
- **Tunnel for Slack** (and any provider rejecting http://localhost): `scripts/dev-tunnel.sh|.ps1` write
  `apps/api/.env.local` with `PUBLIC_API_BASE_URL`. The browser keeps calling `API_BASE_URL` (SSE not tunnelled).
- **Granted-scope checks (Google)**: store exactly the scopes Google returned; "partial" is computed from the
  manifest; each tool declares `scopes`; a tool whose connection lacks a scope never calls Google and never asks
  for approval, it says "Reconnect X and tick the Y permission". Card shows a **Partial access** badge.
  Token-based connectors (Airtable, Trello, Linear, Asana, Stripe) cannot report permissions, so no badge there;
  a 401/403 is shown as the provider's message.
- **Google scope choices**: Gmail = `gmail.send` + `gmail.labels` only (`gmail.compose`, `readonly`, `modify`
  are restricted: not used). Drive = `drive.file` only. Slides `presentations` (sensitive). Calendar =
  `calendar.events`, `calendar.calendarlist.readonly`, `calendar.freebusy`. Forms `forms.body` +
  `forms.responses.readonly`; Tasks `tasks`; Contacts `contacts`; Meet `meetings.space.created`.
- Risk policy is enforced in our code: read runs; write asks unless auto-approve; destructive (email send,
  delete, clear range) ALWAYS asks.
- Never log tokens/codes/secrets/raw tool args; `secret_id` and client secrets never reach the browser.

## 5. Rules from the owner (permanent)
1. **Never call the OpenAI API or any paid API for testing/debugging/verification without explicit approval in
   chat.** Do not run chat/agent/eval flows that hit OpenAI unless the user says "approved". If a real call seems
   necessary: stop, explain, estimate cost, wait.
2. **Mock the LLM in tests** (`FakeLLM` in `apps/api/tests/test_agent.py`); fixtures only.
3. **Build connectors only from the official docs**: fetch them first, confirm auth flow, exact scope names,
   endpoints, shapes, rate limits, errors. If docs are unclear or a scope is restricted, STOP and tell the user.
4. **Never read or print secrets** (OPENAI_API_KEY, service role key, client secrets, tokens). Never commit them.
5. Commit after each unit of work; run all tests before each commit.

## 6. Known issues and next steps
Known issues:
- Only Sheets, Docs and Calendar have been used against real Google; every other connector is unit-tested only.
- Existing Calendar connections must be reconnected to grant the two new scopes.
- Forms/Tasks/Contacts/Meet scope sensitivity not confirmed from docs: check Cloud Console > Data access.
- Unverified details: Slides text-box size/transform shape, Airtable 10-records-per-create limit.
- Windows: `uvicorn --reload` once failed to reload and an orphaned worker kept port 8000. After adding connector
  files restart the API by hand and confirm the NEW process owns port 8000 (check `.api.err.log`).
- Two dev logs were committed by mistake in `b4aacde` (startup output only); now untracked and git-ignored.

Next steps (in order):
1. End-to-end test each connector with real credentials (owner supplies them); finish Slack (tunnel), Notion, GitHub.
2. Harden the agent: tool-count limits, retries, better error summaries, per-user rate limits, eval fixtures.
3. Phase 3: Postgres connector (read-only, SSRF guard).
4. MCP exposure over HTTP (RFC 9728 protected resource metadata); in-process only today.
5. Deployment (hosting for API + web, public HTTPS callback URL, secrets management, Supabase prod project).
6. Phase 4 ads connectors only after approvals are proven; revisit HubSpot via OAuth.

## 7. How to run
```powershell
# API (restart manually after changes; no --reload)
cd C:\connnect\apps\api ; .\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
# Web
cd C:\connnect\apps\web ; npm run dev            # http://localhost:3000
# Tests
cd C:\connnect\apps\api ; .\.venv\Scripts\python.exe -m pytest -q
cd C:\connnect\apps\web ; npx vitest run
# Tunnel for HTTPS-only providers (Slack, Meta)
.\scripts\dev-tunnel.ps1        # or scripts/dev-tunnel.sh
```
Use the venv python for pytest (the system python has no pytest). DB: Supabase migrations 0001-0005 are
applied live; env in git-ignored `apps/api/.env`, `.env.local`, `apps/web/.env.local`.

Docs: `CLAUDE.md` (spec and rules), `docs/decisions.md` (doc URLs, scope choices, skips, bug post-mortems),
`README.md` (local setup, per-provider app setup, Google API/scope table, adding a connector).
