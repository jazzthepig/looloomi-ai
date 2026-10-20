-- 2026-10-20 · Binance USDT-M funding history for the whole binance_hist universe, from the public monthly archive
-- (data.binance.vision/data/futures/um/monthly/fundingRate/<PAIR>/) — ledger S-638 follow-up.
--
-- Why: funding_history (venue binance_perp) covers 36 names, kept by binance_hf_collector through fapi. The R-v2
-- tickets (S-638) trade ~180 names; on the 36 covered ones a long ticket paid 0.08R of funding on average, the rest is
-- unmeasured. The archive is static files (same family as the T-133 metrics loop), so this backfills without a second
-- API client and without hitting fapi for 200 names a day (Jazz 09-09).
--
-- funding_vision_absent: a (symbol, month) whose archive file does not exist (not listed then / never a perp) is written
-- here once and never fetched again — "no file" and "fetch failed" are different things (the second is retried).
-- funding_vision_plan: (symbol, month) still to fetch = months from max(2020-01, the symbol's first binance_hist bar) to
-- the last complete UTC month, minus months that already have any binance_perp funding row, minus absent months.
-- Months the fapi collector already holds are never refetched, so its mark_price is never overwritten with null.

create table if not exists public.funding_vision_absent (
  symbol     text not null,
  month      date not null,
  checked_at timestamptz not null default now(),
  primary key (symbol, month)
);
alter table public.funding_vision_absent enable row level security;
grant select on public.funding_vision_absent to anon;
drop policy if exists lane_read on public.funding_vision_absent;
create policy lane_read on public.funding_vision_absent for select to anon using (true);

create or replace view public.funding_vision_plan with (security_invoker = true) as
with u as (
  select symbol, greatest(date '2020-01-01', date_trunc('month', min(trade_date))::date) start_m
  from ohlcv_daily
  where source = 'binance_hist' and symbol not in ('USDC', 'BTCDOM', 'DEFI')
  group by symbol
), have as (
  select symbol, date_trunc('month', funding_time at time zone 'utc')::date m
  from funding_history where venue = 'binance_perp'
  group by 1, 2
), months as (
  select u.symbol, g::date m
  from u cross join lateral generate_series(
    u.start_m, (date_trunc('month', now() at time zone 'utc') - interval '1 month')::date, interval '1 month') g
)
select m.symbol, m.m as month
from months m
where not exists (select 1 from have h where h.symbol = m.symbol and h.m = m.m)
  and not exists (select 1 from funding_vision_absent a where a.symbol = m.symbol and a.month = m.m);

