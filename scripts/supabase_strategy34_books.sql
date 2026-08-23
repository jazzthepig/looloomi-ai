-- Strategy 3 (pod aggregator) + Strategy 4 (cross-asset factor tilt) book tables
-- S-201, Seth, 2026-08-23. Applied to production the same day.
--
-- ⚠️ WHY THIS FILE EXISTS ALONGSIDE THE MIGRATION. It was applied through the
-- Supabase MCP, which does not pass through preflight or git. Measured
-- 2026-08-20: `scripts/*.sql` had ALREADY drifted from the database —
-- `asset_embeddings.superseded_reason` and `beta_core_nav.exposure_cap` exist
-- live and appear in no CREATE TABLE, which made a schema guard report three
-- false positives and zero true ones. Applying by MCP and not writing the SQL
-- down deepens exactly that. Both, always.
--
-- ⚠️ TWO OF THESE FOUR HAVE NO WRITER YET.
--   pod_aggregator_state · factor_tilt_state   — written today
--   pod_aggregator_nav   · factor_tilt_nav     — DECLARED, NOT WRITTEN
--
-- The books define `NAV_TABLE = "..."` and factor_tilt_paper.py:15 says
-- "8. Persist NAV row to Supabase `factor_tilt_nav` table" — the intent is
-- explicit, the call is absent. Created anyway so the writer has a matching
-- shape to land into, and recorded here so they do not become the next
-- `experiment_runs.dsr`: a column that existed from the day the table was
-- created, was never populated once, and made a missing check look handled.
-- If these are still empty in a week, either the writer lands or the constant
-- goes.
--
-- RLS SHAPE. `USING (auth.role() = 'service_role')` is PERMISSIVE and denies
-- others only because no other policy exists. S-179 measured the failure: two
-- permissive policies are OR'd, so a later `USING(true)` silently opens the
-- table and `USING(false)` subtracts nothing. Any additional policy here must
-- be AS RESTRICTIVE.

CREATE TABLE IF NOT EXISTS pod_aggregator_state (
    id BIGSERIAL PRIMARY KEY,
    inception DATE NOT NULL,
    last_mark DATE NOT NULL,
    nav NUMERIC NOT NULL,
    weights JSONB NOT NULL DEFAULT '{}'::jsonb,
    survivors JSONB NOT NULL DEFAULT '[]'::jsonb,
    pods_dropped JSONB NOT NULL DEFAULT '[]'::jsonb,
    breakers_tripped JSONB NOT NULL DEFAULT '[]'::jsonb,
    max_corr_retained NUMERIC,
    n_days_marked INT NOT NULL DEFAULT 0,
    cell JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(last_mark)
);
CREATE INDEX IF NOT EXISTS idx_pod_aggregator_state_last_mark_desc
    ON pod_aggregator_state(last_mark DESC);

CREATE TABLE IF NOT EXISTS factor_tilt_state (
    id BIGSERIAL PRIMARY KEY,
    inception DATE NOT NULL,
    last_mark DATE NOT NULL,
    nav NUMERIC NOT NULL,
    weights JSONB NOT NULL DEFAULT '{}'::jsonb,
    factor_sharpe_attribution JSONB NOT NULL DEFAULT '{}'::jsonb,
    n_days_marked INT NOT NULL DEFAULT 0,
    cell JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(last_mark)
);
CREATE INDEX IF NOT EXISTS idx_factor_tilt_state_last_mark_desc
    ON factor_tilt_state(last_mark DESC);

-- Shapes derived from each book's mark_and_rebalance() return dict.
CREATE TABLE IF NOT EXISTS pod_aggregator_nav (
    mark_date DATE PRIMARY KEY,
    nav NUMERIC NOT NULL,
    daily_return NUMERIC,
    n_days_marked INT,
    validated BOOLEAN NOT NULL DEFAULT false,
    weights JSONB NOT NULL DEFAULT '{}'::jsonb,
    survivors JSONB NOT NULL DEFAULT '[]'::jsonb,
    pods_dropped JSONB NOT NULL DEFAULT '[]'::jsonb,
    breakers_tripped JSONB NOT NULL DEFAULT '[]'::jsonb,
    max_corr_retained NUMERIC,
    note TEXT,
    marked_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS factor_tilt_nav (
    mark_date DATE PRIMARY KEY,
    nav NUMERIC NOT NULL,
    daily_return NUMERIC,
    excess_vs_bench NUMERIC,
    n_days_marked INT,
    validated BOOLEAN NOT NULL DEFAULT false,
    factor_attribution JSONB NOT NULL DEFAULT '{}'::jsonb,
    max_single_factor_sharpe_share NUMERIC,
    note TEXT,
    marked_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE pod_aggregator_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE factor_tilt_state    ENABLE ROW LEVEL SECURITY;
ALTER TABLE pod_aggregator_nav   ENABLE ROW LEVEL SECURITY;
ALTER TABLE factor_tilt_nav      ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS service_role_only ON pod_aggregator_state;
CREATE POLICY service_role_only ON pod_aggregator_state FOR ALL
    USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');
DROP POLICY IF EXISTS service_role_only ON factor_tilt_state;
CREATE POLICY service_role_only ON factor_tilt_state FOR ALL
    USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');
DROP POLICY IF EXISTS service_role_only ON pod_aggregator_nav;
CREATE POLICY service_role_only ON pod_aggregator_nav FOR ALL
    USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');
DROP POLICY IF EXISTS service_role_only ON factor_tilt_nav;
CREATE POLICY service_role_only ON factor_tilt_nav FOR ALL
    USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');
