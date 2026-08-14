-- ═══════════════════════════════════════════════════════════════════
-- CometCloud AI — Cause-History Migration (Seth, 2026-07-09)
-- New tables: cause_snapshots_daily (forward_supply + positioning history)
-- Run in Supabase SQL Editor (idempotent — safe to re-run)
-- URL: https://supabase.com/dashboard/project/soupjamxlfsmgmmtoeok/sql/new
--
-- WHY: P1 cause-driven backtest (forced-seller short + squeeze-long)
-- requires HISTORICAL cause data. Today the cause data is live-only
-- (Redis TTL 6h for supply, 30min for positioning). After this migration,
-- each daily refresh writes a row so we accumulate ≥6mo of history and
-- can run the actual ARCHITECTURE.md "causes predict" validation.
-- ═══════════════════════════════════════════════════════════════════


-- ═══════════════════════════════════════════════════════════════════
-- 1. Daily Cause Snapshots — one row per (date, symbol) with both causes
-- ═══════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS cause_snapshots_daily (
    id                      BIGSERIAL PRIMARY KEY,
    snapshot_date           DATE NOT NULL,
    symbol                  TEXT NOT NULL,

    -- Forward-supply cause (#1, structural forced-dilution overhang)
    forward_supply_risk     REAL,           -- [0, 1] — saturates at 150% overhang
    float_ratio             REAL,           -- circ / max(circ, total, max)
    overhang                REAL,           -- (future - circ) / circ

    -- Positioning cause (#2, reflexive leverage pressure)
    positioning_pressure    REAL,           -- [-1, +1] — squeeze (+) / long-liq (-)
    funding_rate            REAL,           -- raw OI-weighted funding
    oi_usd                  REAL,           -- total open interest in USD

    -- Reference CIS score at snapshot time (for cross-validation)
    cis_score               REAL,
    signal                  TEXT,           -- OUTPERFORM / NEUTRAL / UNDERPERFORM
    macro_regime            TEXT,

    source                  TEXT NOT NULL DEFAULT 'live_refresh',
    recorded_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (snapshot_date, symbol)
);

CREATE INDEX IF NOT EXISTS idx_cause_snapshots_date
    ON cause_snapshots_daily (snapshot_date DESC);
CREATE INDEX IF NOT EXISTS idx_cause_snapshots_symbol_date
    ON cause_snapshots_daily (symbol, snapshot_date DESC);
CREATE INDEX IF NOT EXISTS idx_cause_snapshots_fs_high
    ON cause_snapshots_daily (snapshot_date DESC) WHERE forward_supply_risk >= 0.5;
CREATE INDEX IF NOT EXISTS idx_cause_snapshots_pos_squeeze
    ON cause_snapshots_daily (snapshot_date DESC) WHERE positioning_pressure >= 0.5;
CREATE INDEX IF NOT EXISTS idx_cause_snapshots_pos_liq
    ON cause_snapshots_daily (snapshot_date DESC) WHERE positioning_pressure <= -0.5;

ALTER TABLE cause_snapshots_daily ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "cause_snapshots_select" ON cause_snapshots_daily;
DROP POLICY IF EXISTS "cause_snapshots_insert" ON cause_snapshots_daily;
-- S-167: was `CREATE POLICY "cause_snapshots_select" ON cause_snapshots_daily FOR SELECT USING (true)`
-- granted to PUBLIC. Measured 2026-08-15: the anon key could read this.
-- Removed live and here. Nothing we ship reads through anon — the frontend
-- goes through /api/v1/* on FastAPI, which holds service_role.
DROP POLICY IF EXISTS "cause_snapshots_select" ON cause_snapshots_daily;
-- S-167: was `CREATE POLICY "cause_snapshots_insert" ON cause_snapshots_daily FOR INSERT` granted to PUBLIC.
-- Removed. service_role bypasses RLS; nothing legitimate needed it.
DROP POLICY IF EXISTS "cause_snapshots_insert" ON cause_snapshots_daily;


-- ═══════════════════════════════════════════════════════════════════
-- 2. Conviction Verdicts Daily — one row per (date, symbol) for kernel output
-- ═══════════════════════════════════════════════════════════════════
-- The full conviction synthesis output (compute_conviction + conviction_book)
-- so we can backtest cause-driven decisions vs raw CIS / vs edge-map / vs
-- benchmark.
-- ═══════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS conviction_verdicts_daily (
    id                      BIGSERIAL PRIMARY KEY,
    snapshot_date           DATE NOT NULL,
    symbol                  TEXT NOT NULL,

    -- Conviction synthesis output
    direction               TEXT,           -- long | short | neutral
    conviction              REAL,           -- [0, 1]
    adjusted_edge_pct       REAL,           -- signed alpha in %
    expected_edge_pct       REAL,           -- empirical edge map alpha
    basis                   TEXT,           -- edge_map | quality_fallback
    confidence              REAL,
    action                  TEXT,

    -- The cause inputs that drove the verdict
    forward_supply_risk     REAL,
    positioning_pressure    REAL,
    in_circle               REAL,           -- 1 - cause_proximity risk
    season                  TEXT,
    quality_score           REAL,
    executability           TEXT,

    -- Named plays (forced-seller short + squeeze-long fall out for free)
    is_forced_seller_short  BOOLEAN DEFAULT FALSE,   -- direction=short AND fs>=0.5
    is_squeeze_long         BOOLEAN DEFAULT FALSE,   -- direction=long AND pos>=+0.3
    is_long_liq_short       BOOLEAN DEFAULT FALSE,   -- direction=short AND pos<=-0.5

    macro_regime            TEXT,
    source                  TEXT NOT NULL DEFAULT 'conviction_kernel',
    recorded_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (snapshot_date, symbol)
);

CREATE INDEX IF NOT EXISTS idx_conviction_date
    ON conviction_verdicts_daily (snapshot_date DESC);
CREATE INDEX IF NOT EXISTS idx_conviction_forced_seller
    ON conviction_verdicts_daily (snapshot_date DESC) WHERE is_forced_seller_short = TRUE;
CREATE INDEX IF NOT EXISTS idx_conviction_squeeze_long
    ON conviction_verdicts_daily (snapshot_date DESC) WHERE is_squeeze_long = TRUE;

ALTER TABLE conviction_verdicts_daily ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "conviction_verdicts_select" ON conviction_verdicts_daily;
DROP POLICY IF EXISTS "conviction_verdicts_insert" ON conviction_verdicts_daily;
-- S-167: was `CREATE POLICY "conviction_verdicts_select" ON conviction_verdicts_daily FOR SELECT USING (true)`
-- granted to PUBLIC. Measured 2026-08-15: the anon key could read this.
-- Removed live and here. Nothing we ship reads through anon — the frontend
-- goes through /api/v1/* on FastAPI, which holds service_role.
DROP POLICY IF EXISTS "conviction_verdicts_select" ON conviction_verdicts_daily;
-- S-167: was `CREATE POLICY "conviction_verdicts_insert" ON conviction_verdicts_daily FOR INSERT` granted to PUBLIC.
-- Removed. service_role bypasses RLS; nothing legitimate needed it.
DROP POLICY IF EXISTS "conviction_verdicts_insert" ON conviction_verdicts_daily;


-- ═══════════════════════════════════════════════════════════════════
-- 3. Cause-Driven Trade Outcomes — measured forward returns for named plays
-- ═══════════════════════════════════════════════════════════════════
-- One row per (date, symbol, play). Captures forward returns at multiple
-- horizons so we can grade the kernel against AQR walk-forward standards.
-- ═══════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS cause_outcomes (
    id                      BIGSERIAL PRIMARY KEY,
    snapshot_date           DATE NOT NULL,
    symbol                  TEXT NOT NULL,

    -- The decision / play classification at snapshot time
    play                    TEXT NOT NULL,  -- forced_seller_short | squeeze_long | long_liq_short
    direction               TEXT,           -- long | short
    conviction              REAL,
    adjusted_edge_pct       REAL,

    -- Forward returns at multiple horizons (matched from OHLCV)
    fwd_7d_return_pct       REAL,
    fwd_30d_return_pct      REAL,
    fwd_60d_return_pct      REAL,
    fwd_90d_return_pct      REAL,

    -- Benchmark-relative (alpha) returns
    bench_fwd_7d_pct        REAL,
    bench_fwd_30d_pct       REAL,
    bench_fwd_60d_pct       REAL,
    bench_fwd_90d_pct       REAL,

    alpha_7d_pct            REAL,
    alpha_30d_pct           REAL,
    alpha_60d_pct           REAL,
    alpha_90d_pct           REAL,

    -- Naive PnL assuming 1× notional
    pnl_30d_usd             REAL,

    -- Cross-validation
    cis_score               REAL,
    macro_regime            TEXT,
    forward_supply_risk     REAL,
    positioning_pressure    REAL,

    source                  TEXT NOT NULL DEFAULT 'cause_outcome_backfill',
    recorded_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (snapshot_date, symbol, play)
);

CREATE INDEX IF NOT EXISTS idx_cause_outcomes_play_date
    ON cause_outcomes (play, snapshot_date DESC);
CREATE INDEX IF NOT EXISTS idx_cause_outcomes_date
    ON cause_outcomes (snapshot_date DESC);

ALTER TABLE cause_outcomes ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "cause_outcomes_select" ON cause_outcomes;
DROP POLICY IF EXISTS "cause_outcomes_insert" ON cause_outcomes;
-- S-167: was `CREATE POLICY "cause_outcomes_select" ON cause_outcomes FOR SELECT USING (true)`
-- granted to PUBLIC. Measured 2026-08-15: the anon key could read this.
-- Removed live and here. Nothing we ship reads through anon — the frontend
-- goes through /api/v1/* on FastAPI, which holds service_role.
DROP POLICY IF EXISTS "cause_outcomes_select" ON cause_outcomes;
-- S-167: was `CREATE POLICY "cause_outcomes_insert" ON cause_outcomes FOR INSERT` granted to PUBLIC.
-- Removed. service_role bypasses RLS; nothing legitimate needed it.
DROP POLICY IF EXISTS "cause_outcomes_insert" ON cause_outcomes;


-- ─────────────────────────────────────────────────────────────────────────────
-- WRITE POLICIES CORRECTED 2026-08-15 (S-167). DO NOT RE-ADD PUBLIC WRITES.
--
-- This file granted INSERT/UPDATE/DELETE to PUBLIC (a `CREATE POLICY ... FOR
-- INSERT WITH CHECK (true)` with no `TO` clause is granted to PUBLIC, and the
-- anon key is public — it ships inside the browser bundle).
--
-- The LIVE database does not have these grants; the 2026-07-30 hardening
-- replaced them. So the drift was file-more-permissive-than-production, which
-- is the dangerous direction: these files are idempotent, they are meant to be
-- re-run, and on 2026-08-15 one of them WAS re-run. Anybody running this file
-- would have silently re-opened public writes on a hardened table.
--
-- Posture below matches live: RLS on, writes denied to PUBLIC. service_role
-- bypasses RLS, so the app is unaffected — production writes through
-- SUPABASE_KEY and never needed these policies at all.
-- ─────────────────────────────────────────────────────────────────────────────

DROP POLICY IF EXISTS "cause_outcomes_no_public_write" ON cause_outcomes;
DROP POLICY IF EXISTS "cause_snapshots_daily_no_public_write" ON cause_snapshots_daily;
DROP POLICY IF EXISTS "conviction_verdicts_daily_no_public_write" ON conviction_verdicts_daily;
