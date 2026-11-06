-- 2026-11-06 · token_holders_daily: holder counts from CoinGecko Analyst holders_chart (Beta), home chain only.
-- days=max gives weekly history (granularity 'weekly'), days=30 daily ('daily'); one row per (d, coin).
create table if not exists public.token_holders_daily (
  d date not null,
  coin_id text not null,
  network text not null,
  address text not null,
  holders bigint not null check (holders > 0),
  granularity text not null check (granularity in ('weekly', 'daily')),
  fetched_at timestamptz not null default now(),
  primary key (d, coin_id)
);
create index if not exists token_holders_daily_coin_d on public.token_holders_daily (coin_id, d);
alter table public.token_holders_daily enable row level security;
grant select on public.token_holders_daily to anon;
drop policy if exists lane_read on public.token_holders_daily;
create policy lane_read on public.token_holders_daily for select to anon using (true);

-- what the writer reads: the point-in-time coin universe (every coin we ever stored a market cap for) and coverage so far
create or replace view public.cg_coin_mcap_coins with (security_invoker = true) as
select coin_id, min(d) first_d, max(d) last_d,
       (array_agg(mcap order by d desc))[1] last_mcap
from public.cg_coin_mcap_daily where mcap > 0 group by coin_id;
grant select on public.cg_coin_mcap_coins to anon;

create or replace view public.token_holders_coverage with (security_invoker = true) as
select coin_id, min(d) min_d, max(d) max_d, count(*) n, count(*) filter (where granularity = 'weekly') n_weekly
from public.token_holders_daily group by coin_id;
grant select on public.token_holders_coverage to anon;
