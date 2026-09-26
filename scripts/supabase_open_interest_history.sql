-- ============================================================================
-- open_interest_history — perp open interest series (T-012, 2026-09-26)
--
-- WHY (T-012): venue_snapshot() has been returning `open_interest` per perp
-- since S-205 (line 252 of hyperliquid_collector.py), but `collect_venue_marks`
-- only persisted funding — OI was extracted and immediately dropped. So we
-- had a daily read of "how much capital is on each perp" and zero history of
-- it, which is the same "measure and forget" defect as funding before
-- funding_history was built (S-107 / S-296).
--
-- WHY NOW. crypto_macro.py:50 — `perp_open_interest ✗ Hyperliquid metaAndAssetCtxs
-- 一次调用就有,未落库` was written down and never fixed. Without OI history
-- we cannot answer `system leverage is climbing or fading?` for the panel —
-- exactly the regime signal the M-119 macro_brief / RiskMeter pillars want
-- to consume, and exactly what data_layer.py:1576 / cis_provider.py:606
-- already try to read but find empty.
--
-- SHAPE. Mirrors funding_history:
--   - PK on (symbol, snapshot_time, venue) — the same 6h cadence the loop
--     already runs (`_venue_marks` loop, S-296) means one row per perp per
--     loop tick, ~4/day, capped at ~232 perps × 4 = 928 rows/day.
--   - Hour bucketing on `started.replace(minute=0, second=0, microsecond=0)`
--     so a re-run inside the same hour is idempotent (S-296).
--   - NOT NULL on open_interest — at write time we SKIP perps with None OI,
--     so the table records only measured quantities. Same as funding_history:
--     a "we have not measured" row would be a 0 row, indistinguishable from
--     "the perp genuinely has zero OI", which is the I1 hazard
--     (CLAUDE.md: 「未测量 = NaN 绝不是 0 且必须传播」).
--
-- SOURCE LABEL. venue = 'hyperliquid' (single value; HL is the only writer
-- for now). A second venue (Binance perps, OKX) can land here later under
-- the same PK without changing this DDL.
--
-- APPLY VIA MCP to production Supabase (Jazz).
-- ============================================================================

create table if not exists open_interest_history (
  symbol        text        not null,
  snapshot_time timestamptz not null,
  open_interest double precision not null,
  venue         text        not null default 'hyperliquid',
  primary key (symbol, snapshot_time, venue)
);

create index if not exists idx_oi_snapshot_time
  on open_interest_history (snapshot_time desc);
create index if not exists idx_oi_sym
  on open_interest_history (symbol, snapshot_time desc);

alter table open_interest_history enable row level security;
revoke all on open_interest_history from anon;

-- VERIFY (the criterion T-012 was opened for):
--   select count(distinct symbol)
--   from open_interest_history
--   where snapshot_time::date = current_date;
--   -- expect > 200 (Hyperliquid lists ~232 perps; a handful may be delisted/None OI)