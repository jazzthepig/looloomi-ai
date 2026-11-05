-- Entity 空间向量(11-05;src/data/entity/entity_vectors.py)。已通过 Supabase MCP 施加(migration name: entity_vectors)。
create table if not exists public.entity_vectors (
  entity_id text not null,
  quarter text not null,
  vector jsonb not null,
  n_days int not null default 0,
  n_decisions int not null default 0,
  code_ref text,
  computed_at timestamptz not null default now(),
  primary key (entity_id, quarter)
);
alter table public.entity_vectors enable row level security;
drop policy if exists lane_read on public.entity_vectors;
create policy lane_read on public.entity_vectors for select to anon using (true);
grant select on public.entity_vectors to anon, authenticated;
grant all on public.entity_vectors to service_role;
