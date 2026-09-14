-- Force-mark primitive: add mark_source column to paper-book NAV tables.
--
-- Why this migration exists (2026-09-14, Seth/Cowork lane):
-- S-328 said the half-fix was /internal/write-probe + /internal/book-dryrun.
-- The OTHER half was force-mark — an endpoint that strikes a real NAV row NOW
-- instead of waiting for 00:05 UTC. A-21 shipped the vault side; this migration
-- plus the router/book edits cover the 9 paper books.
--
-- `mark_source` distinguishes:
--   'cron'   — the 24h scheduled mark (valuation point 00:05 UTC ±30min)
--   'manual' — operator-forced mark via POST /internal/force-mark/{book}
--
-- The forward record can then be served with provenance: a reader can ask "is this
-- mark on the regular schedule?" without re-running the cron history. NAV_POLICY
-- §10 (exceptions log) is the deeper mechanism; this column is the surface
-- provenance the audit reader sees first.
--
-- Idempotent: safe to re-run. Safe to apply BEFORE the code ships (column exists,
-- writers default to 'cron' until they start sending 'manual'). Safe to apply
-- AFTER the code ships (existing rows keep their default 'cron' from DEFAULT).
--
-- Rollback: `ALTER TABLE … DROP COLUMN IF EXISTS mark_source;` per table.
-- No data loss (existing rows unaffected; new column was empty for them).

BEGIN;

-- 1. beta_core — the actual table is `beta_core_nav` (no `_paper` suffix),
-- unlike the other 8 books. beta_core_paper.py:1326 writes to it.
ALTER TABLE beta_core_nav
  ADD COLUMN IF NOT EXISTS mark_source text NOT NULL DEFAULT 'cron';

DO $$ BEGIN
  ALTER TABLE beta_core_nav
    ADD CONSTRAINT beta_core_nav_mark_source_chk
    CHECK (mark_source IN ('cron', 'manual'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- 2. causal
ALTER TABLE causal_paper_nav
  ADD COLUMN IF NOT EXISTS mark_source text NOT NULL DEFAULT 'cron';

DO $$ BEGIN
  ALTER TABLE causal_paper_nav
    ADD CONSTRAINT causal_paper_nav_mark_source_chk
    CHECK (mark_source IN ('cron', 'manual'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- 3. combined
ALTER TABLE combined_book_nav
  ADD COLUMN IF NOT EXISTS mark_source text NOT NULL DEFAULT 'cron';

DO $$ BEGIN
  ALTER TABLE combined_book_nav
    ADD CONSTRAINT combined_book_nav_mark_source_chk
    CHECK (mark_source IN ('cron', 'manual'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- 4. dingge (mark_and_trade, not mark_and_rebalance — same table family)
ALTER TABLE dingge_paper_nav
  ADD COLUMN IF NOT EXISTS mark_source text NOT NULL DEFAULT 'cron';

DO $$ BEGIN
  ALTER TABLE dingge_paper_nav
    ADD CONSTRAINT dingge_paper_nav_mark_source_chk
    CHECK (mark_source IN ('cron', 'manual'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- 5. factor_tilt
ALTER TABLE factor_tilt_nav
  ADD COLUMN IF NOT EXISTS mark_source text NOT NULL DEFAULT 'cron';

DO $$ BEGIN
  ALTER TABLE factor_tilt_nav
    ADD CONSTRAINT factor_tilt_nav_mark_source_chk
    CHECK (mark_source IN ('cron', 'manual'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- 6. fusion
ALTER TABLE fusion_paper_nav
  ADD COLUMN IF NOT EXISTS mark_source text NOT NULL DEFAULT 'cron';

DO $$ BEGIN
  ALTER TABLE fusion_paper_nav
    ADD CONSTRAINT fusion_paper_nav_mark_source_chk
    CHECK (mark_source IN ('cron', 'manual'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- 7. pod_aggregator
ALTER TABLE pod_aggregator_nav
  ADD COLUMN IF NOT EXISTS mark_source text NOT NULL DEFAULT 'cron';

DO $$ BEGIN
  ALTER TABLE pod_aggregator_nav
    ADD CONSTRAINT pod_aggregator_nav_mark_source_chk
    CHECK (mark_source IN ('cron', 'manual'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- 8. scalable
ALTER TABLE scalable_paper_nav
  ADD COLUMN IF NOT EXISTS mark_source text NOT NULL DEFAULT 'cron';

DO $$ BEGIN
  ALTER TABLE scalable_paper_nav
    ADD CONSTRAINT scalable_paper_nav_mark_source_chk
    CHECK (mark_source IN ('cron', 'manual'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- 9. two_layer
ALTER TABLE two_layer_paper_nav
  ADD COLUMN IF NOT EXISTS mark_source text NOT NULL DEFAULT 'cron';

DO $$ BEGIN
  ALTER TABLE two_layer_paper_nav
    ADD CONSTRAINT two_layer_paper_nav_mark_source_chk
    CHECK (mark_source IN ('cron', 'manual'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- Verification: show the new column on each table.
SELECT table_name, column_name, data_type, column_default
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name IN (
    'beta_core_nav', 'causal_paper_nav', 'combined_book_nav',
    'dingge_paper_nav', 'factor_tilt_nav', 'fusion_paper_nav',
    'pod_aggregator_nav', 'scalable_paper_nav', 'two_layer_paper_nav'
  )
  AND column_name = 'mark_source'
ORDER BY table_name;

COMMIT;
