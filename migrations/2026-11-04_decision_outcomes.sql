-- 决策 → 结果(Outcome 层,11-04;src/data/entity/decision_outcomes.py)。已通过 Supabase MCP 施加(migration name: decision_outcomes)。
-- 只追加:每条 issuer_decisions 的 7 / 30 / 90 天前向收益与基准(BTC / SPY)之差,到期才结。
create table if not exists public.decision_outcomes (
  decision_id text not null,
  horizon_d int not null,
  entity_id text,
  symbol text not null,
  cls text not null,
  kind text not null,
  d date not null,
  entry_d date not null,
  exit_d date not null,
  entry double precision not null,
  exit double precision not null,
  ret double precision not null,
  bench text not null,
  ret_bench double precision not null,
  excess double precision not null,
  hit boolean not null,
  source text not null,
  code_ref text,
  settled_at timestamptz not null default now(),
  primary key (decision_id, horizon_d)
);
create index if not exists decision_outcomes_kind_h on public.decision_outcomes (kind, horizon_d);
create index if not exists decision_outcomes_entity on public.decision_outcomes (entity_id, d desc);
alter table public.decision_outcomes enable row level security;
drop policy if exists lane_read on public.decision_outcomes;
create policy lane_read on public.decision_outcomes for select to anon using (true);
grant select on public.decision_outcomes to anon, authenticated;
grant all on public.decision_outcomes to service_role;
