-- ═══════════════════════════════════════════════════════════════════
-- CometCloud AI — Data Landing Migration (2026-06-14)
-- Adds the 3 missing tables the data-landing audit endpoint expects:
--   1. cis_backtest_results  — every /api/v1/cis/backtest call persists here
--   2. cis_regime_fitness    — Pearson IC per pillar × regime, daily
--   3. ohlcv_daily           — CoinGecko Pro market_chart, daily candles, 84 assets
-- Idempotent — safe to re-run.
-- URL: https://supabase.com/dashboard/project/soupjamxlfsmgmmtoeok/sql/new
-- ═══════════════════════════════════════════════════════════════════


-- ── 1. CIS Backtest Results ───────────────────────────────────────────────
-- Persists every /api/v1/cis/backtest invocation so the API result and the
-- data-layer write are one source of truth (currently the endpoint reads
-- backtest_results.json from disk or history_db — neither writes here).
CREATE TABLE IF NOT EXISTS cis_backtest_results (
    id              BIGSERIAL PRIMARY KEY,
    run_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    window_days     INTEGER NOT NULL DEFAULT 30,
    grade_a_avg     REAL,
    grade_b_avg     REAL,
    grade_c_avg     REAL,
    grade_d_avg     REAL,
    grade_f_avg     REAL,
    spread_a_to_f   REAL,
    asset_count     INTEGER,
    n_with_klines   INTEGER,
    source_file     TEXT,
    source_db       BOOLEAN DEFAULT FALSE,
    notes           TEXT,
    payload         JSONB
);

CREATE INDEX IF NOT EXISTS idx_cbr_run_at ON cis_backtest_results(run_at DESC);
CREATE INDEX IF NOT EXISTS idx_cbr_window ON cis_backtest_results(window_days);

ALTER TABLE cis_backtest_results ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "cbr_select" ON cis_backtest_results;
DROP POLICY IF EXISTS "cbr_insert" ON cis_backtest_results;
CREATE POLICY "cbr_select" ON cis_backtest_results FOR SELECT USING (true);
CREATE POLICY "cbr_insert" ON cis_backtest_results FOR INSERT WITH CHECK (true);


-- ── 2. CIS Regime Fitness (Simons feedback) ───────────────────────────────
-- Pearson r(pillar, 7d_return) per (pillar, regime) bucket. Written by
-- scripts/compute_regime_fitness.py — wrapped as a Railway callable so the
-- loop runs daily without the Mac Mini cron.
CREATE TABLE IF NOT EXISTS cis_regime_fitness (
    id              BIGSERIAL PRIMARY KEY,
    computed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    regime          TEXT NOT NULL,
    pillar          TEXT NOT NULL,
    pearson_r       REAL,
    p_value         REAL,
    sample_size     INTEGER,
    mean_return     REAL,
    return_source   TEXT,
    window_days     INTEGER NOT NULL DEFAULT 90,
    notes           TEXT
);

CREATE INDEX IF NOT EXISTS idx_crf_computed_at ON cis_regime_fitness(computed_at DESC);
CREATE INDEX IF NOT EXISTS idx_crf_regime_pillar ON cis_regime_fitness(regime, pillar, computed_at DESC);

ALTER TABLE cis_regime_fitness ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "crf_select" ON cis_regime_fitness;
DROP POLICY IF EXISTS "crf_insert" ON cis_regime_fitness;
CREATE POLICY "crf_select" ON cis_regime_fitness FOR SELECT USING (true);
CREATE POLICY "crf_insert" ON cis_regime_fitness FOR INSERT WITH CHECK (true);


-- ── 3. OHLCV Daily (CoinGecko Pro market_chart) ───────────────────────────
-- Daily candles for the 84 CIS universe assets, sourced from CoinGecko Pro
-- /coins/{id}/market_chart (geo-safe from Railway). Mac Mini parquet
-- (/Volumes/CometCloudAI/data/ohlcv/) is the higher-precision path; this
-- is the Railway-side safety net so backtest + outcome resolution can run
-- even if the local pipeline is dead.
CREATE TABLE IF NOT EXISTS ohlcv_daily (
    id              BIGSERIAL PRIMARY KEY,
    symbol          TEXT NOT NULL,
    asset_class     TEXT,
    trade_date      DATE NOT NULL,
    open            REAL,
    high            REAL,
    low             REAL,
    close           REAL NOT NULL,
    volume          REAL,
    source          TEXT DEFAULT 'coingecko',
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (symbol, trade_date, source)
);

CREATE INDEX IF NOT EXISTS idx_od_symbol_date ON ohlcv_daily(symbol, trade_date DESC);
CREATE INDEX IF NOT EXISTS idx_od_class_date   ON ohlcv_daily(asset_class, trade_date DESC);
CREATE INDEX IF NOT EXISTS idx_od_recorded     ON ohlcv_daily(recorded_at DESC);

ALTER TABLE ohlcv_daily ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "od_select" ON ohlcv_daily;
DROP POLICY IF EXISTS "od_insert" ON ohlcv_daily;
DROP POLICY IF EXISTS "od_update" ON ohlcv_daily;
CREATE POLICY "od_select" ON ohlcv_daily FOR SELECT USING (true);
CREATE POLICY "od_insert" ON ohlcv_daily FOR INSERT WITH CHECK (true);
CREATE POLICY "od_update" ON ohlcv_daily FOR UPDATE USING (true);
