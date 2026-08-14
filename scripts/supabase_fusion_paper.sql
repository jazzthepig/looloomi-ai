-- R65/R66 fusion paper-book persistence
-- Run once in the Supabase SQL editor. All statements are idempotent.
-- Railway writes through the configured SUPABASE_KEY; the public read policies support
-- the existing paper-book and monitoring endpoints.

CREATE TABLE IF NOT EXISTS fusion_paper_nav (
    id                         BIGSERIAL PRIMARY KEY,
    mark_date                  DATE NOT NULL UNIQUE,
    nav                        DOUBLE PRECISION NOT NULL,
    daily_return               DOUBLE PRECISION,
    gross                      DOUBLE PRECISION,
    n_positions                INTEGER,
    cost                       DOUBLE PRECISION,
    fill_ratio_overall         DOUBLE PRECISION,
    weighted_slippage_bps      DOUBLE PRECISION,
    capacity_status            TEXT,
    capacity_used_pct          DOUBLE PRECISION,
    detector_fired             BOOLEAN,
    cell_w_r46                 DOUBLE PRECISION,
    top_longs                  TEXT,
    top_shorts                 TEXT,
    note                       TEXT,
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_fusion_paper_nav_date
    ON fusion_paper_nav (mark_date ASC);

ALTER TABLE fusion_paper_nav ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "fusion_paper_nav_select" ON fusion_paper_nav;
DROP POLICY IF EXISTS "fusion_paper_nav_insert" ON fusion_paper_nav;
-- S-167: was `CREATE POLICY "fusion_paper_nav_select" ON fusion_paper_nav FOR SELECT USING (true)`
-- granted to PUBLIC. Measured 2026-08-15: the anon key could read this.
-- Removed live and here. Nothing we ship reads through anon — the frontend
-- goes through /api/v1/* on FastAPI, which holds service_role.
DROP POLICY IF EXISTS "fusion_paper_nav_select" ON fusion_paper_nav;
-- S-167: was `CREATE POLICY "fusion_paper_nav_insert" ON fusion_paper_nav FOR INSERT` granted to PUBLIC.
-- Removed. service_role bypasses RLS; nothing legitimate needed it.
DROP POLICY IF EXISTS "fusion_paper_nav_insert" ON fusion_paper_nav;


CREATE TABLE IF NOT EXISTS fusion_paper_lifecycle (
    id                         BIGSERIAL PRIMARY KEY,
    event_date                 DATE NOT NULL,
    event_type                 TEXT NOT NULL,
    payload                    JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_fusion_paper_lifecycle_date
    ON fusion_paper_lifecycle (event_date ASC);
CREATE INDEX IF NOT EXISTS idx_fusion_paper_lifecycle_type
    ON fusion_paper_lifecycle (event_type, event_date ASC);

ALTER TABLE fusion_paper_lifecycle ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "fusion_paper_lifecycle_select" ON fusion_paper_lifecycle;
DROP POLICY IF EXISTS "fusion_paper_lifecycle_insert" ON fusion_paper_lifecycle;
-- S-167: was `CREATE POLICY "fusion_paper_lifecycle_select" ON fusion_paper_lifecycle FOR SELECT USING (true)`
-- granted to PUBLIC. Measured 2026-08-15: the anon key could read this.
-- Removed live and here. Nothing we ship reads through anon — the frontend
-- goes through /api/v1/* on FastAPI, which holds service_role.
DROP POLICY IF EXISTS "fusion_paper_lifecycle_select" ON fusion_paper_lifecycle;
-- S-167: was `CREATE POLICY "fusion_paper_lifecycle_insert" ON fusion_paper_lifecycle FOR INSERT` granted to PUBLIC.
-- Removed. service_role bypasses RLS; nothing legitimate needed it.
DROP POLICY IF EXISTS "fusion_paper_lifecycle_insert" ON fusion_paper_lifecycle;


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

DROP POLICY IF EXISTS "fusion_paper_lifecycle_no_public_write" ON fusion_paper_lifecycle;
DROP POLICY IF EXISTS "fusion_paper_nav_no_public_write" ON fusion_paper_nav;
