-- ============================================================================
-- S-283 · NAV policy enforcement — schema + record correction
-- docs/NAV_POLICY.md §3 (valuation point), §6 (materiality), §7 (continuity)
--
-- ⚠️  RUN THIS BEFORE PUSHING THE CODE.
--     `_write` now sends `interval_hours` on every beta_core_nav insert. Without
--     this column PostgREST answers 400, `supabase_insert_table` returns False,
--     `_write` returns False, and the ① book logs "MARK NOT PERSISTED" and stops
--     marking — process healthy, endpoint healthy, one table quietly stops
--     filling. That is S-138/S-185 exactly, so the ordering is load-bearing.
--
-- Idempotent. Safe to re-run.
-- ============================================================================

-- ── 1. interval_hours — the measured gap between two marks (NAV_POLICY §3) ──
-- NOT derivable from mark_date: `mark_date - mark_date` is 24h by definition and
-- would record the assumption instead of testing it. v4's marks ran 10.6h to
-- 35.9h apart (3.38x) while every row claimed to be one day, and those rows feed
-- realized_vol_30d → vol_target_scalar → gross exposure. NULLABLE on purpose:
-- the first mark of an incarnation has no predecessor, and an unmeasurable
-- interval must read as unknown rather than as a plausible 24.0.
ALTER TABLE public.beta_core_nav
    ADD COLUMN IF NOT EXISTS interval_hours double precision;

COMMENT ON COLUMN public.beta_core_nav.interval_hours IS
    'Wall-clock hours since the previous mark was struck. NULL on the first mark '
    'of an inception. Outside [18h, 30h] the row is not a daily observation and '
    'annualized figures are suppressed (docs/NAV_POLICY.md §3).';


-- ── 2. VOID the v4 segment (NAV_POLICY §6 — significant error) ───────────────
-- Three defects, each independently significant under the §6 qualitative override:
--   (a) inception inheritance — v4's first row compounded onto v3's NAV
--       (1.258366 / 1.201872 = 1.047005, v3's last NAV to six figures) because
--       the Redis state key was not scoped by inception_id;
--   (b) stale mark prices inherited by the same route — the +20.187% first-row
--       "daily" return is 08-21, 08-22 and 08-23 compounded into one row;
--   (c) no elected valuation point — intervals 10.6h–35.9h, so vol, Sharpe and
--       every annualized figure on this segment measure nothing.
--
-- VOID, NOT DELETE. The rows stay queryable with the reason attached. A track
-- record that can quietly drop its broken days is not evidence of anything, and
-- `get_curve` already filters `void_reason is null`, so voiding is sufficient to
-- take the segment off the reading surface without destroying it.
UPDATE public.beta_core_nav
   SET void_reason = 'S-283: VOID — (a) inception inheritance via unscoped Redis '
                     'state key (v4 first row compounded onto v3 NAV 1.047005); '
                     '(b) stale mark_prices inherited by the same route, booking '
                     '3 days as one +20.187% daily return; (c) no elected '
                     'valuation point, mark intervals 10.6h-35.9h. See '
                     'docs/NAV_POLICY.md §6/§7 and _INCEPTION_REASON.'
 WHERE inception_id = 'v4'
   AND void_reason IS NULL;


-- ── 3. nav_exceptions — the log that makes "no exceptions" falsifiable ───────
-- NAV_POLICY §10. Every override, stale-price acceptance, IPV breach, refused
-- mark and manual adjustment lands here. An empty table is a fine state; an
-- ABSENT one is not — without the log, "we had no exceptions" and "nobody was
-- looking" are the same observation, which is the miss-vs-error collapse this
-- codebase keeps rediscovering in new places.
CREATE TABLE IF NOT EXISTS public.nav_exceptions (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    occurred_at   timestamptz  NOT NULL DEFAULT now(),
    book          text         NOT NULL,          -- beta_core | causal | ...
    inception_id  text,                           -- scope, per §7
    mark_date     date,
    symbol        text,                           -- NULL when book-level
    control       text         NOT NULL,          -- valuation_point | coverage | ipv | override | ...
    action        text         NOT NULL,          -- refused | flagged | overridden | accepted_stale
    actor         text         NOT NULL,          -- system | seth | jazz | minimax
    detail        jsonb        NOT NULL DEFAULT '{}'::jsonb,
    reason        text
);

CREATE INDEX IF NOT EXISTS nav_exceptions_book_date_idx
    ON public.nav_exceptions (book, mark_date DESC);
CREATE INDEX IF NOT EXISTS nav_exceptions_control_idx
    ON public.nav_exceptions (control, occurred_at DESC);

COMMENT ON TABLE public.nav_exceptions IS
    'NAV_POLICY §10 exceptions log. Every control that fires writes here, '
    'including the ones that fire clean. Read alongside beta_core_nav.void_reason.';


-- ── 4. Verification — run after the code deploys ────────────────────────────
-- Expected: v4 fully voided, v5 accumulating from nav = 1.0, interval_hours
-- populated from the SECOND v5 mark onward (NULL on the first, by design).
--
--   SELECT inception_id, count(*) AS rows,
--          count(*) FILTER (WHERE void_reason IS NOT NULL) AS voided,
--          min(mark_date), max(mark_date),
--          round(min(interval_hours)::numeric, 1) AS min_iv,
--          round(max(interval_hours)::numeric, 1) AS max_iv
--     FROM public.beta_core_nav
--    GROUP BY inception_id
--    ORDER BY min(mark_date);
