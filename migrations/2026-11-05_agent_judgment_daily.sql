-- agent 判断臂(S-725,11-05;src/data/execution/agent_judgment.py)。已通过 Supabase MCP 施加(migration name: agent_judgment_daily)。
create table if not exists public.agent_judgment_daily (
  d date not null,
  author text not null,
  model text,
  probs jsonb not null,
  rationale text,
  drivers jsonb,
  change_mind text,
  dossier_hash text,
  scenario_ids jsonb,
  code_ref text,
  created_at timestamptz not null default now(),
  primary key (d, author)
);
alter table public.agent_judgment_daily enable row level security;
drop policy if exists lane_read on public.agent_judgment_daily;
create policy lane_read on public.agent_judgment_daily for select to anon using (true);
grant select on public.agent_judgment_daily to anon, authenticated;
grant all on public.agent_judgment_daily to service_role;
