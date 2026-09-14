-- ============================================================================
-- S-336 — the table that never existed. The table the code writes to,
-- reads from, and that the system-of-record for fusion_paper state has
-- been referenced since 2026-08-15 without ever being applied.
--
-- Why this migration exists (2026-09-15, Seth/Cowork lane):
-- 2026-08-15..2026-09-09 produced 26 fusion_paper NAV rows claiming 18
-- positions at gross 0.667 while `daily_return` was IDENTICALLY -cost for
-- 26 days in a row and NAV did not compound (26 days of -5bps should be
-- 0.9871, observed 0.9995). The mechanism was not "the data was wrong" —
-- the mechanism was that the STATE was lost every cycle (the table the
-- durable state was supposed to live in did not exist), so `nav` reset to
-- 1.0 and `w_held` reset to {} on every cycle, the P&L loop over an empty
-- dict never ran, and an empty accumulation was recorded as a flat day.
-- **Every layer was working correctly; together they produced a false
-- record.**
--
-- This is the S-166 class incident (eleven tables the code wrote to did
-- not exist), at the single-table level, with the missing table being the
-- one `_load_state` falls through to from Redis. Sweep on 2026-09-12
-- confirmed this was the only one of the 37 declared tables missing.
--
-- This migration voids the v1 NAV records in place rather than deleting
-- them or "correcting" them: the book never knew what it held, so the true
-- NAVs are unrecoverable. Voided segments are filtered at read time
-- (`inception_id = 'v2' AND void_reason IS NULL`), exactly the discipline
-- beta_core adopted for its v3→v4 transition.
--
-- STRUCTURE NOTE (2026-09-15 hotfix). The first version of this file used
-- a BEGIN/COMMIT wrapper around the whole migration; in Supabase SQL Editor
-- that wrapper interacted badly with partial execution (a single failing
-- statement rolled EVERYTHING back, including the fusion_paper_state
-- CREATE TABLE). This version drops the wrapper and runs each statement
-- in autocommit, with every statement idempotent (IF NOT EXISTS /
-- EXCEPTION / WHERE column IS NULL). Re-running this file from any state
-- (partial, full, or failed) lands in the same final state.
--
-- Idempotent. Safe to re-run. Safe to apply BEFORE the code changes (the
-- `inception_id='v2'` filter is enforced by the reader only, not the
-- writer).
--
-- Rollback:
--   DROP TABLE IF EXISTS public.fusion_paper_state;
--   ALTER TABLE fusion_paper_nav DROP COLUMN IF EXISTS inception_id;
--   ALTER TABLE fusion_paper_nav DROP COLUMN IF EXISTS void_reason;
-- (Do NOT unvoid the 26 rows — there is nothing to recover.)
-- ============================================================================


-- ── STEP 1. Create fusion_paper_state (the table that never existed) ────────
-- Idempotent. Safe to re-run.
CREATE TABLE IF NOT EXISTS public.fusion_paper_state (
    id                      bigserial PRIMARY KEY,
    inception_id            text        NOT NULL,
    last_mark               timestamptz NOT NULL,
    nav                     numeric     NOT NULL CHECK (nav > 0),
    weights                 jsonb       NOT NULL DEFAULT '{}'::jsonb,
    mark_prices             jsonb       NOT NULL DEFAULT '{}'::jsonb,
    prev_prices             jsonb       NOT NULL DEFAULT '{}'::jsonb,
    n_days_marked           integer     NOT NULL DEFAULT 0 CHECK (n_days_marked >= 0),
    cell                    jsonb       NOT NULL DEFAULT '{}'::jsonb,
    detector_fired_today    boolean     NOT NULL DEFAULT false,
    void_reason             text,
    inserted_at             timestamptz NOT NULL DEFAULT now()
);

-- ── STEP 2. Index on (inception_id, last_mark) for the reader ───────────────
CREATE INDEX IF NOT EXISTS fusion_paper_state_inception_mark_idx
    ON public.fusion_paper_state (inception_id, last_mark DESC);

-- ── STEP 3. RLS — anon read, service_role full ──────────────────────────────
-- Same shape as the paper_nav tables (write through service role, read anon
-- for dashboard). Idempotent (ALTER TABLE ENABLE is no-op if already enabled;
-- CREATE POLICY wrapped in EXCEPTION block).
ALTER TABLE public.fusion_paper_state ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
  CREATE POLICY fusion_paper_state_read_anon ON public.fusion_paper_state
    FOR SELECT TO anon USING (true);
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE POLICY fusion_paper_state_all_service ON public.fusion_paper_state
    FOR ALL TO service_role USING (true) WITH CHECK (true);
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

COMMENT ON TABLE public.fusion_paper_state IS
    'CometCloud Layer II/III fusion_paper durable state (S-336). '
    'One row per `_save_state` append; the reader takes the latest by '
    '`last_mark`. void_reason is the operator signal — NULL means live; '
    'non-NULL means the row is preserved but excluded from the curve.';


-- ── STEP 4. Add inception_id + void_reason columns to fusion_paper_nav ──────
-- Idempotent: IF NOT EXISTS means re-runs are no-ops. The verification SELECT
-- at the end of the original migration failed with "column inception_id does
-- not exist" because the ALTER TABLE statements were inside a transaction
-- that got rolled back; here they run independently.
ALTER TABLE fusion_paper_nav ADD COLUMN IF NOT EXISTS inception_id text;
ALTER TABLE fusion_paper_nav ADD COLUMN IF NOT EXISTS void_reason  text;


-- ── STEP 5. Stamp existing rows as v1 with void_reason ──────────────────────
-- Idempotent: WHERE inception_id IS NULL matches zero rows after first run.
-- The 26 rows from 2026-08-15..2026-09-09 are PRESERVED but flagged voided
-- (not deleted) because the book never knew what it held — true NAVs are
-- unrecoverable, so we void rather than fabricate corrections.
UPDATE fusion_paper_nav
   SET inception_id = 'v1',
       void_reason  = 'S-336 — fabricated state. fusion_paper_state never '
                      'existed in Postgres, so w_held was empty every cycle, '
                      'NAV reset to 1.0, and 26 days of empty accumulation '
                      'were written as a flat day. voided not corrected: the '
                      'book never knew what it held. See fusion_paper.py:65.'
 WHERE inception_id IS NULL;


-- ── STEP 6. Force non-null going forward ────────────────────────────────────
-- After STEP 5 every row has inception_id, so SET NOT NULL is safe.
ALTER TABLE fusion_paper_nav ALTER COLUMN inception_id SET NOT NULL;


-- ── STEP 7. CHECK constraint (inception_id IN ('v1','v2')) ──────────────────
-- Idempotent via EXCEPTION block.
DO $$ BEGIN
  ALTER TABLE fusion_paper_nav
    ADD CONSTRAINT fusion_paper_nav_inception_chk
    CHECK (inception_id IN ('v1', 'v2'));
EXCEPTION WHEN duplicate_object THEN NULL; END $$;


-- ── STEP 8. Partial index supports the live-v2 reader filter ────────────────
-- WHERE inception_id='v2' AND void_reason IS NULL — the filter every
-- fusion_paper_nav reader now uses (nav_ledger / weekly_summary /
-- fusion_paper_regime_track).
CREATE INDEX IF NOT EXISTS fusion_paper_nav_v2_live_idx
    ON fusion_paper_nav (ts DESC)
    WHERE inception_id = 'v2' AND void_reason IS NULL;


-- ── STEP 9. Verification (read-only, never errors even if steps above missed)
-- Uses information_schema EXISTS() guards so a missing column or table does
-- not raise — it just reports "missing" as a value. This replaces the
-- verification SELECT in the original migration, which failed the WHOLE
-- transaction on first run.
SELECT
    'fusion_paper_state EXISTS' AS check,
    EXISTS (
        SELECT 1 FROM information_schema.tables
         WHERE table_schema = 'public' AND table_name = 'fusion_paper_state'
    )::text AS value
UNION ALL
SELECT
    'fusion_paper_state row count',
    (SELECT count(*) FROM public.fusion_paper_state)::text
UNION ALL
SELECT
    'fusion_paper_nav inception_id column EXISTS',
    EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_schema = 'public' AND table_name = 'fusion_paper_nav'
           AND column_name = 'inception_id'
    )::text
UNION ALL
SELECT
    'fusion_paper_nav void_reason column EXISTS',
    EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_schema = 'public' AND table_name = 'fusion_paper_nav'
           AND column_name = 'void_reason'
    )::text
UNION ALL
SELECT
    'fusion_paper_nav rows voided (v1 + void_reason NOT NULL)',
    (SELECT count(*) FROM fusion_paper_nav
       WHERE inception_id = 'v1' AND void_reason IS NOT NULL)::text
UNION ALL
SELECT
    'fusion_paper_nav total rows',
    (SELECT count(*) FROM fusion_paper_nav)::text;
