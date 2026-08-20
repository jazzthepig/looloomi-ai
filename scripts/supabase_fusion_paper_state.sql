-- fusion_paper_state — durable state for the R64 fusion paper book (S-176, 2026-08-19)
--
-- WHY THIS TABLE EXISTS.
-- The fusion paper book wrote its state to Redis only. Redis lost it between
-- daily marks (root cause still being diagnosed: UPSTASH_REDIS_REST_URL config
-- vs key path vs TTL), and 5 days of marks came back with identical
-- NAV=0.9995 / daily_return=-0.0005 — the no-compounding placeholder. The
-- fix in src/data/signals/fusion_paper.py now writes the state to Supabase
-- AS THE SYSTEM OF RECORD (durable first), with Redis as a cache (best-effort).
-- This table is the durable target.
--
-- RLS: service_role only. The fusion paper book is a system loop, not an
-- investor-facing surface, and the table holds PIT-sensitive P&L state. The
-- same posture as beta_core_nav.
--
-- UNIQUE(last_mark): every daily mark advances the calendar day, so the
-- constraint is the seam between "today's mark" and "yesterday's mark" — a
-- write that would create a second row for the same date is a bug, not a
-- recoverable retry.

CREATE TABLE IF NOT EXISTS fusion_paper_state (
    id BIGSERIAL PRIMARY KEY,
    inception DATE NOT NULL,
    last_mark DATE NOT NULL,
    nav NUMERIC NOT NULL,
    weights JSONB NOT NULL DEFAULT '{}'::jsonb,
    mark_prices JSONB NOT NULL DEFAULT '{}'::jsonb,
    prev_prices JSONB NOT NULL DEFAULT '{}'::jsonb,
    n_days_marked INT NOT NULL DEFAULT 0,
    cell JSONB NOT NULL DEFAULT '{}'::jsonb,
    detector_fired_today BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(last_mark)
);

CREATE INDEX IF NOT EXISTS idx_fusion_state_last_mark_desc
    ON fusion_paper_state(last_mark DESC);

ALTER TABLE fusion_paper_state ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS service_role_only ON fusion_paper_state;
CREATE POLICY service_role_only ON fusion_paper_state
    FOR ALL
    USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');
