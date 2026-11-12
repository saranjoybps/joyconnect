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

## How to test workflows

**Once, before you start**
1. Apply the migrations (the workflow tables and the chat-mode columns are in `0006` and `0007`):
   `cd apps/api && .venv/Scripts/python scripts/apply_migrations.py` (needs `SUPABASE_DB_URL` in `.env`), or paste
   `supabase/migrations/0006_*.sql` then `0007_workflows.sql` into the Supabase SQL editor.
2. Start three things, each in its own terminal (commands at the end of this section): the **API**, the **worker**
   (it runs queued workflows and fires schedules; without it "Run workflow" stays *queued*), and the **web app**.
3. Open http://localhost:3000 and sign in.

**A. Build and run a workflow by hand**
1. Top nav → **Workflows**. Type `Hello` in the name box → **New workflow**. The canvas opens.
2. In the palette (left), click **Manual Trigger**, then click **Edit Fields (Set)**. Two nodes appear.
   (You can also drag a palette item onto the canvas.)
3. Drag from the small dot on the right of *Manual Trigger* to the dot on the left of *Edit Fields (Set)*. A line connects them.
4. Click the *Edit Fields (Set)* node. In the panel on the right find the **fields** box and paste:
   `[{"name":"greeting","value":"Hello"},{"name":"sum","value":"{{ 1 + 2 }}","type":"number"}]`
   then click outside the box. The header says *Saving…* and then *Saved · v…* each time a change is stored.
5. Press **Test node**. The panel shows the real output: `greeting: "Hello"`, `sum: 3`. A node that changes data in
   an app (for example Slack: Post message) first asks you to confirm.
6. Press **Run workflow** (top right). The strip at the bottom lists every node with its status and duration.
   A node that needs approval shows **Approve / Reject** there.
7. Select a node and press <kbd>Delete</kbd>, or select a line and press <kbd>Delete</kbd>, to remove it.

**B. Schedule**
1. In the same workflow click **Schedule Trigger** in the palette, then connect it to *Edit Fields (Set)*.
2. Select it. Under *Rule 1* choose **minutes**, every **1**. (The shortest allowed interval is 10 seconds.)
3. Click the **Draft** switch in the top bar. It turns to **Published**. Select the Schedule node: it shows *Next run*.
4. Keep the worker running. Within a minute **Runs** (or `GET /api/executions`) shows a run with mode `schedule`.
5. Switch back to **Draft** to stop it. Edits made after publishing are *not* live until you press **Publish changes**.

**C. Webhook**
1. Click **Webhook** in the palette and connect it to *Edit Fields (Set)*. Set **authentication** to `header`.
2. Click the **Draft** switch. A dialog shows the webhook secret **once**: copy it.
3. Select the Webhook node: it shows the production URL (`http://localhost:8000/api/hooks/<random>`).
4. `curl -X POST <url> -H "X-Webhook-Secret: <secret>" -H "Content-Type: application/json" -d '{"name":"Ada"}'`
   answers `{"message":"Workflow was started"}`; without the header it answers 401. For a URL reachable from the
   internet run `scripts/dev-tunnel.ps1` and set `PUBLIC_API_BASE_URL` to the tunnel address.

**D. Chat modes**
1. Top nav → **Chat**. The chip above the input says **Mode: /custom**.
2. Type `/`. A menu lists `/custom`, `/workflow` and one command per connected app (for example `/google-docs`,
   `/trello`). <kbd>↓</kbd>/<kbd>↑</kbd> move, <kbd>Enter</kbd> picks, <kbd>Esc</kbd> closes.
3. Pick `/trello` (or any connected app). The chip changes; from now on the assistant only gets that app's tools, and
   the server refuses any other tool even if the model asks for it. Click the **×** on the chip to go back to `/custom`.

**Restart the servers** (stop the old ones first; on Windows `--reload` can leave an orphaned process on port 8000)
```powershell
cd C:\connect\joyconnect\apps\api ; .\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
cd C:\connect\joyconnect\apps\api ; .\.venv\Scripts\python.exe -m app.worker
cd C:\connect\joyconnect\apps\web ; npm run dev
```

## Chat agent (Phase 2)

- Set `OPENAI_API_KEY` (and optionally `OPENAI_MODEL`, default `gpt-4o-mini`) in the root `.env`.
- `POST /api/chat` streams Server-Sent Events: `token`, `tool_call`, `approval_required`, `tool_result`,
  `error`, `done` (plus `mode` when the chat mode changes). `POST /api/chat` accepts `mode`: `custom`, `workflow` or a
  connector command; `GET /api/chat/modes` lists them. `POST /api/approvals/{id}/decision {"approve": bool}` resumes with the same events.
- Policy: read tools run immediately; write tools ask unless the connection has *Auto-approve writes*;
  destructive tools always ask. Every call is audited in `tool_runs` (arguments redacted).

## Local OAuth setup

Two URLs, two jobs:

| Variable | Used for | Default |
|---|---|---|
| `API_BASE_URL` | the browser calling the API (chat, **SSE**, connections) | `http://localhost:8000` |
| `PUBLIC_API_BASE_URL` | the redirect URIs providers send users back to | `API_BASE_URL` |

Every redirect URI (shown in the Set up panel, sent to `/authorize`, used for the token exchange) is
`{PUBLIC_API_BASE_URL}/api/oauth/callback/{family}`; the web app never builds one itself.

**What each provider accepts (checked against their docs):**

| Provider | `http://localhost` redirect | Local setup |
|---|---|---|
| Google (Sheets, Docs, Calendar) | Yes (Google's redirect URI rules exempt localhost) | localhost |
| Slack | **No**: "A Redirect URL must also use HTTPS" | tunnel |
| Notion | Not stated in Notion's docs (third-party guides say it works) | try localhost, tunnel if rejected |
| GitHub App | Not stated in GitHub's docs (its tutorials use localhost) | try localhost, tunnel if rejected |
| Meta (Phase 4) | HTTPS enforced by default; a localhost exemption in dev mode is only documented in a 2018 announcement | tunnel |

**Localhost (default).** Nothing to do. Register `http://localhost:8000/api/oauth/callback/google` (and the
`github` / `notion` ones) in the provider console.

**Quick tunnel (optional, off by default).** Install `cloudflared` yourself (`brew install cloudflared`,
`winget install --id Cloudflare.cloudflared`, or https://pkg.cloudflare.com/ on Linux; the script never
installs anything), then in a separate terminal:

```
scripts/dev-tunnel.sh          # Windows: .\scripts\dev-tunnel.ps1
```

It runs `cloudflared tunnel --url http://localhost:8000`, finds the `https://<random>.trycloudflare.com` URL,
writes `PUBLIC_API_BASE_URL=...` to `apps/api/.env.local` (git-ignored; restart the API unless it runs with
`--reload`), prints the redirect URIs to register, and removes the line again when you press Ctrl+C. The URL
changes on every run, so after restarting it update the redirect URI in each provider console. The Set up
panel shows an amber banner ("redirect URI changed") until you click "I've updated it".

**Named tunnel (stable hostname).** Once: `cloudflared tunnel login`, `cloudflared tunnel create connect-dev`,
`cloudflared tunnel route dns connect-dev api.example.com`, and point it at `http://localhost:8000` in
`~/.cloudflared/config.yml`. Then:

```
TUNNEL_HOSTNAME=api.example.com TUNNEL_NAME=connect-dev scripts/dev-tunnel.sh
```

This runs `cloudflared tunnel run connect-dev` and sets `PUBLIC_API_BASE_URL=https://api.example.com`.

**SSE note.** Quick tunnels do not support Server-Sent Events, so only the OAuth callback goes through the
tunnel. The browser keeps calling `http://localhost:8000` for chat (`NEXT_PUBLIC_API_BASE_URL`); after the
callback the API redirects the browser back to `WEB_BASE_URL` (localhost), so nothing else changes.

## Troubleshooting: "insufficient authentication scopes" (Google)

Google's consent screen has one checkbox per permission, and the user can leave one **unticked** while
still pressing Continue. Google then returns a token without that permission, and the Google API answers
403 "Request had insufficient authentication scopes". The app stores exactly the scopes Google returned
(shown under "Granted permissions" on the card). If one the connector needs is missing the card shows
**Partial access**, and chat answers "Reconnect Google Sheets and tick the Sheets permission" instead of a
raw 403. To fix it: click **Reconnect** on that card and tick every permission box on Google's screen.
If the box is not offered at all, add the scope under Google Auth Platform → Data access and make sure
the matching API is enabled. If Google keeps skipping it, remove the app at
https://myaccount.google.com/permissions and connect again.

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

Redirect URI pattern (one per provider family, built from `PUBLIC_API_BASE_URL`):
**`{PUBLIC_API_BASE_URL}/api/oauth/callback/{family}`** with family `google`, `slack`, `notion`, `github`
(later `meta`). The Set up panel shows the exact URI for your setup. See "Local OAuth setup" below for
localhost vs the HTTPS tunnel.

### Google (one app for every Google connector)
1. https://console.cloud.google.com → create a project → APIs & Services → Library → enable the API for each
   connector you use (table below).
2. Google Auth Platform → Audience: External; add yourself under **Test users**.
3. Data access → add `openid`, `.../auth/userinfo.email` and the scopes in the table (all prefixed
   `https://www.googleapis.com/auth/`). Nothing here is a restricted scope.
4. Clients → Create client → **Web application** → one Authorized redirect URI shared by all Google cards:
   `http://localhost:8000/api/oauth/callback/google`.
5. Paste the client ID (`…apps.googleusercontent.com`) and secret (`GOCSPX-…`) into any Google card's Set up.

| Connector | API to enable | Scopes to add under Data access |
| --- | --- | --- |
| Google Sheets | Google Sheets API | `spreadsheets` |
| Google Docs | Google Docs API | `documents` |
| Google Calendar | Google Calendar API | `calendar.events`, `calendar.calendarlist.readonly`, `calendar.freebusy` |
| Gmail | Gmail API | `gmail.send`, `gmail.labels` |
| Google Drive | Google Drive API | `drive.file` |
| Google Slides | Google Slides API | `presentations` |
| Google Forms | Google Forms API | `forms.body`, `forms.responses.readonly` |
| Google Tasks | Google Tasks API | `tasks` |
| Google Contacts | People API | `contacts` |
| Google Meet | Google Meet REST API | `meetings.space.created` |

Gmail has no "create draft" tool: drafts need `gmail.compose`, which Google classifies as restricted. Each
card's Set up form shows its own API and scopes. On the consent screen tick every permission, otherwise the
card shows "Partial access".

### Slack
1. https://api.slack.com/apps → Create New App → From scratch → pick your workspace.
2. OAuth & Permissions → Redirect URLs: `{PUBLIC_API_BASE_URL}/api/oauth/callback/slack`. Slack requires
   HTTPS, so for local use start the tunnel (`scripts/dev-tunnel.sh`) and register the HTTPS URI it prints.
3. Bot Token Scopes: `chat:write`, `channels:read`. Leave token rotation off.
   After connecting, `/invite @YourApp` in each channel the bot should post in (it must be a member).
4. Basic Information → App Credentials → paste Client ID and Client Secret into Slack's Set up.

### Notion
1. https://www.notion.so/profile/integrations → New integration → type **Public**.
2. Redirect URI: `http://localhost:8000/api/oauth/callback/notion` (use the tunnel URI if Notion rejects localhost). Capabilities: Read, Insert, Update content.
3. Paste the OAuth client ID and secret into Notion's Set up. When connecting, pick the pages to share.

### GitHub (a GitHub App, not an OAuth App)
1. GitHub → Settings → Developer settings → GitHub Apps → New GitHub App.
2. Callback URL: `http://localhost:8000/api/oauth/callback/github` (use the tunnel URI if GitHub rejects localhost). Tick **Expire user authorization
   tokens**; leave "Request user authorization during installation" off; Webhook inactive.
3. Repository permissions: Issues **Read & write** (Metadata read-only is automatic). Nothing else is needed.
4. Generate a client secret. In GitHub's Set up paste the **Client ID** (starts with `Iv`, not the App ID),
   the secret, and the app slug (from `github.com/apps/<slug>`).
5. After connecting, use **Choose repositories** on the card to install the app on repos.

### Token-based connectors (Airtable, Trello, Linear, Asana, Stripe)
No OAuth app and no env vars: open the card, paste the credential, Save, Test, Connect.

| Connector | Credential | Permissions to grant |
| --- | --- | --- |
| Airtable | Personal access token (builder hub) | `schema.bases:read`, `data.records:read`, `data.records:write`, plus the bases to use |
| Trello | API key + token (Power-Up admin) | token with read and write |
| Linear | Personal API key (Settings > Security & access) | key (sent without a Bearer prefix) |
| Asana | Personal access token (Developer apps) | token |
| Stripe | Restricted key `rk_...` | Read on Balance, Customers, Invoices only (read-only tools; use test mode first) |

These providers do not tell us what a token may do, so there is no "Partial access" badge for them: a
permission problem shows up as the provider's 401/403 message in the chat.

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
