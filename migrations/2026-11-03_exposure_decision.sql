-- 2026-11-03 · exposure_decision_daily: one row per day for sleeve ③ — the frozen rule's exposure, the inputs it saw,
-- base-rate scenario probabilities (30-day BTC < −10% / ±10% / > +10%, conditional on trend × macro state, shrunk),
-- the three scenario_ledger ids written for the day, a disagreement flag, and the compliance-safe rationale.
create table if not exists public.exposure_decision_daily (
  d              date primary key,
  sleeve         text not null default 'crypto_core',
  rule_exposure  double precision,
  mult_arm       text,
  mult_m         double precision,
  inputs         jsonb not null default '{}'::jsonb,
  bucket         text,
  probs          jsonb not null default '{}'::jsonb,
  n_bucket       integer,
  flag           text,
  rationale      text,
  scenario_ids   jsonb not null default '[]'::jsonb,
  posted_at      timestamptz,
  code_ref       text,
  recorded_at    timestamptz not null default now()
);
alter table public.exposure_decision_daily enable row level security;
grant select on public.exposure_decision_daily to anon;
drop policy if exists lane_read on public.exposure_decision_daily;
create policy lane_read on public.exposure_decision_daily for select to anon using (true);
