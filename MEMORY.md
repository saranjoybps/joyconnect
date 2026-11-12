# MEMORY.md — project context for future sessions

Keep under 150 lines. Update before finishing every session (state, decisions, issues, next steps).
Last updated: 2026-11-12, after the glassmorphism redesign.

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
  parallel read calls. All tests use mocked LLM/embedder. **Migration 0008 must be applied by the owner**
  (`cd apps/api; .venv\Scripts\python.exe scripts\apply_migrations.py`); until then memory/usage degrade silently.
  Existing Google connections show Partial access until reconnected (new scope); Slack needs `users:read`.
- [x] Load options (2026-11-12): connector `loaders` + `param_ui` (x-ui), `POST /api/nodes/{type}/options` (60 s cache, refresh),
  canvas: account, Resource, Operation, then dropdown / resource locator (list, URL, ID) / multi-select / tab range / column mapper;
  parent change clears children (`remove_parameters`), operation switch (`update_node.type`). Loaders wrap the same handlers as the chat
  discovery tools. No loaders for Stripe, Meet, Contacts. Tests: api 619, web 141, all mocked.
- [ ] Step 6 chat workflow tools + diff review + delete approval · Step 7 AI Agent / LLM / Classify / Extract / Approval nodes.
  Not done from the plan: Runs page grouped by workflow/node (CLAUDE.md 5.9), chat-generated workflow opening on the canvas (step 6).

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

## UI redesign (2026-11-12)
- DESIGN DIRECTION (changed 2026-11-12, replaces the earlier strict black-and-white style): colourful GLASSMORPHISM,
  light (soft white / pale lavender-blue) and dark (deep navy / violet). Tokens are CSS variables in
  `apps/web/app/globals.css`: text, border, surface, field, glass (`--glass-*`), shadow, gradient
  (indigo -> violet -> cyan-700), status (emerald / amber / rose / sky = `ok / warn / bad / info`). Class-based dark
  mode (`<html class="dark">`, inline init script, no flash); Light / Dark / System saved per user (`theme:<userId>`).
- Glass rules: `.glass` (blur 18px) for sidebar, cards, composer, popovers; `.glass-strong` (blur 24px) for modals,
  drawers, toasts; `.glass-lite` (NO blur) for canvas nodes, palette, config drawer, toolbars so panning stays smooth.
  `@supports not (backdrop-filter)` falls back to a solid `--glass-solid`. Do not stack blur layers; no blur over the canvas.
- Aurora background = one fixed `body::before` layer, animated slowly, off under prefers-reduced-motion.
- Contrast: `npm run contrast` (apps/web/scripts/contrast.mjs) checks token pairs against WCAG AA over the worst aurora
  blob in both themes; keep it passing when changing tokens. Gradient button/bubbles use white text on stops that pass.
- Legacy `neutral-*`, `red-*`, `blue-*` Tailwind colours are retinted in globals.css (@theme) so older components follow.
- Components in `apps/web/components/ui/` (Button with gradient primary, Field, Card/Badge/Skeleton/EmptyState/PageHeader,
  Tabs, Modal (focus trap, `alert` = alertdialog), Toast, icons, BrandLogo). Use these, not ad-hoc classes.
- App shell `components/shell/` (collapsible sidebar, chat history grouped by date, search, rename/delete, theme
  toggle, user menu, mobile drawer). Sidebar and ChatWindow talk through `lib/chatBus.ts` events and `?c=<id>`.
- Chat: stop button (AbortController), tool timeline cards (input/output/duration), memory event ("Memory used" ->
  /memory), regenerate and edit-and-resend via `POST /api/conversations/{id}/rewind {user_index}`, rename via
  `PATCH /api/conversations/{id}`. SSE `tool_call.input`, `tool_result.output/duration_ms`, new `memory` event.
- Connections: card grid + category filters + 4-step modal (`components/connections/ConnectModal.tsx`).
- Logos: `simple-icons` marks in official brand colour on a small white glass tile (dark marks stay visible in dark mode);
  Slack and Google Contacts are not in the package, so they use a gradient monogram (no recreated logo).
- New `/settings` page; every module (shell, chat, Connections, Workflows list/canvas, Runs, Memory, Settings, Login) uses the glass style.
- Tests: API 621+ passed; web 168 passed; `next build` passes.

## Design direction v3 (2026-11-12, IN REVIEW: preview built, waiting for owner approval)
- The owner found the glassmorphism UI "childish". New direction: premium, restrained, calm, technical (Linear / Vercel /
  Raycast / Perplexity / Claude). Dark primary (#0A0A0F base, layered surfaces, 1px hairlines at 6-10% white), light =
  warm off-white. ONE indigo-violet accent, desaturated status colours, no big gradients/rainbow. Radii 8-12px, 32-36px
  buttons, 13-14px text, Geist + Geist Mono, Lucide icons (16-18px). Glass ONLY on floating layers (modal, popover,
  command palette, composer), with a solid fallback. Motion 120-200ms, honour prefers-reduced-motion.
- AI-native: streaming cursor, thinking shimmer, agent activity timeline, tool/source chips, status bar (mode, model,
  memory), Cmd/Ctrl+K palette, shortcut hints. Canvas: dotted grid, slim nodes with logo tile, animated flow while running.
- Tokens are namespaced `--p-*` / `p-*` Tailwind colours in `globals.css`; components live in `apps/web/components/pro/`.
  Preview route `/design` (dev only, 404 in production). `npm run contrast` also runs `scripts/contrast-pro.mjs`.
- NOT yet applied to the app: the glass UI of the previous section is still what the modules use. After approval: migrate
  every module to `components/pro/*`, drop the old glass tokens/aurora, keep behaviour and tests unchanged.
