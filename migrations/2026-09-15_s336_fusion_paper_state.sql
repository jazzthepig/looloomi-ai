-- S-336 — the table that never existed. The table the code writes to,
-- reads from, and that the system-of-record for fusion_paper state has been
-- referenced since 2026-08-15 without ever being applied.
--
-- Why this migration exists (2026-09-15, Seth/Cowork lane):
-- 2026-08-15..2026-09-09 produced 26 fusion_paper NAV rows claiming 18 positions
-- at gross 0.667 while `daily_return` was IDENTICALLY -cost for 26 days in a row
-- and NAV did not compound (26 days of -5bps should be 0.9871, observed 0.9995).
-- The mechanism was not "the data was wrong" — the mechanism was that the
-- STATE was lost every cycle (the table the durable state was supposed to
-- live in did not exist), so `nav` reset to 1.0 and `w_held` reset to {} on
-- every cycle, the P&L loop over an empty dict never ran, and an empty
-- accumulation was recorded as a flat day. **Every layer was working
-- correctly; together they produced a false record.**
--
-- This is the S-166 class incident (eleven tables the code wrote to did not
-- exist), at the single-table level, with the missing table being the one
-- `_load_state` falls through to from Redis. Sweep on 2026-09-12 confirmed
-- this was the only one of the 37 declared tables missing.
--
-- This migration voids the v1 NAV records in place rather than deleting them
-- or "correcting" them: the book never knew what it held, so the true NAVs are
-- unrecoverable. Voided segments are filtered at read time (`inception_id =
-- 'v2' AND void_reason IS NULL`), exactly the discipline beta_core adopted
-- for its v3→v4 transition.
--
-- Idempotent. Safe to re-run. Safe to apply BEFORE the code changes (the
-- `inception_id='v2'` filter is enforced by the reader only, not the writer).
--
-- Rollback: DROP TABLE public.fusion_paper_state; ALTER TABLE fusion_paper_nav
-- DROP COLUMN inception_id, DROP COLUMN void_reason. (Do NOT unvoid the 26
-- rows — there is nothing to recover.)
-- ⚠️  RUN THE WHOLE FILE — DO NOT "Run selected".
--     The Supabase SQL Editor lets you highlight a portion and run only that
--     portion. This migration is NOT safe to partial-run: lines 97-117 add
--     the inception_id column AND stamp the existing rows in dependent
--     statements, and the UPDATE on line 110 errors 42703 "column
--     inception_id does not exist" if you skip the ALTER TABLE on line 97.
--     Click "Run" (NOT "Run selected"), or press Cmd/Ctrl+Enter with no
--     text highlighted. The BEGIN/COMMIT wrapper at the top/bottom means
--     either ALL of the migration runs, or NONE of it.
--
-- Idempotent. Safe to re-run. Safe to apply BEFORE the code changes (the
-- `inception_id='v2'` filter is enforced by the reader only, not the writer).
--
-- Rollback: DROP TABLE public.fusion_paper_state; ALTER TABLE fusion_paper_nav
-- DROP COLUMN inception_id, DROP COLUMN void_reason. (Do NOT unvoid the 26
-- rows — there is nothing to recover.)
BEGIN;

-- ════════════════════════════════════════════════════════════════════════════
-- Part 1: CREATE TABLE fusion_paper_state — the table that never existed
-- ════════════════════════════════════════════════════════════════════════════
-- Columns mirror _save_state() in src/data/signals/fusion_paper.py:498 —
--   inception, last_mark, nav, weights, mark_prices, prev_prices,
--   n_days_marked, cell, detector_fired_today
-- plus the inception_id / void_reason pair the reader uses to filter voided
-- segments (inception_id already on the row, so the filter is `void_reason
-- IS NULL` only — both v1 and v2 carry their own inception_id; void_reason
-- is the operator signal, not the inception signal).
--
-- Many-rows-per-inception allowed: each `_save_state` is an append, so the
-- latest row wins on read (`order=last_mark.desc&limit=1`).
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

COMMENT ON TABLE public.fusion_paper_state IS
    'CometCloud Layer II/III fusion_paper durable state (S-336). '
    'One row per `_save_state` append; the reader takes the latest by '
    '`last_mark`. void_reason is the operator signal — NULL means live; '
    'non-NULL means the row is preserved but excluded from the curve.';

CREATE INDEX IF NOT EXISTS fusion_paper_state_inception_mark_idx
    ON public.fusion_paper_state (inception_id, last_mark DESC);

-- RLS — same shape as the paper_nav tables (write through service role, read
-- anon for dashboard).
ALTER TABLE public.fusion_paper_state ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
  CREATE POLICY fusion_paper_state_read_anon ON public.fusion_paper_state
    FOR SELECT TO anon USING (true);
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE POLICY fusion_paper_state_all_service ON public.fusion_paper_state
    FOR ALL TO service_role USING (true) WITH CHECK (true);
EXCEPTION WHEN duplicate_object THEN NULL; END $$;


-- ════════════════════════════════════════════════════════════════════════════
-- Part 2: ALTER fusion_paper_nav — add inception_id + void_reason, void v1
-- ════════════════════════════════════════════════════════════════════════════
-- The 26 NAV rows from 2026-08-15..2026-09-09 are PRESERVED but flagged as
-- voided. The reader in src/research/paper_books/nav_ledger.py:68 must be
-- updated to filter `inception_id = 'v2' AND void_reason IS NULL` (separate
-- commit / task). For now this migration only stamps the rows so any naive
-- reader that does `SELECT *` is loudly wrong (it sees 26 with reason
-- populated, all 26 are v1, none are v2).

ALTER TABLE fusion_paper_nav
  ADD COLUMN IF NOT EXISTS inception_id text;

ALTER TABLE fusion_paper_nav
  ADD COLUMN IF NOT EXISTS void_reason text;

-- Stamp the existing rows. The 26 rows from 2026-08-15..2026-09-09 are v1 by
-- definition (v2 hasn't started yet — that happens after this migration
-- applies AND the reader is updated AND the next mark runs with `_INCEPTION_ID
-- = "v2"`). NULL inception_id means "pre-v2, presumed v1 until proven
-- otherwise"; we stamp them all to v1 with a reason here so the column is
-- not nullable in spirit even though we keep it nullable in SQL for the
-- brief window during rollout.
UPDATE fusion_paper_nav
   SET inception_id = 'v1',
       void_reason  = 'S-336 — fabricated state. fusion_paper_state never '
                      'existed in Postgres, so w_held was empty every cycle, '
                      'NAV reset to 1.0, and 26 days of empty accumulation '
                      'were written as a flat day. voided not corrected: the '
                      'book never knew what it held. See fusion_paper.py:65.'
 WHERE inception_id IS NULL;

-- Force non-null going forward. AFTER the UPDATE above, every existing row
-- has inception_id='v1', so the constraint is safe to add.
ALTER TABLE fusion_paper_nav
  ALTER COLUMN inception_id SET NOT NULL;

DO $$ BEGIN
  ALTER TABLE fusion_paper_nav
    ADD CONSTRAINT fusion_paper_nav_inception_chk
    CHECK (inception_id IN ('v1', 'v2'));
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- Index supports the `(inception_id = 'v2' AND void_reason IS NULL)` filter
-- the reader will use.
CREATE INDEX IF NOT EXISTS fusion_paper_nav_v2_live_idx
    ON fusion_paper_nav (ts DESC)
    WHERE inception_id = 'v2' AND void_reason IS NULL;


-- ════════════════════════════════════════════════════════════════════════════
-- Verification
-- ════════════════════════════════════════════════════════════════════════════
SELECT
    'fusion_paper_state' AS table_name,
    (SELECT count(*) FROM public.fusion_paper_state)::text AS rows,
    (SELECT count(*) FROM information_schema.columns
       WHERE table_schema='public' AND table_name='fusion_paper_state')::text
       AS column_count
UNION ALL
SELECT
    'fusion_paper_nav (v1 voided)' AS table_name,
    (SELECT count(*) FROM fusion_paper_nav
       WHERE inception_id='v1' AND void_reason IS NOT NULL)::text
       || ' / ' ||
       (SELECT count(*) FROM fusion_paper_nav)::text AS rows,
    (SELECT count(*) FROM information_schema.columns
       WHERE table_schema='public' AND table_name='fusion_paper_nav')::text
       AS column_count;

COMMIT;