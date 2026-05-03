-- ═══════════════════════════════════════════════════════════════════
-- CometCloud AI — Complete Supabase Schema
-- Run this ONCE in Supabase SQL Editor
-- Dashboard → SQL Editor → New Query → paste → Run
-- URL: https://supabase.com/dashboard/project/soupjamxlfsmgmmtoeok/sql/new
--
-- NOTE: All CREATE TABLE statements use IF NOT EXISTS so this script is
-- idempotent — safe to re-run for Simons Upgrade migrations.
-- ═══════════════════════════════════════════════════════════════════

-- ═══════════════════════════════════════════════════════════════════
-- 1. CIS Score History — v4.2 enhanced (Simons Upgrade)
-- ═══════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS cis_scores (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    symbol              TEXT NOT NULL,
    name                TEXT,
    score               REAL,
    raw_cis_score       REAL,
    grade               TEXT,
    signal              TEXT,
    percentile          REAL,
    pillar_f            REAL,
    pillar_m            REAL,
    pillar_o            REAL,
    pillar_s            REAL,
    pillar_a            REAL,
    asset_class         TEXT,
    macro_regime        TEXT,
    regime_transition   BOOLEAN DEFAULT FALSE,
    previous_regime     TEXT,
    data_tier           INTEGER,
    data_quality_score  REAL,
    las                 REAL,
    confidence          REAL,
    score_delta         REAL,
    score_zscore        REAL,
    source              TEXT DEFAULT 'local_engine',
    recorded_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cis_scores_symbol_time
    ON cis_scores (symbol, recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_cis_scores_class_time
    ON cis_scores (asset_class, recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_cis_scores_regime
    ON cis_scores (macro_regime, recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_cis_scores_regime_transition
    ON cis_scores (regime_transition) WHERE regime_transition = TRUE;

ALTER TABLE cis_scores ENABLE ROW LEVEL SECURITY;
CREATE POLICY "cis_scores_select" ON cis_scores FOR SELECT USING (true);
CREATE POLICY "cis_scores_insert" ON cis_scores FOR INSERT WITH CHECK (true);


-- ═══════════════════════════════════════════════════════════════════
-- 2. Macro Brief History
-- ═══════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS macro_briefs (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brief         TEXT NOT NULL,
    model         TEXT,
    data_snapshot JSONB,
    source        TEXT DEFAULT 'local_engine',
    recorded_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_macro_briefs_time
    ON macro_briefs (recorded_at DESC);

ALTER TABLE macro_briefs ENABLE ROW LEVEL SECURITY;
CREATE POLICY "macro_briefs_select" ON macro_briefs FOR SELECT USING (true);
CREATE POLICY "macro_briefs_insert" ON macro_briefs FOR INSERT WITH CHECK (true);


-- ═══════════════════════════════════════════════════════════════════
-- 3. Wallet Auth Profiles
-- ═══════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS wallet_profiles (
    wallet_address TEXT PRIMARY KEY,
    display_name   TEXT,
    nonce          TEXT,
    created_at     TIMESTAMPTZ DEFAULT NOW(),
    last_seen      TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE wallet_profiles ENABLE ROW LEVEL SECURITY;
CREATE POLICY "wp_select" ON wallet_profiles FOR SELECT TO anon USING (true);
CREATE POLICY "wp_insert" ON wallet_profiles FOR INSERT TO anon WITH CHECK (true);
CREATE POLICY "wp_update" ON wallet_profiles FOR UPDATE TO anon USING (true);


-- ═══════════════════════════════════════════════════════════════════
-- 4. Investor Leads
-- ═══════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS leads (
    id               uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    name             text NOT NULL,
    email            text NOT NULL,
    organization     text,
    investment_range text,
    message          text,
    ref              text,
    source_page      text DEFAULT 'strategy',
    status           text DEFAULT 'new',
    created_at       timestamptz DEFAULT now()
);

ALTER TABLE leads ENABLE ROW LEVEL SECURITY;
CREATE INDEX IF NOT EXISTS idx_leads_ref        ON leads(ref);
CREATE INDEX IF NOT EXISTS idx_leads_created_at ON leads(created_at DESC);


-- ═══════════════════════════════════════════════════════════════════
-- 5. Vault Deposit Intents
-- ═══════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS vault_deposit_intents (
    id             uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    wallet_address text NOT NULL,
    vault_id       text,
    vault_address  text,
    partner        text,
    amount_usdc    numeric,
    tx_signature   text UNIQUE,
    memo_data      jsonb,
    source         text DEFAULT 'cometcloud',
    created_at     timestamptz DEFAULT now()
);

ALTER TABLE vault_deposit_intents ENABLE ROW LEVEL SECURITY;
CREATE INDEX IF NOT EXISTS idx_vdi_wallet  ON vault_deposit_intents(wallet_address);
CREATE INDEX IF NOT EXISTS idx_vdi_partner ON vault_deposit_intents(partner);


-- ═══════════════════════════════════════════════════════════════════
-- 6. Trade Results — Simons Upgrade P0.1
-- Closed loop: scores drive allocations → allocations produce results → results update the model.
-- Every Freqtrade trade (dry-run + backtest) writes here.
-- ═══════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS trade_results (
    id                    BIGSERIAL PRIMARY KEY,
    symbol                TEXT NOT NULL,
    side                  TEXT,
    entry_time            TIMESTAMPTZ NOT NULL,
    exit_time             TIMESTAMPTZ,
    entry_price           REAL,
    exit_price            REAL,
    profit_pct            REAL,
    profit_abs            REAL,
    exit_reason           TEXT,
    enter_tag             TEXT,
    strategy              TEXT,
    cis_score_at_entry    REAL,
    cis_grade_at_entry    TEXT,
    pillar_f_at_entry     REAL,
    pillar_m_at_entry     REAL,
    pillar_o_at_entry     REAL,
    pillar_s_at_entry     REAL,
    pillar_a_at_entry     REAL,
    macro_regime_at_entry TEXT,
    realized_return_7d    REAL,
    recorded_at           TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_trade_results_symbol     ON trade_results(symbol);
CREATE INDEX IF NOT EXISTS idx_trade_results_entry_time ON trade_results(entry_time);
CREATE INDEX IF NOT EXISTS idx_trade_results_exit_time  ON trade_results(exit_time);
CREATE INDEX IF NOT EXISTS idx_trade_results_realized_7d ON trade_results(realized_return_7d)
    WHERE realized_return_7d IS NOT NULL;

ALTER TABLE trade_results ENABLE ROW LEVEL SECURITY;
CREATE POLICY "trade_results_select" ON trade_results FOR SELECT USING (true);
CREATE POLICY "trade_results_insert" ON trade_results FOR INSERT WITH CHECK (true);


-- ═══════════════════════════════════════════════════════════════════
-- 7. Agent Call Log — Simons Upgrade P2.1
-- Behavioral moat: which assets AI agents are querying before price moves.
-- Write is async fire-and-forget from MCP server to avoid latency impact.
-- ═══════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS agent_call_log (
    id                  BIGSERIAL PRIMARY KEY,
    tool_name           TEXT,
    symbol              TEXT,
    agent_id            TEXT,
    latency_ms          REAL,
    response_size_bytes INTEGER,
    recorded_at         TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_call_log_tool     ON agent_call_log(tool_name);
CREATE INDEX IF NOT EXISTS idx_agent_call_log_symbol   ON agent_call_log(symbol);
CREATE INDEX IF NOT EXISTS idx_agent_call_log_recorded ON agent_call_log(recorded_at DESC);

ALTER TABLE agent_call_log ENABLE ROW LEVEL SECURITY;
CREATE POLICY "agent_call_log_select" ON agent_call_log FOR SELECT USING (true);
CREATE POLICY "agent_call_log_insert" ON agent_call_log FOR INSERT WITH CHECK (true);


-- ═══════════════════════════════════════════════════════════════════
-- Regime Transitions View — Simons Upgrade P1.1
-- Convenience view for querying recent regime transitions.
-- ═══════════════════════════════════════════════════════════════════
CREATE OR REPLACE VIEW regime_transitions AS
    SELECT
        symbol,
        macro_regime,
        previous_regime,
        recorded_at
    FROM cis_scores
    WHERE regime_transition = TRUE
    ORDER BY recorded_at DESC;
