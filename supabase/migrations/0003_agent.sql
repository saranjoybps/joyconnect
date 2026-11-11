-- 0003_agent.sql — ordering and lookups for the agent runtime.

-- Deterministic message order (created_at can tie).
alter table public.messages add column seq bigint generated always as identity;
create index messages_conversation_seq_idx on public.messages (conversation_id, seq);

create index conversations_user_idx on public.conversations (user_id, created_at desc);
create index tool_runs_user_idx on public.tool_runs (user_id, created_at desc);
create index approvals_user_status_idx on public.approvals (user_id, status);
alter table public.approvals add column created_at timestamptz not null default now();

-- New columns inherit table grants; keep clients read-only.
revoke insert, update, delete on public.messages, public.approvals from anon, authenticated;
