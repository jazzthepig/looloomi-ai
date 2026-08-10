-- daily_macro_regime — one row per day, so a row cap can never truncate the history
-- 2026-08-10 (S-130). ALREADY APPLIED to production; this file is the record.
--
-- WHAT BROKE. The ① book's v2 marks recorded `excess_return = 0.0000` on both days,
-- with `regime = NULL` and `exposure_cap = 1.0`, while every source in `cis_scores`
-- read TIGHTENING (which maps to cap 0.5). The chain:
--
--   _regime_history() returned []          (see below)
--     -> len(hist) < _REGIME_DWELL_DAYS, so the dwell filter never ran
--     -> _current_regime fell through to the Redis blob, which has no regime field
--     -> canonical_regime_strict(None) = None   (correct — it is honest)
--     -> _exposure_cap(None) = (1.0, "no_regime")
--     -> gross = min(vol_scalar 1.30, cap 1.0) = 1.0
--     -> book weights == benchmark weights, so excess is 0.0000 BY CONSTRUCTION
--
-- Sixty days of that is a curve identical to its own benchmark: it cannot show
-- "captured beta and drew down less", which is the only claim the book exists to make.
--
-- WHY _regime_history RETURNED NOTHING. It fetched raw `cis_scores` rows and computed
-- the daily modal in Python. That table carries 1,000–2,000 rows per day, and
-- PostgREST enforces a SERVER-side row cap (`db-max-rows`, 1000 by default) which
-- silently overrides the client's `limit=20000`. So "30 days" of history was one or
-- two days.
--
-- This is S-123 one layer down. There the cap was ours and an ascending sort dropped
-- the newest end; here the cap belongs to the server and cannot be raised from the
-- client. Raising a limit only moves the failure date — the table grows, the cap does
-- not. Lesson #112: DO NOT TRANSPORT ROWS YOU ARE ABOUT TO AGGREGATE. Asking the
-- database for the aggregate puts the cap out of reach: 35 rows instead of ~49,000.
--
-- The view also fixes a correctness detail the Python version got right only by
-- accident: the modal is computed over ALL rows for the day, across every source
-- (local_engine / railway_snapshot / railway_t2_hourly), and the label is normalised
-- to UPPER_SNAKE here rather than at each call site — `Tightening` and `TIGHTENING`
-- were both live in the table on 2026-08-08.

create or replace view daily_macro_regime as
select d, regime, n_obs, n_sources
from (
  select recorded_at::date                                                    as d,
         upper(replace(replace(trim(macro_regime), '-', '_'), ' ', '_'))      as regime,
         count(*)                                                             as n_obs,
         count(distinct source)                                               as n_sources,
         row_number() over (partition by recorded_at::date
                            order by count(*) desc)                           as rk
  from cis_scores
  where macro_regime is not null
  group by 1, 2
) z
where rk = 1;

grant select on daily_macro_regime to service_role, authenticated;

-- ── VERIFY ───────────────────────────────────────────────────────────────────
-- select d, regime, n_obs, n_sources from daily_macro_regime
--  where d >= current_date - 20 order by d desc;
-- expect ONE row per day. As of 2026-08-10: TIGHTENING for 15 consecutive days,
-- RISK_OFF on 07-25/07-26, NEUTRAL on 07-22..07-24.
--
-- ── THEN, after the code change is deployed ──────────────────────────────────
-- select mark_date, exposure_cap, regime, round((excess_return*100)::numeric,4)
--   from beta_core_nav where inception_id = 'v2' order by mark_date desc limit 1;
-- expect regime = TIGHTENING and exposure_cap = 0.5 on the next mark.
-- Still NULL/1.0 means the view is not being read — check the Railway log for
-- "[beta_core] daily_macro_regime read failed".
