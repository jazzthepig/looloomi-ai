-- S-551: the single heaviest query on the database had no index for its ORDER BY.
--
-- market_state_writer pages ohlcv_daily with
--   WHERE source = $1 AND trade_date >= $2 ORDER BY trade_date, symbol LIMIT 1000 OFFSET n
-- The only (source, …) index is (source, symbol, trade_date), which cannot serve that order, so every page
-- did a parallel seq scan of the table and an external-merge sort spilled to disk (EXPLAIN 10-12: 340 ms,
-- ~6 MB temp per page). pg_stat_statements since 09-24: 56,425 calls, 22,277 s = 44% of all DB time,
-- 691 GB of temp writes = 72% of all temp. On Micro compute (11 MB/s baseline disk throughput) that spill
-- draws down the burst IO budget the whole API shares.
--
-- With (source, trade_date, symbol) the pages are read in index order — no sort, no temp. INCLUDE keeps the
-- two value columns in the index so most pages are index-only.
create index if not exists ohlcv_daily_source_date_symbol_idx
  on public.ohlcv_daily (source, trade_date, symbol) include (close, volume);
