-- 2026-11-03 · treatment_daily: minority-holder treatment per CIS crypto name per day (Jazz 11-02: CIS's core dimension).
-- revenue / holders revenue (DeFiLlama snapshot, all slugs per coingecko id), holder share, market cap, supply and
-- 30-day supply growth (dilution), annualised revenue / holder yields, daily rank. Point-in-time; measurement only.
create table if not exists public.treatment_daily (
  symbol             text not null,
  d                  date not null,
  coin_id            text,
  revenue_30d        double precision,
  holders_30d        double precision,
  holders_share      double precision,
  mcap               double precision,
  price              double precision,
  supply             double precision,
  supply_growth_30d  double precision,
  revenue_yield_ann  double precision,
  holder_yield_ann   double precision,
  rank_holder_yield  integer,
  n_slugs            integer,
  code_ref           text,
  recorded_at        timestamptz not null default now(),
  primary key (symbol, d)
);
create index if not exists treatment_daily_d_idx on public.treatment_daily (d desc);
alter table public.treatment_daily enable row level security;
grant select on public.treatment_daily to anon;
drop policy if exists lane_read on public.treatment_daily;
create policy lane_read on public.treatment_daily for select to anon using (true);
