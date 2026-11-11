-- 0004_provider_apps.sql — user-entered provider app credentials.
-- One row per (user, credential group), e.g. 'google' is shared by Sheets/Docs/Calendar.
-- Secret fields (client secret, API key, connection string) are encrypted through the
-- SecretStore; `secret_id` points at that blob. Clients never read this table's
-- credential columns; FastAPI returns a masked client_id only.

create table public.provider_apps (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  provider text not null,                       -- credential group, e.g. 'google', 'slack'
  client_id text,                               -- primary non-secret identifier (may be null)
  secret_id text,                               -- SecretStore pointer to {field: value} secrets
  extra jsonb not null default '{}',            -- other non-secret fields (e.g. GitHub app slug)
  created_at timestamptz not null default now(),
  unique (user_id, provider)
);

alter table public.provider_apps enable row level security;

revoke all on public.provider_apps from anon, authenticated;
grant select (id, user_id, provider, created_at) on public.provider_apps to authenticated;
create policy "own rows" on public.provider_apps for select to authenticated
  using (user_id = (select auth.uid()));

-- Which app a connection was made with: refresh and revoke must use the same app.
-- Null means the platform default app from server env.
alter table public.connections
  add column provider_app_id uuid references public.provider_apps(id) on delete set null;
grant select (provider_app_id) on public.connections to authenticated;

create or replace view public.connections_public
with (security_invoker = true) as
  select id, user_id, provider, status, account_label, scopes, expires_at,
         auto_approve_writes, created_at, provider_app_id
  from public.connections;
