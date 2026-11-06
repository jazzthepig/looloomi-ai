-- 2026-11-06 · exchange_volume_daily: per-venue daily volume in BTC from CoinGecko Analyst
-- /exchanges/{id}/volume_chart/range (spot + derivatives venues, backfilled from 2021-01-01).
-- d = UTC date of the point's timestamp (the value is already known at that instant ⇒ no look-ahead, ≤1 day stale).
create table if not exists public.exchange_volume_daily (
  d date not null,
  exchange text not null,
  kind text not null check (kind in ('spot', 'deriv')),
  volume_btc double precision not null,
  fetched_at timestamptz not null default now(),
  primary key (d, exchange)
);
create index if not exists exchange_volume_daily_ex_d on public.exchange_volume_daily (exchange, d);
alter table public.exchange_volume_daily enable row level security;
grant select on public.exchange_volume_daily to anon;
drop policy if exists lane_read on public.exchange_volume_daily;
create policy lane_read on public.exchange_volume_daily for select to anon using (true);
