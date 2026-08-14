-- ═══════════════════════════════════════════════════════════════════
-- CometCloud AI — Supabase Schema Setup
-- Run in Supabase SQL Editor (Dashboard → SQL Editor → New Query)
-- ═══════════════════════════════════════════════════════════════════

-- 1. CIS Score History — stores every 30-min push from Mac Mini
CREATE TABLE IF NOT EXISTS cis_scores (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    symbol      TEXT NOT NULL,
    name        TEXT,
    score       REAL,
    grade       TEXT,
    signal      TEXT,
    percentile  REAL,
    pillar_f    REAL,
    pillar_m    REAL,
    pillar_o    REAL,
    pillar_s    REAL,
    pillar_a    REAL,
    asset_class TEXT,
    source      TEXT DEFAULT 'local_engine',
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index for sparkline queries: symbol + time range
CREATE INDEX IF NOT EXISTS idx_cis_scores_symbol_time
    ON cis_scores (symbol, recorded_at DESC);

-- Index for class-level aggregation
CREATE INDEX IF NOT EXISTS idx_cis_scores_class_time
    ON cis_scores (asset_class, recorded_at DESC);

-- 2. Row-level security (allow anon reads, service-key writes)
ALTER TABLE cis_scores ENABLE ROW LEVEL SECURITY;

-- Allow anonymous SELECT (dashboard reads)
-- S-167: was `CREATE POLICY "Allow anon read" ON cis_scores FOR SELECT USING (true)`
-- granted to PUBLIC. Measured 2026-08-15: the anon key could read this.
-- Removed live and here. Nothing we ship reads through anon — the frontend
-- goes through /api/v1/* on FastAPI, which holds service_role.
DROP POLICY IF EXISTS "Allow anon read" ON cis_scores;

-- Allow service-role INSERT (Mac Mini pushes via Railway)
-- S-167: was `CREATE POLICY "Allow service insert" ON cis_scores FOR INSERT WITH CHECK (true)`.
-- The NAME said "service"; the policy had no TO clause, so Postgres granted it
-- to PUBLIC. A policy name is a comment — only the TO clause is the grant.
DROP POLICY IF EXISTS "Allow service insert" ON cis_scores;

-- 3. Auto-cleanup: drop rows older than 90 days (pg_cron)
-- NOTE: pg_cron must be enabled in Supabase Dashboard → Database → Extensions
-- After enabling, run:
--
-- SELECT cron.schedule(
--     'cleanup-old-cis-scores',
--     '0 4 * * *',   -- daily at 4am UTC
--     $$DELETE FROM cis_scores WHERE recorded_at < NOW() - INTERVAL '90 days'$$
-- );

-- 4. Macro Brief History (optional — for archiving daily briefs)
CREATE TABLE IF NOT EXISTS macro_briefs (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brief       TEXT NOT NULL,
    model       TEXT,
    data_snapshot JSONB,
    source      TEXT DEFAULT 'local_engine',
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_macro_briefs_time
    ON macro_briefs (recorded_at DESC);

ALTER TABLE macro_briefs ENABLE ROW LEVEL SECURITY;

-- S-167: was `CREATE POLICY "Allow anon read briefs" ON macro_briefs FOR SELECT USING (true)`

-- granted to PUBLIC. Measured 2026-08-15: the anon key could read this.

-- Removed live and here. Nothing we ship reads through anon — the frontend

-- goes through /api/v1/* on FastAPI, which holds service_role.

DROP POLICY IF EXISTS "Allow anon read briefs" ON macro_briefs;

-- S-167: was `CREATE POLICY "Allow service insert briefs" ON macro_briefs FOR INSERT WITH CHECK (true)`.
-- The NAME said "service"; the policy had no TO clause, so Postgres granted it
-- to PUBLIC. A policy name is a comment — only the TO clause is the grant.
DROP POLICY IF EXISTS "Allow service insert briefs" ON macro_briefs;

-- ═══════════════════════════════════════════════════════════════════
-- DONE. Next steps:
--   1. Copy SUPABASE_URL and SUPABASE_KEY (anon key) from:
--      Supabase Dashboard → Settings → API
--   2. Add to Railway environment variables:
--      SUPABASE_URL=https://xxxxx.supabase.co
--      SUPABASE_KEY=eyJhbGciOi...
--   3. Mac Mini scores will auto-persist on next push cycle
-- ═══════════════════════════════════════════════════════════════════
