-- ① book re-inception — 2026-08-09 (S-123)
--
-- WHY. The v1 run (2026-08-08 → 2026-08-09, 2 marks) sized itself off a regime
-- series 23 days stale: `_regime_history` asked for the ascending first 20,000 rows
-- of a 53,250-row window, so the newest day it could see was 2026-07-17. The stale
-- series plus a missing Redis field went through the LENIENT canonicaliser, where
-- None becomes "NEUTRAL", and NEUTRAL caps exposure at 1.0 while the true regime
-- TIGHTENING caps at 0.5. Both marks therefore ran at double the intended exposure,
-- and `nav = benchmark = 0.99894` exactly — layer ③ contributed nothing at all.
--
-- WHY VOID RATHER THAN KEEP. We sell the falsification apparatus. A 60-day curve
-- that needs a footnote explaining its first two days is worth less than a clean
-- curve that starts two days later. Cost of voiding today: 2 days. Cost of
-- discovering it in a month: 30.
--
-- WHY VOID RATHER THAN DELETE. CLAUDE.md: the graveyard is the asset. The rows stay
-- queryable with the reason attached, so the record shows what was discarded and
-- why. A track record that only shows survivors is the thing we spent S-111
-- measuring the cost of (survivorship bias = 25.1 pp/yr).
--
-- ORDER OF OPERATIONS — DO NOT REORDER:
--   1. deploy the S-123 code fix          (else the next mark repeats the bug)
--   2. verify the regime now reads TIGHTENING  (§verify below)
--   3. run this script                    (adds columns, voids v1)
--   4. clear the Redis state key          (§4 below — the ONLY safe moment)
-- Running 3 before 1 produces a third contaminated mark under a clean label, which
-- is strictly worse than the current state because it hides the fault.

-- ── 1. additive schema ──────────────────────────────────────────────────────
-- `inception_id` stamps every row with the incarnation that produced it. It is a
-- CODE CONSTANT in beta_core_paper.py, deliberately not an env var: re-inception
-- must cost a commit, so it is reviewed, dated, attributed and permanently visible
-- in `git log`. A NAV that can be reset from a dashboard proves nothing.
alter table beta_core_nav add column if not exists inception_id text;
alter table beta_core_nav add column if not exists void_reason  text;

-- ── 2. void the v1 run (2 rows) ─────────────────────────────────────────────
update beta_core_nav
   set inception_id = 'v1',
       void_reason  = 'S-123: regime history truncated to the OLDEST 20,000 of '
                   || '53,250 rows, so the book sized off a 2026-07-17 reading on '
                   || '2026-08-09 and ran at cap 1.0 where TIGHTENING maps to 0.5. '
                   || 'nav == benchmark to 5dp: layer 3 contributed nothing.'
 where inception_id is null;
-- expected: UPDATE 2

-- ── 3. index for the scoped reads ───────────────────────────────────────────
-- Every read path (state recovery, continuity, published curve) now filters on
-- inception_id + void_reason. Small table, but the filter is on the hot path of the
-- daily loop and of /health.
create index if not exists idx_beta_core_nav_incarnation
    on beta_core_nav (inception_id, mark_date desc)
 where void_reason is null;

-- ── 4. verification — run BEFORE clearing Redis ─────────────────────────────
-- (a) v1 is voided, nothing else is:
--     select inception_id, void_reason is not null voided, count(*), min(mark_date), max(mark_date)
--       from beta_core_nav group by 1,2 order by 1;
--     expect exactly one row: v1 | true | 2 | 2026-08-08 | 2026-08-09
--
-- (b) the live incarnation is empty, so the next mark is a clean inception:
--     select count(*) from beta_core_nav where inception_id = 'v2' and void_reason is null;
--     expect 0
--
-- (c) the regime the book will now read is TIGHTENING, not NEUTRAL:
--     with w as (select recorded_at, macro_regime from cis_scores
--                where recorded_at >= (current_date - 35) and macro_regime is not null
--                order by recorded_at desc limit 20000)
--     select max(recorded_at)::date newest, mode() within group (order by macro_regime) modal
--       from w;
--     expect newest = today (or today-1), modal = TIGHTENING
--     If newest is weeks old, the fix is NOT deployed — stop, do not clear Redis.
--
-- ── 5. only then, Mac-side: clear the state key ─────────────────────────────
--     The book refuses to silently re-inception (it reads through to Postgres on a
--     cache miss), which is correct and must stay. With v1 voided and v2 empty, the
--     read-through finds nothing and a genuine inception happens — recorded, at
--     NAV 1.0, under the new id.
--
--     redis-cli -u "$UPSTASH_REDIS_URL" DEL beta_core:state
--     (or the Upstash console: delete key `beta_core:state`)
--
-- ── 6. next day, confirm the new clock ──────────────────────────────────────
--     select mark_date, nav, benchmark_nav, exposure_cap, regime, cap_source
--       from beta_core_nav where inception_id='v2' order by mark_date;
--     expect exposure_cap = 0.5 and regime = TIGHTENING on the first clean mark.
--     If it says NEUTRAL / 1.0 again, the deploy did not take — do not let it run.
--
-- 60-day gate from the first v2 mark: inception + 60 days.
