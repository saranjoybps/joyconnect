-- 0007_workflows.sql — workflows, versions, executions (also the job queue), node records, approvals, triggers.
-- RLS on every table: users may read their own rows; every write goes through FastAPI (service role).

create table public.workflows (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  name text not null,
  status text not null default 'draft' check (status in ('draft', 'published')),
  version integer not null default 1,
  published_version integer,
  definition jsonb not null default '{"nodes": [], "edges": []}',
  settings jsonb not null default '{}',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index workflows_user_idx on public.workflows (user_id, updated_at desc);

create table public.workflow_versions (
  id uuid primary key default gen_random_uuid(),
  workflow_id uuid not null references public.workflows(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  version integer not null,
  name text not null,
  definition jsonb not null,
  settings jsonb not null default '{}',
  created_at timestamptz not null default now(),
  unique (workflow_id, version)
);

create table public.executions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  workflow_id uuid not null references public.workflows(id) on delete cascade,
  workflow_version integer not null,
  mode text not null check (mode in ('manual', 'test_node', 'schedule', 'webhook', 'error', 'sub_workflow', 'chat')),
  status text not null default 'queued'
    check (status in ('queued', 'running', 'waiting', 'success', 'error', 'canceled')),
  trigger_node_id text,
  trigger_data jsonb,
  state jsonb not null default '{}',          -- resumable engine state, saved after every node
  error jsonb,
  response jsonb,                              -- what a webhook caller gets back
  cost_usd numeric not null default 0,
  cost_cap_usd numeric,
  resume_at timestamptz,                       -- a Wait node: claim again at this time
  locked_by text,
  locked_at timestamptz,
  parent_execution_id uuid,
  created_at timestamptz not null default now(),
  started_at timestamptz,
  finished_at timestamptz
);
create index executions_queue_idx on public.executions (status, created_at);
create index executions_user_idx on public.executions (user_id, created_at desc);
create index executions_workflow_idx on public.executions (workflow_id, created_at desc);

create table public.node_executions (
  id uuid primary key default gen_random_uuid(),
  execution_id uuid not null references public.executions(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  workflow_id uuid not null,
  node_id text not null,
  node_name text not null,
  node_type text not null,
  run_index integer not null default 0,
  status text not null check (status in ('success', 'error', 'skipped', 'waiting', 'pinned')),
  input jsonb,
  output jsonb,
  error jsonb,
  attempts integer not null default 1,
  started_at timestamptz,
  finished_at timestamptz,
  duration_ms integer,
  created_at timestamptz not null default now()
);
create index node_executions_execution_idx on public.node_executions (execution_id, created_at);
create index node_executions_node_idx on public.node_executions (workflow_id, node_id, created_at desc);

create table public.execution_approvals (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  execution_id uuid not null references public.executions(id) on delete cascade,
  node_id text not null,
  preview jsonb not null,
  status text not null default 'pending' check (status in ('pending', 'approved', 'rejected', 'expired')),
  created_at timestamptz not null default now(),
  decided_at timestamptz
);
create index execution_approvals_user_idx on public.execution_approvals (user_id, status);

create table public.triggers (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  workflow_id uuid not null references public.workflows(id) on delete cascade,
  node_id text not null,
  type text not null check (type in ('schedule', 'webhook')),
  config jsonb not null default '{}',
  path text unique,                            -- webhook: random, unguessable
  secret_id text,                              -- webhook header-auth value, in the SecretStore
  active boolean not null default true,
  next_run_at timestamptz,                     -- schedule
  last_run_at timestamptz,
  created_at timestamptz not null default now(),
  unique (workflow_id, node_id)
);
create index triggers_due_idx on public.triggers (type, active, next_run_at);

-- Chat sessions remember their mode and tool scope (used by chat modes).
alter table public.conversations
  add column mode text not null default 'custom',
  add column tool_scope text;

-- RLS: read own rows, nothing else for clients.
alter table public.workflows enable row level security;
alter table public.workflow_versions enable row level security;
alter table public.executions enable row level security;
alter table public.node_executions enable row level security;
alter table public.execution_approvals enable row level security;
alter table public.triggers enable row level security;

create policy workflows_select on public.workflows for select using (user_id = auth.uid());
create policy workflow_versions_select on public.workflow_versions for select using (user_id = auth.uid());
create policy executions_select on public.executions for select using (user_id = auth.uid());
create policy node_executions_select on public.node_executions for select using (user_id = auth.uid());
create policy execution_approvals_select on public.execution_approvals for select using (user_id = auth.uid());
-- triggers hold webhook paths and secret pointers: no client policy at all.

revoke insert, update, delete on public.workflows, public.workflow_versions, public.executions,
  public.node_executions, public.execution_approvals from anon, authenticated;
revoke all on public.triggers from anon, authenticated;

-- Queue claim: one worker gets each job (FOR UPDATE SKIP LOCKED). Also picks up Wait nodes that are due and
-- reclaims jobs whose worker died (lock older than the lease).
create or replace function public.claim_next_execution(p_worker text, p_lease_seconds integer default 300)
returns setof public.executions
language plpgsql
security definer
set search_path = public
as $$
declare
  r public.executions;
begin
  select * into r from public.executions
   where status = 'queued'
      or (status = 'waiting' and resume_at is not null and resume_at <= now())
      or (status = 'running' and locked_at < now() - make_interval(secs => p_lease_seconds))
   order by created_at
   for update skip locked
   limit 1;
  if not found then
    return;
  end if;
  update public.executions
     set status = 'running', locked_by = p_worker, locked_at = now(), resume_at = null,
         started_at = coalesce(started_at, now())
   where id = r.id
   returning * into r;
  return next r;
end;
$$;
revoke all on function public.claim_next_execution(text, integer) from public, anon, authenticated;
grant execute on function public.claim_next_execution(text, integer) to service_role;
