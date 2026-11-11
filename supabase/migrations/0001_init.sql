-- 0001_init.sql — core schema. RLS on every table. All writes go through
-- FastAPI with the service role; clients may only read their own rows.

create extension if not exists pgcrypto;

-- ---------------------------------------------------------------- tables

create table public.connections (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  provider text not null,                       -- connector id, e.g. 'google_sheets'
  status text not null default 'active'
    check (status in ('active', 'needs_reauth', 'revoked')),
  account_label text,                           -- e.g. email or workspace name
  scopes text[] not null default '{}',
  secret_id text not null,                      -- pointer to encrypted token blob
  expires_at timestamptz,
  auto_approve_writes boolean not null default false,
  created_at timestamptz not null default now(),
  unique (user_id, provider, account_label)
);
create index connections_user_idx on public.connections (user_id);

create table public.oauth_states (
  state text primary key,
  user_id uuid not null,
  provider text not null,
  code_verifier text,
  created_at timestamptz not null default now()
);                                              -- deleted after callback or after 10 minutes

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
  role text not null check (role in ('user', 'assistant', 'tool', 'system')),
  content text,
  tool_calls jsonb,
  tool_call_id text,
  created_at timestamptz not null default now()
);
create index messages_conversation_idx on public.messages (conversation_id, created_at);

create table public.tool_runs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null,
  conversation_id uuid,
  connection_id uuid,
  tool text not null,
  args_redacted jsonb,
  status text not null check (status in ('pending', 'approved', 'rejected', 'ok', 'error')),
  result_summary text,
  created_at timestamptz not null default now()
);

create table public.approvals (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null,
  tool_run_id uuid not null references public.tool_runs(id) on delete cascade,
  preview jsonb not null,
  status text not null default 'pending'
    check (status in ('pending', 'approved', 'rejected', 'expired')),
  decided_at timestamptz
);

-- Encrypted token blobs for AesGcmSecretStore. No client policies at all.
create table public.secrets (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  nonce text not null,                          -- base64
  ciphertext text not null,                     -- base64 (AES-256-GCM, includes tag)
  created_at timestamptz not null default now()
);

-- ---------------------------------------------------------------- RLS

alter table public.connections   enable row level security;
alter table public.oauth_states  enable row level security;
alter table public.conversations enable row level security;
alter table public.messages      enable row level security;
alter table public.tool_runs     enable row level security;
alter table public.approvals     enable row level security;
alter table public.secrets       enable row level security;

-- Clients never write: strip default write privileges from client roles.
revoke insert, update, delete, truncate on
  public.connections, public.oauth_states, public.conversations, public.messages,
  public.tool_runs, public.approvals, public.secrets
from anon, authenticated;

-- Clients never touch secrets or OAuth state (state rows hold PKCE verifiers).
revoke all on public.secrets, public.oauth_states from anon, authenticated;

create policy "own rows" on public.conversations for select to authenticated
  using (user_id = (select auth.uid()));
create policy "own rows" on public.messages for select to authenticated
  using (user_id = (select auth.uid()));
create policy "own rows" on public.tool_runs for select to authenticated
  using (user_id = (select auth.uid()));
create policy "own rows" on public.approvals for select to authenticated
  using (user_id = (select auth.uid()));
create policy "own rows" on public.connections for select to authenticated
  using (user_id = (select auth.uid()));

-- connections: clients read through a view without secret_id. Column-level
-- grants make sure secret_id cannot be read from the base table either.
revoke select on public.connections from anon, authenticated;
grant select (id, user_id, provider, status, account_label, scopes, expires_at,
              auto_approve_writes, created_at)
  on public.connections to authenticated;

create view public.connections_public
with (security_invoker = true) as
  select id, user_id, provider, status, account_label, scopes, expires_at,
         auto_approve_writes, created_at
  from public.connections;

revoke all on public.connections_public from anon;
grant select on public.connections_public to authenticated;
