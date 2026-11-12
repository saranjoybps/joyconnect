Read MEMORY.md first at the start of every session and update it before finishing.

# CLAUDE.md — Chat-first workflow platform

## 1. Product

Users connect their apps once, then work in two ways that edit the same thing:

- **Chat**: ask in plain language. The agent acts directly on connected apps, or builds and edits workflows.
- **Canvas**: drag and drop nodes (modeled on n8n) and edit the same workflow by hand.

Every connector becomes a set of workflow nodes. A workflow is one JSON document; chat, canvas and API all edit it
through one patch API.

## 2. Working rules (the only ones)

1. **Never use my OpenAI API key (or any paid API) for testing, debugging or verification** unless I send the exact
   text "yes use the openai key for testing" in the chat.
   - Without that exact text: mock or stub the LLM in every test (`FakeLLM` in `apps/api/tests/test_agent.py`) and do
     not run any flow that triggers a real OpenAI call.
   - If a real call seems necessary: stop, explain why, estimate the cost, and wait for that exact text.
   - My approval covers only the one task I gave it in. Ask again next time.
   - Never read or print the key.
2. **Build connectors and nodes from official docs.** Fetch the docs first and confirm auth flow, scope names,
   endpoints, shapes, limits, errors. For n8n-modeled nodes, read n8n's docs. If docs are unclear or a scope is
   restricted, stop and tell me. Where docs and this file disagree, docs win; note it in `docs/decisions.md`.
3. **Never print or commit secrets.** Do not read `.env` values into output. Never log tokens, codes, secrets or raw
   tool arguments.

Housekeeping that follows from these: tests mock all HTTP and the LLM; run all tests before each commit.

## 3. Stack (fixed)

| Layer | Choice |
| --- | --- |
| Frontend | Next.js (App Router), TypeScript, Tailwind CSS; canvas with React Flow (`@xyflow/react`) |
| Backend | FastAPI (Python 3.11+), httpx, pydantic v2 |
| Database / Auth | Supabase (Postgres, Auth, RLS) |
| LLM | OpenAI `gpt-4o-mini` via tool calling; model name from env `OPENAI_MODEL`, never hard-coded |
| Tool protocol | MCP (`FastMCP`), in-process |
| Tests | pytest + respx (API), Vitest (web) |

## 4. Kept foundations

### Connector manifest (one file per app in `apps/api/app/connectors/`)
Adding an app = one manifest module exposing `MANIFEST` (id, name, auth_type, scopes, `credential_fields`, tools with
JSON-schema parameters and a `risk` of read | write | destructive). Never add per-app code in routers, the engine, the
agent or the UI. Tool parameters are OpenAI-strict schemas (closed objects, every property required, `null` for
optional).

### Dynamic credentials
Provider app credentials (client id/secret, API keys, connection strings) are entered by each user in the UI
(Connections → Set up → Save → Test → Connect) and stored encrypted in `provider_apps`. Env holds only server keys;
`PLATFORM_<APP>_<FIELD>` env defaults are an optional fallback. Redirect URIs are one per provider family:
`{PUBLIC_API_BASE_URL}/api/oauth/callback/{family}`. The browser never sees a provider token; only FastAPI uses the
Supabase service role key.

### Granted-scope checks and "Partial access"
Store exactly the scopes the provider returned. A connector is *Partial access* when a scope it needs was not granted.
A tool whose connection lacks a scope never calls the provider and never asks for approval; it says
"Reconnect X and tick the Y permission". Token-based connectors cannot report scopes (no badge there).

### SecretStore
`put / get / delete`; AES-GCM (`TOKEN_ENCRYPTION_KEY`) or Supabase Vault, chosen by `SECRET_STORE`. Tokens refresh on
demand 60 s before expiry; `invalid_grant` sets `needs_reauth`. Disconnect revokes at the provider, deletes the secret.

### RLS on every table
Users read only their own rows (`user_id = auth.uid()`). All writes go through FastAPI with the service role. Any
table holding secrets has no client policies. New tables ship with RLS and a test.

### Risk policy (enforced in our code, never by the model or MCP hints)
| Risk | Behavior |
| --- | --- |
| read | runs immediately |
| write | asks for approval unless auto-approve applies |
| destructive | always asks (chat); in workflows only skipped by `auto_approve = "all"` |

## 5. Architecture

```
Browser (Next.js: chat + React Flow canvas)  <->  FastAPI  <->  Supabase (Postgres, Auth, RLS)
                                                    |  \
                                                    |   `-> OpenAI (chat agent, AI nodes)
                                                    `-> Connected apps
Worker (python -m app.worker)  <-- Postgres queue (SKIP LOCKED) -->  FastAPI enqueues
```

### 5.1 Workflow JSON (single source of truth)
```
{ id, name, status: draft|published, version,
  nodes: [{ id, type, name, parameters, position:{x,y}, connection_id, settings?, pinned_data?, disabled? }],
  edges: [{ from, to, output, input? }],
  settings: { auto_approve: off|writes|all, error_workflow_id, timeout_seconds, cost_cap_usd } }
```
- Validated by one shared JSON Schema, `schemas/workflow.schema.json`, loaded by the API (jsonschema) and the web app.
  Structural rules the schema cannot express (unique ids and names, edges point at real nodes and valid outputs) are
  enforced by the API after every patch.
- Node `name` is unique per workflow (expressions reference it). `connection_id` selects which connected account an app
  node uses, so several accounts of one app work.
- `edge.output` is the source output (`main`, `true`, `false`, `loop`, `done`, `case_0`, ...); `edge.input` is the
  target input (`main`, or `input1` / `input2` for Merge).

### 5.2 One patch API
`POST /api/workflows/{id}/patch {base_version, operations[]}` with operations `add_node, update_node, remove_node,
connect, disconnect, rename, move` (plus `set_settings`). Chat, canvas and API all use it.
- Optimistic concurrency: `base_version` must equal the stored version or the call is `409` with the latest workflow.
  The write is a compare-and-swap on `version`, so two editors never overwrite each other.
- All operations apply atomically or not at all. Each successful patch bumps `version` and stores a snapshot in
  `workflow_versions`.
- Removing a node from a *published* workflow is destructive (chat must get approval).
- `publish` snapshots a version to run unattended; schedule/webhook triggers run the published snapshot only.

### 5.3 Nodes
Modeled on n8n. Registry in `apps/api/app/workflows/registry.py`; the palette and config panels are generated from it.
- Triggers: manual, schedule, webhook, error trigger.
- Flow: IF, Switch, Merge, Loop Over Items, Wait, Filter, Stop and Error, Sub-workflow.
- Data: Set (edit fields), Aggregate, Split Out, Sort, Limit, HTTP Request, Respond to Webhook.
- AI (later): AI Agent, LLM prompt, Classify, Extract. Human: Approval.
- App nodes: auto-generated, one per connector tool; the node `type` is the tool name (`google_sheets__append_row`),
  parameters come from the tool schema, risk from the tool.
- Data between nodes is a list of items (`{json: {...}}`).

### 5.4 Expressions
`{{ $json.field }}`, `{{ $node["Name"].json.field }}` (also `$("Name").item.json.x`, `.first()`, `.last()`, `.all()`,
`$input`, `$itemIndex`, `$now`, `$execution`). Evaluated by our own tokenizer and parser, never `eval`, with a whitelist
of operators and string/number/array methods. No access to attributes starting with `_`, no imports, no calls to
anything outside the whitelist. A string that is exactly one `{{ }}` keeps the value's type.

### 5.5 Execution engine
- Separate worker process; queue is the `executions` table claimed with `FOR UPDATE SKIP LOCKED` (RPC
  `claim_next_execution`); stale locks are reclaimed.
- Execution state is serialisable and saved after every node, so runs can pause (approval, wait) and resume.
- Per-node records in `node_executions` (input, output, status, duration, attempts). Per-node `settings`: timeout,
  retry (read-risk and non-app nodes only; write/destructive never retry on their own), on_error stop | continue.
- Error workflow: on a failed run, the workflow named in `settings.error_workflow_id` runs with the error payload.
- "Test this node", "run from here" (reuses stored upstream outputs or pinned data), pinned test data.
- Unattended runs (schedule, webhook, error): write nodes pause at an approval unless `auto_approve` covers them;
  destructive nodes pause unless `auto_approve = "all"`. Per-run cost cap and a node-run cap stop runaway runs.

### 5.6 AI Agent node
Model, prompt, allowed tools (chosen connectors), optional memory, max steps, optional output schema, cost cap. Same
risk rules as everything else.

### 5.7 Chat modes
- `/custom` (default): general conversation with all connected integrations.
- `/workflow`: builder mode; the agent only plans and edits workflows; edits are shown as a diff to accept or reject.
- `/<connector>` (e.g. `/google-docs`, `/sheets`, `/trello`): scoped mode; the backend passes ONLY that connector's tools
  to the agent. Scope is enforced server-side when tools are built and again when a call is dispatched, not in the
  prompt.
- Typing `/` opens an autocomplete menu; the active mode is a chip above the input; the session stores `mode` and
  `tool_scope`.
- Workflow tools for the agent: `create_workflow, get_workflow, list_workflows, update_workflow` (patch operations),
  `run_workflow, delete_workflow`. `delete_workflow` and deleting nodes of a published workflow are destructive and
  always need approval; the UI delete button also confirms.
- Autonomy: plan, run up to a step limit, ask approval only for write/destructive actions, ask a clarifying question
  when a required detail is missing, summarize what was done. Final replies are short Markdown plus a validated
  action list built from the audited tool results (`app/agent/response.py`).

### 5.8 Data model (all RLS)
`connections`, `provider_apps`, `secrets`, `conversations` (+ `mode`, `tool_scope`), `messages`, `tool_runs`,
`approvals` (chat) plus: `workflows`, `workflow_versions`, `executions` (also the queue), `node_executions`,
`execution_approvals`, `triggers`.

### 5.9 Frontend
React Flow canvas with a drag-and-drop palette generated from the node registry, per-node config panel,
add/remove/connect/delete, data preview from test runs, workflows list page, Runs page grouped by workflow and node.
The workflow generated by chat opens on the canvas as a draft.

## 6. Repo layout
```
apps/api/app/{core,db,oauth,connectors,agent,workflows,routers,mcp}   apps/api/app/worker.py
apps/web/{app,components,lib}     schemas/workflow.schema.json     supabase/migrations/   docs/
```

## 7. Commands
```
cd apps/api && .venv/Scripts/python -m uvicorn app.main:app --port 8000     # API (restart by hand after changes)
cd apps/api && .venv/Scripts/python -m app.worker                            # execution worker + scheduler
cd apps/web && npm run dev                                                   # http://localhost:3000
cd apps/api && .venv/Scripts/python -m pytest -q     cd apps/web && npx vitest run && npm run typecheck
cd apps/api && .venv/Scripts/python scripts/apply_migrations.py              # needs SUPABASE_DB_URL
```
