# MEMORY.md — project context for future sessions

Keep under 150 lines. Update before finishing every session (state, decisions, issues, next steps).
Last updated: 2026-11-12, after the minimal-design migration, migration 0008 and push (c4e94cf).

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
1. Never use the owner's OpenAI API key (or any paid API) for testing, debugging or verification unless the owner
   sends the exact text "yes use the openai key for testing" in the chat. Without it: mock/stub the LLM in every
   test and run no flow that triggers a real OpenAI call. If a real call seems needed: stop, explain why, estimate
   the cost, wait for that exact text. Approval covers only the one task it was given in; ask again next time.
   Never read or print the key.
2. Build connectors/nodes only from official docs (n8n docs for n8n-modeled nodes); stop and ask if unclear.
3. Never print or commit secrets.

## 6. Progress and next steps
- [x] Part 1: CLAUDE.md rewritten, MEMORY.md updated.
- [x] Step 1: workflow schema, node registry, patch API, versioning, migrations.
- [x] Step 2: executor + worker, expressions, node records, retries, test-node, run-from-here.
- [x] Step 3: triggers (manual, schedule, webhook).
- [x] Step 4: canvas UI (React Flow, palette, config panel, test node, run, publish switch, schedule settings, workflows list).
- [x] Step 5: chat modes (/custom, /workflow, /<connector>), slash menu, server-side tool scope. **STOPPED here: waiting for the owner go-ahead before Step 6.**
- [x] Discovery + agent quality (2026-11-12): search/list tools for every connector, drive.metadata.readonly (RESTRICTED scope,
  owner asked), prompt FIND-DON'T-ASK, Reject stops the task, memory (short-term summary + pgvector long-term + Memory page),
  guardrails (injection taint, schema validation, caps, daily token limit, final-answer check, PII log redaction),
  parallel read calls. All tests use mocked LLM/embedder. **Migration 0008 APPLIED 2026-11-12**
  (tables `memories`, `user_settings`, `llm_usage`, extension `vector`; the owner asked the agent to run
  `scripts/apply_migrations.py`, which skips already-applied files). Memory page works after an API restart.
  Existing Google connections show Partial access until reconnected (new scope); Slack needs `users:read`.
- [x] Load options (2026-11-12): connector `loaders` + `param_ui` (x-ui), `POST /api/nodes/{type}/options` (60 s cache, refresh),
  canvas: account, Resource, Operation, then dropdown / resource locator (list, URL, ID) / multi-select / tab range / column mapper;
  parent change clears children (`remove_parameters`), operation switch (`update_node.type`). Loaders wrap the same handlers as the chat
  discovery tools. No loaders for Stripe, Meet, Contacts. Tests: api 619, web 141, all mocked.
- [ ] Step 6 chat workflow tools + diff review + delete approval · Step 7 AI Agent / LLM / Classify / Extract / Approval nodes.
  Not done from the plan: Runs page grouped by workflow/node (CLAUDE.md 5.9), chat-generated workflow opening on the canvas (step 6).

Known issues:
- Migrations 0001-0008 are applied to the live Supabase project. Apply a new one only when the owner asks:
  `apps/api/scripts/apply_migrations.py` (reads `SUPABASE_DB_URL`, prints only file names; never print the URL).
- Python is not on PATH in Bash: use `apps/api/.venv/Scripts/python.exe`. Bash heredocs with quotes fail on Windows: use the
  Write tool or a `.cjs` script file. Full API suite takes ~4 min (run in background); web `npx vitest run` ~20 s.
- `next build` writes the same `.next` as the running dev server: ask first, or run it with dev stopped.
- Attach and Voice in the composer are disabled placeholders (no backend yet).
- Windows: `uvicorn --reload` may leave an orphaned worker holding port 8000; restart by hand.
- Retry in chat re-sends the last user message (adds a duplicate user bubble).

- [x] Minimal UI migration (2026-11-12): pushed to `origin/main` (head `c4e94cf`); details in the UI section below.
  Next likely: Step 6/7 above, a manual visual pass of every page in light and dark, reconnect Google for the new scopes.

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

## UI: minimal design (2026-11-12, APPLIED to the whole app; owner approved the /design preview)
- Direction (replaces strict monochrome, glassmorphism and "premium dark"): MINIMAL, layout idea from a reference minimal AI
  chat product (own glyph/name/illustrations). FULL-SCREEN window (owner asked for no outer gap or rounded corners), off-white
  (light) / near-black (dark). No glass, no glow, no blur, no gradients on UI.
- Tokens: `--m-*` CSS variables in `apps/web/app/globals.css`, exposed as Tailwind colours `m-window, m-panel, m-soft, m-soft-2,
  m-line, m-line-strong, m-text, m-muted, m-ink, m-ink-fg, m-accent, m-accent-soft, m-ok, m-warn, m-bad, m-info, m-canvas`.
  Short legacy names (`bg-surface`, `text-muted`, `border-line`, `bg-field`, `text-bad`, `bg-accent` = ink, neutral-*, red-*) are
  mapped onto the same palette in `@theme`, so old classes still render minimal. Class-based dark mode (`<html class="dark">`,
  inline script, no flash); Light/Dark/System saved per user. `npm run contrast` (scripts/contrast-min.mjs) = WCAG AA, keep passing.
- Style rules: hairline borders, soft shadows, 12-16px radii, pill buttons/chips, primary = solid near-black pill (white in dark),
  status = dot + quiet text (no filled badges), Geist 13-14px + Geist Mono for IDs/tool output, Lucide icons, 150ms transitions,
  reduced motion honoured, one soft accent (indigo) used sparingly.
- Shell (`components/shell/`): AppShell (full screen), Sidebar (Home, Connections, Workflows, Runs, Memory, Settings; collapsible
  "AI tools" = modes from `/api/chat/modes`; user card with name, email, Light/Dark/System toggle, Sign out; NO chat list),
  HistoryPanel (separate right panel on /chat only: search, title + preview + time, Options menu -> Rename/Delete dialogs,
  "Create new chat"; hidden by default below lg, toggled by the history icon, choice kept in localStorage `history-open`).
  Sidebar/HistoryPanel/ChatWindow talk via `lib/chatBus.ts` (CHAT_OPEN/NEW/CHANGED/DELETED, CHAT_SET_MODE, CHAT_MODE_IS) and `?c=`/`?mode=`.
- `GET /api/conversations` now also returns `preview` (newest assistant reply, one query). `lib/useUser.ts` gives name/first name/email.
- Chat: glyph + "Welcome, <first name>" + 3 suggestion cards (fill the composer); composer with Attach and Voice (disabled, "not
  available yet": no backend), Mode chip (list + clear), Options (memory switch via /api/memory/settings; model is server-side), "/"
  menu, round ink Send/Stop. Messages: user = soft block, assistant = plain Markdown, tools = slim collapsible ActionCard rows,
  approvals = inline card.
- Connections (owner correction): MINIMAL RECTANGULAR cards with ONLY logo + tool name + one button (Set up / Connect / Manage /
  Reconnect); state is sr-only text. Sorted Connected first, then needs-attention, ready, not set up. Setup stays in the modal.
- Workflows = list rows; canvas = dotted grid (`Background` with `--m-dot`) with slim node cards; Runs = bordered table of expandable rows with
  status dots; Memory and Settings use Card/Field/Button. Shared kit: `components/ui/{Button,Card,Field,Tabs,Modal,Toast,kit,BrandLogo,icons}`.
- Logos: `simple-icons` marks in brand colour on a white tile; Slack and Google Contacts get a neutral monogram.
- Removed: glass/aurora/gradient CSS, `components/min`, `/design` preview, `lib/groupByDate`, old contrast script.
- Known: a few `react-hooks/set-state-in-effect` lint errors exist in data-loading components (pre-existing pattern).
