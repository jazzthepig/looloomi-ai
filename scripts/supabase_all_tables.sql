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
    recorded_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Migration: add columns introduced in later versions (safe to run on existing table)
ALTER TABLE cis_scores ADD COLUMN IF NOT EXISTS regime_transition   BOOLEAN DEFAULT FALSE;
ALTER TABLE cis_scores ADD COLUMN IF NOT EXISTS previous_regime     TEXT;
ALTER TABLE cis_scores ADD COLUMN IF NOT EXISTS data_tier           INTEGER;
ALTER TABLE cis_scores ADD COLUMN IF NOT EXISTS data_quality_score  REAL;
ALTER TABLE cis_scores ADD COLUMN IF NOT EXISTS las                 REAL;
ALTER TABLE cis_scores ADD COLUMN IF NOT EXISTS confidence          REAL;
ALTER TABLE cis_scores ADD COLUMN IF NOT EXISTS score_delta         REAL;
ALTER TABLE cis_scores ADD COLUMN IF NOT EXISTS score_zscore        REAL;
ALTER TABLE cis_scores ADD COLUMN IF NOT EXISTS source              TEXT DEFAULT 'local_engine';

CREATE INDEX IF NOT EXISTS idx_cis_scores_symbol_time
    ON cis_scores (symbol, recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_cis_scores_class_time
    ON cis_scores (asset_class, recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_cis_scores_regime
    ON cis_scores (macro_regime, recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_cis_scores_regime_transition
    ON cis_scores (regime_transition) WHERE regime_transition = TRUE;

ALTER TABLE cis_scores ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "cis_scores_select" ON cis_scores;
DROP POLICY IF EXISTS "cis_scores_insert" ON cis_scores;
-- S-167: was `CREATE POLICY "cis_scores_select" ON cis_scores FOR SELECT USING (true)`
-- granted to PUBLIC. Measured 2026-08-15: the anon key could read this.
-- Removed live and here. Nothing we ship reads through anon — the frontend
-- goes through /api/v1/* on FastAPI, which holds service_role.
DROP POLICY IF EXISTS "cis_scores_select" ON cis_scores;
-- S-167: was `CREATE POLICY "cis_scores_insert" ON cis_scores FOR INSERT` granted to PUBLIC.
-- Removed. service_role bypasses RLS; nothing legitimate needed it.
DROP POLICY IF EXISTS "cis_scores_insert" ON cis_scores;


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
DROP POLICY IF EXISTS "macro_briefs_select" ON macro_briefs;
DROP POLICY IF EXISTS "macro_briefs_insert" ON macro_briefs;
-- S-167: was `CREATE POLICY "macro_briefs_select" ON macro_briefs FOR SELECT USING (true)`
-- granted to PUBLIC. Measured 2026-08-15: the anon key could read this.
-- Removed live and here. Nothing we ship reads through anon — the frontend
-- goes through /api/v1/* on FastAPI, which holds service_role.
DROP POLICY IF EXISTS "macro_briefs_select" ON macro_briefs;
-- S-167: was `CREATE POLICY "macro_briefs_insert" ON macro_briefs FOR INSERT` granted to PUBLIC.
-- Removed. service_role bypasses RLS; nothing legitimate needed it.
DROP POLICY IF EXISTS "macro_briefs_insert" ON macro_briefs;


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
DROP POLICY IF EXISTS "wp_select" ON wallet_profiles;
DROP POLICY IF EXISTS "wp_insert" ON wallet_profiles;
DROP POLICY IF EXISTS "wp_update" ON wallet_profiles;
-- S-167: was `CREATE POLICY "wp_select" ON wallet_profiles FOR SELECT USING (true)`
-- granted to PUBLIC. Measured 2026-08-15: the anon key could read this.
-- Removed live and here. Nothing we ship reads through anon — the frontend
-- goes through /api/v1/* on FastAPI, which holds service_role.
DROP POLICY IF EXISTS "wp_select" ON wallet_profiles;
-- S-167: was `CREATE POLICY "wp_insert" ON wallet_profiles FOR INSERT` granted to PUBLIC.
-- Removed. service_role bypasses RLS; nothing legitimate needed it.
DROP POLICY IF EXISTS "wp_insert" ON wallet_profiles;
-- S-167: was `CREATE POLICY "wp_update" ON wallet_profiles FOR UPDATE` granted to PUBLIC.
-- Removed. service_role bypasses RLS; nothing legitimate needed it.
DROP POLICY IF EXISTS "wp_update" ON wallet_profiles;


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
DROP POLICY IF EXISTS "trade_results_select" ON trade_results;
DROP POLICY IF EXISTS "trade_results_insert" ON trade_results;
-- S-167: was `CREATE POLICY "trade_results_select" ON trade_results FOR SELECT USING (true)`
-- granted to PUBLIC. Measured 2026-08-15: the anon key could read this.
-- Removed live and here. Nothing we ship reads through anon — the frontend
-- goes through /api/v1/* on FastAPI, which holds service_role.
DROP POLICY IF EXISTS "trade_results_select" ON trade_results;
-- S-167: was `CREATE POLICY "trade_results_insert" ON trade_results FOR INSERT` granted to PUBLIC.
-- Removed. service_role bypasses RLS; nothing legitimate needed it.
DROP POLICY IF EXISTS "trade_results_insert" ON trade_results;


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
DROP POLICY IF EXISTS "agent_call_log_select" ON agent_call_log;
DROP POLICY IF EXISTS "agent_call_log_insert" ON agent_call_log;
-- S-167: was `CREATE POLICY "agent_call_log_select" ON agent_call_log FOR SELECT USING (true)`
-- granted to PUBLIC. Measured 2026-08-15: the anon key could read this.
-- Removed live and here. Nothing we ship reads through anon — the frontend
-- goes through /api/v1/* on FastAPI, which holds service_role.
DROP POLICY IF EXISTS "agent_call_log_select" ON agent_call_log;
-- S-167: was `CREATE POLICY "agent_call_log_insert" ON agent_call_log FOR INSERT` granted to PUBLIC.
-- Removed. service_role bypasses RLS; nothing legitimate needed it.
DROP POLICY IF EXISTS "agent_call_log_insert" ON agent_call_log;


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


-- ═══════════════════════════════════════════════════════════════════
-- 8. API Keys — Self-serve key issuance (Week 10)
-- ═══════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS api_keys (
    id              BIGSERIAL PRIMARY KEY,
    key_prefix      TEXT NOT NULL UNIQUE,
    key_hash        TEXT NOT NULL UNIQUE,
    name            TEXT,
    email           TEXT,
    notes           TEXT,   -- NAME MATTERS: the live column is `notes`.
                            -- This file said `intended_use` and the table never had it,
                            -- so /api/v1/keys returned "Key storage failed" from the day
                            -- it shipped and zero keys were ever issued. A CREATE TABLE
                            -- script with IF NOT EXISTS never corrects an existing table —
                            -- it silently confirms whatever is already there.
    tier            TEXT NOT NULL DEFAULT 'free',
    rate_limit_rpm  INTEGER NOT NULL DEFAULT 60,    -- matches keys.py
    rate_limit_day  INTEGER NOT NULL DEFAULT 1000,  -- matches keys.py
    active          BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_used_at    TIMESTAMPTZ,
    request_count   BIGINT NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_api_keys_prefix  ON api_keys(key_prefix);
CREATE INDEX IF NOT EXISTS idx_api_keys_hash    ON api_keys(key_hash);
CREATE INDEX IF NOT EXISTS idx_api_keys_email   ON api_keys(email);
CREATE INDEX IF NOT EXISTS idx_api_keys_active  ON api_keys(active) WHERE active = TRUE;

ALTER TABLE api_keys ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "api_keys_insert" ON api_keys;
DROP POLICY IF EXISTS "api_keys_select" ON api_keys;
DROP POLICY IF EXISTS "api_keys_update" ON api_keys;
-- S-167: was `CREATE POLICY "api_keys_insert" ON api_keys FOR INSERT` granted to PUBLIC.
-- Removed. service_role bypasses RLS; nothing legitimate needed it.
DROP POLICY IF EXISTS "api_keys_insert" ON api_keys;
-- S-167: was `CREATE POLICY "api_keys_select" ON api_keys FOR SELECT USING (true)`
-- granted to PUBLIC. Measured 2026-08-15: the anon key could read this.
-- Removed live and here. Nothing we ship reads through anon — the frontend
-- goes through /api/v1/* on FastAPI, which holds service_role.
DROP POLICY IF EXISTS "api_keys_select" ON api_keys;
-- S-167: was `CREATE POLICY "api_keys_update" ON api_keys FOR UPDATE` granted to PUBLIC.
-- Removed. service_role bypasses RLS; nothing legitimate needed it.
DROP POLICY IF EXISTS "api_keys_update" ON api_keys;


-- ═══════════════════════════════════════════════════════════════════
-- 9. Analytics Events — Self-hosted Supabase tracking (Week 10)
-- ═══════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS analytics_events (
    id          BIGSERIAL PRIMARY KEY,
    event       TEXT NOT NULL,
    props       JSONB DEFAULT '{}',
    path        TEXT,
    referrer    TEXT,
    ip_hash     TEXT,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_analytics_event    ON analytics_events(event);
CREATE INDEX IF NOT EXISTS idx_analytics_recorded ON analytics_events(recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_analytics_ip       ON analytics_events(ip_hash);

ALTER TABLE analytics_events ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "analytics_insert" ON analytics_events;
DROP POLICY IF EXISTS "analytics_select" ON analytics_events;
-- S-167: was `CREATE POLICY "analytics_insert" ON analytics_events FOR INSERT` granted to PUBLIC.
-- Removed. service_role bypasses RLS; nothing legitimate needed it.
DROP POLICY IF EXISTS "analytics_insert" ON analytics_events;
-- S-167: was `CREATE POLICY "analytics_select" ON analytics_events FOR SELECT USING (true)`
-- granted to PUBLIC. Measured 2026-08-15: the anon key could read this.
-- Removed live and here. Nothing we ship reads through anon — the frontend
-- goes through /api/v1/* on FastAPI, which holds service_role.
DROP POLICY IF EXISTS "analytics_select" ON analytics_events;


-- ═══════════════════════════════════════════════════════════════════
-- 10. Webhook Subscriptions — Grade-change push delivery (Week 10)
-- ═══════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS webhook_subscriptions (
    id             BIGSERIAL PRIMARY KEY,
    key_prefix     TEXT NOT NULL,
    url            TEXT NOT NULL,
    events         TEXT[] NOT NULL DEFAULT '{GRADE_UPGRADE,GRADE_DOWNGRADE}',
    secret         TEXT NOT NULL,
    active         BOOLEAN NOT NULL DEFAULT TRUE,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_fired_at  TIMESTAMPTZ,
    fire_count     INTEGER NOT NULL DEFAULT 0,
    fail_count     INTEGER NOT NULL DEFAULT 0,
    last_error     TEXT,
    UNIQUE (key_prefix, url)
);

CREATE INDEX IF NOT EXISTS idx_webhook_subs_key_prefix ON webhook_subscriptions(key_prefix);
CREATE INDEX IF NOT EXISTS idx_webhook_subs_active     ON webhook_subscriptions(active) WHERE active = TRUE;

ALTER TABLE webhook_subscriptions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "webhook_subs_insert" ON webhook_subscriptions;
DROP POLICY IF EXISTS "webhook_subs_select" ON webhook_subscriptions;
DROP POLICY IF EXISTS "webhook_subs_update" ON webhook_subscriptions;
DROP POLICY IF EXISTS "webhook_subs_delete" ON webhook_subscriptions;
-- S-167: was `CREATE POLICY "webhook_subs_insert" ON webhook_subscriptions FOR INSERT` granted to PUBLIC.
-- Removed. service_role bypasses RLS; nothing legitimate needed it.
DROP POLICY IF EXISTS "webhook_subs_insert" ON webhook_subscriptions;
-- S-167: was `CREATE POLICY "webhook_subs_select" ON webhook_subscriptions FOR SELECT USING (true)`
-- granted to PUBLIC. Measured 2026-08-15: the anon key could read this.
-- Removed live and here. Nothing we ship reads through anon — the frontend
-- goes through /api/v1/* on FastAPI, which holds service_role.
DROP POLICY IF EXISTS "webhook_subs_select" ON webhook_subscriptions;
-- S-167: was `CREATE POLICY "webhook_subs_update" ON webhook_subscriptions FOR UPDATE` granted to PUBLIC.
-- Removed. service_role bypasses RLS; nothing legitimate needed it.
DROP POLICY IF EXISTS "webhook_subs_update" ON webhook_subscriptions;
-- S-167: was `CREATE POLICY "webhook_subs_delete" ON webhook_subscriptions FOR DELETE` granted to PUBLIC.
-- Removed. service_role bypasses RLS; nothing legitimate needed it.
DROP POLICY IF EXISTS "webhook_subs_delete" ON webhook_subscriptions;

-- ═══════════════════════════════════════════════════════════════════
-- 11. Signal Journal — CIS OUTPERFORM threshold crossings
-- Starts the institutional track record clock.
-- Auto-populated by /internal/cis-scores push path (signals.py).
-- Each row = one tradeable signal (entry + eventual exit).
-- ═══════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS signal_journal (
    id              BIGSERIAL PRIMARY KEY,
    symbol          TEXT NOT NULL,
    asset_class     TEXT,
    grade           TEXT,
    signal          TEXT NOT NULL,            -- OUTPERFORM | STRONG_OUTPERFORM
    cis_score       REAL,
    raw_cis_score   REAL,
    las             REAL,
    pillar_f        REAL,
    pillar_m        REAL,
    pillar_o        REAL,
    pillar_s        REAL,
    pillar_a        REAL,
    macro_regime    TEXT,
    strategy        TEXT DEFAULT 'CIS_THRESHOLD',
    data_tier       INTEGER DEFAULT 2,
    entry_price     REAL,
    exit_price      REAL,
    exit_date       TIMESTAMPTZ,
    exit_reason     TEXT,                     -- DOWNGRADE | STOP_LOSS | TAKE_PROFIT | OPEN
    return_pct      REAL,
    holding_days    REAL,
    signal_date     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sj_symbol    ON signal_journal(symbol);
CREATE INDEX IF NOT EXISTS idx_sj_date      ON signal_journal(signal_date DESC);
CREATE INDEX IF NOT EXISTS idx_sj_signal    ON signal_journal(signal);
CREATE INDEX IF NOT EXISTS idx_sj_regime    ON signal_journal(macro_regime);
CREATE INDEX IF NOT EXISTS idx_sj_class     ON signal_journal(asset_class);
CREATE INDEX IF NOT EXISTS idx_sj_open      ON signal_journal(exit_date) WHERE exit_date IS NULL;

ALTER TABLE signal_journal ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "sj_select" ON signal_journal;
DROP POLICY IF EXISTS "sj_insert" ON signal_journal;
DROP POLICY IF EXISTS "sj_update" ON signal_journal;
-- S-167: was `CREATE POLICY "sj_select" ON signal_journal FOR SELECT USING (true)`
-- granted to PUBLIC. Measured 2026-08-15: the anon key could read this.
-- Removed live and here. Nothing we ship reads through anon — the frontend
-- goes through /api/v1/* on FastAPI, which holds service_role.
DROP POLICY IF EXISTS "sj_select" ON signal_journal;
-- S-167: was `CREATE POLICY "sj_insert" ON signal_journal FOR INSERT` granted to PUBLIC.
-- Removed. service_role bypasses RLS; nothing legitimate needed it.
DROP POLICY IF EXISTS "sj_insert" ON signal_journal;
-- S-167: was `CREATE POLICY "sj_update" ON signal_journal FOR UPDATE` granted to PUBLIC.
-- Removed. service_role bypasses RLS; nothing legitimate needed it.
DROP POLICY IF EXISTS "sj_update" ON signal_journal;


-- Atomic delivery counter increment (called by webhooks.py _sb_increment)
CREATE OR REPLACE FUNCTION increment_webhook_delivery(
    p_key_prefix TEXT,
    p_url        TEXT,
    p_success    BOOLEAN
) RETURNS void AS $$
BEGIN
    IF p_success THEN
        UPDATE webhook_subscriptions
        SET fire_count = fire_count + 1
        WHERE key_prefix = p_key_prefix AND url = p_url;
    ELSE
        UPDATE webhook_subscriptions
        SET fail_count = fail_count + 1
        WHERE key_prefix = p_key_prefix AND url = p_url;
    END IF;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- SECURITY (2026-08-09): SECURITY DEFINER must never keep the default PUBLIC grant.
revoke all on function increment_webhook_delivery(text, text, boolean) from public, anon, authenticated;
grant execute on function increment_webhook_delivery(text, text, boolean) to service_role;


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

DROP POLICY IF EXISTS "agent_call_log_no_public_write" ON agent_call_log;
DROP POLICY IF EXISTS "analytics_events_no_public_write" ON analytics_events;
DROP POLICY IF EXISTS "api_keys_no_public_write" ON api_keys;
DROP POLICY IF EXISTS "cis_scores_no_public_write" ON cis_scores;
DROP POLICY IF EXISTS "macro_briefs_no_public_write" ON macro_briefs;
DROP POLICY IF EXISTS "signal_journal_no_public_write" ON signal_journal;
DROP POLICY IF EXISTS "trade_results_no_public_write" ON trade_results;
DROP POLICY IF EXISTS "wallet_profiles_no_public_write" ON wallet_profiles;
DROP POLICY IF EXISTS "webhook_subscriptions_no_public_write" ON webhook_subscriptions;
