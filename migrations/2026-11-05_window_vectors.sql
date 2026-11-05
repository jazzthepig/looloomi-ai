-- 时序窗口向量(11-05;src/data/state/window_vectors.py)。已通过 Supabase MCP 施加(migration name: window_vectors)。
create table if not exists public.window_vectors (
  d date primary key,
  vec jsonb not null,
  dims jsonb not null,
  close double precision,
  code_ref text,
  computed_at timestamptz not null default now()
);
alter table public.window_vectors enable row level security;
drop policy if exists lane_read on public.window_vectors;
create policy lane_read on public.window_vectors for select to anon using (true);
grant select on public.window_vectors to anon, authenticated;
grant all on public.window_vectors to service_role;
