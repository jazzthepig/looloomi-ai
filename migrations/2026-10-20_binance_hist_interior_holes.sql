-- 2026-10-20 · interior holes in binance_hist (found by S-628).
--
-- The deep-panel collector heals only the FRONTIER (how far the newest bar is from today). A hole in the middle —
-- 2026-08-09 → 09-06, 85 names, the collector was stopped for 30 days and resumed 09-07 — is invisible to it, so it
-- stays forever, and every study that reads "the next N rows" as "the next N days" silently stretches across it.
-- This lists, for names still alive (a bar in the last 3 days), every gap inside the last p_lookback days.
-- Reader: deep_panel_collector.heal_interior_holes (service_role). STABLE, SECURITY INVOKER.

create or replace function public.binance_hist_interior_holes(p_lookback int default 120)
returns table(symbol text, first_missing date, n_missing int)
language sql stable security invoker set search_path = public as $$
  with lat as (
    select max(trade_date) m from ohlcv_daily where source = 'binance_hist'
  ), live as (
    select o.symbol from ohlcv_daily o, lat
    where o.source = 'binance_hist' and o.trade_date >= lat.m - 3
    group by o.symbol
  ), b as (
    select o.symbol, o.trade_date d,
           lead(o.trade_date) over (partition by o.symbol order by o.trade_date) nd
    from ohlcv_daily o, lat
    where o.source = 'binance_hist' and o.trade_date >= lat.m - p_lookback
  )
  select b.symbol, min(b.d + 1) first_missing, sum(b.nd - b.d - 1)::int n_missing
  from b join live using (symbol)
  where b.nd > b.d + 1
  group by b.symbol
  order by b.symbol;
$$;
revoke all on function public.binance_hist_interior_holes(int) from public, anon, authenticated;
grant execute on function public.binance_hist_interior_holes(int) to service_role;
