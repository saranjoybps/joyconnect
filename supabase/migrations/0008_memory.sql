-- Long-term memory (pgvector), the per-user memory switch, conversation summaries and LLM usage.
-- Embeddings: OpenAI text-embedding-3-small, 1536 dimensions, compared with cosine distance (<=>).
-- RLS: users can read only their own rows; every write goes through FastAPI with the service role.

create extension if not exists vector with schema extensions;

create table public.memories (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users (id) on delete cascade,
  kind text not null default 'fact' check (kind in ('fact', 'preference', 'task', 'identifier')),
  content text not null check (char_length(content) between 1 and 500),
  embedding extensions.vector(1536),                 -- null when embedding failed; such rows are still listed
  source_conversation_id uuid references public.conversations (id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index memories_user_idx on public.memories (user_id, created_at desc);
create index memories_embedding_idx on public.memories using hnsw (embedding extensions.vector_cosine_ops);

create table public.user_settings (
  user_id uuid primary key references auth.users (id) on delete cascade,
  memory_enabled boolean not null default true,
  updated_at timestamptz not null default now()
);

-- Rolling summary of the older part of a conversation (short-term memory).
alter table public.conversations
  add column summary text,
  add column summary_upto bigint not null default 0;     -- messages.seq up to which `summary` covers

-- Token and cost accounting for per-user daily limits.
create table public.llm_usage (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users (id) on delete cascade,
  conversation_id uuid references public.conversations (id) on delete set null,
  purpose text not null default 'chat',                -- chat | summary | memory
  prompt_tokens integer not null default 0,
  completion_tokens integer not null default 0,
  cost_usd numeric(10, 6) not null default 0,
  created_at timestamptz not null default now()
);
create index llm_usage_user_day_idx on public.llm_usage (user_id, created_at desc);

alter table public.memories enable row level security;
alter table public.user_settings enable row level security;
alter table public.llm_usage enable row level security;

create policy memories_select on public.memories for select using (user_id = auth.uid());
create policy user_settings_select on public.user_settings for select using (user_id = auth.uid());
create policy llm_usage_select on public.llm_usage for select using (user_id = auth.uid());

revoke insert, update, delete on public.memories, public.user_settings, public.llm_usage from anon, authenticated;

-- Nearest memories of one user. Called only by the API (service role); the user id is always passed explicitly.
create or replace function public.match_memories(
  p_user_id uuid,
  query_embedding extensions.vector(1536),
  match_count int default 5,
  match_threshold float default 0.25
)
returns table (id uuid, kind text, content text, similarity float)
language sql
stable
set search_path = public, extensions
as $$
  select m.id, m.kind, m.content, 1 - (m.embedding <=> query_embedding) as similarity
    from public.memories m
   where m.user_id = p_user_id
     and m.embedding is not null
     and 1 - (m.embedding <=> query_embedding) >= match_threshold
   order by m.embedding <=> query_embedding asc
   limit least(match_count, 20);
$$;
revoke all on function public.match_memories(uuid, extensions.vector, int, float) from public, anon, authenticated;
grant execute on function public.match_memories(uuid, extensions.vector, int, float) to service_role;
