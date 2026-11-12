# MEMORY.md — project context for future sessions

Keep under 150 lines. Update before finishing every session (state, decisions, issues, next steps).
Last updated: 2026-11-12, architecture revision (see CLAUDE.md, rewritten today).

## 1. What we are building
A **chat-first workflow platform**: connectors become nodes; users build workflows by chat or by drag and drop
(React Flow canvas), and the chat is a more autonomous agent with scoped modes (`/custom`, `/workflow`,
`/<connector>`). One workflow JSON, one patch API, a separate worker with a Postgres queue. Full design: CLAUDE.md.

## 2. Stack
Next.js 16 (App Router, React 19, Tailwind 4) · FastAPI (Python 3.12) · Supabase (Postgres, Auth, RLS) · OpenAI
`gpt-4o-mini` (env `OPENAI_MODEL`) · MCP in-process · pytest + respx, Vitest.
Repo: https://github.com/saranjoybps/joyconnect (branch `main`). Local clone: `C:\connect\joyconnect`.

## 3. Current state (2026-11-12)
Built before the revision (all still in place):
- 18 connectors, 67 tools (Google Sheets/Docs/Calendar/Gmail/Drive/Slides/Forms/Tasks/Contacts/Meet, Slack, Notion,
  GitHub, Airtable, Trello, Linear, Asana, Stripe read-only). Only Sheets, Docs, Calendar were used against real Google.
- OAuth broker, per-user provider apps, granted-scope checks, health checks, Runs page, chat agent with approvals
  and SSE, conversation delete.
- Part 0 (commit `968baab`): chat follow-up fix (orphaned tool calls are repaired on replay and always closed) and
  the response contract (`app/agent/response.py`: validated Action per tool call, Markdown UI, error block with
  Reconnect/Retry).
Revision plan (CLAUDE.md section 5): workflow engine in steps 1-7 below. Progress is tracked in section 6.

## 4. Key decisions (details in docs/decisions.md)
- Credentials entered by each user in the UI, stored encrypted in `provider_apps`; one redirect URI per provider family.
- Granted-scope checks; "Partial access" badge; tools missing a scope never call the provider.
- Risk policy enforced in code. Workflow `auto_approve` is `off | writes | all`: `writes` skips approval for write
  nodes only; destructive nodes pause unless `all` (we kept "destructive always asks" unless explicitly opted in).
- Chat response = short Markdown + server-built validated actions; never raw JSON in the UI.
- Expressions use our own parser (no eval). `$node["Name"].json` (legacy n8n form, as requested) and the documented
  `$("Name")` form are both supported.

## 5. Rules from the owner (permanent)
1. Never call the OpenAI API or any paid API for testing without explicit approval ("approved"); mock the LLM.
2. Build connectors/nodes only from official docs (n8n docs for n8n-modeled nodes); stop and ask if unclear.
3. Never print or commit secrets.

## 6. Progress and next steps
- [x] Part 1: CLAUDE.md rewritten, MEMORY.md updated.
- [ ] Step 1: workflow schema, node registry, patch API, versioning, migrations.
- [ ] Step 2: executor + worker, expressions, node records, retries, test-node, run-from-here.
- [ ] Step 3: triggers (manual, schedule, webhook). **Then STOP and wait for the owner's go-ahead.**
- [ ] Step 4 canvas UI · Step 5 chat modes/slash commands/server-side scope · Step 6 chat workflow tools + diff review +
  delete approval · Step 7 AI Agent / LLM / Classify / Extract / Approval nodes.

Known issues:
- Migration `0006` (and the new workflow migrations) must be applied to the live Supabase project by the owner
  (`apps/api/scripts/apply_migrations.py`, needs `SUPABASE_DB_URL`); the agent was blocked from running it.
- Windows: `uvicorn --reload` may leave an orphaned worker holding port 8000; restart by hand.
- Retry in chat re-sends the last user message (adds a duplicate user bubble).

## 7. How to run
```powershell
cd C:\connect\joyconnect\apps\api ; .\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
cd C:\connect\joyconnect\apps\api ; .\.venv\Scripts\python.exe -m app.worker      # after Step 2
cd C:\connect\joyconnect\apps\web ; npm run dev                                   # http://localhost:3000
cd C:\connect\joyconnect\apps\api ; .\.venv\Scripts\python.exe -m pytest -q
cd C:\connect\joyconnect\apps\web ; npx vitest run ; npm run typecheck
.\scripts\dev-tunnel.ps1       # HTTPS tunnel for Slack/Meta redirect URIs (cloudflared is installed)
```
Env lives in git-ignored root `.env`, `apps/api/.env.local`, `apps/web/.env.local`.
Docs: CLAUDE.md (design + rules), docs/decisions.md, README.md (setup, provider apps).
