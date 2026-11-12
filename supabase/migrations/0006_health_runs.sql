-- Connector health checks, run history, per-user daily usage (counted from existing tables).
alter table public.connections
  add column if not exists last_checked_at timestamptz,
  add column if not exists last_check_ok boolean,
  add column if not exists last_check_message text;

alter table public.tool_runs
  add column if not exists connector text,
  add column if not exists risk text,
  add column if not exists duration_ms integer,
  add column if not exists result_redacted jsonb,
  add column if not exists finished_at timestamptz;

create index if not exists tool_runs_user_created_idx on public.tool_runs (user_id, created_at desc);
create index if not exists messages_user_role_created_idx on public.messages (user_id, role, created_at desc);
