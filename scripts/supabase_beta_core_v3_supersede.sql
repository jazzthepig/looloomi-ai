-- ① book v2 → v3 supersession (2026-08-11, S-137)
--
-- v2 is SUPERSEDED, NOT VOID. The distinction is the product.
--
--   VOID (v1, S-123) = the rows are WRONG. The book sized off a 23-day-stale
--                      regime and ran at double the intended exposure for its
--                      entire 2-mark life. Those NAVs describe a book nobody
--                      meant to run.
--   SUPERSEDED (v2)  = the rows are RIGHT. Three honest marks, and by the last of
--                      them layer ③ was working correctly (cap 0.5, cap_source
--                      regime_map, regime TIGHTENING). What changed is the POLICY:
--                      the cap is now selected by trailing-vol tercile rather than
--                      macro regime.
--
-- A 60-day curve spliced across two sizing policies is not a 60-day record of
-- either one. Retiring at day 3 costs 3 days; finding the splice at day 55 costs
-- 55 — which is the entire argument for changing this the day it is measured.
--
-- WHY v2 KEEPS ITS ROWS AND ITS NAV. Deleting them would remove the evidence that
-- the regime-driven policy was tried, and CLAUDE.md is explicit that the graveyard
-- is the asset. A reader who can see v1 (void, wrong), v2 (superseded, honest,
-- 3 marks) and v3 (live) can audit the decision; a reader who sees only v3 has to
-- take our word for it. `void_reason` stays NULL on v2 precisely because it is not
-- void — the supersession is recorded in `note`, which is a different claim.

update beta_core_nav
   set note = coalesce(note, '') ||
              ' | SUPERSEDED by v3 on 2026-08-11 (S-137): cap driver changed from '
              'macro_regime to trailing-vol tercile. Rows are honest, policy is '
              'retired. Measured 902d OOS: vol-tercile ladder ret/DD 0.780 vs '
              'constant-cap 0.634 vs forward-vol oracle 0.885.'
 where inception_id = 'v2'
   and void_reason is null
   and note not like '%SUPERSEDED by v3%';       -- idempotent: safe to re-run

-- ── VERIFY ───────────────────────────────────────────────────────────────────
-- select inception_id, count(*) n, min(mark_date) first, max(mark_date) last,
--        count(void_reason) voided
--   from beta_core_nav group by 1 order by 1;
-- expect: v1 (2 rows, 2 voided) · v2 (3 rows, 0 voided) · v3 appears on the next mark.
--
-- The live curve must show v3 ONLY, and start fresh at NAV 1.0:
--   select mark_date, nav, exposure_cap, cap_source, regime
--     from beta_core_nav where inception_id = 'v3' order by mark_date;
--
-- cap_source should now read vol_state_low / vol_state_mid / vol_state_high with
-- the regime carried alongside in parentheses — e.g. 'vol_state_high(regime=
-- TIGHTENING)'. Seeing 'regime_map' on a v3 row means the old driver is still
-- wired somewhere and the deploy did not take.
