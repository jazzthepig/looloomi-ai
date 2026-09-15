-- ============================================================================
-- S-336 RECOVERY — drops the partial state and recreates cleanly.
--
-- Why this file exists (supersedes 2026-09-15_s336_fusion_paper_state.sql
-- in practice):
--   Jazz's insight: CREATE TABLE IF NOT EXISTS does NOT update an existing
--   table — if the table already exists with a partial schema (some columns
--   missing), the CREATE TABLE is a no-op and the table is left in the
--   broken state. Subsequent CREATE INDEX / verification SELECT statements
--   then fail with "column inception_id does not exist" because the column
--   the earlier CREATE TABLE was supposed to define was never added.
--
-- What this file does:
--   STEP 0  Diagnostic SELECTs — show exactly what's broken RIGHT NOW.
--   STEP 1  DROP TABLE public.fusion_paper_state (we have no durable state
--           there yet — the original 26 NAV rows are in fusion_paper_nav,
--           not fusion_paper_state; only the v2 marks will go there, and
--           those haven't started).
--   STEP 2  CREATE TABLE public.fusion_paper_state with the full schema.
--   STEP 3  CREATE INDEX / RLS / POLICIES / COMMENT.
--   STEP 4  ALTER TABLE fusion_paper_nav ADD COLUMN IF NOT EXISTS (safe —
--           preserves the 26 real NAV rows, only adds missing columns).
--   STEP 5  UPDATE existing rows to v1 + void_reason (idempotent).
--   STEP 6  NOT NULL + CHECK + partial index.
--   STEP 7  Verification SELECTs using EXISTS() guards so they never error.
--
-- Each statement is autocommit (no BEGIN/COMMIT wrapper). Every statement
-- is idempotent. Re-running this file from any state lands in the same
-- final state.
--
-- ⚠️  STEP 1 IS DESTRUCTIVE: it DROPs public.fusion_paper_state. That's
--     intentional — the table either doesn't exist (no-op) or exists with
--     a partial schema (must be rebuilt). The fusion_paper_state table
--     has NO rows in production yet (the v1 marks never landed there
--     because the table never existed; v2 marks haven't started because
--     the migration hasn't completed).
--
-- Idempotent. Safe to re-run.
-- ============================================================================


-- ── STEP 0. Diagnostic — show current state (read-only, never errors) ───────
SELECT 'BEFORE: fusion_paper_state table' AS check,
       EXISTS (SELECT 1 FROM information_schema.tables
                WHERE table_schema='public' AND table_name='fusion_paper_state')::text
       AS value
UNION ALL
SELECT 'BEFORE: fusion_paper_state columns',
       (SELECT string_agg(column_name, ', ' ORDER BY ordinal_position)
          FROM information_schema.columns
         WHERE table_schema='public' AND table_name='fusion_paper_state')
UNION ALL
SELECT 'BEFORE: fusion_paper_nav inception_id column',
       EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_schema='public' AND table_name='fusion_paper_nav'
                  AND column_name='inception_id')::text
UNION ALL
SELECT 'BEFORE: fusion_paper_nav void_reason column',
       EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_schema='public' AND table_name='fusion_paper_nav'
                  AND column_name='void_reason')::text
UNION ALL
SELECT 'BEFORE: fusion_paper_nav total rows',
       (SELECT count(*) FROM fusion_paper_nav)::text;


-- ── STEP 1. DROP fusion_paper_state — partial schema means we must rebuild ──
-- No production data lives here yet (the 26 v1 marks never landed because
-- the table never existed; v2 hasn't started). DROP + CREATE is the only
-- safe path when CREATE TABLE IF NOT EXISTS would leave a broken schema
-- in place.
DROP TABLE IF EXISTS public.fusion_paper_state CASCADE;


-- ── STEP 2. CREATE TABLE with the FULL schema (no IF NOT EXISTS) ────────────
-- Columns mirror _save_state() in src/data/signals/fusion_paper.py:498 —
-- inception, last_mark, nav, weights, mark_prices, prev_prices,
-- n_days_marked, cell, detector_fired_today — plus the void_reason column
-- the operator uses to exclude segments.
--
-- Many-rows-per-inception allowed: each `_save_state` is an append, so the
-- latest row wins on read (`order=last_mark.desc&limit=1`).
CREATE TABLE public.fusion_paper_state (
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


-- ── STEP 3. Index, RLS, policies, comment ───────────────────────────────────
CREATE INDEX fusion_paper_state_inception_mark_idx
    ON public.fusion_paper_state (inception_id, last_mark DESC);

ALTER TABLE public.fusion_paper_state ENABLE ROW LEVEL SECURITY;

CREATE POLICY fusion_paper_state_read_anon ON public.fusion_paper_state
    FOR SELECT TO anon USING (true);

CREATE POLICY fusion_paper_state_all_service ON public.fusion_paper_state
    FOR ALL TO service_role USING (true) WITH CHECK (true);

COMMENT ON TABLE public.fusion_paper_state IS
    'CometCloud Layer II/III fusion_paper durable state (S-336). '
    'One row per `_save_state` append; the reader takes the latest by '
    '`last_mark`. void_reason is the operator signal — NULL means live; '
    'non-NULL means the row is preserved but excluded from the curve.';


-- ── STEP 4. Add inception_id + void_reason to fusion_paper_nav ──────────────
-- These preserve the 26 real NAV rows (data is intact); only the schema
-- gains columns. ADD COLUMN IF NOT EXISTS is a no-op if columns already
-- exist, so re-running is safe.
ALTER TABLE fusion_paper_nav ADD COLUMN IF NOT EXISTS inception_id text;
ALTER TABLE fusion_paper_nav ADD COLUMN IF NOT EXISTS void_reason  text;


-- ── STEP 5. Stamp the 26 existing rows as v1 (voided) ───────────────────────
-- Idempotent: WHERE inception_id IS NULL matches zero rows after first run.
-- The 26 rows from 2026-08-15..2026-09-09 are PRESERVED but flagged
-- voided (not deleted) because the book never knew what it held — true
-- NAVs are unrecoverable, so we void rather than fabricate corrections.
UPDATE fusion_paper_nav
   SET inception_id = 'v1',
       void_reason  = 'S-336 — fabricated state. fusion_paper_state never existed in Postgres, so w_held was empty every cycle, NAV reset to 1.0, and 26 days of empty accumulation were written as a flat day. voided not corrected: the book never knew what it held. See fusion_paper.py:65.'
 WHERE inception_id IS NULL;


-- ── STEP 6. Force non-null, CHECK constraint, partial index ────────────────
-- After STEP 5 every row has inception_id, so SET NOT NULL is safe.
ALTER TABLE fusion_paper_nav ALTER COLUMN inception_id SET NOT NULL;

-- CHECK constraint — DO block keeps it idempotent (re-running is no-op).
DO $$ BEGIN
  ALTER TABLE fusion_paper_nav
    ADD CONSTRAINT fusion_paper_nav_inception_chk
    CHECK (inception_id IN ('v1', 'v2'));
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- Partial index supports the live-v2 reader filter.
CREATE INDEX IF NOT EXISTS fusion_paper_nav_v2_live_idx
    ON fusion_paper_nav (ts DESC)
    WHERE inception_id = 'v2' AND void_reason IS NULL;


-- ── STEP 7. Verification (read-only, EXISTS()-guarded so it never errors) ──
SELECT 'AFTER: fusion_paper_state table exists' AS check,
       EXISTS (SELECT 1 FROM information_schema.tables
                WHERE table_schema='public' AND table_name='fusion_paper_state')::text
       AS value
UNION ALL
SELECT 'AFTER: fusion_paper_state columns',
       (SELECT string_agg(column_name, ', ' ORDER BY ordinal_position)
          FROM information_schema.columns
         WHERE table_schema='public' AND table_name='fusion_paper_state')
UNION ALL
SELECT 'AFTER: fusion_paper_nav inception_id column',
       EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_schema='public' AND table_name='fusion_paper_nav'
                  AND column_name='inception_id')::text
UNION ALL
SELECT 'AFTER: fusion_paper_nav void_reason column',
       EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_schema='public' AND table_name='fusion_paper_nav'
                  AND column_name='void_reason')::text
UNION ALL
SELECT 'AFTER: fusion_paper_nav rows voided (v1 + void_reason NOT NULL)',
       (SELECT count(*) FROM fusion_paper_nav
         WHERE inception_id = 'v1' AND void_reason IS NOT NULL)::text
UNION ALL
SELECT 'AFTER: fusion_paper_nav total rows',
       (SELECT count(*) FROM fusion_paper_nav)::text
UNION ALL
SELECT 'AFTER: fusion_paper_state row count',
       (SELECT count(*) FROM public.fusion_paper_state)::text;
