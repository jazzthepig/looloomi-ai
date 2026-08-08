-- ============================================================================
-- Storage hygiene — 449 MB -> 237 MB (90% -> 47% of the 500 MB tier), 2026-08-08.
-- APPLIED. Zero rows archived, zero rows deleted.
--
-- Jazz asked whether to start moving data to local storage. Measurement said no:
-- the database was not full of data, it was full of two recoverable wastes.
--
--   (1) DEAD INDEXES — ~84 MB.  pg_stat_user_indexes had 176 days of accumulated
--       statistics, so a zero scan count is trustworthy evidence rather than a
--       fresh-stats artifact. That age check comes first; without it the whole
--       exercise is guesswork.
--
--   (2) MY OWN BLOAT — ~128 MB.  Populating `asset_id` earlier the same day
--       UPDATEd ~1M rows across ohlcv_daily + ohlcv_hourly. Every UPDATE writes a
--       new tuple version; autovacuum reclaimed the dead ones (n_dead_tup = 0)
--       but free space inside pages is NOT returned to the OS. The tell was
--       276 B/row on hourly against 108 B/row on daily for a similar column set.
--       **An UPDATE across a large table is a storage event, not just a data
--       event** — plan the VACUUM FULL with it, do not discover it later.
--
-- THE TRAP AVOIDED. Four of these indexes were created TODAY, so their low scan
-- counts reflect their AGE, not their usefulness. Those were judged on structural
-- redundancy instead:
--   · a btree on (symbol, ts, source) already serves any (symbol, ts) predicate,
--     and btrees scan backwards, so a separate DESC index buys nothing;
--   · asset_id is 1:1 with symbol for every row today, so asset_id indexes
--     duplicate the symbol ones. **RECREATE THEM IF asset_id EVER DIVERGES FROM
--     symbol** (aliases, renames, or a merged venue) — that is the one condition
--     under which this decision reverses.
-- ============================================================================

-- Step 0 — ALWAYS check the stats age first. A zero scan count on freshly reset
-- statistics means nothing at all.
--   select stats_reset, now()-stats_reset from pg_stat_database
--    where datname = current_database();     -- measured: 176 days
--
--   select i.relname, pg_size_pretty(pg_relation_size(i.oid)), s.idx_scan
--   from pg_class i join pg_index x on x.indexrelid=i.oid
--   join pg_class t on t.oid=x.indrelid
--   left join pg_stat_user_indexes s on s.indexrelid=i.oid
--   where t.relnamespace='public'::regnamespace
--   order by pg_relation_size(i.oid) desc;

-- Dead by SCAN COUNT over 176 days:
drop index if exists idx_cis_scores_class_time;        -- 0 scans  · 2.8 MB
drop index if exists idx_cis_scores_data_tier_time;    -- 0 scans  · 1.5 MB
drop index if exists idx_od_recorded;                  -- 30 scans · 5 MB

-- Dead by BANNED QUERY PATTERN rather than by scan count: filtering observation
-- rows on asset_class is now forbidden (tests/test_data_architecture.py) because
-- it selects a SOURCE, not a class. An index serving a banned pattern is dead
-- however often it was used before the ban.
drop index if exists idx_od_class_date;                -- 7 MB

-- Redundant by PREFIX. Judged structurally because these are hours old.
drop index if exists idx_ohlcv_hourly_sym_ts;          -- 25 MB, prefix of pkey
drop index if exists idx_ohlcv_hourly_ts;              -- 7.7 MB, ts-only; every real query is symbol-scoped
drop index if exists idx_ohlcv_hourly_asset;           -- 19 MB, asset_id == symbol today
drop index if exists idx_ohlcv_daily_asset;            -- 16 MB, ditto
drop index if exists idx_od_symbol_date;               -- 23 MB, prefix of the unique key

-- Reclaim the space the UPDATEs left inside pages. VACUUM FULL takes an EXCLUSIVE
-- lock and rewrites the table, so it cannot run inside a transaction block and
-- must be issued one statement at a time. On these sizes it completes in seconds;
-- on a serving table, schedule it.
vacuum full ohlcv_hourly;
vacuum full ohlcv_daily;
vacuum full cis_scores;

-- MEASURED RESULT
--   ohlcv_hourly  216 MB -> 86 MB   (heap 124->63, idx 92->22)
--   ohlcv_daily   161 MB -> 89 MB   (heap  55->55, idx 106->34)
--   cis_scores     41 MB -> 37 MB
--   database      449 MB -> 237 MB  (90% -> 47% of the free tier)
--
-- WHEN THIS STOPS BEING ENOUGH — the archive order, cheapest regret first:
--   1. `ohlcv_hourly` (86 MB, 10 assets). Built for the S-106 intraday work,
--      which is complete; it is refetchable from Binance in minutes via
--      backfill_binance_hourly(). **Refetchable data is the correct first thing
--      to evict** — the archive question is not "what is big" but "what could we
--      not rebuild".
--   2. `cis_scores` older than ~18 months (37 MB). Historical scores are inputs to
--      finished studies, not to the live loop.
--   3. NEVER archive: beta_core_nav, signal_outcomes, the paper NAV tables, or
--      REFUTATION_LEDGER-linked rows. Those are forward record and graveyard —
--      irreplaceable by construction, and small.
