-- ═══════════════════════════════════════════════════════════════════
-- CometCloud AI — Time Series Migration
-- Run in Supabase SQL Editor AFTER supabase_all_tables.sql
-- Dashboard → SQL Editor → New Query → paste → Run
-- URL: https://supabase.com/dashboard/project/soupjamxlfsmgmmtoeok/sql/new
-- ═══════════════════════════════════════════════════════════════════

-- ─── 1. Extend cis_scores for time-series analytics ─────────────────────────

ALTER TABLE cis_scores
    ADD COLUMN IF NOT EXISTS score_delta   REAL,          -- change vs previous push for same symbol
    ADD COLUMN IF NOT EXISTS score_zscore  REAL,          -- Z-score vs 30-day rolling mean/std
    ADD COLUMN IF NOT EXISTS macro_regime  TEXT,          -- regime at time of scoring
    ADD COLUMN IF NOT EXISTS data_tier     TEXT DEFAULT 'T2',  -- T1 / T2 / T2_historical
    ADD COLUMN IF NOT EXISTS raw_cis_score REAL,          -- pre-regime-adjustment composite score
    ADD COLUMN IF NOT EXISTS las           REAL,          -- Liquidity-Adjusted Score
    ADD COLUMN IF NOT EXISTS confidence    REAL;          -- data completeness 0-1

-- ─── 2. New index for time-series queries ────────────────────────────────────

-- Covering index for regime-filtered time-series queries
CREATE INDEX IF NOT EXISTS idx_cis_scores_symbol_regime_time
    ON cis_scores (symbol, macro_regime, recorded_at DESC);

-- For velocity queries: latest N rows per symbol
CREATE INDEX IF NOT EXISTS idx_cis_scores_data_tier_time
    ON cis_scores (data_tier, recorded_at DESC);

-- ─── 3. cis_score_deltas view — pre-computed velocity signal ─────────────────
-- Used by the Freqtrade adapter and ScoreAnalytics heatmap.
-- Returns the latest score for each symbol plus its delta and Z-score.

CREATE OR REPLACE VIEW cis_score_latest AS
SELECT DISTINCT ON (symbol)
    symbol,
    name,
    score,
    raw_cis_score,
    grade,
    signal,
    pillar_f,
    pillar_m,
    pillar_o,
    pillar_s,
    pillar_a,
    score_delta,
    score_zscore,
    macro_regime,
    data_tier,
    las,
    confidence,
    asset_class,
    recorded_at
FROM cis_scores
ORDER BY symbol, recorded_at DESC;

-- ─── 4. cis_score_history_7d view — grade migration heatmap source ────────────
-- For ScoreAnalytics: last 7 days of scores per symbol, one row per day.

CREATE OR REPLACE VIEW cis_score_history_7d AS
SELECT
    symbol,
    asset_class,
    grade,
    score,
    score_delta,
    macro_regime,
    data_tier,
    recorded_at::date AS score_date,
    recorded_at
FROM (
    SELECT *,
        ROW_NUMBER() OVER (
            PARTITION BY symbol, recorded_at::date
            ORDER BY recorded_at DESC
        ) AS rn
    FROM cis_scores
    WHERE recorded_at >= NOW() - INTERVAL '7 days'
) ranked
WHERE rn = 1
ORDER BY symbol, score_date DESC;

-- ─── 5. cis_regime_fitness view — pillar performance per regime ───────────────
-- The Simons feedback loop: which pillar predicts 7d return in each regime?
-- (Populated once we have 60+ days of history + Freqtrade results)

CREATE TABLE IF NOT EXISTS cis_regime_fitness (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    regime          TEXT NOT NULL,
    pillar          TEXT NOT NULL,   -- F / M / O / S / A
    correlation     REAL,            -- Pearson r vs 7d realized return
    n_samples       INTEGER,
    window_days     INTEGER DEFAULT 30,
    computed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_regime_fitness_regime
    ON cis_regime_fitness (regime, computed_at DESC);

-- ─── 6. cis_backtest_results — Freqtrade results feed-back table ─────────────

CREATE TABLE IF NOT EXISTS cis_backtest_results (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    symbol          TEXT NOT NULL,
    entry_time      TIMESTAMPTZ NOT NULL,
    exit_time       TIMESTAMPTZ,
    entry_price     REAL,
    exit_price      REAL,
    realized_return REAL,            -- % return on the trade
    cis_score_at_entry   REAL,
    grade_at_entry       TEXT,
    signal_at_entry      TEXT,
    pillar_f_entry       REAL,
    pillar_m_entry       REAL,
    pillar_o_entry       REAL,
    pillar_s_entry       REAL,
    pillar_a_entry       REAL,
    macro_regime_entry   TEXT,
    strategy        TEXT DEFAULT 'CISEnhancedStrategy',
    is_dry_run      BOOLEAN DEFAULT TRUE,
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_backtest_symbol_time
    ON cis_backtest_results (symbol, entry_time DESC);

CREATE INDEX IF NOT EXISTS idx_backtest_regime
    ON cis_backtest_results (macro_regime_entry, entry_time DESC);

ALTER TABLE cis_backtest_results ENABLE ROW LEVEL SECURITY;
CREATE POLICY "backtest_select" ON cis_backtest_results FOR SELECT USING (true);
CREATE POLICY "backtest_insert" ON cis_backtest_results FOR INSERT WITH CHECK (true);
