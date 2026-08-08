-- ============================================================================
-- L2 CANONICAL, rebuilt on L0.  docs/DATA_ARCHITECTURE.md steps 2 + 3.
-- APPLIED 2026-08-07 (migration l2_canonical_registry_backed).
--
-- TWO CHANGES, BOTH MEASURED RATHER THAN ASSUMED.
--
-- (1) CLASS COMES FROM THE REGISTRY.
--     The old view passed `asset_class` through from the observation row. 24 symbols
--     carried conflicting values there, because the column did not describe the asset —
--     it recorded which SOURCE the row came from. All 6 classes appear under all 4
--     sources, so class and source are orthogonal and class was never a proxy for
--     anything.
--
-- (2) BAR CONVENTION IS A PROPERTY OF THE SOURCE, and is now explicit.
--     Measured |open/prev_close - 1|, per source, over the whole table:
--       binance_hist  82,186 rows  50.1% ~zero  median 0.00010   0.1% >1%
--       yfinance      90,738 rows   2.9% ~zero  median 0.00362  19.1% >1%
--       eodhd          8,613 rows   2.4% ~zero  median 0.00355  20.4% >1%
--       coingecko     48,303 rows   0.2% ~zero  median 0.02563  77.2% >1%
--     CoinGecko's daily `open` is not the prior close because its snapshot boundary
--     differs. The discontinuity is vendor timing, not a market gap, and it makes
--     `open` unusable on those 48,303 rows. Reading that seam as market structure is
--     exactly what produced the S-106 "+12.30 cumulative overnight return".
--
-- RESULT AFTER THE REBUILD — the gap rate is now explained by convention, not class:
--       continuous_utc   0.1%   |  session 19.2%  |  vendor_snapshot 77.5%
--     and by class it collapses: Crypto 31.3% -> 0.7%.
--     Re-running the S-106 decomposition on continuous bars only gives overnight
--     +2.05 vs the original +12.30 — about +0.05 per asset, i.e. the ~zero that
--     physics demands for a 24/7 instrument. The artifact was not patched out; it
--     disappeared once identity was correct.
-- ============================================================================

-- ⚠️ STORAGE COST — the three UPDATEs below rewrite ~1M rows across two large
-- tables. Every UPDATE writes a NEW tuple version; autovacuum will reclaim the
-- dead ones, but the freed space stays inside the pages and is never returned to
-- the OS. Measured consequence on 2026-08-08: hourly ran at 276 B/row against
-- daily's 108 B/row for a comparable column set, and the database sat at 90% of
-- its tier with n_dead_tup already at 0 — i.e. the bloat was invisible to the
-- usual "are there dead tuples" check.
--
-- **A bulk UPDATE is a storage event, not just a data event.** Run VACUUM FULL as
-- part of THIS migration rather than discovering it later at capacity:
--     vacuum full ohlcv_daily;      -- one statement at a time; VACUUM cannot run
--     vacuum full ohlcv_hourly;     -- inside a transaction block
-- Recovery when this was found late: scripts/supabase_storage_hygiene.sql.
alter table ohlcv_daily     add column if not exists asset_id text references assets(asset_id);
alter table ohlcv_hourly    add column if not exists asset_id text references assets(asset_id);
alter table funding_history add column if not exists asset_id text references assets(asset_id);

update ohlcv_daily     o set asset_id = a.asset_id from assets a where a.symbol = o.symbol and o.asset_id is null;
update ohlcv_hourly    o set asset_id = a.asset_id from assets a where a.symbol = o.symbol and o.asset_id is null;
update funding_history f set asset_id = a.asset_id from assets a where a.symbol = f.symbol and f.asset_id is null;

create index if not exists idx_ohlcv_daily_asset  on ohlcv_daily (asset_id, trade_date);
create index if not exists idx_ohlcv_hourly_asset on ohlcv_hourly (asset_id, ts);

drop view if exists ohlcv_daily_canonical cascade;
create view ohlcv_daily_canonical as
select distinct on (o.symbol, o.trade_date)
  o.symbol, o.asset_id, o.trade_date,
  a.class as asset_class,               -- FROM THE REGISTRY, not from the row
  o.source, o.open, o.high, o.low, o.close, o.volume,
  case o.source
    when 'coingecko' then 'usd_notional' when 'eodhd' then 'shares'
    when 'yfinance'  then 'shares'       else 'base_units' end as volume_unit,
  case o.source
    when 'binance_hist' then 'continuous_utc'    -- 24/7, bar aligned to UTC midnight
    when 'hyperliquid'  then 'continuous_utc'
    when 'coingecko'    then 'vendor_snapshot'   -- open is a snapshot artifact
    else 'session' end as bar_convention,        -- eodhd / yfinance: real overnight gaps
  (o.source <> 'coingecko') as open_usable
from ohlcv_daily o
join assets a on a.asset_id = o.asset_id
order by o.symbol, o.trade_date,
  case o.source when 'binance_hist' then 1 when 'hyperliquid' then 2 when 'eodhd' then 3
                when 'coingecko' then 4 when 'yfinance' then 5 else 9 end;

comment on view ohlcv_daily_canonical is
  'L2 canonical daily bars. class is joined from `assets`, NOT taken from the observation row '
  'which recorded the source and gave 24 symbols conflicting labels. bar_convention and '
  'open_usable are explicit: coingecko medians a 2.56% open/prev_close discontinuity that is '
  'vendor snapshot timing. Any overnight/intraday decomposition MUST filter open_usable.';

-- ---------------------------------------------------------------------------
-- VERIFY
--   select count(*) from ohlcv_daily where asset_id is null;          -- expect 0 (same for
--   select count(*) from ohlcv_hourly where asset_id is null;         --   hourly and funding)
--
--   -- convention must EXPLAIN the gap rate; class must no longer:
--   select bar_convention,
--          round(100.0*count(*) filter (where abs(open/pc-1)>0.01)/count(*),1) pct_gap_over_1pct
--   from (select bar_convention, open,
--                lag(close) over (partition by symbol order by trade_date) pc
--         from ohlcv_daily_canonical) z
--   where pc>0 group by bar_convention;
--   -- measured: continuous_utc 0.1 · session 19.2 · vendor_snapshot 77.5
--
--   -- coverage gap this made visible for the first time:
--   select count(*) filter (where not has_cont) as assets_without_continuous_bars, count(*)
--   from (select asset_id, bool_or(bar_convention='continuous_utc') has_cont
--         from ohlcv_daily_canonical group by asset_id) c;   -- measured: 34 of 75
