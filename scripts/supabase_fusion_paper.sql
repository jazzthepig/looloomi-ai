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
CREATE POLICY "fusion_paper_nav_select" ON fusion_paper_nav FOR SELECT USING (true);
CREATE POLICY "fusion_paper_nav_insert" ON fusion_paper_nav FOR INSERT WITH CHECK (true);


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
CREATE POLICY "fusion_paper_lifecycle_select" ON fusion_paper_lifecycle FOR SELECT USING (true);
CREATE POLICY "fusion_paper_lifecycle_insert" ON fusion_paper_lifecycle FOR INSERT WITH CHECK (true);
