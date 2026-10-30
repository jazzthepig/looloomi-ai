-- 2026-10-30 · 执行质量日表(src/data/execution/exec_quality.py):每本执行账(sleeve)每天一行 + 一行自开账起累计。
-- fill_log.execution_quality 的第一个消费者 —— 真钱第一批成交(10-30 15:44 UTC,T25 的 XAUT0 / SPYX)之后才有数可算。
-- 幂等 upsert;进 forward_anchor_daily。公开读走 /api/v1/proof/books 的 execution 段(只出聚合,不出方向词)。
create table if not exists public.execution_quality_daily (
  d                              date not null,
  sleeve                         text not null,
  span                           text not null check (span in ('day', 'since_inception')),
  n_intents                      integer not null,
  n_resolved                     integer not null,
  n_unresolved                   integer not null default 0,
  n_filled                       integer not null,
  fill_rate                      double precision,
  notional_usd                   double precision not null default 0,
  mean_slippage_bps              double precision,
  mean_fee_bps                   double precision,
  mean_opportunity_bps           double precision,
  implementation_shortfall_bps   double precision,
  median_quoted_spread_bps       double precision,
  maker_share                    double precision,
  first_d                        date,
  note                           text,
  code_ref                       text not null,
  computed_at                    timestamptz not null default now(),
  primary key (d, sleeve, span)
);
alter table public.execution_quality_daily enable row level security;
revoke all on public.execution_quality_daily from anon, authenticated;
