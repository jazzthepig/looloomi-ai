-- fusion_paper_regime_track — durable storage for the R64 regime-adjusted paper curve
-- (S-369 1.4, 2026-09-20; A-369 diagnostic → Seth handoff).
--
-- WHY THIS TABLE EXISTS.
-- `src/research/validation/fusion_paper_regime_track.py` writes regime-adjusted
-- daily marks to /tmp CSV. /tmp is ephemeral (Railway deploys wipe it; Mac reboots
-- wipe it) — **the only durable write target was Supabase, but the table did not
-- exist (PGRST205 measured 2026-09-17 by A-369 probe)**. Result: writes failed
-- silently, /tmp CSV was the de facto sole source of truth, and every deploy
-- silently zeroed the regime_track history. This table makes Supabase the system
-- of record; /tmp CSV becomes a redundant cache the writer rebuilds on read miss.
--
-- Schema mirrors `fusion_paper_state` (S-176): one row per day, BIGSERIAL id,
-- UNIQUE(date_utc) for upsert via `Prefer: resolution=merge-duplicates`.
-- The Python writer passes this header in `_supabase_write_track()`.
--
-- RLS posture matches `fusion_paper_state`: service_role ONLY. No PUBLIC writes.
-- The regime_track is internal paper-book telemetry, not an investor surface; the
-- anon key does not need it. If a future dashboard reads it, route through FastAPI
-- `/api/v1/*` which holds service_role — same posture as `fusion_paper_nav` (S-167).
--
-- Idempotent: CREATE TABLE IF NOT EXISTS + DROP POLICY IF EXISTS.

CREATE TABLE IF NOT EXISTS fusion_paper_regime_track (
    id                  BIGSERIAL PRIMARY KEY,
    date_utc            DATE NOT NULL UNIQUE,
    band                TEXT NOT NULL,
    exposure_cap        DOUBLE PRECISION NOT NULL,
    signal_value        DOUBLE PRECISION,                          -- NULL when signal window incomplete
    r77_daily_return    DOUBLE PRECISION NOT NULL,
    regime_daily_return DOUBLE PRECISION NOT NULL,
    regime_pnl_usd      DOUBLE PRECISION NOT NULL,
    regime_nav_usd      DOUBLE PRECISION NOT NULL,
    note                TEXT,                                       -- future hook for soft-delete / void
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_fusion_paper_regime_track_date_desc
    ON fusion_paper_regime_track (date_utc DESC);

-- updated_at trigger: bump on row update
CREATE OR REPLACE FUNCTION fusion_paper_regime_track_touch_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_fusion_paper_regime_track_touch ON fusion_paper_regime_track;
CREATE TRIGGER trg_fusion_paper_regime_track_touch
    BEFORE UPDATE ON fusion_paper_regime_track
    FOR EACH ROW
    EXECUTE FUNCTION fusion_paper_regime_track_touch_updated_at();

ALTER TABLE fusion_paper_regime_track ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS service_role_only ON fusion_paper_regime_track;
CREATE POLICY service_role_only ON fusion_paper_regime_track
    FOR ALL
    USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');

-- Verify block (run after applying):
--   SELECT column_name, data_type FROM information_schema.columns
--   WHERE table_name = 'fusion_paper_regime_track' ORDER BY ordinal_position;
-- Expected rows: id (bigint), date_utc (date), band (text), exposure_cap (double precision),
--   signal_value (double precision), r77_daily_return (double precision),
--   regime_daily_return (double precision), regime_pnl_usd (double precision),
--   regime_nav_usd (double precision), note (text), created_at (timestamp with time zone),
--   updated_at (timestamp with time zone).