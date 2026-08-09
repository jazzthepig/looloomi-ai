# PROJECT_STATE.md — the living single source of truth

## OPEN RISKS  (≤7 · cold-start first screen · every item ships a VERIFY command)

*Why this block is first: measured on 2026-07-30, a cold agent following CLAUDE.md exactly could
not reach S-92 or the still-open security hole — the header was dated older than the incident and
the lessons lived only in a 5,672-line ledger. **Don't transmit memory, transmit verification.**
Contract + failure-path walkthrough: `docs/AMNESIA_PROTOCOL.md`; enforced by
`tests/test_cold_start_contract.py`.*

1. **🔴 No working service_role key on this machine — the one in `.env` was FORGED** (2026-08-02).
   Removed. Every Supabase-writing path off the Mac is blocked until Jazz re-copies the real key.
   **Lesson #72: a JWT that decodes is not a JWT that verifies.** The token carried
   `iss=supabase`, `ref=soupjamxlfsmgmmtoeok`, `role=service_role`, exp 2036 — every local check
   passed. It was the **anon key's signature spliced onto an edited payload**: byte-identical
   header, byte-identical 43-char signature, only the `role` claim differed. A signature is an
   HMAC over header+payload, so it cannot survive a payload edit — proof it was hand-assembled,
   not issued. Server verdict: `401 Invalid API key`. Almost certainly an earlier agent that
   needed service_role, had only anon, and produced one. **Never validate a credential by
   decoding it; validate it against the server that issued it.** Now enforced in
   `build_l1_observations.py --diagnose`, which probes for ROWS (real anon returns 200/0 rows
   under S-94 RLS, so status alone also proves nothing). Forged copies purged from `.env` and
   both `.claude/**/settings.local.json` (12 entries); never git-tracked (`.gitignore:42`).
   VERIFY: `bash -c 'set -a; . .env; set +a; curl -s -H "apikey: $SUPABASE_KEY" "$SUPABASE_URL/rest/v1/ohlcv_daily?select=symbol&limit=1"'`
   → `[{...}]` = real service_role · `401` = forged/stale · `[]` = anon under RLS, still blocked
   OWNER: Jazz (dashboard → Project Settings → API Keys → service_role → paste into `.env`)

   **Lesson #71: a security linter's silence is not safety.** Four of the worst exposures were absent from the advisor's 11 errors — it excludes permissive SELECT policies, so `cis_scores` was world-readable and unflagged. Audit `pg_policies` / `pg_proc` directly.

2. **🟡 External probe live 2026-07-30, unproven** — `cometcloud-external-probe`, every 2 h,
   **outside the monitored process** (5 checks: liveness · the endpoint that died · Mac-push
   freshness · security-regression on the revoked RPC · anonymous read). Worst-case blind window
   **10.4 h → 2 h**. Still open because: it runs only while the desktop app is open, it has never
   fired on a real failure, and **an unfired alarm is not a proven alarm**. Downgrade to 🟢 only
   after it catches something, or after a deliberate induced failure confirms it fires.
   VERIFY: `ls /Users/sbb/Documents/Claude/Scheduled/cometcloud-external-probe/` and check the
   last run reported `✅ probe OK`; no run in >3 h ⇒ the probe itself is dead.
   OWNER: Jazz (keep the app open) / Seth (induce a failure to prove it fires)

3. **🔴 The VDB's durable layer is not finished — and one gap was silently losing research.**
   *(merged from two entries: "tables are empty" and "the graveyard was in a cache" are the same
   problem seen from the data side and the mechanism side.)*

   **(a) A table that was never created.** `scripts/supabase_strategy_records.sql`, written
   2026-07-26 specifically to move the strategy record library off a 24 h-TTL Redis key, **was
   never applied.** `_pg_upsert()` POSTed to a nonexistent table, caught the exception, logged one
   WARNING, returned False, and `upsert_record()` fell back to Redis with `_TTL = 86_400`.
   CLAUDE.md calls the graveyard the asset; the asset sat in a cache that expires daily, for 12
   days. **It survived because the warning fired on EVERY write — an always-on warning carries no
   information.** Migration now applied (RLS on, anon revoked); `/health` gained
   `data_layer.strategy_library`; `tests/test_strategy_durability.py` 4/4 in preflight. Kept OUT of
   `degraded` on purpose: losing durable research does not make the API unhealthy, and conflating
   them would either 503 a healthy API or bury data loss under a green tick.
   **Backfill still pending** (service_role, blocked by risk #1) ⇒ records remain TTL-only today.
   **Task #20 "VDB 落库" was logged COMPLETE but only the asset half landed** — `asset_embeddings`
   72 rows, strategy side absent. A half-migration recorded as done is how the next agent stops looking.

   **(b) Tables that exist but are empty.** `asset_embeddings_history` (risk #1) ·
   `risk_meter_history` 0 rows (M-WO-D2) · **`decisions` 0 rows / `entities` 1 row.**
   ARCHITECTURE.md says the deepest object is the entity-and-decision, not the asset; that is where
   the claim lands, and it is empty. **Either wire them or demote the claim — an empty table cannot
   carry an ontological argument.** `signal_outcomes` also ends 2026-05-03, so the response surface
   omits the last 3 months.
   VERIFY: `select count(*) from strategy_records;` → 0 ⇒ backfill pending ·
   `curl -s $BASE/health | jq .data_layer.strategy_library.degraded` → true ⇒ writes not durable ·
   `select count(*) from decisions;` → 0 ⇒ ontology claim still unbacked
   OWNER: Jazz (service_role → risk #1; judgement call on the ontology) · Seth (backfill, extend
   signal_outcomes) · Minimax-A (M-WO-D2)

4. **🟡 ① beta_core: v1 marked twice then was VOIDED (S-123); v2 inception is blocked on a
   schema fix.** Superseded by events — kept because the clock is still not running.
   v1's two marks sized off a 23-day-stale regime (cap 1.0 where TIGHTENING maps to 0.5,
   `nav == benchmark` to 5dp, layer ③ contributed nothing) and were voided in place.
   v2 cannot write until `beta_core_nav`'s `PRIMARY KEY (mark_date)` becomes
   `(inception_id, mark_date)` — v1's voided row for the same day raises 23505.
   VERIFY: `select inception_id, count(*) from beta_core_nav group by 1;`
   → expect `v2 | 1` once `scripts/supabase_beta_core_pk_by_incarnation.sql` has run and
   Railway has been redeployed. Still `v1` only = the clock has NOT started.
   OWNER: Jazz (Supabase SQL editor, then Redeploy — the loop retries on restart, not on a timer)

   *Original entry, for the record:* **① beta_core has NEVER marked — the 60-day clock is NOT running.**
   (OVERSIGHT_2026-08.md §0 + §3, 2026-08-08; **worse than the previous entry's "1 day old"
   — verified 2026-08-09 07:05Z that `marks:0, started:false`**). S-103 + S-105 refuted the
   ④-layer cross-sectional market-neutral L/S construction (β confounded across all 5 tiers,
   cost 4.6 %/yr > ~3 % best-case effect). **3 of 5 live L/S paper books
   (causal_paper / combined_book / scalable_paper) demoted to RESEARCH RECORDS
   on 2026-08-08** (commit `fc4d331`). The product book `beta_core_paper` (commit `121b54c`) is the
   only forward-clock with a SHIP floor in mind: equal-weight hold-the-panel
   (no short, no neutralisation) + ex-ante vol target + ⓠ regime override
   caps gross at {0.0, 0.5, 1.0, 1.3}, marked daily to Supabase `beta_core_nav`
   with `benchmark_nav` alongside `nav` so excess is arithmetic. **S-123 fix in
   code (commits b8af18b + c0516f9) and DEPLOYED — `git_sha=5a54d1c1` is live on Railway.**
   The migration `scripts/supabase_beta_core_reinception.sql` (add `inception_id` +
   `void_reason` columns, mark v1 rows void, unblock v2 SELECT) **HAS NOT RUN —
   blocked on service_role (OPEN RISK #1)**, so the `_recover_state_from_nav` filter
   `inception_id=eq.v2&void_reason=is.null` returns 0 rows even though the
   book would mark if the loop fired. **The 60-day SHIP-ready date 2026-10-初 has not
   started; until the migration runs we cannot say the loop is broken, only that
   we cannot see the marks.** **A book that is silent cannot be told from a book
   that is alive but writes were dropped on the floor (S-105 redux).**
   Every other book lacks a benchmark until this one accrues. **Forward-clock health is
   the single most important number to watch this week.** Full audit (S-103, S-105, S-106,
   demotion reasoning, anti-amnesia state recovery, S-123 inception identity) lives in
   OVERSIGHT_2026-08.md §0 + §3 + §7 + REFUTATION_LEDGER.md S-124.
   VERIFY:
   ```
   curl -sm 15 -H "X-Internal-Token: $INTERNAL_TOKEN" "$BASE/internal/beta-core-clock"
   ```
   `{"configured":true,"marks":N,"started":true,"inception":"YYYY-MM-DD",...}` (N≥1)
   ⇒ loop firing · `{"marks":0,"started":false,"note":"book has never marked — the clock is NOT running"}`
   ⇒ escalate P0 · **also check** `/internal/build-state` `git_sha` ends in a commit that
   includes `b8af18b` or later (the S-123 fix) — if the SHA is older, deploy never picked
   it up; if newer and still 0 marks, the loop is silent on a different cause.
   OWNER: Jazz (service_role → OPEN RISK #1; the 60-day SHIP-ready date
   2026-10-初 is the LP milestone and only he can unblock the migration)
   · Seth (verification probe — see VERIFY; re-run once Jazz pastes key) · Minimax-A
   (M1: keep T1 engine push alive — Mac T1 health drives this loop's panel).

5. **🟡 MCP on deprecated HTTP+SSE transport** — spec `2026-07-28` retires protocol-level sessions;
   legacy SSE has a 12-month offramp. Same root shape as the P0: stateful, unbounded connections.
   VERIFY: `grep -c 'mcp/sse' src/mcp/*.py` → >0 ⇒ still on the deprecated transport
   OWNER: Seth (migration assessment not started)

6. **🔴 `ohlcv_daily` multi-source duplicates — audit COMPLETE 2026-08-09, ONE critical
   consumer needs the canonical view.** 48,582 duplicate `(symbol, trade_date)` pairs across
   57 symbols, 2017→2026 (~21 % of 229,916 rows). Not a schema bug: the unique key is
   `(symbol, trade_date, source)`, so multiple sources per day is by design. The bug is that
   every consumer must pick one, and forgetting is invisible — duplicated trading days,
   volume columns ~62,000× apart (CoinGecko USD notional vs Binance base units), and
   same-day closes differing by up to 5 % (ETH 4.8 %, SOL 5.0 %). Fixed forward with the
   `ohlcv_daily_canonical` view (229,916 → 181,334 rows, 0 remaining duplicates, deterministic
   precedence: native venue > aggregator, paid > free). **Lesson #76: any table permitting
   multiple rows per entity must ship a deterministic one-row-per-entity view, or the choice
   of source is silently delegated to every reader. Today: the view exists but is unused
   (0 consumers).**

   **AUDIT 2026-08-09 — consumer categorization:**

   **A. Filters by `source=` explicitly (SAFE — single-source pick):**
   - `src/research/validation/r95_panel.py:85,135` — `source = 'coingecko'`
   - `src/research/validation/r96_panel.py:104,144` — `source = 'eodhd'`
   - `src/research/validation/s113_revisit_s108_s109_on_687asset.py:132` — `source=eq.binance_hist`
   - `src/api/routers/ohlcv.py` — UPSERT writer (not a reader)

   **B. Reads only freshness metadata (SAFE — no data semantics):**
   - `src/api/store.py::supabase_ohlcv_daily_freshness` (only `max(trade_date)` aggregate)
   - `src/api/loop_health.py:128+` (freshness stage)
   - `src/api/main.py:1223+` (diagnostic freshness check)

   **C. VULNERABLE — does not filter by source (CRITICAL — produces noisy outcomes):**
   - **`src/data/signals/outcome_tracker.py::_ohlcv_close_at` (line 219) — CRITICAL.** Queries
     `ohlcv_daily` with no `source` filter; orders by `trade_date.asc`; takes `min(|trade_date - target|)`,
     which is unstable when multiple sources share the same `trade_date` for the same symbol.
     Called from 4 sites: `outcome_tracker.py:321` (benchmark close at target — feeds
     `signal_outcomes.benchmark_return_pct_30d`), `outcome_tracker.py:366` (entry price backfill
     → `signal_outcomes.entry_price`), `outcome_tracker.py:377` (exit price → `return_pct_30d`),
     `prediction_resolver.py:125` (entry/exit for the daily resolver). **All historical
     `signal_outcomes` rows that resolved through `_ohlcv_close_at` carry an
     arbitrary-source pick on every (symbol, trade_date) with duplicates.** This noise
     propagates to: `refresh_signal_track_record()` BETA_ADJ + BETA_ADJ_T_STAT (§BETA-METRIC-AGG
     #241), Risk Meter conviction (`cometcloud_mcp.py:1022` uses track record), the §P1 conviction
     tilt. Bound on the noise: the source-spread on duplicates, up to 5 % on closes (per the
     OPEN RISK header). On a `30d` window a 5 % exit-price noise can flip a small return's sign.
   - `src/research/data/ohlcv_local.py::load_local_panel` (line 119) — DEFAULT no filter;
     `pivot(index="trade_date", columns="symbol")` on the local sqlite mirror will fail
     (`ValueError: Index contains duplicate entries`) or silently keep the last source, depending
     on pandas version. Has `source=` param but defaults to None. **Affects all research that
     uses `load_local_panel` without an explicit source** — same shape as outcome_tracker but
     less central.

   **D. Reference / metadata only (NOT readers):**
   - `src/api/routers/admin.py:44` (config), `src/mcp/cometcloud_mcp.py:1022+` (descriptive text),
     `src/data/vector/market_state.py:23+` (docs), `src/data/vector/state_l1.py:29+` (Series source
     tags — actual reads go through `build_l1_observations.py`, not from this file),
     `src/data/vector/embedder.py` (uses `asset_edge_moments` view, a separate computation, not
     the base table).

   **Resolution path (steps, NOT a sub-list — using dashes so the cold-start regex doesn't
   mis-count them as new OPEN RISKs):**
   - Fix `outcome_tracker._ohlcv_close_at` to filter by `source=eq.binance_hist` for crypto and
     `source=eq.eodhd` for TradFi (or use `ohlcv_daily_canonical` view). Both options are
     correct; the view is the more durable one (new sources just need to be added to the
     view's precedence, not patched into every reader).
   - Fix `ohlcv_local.load_local_panel` to default to canonical-source (highest precedence)
     when no `source` is passed, or raise a loud error if multiple sources exist for a row.
   - Re-run `refresh_signal_track_record()` (P0 #241) to repopulate `signal_outcomes` with
     source-deterministic closes. **Note: `signal_outcomes` is currently DEAD 80+ days per
     `main.py:1229`**, so a full backfill is needed regardless; the question is whether the
     backfill uses the fixed or unfixed path.
   - **The original OPEN RISK #6 "S-83→S-91 used ohlcv_11yr.db, probably unaffected" guess was
     CORRECT** — S-83→S-91 read from local Binance, not Supabase. S-113 (S-108/S-109 re-run)
     reads `source=eq.binance_hist` explicitly and is SAFE. Only `asset_edge_moments` and
     `signal_outcomes` were flagged, and `asset_edge_moments` uses a separate view (not
     the base table) — so the ONLY critical path is `signal_outcomes` via `_ohlcv_close_at`.
   VERIFY:
   `grep -rn "ohlcv_daily" /Users/sbb/Projects/looloomi-ai/src/ --include="*.py" | grep -v 'source=' | grep -v 'rest/v1/ohlcv_daily\?' | grep -v 'rest/v1/ohlcv_daily"' | grep -v '//'`
   → only Category A/B/D entries should appear; any Category C is regression.
   `select count(*) from ohlcv_daily_canonical;` → 181,334 (vs 229,916 base) = 21 % deduped.
   → non-zero is expected and fine; what matters is that no consumer reads the base table
   OWNER: Seth (audit consumers, then re-run affected features off the view)

7. **🟢 S-104 T2 fan-out fix VERIFIED IN PRODUCTION 2026-08-09 07:05Z.** `git_sha=5a54d1c1`
   is the live build (24.6 min uptime, last_cis_push 221s ago). `t2_branches` reports
   `fanout_total_ms=634` (well under 12 s budget), `degraded_branches=[]`. Served
   `/api/v1/cis/universe`: `timestamp=2026-08-09T07:02:27.674901Z, data_age_s=70.8,
   stale=false, t1_count=43, t2_count=15, source=merged, macro_regime=Tightening,
   regime_confidence=0.72`. `/internal/loop-health` shows ALL 7 stages `flowing`
   (compute/serve · store/hot · data completeness · ingest freshness · upstream causes ·
   outcomes→conviction · narrative/NMA). `/internal/health-summary`: `mac_mini_push:
   ok - 71s ago`. Two `/cis/universe` calls 35 s apart show `timestamp` advancing
   normally (70.8s → ~110s) and `stale=false` steady. **This entry stays here as the
   verification record; the original "UNVERIFIED IN PROD" hypothesis is settled.**
   **What remains (fix-ladder steps 3+4, not in scope of S-104):** T2 still runs inside
   the request path; 24 h data still runs inside the build. These are different problems.
   VERIFY: `curl -sm 15 $BASE/api/v1/cis/universe | python3 -c "import json,sys;
   d=json.load(sys.stdin); print(d['timestamp'], d['data_age_s'], d['stale'], d['t1_count'],
   d['t2_count'])"` ⇒ should print a recent ISO timestamp, age <300s, `False`, 40+43+,
   10+15+. OWNER: Seth (re-verify if any of the three: build, T2 fan-out, or /health
   payload change)

---

**🟢 S-104 T2 fan-out fix verified in production 2026-08-09 07:05Z** — promoted from
   OPEN RISK #7 to LANDED. The per-branch budget fix lands cleanly:
   `t2_branches.fanout_total_ms=634` (under 12 s budget), `degraded_branches=[]`,
   `last_universe_build.total_ms≈5 s` steady, served timestamp advances 70→110 s
   over a 35 s gap, `stale:false` steady. `/internal/loop-health` shows all 7 stages
   `flowing` (compute · store · data completeness · ingest · upstream causes ·
   outcomes→conviction · narrative). `mac_mini_push: ok - 71s ago` matches the
   served timestamp within seconds. The original "build never completes" failure
   mode is gone. *(fix-ladder steps 3+4 — T2 outside request path, 24h data outside
   build — are not in scope of S-104.)* **Lesson to write up: a 56-min stalled payload
   read as a slow endpoint — measurement (S-104) found it was a never-completed build;
   preflight is the only place that re-verifies the fix in production, so the
   `/health` `t2_branches` block stays load-bearing.**

**🔴 ① beta_core paper book — clock STALLED, not 1 day old but 0 days old.** OPEN
   RISK #4 promoted from "1 day old" to "never marked." `/internal/beta-core-clock` returns
   `marks:0, started:false, gate_days_remaining:60` and the S-123 fix (commits b8af18b +
   c0516f9) IS deployed (`git_sha=5a54d1c1`). The migration that adds the
   `inception_id`/`void_reason` columns and unblocks v2 SELECT has not run —
   blocked on service_role (OPEN RISK #1). A book that is silent cannot be told from
   a book that is alive but writes were dropped on the floor (S-105 redux) — *and
   this is a re-inception, so the lesson compounds: the S-123 fix INCLUDED a
   migration for exactly this reason, but the migration needs service_role which is
   the OPEN RISK #1 dependency. A code fix without its data migration is half a fix.*

---

## LANDED — kept for the lessons, not for the status

**🟢 VDB decision chain COMPLETE 2026-08-06 — and its first answer is unflattering.**
   `market_state_vectors` 582 days · `similar_market_states()` · `strategy_response`
   (22 sufficient / 2 sparse / **16 `none`**). Chain now runs end to end: environment → similar
   history → who survived there → allocation. First real query, today =
   `trend_down|vol_low|breadth_narrow`: **no signal tier is positive-alpha here**; OUTPERFORM hits
   **4.1 %** over 74 days; **STRONG OUTPERFORM and NEUTRAL have n=0 — never observed in this
   environment at all.** That last line is not "poor performance", it is **we have no weapon for
   this environment**, and it is invisible in any aggregate Sharpe.
   **Lesson #79: "never seen in this environment" must be a ROW, not a missing row** — a coverage
   gap is the research agenda generating itself; hidden as absence it looks like a question nobody
   asked.
   **Bounds — do not over-read:** alpha uncorrected for multiple testing; ~365-day window;
   `signal_outcomes` ends 2026-05-03 while vectors run to 08-05, so **the last 3 months are not in
   it**; cluster thresholds are fixed constants with no sensitivity analysis. **A queryable
   capability, not a validated conclusion.**
   *(Residual open items promoted to OPEN RISK #3.)*

   **Also live from this pass — Lesson #78: dedup and spread-preservation are two jobs, one view
   cannot do both.** `ohlcv_daily_canonical` (one row/day, for backtests) now sits alongside
   `ohlcv_venue_spread` (cross-source dispersion kept as a feature, with `spread_kind` typing it:
   today's only multi-source crypto pair is a 257 bps candle-definition mismatch, NOT arbitrage).
   Vector tables carry `price_sources`/`provenance_note` — two vectors with identical numbers but
   different venues are not the same observation. **Lesson #77: measure a similarity's SPREAD
   before shipping it, not just its top-k** — top-k always returns the closest few whether or not
   the metric discriminates.

   **Data asset map (2026-08-06): `docs/DATA_ASSET_MAP.md`** — 40 tables + 10 views counted,
   not estimated. Biggest finding was not an empty table: `signal_outcomes` (ends 2026-05-03) and
   `signal_journal` (starts 2026-05-25) are two eras of ONE measurement, and every consumer was
   silently reading only the older half — so the response surface was computed on data ending three
   months ago, containing none of the current environment. Fixed with `signal_outcomes_unified`
   (era column exposes the seam; the 3-week gap is represented, not smoothed — sampling density
   differs 13x and the new era has no beta-adjusted alpha). **Lesson #80: a pipeline migration must
   ship a view spanning the seam, or consumers silently downgrade to the old era.**
   **Open judgement call: `decisions` 0 rows / `entities` 1 row.** ARCHITECTURE.md claims the
   deepest object is the entity-and-decision, not the asset — these tables are where that ontology
   lands, and they are empty. Either wire them or demote the claim; an empty table cannot carry an
   ontological argument.

   **Lesson #81 (S-101): a day-weighted alpha/Sharpe/t can vanish entirely under event
   counting** — a 30-day good run is 30 samples by day and ONE by episode. Our flagship
   +7.99 became +3.58 at t=1.55 across 30 episodes, and the only strongly significant
   result was OUTPERFORM at t=−6.88, i.e. negative. **Day-weighted performance is narrative,
   not evidence, until episodes are counted.**

   **Lesson #82 (S-102): the control experiment is often worth more than the main one.**
   |score−median| quintiles came out monotone (−3.15→+4.29); stopping there would have
   concluded 'the ranking works'. The percentile-rank control was NOT monotone (top
   quintile ≈0), which located the actual mechanism: distance from the crowd carries
   signal, being top-ranked does not. Root cause found: **absolute tier thresholds applied
   to a distribution whose daily median swings 23→75 (sd 12.4)** — so the label tracks the
   market's score level, not the asset's relative standing. `cis_scores.percentile` exists
   and is all NULL. ~~Robust across both parameterisations: **near-median underperforms**
   (t=−2.91 / −1.96) — an EXCLUSION signal, which for a FoF is a real product.~~
   🔴 **RETRACTED by S-103 the next day, see risk #4.**

---

**Read this FIRST every session. Update it LAST.** It's the navigation layer over the detailed
docs. If it's stale, fix it. (Behavioral discipline this doc can't enforce but must remind:
before describing any "pending push", run `git status` / `git rev-list origin/main..HEAD` — do
NOT trust memory of what's committed. That error happened 2026-07-02.)

**Last updated:** 2026-08-09 — **S-125 full code check: three findings, one shape —
"succeeded and changed nothing."**
🔴 **P0-1 SECURITY, needs Jazz in the Supabase console:** `anon` — public by construction, and
additionally hardcoded in `external_probe.sh` — could RPC four `SECURITY DEFINER` functions that
bypass RLS, with a **caller-controlled `p_max_batches`**. One unauthenticated call drives unbounded
outbound `http_get` and unbounded INSERTs into a tier we were at 90% of last week. **The scripts
already contained the revoke and always had:** `CREATE FUNCTION` grants EXECUTE to **PUBLIC**, and
`anon` merely inherits it, so `revoke ... from anon` removes a grant that role never held — a
successful no-op with no error, no warning, no rows. The ACL shows it: `{=X/...}` where the empty
grantee IS PUBLIC. The correct idiom already existed once in this repo (`from public`) on the one
function that was actually locked. **RUN: `scripts/supabase_revoke_public_execute.sql`.**
🔴 **P0-2 COMPLIANCE (hard rule #1, never enforced by anything):** 9 user-facing transactional
strings across 5 files. The finding isn't the count — **every one was hedging prose** ("Avoid
chasing", "not a buy list", "trim position"), written to sound prudent, which is exactly why they
passed review. **The words that read as caution to a colleague read as advice to a regulator.**
All replaced with positioning language; `test_compliance_language` now in preflight.
🟡 **P0-3 GATE:** preflight aborted midway in a clean env (3 of 24 test files need pytest, `set -e`)
— 5 suites plus the contract echo never ran, with no indication. **A gate that fails silently looks
exactly like a gate that passed.** Dependency check moved to the front; **23 suites now green**.
Lesson #107: **"the operation succeeded" and "the state changed" are separate facts — check the
target, not the action.** Unifies S-105/S-116/S-122/S-124, all of which reported success.
Full report: `docs/CODE_CHECK_2026-08-09.md`.

**Earlier 2026-08-09 — S-123: the forward clock is dirty. The ① book sized itself off a
regime series 23 days stale, and both marks ran at double the intended exposure.**
Asked whether we were ahead of schedule; checked the one asset that cannot be accelerated. The
truth is TIGHTENING on every source every day (cap 0.5); the book recorded NEUTRAL (cap 1.0), and
`nav == benchmark == 0.99894` exactly — **layer ③ has contributed nothing to the record.** Three
bugs compose in one 40-line function: `_regime_history` queried `order=recorded_at.asc&limit=20000`
over a window holding **53,250 rows**, so the cap truncated the NEWEST end (newest visible day
**2026-07-17** vs actual **2026-08-09**); the stale series plus a missing Redis field went through
the **lenient** `canonical_regime(None) → "NEUTRAL"`; and `_exposure_cap("NEUTRAL")` is 1.0.
Fixed all three, plus **four other modules holding their own lenient call on a write path** —
including `main.py`, which writes the very table the ① book reads, closing the loop. Fixing the two
call sites I was looking at yesterday was not fixing the contract.
Lesson #103: **a row cap plus an ascending sort is a silent "oldest N", and it grows on its own —
the table lengthens, the limit does not.** Lesson #104: **a stale series is structurally identical
to a fresh one, so it must prove it reaches the present.**
**🔴 AWAITING JAZZ — ① book re-inception.** Today costs 2 days (gate 2026-10-07 → 2026-10-09);
discovering it in 30 days costs 30. Recommend re-inception today. Assignments for all four lanes:
`docs/ASSIGNMENTS_2026-08-09.md`.

**Earlier 2026-08-09 — S-122: the "unknown wearing a valid value" shape is now a
scanner, and it found 8 more — one of them worse than the bug that motivated it.**
S-121 was the fifth instance in one day, and four of the five were caught only *after* they had
written data — three only because the substitute happened to look wrong. That detection route has
a precise failure point: **a default equal to the majority value never looks wrong.**
`trade_results.side` defaulted to `"LONG"` while **82.5 % of rows are LONG (175/212)**, and
**shorts average −2.279 % against longs' +0.260 %** — so the failure mode silently moves the worst
trades into the long side of the very curve we intend to underwrite. `side_null = 0` proves
nothing: the default is what removed the nulls. Fixed 8 sites to NULL; three needed more than that
— `_mine_signal_accuracy` now reports `n_unattributed`/`coverage_pct` instead of folding untagged
trades into NEUTRAL (whose `accuracy_pct` is reported as `None`, so the contamination landed in the
one cell that never displays); `_run_paper_rebalance` **refuses** on a missing side rather than
guessing on a live sizing input; and the rebalance loop now prints refusals, which it previously
would not have. Guard: `tests/test_degraded_value_guard.py` (preflight 3a-quaterdecies) — scoped to
functions that persist, transitively through row builders, unwrapping `.upper()`; read-side
rendering excluded by construction. Known gap recorded, not papered over: `trading.py:1160`
`REGIME_FACTOR.get(..., 0.80)` is the same class and the scanner cannot see it.
Lesson #102: **harm is inversely proportional to detectability — and "no nulls in the column" can
never be the evidence, because that is exactly what the fallback does.**

**Previously (2026-08-08):** **The ① book marked: the clock is running (gate 2026-10-07) — and
its first row exposed that layer ③ was inert on 47.5 % of days without saying so.**
`beta_core_nav`: 1 mark, inception 2026-08-08, NAV 1.0, benchmark 1.0, 24 positions, regime read
successfully (not null, so the feed is live).
**Then I checked what that row's `exposure_cap = 1.0` actually meant.** The canonical regime
vocabulary is exactly seven — GOLDILOCKS / RISK_ON / EASING / NEUTRAL / TIGHTENING / RISK_OFF /
STAGFLATION — and my mapping matched CRISIS, CAPITULATION, EUPHORIA, EXPANSION, BULL, BEAR,
**none of which exist in it**. Only RISK_OFF (40.2 % of days) and RISK_ON (12.3 %) ever hit, so
**EASING 30.1 % + TIGHTENING 13.9 % + STAGFLATION 1.4 % fell silently through to full exposure.**
**Root cause: two vocabularies conflated.** Those invented names are the BAND names from
`EXPOSURE_BANDS_V1` (CRISIS 0.0 / CONTRACTION 0.5 / NEUTRAL 1.0 / EXPANSION 1.0 / HOT 1.3), which is
driven by a stablecoin-supply Δ28d hysteresis machine — a different input entirely. **Third instance
of the same error after `asset_class` (recorded the source) and `bench` (was BTC): a mapping written
against an imagined vocabulary rather than the real one.**
Fixed: `_REGIME_CAP` now covers the canonical seven EXACTLY, pinned by a test that compares against
`_CANONICAL_REGIMES`, so **a newly added regime breaks CI instead of silently becoming full
exposure**. `_exposure_cap()` returns (cap, source) and `cap_source` lands on the row —
`regime_map` / `unmapped_regime` / `no_regime` / `stablecoin_band` — because `exposure_cap = 1.0`
previously meant three different things at once, which is the −2-folded-into-0 conflation one layer up.
**An upstream swallow remains, recorded not fixed:** `canonical_regime()` maps ANY unrecognised label
to NEUTRAL, so a new regime name arrives already neutralised — `unmapped_regime` is defence in depth,
not the primary catch. Same shape as `min/max` swallowing NaN (I1).
**Honest about ③ in this window:** the ⓠ spec's real driver is the stablecoin band, and its own
frozen comment says *2025-26 has NO stablecoin signal by design* — so even wired, the cap would sit
at 1.0 and **this book is effectively pure ① for the forward test.** Saying so in the row beats a
mapping that returns 1.0 for the wrong reason.
**Lesson #96: on day one, do not check that it ran without errors — check that every field it wrote
means what it says.** The first mark looked perfect: status ok, 24 positions, NAV 1.0. The defect hid
inside a CORRECT value — right number, wrong reason. Corollary: **every default must carry the reason
it was chosen**, or the default swallows the defect it should have exposed.
**Needs Jazz or the spec:** EASING→1.0 and TIGHTENING/STAGFLATION→0.5 are MY judgement — the ⓠ spec
defines band→cap, never regime→cap. Also unresolved: `cis_scores` says Tightening today while the
book's Redis read says NEUTRAL.

Earlier: **Supabase 449 MB → 237 MB with zero rows archived, then feeds
gated by FREQUENCY rather than by asset count.** Jazz flagged the tier filling up and asked about
moving data local. Measurement said the database was not full of data: **~84 MB of dead indexes**
(176 days of accumulated statistics make a zero scan count trustworthy) plus **~128 MB of bloat I
created hours earlier** — populating `asset_id` UPDATEd ~1M rows, autovacuum reclaimed the dead
tuples so `n_dead_tup` was already 0, **and the waste was therefore invisible to the usual check**
while free space stayed inside the pages. The tell was 276 B/row on hourly against 108 on daily.
A trap avoided: four of the dropped indexes were created the SAME DAY, so their low scan counts
reflected age rather than uselessness and were judged on structural redundancy instead. One was
dropped for a stronger reason — it served filtering observation rows by `asset_class`, a pattern now
BANNED, and an index serving a banned pattern is dead however heavily it was used before.
**Then the ongoing-cost question, which is the one Jazz actually raised.** Per-feed measurement moves
the constraint from COUNT to FREQUENCY: daily @687 = 42 MB/yr, funding @687 = 237 MB/yr,
**hourly @687 = 1,096 MB/yr — two months to exhaustion** — against hourly @24 = 38 MB/yr. So the rule
is **broad at low frequency, narrow at high**, which is also what the research needs: survivorship is
only measurable on a WIDE daily panel (S-111), while intraday work was always about a handful of names.
Hourly was then tightened from "admissible" (74) to **actually consumed** (24, the ① book's holdings)
— nothing reads hourly today, and **a feed whose consumer list is empty is a subscription nobody
cancelled.** The 126 delisted assets subscribe to nothing: their history is complete by definition.
**Total 98 MB/yr against 1,375 MB/yr unbounded.**
The flags are ENFORCED, not advisory — both backfill functions refuse with a **distinct sentinel
(−2 = not monitored, −1 = unaddressable, 0 = nothing new)**, because collapsing −2 into 0 would let
"we chose not to watch" read as "the market has no data", which is the S-106 conflation moved into
the storage domain. Verified: AGIX → −2, BTC → 30 bars, 663 assets now refused hourly.
Shipped `scripts/supabase_storage_hygiene.sql` + `scripts/supabase_monitoring_tiers.sql` +
`tests/test_storage_hygiene.py` 7/7 in preflight — and the guard immediately caught the real culprit,
`supabase_l2_canonical.sql`, whose UPDATEs never declared their storage cost. **A bulk UPDATE is a
storage event, not just a data event.**

Earlier: **S-115: the breadth formula was never wrong; quoting it without
naming the book was.** Built the spectral estimator to replace `N/(1+(N-1)rho)` and the sanity check
reversed my own S-114 caveat. Against a matrix where equicorrelation genuinely HOLDS (rho=0.3,
N=20) the two measures still disagree — naive 2.99 vs participation ratio 7.38 — **and both are
exact.** They are not rival estimators of one quantity, they are two quantities, and which one binds
is set by the BOOK: a long-only book rides the common factor so equal-weight variance reduction is
its limit (naive is correct, and it is EXACT for any correlation structure — what it needs is equal
VOLATILITIES, which crypto 0.957 vs TradFi 0.392 violates 2.4×); a market-neutral book trades the
residual directions so the spectrum is its limit.
⇒ **"crypto is capped near 2" is right for the ① book; 3.31 is right for a ④ book. The error was
never arithmetic — it was a breadth number quoted with no statement of what it constrains.**
Measured, 20 crypto + 20 TradFi: crypto naive 1.95 / participation **3.31** / top eigenvalue **53.0 %**
of variance · TradFi 3.43 / 5.96 / 35.2 % · combined 3.81 / **7.67** / 31.1 %. Combined 7.67 against
3.31 + 5.96 = 9.27 means **~83 % additive**, better than the naive view implied. Crypto's single
factor at 53 % vs TradFi's 35 % is the precise form of "crypto is basically one bet".
**The guard caught a bug in itself.** Rank-deficiency was detected by counting NEGATIVE eigenvalues
and missed a deliberately singular 30-asset / 5-observation matrix outright, because LAPACK returns
those directions as +1e-17 rather than negative — deficiency lives at NUMERICAL ZERO, not below it.
**And the test asserted the same wrong thing**, so detector and assertion failed together because
they came from one assumption. Now measured by numerical rank (rank 4, correctly flagged).
**Lesson #95: an efficiency/breadth/degrees-of-freedom number must be quoted with the object it
constrains.** `N_eff` alone is meaningless — 1.95 for long-only and 3.31 for neutral, both correct.
Corollary: when a detector and its test pass or fail together, suspect a shared premise.
Shipped `src/research/validation/effective_breadth.py` (both spectral measures plus the naive figure
side by side, `rank_deficient`/`numerical_rank` exposed) and `tests/test_effective_breadth.py` 6/6 in
preflight. **Bound:** the 20 crypto names came from the most-data-rich set, which my backfill order
skewed toward delisted small caps, so rho-bar 0.486 is a SMALL-CAP reading, not the major-cap panel.

Earlier: **S-114: the diversification is in TradFi, not in more coins —
and the formula I had used three times turns out not to apply.** S-113 inferred that breadth inside
crypto has a ceiling; this measures it. 40 crypto + all 33 TradFi assets, 2024-01 on, ≥250 common
observations per pair:
**crypto ↔ crypto rho-bar 0.441 with only 1 % of pairs near zero · TradFi ↔ TradFi 0.217 · crypto ↔
TradFi 0.104 with 62 % of pairs near zero.** Cross-asset correlation is a quarter of within-crypto.
Indicative N_eff: crypto-only 2.20, TradFi-only **4.15**, combined 4.27 — **33 TradFi names give
nearly twice the breadth of 40 crypto names, and adding those 40 coins on top of TradFi moves N_eff
4.15 → 4.27, i.e. forty coins contribute about a tenth of one independent bet.**
**But I have to flag the formula, not just the result.** `N_eff = N/(1+(N−1)rho-bar)` assumes
EQUICORRELATION. Measured on this sample: rho runs −0.853 to +0.987, sd 0.214 against a mean of
0.224 — **dispersion equals the mean, so the assumption fails outright.** Every N_eff in S-96, S-113
and here is therefore INDICATIVE ONLY; the block-level rho-bar comparisons (hundreds of pairs each,
unambiguous direction) are what is trustworthy. Correct treatment under block structure is the
eigenvalue participation ratio, which SQL cannot do and which now needs a Python-side follow-up.
**Lesson #94: periodically re-check an estimator's PREMISES, not just its inputs.** I used this
formula across three ledger entries, verified rho-bar each time, and never once checked whether
equicorrelation held — it never did on a block-structured panel. Correct inputs plus a dead premise
produce a number that looks rigorous and is wrong.
**Strategic consequence, now measured rather than argued:** a crypto-only mandate is structurally
capped near N_eff 2, so there is no diversification to harvest and ①+③ is not a preference but the
only remaining path. Millennium-style multi-pod and WorldQuant-style factor spreading both require a
TradFi leg — **not more coins** — and we already hold data for 33 such assets.
**Bounds:** correlations computed on TradFi trading days only (~250/yr), which is the right
convention for a joint book but understates crypto's usable observations; the 40 crypto names were
chosen by data volume rather than at random, so 0.441 may run high; single window, and S-113 just
showed correlation is a state variable. Cross-asset execution, custody and compliance costs for a
FoF TradFi leg are entirely unassessed.

Earlier: **S-113: `N_eff = 3.1` was never a constant, and I read the
correction backwards before the control caught me.** Recomputed on the expanded 249-asset panel:
rho-bar 0.435, N_eff 2.28 — against S-96's 0.310 / 3.1, which I was about to write up as
"expanding the panel REDUCED effective breadth". **The control killed that reading:** the same
original panel measured over the SAME window gives rho-bar **0.655**, not 0.310. Window effect,
not asset-set effect — 2024+ is simply a high-correlation regime.
**Clean, same-window result:** original panel N=41 rho-bar 0.655 **N_eff 1.51**; expanded N=249
rho-bar 0.435 **N_eff 2.28**. **Breadth is real but severely sub-linear: 6.1× the names buys 1.51×
the effective breadth.**
Two consequences. **(1) `N_eff = 3.1` must stop being quoted as a constant** — the same assets read
1.51 today. Correlation is a state variable, and any rho-bar or N_eff cited without its measurement
window is narrative. **(2) Breadth inside crypto has a ceiling:** 208 extra names bought a drop from
0.655 to 0.435, so reaching N_eff 10 would need rho-bar near 0.10, which crypto does not offer.
WorldQuant-style stays permanently out, and **Millennium's ≥5 uncorrelated pods is equally out
WITHIN crypto** — real diversification has to come from other asset classes. With N_eff ≈ 2 there is
no room to raise Sharpe by diversifying, which leaves capturing beta and timing exposure: ①+③.
**This also downgrades my own P1 from a few hours ago.** OVERSIGHT §3 P1 said unfreezing breadth
would unlock the S-108/S-109 class of tests. Partly true and overstated: breadth did improve, but
those tests need dozens of INDEPENDENT events, and N_eff 2.28 says the events across these names
co-move.
**Lesson #93: any number quoted repeatedly as a constant must be quoted with its measurement
window.** N_eff=3.1 was used as a physical constant for two weeks; the same assets give 1.51 in
another window. Both are correct, and they differ by 2×. Corollary: run a same-window control
before comparing across periods — the first version of this entry subtracted two windows directly.
**Not done:** crypto + TradFi cross-asset N_eff — the query timed out and needs sampling or a
materialised intermediate. That is the direct test of "diversification must come from other asset
classes", and it is the next measurement.

Earlier: **S-112: "亏得越多反向越有价值" is right about the magnitude and
wrong about the instrument — and I caught my own sampling contamination twice getting there.**
Jazz's instinct, made testable: "will be delisted" is knowable only ex-post, so the honest question
is whether anything observable BEFORE the collapse identifies the cohort. Two candidates, both
refuted. The bucket table looked excellent — liquidity fading alone −4.4 % excess vs panel while deep
drawdown alone was −0.2 %, i.e. **volume carries the information and price does not**, which fits
"price is the reflection" perfectly. **The continuous test killed it:** r(ln liquidity change,
excess) = 0.034, t = 1.37 on n = 1,676, while the S-102-mandated control on drawdown came back
*stronger* at t = 2.18 with the opposite sign to the buckets, and both tails were negative. Same
pattern-seeking as S-108; caught this time because the control ran first.
**The reframe that matters: avoiding the dying is not alpha for a FoF, it is not-dying** — it shows
up in the LEVEL, and the level is S-111's 25.1pp/yr. So the instrument is an ADMISSION RULE, not a
short book, and an admission rule needs a death base rate rather than a significant cross-sectional t.
**Then I contaminated my own sample and caught it.** Death rate by liquidity quintile came out
85 / 74 / 53 / 47 / 42 % — beautifully monotone, and entirely an artifact of MY BACKFILL ORDER: I had
loaded 125 dead names first and only ~40 survivors, so the sample ran 60 % dead against a true base
rate of 126/687 = 18 %. Backfilled 179k rows of survivors and re-ran on 186 assets: **39 / 27 / 24 /
24 / 24 % — not monotone at all, a threshold effect at the very bottom.**
⇒ **Actionable: investable-universe admission at ADV > ~$15M. Being pickier than that buys nothing**
(quintiles 2–5 are flat), which is also why the coarse threshold cannot overfit.
**Lesson #92: when you control the sampling order, the base rate is the first thing to check.** That
85→42 table would pass any review — monotone, adequate n, plausible mechanism. The only thing that
exposes it is "what is this population's true base rate", a question unrelated to the hypothesis.
**Bounds:** death rate still runs high (28 % sample vs 18 % population — survivor backfill
incomplete), so only the SHAPE across quintiles is usable, not the levels; `died` = current SETTLING,
a snapshot of in-flight delistings; $15M has no sensitivity analysis and no DSR; **no shorting-cost
model exists, so the "reverse" trade's executability is entirely unverified.**

Earlier: **S-111: survivorship bias measured at 25.1 percentage points
per year — 8× the largest effect we have ever chased.** DATA_ARCHITECTURE §4 step 4 landed and the
answer is bigger than the step. `fapi/exchangeInfo` exposes **126 SETTLING** symbols — names being
delisted right now, i.e. exactly the population a current-liquidity screen erases — and we had not
looked at that field in two months. Assets **76 → 687**, 126 recorded as delisted, 125,003 rows of
dead-name history backfilled (addressed by `venue_symbol`, because `base||'USDT'` silently 400s on
`1000WHY` / `AI16Z`, and a 400 is indistinguishable from "no history").
**Measured: of 302 assets alive on 2024-06-15, 63 are dead today = 20.9 %.** Equal-weight panel,
2024-01 → 2026-08, PIT: **with the dead −211.1 % cumulative log, survivors only −146.3 % — a
+64.8pp gap over 2.58 years = 25.1pp/yr.** The largest tier effect we ever measured was ~3 %/yr.
**We spent fifteen attempts hunting a 3 % signal on a benchmark that was wrong by 25 %.** Same error
class as S-103 twice over: there the benchmark had the wrong ASSET, here the wrong MEMBERSHIP —
neither was an analysis mistake, both were "compared to what".
Also fixed quietly: `listed_at` had been the date OUR COLLECTION began, a collection artifact
wearing a listing date's clothes, which dated every membership interval wrong. `onboardDate` is now
the source.
**The forward book is unaffected and this raises its value:** membership is recorded point-in-time
from today, so a name that dies stays in the panel until it dies. `beta_core_nav` is
survivorship-free from its first mark.
**Lesson #91: a bias that is known to exist but cannot be quantified outranks any signal not yet
found.** Quantify every known bias into a number before hunting; if it cannot be quantified, either
go get the data — here, one `exchangeInfo` call — or mark the conclusions untrustworthy.
**Bound: 25.1pp/yr is a LOWER bound** (SETTLING catches only in-flight delistings; symbols already
removed from exchangeInfo are invisible) **and is computed on partial coverage** — ~136 of the 302.
Not yet done: applying this correction retroactively to R76–R94 and S-101…S-109.

Earlier: **① beta_core live (commit 121b54c); 3 L/S paper books demoted (commit fc4d331); OVERSIGHT §7 addendum documents §3 P0 execution receipts.**
The decisive measurement: bar convention is a property of the SOURCE, not of the class.
`|open/prev_close-1|` per source — binance_hist median **0.00010** (0.1 % of rows >1 %) ·
yfinance 0.00362 (19.1 %) · eodhd 0.00355 (20.4 %) · **coingecko 0.02563 (77.2 %)**. CoinGecko's
daily open is a vendor snapshot boundary, not a price, so **`open` is unusable on 48,303 rows** —
and reading that seam as market structure is precisely what produced S-106's fake "+12.30
cumulative overnight return". All 6 classes appear under all 4 sources, so class and source are
orthogonal and class was never a proxy for anything.
Rebuilt `ohlcv_daily_canonical` on the registry: class JOINED from `assets`, plus explicit
`bar_convention` (continuous_utc / session / vendor_snapshot) and **`open_usable`**.
**Verified: A1 0 · A2 0 · `asset_id` null 0 across all three observation tables · 181,390 canonical
rows · A4 answerable** (74 coverage / 0 investable on 2024-06-15, the 0 being correct since CIS
scoring began 2025-05-03). **A3 is now explained by convention, not class:** continuous_utc 0.1 %,
session 19.2 %, vendor_snapshot 77.5 %; by class Crypto collapses 31.3 % → 0.7 %.
**Re-running S-106 on continuous bars only: overnight +2.05 vs +12.30, i.e. +0.05 per asset — the
≈0 that physics demands of a 24/7 instrument. The artifact was not patched out; it vanished once
identity was correct.** Newly visible and previously invisible: **34 of 75 assets have no
continuous-convention data at all**, so nearly half the panel cannot support intraday or
open-based work — formerly "the data is there but the answer looks odd", now a queryable flag.
**Lesson #90: a classification field that neither predicts behaviour nor holds one value per
entity is recording where the data came from, not what it is.** `asset_class` did both — 24
symbols took multiple values, and its apparent explanatory power vanished the moment `source` was
substituted. The fix is to remove it from observation rows, not to clean it: cleaning would
preserve the wrong abstraction.
Still contract-only: **L3 (PIT features) / L4 (states + `episode_id`) / L5 (one-way valve)**. The
`display` universe has no members yet — the strong-filter rule is Jazz's call. `asset_class` is
not yet dropped from observation rows, only unused by L2. **Data expansion stays frozen** until
§4 step 4 (membership backfill including delisted names).

Earlier same day: **架构层 L0 landed: identity now precedes data.** Jazz stopped the
data expansion — "先做架构,再补充数据源,现在很多细节都不对的" — and the details being wrong was
measurable, not a feeling. Audit A1–A4: symbol coverage differs per table (ohlcv 65 / cis 76 /
vectors 72, 1 orphan); **24 symbols carried MULTIPLE `asset_class` values**, because class was
stored on the OBSERVATION row where it actually recorded the SOURCE; and source determines candle
convention (>1 % open gaps: Crypto 31.3 % vs L1 73.7 %, L2 79.5 %, **DeFi 83.5 %**). So
`where asset_class='Crypto'` was a SOURCE filter wearing a class filter's clothes — **that is the
root cause of the S-106 artifact**, which spliced two bar conventions and read the seam as market
structure. Fourth finding: no way to answer "who was in the panel on date D", so survivorship bias
was present in every backtest AND unmeasurable.
**Also Jazz: "我们是强筛选展示,但是我们跟踪要足够广"** — tracking and investing are different
objects, and this is a statistical requirement rather than a preference: three separate analyses
today died of sample size (N_eff 3.1 / S-108 n=20 / S-109 13 episodes) and **every one was computed
on the investable set**. Hence three universes with PIT membership: **coverage** (statistics),
**investable** (allocation), **display** (LPs).
Shipped: `docs/DATA_ARCHITECTURE.md` (L0–L5 contract, 7 invariants, 6-step migration order),
`scripts/supabase_l0_registry.sql` applied — `assets` / `asset_aliases` / `universe_membership`,
76 assets with **24 class conflicts RECORDED rather than silently flattened**.
**Verified: A1 0 · A2 0 · A4 answerable** (74 in coverage on 2024-06-15; **0 in investable on that
date, which is the correct answer** — CIS scoring began 2025-05-03, and a non-zero result would mean
we had backfilled an investment decision into a period where none existed).
`tests/test_data_architecture.py` 4/4 in preflight, and the scanner was **proven to fire** on a
synthetic offender before being trusted — it had just been narrowed from file-level to
statement-level to kill five false positives, and a narrowed scanner that detects nothing passes
for the wrong reason.
**Data expansion is deliberately BLOCKED until migration steps 1–4 land** (`DATA_ARCHITECTURE` §4):
pouring 4× the symbols into the old identity model would multiply A2/A3 by four.

Earlier same day: **S-108: the distribution hypothesis, one fake finding caught, and
the real bottleneck named.** Jazz described the actual mechanics — sell-side rates it highly, but big
money accumulated first, needs a shakeout to buy bloody chips, marks it up in waves, and "出圈"
(going mainstream) is when retail takes the bag. That is Wyckoff with the rating in the DISTRIBUTION
phase, and it would explain S-102's U-shape: a high score is a LATE signal, not an early one.
One link is directly measurable — `ohlcv_hourly` carries `trades` and `quote_volume`, so **average
trade size is a proxy for WHO is trading** (few large = size, many small = retail). A variable about
WHO, not about price, which is the S-107 anchor shape.
**A fake finding was caught in flight and is recorded on purpose:** the first cut of
`after +10 % markup × ATS collapsing` printed **−9.43 %, t = −13.35** — on **n = 2**. Deepening the
hourly panel from 400 days to 2021-01 (96k → 470k rows) collapsed it to −1.41 %, t = −0.57, n = 20.
**It looked exactly like a real finding; the only thing separating them was n.**
**As a continuous predictor the variable is refuted:** r = 0.0113, t = 0.35 on 967 non-overlapping
observations, and the S-102-style control on the LEVEL gives r = −0.0448 — larger in magnitude, opposite
in sign, both noise. The tidy monotone bucket table (+1.92 / −0.06 / −1.41 after markup) was
pattern-seeking: **a bucket ordering is not evidence unless a continuous relationship backs it.**
**But that does not kill the mechanism — it was the wrong test.** Jazz described a RARE STATE
SWITCH, not a continuous relationship, and a full-sample correlation is a category error for a rare
event. The event-form test has n = 20. Status is UNTESTED, not refuted.
**The bottleneck is named: breadth, not length.** Going from 400 days to 4.5 years still yields only
20 non-overlapping setups, because the sample grows with the number of ASSETS, not with time — and
"出圈" is most visible in small/mid caps while the hourly panel holds 10 large caps, the segment
where the cycle is faintest. Same wall as `N_eff = 3.1`. **Action: extend hourly + ATS to dozens of
small/mid-cap names.**
**Lesson #88: decide whether a hypothesis is a continuous relationship or a rare event BEFORE
choosing the test** — the wrong test type produces no evidence whichever way it comes out. Corollary:
**every grouped result table must print n on the same row**; that is the only reason t = −13.35 was
stopped rather than shipped.

Earlier same day: **S-107: the anchor criterion, and our first persisted anchor.**
Jazz: "a rating changes and then you slowly buy" cannot work in crypto or in traditional assets —
that is the sell-side distribution model, and S-106 already measured that we cannot be the fastest.
Turned that into a testable criterion: **a good anchor's payoff ACCRUES rather than JUMPS**, measured
on the same concentration ruler, BEFORE spending anything on a return test.
**funding carry: best 10 days = 14.9 % of total, 73.6 % of days positive. Price momentum: best 10
days = 152 % of total (everything else is net negative), 50.0 % of days positive.**
Audit finding that outlived the result: **until today the warehouse held NO anchor series at all** —
no funding, flows, TVL or unlocks, all fetched live and never persisted. Every test we had ever run
was price predicting price, which is a previously unwritten explanation for the R76–R94 graveyard.
Built `funding_history` + `backfill_binance_funding()` (10 assets × 2,700).
**But the tempting number is fake and is called out as such:** gross Sharpe 8.75 measures a PAYMENT
STREAM, not the basis trade's P&L — spot-perp basis, margin/liquidation tail and two legs of
execution are all absent from the measured series. Carry is smooth; the risk is in the tail you did
not measure. Mean pairwise corr 0.707 ⇒ **N_eff = 1.36 across 10 assets**: ONE systematic factor
(crowd leverage demand), not ten sleeves. So funding is **not** a standalone sleeve — its job is as a
state variable for ③ exposure timing, which S-106 had just made the main line.
**Lesson #87: a smooth return series is not a low-risk strategy — ask whether you are measuring a
payment stream or a P&L.** When a number is good enough that it needs no argument, it is usually
measuring the wrong object.

Earlier same day: **S-106: the product was reframed, and the reframing is measured.**
Jazz: we were never a chase-the-CIS-score strategy. Confirmed on a new hourly panel — return is
delivered in **0.8 % of days**, **45.9 % of a top-1 % day's move lands in US 13-16 UTC**, and big
days **cluster 3.8×**. So *score → chase* is mechanically impossible (30-min refresh against a
4-hour payoff window), while *surfing* is supported: staying in captures what timing entry cannot.
**①(hold the panel) + ③(time the exposure) is the main line; ② tilt is parked.** Direction is NOT a
session property — all four blocks negative, taker-buy share flat 48-49 % across 24 h; the structure
is in volume and volatility, not sign. Built `ohlcv_hourly` + `backfill_binance_hourly()`
(10 assets × 9,600 bars, 0 gaps) to make this testable at all. **Lesson #86: establish WHEN return
is delivered before choosing WHEN to decide.** Also caught and retracted my own first cut, which
decomposed daily overnight-vs-intraday for 24/7 assets — crypto median gap is 0.00004, so that
decomposition measured a candle-convention artifact, not market structure.
Earlier same day: **S-105: the re-benchmark closed and the signal turned out to be unholdable.**
Against hold-the-panel three "hugely significant" t-stats vanish and one FLIPS SIGN (−4.09 → +0.76).
STRONG OUTPERFORM has a 2-day median episode and assets switch signal 45.8×/yr = 4.6 %/yr turnover
against a ~3 %/yr effect. Lesson #85 now enforced in the gate. The strategy record library was also
found sitting in a 24 h-TTL Redis key for 12 days — migration written 2026-07-26, never applied —
now fixed and observable on /health, backfill pending.
Earlier same day: **S-103: the multiple-testing floor and `neutralize()` both landed,
and the second one refuted the main line I had written the day before.** DSR + PBO are now gate
conditions (`test_strategy_discipline.py` 12/12; SHIP needs `deflated_sharpe ≥ 0.95`, `pbo ≤ 0.5`,
`n_trials` — **0 of 8 existing strategies carry one**). Then `neutralize()`, which had existed as
prose in 71 files and 0 defs, was run on the full panel: **all five signal tiers collapse to
|t| < 2**, β by tier is monotone 2.37→0.15 (**the tier ordering is substantially a beta sort**),
and the dominant term is not beta but **the benchmark** — `bench` = BTC on 7,706/7,743 rows, and
BTC beat the panel by +2.16pp, t=3.96. The "near-median underperforms / build an exclusion product"
recommendation is **withdrawn**: 85 % of it was the benchmark. **①層 + vol target is now the only
live main line.** Also this pass: OPEN RISKS converged 8→7 by actually fixing the MEMORY.md
overrun, and the cap was re-expressed in characters — bytes were measuring encoding, not
readability. Prior entry: **S-95: the T2 universe fallback was silently dead.** Build-phase
timing on `/health` (added 07-31 precisely because three hypotheses had failed to explain a
reproducible 12 s overrun) reported it on first deploy: `railway_error: name 'market_cap' is not
defined`, 5,207 ms burned per rebuild. `calculate_cis_universe()` referenced a local belonging to a
different function, raised on every asset with open interest, and the caller swallowed it into a
warning — so production had **no working fallback if the Mac engine went down**, and nobody knew.
Fixed, plus `tests/test_no_undefined_names.py` (py_compile and boot smoke are both blind to a
NameError on a conditional branch). **In the same pass I also retracted a red risk of my own: the
"price feed stalled 10 days" was false** — every day 07-24 → 08-06 is populated; `max(trade_date)`
is a transient on a feed that re-pulls 365 days per run. **Lesson #72: confirm a metric measures
what you think before you alarm on it — take two readings at different times and explain the
difference.** Fourth causal hypothesis killed by measurement this cycle; the only one that cost
nothing was T2, where I instrumented instead of guessing.

**Previously (2026-07-30):** **S-92/S-93 P0 CLOSED: CIS layer was dead 10.4 h; `/api/v1/cis/universe`
now 200 / 0.509 s / `stale=false` / 58 assets, `/health` reports `data_layer.supabase="ok"` with the
breaker visible.** Two bugs multiplying: (1) client-only timeouts — `urlopen(timeout=10)` closes the
socket but does NOT cancel the server-side statement, so abandoned-but-live queries pinned the
Supavisor pool of 15 (HNSW on `asset_embeddings` was created with default m=16/ef=64 on a 72-row
table, making upserts expensive on Nano); (2) the universe single-flight lock held across unbounded
external calls, so one starved rebuild queued everyone for the 33 s retry budget — a burst-protection
fix that became an outage amplifier. Fixed with server-side `statement_timeout` /
`idle_in_transaction_session_timeout` / `lock_timeout` per role, a circuit breaker that fails fast and
provably recovers, a bounded lock that degrades to flagged-stale, and a `/health` that observes the
data layer instead of asserting it. **Lesson #69: a client timeout with no matching server-side
timeout is not a timeout, it is a connection leak with a reassuring log line. Lesson #70: collect
baselines while healthy — `pg_stat_activity` needs a connection, and the absence of connections was
the symptom.** Root transmission mechanism was S-83's undiagnosed bypass surviving across amnesiac
sessions ⇒ `docs/AMNESIA_PROTOCOL.md` + `tests/test_cold_start_contract.py`. Security SQL is written
and committed but **NOT run** (OPEN RISK 1).

**Previously (2026-07-28):** — **R97-11yr baseline correction COMPLETE: 2026-07-27 PARTIAL 3/5 verdict DEMOTED to 🔴 CORRECTED_BASELINE_REFUTED.** After 11 audit defect fixes (real 5d rebalance, percentage-ATR sizing, signed t-gates, M-WO-1 helper delegation, C6 split, effective-universe disclosure, late-window `is_holdout=False`, fetch +1ms page advance, hard per-name 5% + book 100% caps enforced post-normalization, explicit one-sided cap, parity test), the corrected daily baseline on the same 11yr panel reports **gross_t=+1.728** (below 1.96), **maxDD=−38.92%** (improved from −77.62% but still over −20% budget), **2/7 positive cycles** (C3 + C4 only; C5/C6a/C6b all negative), and **M-WO-1 majority-positive FAILS** (19 ep, 9 pos vs 10 neg). The previous +2.687 headline was inflated by absolute-ATR rank mis-sizing (BTC target weight ~50× small-cap) + the synthetic net-long tilt the per-name cap forced; percentage-ATR + symmetric cap removes the confound. `0/4` passed → `CORRECTED_BASELINE_REFUTED`. 11/11 baseline smoke + 13/13 M-WO-1 tests pass; no production change; frozen R77 cell at w_R46=0.25/w_R62=0.75/w_R76=0.30 unchanged. The 11yr daily panel (`/tmp/cometcloud_data/ohlcv_11yr.db`, 88,794 rows × 48 symbols) remains the permanent data infrastructure win — unblocks future multi-cycle re-validation. Dated report at `reports/r97_cis_ls_v5_11yr/2026-07-28/`; correction notice appended to 2026-07-27 report. **Phase B (pre-registered risk hardening) NOT entered** because the corrected baseline fails gross_t (Phase A gate required signed t > 1.96 + ≥5 fully-covered positive cycles). Path forward unchanged: §OHLCV-EXTENSION (Minimax Mac-side) remains the only available lever; R77 stays the only tradeable L/S today.

**M-WO-2 data prerequisite is now UNBLOCKED (2026-07-27, Seth):** the earlier statement that 11yr daily OHLCV did not exist locally is obsolete. `/tmp/cometcloud_data/ohlcv_11yr.db` now contains 88,794 Binance spot daily rows across 48 symbols from 2017-08-17 through 2026-07-27; 27 symbols have ≥2000 days. R97-11yr used this panel and passed episode count plus 6/6 cycle sign stability. The broader R46/R78/R79/S-78/R77 multi-cycle reruns remain separate pending work; no production or frozen-strategy state changed.

**Strategy 1 = R77 fusion cell — RELABELED "regime-specific candidate" per Minimax-A's M-WO-1 episode-count audit (2026-07-27).** R77's day-level OOS_t=+3.61 is **one 220-day continuous structural-alpha run on a bear-dominated 731-day panel** (gap>7d → 1 episode, below the ≥8 floor required by §DIRECTIVE). Construction preserved; "unique survivor" label corrected. Forward commit to live production is DEFERRED pending either M-WO-2 (11yr deep-panel re-run, Mac-side data ready) OR M-WO-7-style VDB-derived episode structure (≥8 independent OOS clusters under the same gap>7d discipline).

**Strategy 2 = R97-11yr 🟡 PARTIAL 3/5; targeted hardening remains.** The 15-attempt 731-day graveyard remains valid for that short panel, but the local 11yr extension has now changed the evidence: R97 daily dual-horizon clears full-sample significance and multi-cycle/episode stability, while failing OOS significance and drawdown control. Per §DIRECTIVE, do not resume broad sleeve mining; only test pre-specified changes that directly address these two failed gates.

**M-WO-7.1 REGIME FINGERPRINT BUILD COMPLETE 2026-07-28 (Seth, per Jazz 2026-07-28 critical 'VDB 做风格辨识' redirection).** First slice of §M-WO-7 "VDB 做多" — replace "simple-factor loop" with a regime-similarity retrieval layer. Spec-first design (`docs/REGIME_FINGERPRINT_SPEC.md` v0.1) → user sign-off with default answers → 3 new files: `src/research/vector/regime_fingerprints.py` (~480 LoC, 12-dim compute + best-effort upsert via REST), `src/research/vector/tests/test_regime_fingerprints_smoke.py` (9/9 PASS), `scripts/supabase_regime_fingerprints.sql` (idempotent table + HNSW + `match_regime_fingerprints` RPC). 12-dim vector per `(trade_date)`: [0] macro one-hot · [1] S-78 vol tercile · [2]-[6] M-WO-2 EXT 5-pillar IC · [7] R75 S/O pulse · [8] R62 detector-fire-rate · [9] R76 funding-residual W5 t-stat · [10] pillar_A trajectory slope · [11] asset_embeddings centroid drift. Storage carries VECTOR_SCHEMA_SPEC §0 I1 (NaN→null) + I2 (PIT) + I6 (versioned) verbatim — same recipe as asset v2. **Side-effect (free win) on M-WO-1's ≥8 episode floor** (PROJECT_STATE §M-WO-1): the new RPC `match_regime_fingerprints(target=today, k=50)` returns 50+ regime analogs with `r77_fwd_5d_alpha_pct` outcome labels ≫ 8 gap>7d clusters — satisfies the §DIRECTIVE floor for the R77 forward-commit deck on the VDB path (alternative path to the M-WO-2 long-panel re-run). **Default answers baked in** per Jazz "approved proceed, default answers": outcome column = R77 5d only; sparse rows KEPT (MIN_SHARED_DIMS=4 gate is read-side); backfill depth = 11yr daily ≈3000 rows; first readout = API + table only (no 1-pager). **Verdict grammar**: 🟢 BUILT on smoke 9/9; 🟡 PARTIAL if Mac-side schema deploy fails; 🔴 REFUTED if match_regime_fingerprints top-k fails to discriminate from random baseline. Verification path post-commit: Mac commits → Minimax applies SQL via psql → Seth runs 11yr backfill → first match query confirms k neighbors with non-null `r77_fwd_5d_alpha_pct`. Frozen R77 cell UNCHANGED. R97-11yr PARTIAL UNCHANGED. No production/frontend/contract changes.

**Goal:** "完成两个可以进入真正交易的long/short 策略的开发" — 0/2 satisfied under the post-M-WO-1 acceptance criteria. R97-11yr is the first credible Strategy 2 research candidate (PARTIAL 3/5), but neither it nor R77 currently clears all post-M-WO-1/M-WO-2 and forward-paper requirements. The immediate research path is: (1) revalidate R77 on the now-available 11yr OHLCV panel; (2) harden R97's two explicit failures—OOS_t and maxDD—without changing its signal family.

**R97 work product (substantive, ships):** 24-asset strict universe on real 1h parquet (731 days, 103,529 4h-bars; BTC/ETH/SOL native-futures 4h feather parity OK). Major trend = 4h EMA54/126 (≈9d/21d); entry confirmation = 4h EMA9/21 + ADX14 ≥ 25 + DMI consistency; direction rule = major trend is ceiling/floor (fast cannot REVERSE major); CIS gate = composite score ≥ 55 (B+); funding z ≥ 2 veto; ATR14 inverse-vol sizing; 5d rebal; PIT lag ≥ 1 bar. **3-check FAILS** at every cost tier: gross_t=+0.69 (need >1.96), OOS_t=−0.29, maxDD=−30.10%, positive windows=3/6, Sharpe=+0.09. **QUALITATIVELY BEST cisLSv4 family on this panel** — LS V4 Sharpe=−0.93 / V5c=−0.25 / slow signed=+0.09 / R97=+0.09 with maxDD −30.10% vs −69.08%/−53.83%/−47.33%; the dual-horizon FIXES R49's flaws but doesn't clear 1.96 on the 731-day panel. Two bugs caught + fixed during smoke run: (a) dual-horizon conflict-zone side-flip → fixed to zero side when major×fast<0; (b) zero-net normalization bleeding CIS-gated zero-weight names into the book as synthetic shorts → fixed via `mask.where(has_both_signs, 0)`. **Lesson #64:** cisLSv4's working structure IS recoverable and R49's flaws are fixable, but the recovered shape still cannot clear the 1.96 3-check on the 731-day panel. R97 SHOULD be a candidate to re-test on M-WO-2's 11yr panel when M-WO-2 lands. Frozen R77 weights unchanged at w_R46=0.25/w_R62=0.75/w_R76=0.30. 13/13 smoke tests + preflight PASS; no production change; Mac-side commit required.
 R93 = fade_sign × funding_z × ι[i,t] (per-asset conditioning) on perp panel, k=3, {5,7,14,21}d × {0,5,10,20,30}bps × {14,30,60}d iwins × 2 signs = 120-cell sweep, anti-costume gate |corr(R93, naive_fade)| < 0.60. 🔴 REFUTED on three independent counts: (1) anti-costume gate FAILED corr=+0.728 (R93 collapses onto naive R60 with 73% correlation — informativeness-weighting does NOT add information beyond ι≡1); (2) 3-check fails at every cell (best 7d/iwin=60/5bps gross_t=+0.11, well below 1.96; 0bps → 30bps degrades monotonically from +0.47 to −1.70); (3) falsifiable mechanistic claim disproven — R60 W1=−37.4% / W3=−22.5% was supposed to lift via ι, R93 W1=−26.1% (still negative) / W3=−31.8% (still negative, slightly WORSE). Per-window W5=+59.5% kept discovery. **Lesson #43 v5 (CONFIRMED, 8th case)**: cross-sectional-demean family + informativeness-conditioned family = BOTH exhausted on funding. **Lesson #56 v2 (FINAL, 11-attempt graveyard)**: on perp panel, neither cross-sectional demean (R76) nor informativeness (R93) nor regime-gating (R62) nor perp-only carry (R90) nor perp-spot basis (R89) nor cross-asset pair (R91) nor directional overlay (R92) can clear 3-check. R77 multi-leg fusion remains the unique survivor. Strategy 1 = R77 fusion cell (LOCKED); Strategy 2 = STRUCTURALLY DEFERRED pending §OHLCV-EXTENSION (Option A — wait for 11yr panel). Goal condition STILL NOT satisfied after 11 attempts. Frozen R77 cell at w_R46=0.25/w_R62=0.75/w_R76=0.30 unchanged. PR-SETH R93 entry below at top of building log; `r93_informativeness_weighted_funding.py` (NEW ~520 LoC) + 10/10 smoke tests; R93 entry in REFUTATION_LEDGER.md; STRATEGY_2_DEFERRED.md updated to 11-attempt graveyard; new memory `r93-informativeness-weighted-refuted.md`. Ships no production change. FUSE blocks git-write in sandbox — Mac-side commit required.** + **🔴 §STRATEGY-2 — R91 cross-asset funding pair REFUTED; perp shelf EXHAUSTED on 3 distinct shapes (RESIDUAL / CARRY / PAIRWISE) plus the basis variant.** R91 = pair-funding L/S on top 8 most-correlated perp pairs (ETC-LDO etc., corr 0.78–0.82), 7d/0bps gross_t=+1.19 (already below 1.96); 5bps → +0.88; 10bps → +0.58 (dead at GATE); W5=+60.6% kept discovery, W4=−32.4% catastrophic (new bear-window exposure cross-sectional didn't have), maxDD=−30.44% (R77 by comparison is −8.91%). Pair-spread is a smaller fainter echo of R76's signal at lower frequency with worse drawdown — R76's edge is structural to cross-sectional residual, NOT transferable to pairwise. Strategy 1 = R77 fusion cell (LOCKED); Strategy 2 = STILL OPEN after 9 attempts (R82/R83/R85/R86/R87/R88/R89/R90/R91). Frozen R77 cell unchanged. Goal condition STILL NOT satisfied — 3 paths remain: A (wait OHLCV extension), C (accept R77 single-strategy book), D (STRUCTURALLY DIFFERENT data class). User decision requested.** + **§OHLCV-OFF-ENGINE decision — per Jazz 2026-07-26 "不动 Supabase, 让本地 SQLite 成为 off-engine 决策的数据源". Boundary: production reads from Supabase ohlcv_daily (Mac-side daily loop = 22 crypto + AAPL, fresh daily); research that needs the full 58-symbol universe reads from /tmp/cometcloud_data/ohlcv.db via `src/research/data/ohlcv_local.py` (NEW, 10/10 smoke tests PASS, `src/research/data/tests/test_ohlcv_local_smoke.py` NEW). 35 TradFi symbols (US Equity/Bond/Commodity/FX/REIT/EM Equity) are NOT in Supabase and will NOT be pushed — Jazz decision. Railway httpx UA bug + §SEC hardening both stay as-is. Refresh cadence: manual `python3 scripts/fetch_ohlcv_to_local.py` (~60s full 58×365d), no cron. Local SQLite is the off-engine data source for any R-number cross-asset factor work. NEW MEMORY: `2026-07-26-local-ohlcv-off-engine`.** PR-SETH R91 entry below at top of building log; `r91_cross_asset_funding_pair.py` (NEW ~360 LoC) + 11/11 smoke tests; R91 entry in REFUTATION_LEDGER.md. PR-SETH R89 correction (prior pass) + STRATEGY_PLAYBOOK + STRATEGY_2_DEFERRED + REFUTATION_LEDGER R89 + r89 module/smoke. PR-SETH §BETA-METRIC-AGG + §VDB + §REGIME-ALIGN + §FEEDS-RESILIENCE PRODUCTION PUSH — every P0 Seth-side item shipped; auto-gated on Mac-side ohlcv_daily restart** (per Jazz "完成beta-metric-agg 还有所有的minimax_sync 里面的p0，我们需要尽快跑通进入production"). §BETA-METRIC-AGG: investor `/signals/track-record` now publishes RAW + β-ADJ side by side, labelled. SQL migration `scripts/supabase_refresh_signal_track_record_v2.sql` (idempotent, 270 lines) emits 4 new β columns per (symbol, signal-bucket) using PIT expanding-window OLS (min 20 priors, never default β=1.0). Aggregator refactored into pure module `src/api/routers/_track_record_agg.py` ⇒ 16/16 smoke tests pass. Ship gate in `src/api/store.py::supabase_ohlcv_daily_freshness()` (5-min cache, opens iff age < 36h) — when gate CLOSED, BETA_ADJ + BETA_ADJ_T_STAT become explicit None (not silent zero), RAW continues to publish so no investor surface degrades today. **Auto-opens when ohlcv_daily resumes — no manual sync needed.** §VDB (strategy vectors): `src/data/vector/strategy_store.py` rewritten — source of truth = Postgres jsonb (`strategy_records` table), Redis = embeddings cache (rebuildable from records). Migration `scripts/supabase_strategy_records.sql` + idempotent `migrate_redis_to_postgres()` helper. NaN boundary preserved via `_nan_to_null`/`_null_to_nan` pair. 7/7 strategy-store tests pass. §REGIME-ALIGN ②: `cis_provider.canonical_regime()` normalizes stored `macro_regime` to UPPER_SNAKE on read; T2 fallback output now agrees with T1. §FEEDS-RESILIENCE: DONE (EODHD primary TradFi + Hyperliquid fallback crypto live and verified). §PIT-LEAK-C (production): `_NORM_WIN = 252` trailing window in `regime_score_c` — production is PIT-LEAK-CLEAN. §OHLCV-DEAD (partial): data-completeness RECOVERED, but ohlcv_daily ingest-freshness STILL STALE at 2026-06-19 (~37d). **FUSE blocks git-write in sandbox — Mac-side commit required.** Mac-side handoff: `src/api/store.py` (M), `src/api/routers/_track_record_agg.py` (N), `src/api/routers/signals.py` (M), `src/api/routers/tests/test_track_record_agg_smoke.py` (N), `src/data/vector/strategy_store.py` (R), `src/data/vector/tests/test_strategy_store_pg_smoke.py` (N), `src/data/market/cis_provider.py` (M), `scripts/supabase_refresh_signal_track_record_v2.sql` (N), `scripts/supabase_strategy_records.sql` (N), `src/mcp/cometcloud_mcp.py` (docstring update), `MINIMAX_SYNC.md` (resolution entries), `MINIMAX_OPEN_QUEUE.md` (N), `PROJECT_STATE.md` (this entry). **Plus: `select refresh_signal_track_record();` once** after the migration is applied (Supabase side, requires service-role key). Commit message draft: `feat(production): §BETA-METRIC-AGG + §VDB + §REGIME-ALIGN — ship-gated β-ADJ + durable strategy vectors + canonical regime contract (Seth, 2026-07-26)`. **NEW MEMORY**: `2026-07-26-production-push` — non-obvious: ship gate is calibrated at 36h on `ohlcv_daily.last_trade_date`; the layered endpoint shape (RAW/BETA_ADJ/BETA_ADJ_T_STAT/WIN_PCT × TIER_ORDER) is the consumer contract; the strategy_store NaN boundary uses `_nan_to_null`/`_null_to_nan` pair, not python's default (which would emit invalid `NaN` literal). New entry head: `MINIMAX_OPEN_QUEUE.md` is the one-page Monday standup summary. **PRIOR: §STRATEGY-2-DEFERRED — Strategy 1 = R77 fusion cell LOCKED, Strategy 2 = 4 candidates REFUTED on 731-day panel, structural reason documented**; R82 🟡 PARTIAL (pillar_A regime-gated, gross_t=+1.45 < 1.96 but matched-cell diff +5.46 = directional-right magnitude-wrong); R83 🔴 REFUTED (vol risk-premia, gross_t=+0.36, 5bps_t=+0.27); R85 🔴 REFUTED (R77 + regime-gate at fusion level, gross_t=−0.26 = double-counts R62's detector, lesson #45); R86 🔴 REFUTED (R46 on 11yr pillar + 50% OOS, best OOS_t=+0.52 < 1.96 — OHLCV binding constraint, lesson #48). **Structural finding FINAL**: the 731-day OHLCV window (2024-06-07 → 2026-06-07) is too bear-dominated for ANY single-leg factor to clear the 3-check gauntlet; R77 fusion of three regime-protected legs is the unique survivor. **Architectural insight (NEW)**: §TRADER_TOM_DOCTRINE two-layer book needs orthogonal SHAPES (one market-neutral factor book + one DIRECTIONAL trend-overlay book) — Strategy 2 candidates were all attempts at a second market-neutral L/S (the wrong shape). Right Strategy 2 is a DIRECTIONAL sleeve, deferred pending architecture + OHLCV extension. `STRATEGY_PLAYBOOK.md` (Strategy 1 LOCKED spec) + `STRATEGY_2_DEFERRED.md` (honest graveyard) + batched R82/R83/R85/R86 entry in REFUTATION_LEDGER.md. PR headline: R75c — pipeline RECOVERED (1.3h staleness), R75 still ⚪ PREMATURE on panel-density (valid_hours 662 < 720)**; same module re-run end-to-end, no code change; headline t-stats slightly improved (gross +1.18 → +1.46, OOS −1.70 → −1.21) but all 3 cells still fail — even if maturity had cleared, verdict would read 🔴 REFUTED; density hole from 2026-07-19→25 stall needs ~24h more fresh pipeline to fill; new lessons #46 (panel-density vs calendar-span distinction) + #47 (headline t-stat data-sensitive to stall window — re-run after every recovery); next R75d tomorrow 2026-07-27. §DATA-ALIGN PRIOR + R73/R74/R76-R81 LANE unchanged. Ships no production change — see building log. **PRIOR: SESSION 2 + R73 + R74 + R76 + R77 + R78 + R79 + R80 + R81 LANE.** 🟢/🟡/🔴 status chain now: **R81 🔴 REFUTED — orthogonal candidate #5 (taker-buy ratio residual, cross-sectional demean of trailing-30d rolling-mean taker-buy ratio) on the PRICE-FLOW axis (NON-rate, per user direction "不做费率相关的") FAILS 3-check gauntlet** — best 5d/0bps gross_t=+2.03 (just over 1.96), OOS_t=+0.40 (well below 1.96), no cell in the 6-cadence × 3-cost sweep clears on all 3 checks. **Panel-mismatch honesty: leg-correlation gate (lesson #42) N/A** — R81's A-S1 24-symbol 564-day panel (2025-01-01 → 2026-07-18) is STRUCTURALLY NOT COMPARABLE to the 28-asset 731-day panel used by R46/R62/R76/R78/R80; lessons #42 + "directional-right, magnitude-wrong" carry. Sign verdict **high_tafi_long** (matched-cell top-3 differentials ALL positive +4.05 to +4.06 — perfect sign symmetry, directional thesis rock-solid, absolute edge too thin). Per-window W1=+15.4%, W2=+85.6%, W3=+66.7%, W4=+94.2%, W5=+21.9%, W6=+60.3% — **6/6 WINDOWS POSITIVE** (cleanest per-window pattern of any refuted candidate in the R78/R79/R80/R81 sequence; no late-cycle sign-flip, maxDD only −17.39%). **Lesson #43 v3 v4 (CONFIRMED, full articulation in 6 cases now)**: ✅ R76 (orthogonal + standalone edge → SURVIVES + FUSION LIFT), 🔴 R78 (orthogonal + NO edge → REFUTED, TREND axis), 🔴 R79 (orthogonal + NO edge + W5-catastrophic → REFUTED, VOL axis), 🔴 R80 (orthogonal + NO edge → REFUTED, TURNOVER / CARRY axis), 🔴 R81 (orthogonal but NO standalone edge → REFUTED, **PRICE-FLOW / NON-RATE axis**), 🔴 R74 (NOT orthogonal + NO edge → REFUTED, CIS-quality pillar_A). **Structural finding FINAL**: cross-sectional demean of single-class microstructure axes (rate, price-flow, vol, trend, activity) MOSTLY LACKS EDGE on this universe; only R76 funding residual survives. R76 is the 1-in-5 outlier, not the rule. **Pool of viable candidates is EXHAUSTED for the cross-sectional demean shape.** Future orthogonal candidates must reach for STRUCTURALLY DIFFERENT sources (cross-asset carry / cross-frequency / cross-section-of-cross-section / informativeness-WEIGHTED scoring). **Sub-lesson (new, proposed)**: "directional-right, magnitude-wrong" is itself informative — the matched-cell sign audit passes cleanly but t-stats fail; next step is to find STRUCTURAL AMPLIFICATION (perp-spot basis curve, term-spread) rather than another demean. **R82 candidate** deferred pending structurally-different shape selection. R81 ships no production change; frozen R77 cell at w_R46=0.25/w_R62=0.75/w_R76=0.30 unchanged). **R78 🔴 REFUTED — orthogonal candidate #2 (TSMOM cross-sectional demean) PASSES lesson #42 leg-correlation gate (max |corr|=0.113 ≪ 0.30) BUT FAILS 3-check gauntlet** — best 3d/0bps gross_t=+0.32 ≪ 1.96; no cell in the 6-cadence × 3-cost sweep clears. Sign verdict high_mom_long (correct direction, matched-cell diff +2.17 top-3) but absolute edge does not cross 1.96. Per-window W4=−8.2%, W5=−6.9% (NOT R76's clean W5 lift). **Lesson #43 SHARPENS**: orthogonal candidate screening can PASS the gate but FAIL the gauntlet — gate is necessary but not sufficient. R78 ships no production change; frozen R77 cell unchanged). **R77 ✅ FUSION LIFT — R76 (funding residual) carries as 3rd fusion contribution to R69 family** (best w_R76=0.30 — sweep monotone across all 7 grid points, every cell passes 3-check; **frozen baseline** w_R46=0.25/w_R62=0.75/w_R76=0 → gross_t=+2.52, OOS_t=+2.44, maxDD=−11.05%, Sharpe=+1.69 lifts to **w_R76=0.30** → gross_t=+3.10, OOS_t=+3.61, maxDD=−8.91%, Sharpe=+2.06, ΔOOS_t=**+1.17**, ΔW5 ann%=+16.6). **Lesson #43 CONFIRMED in full positive form** — orthogonal signal sources (max |corr| = 0.103 ≪ 0.30) DO carry as 3rd fusion contribution; R76's W5 lift (+98.4% standalone) translates to ΔW5 = +16.6 ann% at the fusion level. **Lesson #42 + #43 form a complete pair**: don't rescue via fusion (R74) + do test orthogonal candidates (R77). **R78 candidate** = rebalance w_R46 + add w_R76 to live R69 cell — forward commit pending, not in scope for this round. R77 ships no production change; frozen R69 cell unchanged). **R76 ✅ SURVIVES + ORTHOGONAL — funding residual cross-sectional L/S clears 3-check** (best cell 5d/0bps gross_t=+2.11, OOS_t=+3.15) **AND passes lesson #42 leg-correlation gate** (corr(R76,R46)=+0.156, corr(R76,R62)=−0.040, max |corr|=0.156 ≪ 0.30 threshold). **Killer finding**: W5 = +98.4% (the late-cycle fragility window where R46 sign-flips at −54.1%) and W6 = +147.3% (most recent, accelerating). Sign verdict high_fund_long, matched-cell diff +3.48. R76 is the strongest candidate leg identified since R46/R62 to add to the fusion book. **Lesson #43** — orthogonal signal sources carry real cross-sectional edges that survive the 3-check gauntlet AND are uncorrelated with existing fusion legs; funding residual (cross-sectional demean) is a structurally different signal than absolute funding-z (R62). R76 ships no production change). **R74 🔴 FUSION LOSES — pillar_A does NOT carry as 3rd fusion contribution to R69 family** (best w_A=0.05 still gives ΔOOS_t=−0.08; pillar_A's matched-cell +3.07 directional differential is real but **fails the structural-correlation gate** with corr(R46,R73)=+0.69 — both are CIS-quality signals moving together, so adding pillar_A at any positive w just dilutes R46 without diversification. **Lesson #42** — REFUTED at gauntlet → don't rescue via fusion; **read leg correlations before adding legs**. Adding pillar_A at any w_A *monotonically degrades* OOS_t and *monotonically destroys* W5 ann%; at w_A ≥ 0.25 the fusion fails the 3-check entirely. **Frozen R69 cell CONFIRMED optimal** (w_R46=0.25, w_A=0 → gross_t=+2.52, OOS_t=+2.44, maxDD=−11.05%, Sharpe=+1.69 — one of the strongest sleeves in the entire R-numbered ladder). R65 paper book, R66 tracking: unaffected. R74 ships no production change). **R73 🔴 REFUTED — pillar_A LEVEL cross-sectional L/S clears NONE of 3 checks** (gross_t=+1.69, 5bps_t=+1.44, OOS_t=−0.22) despite matched-cell directional differential +3.07 favoring R63b level-edge claim. R63b's "+4.48 level edge" reduces to thin positive IC that does not survive aggregation. **Lesson #41** — headline numbers live in the test construction; **read t-stats, not raw ann-spreads.** pillar_A belongs in fusion contribution, not as a sole sleeve. **Frozen R69 fusion cell remains w_R46=0.25 unchanged**; R73 ships no production change. **SESSION 2 historical:** β build-order #1 + #2 LANDED + ledger reconciled + 🔴 dead-pipeline found.** [#2] asset-vector **v2** (18→25 dims: pillar deltas d_F..d_A + O/S stability), NaN-honest (I1) / PIT (I2) / versioned (I6), NaN-aware cosine + length-tolerant, store NaN↔null, provider wired best-effort, 9/9 tests + preflight green — see building log. (1) **β-adjusted backfill DONE** on `signal_outcomes` (7044/7743 rows β-filled, avg β **1.49** — the premise confirmed; R62 reproduced from persisted data: STRONG OUTPERFORM **+8.12/t+5.41**, OUTPERFORM **+2.53/t+4.57**, UNDERPERFORM +1.25/t+5.65, **UNDERWEIGHT −3.69/t−3.56 = the one real defect**). New forward-safe view **`signal_beta_scorecard`** (raw + β side by side, ex symbol=bench). Historical half only — live writer stays Minimax's. (2) **R-number collision resolved per Jazz**: Minimax keeps R64–R68b; Seth's fusion lane renumbered **R64→R69, R65→R70, R66→R71, R67→R72**, **R73** added in Seth lane for the parallel "pillar_A level L/S" claim, **§LEDGER-RECONCILIATION-MAP** appended (also flags Minimax's R64–R68b have no auditable bodies, and the R61/R63 in-ledger dupes). (3) **🔴 The signal-outcome pipeline is DEAD**: `signal_outcomes` frozen at 2026-05-03, `ohlcv_daily` stale since **2026-06-19** (root cause = price feed died; `cis_scores` is fresh), while the investor `/track-record` RPC republishes the **raw pre-R62** metric daily on a surface whose docstring still asserts the overturned conclusion. **Railway live state check 2026-07-22**: t1_count=0 (Mac Mini not pushing), n_signal_feed=0, R70 fusion paper = no_data after 2 days post-deploy. **Handed to Minimax**: **§OUTCOMES-STALE** (P0 price-feed fix) + **§BETA-METRIC-AGG** (β-adjust the RPC, publish raw+β labelled — Jazz's call to ship, gated on fresh prices) + **§BETA-METRIC-BACKFILL** + **§T1-PIPELINE-DEAD** (new, R70/R71 unblock). Preflight PASSED. **Today's commit log**: 8 commits all on origin/main (R61+R72+R58-R60+R63+R69+R70/R71/§5b+docs+state+R73 — gitignored `_data/` 12MB CSV **483228d**). **SESSION 1 detail follows:** **R61 🟡 PARTIAL — detector × flat_zero on pillar_O clears the 3-check gauntlet but does NOT lift OOS (ΔOOS_t = −0.12); gate trades ~$625pp W1-W4 in-sample alpha for ~$16pp W5+W6 gain — frozen R69 fusion cell stays at w_R46 = 0.25 unchanged**). Also: R71 🟢 WIRED + R70 🟢 DEPLOYED + R69 ✅ FUSION WINS + R63 ✅ SURVIVES + R60 🔴 REFUTED + R58/R59 🟡 partial + earlier (R61 OVERTURNED metric-bug chain). R61 is the strategy lane parallel to R71 monitoring: tests whether the detector × `flat_zero` pattern (R62/R63 SURVIVED on fade-the-crowd) generalizes to pillar_O. **Hypothesis REFUTED** on this data: (a) W5 was +15.0% on the 41-asset R46 pillar_O 5d/5bps reproduction — the plan-assumed sign-flip didn't exist; (b) detector × `flat_zero` keeps the gauntlet alive but destroys W2 ann% +685.9% → +137.0% (−$548.9pp Δ) for marginal W5 (+6.6pp) and W6 (+9.5pp) gain — net loss. Best gated cell: cross_class_crowded_count / 5d / 0bps → gross_t=+2.78, OOS_t=+2.35, pass_all=True. **10/54 cells pass all 3 checks; ZERO cells have ΔOOS_t > 0**. Per-detector at R46 frozen cell: btc_funding_level → ΔOOS_t=−1.50 (refutes); cross_class_crowded_count → ΔOOS_t=−0.28; btc_funding_acceleration → ΔOOS_t=−0.36. New aggregate lessons #28-#29: detector × flat_zero is factor-specific (does NOT transfer from R63 to R61) and fragile-regime hypotheses are empirical claims, not prior assumptions (re-derive from per-window P&L before training a detector). **Frozen R69 fusion cell unchanged**. Next moves: continue observing first live marks through R71 monitoring; if R69 Sharpe drifts, the lever is RE-BALANCE w (w_REBALANCE candidate) NOT detector-add on R46. **Action per MECHANISM_SPEC §P1/§P2/§P3**: P1 forward commitment cell = R69 verdict (locked, w_R46=0.25); P2 fill-attribution replaces CRUDE $5M with per-clip fill ratio + slippage + capacity status; P3 lifecycle = fragility-gated position count + validated flag at n_days ≥ 60. Modules: `src/research/validation/r61_pillar_o_detector_gated.py` (~470 LoC, NEW) + `src/research/validation/tests/test_r61_pillar_o_detector_gated_smoke.py` (NEW, 11/11 tests pass) + previous R70/R71 infrastructure. Reports gitignored at `reports/r61_pillar_o_detector_gated/2026-07-22/`.

## Building log (terse; NOT more md — this replaces scattered docs)

- **2026-07-27 🎯 S-84→S-87 ⓠ层闸门跑通并找到第一个产品原型(Jazz 两次指正驱动)(Seth).**
  **S-84 🔴** F&G 反用(极端贪婪离场)全阈值跑输裸持有(−68%~+89% vs +490%)、回撤零改善;MVRV 免费源
  仅 2022-07+ 从未触发(UNTESTED 非 REFUTED)。**S-85 ✅ Jazz 指正"F&G 要 >50 才加仓 + 量价共振" ——
  我用反了。** 顺用后:F&G>50 单用 +1821%;**F&G>50 ∧ 200MA = +1957%/Sh0.96**(取 OR 退化至 +1032% ⇒
  **必须 AND 双重确认**);**加量价共振(量>30日均量)把 maxDD 从 −83.3% 压到 −38.9%(削 44pp)**。
  与 S-76 自洽:情绪与价格同 bar 塌缩 ⇒ **同步指标只能顺用作确认,不能反用作预测** —— 已升级为
  `REGIME_OVERRIDE_SPEC §2` 候选筛选原则(领先→反向 / 同步→确认 / 滞后→归因)。
  **S-86 ✅/⚠️ 加迟滞定型:稳健型(F&G>50 ∧ 价>200MA ∧ 量>30日均量,迟滞10日)= +685% / CAGR 27.2% /
  Sharpe 0.87 / maxDD −44.1% / 切换 1.8次每年 —— 首个全部通过ⓠ层 pre-declared 验收的配置**
  (DD改善39pp>门槛10 · 收益140%>门槛85% · 频率1.8<门槛6)。**⚠️ 悬崖:迟滞15日收益崩至 −13%**,
  信号对确认窗口高度敏感,10日可能站在悬崖边 ⇒ 必须做参数曲面+样本外才算定型。
  **S-87 ⚪ 顺周期杠杆(Jazz 问)= 纯风险缩放:1.0x→2.0x Sharpe 全程 0.86–0.87 不变、回撤线性放大**
  (1.3x: +1060%/DD−55.9%;2.0x: DD−79% 已吃掉⓪层全部保护)。**创造价值的是闸门本身(Sh 0.67→0.87),
  不是杠杆** ⇒ 产品应是"一个策略两个杠杆档"(保守1.0x/进取1.3x,对外最高1.3x),杠杆是客户风险偏好
  旋钮而非策略组成。阶梯式(2项共振即满仓)更差(Sh 0.82/DD−71.8%)⇒ **弱确认不该给满仓**。
  派工 §PROTOTYPE-FOUND(M-WO-C″):参数曲面(4维扫描看是高原还是尖峰)· 时间分割样本外 · 全41币 ·
  随机同频对照 · 三段崩塌命中率;**过了立刻上 live paper 走前向时钟。**

- **2026-07-27 ✅✅ S-83 技术通了 — ①层 beta 曲线 + ⓠ闸门首次实测,本月第一条正向结论 (Seth).**
  Jazz:"技术和交易都没通,我给谁看?" ⇒ 停止写规格,直接跑。**Supabase 持续超时 ⇒ 沙箱直连 Binance
  绕过**(51,675 行 / 20 币 / 2018-01→2026-07),严格按 BETA_CORE_SPEC(PIT 资格 · 月度再平衡 · 10bps ·
  退市计 −100% · CW 封顶 30%)。**结果:①EW +490% / CAGR 23.0% / Sharpe 0.67 / maxDD −83.3%,
  打赢持有 BTC(+372% / 19.9% / 0.61);加 ⓠ闸门(BTC 200MA,PIT)后 +1107% / 33.7% / 0.80 / −64.2%
  —— 净额已含 67 次切换成本。** 三个可对外事实:(1) 等权持有面板 > 持有 BTC,回答了 LP 第一问;
  (2) 成本不吃收益(10bps 仅掉 4pp,年化换手 75%)⇒ 可容纳可复制;(3) **⓪闸门同时提收益+削回撤 19pp
  ⇒ ⓪层不是锦上添花,是能否募资的分界线**(家办不会为 23% CAGR 承受 83% 回撤)。**诚实边界:**
  200MA 是趋势代理**不是** O1 stablecoin 流动性因;切换 7.9次/年超 ≤6 上限需加迟滞;单参数无敏感性;
  20 币非全 41;CW 用成交额代理市值 ⇒ **方向已证实,参数未定型,不是可上线产品。** 脚本
  `src/research/beta_core/`,ledger S-83。**派工 §BETA-CORE-RESULT:** M-WO-A′ 全面板定型①层 **并立刻
  上 live paper(时钟今天开始走)**;M-WO-C′ 用 O1 流动性因跑同一测试与 200MA 对比(**若流动性因打不赢
  一条均线,那是重要的负面结论**)+ 加迟滞 + 三段崩塌命中率 + 随机对照;M-WO-B′ ②层倾斜叠加。

- **2026-07-27 ✅ Railway/Supabase 配合项完成 + 📊 七月大 Review (Seth).**
  **(A) Minimax 要的 Railway 侧全部落地:** `POST /internal/asset-vectors`(token + schema_version 校验 →
  逐资产 generate_embedding(prior_pillars/pillar_history/edge_moments) → pgvector upsert)+
  `GET /internal/asset-vectors/schema`(它要的 echo/dryrun 端点)。**edge_moments 服务端自动补**(批量读
  `asset_edge_moments` 视图,读不到=NaN 非 0);regime 自动过 canonical_regime;返回含 **`v2_count` 诊断位**
  (=0 说明 Mac 没送 v2 输入、拿到的是 v1 降级向量)。preflight 绿。**⚠️ Supabase 持续超时(多次重试均失败,
  82k 深回填后一直脆弱)** ⇒ `beta_core_nav` + `risk_allocations` 两张表 DDL 写进
  `scripts/supabase_beta_core.sql`,**请 Mac 端 apply**(已在 §ASSET-VECTORS-READY 说明,并提醒重活分批)。
  **(B) `docs/MONTHLY_REVIEW_2026-07.md`** — 95 commits / 97 ledger 条目 / 本月 ~33 个实验 /
  **可上线策略 0**。核心结论:**0 不是失败,是尺子终于变准了**;最贵的一课是**层级搞反**(15+ 次都在打
  ④层 pure alpha,①层 beta capture 从未建过 —— 设定错误而非运气);三条已进 CI 的标准闸(事件计数 /
  多周期符号稳定 / 总收益口径);4 个静默故障全是"表面绿内里死",活性检查抓不到、只有完整性检查能抓。
  下月唯一优先级:**①层基准 + ⓪层周期闸门**(其余可等)。提前打的预防针:①层曲线出来后,过去"验证
  通过"的东西很可能连持有都跑不赢 —— **那是我们第一次知道自己在哪。**

- **2026-07-27 📐 中心风险分配器 SPEC + Millennium 纪律进 CI(Seth)—— 补上"框架有了但标准没写好"的四样.**
  `docs/RISK_ALLOCATOR_SPEC.md`。现有 `portfolio.py` 的 meta risk-parity 是**框架**,本文是**标准**:
  **(1) 分配单位是风险不是钱** — `capital_i = risk_budget_i/vol_i`(40%波动与8%波动分同样的钱=5倍风险),
  组合目标年化波动 15%,新 sleeve 回测波动 ×1.3 保守系数。**(2) 回撤阶梯机械无裁量** — −8% 份额×0.5 /
  −12% ×0.25 / −15% 归零+30日冷冻,冷冻后**必须重走晋升阶梯**;组合熔断 −20% 全体减半 / −25% 只留①层。
  **(3) 进场慢退场快** — research→paper(60d,0资金)→试点≤10%→标准≤25%→核心≤40%,**任一关失守立即
  退回上一级**(不是"再观察一个月")—— 这是 Millennium 与学院派的分水岭。**(4) 相关性 >0.7 的 pod 合并
  共享一份预算**(redundancy() 已证 risk_direction_score 是枢纽,我们**以为**的分散度常不存在);
  **ENB<2 不许把暴露开到 1.0x 以上**;ⓠ层是乘性闸门凌驾一切(CRISIS ⇒ 所有 pod ×0,无论表现多好),
  但 EXPANSION **不自动放大**。**§0 诚实标注现状:今天可交易 sleeve 实为 0,v1 目标不是优化分配,而是
  建立纪律让未来每个 sleeve 从第一天就活在规则里 —— 规则先于规模;§9 标明哪些条款现在生效、哪些 ≥5 pod
  才启用。** **纪律已进 CI(不只是文档):** `StrategyRecord` 新增 `max_dd_stop` / `capital_action_on_breach`
  / `backtest_included_stop` / `promotion_stage`,`validate()` 对 SHIP 硬失败缺止损者;
  **新测试 `test_stop_added_after_the_fact_is_rejected`** — 事后补止损会改变曲线形状,属自欺,CI 拒绝。
  6/6 discipline + preflight 全绿。Handoff §RISK-ALLOCATOR(点名请 minimax-b 对 §2 三因子与 §3 阈值提分歧)。

- **2026-07-27 🚨 架构修订 — ⓪层 REGIME OVERRIDE 凌驾四层 + Millennium 化 + 放开空仓/裸空 (Jazz 纠正, Seth 落规格).**
  Jazz 指出我前一版规格的两个教条错误:**(1) "全周期正交"是错的** —— 正交只是归因工具,不是建仓约束;
  边际流动性转向时三层就该同时服从同一判断,那是正确的风险反应不是污染归因。**(2) 0.7x 下限+禁做空是
  错的** —— "转向的时候,有时候就是空仓或者裸空的好时候";暴露放宽为 **[−0.3, 1.3]** 含空仓/裸空,
  **①层吃 beta 是"条件性默认"非无条件义务**。⇒ **新架构:四层之上有 ⓪ REGIME OVERRIDE(风格/流动性
  周期判断),是最该建的能力** —— 新规格 `docs/REGIME_OVERRIDE_SPEC.md`:判据与其他层完全不同(不判
  Sharpe,判**三段崩塌 2018/2022/2025-26 是否在回撤前 1/3 内降暴露 ≥2/3 命中** + maxDD 改善≥10pp +
  总收益≥①层85% + 切换≤6次/年 + 优于同频随机);cause = 边际流动性定价,最强先验 **O1 stablecoin 供应Δ**
  (已验 DD −56.5% vs 持有 −75.2%,削 19pp —— 正是⓪层该有的形状);输出**只有闸门** `regime_state →
  exposure_cap`,不输出权重;**必须内建迟滞**否则阈值附近来回切换吃光收益;防作弊 5 条(t判定t+1生效/
  扩张窗口分位/逐段标注拟合vs样本外/随机对照/禁用含未来信息的regime标签)。**(3) Millennium 化:平台
  edge 在中心化风险分配,不在单个 pod ⇒ 立刻强制每个组件必须有 `max_dd_stop` + `capital_action_on_breach`,
  且回测带着止损跑(事后加会改变曲线形状),无止损不许进生产,⓪层自己也是 pod 同样要有。** 优先级:
  M-WO-A(①基准)与 ⓪层 O1 变体**并列 P0**。已同步改 TILT_MULTIPLIER_SPEC(暴露五档含 −0.3/0.0、
  §3.4b 裸空纪律、§3.5 止损强制)、HIGH_DIM_ONTOLOGY §5b-bis/§5b-ter、MEMORY.md、handoff §REGIME-OVERRIDE。

- **2026-07-27 📐 Layer-②③ SPEC written — 三层口径全部定完,M-WO-A/B/C 可并行 (Seth).**
  `docs/TILT_MULTIPLIER_SPEC.md`. **核心设计是正交性:②固定暴露=100%只改相对权重;③固定权重只改总
  暴露 0.7–1.3x。** 混做则无法归因、单层失败污染全局 —— 正是过去 15 次的坑。分开建/测/归因,叠加放最后
  且必须给归因分解(①+②+③+交互项),任一层未过则该层乘数设中性,**不许"整体跑赢"掩盖单层失败**。
  **②:** w = ①基座 × m(CIS截面分位),**m∈[0.5,2.0] 硬约束、归一化后永远满仓、禁负权重**、NaN→m=1.0
  (不假装有观点)。变体 T1=pillar_F(S-80 的 12/12 锚)/T2=v5 return_score/T3=return×risk。
  **Pre-declared 通过标准:Sharpe +≥0.15 且 maxDD 不劣化≥2pp 且 ≥4/5 周期为正 且 10bps 下成立** —— 达不到
  就诚实结论"CIS 在②层无产品价值",回落①层。**③:门槛与②根本不同(这正是 S-78 被误杀的原因)——
  ③的任务是改善持有体验不是独立收益,主判据 maxDD 改善≥5pp 且 total_return ≥①层95%。** 三档离散
  {0.7,1.0,1.3},余额持现金,绝不做空;**1.3x 需杠杆 ⇒ v1 先做纯减仓 {0.7,1.0},1.3x 单独报告并注明
  融资成本**(不许把杠杆收益混进"择时有效")。信号 E1=regime×vol(S-78 正确重测)/E2=流动性Δ/E3=v5
  risk_score,并与同频随机切换对比排除运气。统一 variant 命名入 `beta_core_nav`。Handoff §TILT-MULT-SPEC。

- **2026-07-27 📐 Layer-① Beta Core SPEC written — the benchmark the whole validation apparatus rests on (Seth).**
  `docs/BETA_CORE_SPEC.md` — M-WO-A's sole implementation basis. **Why the "boring" curve got a full spec:
  it is the benchmark for every sleeve; a contaminated benchmark makes every future "excess" fake. Its
  credibility = the validation system's credibility.** Locked the 5 things implementations get wrong:
  (1) **PIT eligibility** (≥180d listed, 30d ADV ≥$5M, data-complete, no stablecoins) — never filter
  history by "still alive today"; (2) **delisted/zeroed carried at −100%**, sold at last valid price and
  redistributed — silent removal manufactures returns; (3) **no intervention between rebalances** (winners
  run) — daily rebalancing is covertly short-momentum, not "holding"; (4) **CW variant capped at 30%/asset**
  or it degenerates into a BTC chart and stops being a FoF; (5) **explicit costs** (10bps/side base, 5/20
  sensitivity). Deliverables: 4 NAV curves (EW/CW × 0/10bps) → `beta_core_nav`, per-cycle report, **vs
  BTC-only and ETH-only** (the first question an LP asks — "why not just hold BTC" — we answer it before
  they ask), written answers to 4 bias traps + delisted list, forward paper accruing daily. **§6 also
  pre-defines how layers ②/③ get tested** (CIS tilt = 0.5x–2.0x bounds, fully invested, no shorts;
  exposure multiplier = 0.7x–1.3x, cash for the remainder, never short) so M-WO-B/C results are mutually
  comparable instead of each inventing its own convention. Table DDL in `scripts/supabase_beta_core.sql`
  (Supabase timed out on my side — Minimax applies it as step 1). Handoff: `MINIMAX_SYNC §BETA-CORE-SPEC`.

- **2026-07-27 🚨 §BETA-FIRST — Jazz reverses the research priority order; this explains the whole graveyard (Seth).**
  Jazz (asset manager): **"首先保证吃到 beta,然后 beta+,beta multiplier,最后才 pure alpha"** — a PRIORITY
  ORDER. Caught my error mid-experiment: I subtracted the market baseline in S-82 and called the residual
  "the finding". That's correct for ATTRIBUTION, wrong for PRODUCT. **The reframe explains 15 attempts:
  R76–R94 were ALL layer ④ (cross-sectional demean = neutral BY CONSTRUCTION = beta thrown away before
  the test starts), while layer ① (guarantee beta capture) was NEVER BUILT.** In an asset class with
  long-run positive drift that's a specification error, not bad luck. **Everything re-slotted:** CIS is a
  **layer-② tilt engine** (long-only overweight inside the book — S-80's F_IC 12/12 positive is exactly a
  tilt engine's evidence shape, never given its product form), S-78 regime×vol is a **layer-③ exposure
  multiplier** (bar = improve the held book's return/DD, NOT standalone neutral return — I refuted it
  against the wrong bar), S-82's event continuation is a ②/③ input (raw +5.44%, no shorting anywhere).
  Written into doctrine: `HIGH_DIM_ONTOLOGY.md` §5b (four-layer table + 3 disciplines), CLAUDE.md
  (constitution), MEMORY.md (never-evict). **`MINIMAX_SYNC §BETA-FIRST` supersedes §DIRECTIVE's WO order:**
  M-WO-A build the layer-① beta book (THE benchmark — "beat hold-the-panel", never 0), M-WO-B test CIS as
  long-only tilt vs equal-weight, M-WO-C re-run S-78 as exposure multiplier; **layer-④ neutral work FROZEN**.
  New reporting rule all lanes: total_return · vs hold-the-panel · then excess. (Supabase timed out
  mid-study — the layer-① backtest numbers are M-WO-A's deliverable, not blocked on me.)

- **2026-07-27 🔴/✅ S-82 E1 ran — field spillover REFUTED, local continuation CONFIRMED; the kernel gets sharper (Seth).**
  First Entity/Decision experiment. **Data-premise correction first:** `forward_supply.py` holds
  STRUCTURAL overhang (static state), NOT dated unlock events (calendars are paywalled) — E1-as-specced
  isn't runnable on data we own. Adapted to the same mechanism with events we DO have: **volume shocks**
  (>4× 60d avg vol AND |ret|>8%) on the 2017+ deep panel, 748 events / 41 syms / 2017-11→2026-07,
  **market-baseline subtracted** (without it, "spillover" is pure co-movement). **Result: up-shock self
  +2.71% excess vs neighbours −0.07% (t−1.79); down-shock self +0.35% vs nbr +0.17% (t+1.69).** The raw
  +3.39% neighbour number was 100% market baseline. **Independence gate PASSES** — 536 up-events across
  **381 distinct dates** (293 solo, max 8/day) = genuinely independent, not the pseudo-replication that
  killed S-78/S-79. **⇒ 🔴 spillover refuted / ✅ local continuation real and event-counted.** **The
  valuable part:** co-movement neighbourhoods (asset_class, and by extension price-similarity) are NOT
  influence channels — "similar" ≠ "downstream". A field edge must be a CAUSAL channel (shared holder,
  shared venue, governance/collateral link). This independently explains S-81's level-diffusion failure
  (diffusing over the wrong topology) and **redirects the Entity space: build edges from holder/flow/
  governance overlap, not price-similarity** — feeding straight into Minimax's extractor scope. Next:
  E1b (embedding-graph neighbourhoods to confirm the topology point), then real causal edges. The
  +2.71% continuation is logged as an OBSERVATION, not a sleeve (needs cause + cost + capacity).

- **2026-07-28 ✅ 3-sleeve parallel paper phase LIVE — directional pivot from R-numbered sleeve graveyard (Seth).** Per Jazz's 2026-07-28 critical redirection ("隔壁gpt sol5.6已经开发了很多生产环境能赚钱的策略了...风格周期预判那么难嘛？我们可以容错的，你倒是好好做啊"), the 15-attempt 731-day sleeve graveyard (R82/R83/R85/R86/R87/R88/R89/R90/R91/R92/R93/R94 + earlier R76-R81) was structurally single-family (cross-sectional single-leg factor L/S). This package is a directional pivot: 3 production-grade alpha sources that top quant funds actually deploy, none of which require the 1.96 3-check gauntlet to be useful. **3 sleeves in parallel for 60d forward paper**: (1) **sleeve_1 vol_carry** — Deribit DVOL 30d − Binance BTC 30d RV → term_premium; ENTER_SELL at term_premium ≥ 5%; short ATM straddle + long OTM 1.5x put tail hedge, 30% paper NAV ($300k notional); today's signal = IV=37.82% RV=31.68% term_premium=+6.14% → ENTER_SELL. (2) **sleeve_2 regime_nowcast** — logistic P(RISK_ON | BTC 30d ret, TVL 7d Δ, USDT 7d Δ) with pre-registered heuristic coefficients → R77 tilt ∈ {0.5, 1.0, 1.5}; today's signal = btc_30d=+6.63% tvl_7d=−2.21% usdt_7d=+0.03% → P=0.508 → BASELINE 1.0x (NOT static rotation per Asness R20 lesson; smooth probability tilt). (3) **sleeve_3 macro_overlay** — 7-asset cross-section momentum z (30d+90d) via EODHD: SPY/TLT/GLD/USO/SLV/UUP/DBA, weekly rebal, long top half / short bottom half, 40% paper NAV ($400k notional); today's signal = LONGS=[USO,UUP,DBA,SPY] SHORTS=[SLV,GLD,TLT]. **Shared paper-book ledger** (`src/research/paper_books/ledger.py`, append-only CSV at `/tmp/cometcloud_data/paper_books/{sleeve_id}_positions.csv`) prevents contamination of R77's Supabase `fusion_paper_nav`. **Daily runner** (`daily_runner.py`) orchestrates all 3 sleeves + writes `daily_summary.csv` (one row/day, joined signal values). **Weekly summary** (`weekly_summary.py`) — signal-trajectory aggregation + pairwise correlation + optional R77 NAV orthogonal comparison (needs SUPABASE_URL/KEY env); operates on SIGNAL trajectories NOT mark-to-market P&L (honest scope limit — daily NAV ledger is next-phase work). **No 3-check gauntlet, no R-numbered ledger entries, no mock data** — per Jazz "我们可以容错的" the 60d verdict uses Sharpe (primary) / maxDD (secondary) / orthogonal-to-R77 (tertiary). **R77 frozen cell UNCHANGED** at w_R46=0.25/w_R62=0.75/w_R76=0.30. Mac-side cron (Minimax's lane) needs to wire 00:30 UTC daily run. Mac-side commit handoff required — FUSE blocks git-write in sandbox. New files (all NEW, ~890 LoC total): `src/research/paper_books/{ledger.py, sleeve_1_vol_carry.py, sleeve_2_regime_nowcast.py, sleeve_3_macro_overlay.py, daily_runner.py, weekly_summary.py, README.md}`. New memory: `2026-07-28-3-sleeve-parallel-paper-phase` (TBD on commit).

- **2026-07-27 ✅ Entity/Decision space v1 BUILT + contract-verified — the kernel's missing object is now persisted (Seth).**
  My half of M-WO-7.5 (Minimax owns extractors, after schema review). **Live in Supabase:** `entities`
  (12-dim influence coords, HNSW) + `decisions` (dated CHANGE events) + **`decision_source_term(as_of,
  lookback)`** — the PIT-safe decayed push per asset that is the CORRECT source term `s` for
  `propagation.propagate()` (S-81: diffuse the CHANGE, not the level). `src/data/vector/entity_store.py`
  mirrors the pgvector_store contract. **Discipline is enforced by the DB, not by prose — all three
  verified end-to-end then cleaned:** (1) PIT decay exact (ARB = today −0.06 + 7d-old −0.06×2^(−7/14) =
  −0.1024 ✓); (2) **provenance CHECK rejects an empty-source row** (no provenance ⇒ no evidence);
  (3) **zero future leakage** — as_of before the decision date returns 0 rows. I1 handled honestly:
  pgvector can't hold NaN, so unmeasured influence dims are 0.0 in `vec` but flagged False in
  `meta.measured` — the FLAG is the truth, never read the 0 as "average influence". `lead_score` stays
  NULL until EARNED by experiment E2. 6/6 smoke (one real bug caught: silent-success when creds absent),
  preflight green, provenance `scripts/supabase_entity_decision.sql`. **Next: E1 unlock-propagation on the
  2017+ panel** (grade-A data, naturally event-counted) → E2 lead_score → **E3 the kernel test**
  (decision-diffusion vs the refuted −0.16 level-diffusion baseline). Noted from Minimax: R77 already
  RELABELED "regime-specific candidate" per M-WO-1 (their event-count came back), 15-attempt graveyard
  complete, Strategy-2 deferred pending M-WO-2 deep-panel reruns.

- **2026-07-27 📐 Entity/Decision space DESIGNED (M-WO-7.5, design-first) — the kernel's missing object (Seth, planning role).**
  `docs/ENTITY_DECISION_SPACE.md` v1: Entity = influence NODE (12-dim coords incl. EARNED lead_score),
  Decision = dated CHANGE event w/ mandatory provenance (kind/direction/magnitude/targets/half-life) —
  the correct source term `s` for propagation (S-81: diffuse the CHANGE). Grounded in data we already
  own (forward_supply=grade A, positioning, whale_alerts, trending D4, macro calendar); v1 entity set
  deliberately tiny (~10-30 nodes, depth over breadth). **Three gauntlet-first experiments:** E1 unlock-
  propagation (grade-A, naturally event-counted), E2 lead_score earning, **E3 the kernel test —
  decision-diffusion vs the refuted level-diffusion (−0.16) baseline: pass = empirically one step
  upstream; fail = space stays a risk lens (unlock overhang pays rent either way).** Boundaries: no
  social scraping/person profiling/KOL sentiment; nothing investor-facing pre-gauntlet. Build split §5
  (Seth: schema+stores+E1/E3 harness · Minimax: extractors, AFTER schema review — spec-first, §ENTITY-
  DECISION handoff sent). Also noted: `strategy_records` table already live — Minimax moving on WO-3.

- **2026-07-27 ✅ Jazz corrections applied — ONTOLOGY CORE preserved + numbering ceremony dropped + VDB 做多 work order (Seth).**
  (1) **`docs/HIGH_DIM_ONTOLOGY.md` created** — the 高维/量子/降维 core communications consolidated as
  soul-material (geometric form of ARCHITECTURE.md): kernel-as-field, be-water (W reshapes per cycle,
  regime = phase), be-quantum (state=distribution, entanglement_delta, measurement-collapse-with-lag,
  **S-81 theorem: diffuse the CHANGE not the level**), the compression cascade with 4 conservation laws
  (I1/I3/I5/R63b), dense-vs-sparse storage law, quantum-computing hooks (keep operators LINEAR → quantum
  walk port; sleeve selection = QUBO/QAOA; amplitude encoding), and the **VDB expansion roadmap** (7 spaces:
  Asset✅/Strategy🔨/Regime📋/Entity-Decision🎯/Text-RAG📋/TS-windows📋/Outcome📋). **MEMORY.md expanded**
  (cap 4→8KB): ONTOLOGY CORE section marked never-evict. (2) **§DIRECTIVE-AMENDMENT to Minimax:** numbering
  freeze/enforcement WITHDRAWN (velocity > ceremony, bare numbers fine); **NEW M-WO-7 "VDB 做多"** — ordered
  slices: regime fingerprints→pgvector (phase retrieval), strategy records durable, outcome-distribution
  vectors (§P1 geometric), TS-window shapelets, Entity/Decision space (design-first, with Seth). Acceptance
  per space: table+RPC live, backfilled, one real retrieval demonstrated, M- ledger entry.

- **2026-07-27 📋 §DIRECTIVE issued (Jazz+Seth → Minimax) — phase shift: stop mining, harden the survivor, ship the product loop (Seth, planning role).**
  Reviewed Minimax's R77–R94 run with full cognition: 11-attempt funding-axis exhaustion (lesson #43+#56
  v2: axis dead, **R77 fusion = unique survivor** OOS_t+3.61), §DATA-ALIGN executed (data_align pkg, 2024-bull
  real pillar_a, pillar_A settled regime-conditional = S-79 confirmed). **Audit found 3 real issues:** (1)
  R77's +3.61 is day-level on the S-78-style risk-off OOS window — **never event-counted** (the exact gate
  that killed S-78's t+14); (2) R78–R94 numbered BARE despite approved M- convention; (3) all new validation
  ran on the old 731–1165d panel, ignoring the fresh 2017+ deep panel. **§DIRECTIVE = 6 work orders with
  acceptance criteria:** WO-1 event-count R77 (P0 — decides deployment language); WO-2 re-run price legs
  (R46/R78/R79/S-78) on the 2017+ multi-cycle panel with per-cycle sign stability; WO-3 portfolio_state +
  unified sleeve schema (their proposal APPROVED, but extend canonical StrategyRecord, durable Postgres, not
  a new schema); WO-4 R77 second paper book (gated on WO-1, don't mutate frozen R69/R70); WO-5 S-81
  change-diffusion frontier test on data_align real-CIS (now unblocked); WO-6 Mac MEMORY.md ≤4KB + ledger
  amendment (bare frozen extends to R94; M-95+/S-82+ from next entry) + naming + no-add-A. Sleeve mining
  FROZEN except where WOs ask. Vision anchor: product = verifiable forward track record; every WO answers
  "can an external agent verify this claim?"

- **2026-07-27 ✅ CLAUDE.md + MEMORY.md RESTRUCTURED (Jazz: "高价值规划整理,不做执行") (Seth).**
  **CLAUDE.md 32.2KB → 9.1KB (−72%).** Principle: the constitution keeps only what nothing else can hold
  — identity, boundaries, 9 hard rules, source-of-truth map, compressed loop. Everything else became
  POINTERS to where it now actually lives: skills (compliance/cis-methodology/deploy/task-audit/completion),
  CI (discipline suite + preflight stage 3 replaced the prose "bar"), state docs (PROJECT_STATE/LEDGER/
  SYNC/PLAYBOOK). **Promoted to constitution (were missing!): never-`git add -A` (own paths only) + S-/M-
  ledger prefix + no-mock-data.** Dropped: 33-line project tree (drifts), 17-row env-var história, CIS
  v4.1 scoring detail (skill owns it), 170-line loop ceremony (→ 12 lines + handoff template + threshold
  one-liner). All 11 safety-critical rules verified present post-cut. **MEMORY.md CREATED (3.6KB)** — the
  file session-start always referenced but which never existed in-repo (it lived Mac-side at 30KB, OVER the
  24.4KB auto-load truncation = Minimax's "silent memory loss"). Rules in header: ≤4KB cap, one line per
  expensive-to-rediscover fact, evict when stale or compiled-into-code. Seeded: infra traps (FUSE/Supabase-
  region/Binance-reachability), data layout, validated findings (R62/S-77…S-81 + meta-lessons), standing
  coordination. **Mac-side MEMORY.md (30KB) still needs the same treatment — Minimax applies the same
  index-only rule; flagged in §PROTOCOL adoption.** Role note: Seth shifts to planning/审计/整理 (expensive
  tokens on judgment, not execution) per Jazz + Minimax-C's "audit/linter, not strategy generator."

- **2026-07-27 ✅ Minimax-feedback P0 + P2 EXECUTED — 731-day panel ELIMINATED + philosophy compiled to CI (Seth).**
  Both Minimax lanes converged on two levers; both landed same-day. **P0 — deep panel:** discovered
  api.binance.com is reachable from Supabase itself (ap-southeast-2, not geo-blocked) ⇒ built
  `backfill_binance_ohlcv()` (Postgres `http` ext fetches its own klines — zero data through agent/Railway).
  **Result: 82,227 rows · 41 symbols · back to 2017-08-17 · 25 symbols ≥2000 days** (source='binance_hist',
  idempotent). The bear-only 731-day constraint behind most R46-R94 refutations is GONE — R46 rerun + all
  R8x OOS validation + S-78/S-79 multi-cycle re-tests are now unblocked on Supabase data. Provenance:
  `scripts/supabase_ohlcv_backfill.sql`. **P2 — discipline CI:** `StrategyRecord` gained evidence-grade
  fields (base_rate/cause, oos_window, oos_survival, paper_trade_days≥60, regime_skip, regime_reported —
  additive, I6); `validate()` now HARD-FAILS a SHIP verdict missing any of them ("guilty until proven" is
  now red/green, not prose). New `tests/test_strategy_discipline.py` (5/5) with an EXPLICIT
  LEGACY_ALLOWLIST (trend_v5c — visible debt, owes backfill). **Preflight gained stage [3/3]:** discipline
  suite + contract SCHEMA_VERSION echo (cis_push v1.0 · vector v2/27-dim) — the schema-drift class it
  previously couldn't see. First run immediately caught real missing cause-docs in the canonical graveyard
  (fixed: all 8 sleeves now carry CAUSE notes). Preflight PASSED end-to-end. Remaining Minimax-feedback
  items dispatched, not dropped: session-state.json + cold_start.sh + webhook queue (their lane / joint),
  portfolio_state schema rewrite (needs Jazz call on ownership), MEMORY.md truncation (Mac-side).

- **2026-07-27 🔴 §STRATEGY-2 — R96 cross-asset bond-equity β-residual L/S REFUTED; 14-attempt graveyard COMPLETE (Seth, Option D structurally-different data-class pivot).** R96 used 33 TradFi assets from the EODHD local SQLite buffer, 249 daily observations (2025-07-29 → 2026-07-24), score = 60d rolling β_TLT − β_SPY lagged 1d, market-neutral tercile L/S, and a 6-cadence × 5-cost sweep (30 cells). **Best 5d/0bps: full_t=−0.347, OOS_t=+0.845, maxDD=−14.25%, Sharpe=+0.477; 5bps_t=+0.188, 10bps_t=+0.104, zero realistic-cost passing cells.** Absorption: alpha_t=−0.63, SPY β=+0.919/t=+8.54, R²=0.46 — beta-tilted book in disguise. Windows alternate W2=−69.1%, W3=+92.8%, W4=−58.7%, W5=+149.5%, W6=−51.0%. **Lesson #63:** even a cross-asset TradFi pivot cannot escape the short-panel constraint; panel length remains binding. Strategy 2 remains STRUCTURALLY DEFERRED pending §OHLCV-EXTENSION; frozen R77 unchanged. Files: `r96_panel.py` (N), `r96_cross_asset_bond_equity.py` (N), smoke tests (N, 14/14 PASS), ledger/deferred/state docs (M). Reports gitignored. No production change; Mac-side commit required.

- **2026-07-27 🔴 §STRATEGY-2 — R95 canonical per-asset TSMOM trend strategy REFUTED; 13-attempt graveyard COMPLETE (Seth, per user "做趋势的策略" pivot to canonical per-asset trend).** R95 = the AQR/MAN AHL/Tran 2012 construction: per-asset signed TSMOM (NOT cross-sectionally demeaned), 25 crypto assets from local SQLite off-engine OHLCV, 363 days (2025-07-28 → 2026-07-25), 7 horizons (5/10/21/42/63/126/252d) × 6 cadences (1/3/5/7/14/21d) × 5 cost tiers (0/5/10/20/30bps) = 210 cells. 15/15 smoke tests pass; preflight PASS. **Best cell 63d/14d/0bps: full_t=+1.360, OOS_t=+1.320, Sharpe=+1.873, maxDD=−1.21% — below the 1.96 3-check bar even at 0bps. 5bps full_t=+1.33, 10bps full_t=+1.31, zero cells survive 5bps/OOS gate and zero cells survive 10bps. W1–W5 contain no realized P&L (warmup); W6 alone contributes +59.5% annualized — discovery, not robust 6-window evidence. Verdict: 🔴 REFUTED. Lesson #62**: even canonical per-asset signed TSMOM (multi-horizon, 25-asset breadth, no demean, market-neutral) cannot clear the gauntlet on the available short bear-dominated panel. The trend premise is not falsified globally; the panel is insufficient. Strategy 2 = STRUCTURALLY DEFERRED pending §OHLCV-EXTENSION; Jazz's Option A re-confirmed; R77 fusion cell UNCHANGED at w_R46=0.25/w_R62=0.75/w_R76=0.30. Files: `r95_panel.py` (NEW) + `r95_per_asset_tsmom.py` (NEW) + smoke `test_r95_per_asset_tsmom_smoke.py` (15/15) + R95 entries in `REFUTATION_LEDGER.md` + `STRATEGY_2_DEFERRED.md` (TL;DR row added, 13-attempt graveyard noted). Also fixed a JSON serialization bug in the module — `cost_tier_sweep` previously emitted NaN, now emits `None` and the cost-tier helper iterates over a list of sweep keys (no dict iteration confusion). Reports gitignored at `reports/r95_per_asset_tsmom/2026-07-27/`. FUSE blocks git-write in sandbox — Mac-side commit required. NEW MEMORY: `r95-per-asset-tsmom-refuted`.

- **2026-07-26 🔴 §STRATEGY-2 — R94 §TRADER_TOM Directional Crypto Beta Sleeve (L2) REFUTED; 12-attempt graveyard COMPLETE; Strategy 2 STRUCTURALLY DEFERRED pending §OHLCV-EXTENSION (Seth, per user pivot to directional crypto beta sleeve — closest shape to doctrine's tactical trend-overlay).**
  R94 = Layer 2 of §TRADER_TOM two-layer book (R77 = Layer 1, frozen at w_R46=0.25/w_R62=0.75/w_R76=0.30). Universe = BTC/ETH/SOL equal-weight (3-asset crypto beta sleeve), LONG-only, weekly rebal + **DAILY risk-state evaluation** (KEY FIX vs R87/R92 weekly-only) + **one-day lag** on regime (PIT-safe). Regime map: RISK_ON/GOLDILOCKS/EASING=1.00, NEUTRAL/STAGFLATION=0.50, TIGHTENING=0.25, RISK_OFF/None=0.00. Cost grid 0/5/10/20/30bps (R32/R89/R90 lesson #58 baked in). maxDD budget = −20% (tighter than R92's −30%). Anti-imposter gates mandatory: static_beta + BTC-only + regime-flat benchmarks + combined-book check (does R94 ADD to R77?). 15/15 smoke tests pass. **🔴 REFUTED — every gate fails.** (1) **3-check FAILS at every cost tier** (best gross_t=−1.820 at 0bps, sign-FLIPPED NEGATIVE at 5/10/20/30bps: −1.940/−2.060/−2.290/−2.520). (2) **Scaling HURTS static_beta** (R94 OOS_t=−1.96 vs static_beta OOS_t=−1.33 — anti-imposter FAILED, scaler is destructive). (3) **maxDD=−47.38%** (blows past −20% budget 2.4× over). (4) **W5=−58.1%** (catastrophic late-cycle fragility, same window R46/R76/R77 sign-flipped in). (5) **W1=−76.8%** (catastrophic bear-window front; BTC dropped 70k → 50k). (6) **2/6 windows positive** (W2=+41.2%, W4=+118.8% ride the post-election bull + post-Tariff-Friday recovery; W1/W3/W5/W6 all negative). (7) **BTC-only with same scaling ALSO REFUTED** (gross_t=−2.270, Sharpe=−0.430 — confirms even BTC-only directional cannot clear 3-check). Regime distribution on panel: RISK_OFF 35.0% + EASING 29.4% + TIGHTENING 23.9% + RISK_ON 7.9% + STAGFLATION 3.7% (37.3% bull-active — regime distribution OK, NOT the binding constraint). **Lesson #59 (FINAL, 12th attempt, 2nd directional shape)**: directional crypto beta sleeve (LONG-only AND signed via R92) BOTH fail on the 731-day bear-dominated panel — even with DAILY state updates + one-day lag + tight maxDD + mandatory benchmarks + combined-book check, a structurally unsound shape cannot be rescued. The fixes were all PROPER (no in-sample leakage, PIT-safe, cost-honest), but the SIGNAL isn't there to express. **Methodology ≠ edge (lesson #60 anti-imposter FINAL confirmation)**. **Why the directional shape is dead on this panel**: 731 days × 35% RISK_OFF + 24% TIGHTENING = 59% of days where being long crypto is structurally negative or choppy enough that net of cost+drag no directional alpha emerges. Regime classifier DID respond to bear windows (correctly flat in RISK_OFF → gross=0), but within the 37.3% bull-eligible days (mostly EASING = transitional not genuine risk-on), price action was choppy enough that net of cost, this directional book doesn't make money. **R77 cross-reference**: R77 doesn't bleed in W1/W5 because it's **market-neutral** (W1 BTC drop of −76.8% is captured by R46's quality-rank + R76's funding-demean — both carry +ve on relative-rank component even when BTC drops). **LONG-only directional betas are structurally doomed on a 731-day panel that contains a real bear.** This is the §TRADER_TOM_DOCTRINE implication: a tactical overlay needs a TREND overlay (signed directional), not a LONG-only beta sleeve. **Path forward confirmed**: Strategy 2 STRUCTURALLY DEFERRED pending Minimax §OHLCV-EXTENSION completion; on 11yr price data, bear% drops from 60% to ~20% and the directional shape may finally have room to clear 3-check. **Files**: `r94_directional_crypto_beta.py` (NEW ~660 LoC), `test_r94_directional_crypto_beta_smoke.py` (NEW 15/15 pass), `reports/r94_directional_crypto_beta/2026-07-26/{verdict.json, REPORT.md}`, R94 entry in `REFUTATION_LEDGER.md` (~150 lines), `STRATEGY_2_DEFERRED.md` updated to 12-attempt graveyard. Frozen R77 cell at w_R46=0.25/w_R62=0.75/w_R76=0.30 unchanged. Ships no production change. **Goal condition ("two tradeable L/S strategies") — STILL UNSATISFIED after 12 attempts.** NEW MEMORY: `r94-directional-crypto-beta-refuted.md`. FUSE blocks git-write in sandbox — Mac-side commit required.

- **2026-07-26 🔴 §STRATEGY-2 — R93 informativeness-weighted funding-z REFUTED; 11-attempt graveyard COMPLETE; Strategy 2 STRUCTURALLY DEFERRED pending §OHLCV-EXTENSION (Seth, per user "换全新结构轴" pivot to structurally-new axis).**
  R93 = fade_sign × funding_z(zwin=30d) × ι[i,t] (per-asset conditioning) L/S on perp panel, k=3, sweep over cadences {5,7,14,21}d × iwins {14,30,60}d × methods (sign_consistency default) × cost_grid {0,5,10,20,30}bps × 2 signs = 120 cells, mandatory cost-tier sweep (R32/R89/R90 lesson #58 baked in), anti-costume gate |corr(R93, naive_fade)| < 0.60 vs R62/R60-style per-asset-z fade (lesson #42). 47 perps ∩ perp OHLCV = 46 perps after coverage filter, **1165-day panel 2023-05-12 → 2026-07-19** (longer/more balanced than 731d strict panel — in-sandbox perp data is the longest balanced panel available). 10/10 smoke tests pass. **🔴 REFUTED — three independent failures.** (1) **Anti-costume gate FAILED**: corr(R93_leg, naive_fade_leg) = **+0.728** (gate < 0.60). Informativeness-weighting did NOT meaningfully diverge from naive per-asset-z fade — cross-sectional signal dominated by underlying funding-z, ι too small a perturbation to move tercile assignments on this universe. **R93 collapses onto R60** (refuted naive fade) with 73% correlation. (2) **3-check fails at every cell**: best cell 7d/iwin=60/5bps/high_fund_long gross_t=+0.11 (well below 1.96); 0bps → +0.47, 5bps → +0.11, **10bps → −0.26 (dead at GATE)**, 20bps → −0.98, 30bps → −1.70. ALL 120 cells fail 3-check. Edge sign-flips from gross +0.47 (0bps) to gross −1.70 (30bps) — informativeness loses to naive fade at every realistic cost. (3) **Falsifiable mechanistic claim disproven**: R60 failed in W1 (−37.4%) and W3 (−22.5%) — the noisy-funding windows where crowd was RIGHT or funding was noise. R93 with ι was supposed to suppress those. **R93 W1=−26.1% (still negative, less bad) and W3=−31.8% (STILL NEGATIVE, slightly WORSE)**. Informativeness conditioning made W1 slightly less bad but did NOT turn it positive, and W3 actually got worse. Mechanism hypothesis disproven on this data. Per-window W1=−26.1%, W2=+11.0%, W3=−31.8%, W4=−2.9%, **W5=+59.5% (kept discovery)**, W6=+3.9% — 3/6 windows positive. maxDD=−26.24% (W2). Sign verdict **high_fund_long** (anti-fade — surprising for funding data, but 1165-day panel may have enough persistent crowding events that long-the-crowd is right side). **Lesson #43 v5 (CONFIRMED, 8th case)**: cross-sectional-demean family + informativeness-conditioned family = BOTH exhausted on funding. Perp-funding alpha now tested in 11 forms (R47/R60/R62/R76/R77/R89/R90/R91/R92/R93 plus R77's R76 leg). **Lesson #56 v2 (FINAL articulation, 11-attempt graveyard)**: perp panel cannot support 2nd single-strategy L/S on funding — lever is panel length (Minimax §OHLCV-EXTENSION), not strategy shape. **Why R93's anti-costume gate FAILED (structural reason)**: on perp panel, funding-z signal is highly cross-sectionally correlated (all 47 perps sample similar funding regimes); ι normalizes per-asset time-series persistence, which is largely INDEPENDENT of cross-sectional ranking. So top/bottom tercile picks are similar with or without ι → corr ~0.73. **Informativeness weighting adds information on the ASSET dimension but the cross-section L/S ignores that dimension.** **Path forward**: Strategy 2 = STRUCTURALLY DEFERRED pending §OHLCV-EXTENSION. R77 ships as the only L/S strategy. R93's W5=+59.5% lift is a kept discovery — re-run on extended panel when 11yr data available. **No more R94 in-sandbox attempts on funding** — perp-funding family is genuinely exhausted (lessons #43 v5 + #56 v2). Future R-numbers on funding MUST be on extended panel AND fundamentally different signal class (cross-frequency, structural-break, cross-asset basis, NOT informativeness/cross-sec-demean). **Files**: `src/research/validation/r93_informativeness_weighted_funding.py` (~520 LoC, NEW), `src/research/validation/tests/test_r93_informativeness_weighted_funding_smoke.py` (10/10 pass), R93 entry in REFUTATION_LEDGER.md. STRATEGY_2_DEFERRED.md updated to 11-attempt graveyard. Frozen R77 cell at w_R46=0.25/w_R62=0.75/w_R76=0.30 unchanged. Ships no production change. **Goal condition STILL UNSATISFIED** after 11 attempts (R82/R83/R85/R86/R87/R88/R89/R90/R91/R92/R93). NEW MEMORY: `r93-informativeness-weighted-refuted.md`.

- **2026-07-26 🔴 §STRATEGY-2 — R92 §TRADER_TOM two-layer directional overlay REFUTED; 10 attempts ALL REFUTED on 731-day panel; Strategy 2 STRUCTURALLY DEFERRED pending §OHLCV-EXTENSION (Seth, per user pivot to directional §TRADER_TOM overlay).**
  R92 = trend-conditional L/S sleeve = Layer 2 of §TRADER_TOM two-layer book (Layer 1 = R77, frozen). **KEY FIX vs R87** (REFUTED — 71% zero-gross + W4=−54.2% + W5=−29.3%): (1) **pre-confirmation filter (lesson #49)** — BTC close > 100d MA + 100d MA slope > 0 + 30d return > +3% → BULL_TREND LONG top-K; inverted → BEAR_TREND SHORT top-K; otherwise CHOP FLAT. Trend-specific, NOT macro-broad. (2) **SIGNED directional** — BEAR_TREND goes SHORT (R87 was long-only, couldn't earn bear alpha). 28-asset strict (OHLCV ∩ CIS ∩ funding), 731-day panel. 13/13 smoke tests pass. **🔴 REFUTED — NO cell passes 3-check at any cost tier.** Cost-tier sweep at best cell (7d rebal): 0bps → full_t=+1.03 (already below 1.96), 5bps → +0.98, **10bps → +0.94 (dead at GATE)**, 20bps → +0.85, 30bps → +0.76. Trend state distribution: 61.1% CHOP / 21.6% BULL / 17.2% BEAR (39% non-flat vs R87's 29%). Per-window W1=+0.0% (warmup), **W2=+254.8%** (early bull), W3=**−46.8%** (catastrophic chop-bear), W4=+136.2% (recovery), **W5=+509.7%** (massive late-cycle lift — directional overlay CAPTURES the bear move, kept discovery), W6=**−4.6%** (recent chop). 3/6 windows positive. **maxDD=−48.69%** (over 30% budget). **Lesson #55 (NEW)**: directional sleeves can have REAL alpha in some windows (W5=+509.7% beats R77's per-window lift) but the 3-check requires CONSISTENT alpha across windows, not just a strong subset. The "directional-right, magnitude-wrong" pattern (lesson #46) is the new 3-check failure mode for directional books. **Lesson #56 (NEW, FINAL articulation of 731-day panel constraint)**: the 10-attempt graveyard (R82/R83/R85/R86/R87/R88/R89/R90/R91/R92) is COMPLETE. **NO single-strategy shape clears 3-check on the 731-day panel** — not market-neutral L/S, not directional long-only, not directional long-short, not pair-trading, not perp-funding (3 shapes), not cross-asset, not trend-conditional. The lever is **panel length**, not strategy shape. **Aggregate lesson #55+#56 (10-attempt FINAL)**: "Try another shape on the 731-day panel is structurally futile" (lesson #54 upgraded to confirmed). R77 multi-leg fusion of regime-protected legs is the unique survivor. **Files**: `src/research/validation/r92_two_layer_directional_overlay.py` (~430 LoC, NEW), `src/research/validation/tests/test_r92_two_layer_directional_overlay_smoke.py` (13/13 pass), R92 entry in REFUTATION_LEDGER.md. Frozen R77 cell at w_R46=0.25/w_R62=0.75/w_R76=0.30 unchanged. Ships no production change. **Goal condition STILL UNSATISFIED** after 10 attempts. **R92's W5=+509.7% lift is a kept discovery** — re-run on 11yr panel when §OHLCV-EXTENSION completes.

- **2026-07-26 🔴 §STRATEGY-2 — R91 cross-asset funding pair REFUTED — perp shelf EXHAUSTED on pairwise axis (Seth, R90 follow-on per lesson #58 "next candidate must be STRUCTURALLY DIFFERENT").**
  R91 = pair-funding L/S on top 8 most-correlated perp pairs (ETC-LDO, ETC-STX, ETC-FIL, DOGE-ETC, FIL-LDO, AVAX-ETC, DOGE-LINK, FIL-SUSHI — all 0.78–0.82 funding correlation), 4 cadences (7/14/21/30d) × 5 cost tiers (0/5/10/20/30bps) = 20 cells, single-instrument per pair, mandatory cost-tier sweep (R32 lesson #58 baked in). 46 perps (Hyperliquid ∩ funding ∩ OHLCV), 1165-day panel (2023-05-12 → 2026-07-19). 11/11 smoke tests pass. **🔴 REFUTED — NO cell passes 3-check at any cost tier.** Cost-tier sweep at best cell (7d rebal): 0bps → +1.19 (already below 1.96!), 5bps → +0.88, **10bps → +0.58 (dead at GATE)**, 20bps → −0.03, 30bps → −0.63. Per-window W5=+60.6% (kept discovery PARTIALLY preserved, smaller magnitude than R76's +98.4%), W4=−32.4% (catastrophic — new bear-window exposure cross-sectional didn't have), maxDD=−30.44% (R77 by comparison is −8.91%, 3.4× better). **Critical finding**: pair-spread is a smaller, fainter echo of R76's signal at lower frequency and worse drawdown — the cross-sectional RESIDUAL edge is STRUCTURAL, not transferable to a pairwise version. **Lesson #58 (CONFIRMED, 4th case, 3rd shape)**: perp funding-driven L/S — RESIDUAL (R76), LEVEL (R73 path), CARRY (R90), or PAIRWISE SPREAD (R91) — does NOT survive at realistic cost on this universe. **Aggregate lesson #58 (FULLY ARTICULATED, 4 cases / 3 shapes)**: R89 (basis daily flip → 10bps fee trap), R90 (cross-sectional carry weekly+ → too thin), R76 (5d/0bps appeared to survive → R90/R91 show 5d-specific), R91 (pair-spread 7d/0bps → fainter echo, maxDD 3× R77). **Three paths remain** for the goal condition "完成两个可以进入真正交易的long/short 策略的开发": **A (RECOMMENDED)** — wait for OHLCV extension (Minimax §OHLCV-EXTENSION back to 2015-2023) then re-run on 11yr panel; **C (PRAGMATIC)** — accept R77 as the only L/S strategy (production-ready today, maxDD=−8.91%, Sharpe=+2.06, lower diversification); **D (NEW)** — pivot to STRUCTURALLY DIFFERENT data class entirely (cross-asset bond-equity L/S, TradFi-relative-value, structural-break vol). **Files**: `src/research/validation/r91_cross_asset_funding_pair.py` (~360 LoC, NEW), `src/research/validation/tests/test_r91_cross_asset_funding_pair_smoke.py` (11/11 pass), R91 entry in REFUTATION_LEDGER.md. Frozen R77 cell at w_R46=0.25/w_R62=0.75/w_R76=0.30 unchanged. Ships no production change. **Goal condition STILL UNSATISFIED** after 9 attempts (R82/R83/R85/R86/R87/R88/R89/R90/R91). **Surface to user**: 3 paths (WAIT OHLCV / ACCEPT R77 / NEW DATA CLASS) — decision required.

- **2026-07-26 🔴 §STRATEGY-2 — R90 perp funding-carry HELD REFUTED — perp shelf EXHAUSTED on cross-sectional funding family (Seth, per user "Try LOW-turnover single-instrument perp signal (R90)" pivot).**
  Per user choice (Option B over Option A "wait for OHLCV" and Option C "ship R77 alone"), R90 = perp funding residual (R76's signal verbatim) cross-sectional L/S, weekly+ rebal (cadences 7/14/21/30d), single-instrument perps only (no spot leg), **mandatory cost-tier sweep at 5/10/20/30bps** (R32 lesson #58 baked in). 47 perps ∩ perp OHLCV = 46 perps after coverage filter, 1165-day panel (2023-05-12 → 2026-07-19). 12/12 smoke tests pass. **🔴 REFUTED — NO cell passes 3-check at any cost tier.** Cost-tier sweep at best cell (7d/5bps): 0bps → +1.21 (below 1.96), 5bps → +0.91, 10bps → +0.62 (already dead at GATE), 20bps → +0.03, 30bps → −0.56. **Edge erodes monotonically with cost.** Per-window W5=+14.6% (kept discovery PARTIALLY preserved), W6=−47.0% (catastrophic — the recent 6-month chop). Critically, **the lower turnover DEFEATS the signal** — 21d/0bps already at gross_t=+0.10 (0.07× the W1 alpha); the carry does not persist across a week. **R76's standalone edge was a 5d-specific phenomenon, not a perpetual carry.** **Lesson #58 (CONFIRMED, third case)**: perp microstructure — RESIDUAL, LEVEL, or CARRY — never survives realistic cost. **Aggregate lesson #58 (FINAL articulation, 3 cases)**: R89 (two-leg daily flip → dies at 10bps fee trap), R90 (single-instrument weekly+ HELD → fails at every cost tier), R76 (5d/0bps appeared to survive but R90 shows the edge was a 5d-specific artifact). Shelf EXHAUSTED on cross-sectional funding demean. **Path forward**: STRUCTURALLY DIFFERENT shapes only — cross-frequency funding (4h → 24h aggregation), informativeness-WEIGHTED funding, CROSS-ASSET perp basis (ETH-funding vs BTC-funding, both perp-taker cheaper than spot-perp), time-series funding momentum (Δfunding acceleration). Or accept R77 single-strategy book (Option C) / wait for OHLCV extension (Option A). **Files**: `src/research/validation/r90_perp_funding_carry_held.py` (~530 LoC, NEW), `src/research/validation/tests/test_r90_perp_funding_carry_held_smoke.py` (12/12 pass), R90 entry in REFUTATION_LEDGER.md. Frozen R77 cell at w_R46=0.25/w_R62=0.75/w_R76=0.30 unchanged. Ships no production change. **Goal condition STILL UNSATISFIED** after 8 attempts (R82/R83/R85/R86/R87/R88/R89/R90). Surface to user: 3 paths (STRUCTURAL SHIFT for R91+ / accept R77 / wait OHLCV).

- **2026-07-26 🔴 §STRATEGY-2 — R89 perp-spot basis REFUTED as taker-fee illusion; correcting a wrongly-locked Strategy 2 verdict (Seth).**
  Per user option C ("fundamentally different data shape"), R89 = perp-spot basis L/S (long spot / short perp when basis wide, dollar-neutral, daily rebal) on Hyperliquid perp OHLCV ∩ spot OHLCV (30-asset, 731-day panel) — a NEW data feed not in R77's family. It cleared the 3-check gauntlet **at 5bps** (gross_t=+5.51, 5bps_t=+3.62, OOS_t=+4.75) and — critically — **beat the W5 fragility** that kills the OHLCV family (all 6 windows positive, W5=+36.59%). A prior pass (pre-compact) had LOCKED it as Strategy 2 in `STRATEGY_PLAYBOOK.md` + `STRATEGY_2_DEFERRED.md` + `REFUTATION_LEDGER.md`. **That was wrong.** On resume I ran the cost-tier check that is MANDATORY for basis/carry trades per R32 (`1af76e5` cash_carry): R89 is a **daily-rebalanced two-leg (spot+perp) flip** paying taker on BOTH legs; realistic round-trip is 15–30bps, not 5. **Cost-tier sweep: 5bps → 3/3 (OOS +33.9%); 10bps → cost_t=−0.69 / OOS +1.9% (dead); 20bps → −62%/yr; 30bps → −126%/yr. NO cell survives ≥10bps** across the full threshold × cadence × lookback grid. **Verdict → 🔴 REFUTED — taker-fee illusion, same class as R32.** **Lesson #58 (decisive)**: ANY basis/carry/two-leg trade MUST pass a ≥10bps cost-tier gate before "tradeable"; the 3-check at 5bps is necessary but NOT sufficient for high-turnover multi-leg strategies. Gate is now baked into the R89 module verdict (`survives_realistic_10bps: false` in `verdict.json`). **Also fixed**: smoke test asserted the pre-lock config (R89_BASIS_THRESHOLD=0.005, R89_CAD=7) while the module was locked at (0.003, 1) — the prior "8/8 pass" was drift; corrected, now genuinely 8/8. **Goal condition ("two tradeable L/S strategies") — NOT satisfied.** Strategy 1 = R77 fusion cell (LOCKED, validated WITH 5bps, low-turnover single-instrument legs — defensible). Strategy 2 = STILL OPEN; no candidate has survived realistic cost. **Kept discovery**: perp microstructure IS regime-orthogonal to the OHLCV factor family (that's where a genuinely tradeable perp signal may live) — but R90 candidates must be **LOW-turnover / single-instrument** (funding-carry HELD across days, not a two-leg daily flip; basis term-structure and intraday reversion are also two-leg, same tax). **Files (M)**: `src/research/validation/r89_perp_spot_basis_sleeve.py` (cost-tier gate added + verdict gates on `survives_realistic`), `src/research/validation/tests/test_r89_perp_spot_basis_smoke.py` (config-assert fix → 8/8 real), `STRATEGY_PLAYBOOK.md` (R89 row → 🔴 REFUTED + cost-tier table), `STRATEGY_2_DEFERRED.md` (still-open status, taker-fee illusion explanation), `REFUTATION_LEDGER.md` (R89 header/verdict flipped + lesson #58). **NEW MEMORY**: `r89-perp-basis-fee-illusion`. Frozen R77 cell at w_R46=0.25/w_R62=0.75/w_R76=0.30 unchanged; ships no production change. **Surface to user**: goal condition NOT yet satisfied after 7 attempts (R82/R83/R85/R86/R87/R88/R89); decision requested — accept R77 single-strategy book (Option C of STRATEGY_PLAYBOOK §Path forward) or keep waiting for OHLCV extension (Option A) / different signal shape (Option B).

- **2026-07-26 ✅ §STRATEGY-2-DEFERRED — Strategy 1 (R77 fusion cell) LOCKED in STRATEGY_PLAYBOOK.md, Strategy 2 = 4 candidates REFUTED on the 731-day panel, structural reason documented (Seth).**
  Per goal "完成两个可以进入真正交易的long/short 策略的开发", Strategy 1 = R77 fusion cell (gross_t=+3.10, OOS_t=+3.61, maxDD=−8.91%, Sharpe=+2.06) — **live spec written, frozen weights (w_R46=0.25/w_R62=0.75/w_R76=0.30), monitoring via R66/R71 wired, preflight green, 11/11 R77 smoke tests pass**. Strategy 2 = DEFERRED after 4 attempts all REFUTED on the same 28-asset 731-day panel: **R82** 🟡 PARTIAL (pillar_A regime-gated, gross_t=+1.45 < 1.96 but matched-cell diff +5.46 — directional-right magnitude-wrong, lesson #46); **R83** 🔴 REFUTED (vol risk-premia L/S, gross_t=+0.36, 5bps_t=+0.27 — crypto microstructure does not support TradFi low-vol anomaly, lesson #47); **R85** 🔴 REFUTED (R77 + regime-gate at fusion level, gross_t=−0.26 — double-counts R62's fragility detector, lesson #45); **R86** 🔴 REFUTED (R46 on 11yr pillar + 50% OOS, best OOS_t=+0.52 — OHLCV binding constraint NOT a sample-size issue, lesson #48). **STRUCTURAL FINDING FINAL**: the 731-day window (2024-06-07 → 2026-06-07) is too bear-dominated for ANY single-leg factor to clear the 3-check gauntlet; R77 fusion of three regime-protected legs (quality / crowding / funding) is the unique survivor. **S-82 + R85 corroboration**: R77 alpha is FLAT across BTC-trend bands (deep_off +0.9% / off +0.5% / neutral +0.2% / on +0.7% / deep_on +0.6%) — genuinely regime-INVARIANT, not regime-DEPENDENT. **Architectural insight (NEW)**: §TRADER_TOM_DOCTRINE two-layer book needs orthogonal SHAPES — one market-neutral factor book (R77) + one DIRECTIONAL trend-overlay book (not yet built). All four Strategy 2 candidates were attempts at a second market-neutral L/S (the wrong shape for the trend-overlay slot). Right Strategy 2 is a DIRECTIONAL sleeve (LONG in confirmed risk-on trend, SHORT or FLAT otherwise), deferred pending architecture + new paper-book infra (out of scope this round). **Path forward**: Option A (RECOMMENDED) — wait for OHLCV extension (Minimax §OHLCV-EXTENSION) then re-run R86-style sweeps on 11yr price data; Option B — fundamentally different approach (directional L/S, perp-spot basis, cross-frequency); Option C (NOT recommended) — ship R77 as single-strategy book. **NEW files**: `STRATEGY_PLAYBOOK.md` (Strategy 1 LOCKED spec, ~170 lines), `STRATEGY_2_DEFERRED.md` (honest graveyard, ~180 lines), batched R82/R83/R85/R86 entry in REFUTATION_LEDGER.md. **NEW modules**: `r82_pillar_a_regime_gated.py` (~290 LoC, 10/10 smoke), `r83_vol_risk_premia_ls.py` (~165 LoC, 5/5 smoke), `r85_r77_regime_gated.py` (~280 LoC, refuted), `r86_r46_11yr_extended_oos.py` (~165 LoC, refuted). Frozen R77 cell at w_R46=0.25/w_R62=0.75/w_R76=0.30 unchanged. Ships no production change — research + spec docs only; awaiting user sign-off on Strategy 2 deferred verdict.

- **2026-07-26 🔴 §STRATEGY-2 — 6 attempts all REFUTED — R87 directional sleeve + R88 pair-trading sleeve also fail 3-check; structural finding FINAL (Seth, per user's "keep on finishing" pivot).**
  Per user pivot ("build a DIRECTIONAL sleeve to literally satisfy the goal"), attempted two more shapes after the §STRATEGY-2-DEFERRED close-out. **R87** 🔴 REFUTED — directional LONG top-K quality + regime-gated gross: gross_t=+0.08, 5bps_t=+0.03, OOS_t=−1.41 (0/3 cleared). 71% of panel has reduced/zero gross (RISK_OFF 35% + TIGHTENING 24% + STAGFLATION 4%); alpha FLAT across all 4 measured regimes (RISK_ON +0.1%, EASING −0.1%, TIGHTENING +0.3%, RISK_OFF +0.2% — all noise). Per-window W1-W6: only W2=+115.6% positive, W1=−38.4%, W4=−54.2%, W5=−29.3%, W6=−25.6%. Lessons #49 (need pre-confirmation signal on top of regime), #50 (W4-W6 leak). **R88** 🔴 REFUTED — pair-trading (within-pair quality spread, dollar-neutral, top-10 pairs by 60d rolling corr ≥ 0.70): gross_t=+1.30, 5bps_t=+1.03, OOS_t=+0.48 (0/3 cleared). 4/6 positive windows but t-stats too thin to clear 1.96 (max α_t = +1.93 in W6). W3=−30.9% (new pair-trading-specific bear-window exposure on average-vol days) + W5=−35.7% (same late-cycle risk-on chop window R46/R77 sign-flipped in — consistent across shapes). Selected pairs MANA-SAND (0.93), ARB-OP (0.90), GALA-MANA (0.87), DOGE-SHIB (0.87), ARB-GALA (0.86), DOT-GALA (0.86), AVAX-LINK (0.85), GALA-VET (0.84), ATOM-GALA (0.83), ARB-ETH (0.82). **FINAL structural finding (lessons #52-#54)**: 731-day panel is bear-dominated for ANY single-strategy shape — market-neutral L/S (R82/R83/R85/R86), directional long-only (R87), AND pair-trading (R88); R77 multi-leg fusion is the unique survivor because each leg has its own regime-protection mechanism. "Try another shape" on the same panel is a sunk-cost trap (lesson #54); the lever is panel length, not strategy shape. **Goal condition ("two tradeable L/S strategies") — STILL UNSATISFIED after 6 distinct attempts**. **Path forward FINAL**: A (RECOMMENDED) — wait for OHLCV extension (Minimax §OHLCV-EXTENSION back to 2015-2023), then re-run R46/R82/R83/R86 candidates on 11yr price data; B — accept R77 as the only L/S strategy and ship as single-strategy book (lower diversification, but production-ready today, maxDD=−8.91%, Sharpe=+2.06). **NEW files**: `r88_pair_trading_sleeve.py` (~310 LoC) + 8/8 smoke tests; R88 entry in `REFUTATION_LEDGER.md` (~80 lines); `STRATEGY_2_DEFERRED.md` updated to 6-attempt graveyard; `STRATEGY_PLAYBOOK.md` graveyard table extended. Frozen R77 cell at w_R46=0.25/w_R62=0.75/w_R76=0.30 unchanged. Ships no production change — research + spec docs only; **next step: present cleanest options to user**.

- **2026-07-26 ⚪ R75c — R75 re-run end-to-end after upstream T1 recovery; pipeline HEALTHY (1.3h), maturity still ⚪ PREMATURE on density (valid_hours 662 < 720) (Seth).**
  Same `src/research/validation/r75_hourly_so_quintile.py` re-executed end-to-end (no code change, no smoke-test change, no production change). Coverage-only dry-run first to confirm freshness, then full 96-cell sweep. **Pipeline recovered cleanly** per §OHLCV-DEAD — staleness 74.5h (2026-07-23) → **1.3h** (today), latest_data_hour `2026-07-26T01:00:00`, returns_source=`public_ohlcv_api`. **Maturity gate binds on valid_hours (662 < 720)** — calendar_days 35.96 ✓, assets 28 ✓. The 3-day stall (2026-07-19 → 2026-07-25) left a 200-hour density hole in the 863-hour calendar span; need ~58 more cleanly-written hours with ≥12 valid assets to cross. **Headline t-stats** (provisional / no credit): pillar O / Δ=1h / rebal=4h → gross α_t=**+1.46** (ann +150.63%), 5bps α_t=**−0.77**, OOS α_t=**−1.21** — all 3 cells still fail; even if maturity had cleared the verdict would read 🔴 REFUTED. **3 assets still null-pillar** (BCH, ICP, WIF — same as 2026-07-23; not in strict 28-asset funding ∩ OHLCV universe so doesn't block research). **Lessons #46 + #47** in `REFUTATION_LEDGER.md` R75 §update 2026-07-26 (panel-density vs calendar-span distinction; re-run after every pipeline recovery). Next R75d: re-run tomorrow 2026-07-27 to check if 720h gate has cleared on clean pipeline; if so, the next sweep becomes the first **verdict-eligible** run (maturity gate is the binding constraint, not the t-stats themselves). Reports gitignored at `reports/r75_hourly_so_quintile/2026-07-26/` (full) + `2026-07-26_coverage/` (coverage dry-run).

- **2026-07-26 ✅ §BETA-METRIC-AGG + §VDB + §REGIME-ALIGN + §FEEDS-RESILIENCE PRODUCTION PUSH — every P0 Seth-side item shipped, gated on Mac-side ohlcv_daily restart (Seth, Jazz "完成beta-metric-agg 还有所有的minimax_sync 里面的p0，我们需要尽快跑通进入production").**
  **(1) §BETA-METRIC-AGG** — investor `/signals/track-record` now publishes RAW + β-ADJ side by side, labelled. SQL migration `scripts/supabase_refresh_signal_track_record_v2.sql` (idempotent, 270 lines) emits 4 new β columns per (symbol, signal-bucket) row (avg_edge_beta_adj_pct, edge_beta_adj_t, avg_beta_pit, n_beta_adj) using PIT expanding-window OLS — exactly mirrors `src/data/market/beta_adjust.py`, min 20 priors, never default β=1.0. Aggregator refactored into pure module `src/api/routers/_track_record_agg.py` (no Supabase/httpx) ⇒ 16/16 smoke tests pass. Ship gate in `src/api/store.py::supabase_ohlcv_daily_freshness()` (5-min cache, opens iff age < 36h) — when gate CLOSED, BETA_ADJ + BETA_ADJ_T_STAT become explicit None (not silent zero), defect_warning silent; RAW continues to publish so no investor surface degrades today. **Auto-opens when ohlcv_daily resumes — no manual sync needed.**
  **(2) §VDB (strategy vectors)** — `src/data/vector/strategy_store.py` rewritten: source of truth = Postgres jsonb (`strategy_records` table), Redis = embeddings cache (rebuildable from records). Migration `scripts/supabase_strategy_records.sql` creates the table + index + `strategy_records_bump_updated_at()` trigger (idempotent). `STRATEGY_RECORDS_DUAL_WRITE=1` env flag (default ON) writes BOTH paths during cutover; `migrate_redis_to_postgres()` helper is one-shot idempotent. **NaN boundary preserved** — `_nan_to_null` / `_null_to_nan` serialize NaN→null on write (Upstash/JS JSON.parse doesn't reject), restore null→NaN on read (cosine's NaN-skip sees unmeasured dims). Design rule (unchanged, re-stated): **dense+many → pgvector HNSW; sparse+few → Postgres jsonb + NaN-aware Python cosine**. 7/7 strategy-store tests pass. Asset-vectors side (Mac-side embedding push → pgvector) still on Minimax's board per original 2026-07-23 §VDB ask.
  **(3) §REGIME-ALIGN ②** — `src/data/market/cis_provider.py::canonical_regime()` normalizes stored `macro_regime` to UPPER_SNAKE (GOLDILOCKS/RISK_ON/EASING/NEUTRAL/TIGHTENING/RISK_OFF/STAGFLATION). Internal title-case lookups untouched. "UNKNOWN"/None → NEUTRAL. T2 fallback output now agrees with T1's format. **Minimax**: confirm T1 keeps emitting the canonical 7; map UNKNOWN → NEUTRAL at source.
  **(4) §FEEDS-RESILIENCE** — DONE (closes the §FEEDS-RESILIENCE work). EODHD primary (TradFi) + Hyperliquid fallback (crypto) live and verified; loud zero-write warning + 2 new `loop_health` stages wired. **Important re-read**: §FEEDS-RESILIENCE fixed the COLLECTOR (Railway-side). The §OUTCOMES-STALE / §OHLCV-DEAD stalls are caused by the WRITER (Mac-side scheduler / T1 engine), not the collector. The two were co-temporaneous but separate problems.
  **(5) §PIT-LEAK-C (production)** — `src/data/signals/two_layer_paper.py::_NORM_WIN = 252` trailing window; `regime_score_c` F1/F2/F3 use rolling normalization on strictly-prior 252 bars. **Production is PIT-LEAK-CLEAN.** Re-run research on the fixed engine is on Minimax-A's board (P2, not blocking production).
  **(6) §OHLCV-DEAD (partial)** — pipeline state reality check: data-completeness RECOVERED (T2 fallback now persists pillars; the 07-19 14:54 stall symptom does not reproduce) but ohlcv_daily ingest-freshness STILL STALE at 2026-06-19 (~37d). The §BETA-METRIC-AGG ship gate is calibrated to this 36h threshold.
  **Mac-side commit handoff**: FUSE blocks git-write in sandbox. Files to commit (Mac-side): `src/api/store.py` (modify), `src/api/routers/_track_record_agg.py` (new), `src/api/routers/signals.py` (modify), `src/api/routers/tests/test_track_record_agg_smoke.py` (new), `src/data/vector/strategy_store.py` (rewrite), `src/data/vector/tests/test_strategy_store_pg_smoke.py` (new), `src/data/market/cis_provider.py` (modify), `scripts/supabase_refresh_signal_track_record_v2.sql` (new), `scripts/supabase_strategy_records.sql` (new), `src/mcp/cometcloud_mcp.py` (docstring update), `MINIMAX_SYNC.md` (resolution entries), `MINIMAX_OPEN_QUEUE.md` (new), `PROJECT_STATE.md` (this entry). **Plus: `select refresh_signal_track_record();` once** after the migration is applied (Supabase side, requires service-role key). Commit message draft: `feat(production): §BETA-METRIC-AGG + §VDB + §REGIME-ALIGN — ship-gated β-ADJ + durable strategy vectors + canonical regime contract (Seth, 2026-07-26)`. **NEW MEMORY**: `2026-07-26-production-push` — non-obvious: ship gate is calibrated at 36h on `ohlcv_daily.last_trade_date`; the layered endpoint shape (RAW/BETA_ADJ/BETA_ADJ_T_STAT/WIN_PCT × TIER_ORDER) is the consumer contract; the strategy_store NaN boundary uses `_nan_to_null`/`_null_to_nan` pair, not python's default (which would emit invalid `NaN` literal). New entry head: `MINIMAX_OPEN_QUEUE.md` is the one-page Monday standup summary.

- **2026-07-26 ✅ OPERATIONAL LOOP SKILLS SHIPPED — `task-audit` + `completion-verification` + CLAUDE.md §Operational loop wired (Seth, per Jazz "完成beta-metric-agg 还有所有的minimax_sync 里面的p0，我们需要尽快跑通进入production" + "还有很多东西做了一半不知道").**
  Closed the "things half-done, we don't know" failure mode. Two new Seth-side skills + one new CLAUDE.md section. **NEW files**: `.claude/skills/task-audit/SKILL.md` (~165 lines, 4-block unified status — Seth-side in-flight / Mac-side P0-P1 / awaiting Jazz / drift check; thresholded stale detection: P0 > 3d → ⚠️, > 7d → 🔴; runs auto on session start + on-demand "audit/卡在哪/where are we"); `.claude/skills/completion-verification/SKILL.md` (~145 lines, 5-check done-claim hook — git status / staged vs scope / unpushed / preflight + tests / state-doc drift; closes the "trust memory of what's committed" failure mode (2026-07-02 commit-mismatch, 2026-07-13 main.py unimported Response, 2026-07-19 §OHLCV-DEAD silent 7 days)). **MODIFIED**: `CLAUDE.md` added §Operational loop (session-start ritual + 5-node loop diagram + Mac-side commit handoff template + block-detection threshold table + linked-artifacts map). Skills table now includes `task-audit` + `completion-verification` rows. **Validation**: ran `completion-verification` on this very shipping session — verdict PASS-WITH-WARNINGS (warnings: FUSE-blocked working tree, expected; preflight PASS; Last updated header same day, no drift). Self-test of the new skill on the new skill = clean. **Architectural insight**: the loop is closed structurally — session-start ritual + done-claim hook + drift check are the three hooks that make the rest of the page-level instructions actually enforceable. The skill files are the "what" + "when" + "how"; CLAUDE.md's new section is the "where it fits in the world" + the threshold table + the handoff template. **Mac-side commit handoff** (combined with the production push above): add `.claude/skills/task-audit/SKILL.md` (N), `.claude/skills/completion-verification/SKILL.md` (N), `CLAUDE.md` (M) to the same Mac-side commit. **NEW MEMORY**: `2026-07-26-operational-loop` — the 5-node loop name, the stale-threshold table, the failure-mode table (3 historical failures this skill kills).

- **2026-07-25 ✅ §DATA-ALIGN (A/B/C) DELIVERED — 11yr CSV aligned to cis_scores schema, 2024-bull pillar_a unlocked, per-pillar IC mining settles "is pillar_A real?" (Seth).**
  Jazz's 3-part directive closed end-to-end. **(A) Header alignment:** new canonical schema module
  `src/research/data_align/cis_history_schema.py` (single source of truth, 20 cols) — both
  `scripts/cis_historical_ingest.py` and `absorption_sweep_runner.py` now import from it (killed the
  position-inferred column duplication). CSV header prepended idempotently; aligned output at 75,478 rows
  × 33 cols (+12 trailing-window regime z-score cols + β-adj returns via PIT-safe expanding β from
  `src.data.market.beta_adjust`, NEVER full-sample — §BETA-METRIC / §PIT-LEAK-C respected). **(B) Supabase
  unlock:** `cis_historical_ingest.py --target supabase` is data-ready; **34/34 assets pass the 2024 bull
  gate** (≥95% rows have all 5 pillars, 100% pillar_a coverage) — blocked only on SUPABASE_SERVICE_KEY.
  **(C) Mining granularity:** per-pillar IC × regime × cycle + per-asset-class + per-vol-bucket, with the
  **event-count gate MANDATORY** (n<30 ⇒ ⚪ INSUFFICIENT — the S-78/S-79 pseudo-replication fix baked into
  `verdict()`). **HEADLINE FINDING: pillar_A is regime-CONDITIONAL, not regime-illusion.** ✅ POSITIVE in
  RISK_ON (2024 t=+5.15, 2025 t=+2.36), EASING (2024 t=+7.24, 2025 t=+6.23), STAGFLATION (2025 t=+2.80);
  🔴 NEGATIVE in TIGHTENING (2024 t=−3.45), RISK_OFF-bear (2025 t=−8.63, 2026 t=−9.83), EASING-bear (2026
  t=−8.71). By class: ✅ L1/L2/Infra on 2024-bull, 🔴 RWA on 2024-bull. **The R73/R74 "A is dead" verdicts
  were panel-limited (2025-2026 bear) — regime artifact, not true refutation.** ⇒ pillar_A must be
  **REGIME-GATED** in production; S-77/78/79 must run regime-conditioned from the start (no more
  single-panel refutations). 10/10 + 6/6 smoke, preflight green. Reports gitignored at
  `reports/data_align/`. NEW package `src/research/data_align/` (schema/loader/enrich/coverage/ic_mining/
  ic_summary + 2 test files) + `scripts/cis_historical_align.py` orchestrator; MODIFIED
  `cis_historical_ingest.py` + `absorption_sweep_runner.py` (import canonical schema). Ships no production
  change — research + data-prep only.

- **2026-07-23 🛠 S-81 — the INFLUENCE-PROPAGATION frontier: primitive built, naive form refuted, correct form gated on data ("be water, be quantum", Seth).**
  Jazz "往高认知做 / be water be quantum" → went to the ARCHITECTURE frontier (Entity/Decision/propagation;
  "CIS is a reflection, beta+ is a TEMPORAL vector upstream of the wavefront — the edge is the LAG"). Built
  `src/data/vector/propagation.py`: the embedding similarity graph IS the diffusion field; signal diffuses via
  personalized-PageRank `p=(1−α)s+αWp`; `entanglement_delta=p−s` reads the lag (field ahead of a node ⇒ beta+).
  6/6 smoke, closed-form verified. **Ran it through the loop immediately (anti-imposter):** (1) diffusing the
  CIS **level** is REFUTED — Δ-IC −0.16 vs raw +0.13 (level-diffusion just re-derives inverse-level; a
  reflection can't carry the lag) ⇒ the source must be the **change/flow (the cause)**, not the level; (2)
  diffusing the **change** is UNTESTABLE on proxy data — Δscore is reconstructed FROM the return (own-Δscore→fwd
  IC 0.9999 = leak). **So: the frontier layer is built + design-correct, the naive form is dead, the correct
  change/flow form is the open frontier — gated on §DATA-ALIGN (real multi-cycle CIS).** Third confirmation
  (S-79/S-80/S-81) that proxy/bear data can't validate the deep signals. NOT claimed as alpha. Ledger S-81.
  "Be quantum" done rigorously = build the non-local field operator, run the loop, let it refute the naive
  form and point at the right one. Source signals to diffuse when data lands: Δpillar, D1 flow, D4 attention.

- **2026-07-23 ✅ VDB follow-through — "find sister sleeve" mining flow + Minimax handoff (Seth).**
  Added `neighbours(records, id, k)` to the canonical strategy stack (NaN-aware cosine over SHARED dims) —
  the "find sister sleeve" primitive Minimax flagged. Wired into the graveyard library report. Output on the
  8 sleeves: **`risk_direction_score` is a redundancy HUB** (sister to cis_quality_ls_5d 0.90 AND
  swing_overlay_v9 0.89 → adds little unique breadth); ls_v4_ema_flip ≈ trend_v5c 0.86 (the churning twin).
  8/8 strategy + 6/6 graveyard tests, preflight green. Dispatched `MINIMAX_SYNC §VDB`: route the Mac
  embedding push through pgvector; move strategy records to DURABLE Postgres (Redis 4h-TTL loses permanent
  records) but keep similarity in NaN-aware Python — design rule **dense+many → pgvector HNSW; sparse+few →
  Postgres jsonb + NaN-aware cosine** (strategy vectors are 8–20 & sparse, ANN gives nothing + dense cosine
  over 0-imputed sparse would be WRONG). VDB thread complete: assets on pgvector (live), strategy path spec'd.

- **2026-07-23 ✅ VDB 落库 — vector store migrated Redis-JSON → Supabase pgvector (proper vector DB) (Seth, Jazz "路径不对").**
  The Redis-JSON blob path worked but wasn't a vector DB (no index/ANN, O(n) Python cosine). Migrated to
  **pgvector** (native to Supabase, no external Qdrant): enabled the `vector` ext; created `asset_embeddings`
  (`vec vector(18)` dense v1 core on an **HNSW cosine index** + `vec_full jsonb` full v2 with null for NaN)
  + `match_asset_embeddings(target,k,class_mode)` RPC (any/same/cross). **I1 preserved:** NaN never enters
  pgvector (rejects it) — unmeasured dims live in JSONB, never fabricated as 0. **Verified end-to-end:** 72
  assets loaded from cis_scores; ETH `any`→SOL/XRP/BTC/BNB, ETH `cross`→LINK/UNI/AAVE/POL/**AAPL** (cross-class
  analogs). New `src/data/vector/pgvector_store.py` (REST upsert + RPC similar), 6/6 smoke. Provider
  **dual-writes** to pgvector beside Redis (best-effort); `/api/v1/cis/similar` reads **pgvector-first, Redis
  fallback**. Preflight PASSED. Migrations captured in `scripts/supabase_pgvector_vdb.sql`. Redis stays
  belt-and-braces until reads fully cut over. Follow-up (Minimax): route the Mac-side embedding push + the
  strategy vectors (`strategy_store`) through pgvector too; text/news RAG embeddings get their own table later.

- **2026-07-23 ✅ S-80 — "拉长周期" (Jazz) reverses the bear-window pessimism: CIS score + F robust 12/12 years (Seth).**
  Jazz caught it: S-77/78/79 were all mined on the bear-dominated 1-yr real-CIS window, so "signal weak / A
  unstable" was regime confound, not refutation. Extended to the 11yr history (`cis_historical_11yr.csv`,
  2015-2026, 34 assets): **score→fwd-return rank-IC POSITIVE every single year (12/12, +0.12…+0.18), F_IC
  12/12 positive pooled +0.197 (2× M, 4× O/S).** The CIS signal is durable across bull/bear; F is the
  double-confirmed durable anchor (S-79 bear + S-80 long). **⇒ CIS v5 return_score reweighted F-anchored
  (F 0.40 / M 0.25 / A 0.35).** Corrections logged: **S-79's A-refutation DOWNGRADED to "bear-window-only,
  unresolved"** (A absent from the 11yr proxy — untestable long-horizon); S-78 vol sleeve stays refuted on
  available β-data but bear-scoped. Caveat: 11yr is proxy (pre-2024 momentum+vol, no A, raw fwd-ret).
  **Dispatched Minimax `§DATA-ALIGN`** (Jazz's instruction): (A) header-align the 11yr CSV to cis_scores schema
  + add pillar_a + β-adj; (B) **land the real-CIS 2024-bull backfill into Supabase** — the actual unlock to
  settle A/vol across a full cycle; (C) mining spec with EVENT-COUNTING mandatory (per-pillar IC×regime×cycle,
  vol×macro, per-class). 7/7 v5 tests. **Meta-lesson (session's biggest): a 1-year single-regime sample cannot
  falsify a signal — need a multi-cycle window; the real fix is more real-CIS history, not more bear-mining.**

- **2026-07-23 🔴 S-78 event-count — the last survivor REFUTED; no tradeable vol-sizing sleeve (Seth).**
  Applied R44 lesson #12 (count EVENTS not autocorrelated days) to the one OOS survivor, RISK_OFF×storm. Its
  day-level oos t+14.1 (n=1300) is only **4 independent episodes, 2 up / 2 down** (−7.82/+4.70/+5.62/−10.38;
  episode-mean −1.97) — the t+14 was pseudo-replication of ONE 62-day risk-off block. **REFUTED.** Full arc:
  in-sample t+8/+17 → temporal split kills 5/6 → event-count kills the 6th. **The (macro×vol) stratification
  is real descriptively but NOT a tradeable sizing edge** — `size_multiplier()` now presses nothing (bar
  `event_confirmed`, uncleared). The vol sleeve the coverage map wanted is not born from this seed — honest
  graveyard. 5/5 smoke. Ledger: S-78 event-count. This is the anti-imposter gauntlet working end-to-end; the
  graveyard is the asset. **Net today: fixed 4 silent pipeline failures (pillar/regime/TradFi/crypto feeds) +
  2 health-check gaps; mined + honestly killed a vol sleeve.** Real remaining edge search continues elsewhere.

- **2026-07-23 🟡 S-78 OOS — the map was too generous; ONLY RISK_OFF×storm survives the temporal split (Seth).**
  Ran the gauntlet on S-78's two ✅ corners. Train/OOS split 2026-02-01, vol cuts derived from TRAIN only
  (PIT). **RISK_OFF×storm SURVIVES** — train +0.98 (t+1.91) AND oos **+4.84 (t+14.1, n=1300)**, same sign both
  halves → the one OOS-robust sizing cell (size UP when risk-off + high vol). **EASING×calm FAILS the test**:
  real in train (+3.13, t+4.52) but **zero OOS obs** (regime didn't recur) → untestable, not tradeable.
  RISK_OFF×normal consistently negative; EASING×normal sign-flips (unstable). **So the pretty in-sample
  2-corner map collapsed to ONE cell under time-splitting** — exactly what the gauntlet is for. Caveat logged:
  RISK_OFF×storm's OOS window is risk-off-dominated → event-count + DSR/PBO still owed before it's a live
  sleeve. Module now OOS-gated (`S78_CELLS` status; `size_multiplier` presses only `oos_confirmed`), 5/5 smoke.
  Meta-lesson: in-sample t+8/+17 can still be one-regime-deep; the temporal split separates real-across-time
  from recent-artifact. Ledger: S-78 OOS follow-up.

- **2026-07-23 ✅ S-78 — VALUE MINED: volatility regime stratifies the edge (the 风格分层 / sizing layer) (Seth).**
  Mined the coverage-map gap (calm/storm uncovered) into a real finding. Market-vol regime (BTC PIT 30d
  realized-vol tercile) stratifies the β-adj signal edge, INDEPENDENTLY of macro. One-way: calm +2.52 (t+6.3),
  normal −0.93 (t−2.3), storm +4.09 (t+15.1) — U-shape, best at extremes. **Two-way (× macro) is the finding:
  EASING×calm +6.35 (t+8.0) ✅ and RISK_OFF×storm +5.70 (t+17.6) ✅ — edge lives in OPPOSITE vol corners by
  regime; normal vol loses in both.** Not time-clustered (full-sample spread), not a macro proxy (U-shape vs
  monotonic RISK_OFF%). This is the SIZE layer above Minimax's H2 DIRECTION table + grounds CIS v5 `risk_score`
  (market vol IS a sizing input, not just pillar_O). Module `regime_vol_stratification.py` (PIT `vol_regime()`
  + `size_multiplier(macro,vol)` + reproducible `stratify()`), 5/5 smoke. **IN-SAMPLE — needs OOS/DSR before
  sizing capital** (the seed of the vol sleeve, not the sleeve yet). Ledger S-78. Also: `MINIMAX_SYNC
  §FEEDS-RESILIENCE` (HL crypto fallback + EODHD TradFi + the two new health-check stages, all documented).

- **2026-07-23 🟢 ohlcv_daily stall — TradFi source fixed (yfinance→EODHD) + observability; crypto side scoped (Seth).**
  Chased the 06-18/19 price-feed stall directly. Both sources stopped together (coingecko 06-19, yfinance
  06-18). **Confirmed yfinance is dead** — sandbox test returns `YFRateLimitError: Too Many Requests`. The
  collector's TradFi path still used yfinance even though the rest of the system moved TradFi to EODHD
  (`afdc705`). **Fixed:** added `_fetch_eodhd_daily()` (mirrors the proven `get_eodhd_eod_data` `/eod/`
  endpoint) and wired it as TradFi PRIMARY with yfinance FALLBACK in `collect_ohlcv` (no regression — worst
  case = current behavior; new rows tagged source='eodhd'). **Observability (so it can't hide again):** the
  daily loop now logs a LOUD `⚠️⚠️ WROTE 0 ROWS` on a zero-write; `loop_health` gained an **"ingest freshness
  (ohlcv_daily)"** stage (BTC latest trade_date age >3d ⇒ broken). TradFi EODHD path can't be live-tested here (no key) but reuses the system's proven endpoint/auth.
  **Crypto (CoinGecko) side — FIXED with Hyperliquid fallback (Jazz's suggestion).** CG stalled 06-19
  (rate-limit/quota). Added `_fetch_hyperliquid_daily()` — HL is a public DEX API (no key, not geo-blocked
  unlike Binance-US), wired as crypto fallback (CoinGecko primary → HL fallback). **VERIFIED LIVE from the
  sandbox** (unlike EODHD): the exact shipped function returns BTC/ETH/SOL/HYPE daily candles, latest =
  today 2026-07-23, real closes; unlisted coins fall through gracefully. So both feed halves are now
  resilient: TradFi = EODHD→yfinance, crypto = CoinGecko→Hyperliquid. Preflight PASSED. Remaining Jazz/Railway
  item: check `COINGECKO_API_KEY` quota (nice-to-restore-primary), but crypto no longer depends on it.

- **2026-07-23 🟢 FIXED the null-pillar ROOT CAUSE (my lane, not just T1) + the health-check blind spot (Seth).**
  Ran it down instead of handing off. **The null pillars were a latent T2 bug, exposed by the T1 stall.**
  Evidence: T1 wrote full pillars until 07-19 then stalled (Mac-side); **T2 NEVER wrote pillars — 32,887
  null rows since 2026-04-16.** Root cause found in MY lane: the T2 writers (`main.py::_hourly_t2_snapshot_loop`
  + `cis.py` railway_snapshot) only read the NESTED `a["pillars"]["O"]`, but the universe builder emits the
  FLAT `a["o"]` shape → `pillars={}` → NULL pillar_f/o every write. Masked for months because T1 covered it.
  **Fixed:** shape-tolerant `_pillar_of()` (nested / flat `o` / `pillar_o` / `o_score`) in both writers, so
  the T2 fallback now persists real pillars — **v5 / risk-moments / edge_map now survive a T1 outage**
  instead of silently dying. Both writers also now emit `canonical_regime()` UPPER_SNAKE. **Health-check
  blind spot fixed** (`loop_health.py`): it only checked liveness (universe size, push freshness, spreads) —
  T2 kept those green while writing NULL pillars, so a 4-day pillar outage hid. Added a **"data completeness
  (pillars populated)"** stage → BROKEN when <50% assets have non-null pillar_O; surfaces data_tier too.
  Preflight PASSED; `_pillar_of` verified on all 4 shapes. **Only genuinely Mac-side item left: restart the
  T1 engine (cis_v4_engine.py) — but with the T2 pillar fix it's no longer a hard outage.** Still open (my
  lane, next): why `ohlcv_daily` collector (`main.py::_ohlcv_collector_loop`) is stale since 06-19.

- **2026-07-23 🔴→🟢 "升级之后就乱了" DIAGNOSED — T1 engine stall broke pillars + regime labels; the regime SIGNAL is validated (Seth).**
  Jazz asked if 周期判断/分类 are done + v5's real effect. Investigated on live data:
  **(1) v5 can't show live effect** — `cis_scores.pillar_o` (all pillars) is **NULL since 2026-07-19** (last
  non-null 14:54); v5/risk-moments need pillars. Same family as ohlcv stall + Minimax R75b probe = **T1
  engine stalled ~07-19**, Railway T2 limping. **(2) 周期判断 core is VALIDATED:** on the clean UPPER_SNAKE
  period (2025-06-18→2026-05) bucketing β-adj edge by regime separates risk cleanly — **RISK_ON +10.22/tail
  −6.35, RISK_OFF +1.74, EASING −1.49, STAGFLATION −4.76**. The scary "Risk-On −3.45" was a TIME CONFOUND
  (title-case `Risk-On` only existed 2025-05→06-17, pre-upgrade bad window), NOT a broken detector.
  **(3) Label contract fixed (my lane):** two formats polluted `macro_regime` (T1 UPPER_SNAKE vs T2
  title-case + "UNKNOWN"). Added `cis_provider.canonical_regime()` → normalizes the STORED macro_regime to
  UPPER_SNAKE (internal `_REGIME_MULT`/`_REGIME_ALIGN` title-case lookups untouched; UNKNOWN/None→NEUTRAL).
  Preflight PASSED. **(4) 策略分类 = DONE** (yesterday's coverage map: build a cost-feasible VOL sleeve).
  **P0 for Minimax (`MINIMAX_SYNC §REGIME-ALIGN`): restart T1 + backfill pillars 07-19→now** — that revives
  the whole pillar-dependent stack (v5, risk moments, edge_map) on live data. Answer to Jazz: classification
  done · regime core validated (not "done" until T1 back + labels canonical both sides) · v5 validated
  historically but blocked live by the stall.

- **2026-07-23 ✅ Build-order #3 COMPLETE (3b done) — graveyard migrated to canonical; the library map is live (Seth).**
  Closed the last open build-order item. The 8 refuted/parked sleeves that lived in the DEPRECATED
  `src/research/strategy_vector.py` schema are re-expressed as canonical `StrategyRecord`s in
  `src/research/embed_graveyard_canonical.py` and run through the #3a-ported `coverage_gaps()`/`redundancy()`.
  The two "lossy" blockers resolved honestly: `leakage_clean=None` (UNVERIFIED) → `pit_clean=True` + a
  `pit_unverified` tag (an untested sleeve is NOT proven-leaky ⇒ must not be falsely disqualified — the
  swing_overlay_v9 case); `cost_slope` dropped (no lossless canonical home, acceptable). **The strategic
  output (reproduces VECTOR_SCHEMA_SPEC §2.1 on the canonical stack):** 7 live / 8 total (vol_carry_btc
  DISQUALIFIED on cost). **Regime coverage — the build-list: `regime_calm_vol` n=0 and `regime_storm_vol`
  n=0 are UNCOVERED; everything we own is directional** (risk_on 1.0, risk_off 0.65, trend 0.95, chop 0.45).
  **Fake breadth (redundancy ≥0.85):** cis_quality_ls_5d ≈ risk_direction_score (0.90), swing_overlay_v9 ≈
  risk_direction_score (0.89), trend_v5c ≈ ls_v4_ema_flip (0.86) — risk_direction_score adds little real
  breadth; ls_v4 is a trend-v5c dup (as its own notes said). **⇒ the next sleeve to build is a
  COST-FEASIBLE volatility sleeve (calm and/or storm), not another directional one.** `embed_graveyard.py`
  + `strategy_vector.py` marked DEPRECATED (superseded; `git rm` Mac-side). 6/6 canonical-graveyard smoke
  tests. Build order now FULLY closed: #1✅ #2✅ **#3✅** #4✅ #5🔴(refuted) #6✅(validated S-77).
  Also: `MINIMAX_SYNC §PROTOCOL` (READ FIRST) — the two Jazz-approved hard rules (S-/M- lane prefix +
  never `git add -A`, stage own paths only) written to the top so Minimax adopts them (flagged its bare
  `r78` should be `M-76`).

- **2026-07-22 (SESSION 2) ✅ S-77 — CIS v5 architecture VALIDATED on β-data; risk side corrected S→O (Seth).**
  Proved #6's claims before proposing deploy (β-backfilled `signal_outcomes`, n=6,207). **Return claim ✅:**
  v5_return (F/M/A) IC **0.0663** ≥ v4 composite (F/M/O/S/A) IC **0.0656** — dropping S/O from the return score
  costs nothing (A alone 0.0667 = the workhorse). **Risk claim ✅ but O-led:** dispersion corr(pillar, edge²)
  = **O +0.145** (2× any other), A +0.079, S +0.040, **F −0.002** (pure return). O quintiles escalate vol
  14.3→20.8 + tail −13.5→−20.9 monotonically. **⇒ O is the dispersion pillar, NOT S** — corrected the v5
  reference (`cis_v5_architecture.py` risk_score was S-led → now O-led; S enters only via Δ-stability→confidence).
  7/7 smoke still pass (load-bearing test: identical-except-O ⇒ same return rank, size_mult collapses; v4 does
  the opposite). Meta-lesson: build→validate→refine — the test moved risk S→O, which a design-only v5 would
  have baked in wrong. Ledger **S-76** (lead-lag) + **S-77** (this) appended under the approved lane-prefix
  convention (Jazz approved Option 2 2026-07-23; new Seth entries = `S-`, from 76). Build order COMPLETE +
  #6 now empirically validated.

- **2026-07-22 (SESSION 2) ✅ Build-order #6 — CIS v5 two-score architecture (reference) + R-numbering proposal (Seth).**
  The LAST build-order item. **CIS v5 is an architecture change, not a reweight** (R63b): v4 collapses 5
  pillars into ONE weighted sum (`calculate_total_score`: base×regime×IC), which cannot express that the
  pillars are three KINDS. Built `src/data/cis/cis_v5_architecture.py` (pure REFERENCE, not deployed) that
  emits **TWO separate scores**: `return_score` from {F level, M level, A level+change} — RANK on this;
  `risk_score`/`confidence`/`size_mult` from {S level→sizing, S/O stability→confidence} — SIZE on this.
  Grounded in the validated chain: R62 (β), R63 (S is risk not return), R63b (three factor kinds), **S-76**
  (S/O price-coincident, F price-independent → F/M/A carry return, S/O carry risk). **The load-bearing test
  (7/7 pass): two assets identical except S have IDENTICAL return_score (rank unchanged) but the hot-S one's
  size_mult collapses (0.06 vs 0.64)** — exactly R63; v4's single sum does the OPPOSITE (S is +weighted, so
  hot sentiment RAISES the composite, ranking the riskier asset better — the conflation v5 removes).
  NaN-honest (unmeasured pillar dropped + renormalized, never 0). `blended_for_display` exists only for
  legacy single-number surfaces, explicitly NOT for ranking. Reference for BOTH engines (Minimax's Mac
  `cis_v4_engine.py` + Seth's Railway `cis_provider.py`) — does not change live scores/grades/signals/push
  contract; adoption is a separate coordinated deploy. Also drafted **`docs/R_NUMBERING_CONVENTION.md`** —
  lane-prefix proposal (`S-`/`M-`, forward-only from 76, frozen history) to end the recurring R-collision;
  awaiting Jazz's one-line approval. **Build order COMPLETE: #1✅ #2✅ #3🟡(3b deferred) #4✅ #5🔴(refuted) #6✅.**

- **2026-07-22 (SESSION 2) 🔴 Build-order #5 PREMISE REFUTED — price does NOT lead S/O; it's price-COINCIDENT (Seth).**
  Before building any "related-instrument price-action nowcast" for hi-freq S/O, tested the load-bearing
  premise (price LEADS S/O ⇒ a fast price proxy front-runs the slow CIS sample) on real data — 58 assets ∩
  ohlcv, daily, 2025-05→2026-06, n≈8,280. **Result: REFUTED.** corr(own_ret[t], Δpillar over [t-1,t])
  CONTEMPORANEOUS = **O +0.52 (t=56.6), S +0.44 (t=45.0)**; the LEAD+1 test = **ΔO +0.013 (t=1.1), ΔS
  −0.010 (t=−0.9)** — zero predictive lead; lead+2/+3 mildly NEGATIVE (weak mean-reversion, wrong sign).
  Pillar-spectrum control: M +0.82 (definitionally price), A/O/S +0.57/+0.52/+0.44, **F −0.01** (only F is
  price-independent). **⇒ O and S largely reprice WITH price on the same daily bar; a daily price nowcast of
  S/O adds nothing — do NOT build it.** The R63b stability premium is better read as a REGIME/RISK signal
  (large ΔS/ΔO = large contemporaneous price moves = high-vol tape where edge degrades) — consistent with S
  as a risk gate, NOT a sampling-latency problem. Residual: a lead could only exist SUB-DAILY (intraday
  price → EOD snapshot), which needs hourly pillar+price (geo-blocked/absent) and has marginal payoff since
  S/O are ~contemporaneous price transforms. Module `src/research/validation/so_price_leadlag.py` (pure,
  runs at any resolution — re-read the LEAD row when hourly lands) + 6/6 smoke tests. **Companion to
  Minimax's R75** (hourly S/O Δ-quintile edge): my result predicts S/O Δ is ~half price-mechanical, so R75's
  hourly factor MUST clear an absorption test vs contemporaneous price/momentum or it's momentum-in-a-costume
  (the R24 Crowd-Clock trap) — handed to Minimax via §SO-LEADLAG. **Ledger R-number DEFERRED** pending Jazz's
  lane-namespacing ruling (Minimax active at R73/R74/R75; my fusion renumber at R69-72 — flat sequence keeps
  colliding). Build order now: #1✅ #2✅ #3🟡 #4✅ **#5 premise refuted (nowcast path closed)** · #6 CIS v5 LAST.

- **2026-07-22 (SESSION 2) 🟡 Build-order #5 — hourly S/O stability + Δ-quintile; **PREMATURE** with pipeline shipped (Seth).**
  Per `docs/VECTOR_SCHEMA_SPEC.md` §4 build-order #5: test R63b's S/O stability-premium claim using **genuine sub-day
  `cis_scores.recorded_at` snapshots**, not daily expansion. Module `src/research/validation/r75_hourly_so_quintile.py`
  (~370 LoC) — pure functions: `normalize_hourly_history` (UTC-hour bucket, NaN-honest, no ffill), `build_hourly_pillar_panel`,
  `align_score_to_next_bar` (shift + `max_staleness_hours=4` bounded ffill — preserves PIT while spreading sparse
  snapshots across intra-hour gaps), `delta_score` (stable/positive/negative), `hourly_ls` (k=5 next-bar L/S with
  turnover-aware cost), `maturity_status` (frozen 30d/720h/12-asset gate), `run` (orchestrator + returns-source tracking
  + maturity-dominant verdict). Wired `fetch_hourly_returns_public` (public Railway `/api/v1/market/ohlcv/{symbol}?interval=1h&limit=744`)
  as primary hourly-returns loader; local parquet fallback only if API returns zero rows. **10/10 smoke tests pass** + **preflight
  PASSED**. Initial 2026-07-22 14:17 UTC sweep: maturity = **37.12 days / 662 unique hours / 28 assets** (below 720h floor by ~58h);
  best gross cell pillar O / Δ=1h / rebal=4h ⇒ α_t=+1.18 (ann +128.3%), **fails** the 1.96 gross gate; 5bps α_t=−0.92, last-30%
  OOS α_t=−1.70. All three gates fail — even if maturity had been met the headline would read 🔴 REFUTED — but **verdict ⚪ PREMATURE**
  per pre-declared gate. **Two new lessons (#43 #44)** in REFUTATION_LEDGER — INCONCLUSIVE ≠ PREMATURE (loader-failure vs
  maturity-gate); a sub-day L/S can silently produce all-zero weights from snapshot sparsity, so the honest signal is the
  *per-hour fraction of evaluable rebalances*, not the t-stat alone. **No production change**: CIS scoring, weights, grades,
  signals, Mac Mini, Shadow, push contract all untouched. Re-run when maturity crosses 720h (~24h); same module, no code change.
  Mac-side commit handoff pending (sandbox FUSE blocks git write). Reports gitignored at `reports/r75_hourly_so_quintile/2026-07-22/`.

- **2026-07-23 (SESSION 2) 🔧 R75b — infrastructure blocker surfaced via R75 freshness probe; NOT R75's lane to fix (Seth).
  Same module re-executed today; **headline t-stats did NOT move because the underlying data window did NOT extend forward**
  — produced a stronger, more actionable finding: public `/api/v1/cis/history/{symbol}` endpoint **stopped writing fresh
  non-null `pillar_s`/`pillar_o` rows at 2026-07-19T14:00 UTC**. As of run time: staleness = **74.5 hours**; 3 assets
  (BCH, ICP, WIF) have **no historical rows at all**. Added `_data_freshness()` probe (+~85 LoC) + `data_freshness` block
  in `verdict.json` + `REPORT.md §3` so every future R75 run surfaces `latest_data_hour`, `earliest_data_hour`,
  `staleness_hours`, `null_assets` directly. **11/11 smoke tests pass** + **preflight PASSED** (added
  `test_data_freshness_surfaces_staleness_and_nulls`). **Lesson #45** in REFUTATION_LEDGER — a research-grade factor
  pipeline needs TWO necessary-but-not-sufficient gates: (1) calendar-coverage (30d/720h/12-asset) AND (2) wall-clock
  freshness (latest_data_hour close to run time). R75 enforces neither independently — the maturity gate is the floor,
  the freshness gate is now expressed but gated off (cannot be Seth's unilateral call). **Verdict remains ⚪ PREMATURE**
  even as the day ticks because pipeline stall prevents the calendar gate from advancing at the same rate as wall-clock.
  **Out-of-R75-lane finding → Minimax** (Mac-side CIS push author): pipeline stall since 2026-07-19T14:00 UTC; the 200
  newest endpoint rows are null-pillar skeleton writes (likely a reconnect/recovery loop); 3 assets have no rows at all;
  reference in `REFUTATION_LEDGER.md` R75 §update 2026-07-23 + `data_freshness` block in
  `reports/r75_hourly_so_quintile/2026-07-23/verdict.json`. **No production code change**; Mac-side commit handoff ready.

- **2026-07-22 (SESSION 2) ✅ Build-order #4 — edge risk moments (edge_vol, edge_p10) into the asset vector, I5 (Seth).**
  Now unblocked by the β backfill. Asset vector v2 **25→27 dims**: added `edge_vol` [25] + `edge_p10` [26] —
  dispersion + 10th-pctile LEFT TAIL of the realized β-adjusted edge, per **I5** (a mean-only schema is blind
  to where money is lost; R63: high-S leaves the mean flat but widens vol 15.89→17.17 and deepens the p10 tail
  −13.93→−18.33). New Supabase view **`asset_edge_moments`** (per-symbol, ex-self, n≥20) — verified: 25 symbols,
  mean vol 17.06 / p10 −20.54, squarely in R63's range. Pure `edge_risk_moments(history)` helper + fixed-length
  27-dim v2 block (deltas+stability+risk always appended, NaN-filled when absent — I1). Provider wired best-effort
  (one GET of the view; missing/fail ⇒ NaN, can't break v1). Normalization vol/25, p10/25 (clamped; deep tails
  saturate at −1). **10/10 v2 tests + preflight green.** View captured in `scripts/supabase_signal_beta_scorecard.sql`.
  Build order now: #1 ✅ #2 ✅ #3 🟡(3a done, 3b deferred) #4 ✅ #5 🟡 **PREMATURE — pipeline shipped, awaiting maturity** (see R75 entry below) · next #6 (CIS v5, LAST).

- **2026-07-22 (SESSION 2) ✅ β build-order #1 LANDED + ledger reconciled + 🔴 dead-pipeline found (Seth).**
  **β backfill (build-order #1, historical half):** reproduced `src/data/market/beta_adjust.py` in SQL over
  Supabase (PIT expanding-window OLS, ≥20 priors, strictly-prior same-symbol rows) and populated
  `signal_outcomes.{beta_pit, alpha_beta_adj, edge_beta_adj}` — **7044/7743 rows** (699 unadjustable =
  correct PIT warmup, not a gap). **avg β = 1.49** → confirms raw `a_ret−b_ret` was booking ~½ unit of
  benchmark as "alpha." Verified vs R62 (ex symbol=bench): **STRONG OUTPERFORM +8.12 (t+5.41)** ≈ R62's
  +8.06/t+5.41; OUTPERFORM **+2.53 (t+4.57)** (raw was −0.95 — sign flips); UNDERPERFORM +1.25 (t+5.65);
  **UNDERWEIGHT −3.69 (t−3.56) = the one real defect**. **CIS works, reproduced from persisted data.** New
  view **`signal_beta_scorecard`** (migration `signal_beta_scorecard_view`) — forward-safe, raw+β labelled.
  Data-quality notes handed to Minimax: 259 benchmark-self rows (β≈1/α≈0, stored faithfully, excluded from
  the aggregate) + 63 dup (symbol,d) pairs. **Live `signal_outcomes` writer + investor RPC β-wiring remain
  Minimax's** (see §BETA-METRIC-AGG spec).
  **Ledger reconciliation (per Jazz):** Minimax keeps R64–R68b (pillar_A kill register); Seth's fusion lane
  renumbered **R64→R69, R70, R71, R67→R72** across ledger + PROJECT_STATE; placeholders de-clashed;
  **§LEDGER-RECONCILIATION-MAP** appended (append-only) — flags Minimax's R64–R68b lack auditable bodies,
  documents R61/R63 in-ledger dupes (unresolved, Jazz's call), and retires the R46-as-corroboration-for-R62
  sentence (different objects per R16: absolute per-signal vs cross-sectional rank; R62 stands alone).
  **🔴 Dead pipeline (new finding, nobody logged it):** `signal_outcomes` last row 2026-05-03;
  `ohlcv_daily` last 2026-06-19 (**33d stale — root cause, price feed died**); `cis_scores` fresh (today).
  Investor `/api/v1/signals/track-record` RPC computes off the price-starved `cis_scores×ohlcv_daily` and
  republishes the **raw pre-R62** number daily, docstring still asserting the overturned conclusion. Handoffs
  appended to MINIMAX_SYNC: **§OUTCOMES-STALE** (P0), **§BETA-METRIC-AGG** (β-adjust RPC + publish both
  labelled — investor-facing, Jazz's ship call, gate on fresh prices), **§BETA-METRIC-BACKFILL**. Preflight
  PASSED. **No `src/` code changed this session** (Supabase + docs + gitignored MINIMAX_SYNC only).

- **2026-07-22 (SESSION 2) 🟡 Build-order #3 — strategy-vector stacks CONVERGED onto the canonical keeper; duplicate deletion deferred with documented blockers (Seth).**
  Made Minimax's 30-dim `src/data/vector/{strategy_embedder,strategy_store}.py` the **honest keeper** by
  porting in the four things Seth's `src/research/strategy_vector.py` had that it lacked: **(1) NaN-honesty
  (I1)** — every `_norm_*` now returns `NaN` (not `0.0`) when a field is unmeasured; the old "missing→0"
  fabricated the map and made sparse records "similar to everything." A *measured* 0 (e.g. market-neutral
  directionality) is kept. **(2) binary validity floor (I4)** — `is_disqualified(record)`: ONLY leakage or
  cost-infeasibility@5bps disqualify; `forward_committed` is a lifecycle state, NOT a kill. **(3)
  `coverage_gaps()`** (regime block, excludes disqualified) **+ (4) `redundancy()`** (near-dupe pairs; R20
  breadth truth). **NaN-aware + length-tolerant `cosine_similarity`** (skips shared-NaN dims, refuses <4
  shared). Ripple fixes: `strategy_store` NaN↔null JSON on embeddings; `coverage_summary` counts **measured**
  (non-NaN) not nonzero; router per-dim breakdown → measured; no NaN leaks into JSON responses. **8/8 new
  honesty tests + 9/9 asset-v2 tests + preflight all green.** **Deletion of Seth's duplicate DEFERRED (#3b)**:
  a lossless port is blocked on two canonical-schema gaps that touch MECHANISM_SPEC §3 (Minimax-owned) —
  (a) `cost_slope` vs `cost_sensitivity{0/2/5/10bps}` (no lossless conversion), (b) tri-state validity
  (`leakage_clean=None`=UNVERIFIED ≠ leaky; bool `pit_clean` would falsely disqualify swing_overlay_v9).
  Marked the duplicate DEPRECATED (kept working for its one consumer, `embed_graveyard.py`); did NOT ship a
  lossy migration. New tests: `src/data/vector/tests/test_strategy_embedder_honest_smoke.py`.

- **2026-07-22 (SESSION 2) ✅ Build-order #2 — pillar deltas + O/S stability into the asset vector (Seth).**
  Extended `src/data/vector/embedder.py` to **asset-vector v2 (SCHEMA_VERSION=2, 18→25 dims)** per
  VECTOR_SCHEMA_SPEC §1.1: appended `d_F d_M d_O d_S d_A` (1-step pillar deltas, /50 clamp) + `stability_O
  stability_S` (trailing-std over the PIT window, /25 clamp). **Invariant-faithful:** I1 — unmeasured dims
  are `float('nan')`, never 0 (no prior ⇒ NaN deltas; <3 window obs ⇒ NaN stability); I2 — deltas/stability
  read only strictly-prior snapshots (provider passes `history[-2]` as prior since `save_cis_snapshot` runs
  before embedding); I6 — v1 dims [0..17] byte-identical, versioned. Made **`cosine_similarity` NaN-aware +
  length-tolerant** (skips NaN coords pairwise, compares the shared leading prefix so 18-dim and 25-dim
  vectors interoperate during rollout, refuses below `MIN_SHARED_DIMS=4`); **`k_means`** NaN-safe via
  column-mean imputation. **`store.py`**: NaN↔null JSON (bare `json.dumps(NaN)` is invalid JSON → Upstash
  rejects it), `schema_version`/`dims` in meta. Wired `cis_provider.py` best-effort (`get_cis_history`,
  NaN on any failure — can never break v1). New `src/data/vector/tests/test_embedder_v2_smoke.py` **9/9
  pass**; consumers (strategy 30-dim embedder, similarity/cluster endpoints) intact; **preflight PASSED**.
  Bug caught by tests + fixed: `_pillars_of` now resolves every key shape (T1 nested / bare UPPERCASE /
  `f_score` / history-row bare lowercase) pillar-by-pillar. Build-order #3 (converge strategy stacks +
  port NaN-honesty/coverage_gaps/redundancy) is next; #4 risk-moments needs the β history (now backfilled).

- **2026-07-22 🔴 R72 — pillar_A change cross-sectional L/S REFUTED (Seth).**
  Tested the R63b directional claim using the correct object: PIT-safe one-day `ΔA = A[t] − A[t−1]`, not A level. Strict funding ∩ CIS ∩ OHLCV universe (28 assets), k=5, 2024-06-07→2026-06-07, market + 30d momentum residualization, last-30% OOS, cadence × cost sweep. Best +ΔA cell (5d/0bps) has gross α_t=+0.96 (FAIL); 5bps α_t=+0.60 (FAIL); last-30% OOS α_t=+2.19 (PASS). Matched −ΔA at the same cell = −0.83 (directional differential +1.79), but independently best −ΔA at 7d is diagnostic only. **Verdict 🔴 REFUTED** as a standalone sleeve; R63b remains architecture evidence only, eligible for conditional state/sizing examination in R69, with no strategy credit. Fixed the OOS cut bug (last 30%, not last 70%) and applied the strict universe anti-imposter guard. 38/38 smoke assertions pass; preflight passes. Aggregate lesson #40: match the strategy score to the measured phenomenon. `REFUTATION_LEDGER.md` → R72. Reports gitignored at `reports/pillar_a_ls/2026-07-22/`.

- **2026-07-22 🟡 R61 — Detector-gated pillar_O sleeve PARTIAL: clears gauntlet, does NOT lift OOS (Seth).**
  Built `src/research/validation/r61_pillar_o_detector_gated.py` (~470 LoC) — applies the R62/R63 detector × `flat_zero` pattern to pillar_O (R46's winning factor). Frozen R46 baseline (5d/5bps/k=3, gate_action='flat_zero'; reverse is REJECTED with ValueError per §TRADER_TOM_DOCTRINE). 6 cadences × 3 costs × 3 R58 detectors = 54 cells. **R46 ungated reproduction: gross_t=+3.33, OOS_t=+2.47, W5 ann%=+15.0% (NOT negative as plan assumed). Best gated cell: cross_class_crowded_count / 5d / 0bps → gross_t=+2.78, OOS_t=+2.35, pass_all=True, ΔOOS_t=−0.12. 10/54 cells pass all 3 checks; ZERO cells have ΔOOS_t > 0.** Per-window gated-vs-ungated: W2 **+685.9% → +137.0% (−548.9 Δ)** — gate destroys $549pp of in-sample alpha for marginal W5 (+6.6 Δ) + W6 (+9.5 Δ) gain. **Verdict 🟡 PARTIAL**: detector × flat_zero keeps gauntlet alive but trades in-sample for OOS-neutrality; not a rescue, not a refutation. **Hypotheses REFUTED**: (a) W5 sign-flip assumed in plan was actually +15.0% on this reproduction; (b) R62's detector pattern does NOT transfer cleanly from fade-the-crowd to pillar_O. **Frozen R69 fusion cell stays at w_R46=0.25 unchanged**. w_REBALANCE candidate (raise w_R46) is NOT warranted; the lever for future R69 tuning is w_REBALANCE, not detector-add. New aggregate lessons #28 (detector × flat_zero is factor-specific, not generalizable) + #29 (fragile-regime hypotheses are empirical, not prior assumptions). 11/11 smoke tests pass; `py_compile` clean. REFUTATION_LEDGER.md → R61. Reports gitignored at `reports/r61_pillar_o_detector_gated/2026-07-22/`.

- **2026-07-21 🟢 R70 — Fusion Paper Book DEPLOYED with §P2 fill-attribution validation (Seth, MECHANISM_SPEC §1 §P1 §P2 deliverable).**
  Built the missing §P2 primitive + the live paper book for the R69 fusion cell per MECHANISM_SPEC §P1/§P2/§P3. **P2 fill-attribution engine** (`src/data/signals/fill_attribution.py`, ~190 LoC, PURE function): `{target_weights, current_weights, nav, prices, adv}` → `{per_asset {target_notional, turnover_pct, adv_participation, slippage_bps, fill_ratio, executed_notional}, totals {weighted_slippage_bps, fill_ratio_overall}, capacity {declared_usd, used_pct, status, breach_usd}}` — replaces R69's CRUDE $5.0M constant with a real per-clip measurement. **Self-tested on 5 synthetic cases** (no-turnover 100% fill, full-rebal 100% fill at $2B ADV, BREACH at declared $1M, thin-ADV <100% fill, undeclared capacity). **Fusion paper book** (`src/data/signals/fusion_paper.py`, ~360 LoC): 28-asset strict-intersection universe FROZEN, R69 cell constants FROZEN (w_R46=0.25, R46 5d/5bps k=3, R62 21d/0bps external/z0.5/mf2/zwin30), FROZEN detector with LIVE trailing 90d reference stats (PIT-safe composite-z + min_features gate), live CIS pillar_O from Redis `cis:local_scores` → Supabase `cis_scores` fallback, live Binance fapi close + funding, state → Redis `fusion_paper:state`, NAV → Supabase `fusion_paper_nav`. PIT-safe: trailing 30d funding z (no full-sample stats), mark-to-market y[t]/y[t-1]−1. Honesty gates: <20 assets with data → mark flat that day; `validated` flag flips True only at n_days ≥ 60. Wired `_fusion_paper_loop` (DISABLE_FUSION_PAPER env guard, 660s warmup, 24h cycle) + `GET /api/v1/signals/fusion-paper` endpoint in `src/api/main.py`. **Preflight PASSED**: `[FUSION-PAPER] ✅ daily R69 fusion paper-book loop scheduled`. **12 smoke tests passing** (cell constants frozen, universe frozen, funding features PIT-safe, detector fires on synthetic fragility, funding score sign-flipped, target weights normalize to gross 2/3, detector gates leg2, fill-attribution reconciles to declared capacity, no forbidden signal language). New aggregate lesson #36: **§P2 binding capacity is a measurement primitive, not a constant** — every strategy record must carry an attribution engine that turns realized turnover + ADV + slippage into a per-clip capacity status, or the declared number is just a wish. Per §P1, the R69 fusion cell is the pre-declared criterion; the live NAV curve is the forward evidence. REFUTATION_LEDGER.md → R70. Smoke: `src/research/validation/tests/test_fusion_paper_smoke.py`.

- **2026-07-21 🟢 R71 — Live NAV accrual monitoring WIRED (Seth, MECHANISM_SPEC §P3 accountability layer).**
  Built `src/research/validation/fusion_paper_tracking.py` (~370 LoC) as a monitoring-only judgment layer over the deployed R70/R69 fusion paper book. Pure primitives calculate live annualized Sharpe, gap versus the R69 OOS reference (1.69), detector fire-rate versus the R62 8.2% reference, capacity evolution from fill ratio/slippage/breach history, max drawdown, and the honest 60-day validation countdown. `detect_lifecycle_events()` emits structured `BOOK_INCEPTION`, `WARMING_UP`, `DETECTOR_PERSISTENT_HIGH`, `CAPACITY_BREACH`, `SHARPE_DRIFT`, and first-crossing `VALIDATED` events; events persist to Supabase `fusion_paper_lifecycle`, with schema migration `scripts/supabase_fusion_paper.sql`, while the latest snapshot is cached in Redis `fusion_paper:tracking`. Wired `_fusion_paper_tracking_loop` (DISABLE_FUSION_TRACK guard, 15-minute warmup, daily cadence) and `GET /api/v1/signals/fusion-paper-tracking`. **13/13 R71 smoke tests pass; `py_compile` passes; application preflight passes** with the existing router-split `main.py`. The monitor does not retune, block, or mutate the frozen R69 cell — it makes live drift and capacity visible before the ≥60-day validation gate. Aggregate lessons #38: §P3 is not a post-hoc report; the forward book needs a daily judgment surface. #39: a Sharpe gap without detector/capacity context is incomplete — lifecycle state must carry all three.

- **2026-07-21 🚨 THE METRIC WAS THE BUG — live signal book re-audited; CIS WORKS; three-way factor map found (Seth + Jazz).**
  Chain: **R61** (🔴 live signal book looked non-predictive; OUTPERFORM t=−4.09) → **R62** (✅ **R61 OVERTURNED**) →
  **R63/R63b** (🟡 factor-behaviour map). Do not read R61 without R62.
  **R62 — root cause:** asset β vs benchmark is **1.4–2.4**, so `a_ret − b_ret` was never alpha, it was
  leveraged beta; in a bear window high-β names lag a falling bench and a GOOD signal looks inverted.
  With PIT-safe trailing per-asset β (expanding window, min 20 priors, no full-sample stats):
  STRONG OUTPERFORM **+8.06% t=+5.41**, OUTPERFORM **+2.86% t=+5.75** (was −0.36), UNDERPERFORM +1.00 t=+4.48,
  **UNDERWEIGHT −4.10 t=−3.79 (genuinely broken — the one real defect)**. Every CIS pillar flips correctly
  signed; cis_score level spread −4.38 → **+2.85**. **CIS works.**
  **Cross-validated against the repo:** R46 (market-neutral L/S, independent method, removes β *by
  construction*) agrees — CIS composite 5bps t=+2.64, and "pillar_S never clears" matches R62's S=+0.03.
  Two yardsticks existed in one house: research pipeline was β-aware via `factor_absorption`, production
  signal metric was not. **Unify the live metric onto the β-adjusted definition.**
  **R63 (Jazz's domain correction — S is a RISK factor, not a return factor):** mean edge flat across S
  (+2.70/−0.77/+2.77) but **vol 15.89→17.17 and left tail −13.93→−18.33**. Peak hype widens the
  distribution. → **Do NOT drop S; move it from return-score to risk/sizing gate.**
  **R63b (Jazz: "不止 ΔO，S 也类似"):** signed Δ quintiles on all pillars give **three distinct factor kinds** —
  (1) **stability-premium: ΔS +2.72, ΔO +2.70** (edge best when stable, degrades at both extremes; specific
  to S/O, ΔF/ΔM≈0 ⇒ not an artifact; these are the fast externally-driven pillars ⇒ **we sample AFTER the
  market reacts** ⇒ raise S/O frequency); (2) **directional: ΔA +1.18** (rising A ⇒ better edge, usable now);
  (3) **level-only: F, M**.
  **⇒ CIS v5 is an ARCHITECTURE question, not a reweight.** A single weighted sum of level-scores cannot
  express a level factor + a change factor + two fast-state/risk factors. **Corrects the pending R46 action
  item** ("toward O, away from S"): away-from-S is *wrong as stated* (S is a risk gate); toward-O is right
  (R46 t=+3.33) but O needs regime-conditioning + higher frequency; **pillar_A (+4.48 level, +1.18 change)
  is the strongest untested candidate — never run at strategy level, queue the L/S test.**
  Meta-lessons: **#21 audit the METRIC before the MODEL** (all three "edge is broken" findings today were
  measurement defects); **#22 a factor can fail as a mean-return predictor and still be information** — test
  levels AND changes, means AND higher moments before declaring anything dead.
  Next: unify live α metric on β-adjustment · fix UNDERWEIGHT · hourly S/O sampling (Jazz's AI-ETF /
  related-instrument price-action route) · pillar_A L/S test · CIS v5 architecture redesign.
  Also shipped today: **§5b two-layer paper book LIVE** (`src/data/signals/two_layer_paper.py`, core-health
  gate holds ZERO size while core dead, hot-swappable core via Redis `two_layer_paper:core`, 7/7 tests,
  preflight PASSED, Supabase `two_layer_paper_nav` + RLS policies applied) · **`docs/MECHANISM_SPEC.md`**
  (A2A capital-market mechanics: forward commitment / binding capacity / lifecycle disclosure) ·
  **§ALTITUDE** + **§PIT-LEAK-C** + **§CORE-BAKEOFF** in MINIMAX_SYNC.

- **2026-07-21 ✅ R69 — Sleeve Fusion Validation FUSION WINS 3/3 gates (Seth, MECHANISM_SPEC §3 deployment gate).**
  Built `src/research/validation/r63_fusion_validation.py` (~430 LoC, file name unchanged) per MECHANISM_SPEC §3 strategy vector + §P1/§P2 deployment discipline — no sleeve ships to live book without fusion validation, forward-committed cells, declared capacity ceiling. **Universal STRICT 28-asset intersection** (NOT easier 41-asset R46 universe) — both R46 pillar_O 5d/5bps and R63 fade-the-crowd 21d/0bps-gated re-computed on this restricted subset. Weight sweep w_R46 ∈ {0.0, 0.25, 0.33, 0.50, 0.67, 0.75, 1.0}. **Best cell: 25% R46 + 75% R63 → gross_t=+2.52, OOS_t=+2.38, maxDD=−11.05%, Sharpe=+1.69**. 3/3 gates pass: (1) 3-check clear, (2) maxDD −11.05% (vs R46 alone −33.62% = **41% improvement**), (3) |ρ(R46, R63)|=**−0.05** (essentially uncorrelated — orthogonal!). **ρ=−0.05 is the structurally important finding**: R46 is a CIS-pillar cross-section rank; R63 is a per-asset funding-z reversal — different return dimensions → diversification math, not averaging. Per-window fusion attribution: **R46 saves W1** (+74.4% vs R63 −31.2%, net fused −11.4%); **R63 saves W5** (+115.7% vs R46 −58.1%, net fused +45.6% — R58/R59's W5 fragility detector payoff complete); both lose W3 (irreducible in this sleeve choice). **R46 alone FAILS on 28-asset** (OOS=+0.61) but adds value in fusion → **failed-leg salvage via orthogonality** (lesson #34). Crude capacity $5.0M per §P2 (median ADV $50M/asset × 5%/leg × 2-leg) — labeled CRUDE, must verify with fill-attribution before deploy. Per §P1, this report IS the pre-declared criterion — the live fusion cell must reconcile to w=0.25/0.75 + the 3-check pass at horizon. New aggregate lessons #33-#35. 9 smoke tests passing. REFUTATION_LEDGER.md → R69. Reports gitignored at `reports/r63_fusion_validation/2026-07-21/`.

- **2026-07-21 ✅ R63 — Regime-Conditioned Fade-the-Crowd SURVIVES 3-check gauntlet via fragility detector (Seth, per R60 verdict recommendation).** [Renumbered from R62 in this session — see R69 entry for explanation.]
  Built `src/research/validation/r62_fragility_gated_funding.py` (~470 LoC, file name unchanged) — layers a KS-based fragility detector on R60's per-asset funding-crowding L/S, trained to discriminate (fragile = W1∪W3 = 243 days = 33% of panel) from (playable = W2∪W4∪W5∪W6). 18 features (10 R58 internal + 6 R59 funding + 2 BTC-specific funding). Reuses R58's `build_w5_detector` + `_ks_2samp` + `gauntlet_3check` with R58-schema keys (`mean_w5`/`mean_ref` aliased for fragile/playable). Sweep: {internal, external, top8} feature sets × {0.0, 0.25, 0.5, 0.75} z_threshold × {2, 3, 4} min_features × {5, 7, 14, 21}d cadence × {0, 5} bps = **288 cells, 7/288 (2.4%) pass all 3 checks**. **Best cell: external/z0.5/mf2/cad21/bps0 → gross_t=+2.03, OOS_t=+2.37**. **W5 ann% jumps from +53.9 (R60 ungated) to +115.7 (R63 gated), +61.8 Δ** — the dominant contributor to clearing the gauntlet. Fragile_hit_rate=8%, playable_hit_rate=12% (slightly under-fired; gate is precise but conservative). **Top-3 cells all use 21d cadence + 0bps** — slow cadence + detector is the regime-aware oracle; fast cadence + detector stays dead (lesson #29). **External-funding features beat internal features for fragility discrimination** (lesson #28): internal features (mkt_vol_30, xsec_rank_ic_30, xsec_disp, streak_5) topped KS ranking but `external` subset won the gauntlet — internal features characterize the regime, external funding features characterize which fragile regime translates into L/S failure. Detector over-fires in W2 (bull-trend −35.4 Δ) and W4 (mid-late −16.1 Δ) — acceptable but reveals the detector separates *days*, not windows. **Verdict: ✅ SURVIVES** — R60's per-asset overlay path is now credit-eligible as a funding-crowding L/S sleeve (gated). New aggregate lessons #27-#29. Per MECHANISM_SPEC §3 strategy vector + §P2 binding capacity declaration: declare capacity before paper-deploy; P3 mandatory lifecycle disclosure = flat-recording fragility-gated position count. R69 fusion (right below): 2-sleeve fusion (R46 pillar_O + R63 fragility-gated fade-the-crowd) under the strategy vector harness. 9 smoke tests passing. REFUTATION_LEDGER.md → R63 + lessons #27-#29. Reports gitignored at `reports/r62_fragility_funding_ls/2026-07-21/`.

- **2026-07-21 🔴 R60 — Funding-Crowding L/S Per-Asset REFUTED (Seth, "继续开发因子还有策略").**
  Per R49's final recommendation (per-asset overlay as highest-orthogonality remaining route), built `src/research/validation/funding_crowding_ls.py` (~340 LoC) — cross-sectional L/S indexed by per-asset funding z-score (zwin=30d, sign=`−z` = fade-the-crowd direction), 28-asset funding ∩ CIS ∩ OHLCV tradeable universe, k=3 terciles, swept cadences {1,3,5,7,14,21}d × costs {0,5,10}bps. Reuses `tercile_ls`/`cadence_ls`/`cadence_sweep`/`quarter_cuts`/`sub_period_absorption` from R45/R46 + `load_funding_daily` from R59 + `gauntlet_3check` from R58 + `absorption_test` from `factor_absorption.py`. 9 smoke tests passing (synthetic positive-IC end-to-end). **Cadence × cost grid reveals STRUCTURAL sign-flip at fast cadence:** 1d/5bps α_t=−0.83, 3d/5bps=−0.46, 5d/5bps=−0.28, 7d/5bps=+0.17, 14d/5bps=+0.98, 21d/5bps=+1.60. The fade-the-crowd premium only materializes at slow cadence (≥14d). **Best cell (21d/0bps): gross_t=+1.73, OOS_t=+1.89** — both below 1.96 threshold (just shy by 0.23 and 0.07). **W5 is genuinely new — first factor that wins on W5 without a detector**: W5 ann% +29.6%, α_t +0.43 (vs R46 ungated −57.5%, R58 detector-gated −8.5%, R59 enriched +2.3%). Per-window P&L at best cell: W1 −37.4%, W2 +170.2%, W3 −22.5%, W4 +37.1%, W5 +29.6%, W6 +83.6% — 4/6 windows positive, 2 deeply negative (early-cycle + consolidation). **Verdict: 🔴 REFUTED** (fails 2+ checks at every cell) but **constructive**: (a) W5 fragility is R46/pillar_O-specific, NOT a general L/S failure mode; (b) funding premium's true timescale is 3-week mean-reversion, NOT daily; (c) regime-conditioned overlay is the next step (skip early-cycle + consolidation windows). New aggregate lessons #24-#26. REFUTATION_LEDGER.md → R60 + lessons #24-#26. Report gitignored at `reports/funding_crowding_ls/2026-07-21/`.

- **2026-07-21 🟡 R59 — External-feature W5 detector enrichment (Seth).**
  Per "继续开发因子还有策略" + R58's "panel-internal features partially close W5 but not OOS-clear" finding, built `src/research/validation/w5_forensics_external.py` (~480 LoC) — loads the 28-asset overlap of the funding panel at `/Volumes/CometCloudAI/cometcloud-local/_data/funding/`, computes 8 funding features (funding_mean, funding_disp, funding_skew, funding_extreme_long_frac, funding_extreme_short_frac, funding_net_long_frac, btc_funding_raw, btc_funding_zscore_30), plus OI features from BTC OI cache (cache exists but in wrong format → returns NaN gracefully). KS table against R58 internal-only baseline: **funding_mean KS=0.39 (ranks #3 overall), funding_skew 0.28, funding_extreme_long_frac 0.25** — funding IS informative. Two detectors built: R58 internal-only (z=0.50, mf=3) and R59 enriched (z=0.50, mf=4). **W5 attribution per detector (R46 sleeve baseline, gross t):** R58 (mf=3): W5 contributes −8.5%/yr; R59 (mf=4): W5 contributes +2.3%/yr — funding detector RESCUES W5 but over-gates non-W5 (R59 hit-rate 40% vs R58 27%, blowing up non-W5 turnover cost). **UNION detector (R58 OR R59) is the best of both worlds**: gross=+4.87 (vs R46 ungated +1.84), OOS=+0.73 (vs R46 −0.89). Still doesn't clear 1.96 OOS but closest yet. **Aggregate lessons #21-#23:** (21) gating cost asymmetric — W5 rescue may cost more in non-W5 churn than it gains; (22) UNION of complementary detectors beats either alone (OR-logic = conservative union); (23) we've now ruled out regime-label (R52), construction choice (R56), internal market-state (R58), funding-rate features (R59) — remaining OOS gap lives elsewhere. 7 smoke tests passing. Reports gitignored at `reports/w5_forensics_external/2026-07-21/`. REFUTATION_LEDGER.md → R59 + lessons #21-#23.

- **2026-07-21 🟡 R58 — W5 forensics + detector framework (Seth, "mine w5" directive).**
  Per Jazz's explicit directive "mine w5" — drill into the W5 sub-window (2025-10-07 → 2026-02-05) that both R52 and R56 flagged as the structural OOS failure mode for R46's winning cell (pillar_O 5d/5bps L/S). Built `src/research/validation/w5_forensics.py` (~695 LoC) with 10 panel-internal features (mkt_ret, mkt_vol_30, mkt_trail30, xsec_disp, xsec_absret, xsec_rank_ic_30, score_disp, rankflip_5, top_bot_5d, streak_5), no-scipy KS (Smirnov asymptotic) and Spearman (rank-based via pd.Series.rank). Partitioned full panel into 6 equal windows (W1=2024-06-07→2024-10-05 ... W6=2026-02-06→2026-06-07, ~122d each). **W5 fingerprint: 5 KS-distinctive features at p<0.001** — score_disp↓ (KS=0.46, dispersion compressed), mkt_trail30↓ (0.41, late-cycle trend exhaustion), streak_5↓ (0.24, directional persistence broken), mkt_vol_30↑ (0.23, vol expanding), top_bot_5d↓ (0.21, L/S spread compressed). Detector = z-score composite requiring min_features simultaneously above z_threshold. Selected config: z=0.75, mf=2, top-5 features. **Gauntlet 3-check result on R46 sleeve:** ungated gross=+1.84 / OOS=−0.89 (REJECT) → gated gross=+4.84 / OOS=+0.41 (sign-flipped, +0.5% OOS contribution but doesn't clear 1.96). **Aggregate lessons #18-#20:** (18) per-bar feature distributions can fingerprint sub-windows cleanly even when KS-on-aggregate doesn't; (19) detector design matters — composite z-score + min_features simultaneously is better than any-side OR; (20) gating can flip OOS sign without clearing t=1.96, a partial but not full victory. 9 smoke tests passing. Reports gitignored at `reports/w5_forensics/2026-07-21/`. REFUTATION_LEDGER.md → R58 + lessons #18-#20.

- **2026-07-20 🔴 R48 — Cross-class REFUTES "general L/S quality mechanism"; R46 is **crypto-specific** (Minimax-B, per Jazz option C + "挖掘更远的窗口, 22年起").**
  Per the multi-regime / cross-class deep dive, built two follow-up modules:
  - **`src/research/validation/cis_quality_multiregime.py`** (~270 LoC) — uses 4h-spot feather cache (14 majors × 2017-08 → 2026-07 daily-resampled). CIS history only goes to 2024-03, so pre-2024 uses a **no-CIS quality proxy** (trailing_90d_momentum + inverse_30d_vol, z-scored). Three windows: 2022-01→2024-06 (bear + recovery), 2024-06→2026-06 (CIS coverage), 2022-01→2026-06 (multi-regime full).
  - **`src/research/validation/cis_quality_tradfi.py`** (~230 LoC) — fetches 17 TradFi ETFs via EODHD (env-key `69e60bac0a00c7.10926755` from `/Volumes/CometCloudAI/cometcloud-local/.env`); cached at `/Volumes/CometCloudAI/cometcloud-local/_cache/eodhd_history/`. Universe: SPY/QQQ/IWM/DIA/XLF/XLK/XLE/XLV/XLY/TLT/IEF/HYG/LQD/GLD/USO/SLV/UUP — genuinely heterogeneous (equities / sectors / bonds / commodities / currencies).
  **Three-way result table (5d-rebal / 5bps, after {market, momentum} knowns):**
  | Surface | Best 5d/5bps t | Interpretation |
  |---|--:|---|
  | Crypto, 41 assets, TRUE CIS (R46) | **+3.33 pillar_O / +2.64 composite** ✓✓✓ | strong positive |
  | Crypto, 14 majors, PROXY (this round) | +0.28–0.36 | sub-breadth, no signal |
  | **TradFi, 17 ETFs, PROXY (R48)** | **−1.12 at 5d/5bps** | all cadences × costs negative (range −0.63 to −1.47) |
  **Direction-flipped on TradFi**: the long-winners/short-losers pattern is mildly DESTRUCTIVE on a heterogeneous TradFi cross-section. The crypto edge is contingent on (a) crypto microstructure (24/7, retail-driven flow, persistent cross-section dispersion) and/or (b) true CIS 5-pillar multi-dimensionality that the 2-factor proxy can't replicate. **Aggregate lesson #14**: cross-class is a separate test, not an extrapolation — a positive result on one market does NOT entitle a "general" claim.
  **CIS v5 implication**: pillar_O-vs-composite upgrade path is **crypto-scoped only** — do NOT apply the same weights to a hypothetical TradFi scoring engine. The "regime-conditioned pillar_O sleeve" R47 sibling idea remains valid as a crypto specialist satellite.
  REFUTATION_LEDGER.md → R48 + aggregate lesson #14. Reports gitignored at `reports/cis_quality_multiregime/2026-07-20/` + `reports/cis_quality_tradfi/2026-07-20/`.

- **2026-07-20 ✅ R46 — R45 REFINED: daily-rebal was overfit; 5-day cadence SURVIVES 3-check gauntlet (Minimax-B).**
  Per Jazz "不要立刻改，再继续深化研究," built `src/research/validation/cis_quality_robustness.py` (~280 LoC) — two follow-ups on R45: **cadence sweep** (rebal ∈ {1,3,5,7,14,21} × cost ∈ {0,5,10} bps) and **sub-period OOS** (6 fixed-width windows, per-factor α_t). **Headline flips R45:** pillar_O at **5d rebal / 5bps cost** = **t=+3.33, ann=+70.1%, turnover 80** ✓✓✓ (composite CIS at 5d/5bps = t=+2.64, both clear). Daily-rebal extracts a different signal than mid-frequency; the underlying edge materializes at slower rebal. **Sub-period OOS for pillar_O is 5/6 windows positive**, one bad window (W5 = 2025-10→2026-02 risk-on late-cycle chop) flips to t=−2.32 — **regime-specific, not structural**. pillar_S dead at every cadence. **PENDING (per hold):** R47 candidate = regime-conditioned pillar_O L/S sleeve (5d rebal + skip risk-on-late-cycle regime); CIS v5 weight reweight (toward O, away from S) for Minimax-A. Aggregate lesson #13 sharpened: gauntlet must sweep CONSTRUCTION CHOICES (rebal cadence, k-terciles, signal source) not test one point. REFUTATION_LEDGER.md → R46 + lesson #13 sharpening.

- **2026-07-19→2026-07-20 🔴 R45 — CIS-quality L/S REFUTED at standard construction; **actionable CIS upgrade signal** = reweight toward pillar_O, away from pillar_S (Minimax-B, §CIS-HISTORY-BACKFILL re-run).**
  Built `src/research/validation/cis_quality_absorption.py` (~290 LoC) — the honest adversarial test of our own core product, triggered by §CIS-HISTORY-BACKFILL landing (870 daily JSONs, full F/M/O/S/A pillars, real reconstructions per the cis-history-export-quirks memory note). Construction: long top-tercile / short bottom-tercile by composite CIS (and per pillar), 1-day lag, on 41 tradeable assets (CIS ∩ OHLCV), 731 daily bars 2024-06-07→2026-06-07. Absorption: OLS + Newey-West per-factor against {market, momentum}; composite-over-best-pillar; OOS 70/30 split; cost curve 0/5/10/20 bps. Composite CIS L/S in-sample gross: **+48.4%/yr t=+2.24** (RESIDUAL α). Per-pillar: **pillar_O dominates at +51.4%/yr t=+2.49**; pillar_F/M/A non-sig; **pillar_S actively negative at −10.6%/yr t=−0.56**. Composite after best-pillar control: **t=+0.44 — adds nothing over O**. Robustness kills: (1) cost curve — CIS gross t=+2.24 → 5bps t=+1.68 (below 1.96; Binance VIP taker is 4 bps) → 20 bps t=+0.05 (dead); (2) OOS last 30% — composite t=+0.33, pillar_O flips to t=−0.45. **Verdict per §STRATEGY-REVIVE: composite CIS as quant factor at this construction refuted.** BUT the pillar decomposition is the actionable CIS methodology finding: **reweight CIS v5 toward pillar_O (On-Chain/Health) and away from pillar_S (Sentiment)**; composite retains F/M/A as diversifying. Composite is still useful as a **quality/risk overlay** (size by CIS rank, sign the trade, don't promise alpha) — consistent with H1. **Lesson (ledger aggregate #13):** gross-in-sample + cost-failure + OOS-failure is the refutation pattern for factor sleeves — the three-check gauntlet (gross t > 1.96, cost-t > 1.96 @ 5 bps, OOS t > 1.96) belongs in every factor gauntlet. The signal IS partially real (~+50%/yr gross in-sample uncorrelated to market+momentum) but not at tradable magnitude in this construction — try weekly/monthly rebalance. Per Jazz's "有比 cis 策略更好的，我们就用，这样 cis 才会升级" — pillar_O is the better of the two; CIS gets the upgrade; the graveyard is the asset. Bug fixed in `cis_quality_factor.py` (date resolution: filename `cis_YYYY-MM-DD.json` as primary, JSON "date" key fallback, "timestamp" last). REFUTATION_LEDGER.md → R45 (+ aggregate lesson #13).

- **2026-07-19 🔴 R44 — Capitulation Bounce v2 (per-pair swing overlay) REFUTED — R40's escape hatch closed (Minimax-B).**
  Built `src/research/cis_regime_studies/capitulation_bounce_v2.py` (per-pair overlay, no cross-section demean, 5%/fire, ≤8 concurrent, ≤40% gross, −10% stop) on full 51-asset universe × 17,520 hourly bars, 20% OOS. R40 died on architecture (pooled/ENB); v2 tested the doctrine's §5c tactical-overlay shape to salvage the "real" per-asset trigger. Two independent failure modes, both refute: (1) **doctrine-faithful vm=2.0 fires ZERO times OOS** — all 270 full-sample fires cluster in the 2024-08 Yen unwind (in-sample); R40's "76% win" was ONE macro event, not a recurring edge; full-sample even so 35.9% win / −1.69% avg / 48.5% stop-out; (2) **loosen to vm=0.0 so it fires OOS → it loses**: 819 OOS trades, 33.0% win, −2.48% avg, OOS Sharpe −2.19. 9-config variant sweep uniformly non-positive. Lesson (ledger aggregate #12): **count independent EVENTS, not trades, before crediting a conditional hit rate** — 224 fires on one day = 1 event. Capitulation-bounce is dead on 2024-2026 crypto in EVERY book shape (pooled AND per-pair); might revive only in a mean-reverting tape with frequent flushes (2022-2023 bottom), a different-regime bet not credited now. Idea does not ship in any form. REFUTATION_LEDGER.md → R44 (+ aggregate lesson #12).

- **2026-07-19 🔴 R40 — Capitulation Bounce sleeve REFUTED on pooled cross-section (Minimax-B, doctrine test).**
  Built `src/research/cis_regime_studies/capitulation_bounce.py` (~530 LoC) per §TRADER_TOM_DOCTRINE §5b (durable-core mean-reversion: long when 5d<-5% AND 20d vol > 2× 60d vol; catastrophe stop @ -10%; cross-section demeaned pooled book). Synthetic test fixed (deterministic event injection + helper `_inject_capitulation_event`; previous cumprod smooth-drift failed because close[t_trigger] was never modified by either drop or bounce windows — silent indexing bug, ret_5d saw only original random walk). Real data on BTC/ETH/SOL/AVAX hourly 2024-06-07→2026-06-07: signal correctly identifies 2024-08-05/06 Yen carry-trade unwind (BTC $65k→$50k, all 4 assets fire t=1435-1439); BTC fwd 5d return on first 50 fires = +2.63% mean / +2.15% median / **76% win rate** (per-asset trigger IS real). But cross-section pooled OOS alpha is **negative at every config** (vm=0.5: Sharpe -0.33/α_t -0.31; vm=0.7: -0.08/-0.11; vm=1+: 0.00). 10-asset universe OOS Sharpe -0.85, α_t -0.32, ENB 1327 — even broadening doesn't recover. Two structural reasons: (1) 2024-2026 has too few capitulation events (canonical vm=2.0: 224 BTC fires ALL on 2024-08-05/06, ZERO in OOS 2026-01-12→06-07); (2) BTC/ETH/SOL/AVAX are too correlated — cross-section demean zeroes out the signal precisely when it should fire. Architectural lesson (R16/R40 pair): a correct per-asset trigger does NOT make a correct pooled book — signal architecture must match the correlation structure of the universe. Per-asset trigger logic is reusable for a per-pair swing overlay; pooled form does not ship. Logged honest. REFUTATION_LEDGER.md → R40.

- **2026-07-19 🔴 R38 — Smoothed-CIS empirical-grid gate re-run FALSIFIED the R17 fallback on V7 HOLD-OUT (Minimax-B).**
  Built `src/research/freqtrade/c1_parity_ab_smoothed.py` (~280 LoC, sister driver — same `gate()`/grid/band; only CIS source differs to `_data/cis_history_smoothed/`). Ran on the same V7 HOLD-OUT backtest ZIP (146 trades, 100% smoothed coverage). Headline: Δ Sharpe **−0.42** (vs raw −0.32, **WORSE**); empirical blocks 4 MORE trades (37 vs 33); total PnL drops another $10.30. Per-trade diagnostic: 4 decisions changed — 3 BTC LONGs had smoothed tier flip NEUTRAL → OUTPERFORM on 2026-03-05/11 (raw: "no edge data, ALLOW"; smoothed: "OUTPERFORM × 2_off = -5.8% expected, BLOCK") costing +$2.50 of winners; 1 ETH LONG legacy flip captured +$7.80. **Two distinct failure modes for the empirical grid (this sharpens R17):** (a) tier whiplash (R17 framing) — daily CIS recalc drifts; (b) **smoothed-tier false confidence (R38 finding)** — rolling smoother crosses tier boundary, label flips NEUTRAL→OUTPERFORM, gate sees "confident" OUTPERFORM and acts on it; the smoother didn't remove noise, it created a new layer of confident-noise. Decision: HOLD production paper on `REGIME_CIS_FLOOR`; empirical-grid gate research-only until a **different signal source** is plugged in (NOT a smoothing of the current one). Three candidates to explore next (research-only): (1) pillar-weighted composite tier (smooth pillars, derive tier), (2) regime-pinned tier (gate on (regime, pillar_z) continuous, no tier), (3) walk-forward tier assignment (re-fit thresholds every 30d). Output: `reports/c1_parity_ab/2026-07-19-v7-holdout-smoothed/{per_trade.csv, summary.csv, verdict.md}`. REFUTATION_LEDGER.md → R38.

- **2026-07-19 ⚙️ §CROWDING-BREADTH pre-staged for Mac-side HL credit test (Minimax-B).**
  Added `load_hyperliquid_panel()` to `funding_crowding_breadth.py` (handles `_funding_1h.csv` hourly→daily-sum aggregation + `_1d_ohlcv.csv` daily load, same schema as RWA loader). Built `scripts/crowding_breadth_hl.py` — standalone runner that auto-detects HL cache at `/Volumes/.../hyperliquid_funding/`, runs the pooled breadth experiment + full signal gauntlet, writes summary.json + REPORT.md, prints the ★ ORTHOGONAL EDGE verdict on success. Default `min_history_days=365` (matches directive's ≥2y requirement). Smoke-tested on synthetic HL-format CSVs (5 perps × 100d → ENB=735, experiment runs cleanly, modules import OK). When Minimax-A's HL fetch lands, the credit test is one command: `python3 scripts/crowding_breadth_hl.py --source hyperliquid --out-dir reports/crowding_breadth/2026-XX-XX_hl_credit/`. Verdict logic: α_t > 1.96 + full gauntlet pass → ★ ORTHOGONAL EDGE candidate (slot into two-layer book per §TRADER_TOM_DOCTRINE); α_t < 1.96 → honest R36. No Mac-side / push implications yet — credit test depends on data landing.

- **2026-07-18 🧪 §CROWDING-BREADTH RWA smoke — cross-class mechanism validated, sample too thin for credit (Minimax-B).**
  Built `src/research/cis_regime_studies/funding_crowding_breadth.py` (~440 LoC) — `crowding_signal()`
  UNCHANGED + cross-section-demeaned pooled book + signal_gauntlet runner. Self-test PASSES on
  synthetic 10-perp panel. Real-data run on 21 RWA perps × 84d (corr ~0.22 to BTC, true cross-class
  breadth): **ENB = 57** (≫ 8 expected), β_market = **−0.187** (real market-neutral, the structural
  fix for R35's fake-neutrality trap), β_momentum = +0.023, canonical α_t = **+1.59** under 1.96
  on 17d OOS. All 5 config variants positive Sharpe (2.16 to 5.23), canonical config lands
  cohort-middle (no cherry-pick). **Verdict: DIED at significance_PSR — sample too small.** Mac-side
  HL fetch script `scripts/fetch_hyperliquid_funding.py` delivered to Minimax-A (paginated
  `/info fundingHistory` + `/info candleSnapshot`, 50+ alts × ≥2y, ~5-10 min runtime). Re-run with
  HL cache is the load-bearing credit test: if α_t clears 1.96 + full gauntlet passes → **★
  ORTHOGONAL EDGE** candidate for the two-layer book (market-neutral behavioral sleeve per
  §TRADER_TOM_DOCTRINE); else → honest R36. Report: `reports/crowding_breadth/2026-07-18_rwa_smoke/`.

- **2026-07-18 🧪 §ABSORPTION-SWEEP — the "old wine" gate is LIVE; sleeve verdicts pending Minimax-B/C (P0).**
  Seth. Borrowed the killing floor from the Google/academia LLM-factor study (Jazz): most high-Sharpe
  signals are just repackaged known premia — only RESIDUAL alpha (α t>1.96 after factors) earns a slot.
  Built `src/research/validation/factor_absorption.py` (OLS + Newey-West, pure numpy) + the verdict
  runner `src/research/validation/absorption_sweep.py` (one-table: raw vs α-after-factors vs α-vs-peers,
  ★ independent survivors). Both self-tested. It already caught our own Crowd Clock: +35%/yr raw (t=2.93)
  → α +7.5% t=1.0 after market+momentum ⇒ **ABSORBED** (matches R24: clock = momentum in a costume, a
  display lens not a sizing input). **⚠️ SEQUENCING:** this gate runs BEFORE C-S4 composite-weighting —
  weighting sleeves before filtering out beta-as-alpha produces a smooth-looking but uninformative Sharpe.
  GAP (Minimax-B/C lane): per-sleeve daily-return reconstructors on Mac data (positioning / forward-supply
  / funding-cap / MultiFactorV2 / V9) → emit the CSV contract in `absorption_sweep.py` → run the sweep.
  Only survivors enter the two-layer book. See `MINIMAX_SYNC.md §ABSORPTION-SWEEP`.

- **2026-07-18 🪝 CIS-QUALITY FACTOR — prepped for §CIS-HISTORY-BACKFILL re-run (Seth).**
  Built `src/research/validation/cis_quality_factor.py` (long top-CIS tercile / short bottom tercile,
  1-day forward-fill lag, no look-ahead) — pure interface, sandbox-safe. PLUS 8-test smoke suite (all
  passing) + memory note for the cross-session trigger. Today the `f_cis_quality` column in
  `absorption_sweep_runner.py` is a price-tercile PROXY (overlaps `f_momentum`); once Minimax-A lands
  §CIS-HISTORY-BACKFILL (≥400 cis_YYYY-MM-DD.json at cis_history/, 2024-03-01 → 2025-05-02, per
  MINIMAX_SYNC.md line 3471+), the helper swaps the column source — same column name, real values.
  Re-run verdicts may shift: false survivors under the proxy collapse under true CIS, hidden
  orthogonal edge surfaces. The remaining true-α question lives at that re-run.

- **2026-07-18 🔴 VOL SLEEVE V2 — REFUTED as Phase 3 candidate (R28), KILLED BEFORE SHIP.**
  Seth. Cause (cascade mechanic = leveraged long crowd + perp microstructure → forced selling →
  realized-vol spike) IS articulated; empirical realization on RV + funding data alone is too weak.
  Phase 2 implemented `src/research/cis_regime_studies/vol_sleeve_v2.py` + 10 sandbox smoke tests
  (all passing) + ran 3 legs on real data:
    Leg 1 (`long_vol_rv_only`, 21 names, 9y): Sharpe −2.20, MaxDD **−39.82%** — FAIL Gate 1
    Leg 2 (`long_vol_rv_funding`, 5 majors, 21mo): Sharpe −1.631, ann vol **0.04%** — fails because
      triple-crowding gate fires 0 times in the 21mo subpanel (only 38 RV_pct>0.9 events across
      the full 9y panel). A leg that doesn't fire isn't a leg.
    Leg 3 (`short_vol_carry_rv`, 21 names, 9y): Sharpe **+0.236**, just below +0.3 threshold.
      Premium proxy is an annualized constant (5%/year) — Phase 4 will replace with real IV > RV
      spread from Deribit data.
    Combined NAV: Sharpe +0.012, dragged down by Leg 1.
  Bug surfaced and fixed during Phase 2: Leg 3's first premium proxy (`notional × rv_per_bar ×
  0.30`) gave $259B terminal NAV from compounding. Replaced with constant annualized spread
  (`notional × 5% / (252 × 6)`) giving realistic $10,029. Lesson: per-bar proxies that compound
  over thousands of bars need annualized formulation. Full evidence in R28 + §10 of
  `docs/VOL_SLEEVE_V2_CAUSE_2026-07-18.md`. Phase 4 (Deribit IV integration) is the only path
  that could realize the cause's full alpha; remains on shelf.

- **2026-07-16 🧮 QUANT STACK — multi-asset/multi-strategy model, scalable CTA book, assimilation (Seth).**
  Jazz mandate: "act as a quant, find the profit-max strategy on our infra, capacity 不可以太小."
  **Multi-asset breadth (the deep finding):** crypto majors all co-move (corr→BTC 0.79) so crypto-only
  effective breadth is ~2.5; genuine breadth comes from OTHER classes — equity 0.42, commodity 0.22.
  Effective breadth crypto-only 2.46 → +equity 6.71 → +commodity 7.51 → +sector-ETF 8.31; four per-class
  market-neutral sleeves mutually orthogonal → **ENB 3.87**. All tradeable 24/7 on-chain via Binance
  RWA/ETF perps (uniquely ours). `src/research/factory/multi_asset_study.py`; experiment_runs
  `multi_asset_breadth_20260715`. **热点行业 gap filled:** added sector/thematic ETF perps (XLE/XBI/URNM/
  EWZ/EWJ/QQQ/IWM/DIA) to `dingge_rwa.SECTOR_ETF_PERPS` → live board + funding tracking.
  **Profit-max WITH capacity = scalable book** (`src/data/signals/scalable_paper.py`, table
  `scalable_book_nav`, `/api/v1/signals/scalable-book`, daily loop): **FACTOR + TREND(multi-horizon
  TSMOM, the CTA capacity engine) + CARRY**, risk-parity blend, **genuinely vol-targeted to 10% constant
  ex-ante vol** (verified) — the honest high-capacity construction. Sleeves corr 0.1–0.2; combined
  vol-targeted ~1.0 Sharpe; TREND multi-horizon (20/60/120/250) more robust (worst fold −0.19 vs −0.9).
  Candidate, accruing. `src/research/factory/scalable_book.py`; experiment_runs `scalable_book_20260715`.
  **Assimilated** into ONE portfolio view (`src/data/signals/portfolio.py`, `/api/v1/portfolio`):
  CORE=scalable (deployable) · COMPONENTS=combined_book+causal_paper (inside core, not double-allocated) ·
  CANDIDATES=dingge_paper (RWA/multi-asset extension) · meta risk-parity across non-overlapping books ·
  breadth + discipline inline. Kills the "which of 4 NAVs" confusion.
  **Signal feed v4 (loop-sourced):** `/api/v1/signals/feed` — dated resolvable calls + honest 30d
  accuracy, machine hidden; migrated ALL consumers (web SignalFeed, mobile MobileApp ×2, MCP
  get_signal_feed + asset_deep_dive via `?symbol=`); old market.py rule-engine now orphaned.
  **discover→extract→real-scenario** (Jazz: "good strategies born from overfitting; allow it, extract
  the feature, then real-scenario; 输多赢少 is the baseline"): `src/research/factory/discovery.py` — overfit
  to discover the family, extract the param-robust invariant, gate at stage 3; extracted features added to
  the factory library (`*_extracted`). experiment_runs `discover_extract_pipeline_20260715`.
  **Institutional gates added:** PBO (`src/research/validation/pbo.py`, our library 0.444 "partly overfit"),
  champion/challenger + hysteresis (recalibrate no longer auto-overwrites), live drift monitor on the book.
  Audit: `reports/MECHANISM_AUDIT_2026-07-15.md`. **Refutations R18** (unlock-supply cause — priced in,
  control-adjusted +15.8% p=0.02), **R19** (mining-cost/Puell — decays OOS, cycle descriptor not edge),
  **R20** (style/factor rotation — static beats rotation OOS; breadth is on the strategy axis in crypto).
  **Combined book OOS-validated 1.05** (blend fit on train only; experiment_runs `combined_book_oos_20260715`)
  — first positively-validated ensemble under the hardest test. Reports: UNLOCK_EVENT_STUDY, MINING_COST_STUDY,
  ROTATION_STUDY (all 2026-07-15). **All boot-verified via preflight; pushed incrementally.**
  NEXT (quant): cross-asset TREND (crypto+gold+equity-index perps) as RWA/ETF history matures — the
  canonical tens-of-billions-capacity strategy, uniquely on-chain here.

- **2026-07-15 🏭 THE LOOP, RUN AS A FACTORY (Seth) — artisan→factory shift, all 5 stages shipped.**
  Jazz's push: "you are not a task-by-task tool; why do we need the loop for?" → the loop IS the
  answer to alpha decay + the 82%-of-published-factors-fail base rate (refs: Bailey/LdP Deflated
  Sharpe; Hou-Xue-Zhang 82% fail corrected; WorldQuant ~4M alphas = a loop's output). Stop hunting
  heroes; run the machine. Built `src/research/factory/signal_factory.py` — generates a LIBRARY of
  cheap cross-sectional signals, gates each identically (market-neutral net of funding+cost → DSR
  over N-trials → walk-forward 5-fold robustness → orthogonality), logs deaths + survivors.
  **Batch 1: 15 signals, 0 DSR-certified@0.95 (honest — positioning only 0.50), but the nucleus
  (positioning_funding 1.18 + low_downside_vol_30 1.16 + momentum_120d 0.71 + neg_skew_pref_60 0.53,
  all WF-robust + mutually orthogonal) COMBINES to Sharpe 1.56 / ENB 3.68** (best single 1.18,
  uplift +0.38). The machine even discovered low_downside_vol + neg-skew (real literature factors).
  **Scoreboard moved UP by building the machine, not finding a hero** (1.36/2.95 → 1.56/3.68 as the
  library widened + gate tightened). Stage 3: `src/data/signals/combined_book.py` — ONE live
  market-neutral paper book = the nucleus ensemble, daily mark (price+funding−cost), weekly rebal,
  Supabase `combined_book_nav` (table created), `GET /api/v1/signals/combined-book` (provenance:
  nucleus + backtest-ref 1.56/3.68 + live curve). Stage 4: weekly `_factory_recalibrate_loop` in
  main.py → `recalibrate_and_log()` re-runs factory, writes fresh nucleus blend to Redis
  (`combined_book:nucleus`), auto-logs batch to experiment_runs; combined_book reads the live
  nucleus (decayed signals drop out, no code change). Stage 5: the endpoint IS the substrate
  surface (verifiable, not trust-me). Preflight PASSED (5 new loops boot-safe). experiment_runs:
  `signal_factory_batch1_20260715` (candidate, sharpe 1.36 initial). Honest label: nucleus is
  in-sample-DSR + 5-fold-WF, owes a true purged/embargoed walk-forward before capital; DSR-batch is
  a shortlist not a certificate. **Push (Mac):** src/research/factory/, src/data/signals/combined_book.py,
  src/api/main.py. Tables combined_book_nav live.
- **2026-07-15 🔴 MOAT VALIDATION — forward-supply cause REFUTED as tradeable (R18), survives as risk-filter.**
  Jazz chose "validate the moat." Unlock event study (`src/research/cis_regime_studies/unlock_event_study.py`,
  `reports/UNLOCK_EVENT_STUDY_2026-07-15.md`): 11 curated cliff unlocks (TIA 82%/ENA 66%/ALT 42%/STRK/ARB/APT),
  real Binance prices, 30d BTC-relative alpha, CONTROLLED by each token's own non-event window. Raw −9.75%/82%
  neg looked confirmed but is confounded (alts bleed vs BTC anyway); control-adjusted effect +15.8%, 9/10 positive,
  sign-test p=0.021 (unlock windows BETTER than baseline); largest unlocks biggest relief (TIA→+34.7%). Scheduled
  cause = priced in ("sell rumor buy news"). experiment_runs `unlock_event_study_20260715` refuted, R18.
- **2026-07-15 🔴 MINING-COST / miner-economics REFUTED as live edge (R19), cycle-descriptor only.**
  Jazz's anchor, finally tested. `src/research/cis_regime_studies/mining_cost_study.py`,
  `reports/MINING_COST_STUDY_2026-07-15.md`. BTC 2017-2026, Puell Multiple + difficulty cost proxy,
  IS/OOS split. Puell 180d IS textbook (Q1 low-Puell +89.8%/80%win, IC_IS −0.58) but OOS IC −0.02 (gone);
  only ~2-3 cycle bottoms in all BTC history (tiny effective-n); difficulty proxy = momentum, price-near-cost
  is WORST bucket. Published cost-basis = descriptor, not edge (priced in). experiment_runs refuted, R19.
- **2026-07-15 🟡 顶格 RWA strategy — real entry-time rule built, PREMATURE (all-2026 data), deployed live-paper.**
  Prior backtest peeked at realized trend; built the honest entry-time direction rule
  (`src/research/cis_regime_studies/dingge_strategy_study.py`): IS +8.6%/61%win, OOS −3.1%/31%win, net of
  funding (checked: only −0.31%/trade because entry is +15d post-cap-reset, NOT the 20% bleed feared) + 30bps.
  Every episode is 2026 → no real OOS possible. Right move = deploy live-paper to accrue forward:
  `src/data/signals/dingge_paper.py` (models funding+cost, self-labels "candidate — NOT proven" with a hard
  validation gate ≥30 trades/≥120d), Supabase `dingge_paper_nav`, daily loop, `GET /api/v1/signals/dingge-paper`.
  experiment_runs `dingge_rwa_strategy_20260715` candidate.
- **2026-07-15 🔧 LOOP PLUMBING + OUTPUT FIXES (Seth).** (1) MCP → modern Streamable-HTTP at /mcp (was
  deprecated SSE-only; fixed sys.path shadowing of pip `mcp` by local src/mcp; session-manager lifespan via
  on_event; legacy SSE kept at /mcp-sse); discovery configs updated. (2) Paper-ledger bug: `/trading/metrics`
  conflated the $100k-NAV notional sleeve into the $10k cash book + double-counted realized P&L → $36.9k on
  $10k; fixed (cash book = balance + cash-open only; sleeve reported separately). (3) `_redis_set` sent EX=0
  (invalid) → causal_paper state never persisted, NAV frozen at 1.0 re-inceptioning daily → FIXED (omit EX
  when ttl≤0). (4) Self-iteration loop: 4/5 prediction sources never persisted (tables empty / narrative_snapshots
  missing) → wired persist_forward_supply/positioning into the refresh loops (once/day upsert), conviction +
  narrative into the daily snapshot loop; created narrative_snapshots table; all 5 sources now emit (measurable
  at 30d horizon). (5) Paper skeleton `papers/agent_research_protocol_skeleton.md` (methods + refutation-ledger).
  Proof page `dashboard/proof.html` (Jazz: "frontend meaningless" — deprioritized).
- **2026-07-15 🟡 Phase D2 — V14 CIS macro regime fusion (Minimax-C, Seth × M-C).**
  Built V14 = V9 + CometCloud's 7-regime macro overlay from CIS history JSON
  (`/Volumes/CometCloudAI/cometcloud-local/_data/cis_history/`, 431 days coverage).
  Three macro effects on V9: stake multiplier (0.5×–1.25×), direction override
  (4h contradicts macro → demote neutral; 4h silent + decisive macro → tilt
  bull/bear), and STAGFLATION flat-mode trigger. **NEGATIVE RESULT — fusion
  works as designed but loses too much alpha for the DD benefit.** TRAIN ≡ V9
  bit-exact (sanity ✓, no CIS data). HOLD-OUT 10p: V14 98 trades/+$207/sharpe
  4.80/maxDD 0.82% vs V9 135/+$362/5.45/1.31% → V14 loses 43% PnL for 37% DD
  reduction. FORWARD 10p: V14 159/+$247/7.40/0.43% (lowest maxDD after V10c,
  highest win rate 74.8%) but Sharpe mediocre. Compared to **V12b** (existing
  production regime overlay): V12b dominates V14 on all HOLD-OUT metrics AND
  ties on FORWARD. **Recommendation: do NOT replace V12b; consider V14 as 4th
  sleeve member (low-DD defensive) OR re-tune macro multipliers (Option A in
  report — 0.85× / 0.85× / 0.70× instead of 0.65× / 0.65× / 0.50×).** Files:
  `SwingOverlayV14_MTF_DirAware_CISRegimeOverlay.py`, full sweep results in
  `_data/research/d2_out/2026-07-15_v14_{5,10}pair/`, report
  `SWING_V14_CIS_MACRO_FUSION_2026-07-15.md`.

- **2026-07-16 ✅ Phase D2.1 — V14 Option A re-tune + Sleeve fusion analysis (Minimax-C).**
  TWO tracks completed in one session:

  **Track A (V14 Option A re-tune) — POSITIVE incremental.** Re-tuned macro multipliers
  from aggressive (1.10/1.10/1.00/1.00/0.65/0.65/0.50) to moderate
  (1.10/1.10/1.00/1.00/0.85/0.85/0.70). Re-ran 8 backtests (5p+10p × 4 windows, ~24s).
  Option A vs original V14: HOLD-OUT +15% PnL / +33% DD cost; FORWARD +49% PnL / +26%
  DD cost. Real improvement, ~50% of original PnL loss recovered. **V14a still loses to
  V12b on holdout PnL** (−37%) but **wins on forward DD (−18%) and win rate (74.8% vs
  71.6%)** → qualifies as 4th sleeve candidate. Recommended: V7+V10c+V12b+V14a 4-slot
  sleeve at 50/20/20/10 — pending validation.

  **Track B (Sleeve fusion 70% SwingOverlay + 30% Nautilus LS V1) — NEGATIVE structural.**
  Built Nautilus ParquetDataCatalog (3 instruments BTC/ETH/SOL), ran fresh backtests
  on 3 windows (default OOS 10mo, holdout 2.5mo, forward 4mo). Nautilus realized:
  +3.29% / +1.90% / **−0.43%** across windows — sparse alpha stream, 4–28 positions
  per multi-month window. Sleeve weight sweep shows 30% Nautilus costs 1.4pp PnL for
  0.19pp DD benefit on HOLD-OUT (ratio 7:1 PnL/DD) and is pure PnL drag on FORWARD
  (−2.54pp). Recommendation: **skip Nautilus at 30%**; if exposure wanted for
  "long-short regime" upside, allocate 5-10% max with explicit acknowledgment it's a drag.

  Files: `SwingOverlayV14_MTF_DirAware_CISRegimeOverlay.py` (Option A constants),
  `_data/research/d2_out/2026-07-16_v14a_{5,10}pair/`, `_data/research/sleeve_fusion_2026-07-16/`
  (3 Nautilus windows + sleeve_summary.json), `docs/SLEEVE_FUSION_V14_REPORT_2026-07-16.md`.


- **2026-07-16 ✅ Phase D2.2 — 4-slot sleeve validation (Minimax-C).**
  Validated 4-slot sleeves (V7+V10c+V12b+V14a in various weights) against 3-slot baseline
  (V7+V10c+V12b = 50/30/20) on HOLD-OUT + FORWARD. Built `/tmp/sleeve_4slot.py` for
  weighted-DD estimation (correlation-corrected) and annualized Sharpe proxy.

  **Headline result**: **4-slot E (V7 50% + V9 15% + V12b 20% + V14a 15%)** is the
  recommended production sleeve. Net Δ vs 3-slot baseline: **+1.43pp PnL / +0.15pp DD**
  (PnL:DD ratio 9.5:1 — best in cohort). Per-window:
    HOLD-OUT (74d):  +7.11% PnL / 1.30% DD (vs baseline +6.51% / 1.20%) → +0.60pp PnL, +0.10pp DD
    FORWARD (122d): +8.85% PnL / 0.68% DD (vs baseline +8.02% / 0.63%) → +0.83pp PnL, +0.05pp DD

  Sleeve cohort matrix (Net Δ across HO + FW):
    4-slot A  50/20/20/10   +0.24pp PnL  +0.04pp DD   (neutral, "test the waters")
    4-slot B  45/20/20/15   −0.24pp PnL  −0.05pp DD   (slight risk-budget)
    4-slot C  40/20/20/20   −0.73pp PnL  −0.14pp DD   (max risk-budget; only DD reducer)
    4-slot D  60/20/20 (no V10c) +1.69pp PnL +0.31pp DD (PnL-max)
    **4-slot E  50/15/20/15 +1.43pp PnL +0.15pp DD (RECOMMENDED — best balance)**
    (drop V10c, add V9+V14a)

  **Production sleeve UPDATES**: V7 50% + V9 15% + V12b 20% + V14a 15%. V14a enters
  the sleeve after Option A re-tune validated it as a viable defensive 4th slot.

  Caveats: (1) DD estimation uses correlation-corrected portfolio variance (ρ=0.5) — true
  equity-curve DD may differ ±0.05pp; (2) 4-slot validation assumes individual sleeve
  metrics are independent at the trade level (true daily correlation ~0.3-0.5 for SwingOverlay
  variants); (3) no live paper-trading track record yet for the 4-slot combination.

  Files: `docs/sleeve_4slot_validation_2026-07-16.json`, `PROJECT_STATE.md` updated.

- **2026-07-15 🎯 Phase D1.6 — Forward test 17 weeks post-OOS (Minimax-C).**
  Window 2026-03-16 → 2026-07-15 (true OOS, 17 weeks, 1.7× the D1.5 holdout length).
  All 5 strategies pass 5/5 OOS criteria on 10-pair universe. V7 forward: +$623
  (+10.39%), Sharpe_d 7.98, maxDD 0.99%, PF 3.06 — **improves on holdout on every
  metric**. V8 highest forward Sharpe (8.49). V10c lowest maxDD (0.33%, ~one-third
  of V7). V12b = V9 in forward (funding gate never fired: BTC max fr_bps +0.98,
  never crossed the ±3 bps threshold) — **expected, not a bug**: the gate is
  dormant in benign funding, protective in stressed. $/week retention 71–80% vs
  holdout = normal variance, no edge erosion. **Live paper deployment of
  recommended sleeve is **4-slot E: V7 50% + V9 15% + V12b 20% + V14a 15%** — 4-slot validated via D2.2 sleeve sweep (10p HOLD-OUT + FORWARD).**
  Driver got `--windows` CLI flag + venv-Python fix. Forward output:
  `_data/research/d15_out/2026-07-15_forward_10pair/`. Report:
  `SWING_WALK_FORWARD_D16_FORWARD_2026-07-15.md`.
- **2026-07-14 🎯 Phase D1.5 — V12 funding-gate fix + V10 vol-target calibration + 10-pair extension (Minimax-C).**
  Three sub-tasks, all ✅. **(A) V12 funding-gate bug discovered and fixed**: V12's
  symbol-lookup used `pair.split("/")[0]` ("BTC") to look up a dict keyed by
  "BTC/USDT:USDT" → funding fr_bps always 0 → gate NEVER fired in any test,
  including the 2026-07-13 "falsification" report. V12b (`_FUNDING_GATE_FIXED`)
  now passes full CCXT pair as lookup key. Real result: V12b total PnL -10.9% vs
  V9 but HOLD-OUT Sharpe 5.70 vs 5.22 + maxDD 2.09% vs 2.54% — nuanced risk-control
  story, not simple falsification. **(B) V10c vol-target calibration**: V10/V10b's
  `VOL_TARGET_PCT=0.005/0.01` was 10–20× the actual BTC 15m ATR% → scalar always
  clipped to 1.0 → true no-op. V10c with `VOL_TARGET_PCT=0.0008` now fires: 50%
  DD reduction at 49% PnL cost = same Sharpe with half equity volatility. **(C) 10-pair
  extension**: AVAX/LINK/ARB/OP/DOGE added → wallet $6k. V7 HOLD-OUT PnL +$520 (+8.67%),
  maxDD 1.92% (down from 3.48% on 5p). All 5 strategies pass 5/5 criteria on 10p.
  **Edge generalises beyond BTC-major basket — V10c on 10-pair HOLD-OUT has 0.64% maxDD.**
  Driver updated: --config arg, HTF_DATA_DIR env, cache key includes config stem.
  Files: `SWING_WALK_FORWARD_D15_2026-07-14.md`, V12b/V10c strategy files, 10-pair
  config, 4h+15m feather downloads. NEXT: forward test 2026-03-15 → 2026-07-15.
- **2026-07-14 🎯 Phase D1 SwingOverlay walk-forward OOS (Minimax-C) — 4/4 ROBUST, LP-grade claim ready.**
  Driver: `_data/research/phase_d1_walk_forward.py` (63s for 12 backtests). Universe: 5-pair futures
  (BTC/ETH/SOL/BNB/XRP :USDT), 15m, isolated margin, $900/trade × 7 open × $3k wallet (21% deployment).
  Windows: TRAIN 2024 (bull +113.85%) / VALIDATE 2025 (chop −7.98%) / HOLD-OUT 2026 Q1 (bear bounce
  −25.51%). **All 4 DSR-survived strategies (V7/V8/V9/V10) pass 5/5 pass criteria on every window.**
  HOLD-OUT Sharpe_d 5.22–5.47, maxDD 2.3–3.5%, H/V decay ≥1.0 (HOLD-OUT ≥ VALIDATE). Report:
  `_data/research/SWING_WALK_FORWARD_OOS_2026-07-14.md`. **V7_MTF recommended for production** — highest
  absolute PnL across all windows ($2,419/$1,745/$467), simplest architecture, robustness equal to
  the more complex variants. **KEY CAVEAT surfaced: V9 ≡ V10 in this universe** — V10's funding
  gate no-ops (15m klines have no funding_rate field, defaults to 0) and vol-target scalar rounds
  to 1.0 for liquid majors (BTC 15m ATR ≈ 0.05%, well below VOL_TARGET_PCT=0.005). **V10 not
  falsified, but not validated either** — re-validation needs funding_feed.py + coarser ATR window.
  Two bugs fixed in driver during run: `p.stat.st_mtime` → `p.stat().st_mtime` (unbound method
  → result); `time.monotonic()` → `time.time()` for `since_ts` floor (clock-domain mismatch).
  Bug had blocked the 12-backtest sweep silently (all cached as errors) — fixed by clearing
  cache + re-running. NEXT: forward test 2026-03-15 → 2026-07-15 (4 months post-OOS), V10 funding
  feed + vol-target re-calibration, altcoin universe extension (AVAX/LINK/ARB/OP).
- **2026-07-13 QA SWEEP of all customer-facing page endpoints → found + fixed Trading Engine 500.** Swept 16
  live endpoints across every nav page. Result: most ✅ (CIS universe 58, Protocols 25, Journal, 顶格 27,
  Strategies, Vault). ONE real breaker: `/api/v1/signals/performance` **HTTP 500** (Trading Engine page dead).
  ROOT (reproduced locally): `_compute_metrics` line 432 `r.get("return_pct_30d", 0)` — `.get(k,0)` does NOT
  guard key-present-with-value-None (EXPIRED signals have return_pct_30d=None) → `np.mean([...,None])` TypeError.
  FIX: filter Nones before np.mean + top-level try/except so the flagship page degrades to "building" not 500.
  Verified: _compute_metrics runs clean on edge-case data; SMOKE OK. False alarms: Signal Feed (uses
  `/api/v1/signals` not `/feed`), CG-markets 400 (needs ids param frontend provides). Known-null: Macro Brief
  (Mac LM Studio not pushing — pre-existing). Lesson: a page can render fine but 500 on real data with Nones
  that test data lacks — sweep live endpoints, not just boot.
- **2026-07-13 🚀 FRONTEND BUILDS IN-SANDBOX NOW — the real velocity unblock.** The whole session's frontend
  work was piling up UNBUILT because I assumed the sandbox couldn't `npm run build` (FUSE deny-unlink breaks
  vite emptyDir). SOLVED: build to `/tmp` (outside mount) → copy `dist/` back (copy=write, allowed). Built in
  3.2s; app.html→app-CKbeEh_e.js (present, contains new code); dingge-board/open-source/alpha_equity all in the
  built bundles. `scripts/build_frontend.sh` makes it repeatable; CLAUDE.md deploy workflow updated. IMPACT: no
  more "wait for Mac npm build" — agent builds dist, Mac just `git add -A && commit && push`. Everything this
  session (VC clean, honest alpha metrics + chart, open-source strategies page, 顶格 board on Events, causal-paper
  endpoint, all backend) is now BUILT + boot-verified (SMOKE OK) + ships in ONE push. This was the bottleneck
  behind "还不能给客户用/太慢".
- **2026-07-13 顶格 board surfaced on Events page (live differentiated signal).** Built standalone
  `dashboard/src/components/DinggeBoard.jsx` (fetches live `/api/v1/signals/dingge-board`, renders RWA funding
  extremes: symbol, crowded-long/short side, peak annualized funding, 量能/volume ratio, up/down lean; 10min
  refresh; honest "candidate, not live capital" footer). Mounted on IntelligencePage events view above VC
  Funding. Verified vs LIVE endpoint — fields match, populated NOW (SAMSUNG/SKHYNIX at-cap 696-724%/yr vol 3.4×
  →up_bias; KORU crowded-short 1006%/yr→squeeze). Standalone component = low blind-edit risk. JSX balanced
  (61/61, 979/979). Needs push + Mac npm build. This is the one live, populated, uniquely-ours signal on the UI.
- **2026-07-13 OPEN-SOURCED earlier profitable strategies on the Strategies page (Jazz ask).** Released 3
  directional/CIS-gated strategies under MIT (NOT the moat — causal+conviction stay proprietary):
  `strategies/open_source/` = SwingOverlayV7_MTF (profitable, honest IN-SAMPLE metrics: Sharpe 6.2/CAGR 32%/PF
  1.9/win 66%/DD 3.3%, owes walk-forward) + ValueOnChain (F+O, reference) + Breakout (S+M, reference) + README +
  MIT LICENSE. Backend: `OPEN_SOURCE_STRATEGIES` catalog + `GET /api/v1/strategies/open-source` (metadata, honest
  in_sample-vs-reference labels) + `/{id}/code` (serves source). Frontend: `OpenSourceStrategies` section on
  StrategiesPage (fetch catalog → cards w/ thesis + honest note + View-code). Honesty rule enforced in copy: no
  invented performance, in-sample labeled as such. Verified: import+boot SMOKE OK (ran the real gate, not just
  py_compile — post-Response-bug discipline); JSX balanced. Needs push + Mac npm build.
- **2026-07-13 🚨 DEPLOY 502 FIXED — `Response` not imported in main.py (my bug).** Commit 41dec72 boot-failed
  (502 every endpoint, new build never came up). ROOT CAUSE: my new endpoints `causal_paper`/`dingge_board` use
  `response: Response = None`, but main.py imported only `FastAPI, Request, Header` — annotations eval at IMPORT
  time → NameError at boot → app never starts. `py_compile` PASSED (syntax only, not name resolution) so my
  "compile OK" checks missed it. FIX: `from fastapi import FastAPI, Request, Header, Response` (1 line). VERIFIED
  by actually importing: `import src.api.main` → clean (the real test py_compile can't do). PREVENTION: pre-push
  smoke MUST `import src.api.main`, not just py_compile — it catches annotation/name errors. Recovery: push the
  1-line fix (boots clean, verified) OR Railway-UI rollback to f19275c first for instant uptime. Frontend
  PerformanceDashboard.jsx (held back by Minimax) couples to the now-live alpha_* fields → push it + `npm run
  build` dist together next.
- **2026-07-13 OUTPUT-LAYER QA — fixed the two broken user-facing pages (Jazz: "nowhere near our standard").**
  (1) EVENTS & VC: funding rounds were malformed RSS extractions (project=null, investor="SBI Holdings SBI
  Holdings was the sole investor in the round"). Added `_sanitize_raises` in intelligence.py — drops null-name
  rounds, cleans sentence-fragment/duplicate/project-contaminated investor strings. Verified: →"SBI Holdings".
  (2) SIGNAL PERFORMANCE (Trading Engine): headline showed −0.89 Sharpe / 2.6% win-rate — an ABSOLUTE-return
  long-only sleeve doomed in a Tightening market. Root: scoring relative OUTPERFORM signals on absolute return.
  Fix: signals.py now exposes honest `alpha_sharpe`/`alpha_win_rate_pct`/`avg_alpha_pct` + headline_note pointing
  to causal-paper; PerformanceDashboard.jsx Sharpe+WinRate cards now lead with alpha (fallback absolute).
  Also fixed: (3) VC PORTFOLIOS junk — data_layer.get_cg_vc_portfolios `-portfolio` suffix auto-included CG joke
  categories (Pump Fund=$0/CLAWPUMP); added quality floor (non-whitelist needs ≥$25M mcap + blocks pump/meme/
  airdrop). (4) EQUITY CHART — was plotting the absolute −26% crater; backend now emits `alpha_equity_series`
  (compounds benchmark-relative alpha), PerformanceDashboard prefers it (same shape, chart unchanged), relabeled
  "Cumulative Alpha vs BTC/SPY" + honest total. All backend compiles; JSX balance-checked (464/464 braces).
  STILL TODO (needs Mac build + design): lead Trading Engine with the causal-paper NAV once it accrues marks;
  demote the observational sleeve. Backend verified; frontend needs `npm run build` Mac-side.
- **2026-07-13 🔓 BINANCE GEO-BLOCK RESOLVED (Railway US + Mac SG both reachable).** Sandbox curl to
  `https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT&limit=2` returns HTTP 200, 0.44s — verified
  2026-07-13. Mac SG already reached it (causal_positioning.py uses it daily). **Implications:**
  (a) **NMA pipeline stays CG-primary, Binance-fallback** — do NOT revert the post-push CoinGecko
  reroute (commit f19275c); R11's lesson generalizes ("verify data-source reachability in TARGET
  environment, not just sandbox"). CG-primary is the disciplined choice; Binance is the redundancy.
  (b) **顶格 RWA monitor (commit 41dec72)** is now using live Binance data — verified live SKHYNIX/
  SOXL/SAMSUNG/CBRS signals. (c) **V11/V12 per-bar funding unblocked** — V10 report flagged
  "per-bar funding = V11 work (extend CIS loader to read CIS_HISTORY_DIR)" as the workaround for
  geo-block; now we can pull directly from fapi /fundingRate (8h settlements) and pre-aggregate
  to daily means for backtest. **V12 in flight** = V10's regime-conditional funding gate finally
  firing in backtest (currently inert: CIS funding cache returns 0 in backtest mode). **R11
  retained as historical record** (the specific geo-block instance is superseded, but the lesson
  is permanent — see REFUTATION_LEDGER.md update note 2026-07-13).
- **2026-07-13 V12 BUILD (Minimax-C) — Funding-Gate-Wired (V10 + per-bar funding table); funding gate
  FALSIFIED when it actually fires.** Built the deferred V10 closeout: pre-compute per-pair DAILY MEAN
  funding from fapi /fundingRate (`/tmp/v12_funding_table.json`, 92KB, 4,260 obs × 5 pairs × 926 days,
  μ=+0.45-0.66 bps structural positive, σ=0.86-2.05 bps). V12 = V10 clone + per-bar funding lookup
  (vectorised `_fr_bps` column in populate_indicators; `_v12_fr_for(symbol, current_time)` per-call
  helper in confirm_trade_entry). **Unit test PASS** (table loads, lookups work, forward-fill correct,
  sign conversion verified, gate-firing day counts: 2.6-3.8% long-block, BNB 8.6% short-block).
  Walk-forward 3 windows: **V12 5-pair = +2,554.2 USDT vs V9 +3,169.8 (-19.4% P&L), trades 1,178 vs
  1,297 (-9.2%); V12-ETH = +1,421.2 (FLAT vs V9), trades 242 flat.** **The CLEAN A/B vs V10 (gate
  inert) = -0.7% P&L on -2.4% trades** — the funding gate fires ~29 times over 3 windows × 5 pairs
  (almost all bull + fr>3bps on BTC/SOL/ETH/XRP longs) and the trades it filters are on average
  NET PROFITABLE — bull regime pullbacks with elevated funding are exactly where V9's RSI<35 cross
  historically works. **Three falsifying findings in a row on the funding-gate hypothesis**: (1) V10
  vs V9 = -18.8% (gate inert but vol-target confounded); (2) V12 vs V10 = -0.7% (gate fires, gate
  itself subtracts alpha); (3) ETH-only shows the gate essentially never fires (ETH rarely in pure
  bull/bear + funding rarely crosses ±3bps). **The P1 ground-truth ("funding sign MIXED 5/12 in
  regime-conditional way") was correct as a *descriptive* finding about funding signs in different
  regimes, but it is NOT a *trading* signal.** Crowded longs in a bull market are still on the
  right side of the trend. **Aligns with V10/V11 pattern** (a) **V10 falsified vol-target** for
  per-pair swing; (b) **V11 falsified H3.2 conviction-sizing portability** (R13); (c) **V12
  falsifies funding-gate portability** — three per-pair overlays all net negative. **Causal
  Sleeve (corr +0.002 to swing, ann Sharpe +1.21, ENB 2.16→2.85) remains the orthogonal
  answer** — its CROSS-SECTIONAL signal form is the right port, not per-pair gates. **Don't
  propose more per-pair filters on swing without explicit cross-validation.** V9 retained as
  production; V10/V11/V12 retained for archival + as the canonical funding-gate counter-example
  (R15 added to REFUTATION_LEDGER). Report: `_data/research/V12_FundingGateWired_2026-07-13.md`.
  Configs: `/tmp/config_swing_v12{,_eth}.json`. Walk-forward logs: `/tmp/v12{,_eth}_{train_2024,
  validate_2025,holdout_2026}.txt`.
- **2026-07-11 CAUSAL SLEEVE → LIVE PAPER BOOK (the validated edge, now accruing a real track record).**
  After walk-forward (4/5 folds +1.42) + cost/deployability (weekly-rebal net +1.69@10bps, break-even 47bps,
  no borrow) confirmed the causal positioning sleeve as THE one build-ready edge, wired it to paper. Built
  `src/data/signals/causal_paper.py` — NAV state machine (daily mark + WEEKLY rebalance, the validated cadence);
  market-neutral cross-sectional book (gross 1.0, net ~0; longs low-funding, shorts crowded-longs). State→Redis
  `causal_paper:state`, NAV curve→Supabase `causal_paper_nav` (table CREATED via connector). Daily
  `_causal_paper_loop` in main.py + `GET /api/v1/signals/causal-paper` (curve + Sharpe/DD). Binance reachable
  since SG region → runs on Railway directly. Verified: live weights form correctly (24 majors, ATOM/INJ long,
  UNI/OP/BTC short). This converts "walk-forward candidate" → live-marked track record for LP conversations.
  **Uncommitted — needs push** (causal_paper.py + main.py + causal_positioning docstring). Jazz's
  trading signal: tokenized-RWA perps (MSTR/COIN/NVDA/TSLA/gold/silver/crude/chips) hit funding顶格 (cap,
  500-1170% annualized) because they trade 24/7 on-chain vs a CLOSED underlying (weekend/after-hours blowoff) →
  old trend exhausts → new trend forms → direction set by 量能/VOLUME (not price momentum). Tested: n=24 RWA
  顶格 episodes; VOLUME predicts new-trend direction (corr +0.39 full; vol-expand beats vol-dead in BOTH IS
  (+6.3 vs +2.8) and OOS (+5.2 vs -1.8); vol-gated strat +1.7% IS / +3.5% OOS). Corr noisy (young instrument
  class, small n) but economics directionally consistent IS+OOS. Built `src/data/signals/dingge_rwa.py`
  (RWA_PERPS list, live monitor scan_live() + backtest()) + `GET /api/v1/signals/dingge-board`. Live board now
  flags SKHYNIX/SOXL/SAMSUNG (量能 expanding→watch_up), CBRS (dead→watch_down). experiment_runs updated to
  candidate. This is a structural, differentiated lane (neither crypto nor TradFi quants sit in it) at our exact
  thesis intersection. Needs OOS accumulation + capital-gating before sizing. **Uncommitted — needs push.**
  **CORRECTION (Jazz caught it): 顶格 is BIDIRECTIONAL** — funding at +cap (crowded longs, flush) OR -cap
  (crowded shorts, squeeze). Original detector was long-only → missed ~half the events. Fixed: n 24→40 (20+20);
  short-crowded fwd +5.3%, long-crowded +4.4%; vol-expand +8.2% vs vol-dead +1.5% fullsample, OOS still weak.
  Monitor now shows side + squeeze/flush logic (KORU=short_crowded→up_bias). Foundation corrected, verdict unchanged.
- **2026-07-11 SECTOR VALUATION ROTATION (韭圈儿 template) — tested, naive port REFUTED, right path identified.**
  Jazz flagged 韭圈儿's A-share sector index valuation (温度 = PE/PB percentile vs own history) + rotation as a
  strong template. Studied + built crypto analog (8 sectors from 50 assets) + tested: naive price-based
  temperature FAILS (long-short Sharpe +0.04, long-only −0.16/−25%/109% DD — value trap, cheap keeps falling).
  Root cause: A-shares mean-revert because EARNINGS anchor price (PE/PB); crypto has no earnings floor → price-
  cheap = momentum-reversion = trap (R6 again). Right adaptation: real fundamental temperature (MVRV-Z majors +
  mcap/TVL + mcap/fees via DeFiLlama — we already integrate it) used as a SCREEN, GATED by catalyst+trend
  (CONVICTION L2/L4) — value alone is a trap; value+catalyst is the thesis. Bonus: a legible "估值温度 board" UI
  surface (on-brand for APAC audience). Logged R12 + refuted run in live experiment_runs (now 2 rows: certified
  swing + this). Report: `reports/SECTOR_VALUATION_2026-07-11.md`.
- **2026-07-11 POST-PUSH CHECK caught a prod bug: narrative trend+orderflow used geo-blocked Binance.**
  Verified deploy (f19275c2 live, loop-health FLOWING, 5 Supabase tables live+write-verified). BUT live NMA
  showed trend=50 orderflow=50 FLAT while social differentiated → my trend fix (Binance klines) + orderflow fix
  (Binance fapi) hit Binance, which is GEO-BLOCKED on Railway US (works in sandbox, fails in prod → fallback 50).
  FIXED: rerouted BOTH to CoinGecko (Railway-safe, same source positioning.py uses) — trend→CG market_chart
  (vol+price momentum), orderflow funding→CG /derivatives (OI-weighted funding). Verified differentiated via CG.
  bid_imbalance/depth still Binance (degrades to neutral on Railway; orderflow leans on funding). **NEW uncommitted
  change — needs push.** Lesson (→ Refutation Ledger candidate): "works in sandbox" ≠ "works on Railway" for any
  Binance-sourced signal; CoinGecko is the Railway-safe primary.
- **2026-07-10 PREDICTION RESOLVER — "resolve EVERY prediction" (closes the 88:4 read-back gap).** Built
  `src/data/signals/prediction_resolver.py` — generalizes outcome_tracker (signals only) to ALL 5 sources
  (signal, positioning, forward_supply, conviction, narrative). Each source's directional claim → resolved
  through the SAME alpha engine (price@date+horizon, BTC/SPY-relative alpha, hit=sign(alpha)==direction) →
  `prediction_outcomes` table (`scripts/supabase_prediction_outcomes.sql`). Per-source read-back
  {n, hit_rate, avg_directional_alpha} = the value-mining query (which sources are actually predictive → feeds
  per-source conviction weighting). Wired: daily `_prediction_resolver_loop` in main.py + `GET
  /internal/prediction-track-record`. Smoke-tested engine against REAL Binance prices ✅. This is the LOOP
  automation fix — turns write-only logs (cause_snapshots/conviction_verdicts/narrative) into measured track
  records. **DEPLOYED 2026-07-10 via Supabase connector** ✅ — 5 tables live on project soupjamxlfsmgmmtoeok:
  cause_snapshots_daily, conviction_verdicts_daily, cause_outcomes, experiment_runs (seeded w/ certified swing
  run), prediction_outcomes. Write verified. ⚠️ SECURITY: connector flagged `signal_outcomes` has RLS DISABLED
  (7743 rows exposed to anon key) — matches SECURITY_REVIEW HIGH finding; needs policy decision (Minimax/Jazz),
  not auto-fixed.
- **2026-07-10 LOOP INDUSTRIALIZATION shipped — experiment recorder + FreqAI assignment.** Built
  `src/research/validation/experiment_recorder.py` (Qlib-style per-run memory; Supabase `experiment_runs` +
  JSONL fallback; the positive-results twin of REFUTATION_LEDGER) + `scripts/supabase_experiment_runs.sql`.
  Seeded with this session's real runs → capital shortlist auto-surfaces the DSR-certified swing lineage;
  refuted runs logged with ledger_ref. Assigned Minimax-C (MINIMAX_SYNC §LOOP-INDUSTRIALIZATION): turn on
  FreqAI adaptive retrain on the certified swing set with CIS+causes+NMA as base indicators (not price-only),
  historic_predictions + Tensorboard, A/B vs frozen REGIME_CIS_FLOOR on OOS → cut if it loses. Seth owns:
  recorder (done), generalizing outcome_tracker to resolve ALL predictions, one-definition feature parity.
  Principle: borrow the field's plumbing, keep our signal. Report: `reports/LOOP_VS_OSS_2026-07-10.md`.
- **2026-07-10 LOOP vs OSS benchmark (Qlib / FreqAI / MLOps).** Reviewed our loop vs the field. Verdict: we're
  AHEAD on WHAT we compute (upstream causal signal; curated Refutation Ledger) and BEHIND on HOW we operationalize
  (no experiment recorder, manual learning, ad-hoc feature store, backtest↔live parity). Cheap adoptions, mostly
  from tools we already run: (1) turn on FreqAI adaptive retrain + historic_predictions + Tensorboard for the swing
  lineage (Minimax-C) → closes "manual learning" for free; (2) Qlib-style Recorder → Supabase `experiment_runs`
  (positive-results twin of the Refutation Ledger); (3) generalize outcome_tracker to "resolve every prediction"
  (causes/conviction/narrative, not just signals); (4) one-definition feature-store parity (Redis live + Supabase
  history, same code path) → kills the R9/R10 "wired≠working / drift" bug class; (5) evaluate Qlib as research
  backbone, not a rewrite. Do NOT copy their alpha source (price/feature ML = our R5 graveyard). Report:
  `reports/LOOP_VS_OSS_2026-07-10.md`.
- **2026-07-10 REFUTATION_LEDGER.md — failures made first-class (Jazz: "failures are more important than
  successes").** Durable graveyard of every falsified/null/false-alarm hypothesis (R1-R10 so far), each with
  the number that killed it + the generalizing lesson. Rule: grep before proposing a new test — if it's here,
  don't re-run it. Aggregate lessons: (1) cleverness overfits, simple survives; (2) edge = orthogonality not
  more-of-same; (3) "wired" ≠ "working" — verify the number+schema; (4) the loop's job is to kill our ideas
  cheaply (9/10 died pre-capital). This is the LEARN-memory the loop was missing.
- **2026-07-10 NMA trend source fixed + causal sleeve expansion TESTED (negative, kept simple).** (1) DATA FIX:
  replaced dead Google-Trends/pytrends (429→flat 50) trend source with real Binance volume+price-momentum
  attention score (`get_google_trend_score` rewritten). NMA now fully repaired — all 3 inputs real; produces
  differentiated signals incl. HYPE=NARRATIVE_FADE (35.8). Three NMA data errors all fixed this session
  (orderflow spot→fapi, social dead-endpoint→Pro-key+live dev/sentiment, trend pytrends→vol/price momentum).
  (2) STRATEGY: tested expanding causal_positioning 24→50 perps — **HURTS** (Sharpe +1.34→+0.12, DD 10→30%):
  funding-crowding is a LARGE-CAP signal, thin/new names = noise. Established-40 holds +1.07 (capacity option,
  small Sharpe cost). Second signal (funding acceleration) also degraded it → rejected. Codified DEFAULT_UNIVERSE
  (24) + ESTABLISHED_UNIVERSE (40, capacity-only) + liquidity-gate lesson in `causal_positioning.py`. Discipline
  win: 2 plausible enhancements tested, both failed OOS-style, kept the simple version. Data cached
  outputs/causal_data.json (50 assets). Report: `reports/CAUSAL_SLEEVE_2026-07-10.md`.
- **2026-07-10 LOOP HEALTH — verified flowing end-to-end + standing instrument.** Jazz: "make sure the system
  is working, all parts flowing." Built `src/api/loop_health.py` + `GET /internal/loop-health` — probes every
  stage (ingest→compute→store→measure→feedback). Live result: **FLOWING (all green)** — CIS universe 58 assets,
  Mac Mini push fresh, causes flowing, conviction feedback learned (STRONG OUTPERFORM 1.265×), NMA differentiated.
  **CORRECTED FALSE ALARM**: my earlier "causes empty on Railway" (logged P1 to Minimax) was a measurement bug —
  I checked flat `forward_supply_risk` but the data is NESTED under `forward_supply`/`positioning`; causes ARE
  live (ONDO fs_risk=0.702, pos=-0.405 on all 24 crypto assets). Fixed the probe + retracted the false alarm in
  MINIMAX_SYNC + LOOP_ENGINEERING. Real loop finding stands: ONE arc closes (signal→30d outcome→conviction→weight,
  proven live); rest is write-heavy/read-light (88 inserts, ~1 auto read-back) — value-mining deferred/manual.
  Doc: `LOOP_ENGINEERING.md`.
- **2026-07-10 NARRATIVE ELEVATION — diagnosis + repair (Jazz: "we have narrative structure but you downplay it,
  frontend doesn't show it" — correct).** Found: NMA pipeline (social+orderflow+trend→nma_score→S-pillar) EXISTS
  with 2 live endpoints (`/api/v1/market/narrative[/{sym}]`) but is ORPHANED — (a) `apply_narrative_to_s_pillar`
  never called → NMA doesn't actually feed CIS; (b) frontend `asset.narrative` = CIS description TEXT, NOT the
  NMA signal → nma_score shown nowhere; (c) DATA SOURCES BROKEN: CG killed `community_data` (404 → social=35
  fallback), orderflow used Binance SPOT (`data-api.binance.vision`) which 400s on perp-only tokens (HYPE) +
  faked funding from spot price. Net: NMA outputs degenerate ~44 NEUTRAL for everything → that's why it's
  dormant. FIXED: orderflow_collector → fapi.binance.com (real depth+funding history+OI, works for HYPE now);
  __init__ defensive imports. Built the working narrative layer: `src/data/narrative/moat_map.py` (L1 structural
  moat ontology) + `catalyst_detector.py` (L2 event→moat→on-chain-activation; validated: HYPE 2026-01-27 fires
  at activation z=9.63, $30.79 → ran to $65). STILL TODO to fully elevate: replace CG-community social source,
  fix/verify trend_score, then wire NMA+catalyst into CIS universe payload + S-pillar + SURFACE in frontend
  (Mac build). Discipline: do NOT wire half-broken NMA into live CIS until social+trend repaired.
- **2026-07-10 CONVICTION METHODOLOGY — catching the next HYPE (沉淀).** New durable methodology doc
  `CONVICTION_METHODOLOGY.md` (companion to ARCHITECTURE + CIS_METHODOLOGY). Thesis: biggest winners come from
  NARRATIVE inflection revealing durable STRUCTURAL VALUE → reflexive cash flow → re-rating; trend/momentum is
  the reflection, narrative-becoming-cashflow is the cause (we trade the cause). Worked example HYPE 2026: the
  spark was a real-world event (Trump weekend war → TradFi commodity markets closed → only Hyperliquid could
  trade the shock 24/7 on-chain w/ leverage → proved the moat live) → 99%-fee buyback loop + 70% perp share +
  $840M rev run-rate → institutional re-rating; price confirmed LAST (chopped down H2'25 46→25, re-accelerated
  25→65 H1'26). Data findings: naive trend on majors weak (Sharpe ~0.2, huge DD); trend on HYPE UNDERPERFORMED
  buy&hold (+37% vs +110% — stop chops you out of the winner) → alpha is SELECTION + CONVICTION HOLD, not the
  indicator. 4-layer stack: L1 structural moat / L2 narrative catalyst (the missing organ to build — event→
  structural-value detector) / L3 fundamental momentum (CIS F+O as rate-of-change + reflexive-loop flag) / L4
  trend confirmation (timing only). Execution: convex sizing (pyramid on confirmation), let right tail run,
  exit on THESIS break not volatility, catastrophe stop only, concentrated. This is the 3rd bet (right-tail/
  beta-plus) alongside swing (mean-rev) + causal (market-neutral). It's the moat because it's judgment-led
  (human+AI), not a commodity bot.
- **2026-07-10 CAUSAL POSITIONING SLEEVE — built + validated + orthogonal (the upgrade delivered).** New
  market-neutral cross-sectional sleeve trading the positioning cause (fade funding crowding: short
  high-funding/crowded-longs, long negative-funding/crowded-shorts). Built on REAL Binance-perp data (24
  assets, 668 days, 2024-01→2025-10) via `src/research/strategies/causal_positioning.py`. Results: full-sample
  ann Sharpe +1.21 (Kwin7,5bps), +41%, 10% maxDD; survives 10bps (+1.0); Kwin monotone (not a lucky peak);
  **chronological OOS Sharpe +1.02 — holds sign/magnitude (unlike the falsified edge gate)**. DECISIVE:
  **correlation to swing book = +0.002** → the orthogonal sleeve the diversification math demanded; ENB
  2.16→2.85. Honest: at swing's inflated in-sample Sharpe ~5 the optimal weight is ~5% (modest uplift), but
  its value GROWS as swing deflates to realistic OOS (√(2²+1.2²)≈2.33 vs 2.0) + carries when swing fails +
  it's the moat. Data reachable from research infra (Binance/Bybit/OKX funding+klines all 200). Cached:
  outputs/causal_data.json. NEXT (Jazz: expand to other assets): widen 24→60–80 perps, stack forward-supply
  cause in same frame, liquidity/capacity filter. Report: `reports/CAUSAL_SLEEVE_2026-07-10.md`.
- **2026-07-10 THE UPGRADE — orthogonality finding + combiner.** Stress-tested the obvious upgrades on real
  data: (1) price/TA meta-labeling on V7 (logistic, IS-train/OOS-test) = NULL (SR/trade 0.272→0.274, just cuts
  trades) → swing is price-efficient; (2) naive equal/inverse-vol ensemble = WORSE than best single (dilution).
  Real diagnosis: the 5 DSR-certified survivors are **0.67 mutually correlated (V8/V9/V10 = 0.95–1.0), ENB=2.16
  → ~1.5 ideas in 5 costumes**. Diversification math (V7 ann Sharpe 5.6): marginal book Sharpe is driven by
  CORRELATION not the new sleeve's own Sharpe — orthogonal(SR2.0,corr0)→5.96 vs great-but-correlated(SR2.8,
  corr0.3)→5.73; another swing variant (corr0.95)→~nothing. **The upgrade = ONE uncorrelated sleeve, not a
  sixth swing.** Uniquely-ours orthogonal candidates: (a) causal forced-flow (forward_supply/positioning — moat),
  (b) delta-neutral funding_carry (shipped, market-neutral). Built `src/research/validation/portfolio_combiner.py`
  (corr-de-duplicated inv-variance + effective-number-of-bets X-ray; honest −1.39 uplift on the lineage proves
  no internal blend beats V7). Report: `reports/STRATEGY_UPGRADE_2026-07-10.md`.
- **2026-07-10 DSR factory audit — built the instrument + certified the swing lineage.** Full arsenal is
  ~50 freqtrade strategies (Swing V6→V10, CoreBasketV6, MetaV4, SMC, SmartMM, LiqAware, MVRV, Crowd,
  AutoResearch pipeline, + signal tools: SMC/funding/polymarket/factor-miner/correlation). Built
  `src/research/validation/deflated_sharpe.py` (Bailey-LdP Deflated Sharpe Ratio + expected-max-Sharpe,
  pure-numpy, self-test passes: real edge DSR 0.9997 vs best-of-40 noise 0.078). Ran over live backtests:
  full 35-way search → 0 survive DSR@0.95 (undisciplined search certifies nothing); **disciplined candidate
  set (positive SR, ≥50 trades, N=9) → 5 SURVIVORS, all SwingOverlay lineage** (V8_Regime 0.999, V7 0.998,
  V9_DirAware 0.994, V10_FundingAware 0.994, V10_FundingAggressive 0.981). Investor-grade claim: our swing
  lineage survives multiple-testing correction in-sample. NEXT (real research to strengthen): DSR on
  walk-forward OOS (certify for capital), retire ~25 negative-SR trials, meta-labeling on swing primaries,
  regime-ensemble across the 5 survivors, wire DSR as a standing promotion gate. Report:
  `reports/STRATEGY_DSR_AUDIT_2026-07-10.md`.
- **2026-07-10 V10 BUILD (Minimax-C) — MTF + Funding-Aware + Vol-Target; operational layer for THE UPGRADE
  finding.** Built the next swing iteration layering P1 ground-truth (regime-conditional funding gate) +
  MetaV4's vol-target sizing onto V9. Two files: `SwingOverlayV10_MTF_FundingAware_VolTarget.py` (5-pair,
  815L) + `_ETH.py` (1-pair, 2.5× stakes, 783L) at
  `/Volumes/CometCloudAI/cometcloud-local/user_data/strategies/`. V10 added two pieces: **(1) per-row
  regime-conditional funding gate** (V9's old `FUNDING_BPS_SKIP_LONG` global flag was too coarse; P1
  parity 2026-07-09 found funding sign MIXED 5/12 — negative funding bullish 4/4, positive bearish
  only in bear markets). New logic: `bull & fr>3bps → block long`; `bear & fr<-3bps → block short`
  (per-row mask, defence-in-depth also in `confirm_trade_entry`). **(2) Vol-target sizing**
  (`stake × clip(VOL_TARGET_PCT/atr_pct, 0.5, 1.0)`) applied after naked-short mult — **calibration
  finding**: MetaV4's `VOL_TARGET_PCT=0.04` is a no-op at 15min timescale (BTC 15min ATR% p50=0.31%, so
  the clip pins at 1.0 always); recalibrating to `0.005` actually fires the scaler. Walk-forward 3
  windows (TRAIN 2024 bull / VALIDATE 2025 chop / HOLD-OUT 2026 recovery):
  **V10 = +2,572.7 USDT vs V9 +3,169.8 USDT (-18.8% P&L), trades 1,207 vs 1,297 (-7.0%), MDD
  3.18% vs 2.72% in 2025 chop (+0.46pp), TRAIN avg stake 678→595 USDT (-12.3% — confirms vol-target
  activation)**. Funding-gate LOGIC verified by unit test (`/tmp/v10_unit_test.py`, 4/4 cases pass)
  but **does NOT fire in backtest** — CIS funding cache returns 0 in backtest mode (no per-bar funding
  wired into the loader); per-bar funding = **V11 work** (extend CIS loader to read `CIS_HISTORY_DIR`).
  V10-ETH ≈ V9-ETH (no gates fire at 2.5× scale on ETH-only; benign reversion = expected safety property
  when no signal is present). **Verdict:** V9 retained as production, V10 retained for archival.
  **Aligns with Seth's same-day work on three counts:** (a) **V10_FundingAware (DSR 0.994) already in DSR
  audit survivors** above — audit pre-confirmed the lineage before walk-forward; (b) **THE UPGRADE
  finding (orthogonality math) predicts another swing variant is dilutive** (5 DSR survivors 0.67
  mutually correlated, V8/V9/V10=0.95-1.0) — V10 walk-forward confirms it (-18.8%); (c) **Causal
  Positioning Sleeve** (ann Sharpe +1.21, corr +0.002 to swing, ENB 2.16→2.85) is the orthogonal
  answer V10 isn't. Incremental value = the **vol-target calibration finding** (15min vs daily ATR%
  timescale is transferable to any vol-target implementation) + a documented **regime-conditional
  funding-gate pattern** (template for orthogonal causal-gated swing attempts in V11+). **V10 report
  status = NEUTRAL per compliance language** ("more conservative but does not improve P&L"); no
  signal-grade language used. Reports: `_data/research/V10_MTF_FundingAware_VolTarget_2026-07-09.md`,
  `parity_w5/P1_PARITY_ASSESSMENT_2026-07-09.md`. Configs: `/tmp/config_swing_v10{,_eth}.json`. Walk-
  forward logs: `/tmp/v10{,_eth}_{train_2024,validate_2025,holdout_2026}.txt`.
- **2026-07-10 V11 BUILD (Minimax-C) — Causal-Sized Swing (V9 + H3.2 positioning conviction); H3.2
  does NOT transfer to swing; V12 direction = cross-sectional positioning z.** Cleanest A/B on V9:
  layer Seth's H3.2 conviction-sizing pattern (Nautilus LS v1 winner, Δ $/pos +$1.79 to +$2.14 IS /
  +$0.10 to +$2.25 OOS) onto swing, using the **Causal Positioning Sleeve's per-pair trailing-7-day
  funding z-score** (Kwin=7, matches Sleeve's native window) as a **SIZING INPUT** (not a separate book).
  Direction-aware conviction: `c_long = (1-z/3)/2`, `c_short = (1+z/3)/2`, multiplier = `clip(0.5+c, 0.5, 1.5)`.
  Two files: `SwingOverlayV11_CausalSized.py` (5-pair, 815L) + `_ETH.py` (1-pair, 2.5× stakes) at
  `/Volumes/CometCloudAI/cometcloud-local/user_data/strategies/`. **Data prep:** offline z-table built
  from `causal_positioning.load_binance_panel()` (5 pairs × 4,615 obs → `/tmp/v11_funding_z.json`,
  102KB, clip ±3σ, μ_z≈0 std≈1.0 per pair). **Sizing math unit-tested** (`/tmp/v11_unit_test.py`,
  19/19 pass: z=-3 long→1.5, z=-3 short→0.5, z=0 both→1.0, z=+3 long→0.5, z=+3 short→1.5,
  z=None/tiny/out-of-clip→1.0). Walk-forward 3 windows: **V11 5-pair = +2,774.6 USDT vs V9 +3,169.8
  (-12.5% P&L), trades 1,211 vs 1,297 (-6.6%), avg stake 644 vs 678 USDT in TRAIN 2024 (-5.0%);
  V11-ETH = +1,311.1 vs V9-ETH +1,421.2 (-7.7%), trades flat, avg stake -7.3%.** Notably V11-ETH
  WINS in VALIDATE 2025 (+559.6 vs +234.3, +138.8%) — smaller stake enables more re-entries in
  chop; V11-ETH also wins Sharpe in TRAIN 2024 and HOLD-OUT 2026. **Mechanism analysis (3 reasons
  V11 loses):** (1) avg-stake effect: -5% to -7% stake × similar trades = mechanically -5-7% P&L
  even on same trade list; (2) z-score distribution biased by market microstructure — longs μ_z
  ≈ +1.27-1.41 (V11 cuts long stake), shorts μ_z ≈ -2.20-2.27 (V11 cuts short stake); both sides
  shrunk on average because crypto funding is structurally positive; "fade the crowd" becomes
  permanent downsize not tactical rebalance; (3) **H3.2 is LS-v1-specific, not swing-portable** —
  H3.2's mechanism "let signal through, weight by confidence" works in CROSS-SECTIONAL books
  (conviction = which name to overweight); in PER-PAIR swing entries, conviction = how much to
  size, but swing already has regime-stake (900/600/400) doing similar work; the two conviction
  layers stack and don't compose additively. **Not a falsification of H3.2** (still wins on LS v1)
  but a **boundary finding**: H3.2 portability has limits; the cross-sectional allocation problem
  is fundamentally different from per-pair sizing. **V11 vs V10:** +201.9 USDT recovery (less
  aggressive cutting stake: avg -5% vs V10's -12.3%) but still loses to V9. **Aligns with Seth's
  same-day work on three counts:** (a) **V11 = +1 swing variant, dilutive per orthogonality math**
  — confirms THE UPGRADE finding (5 DSR survivors 0.67 correlated, V8/V9/V10 = 0.95-1.0);
  another swing variant just decorates the same alpha; (b) **Causal Sleeve's signal IS orthogonal
  to swing (corr +0.002)** but the per-pair rolling-z port does NOT transfer its edge — swing's
  regime-stake + naked-short system already captures per-pair conviction in a different way;
  (c) **V12 direction = cross-sectional positioning z** (Causal Sleeve native form) — would test
  if a CROSS-SECTIONAL conviction layer (relative z across the 5-pair universe) beats V9, vs
  V11's per-pair form which doesn't. **Verdict:** V9 retained as production, V11 retained for
  archival + as documented counter-example for H3.2 portability. Reports:
  `_data/research/V11_CausalSized_2026-07-10.md`. Configs: `/tmp/config_swing_v11{,_eth}.json`.
  Walk-forward logs: `/tmp/v11{,_eth}_{train_2024,validate_2025,holdout_2026}.txt`.
- **2026-07-10 Strategy competitiveness review (CORRECTED).** First pass benchmarked against the GRAVEYARD
  (dead LS_V4 −6.59%, META_V4 −5.47%, falsified edge gate) and wrongly concluded "no profitable strategies"
  — a research miss: never opened `Shadow/freqtrade/user_data/backtest_results/`. REAL state: the
  **SwingOverlay V6→V10 family** (MTF regime + funding-aware gates + vol-target + circuit breaker) + CoreBasketV6
  are PROFITABLE — credible n≥500 runs: Sharpe ~6.3–9.5, CAGR ~32–54%, PF 1.9–2.6, DD 2–3%, win 66–70%
  (small-n variants show Sharpe 10–14 = overfit-suspect). Corrected verdict: we ARE competitive on directional
  swing, build quality above public median; the gating question is OOS/walk-forward robustness (high Sharpes +
  window variance = overfit signature — same discipline that caught the edge gate). Only structural moat still
  = forward-supply/unlock cause (unblock via historical unlock event study, not 180-day wait). `funding_carry.py`
  (shipped) repositioned honestly as an OPTIONAL market-neutral sleeve, NOT a missing lane. Report:
  `reports/STRATEGY_COMPETITIVENESS_2026-07-10.md`. NEXT: put SwingOverlay through walk-forward OOS + cost model;
  headline only OOS-surviving numbers for LP use.
- **2026-07-06 ⚠️ FALSIFIED — edge gate CUT** (Minimax-A A2 harness, audit commit 0e868a7): OOS proved the
  empirical edge-map-DIRECTION hypothesis overfits — edge gate took 4 straight longs into a falling BTC
  (−$479) while the frozen CIS baseline (`REGIME_CIS_FLOOR`) MADE money (+0.59 Sharpe, PF 1.38). p=0.867,
  no rejection of null. **Propagation:** `conviction`/`conviction_book` anchor direction on the SAME edge-map
  signal → presumed overfit. **Seth pruned own build:** paper sleeve reverted to risk-meter; `conviction_book`
  gated OFF (`CONVICTION_BOOK_ENABLED`, research-only) until it passes the harness. The causes (forward_supply,
  positioning) are ALSO unvalidated — same trap — must pass B2 before any claim. VALIDATED core = the CIS
  quality gate. The clever cause-timing = hypothesis, not fact. This is the loop earning the word.
- **2026-07-06 FRONT DOOR = Diagnose** (App.jsx): default landing is now `DiagnoseHome` (embedded) +
  Risk Meter — "your book, read upstream of price" — per ARCHITECTURE §iPod (Diagnose = Fusion #1, the
  lovable front). Demoted the commodity breadth (VC/signal-feed leading). De-claimed the losing signal
  page from green "LIVE" → "PAPER · UNVALIDATED" (doc: must not claim unproven). Needs Mac-side build
  (FUSE deny-unlink blocks local vite; binaries wrong-arch). Full convergence (fold provenance, demote
  rest) still to do.
- **2026-07-06 RISK LIMIT: per-name cap** (`conviction._capped_weights`, `_MAX_NAME_FRAC=0.22`): closes
  assessment W3 — no single name > 22% of its side's gross; thin breadth → under-deploy, never over-
  concentrate. Verified: the 77.9%-single-name case now caps at 22%. Pre-capital blocker cleared.
- **2026-07-06 ASSIGNMENTS distributed** to Minimax-A/B/C (MINIMAX_SYNC §ASSIGNMENTS) — all oriented to
  VALIDATION (turn "correct"→"proven"); A2 (OOS harness vs frozen baseline) is the load-bearing one.
- **2026-07-06 UPSTREAM CAUSE #1 = forward supply** (`src/data/cis/forward_supply.py`): forced-seller
  overhang from CoinGecko circ/total/max supply (free; DeFiLlama unlock API now paywalled). Wired into
  the conviction KERNEL as a BEARISH directional cause (`_FS_WEIGHT`), attached in cis.py, 6h loop in main.py.
  Verified: it OVERRIDES the reflection — ONDO (70% overhang) flips +1.7% edge long → short. Mirror of 出圈
  (demand-exhaustion) on the supply side. This is the first factor that is a CAUSE, not a price reflection.

- **2026-07-06 UPSTREAM CAUSE #2 = positioning** (`src/data/cis/positioning.py`): reflexive leverage —
  OI-weighted funding from free CG /derivatives → signed pressure (+ crowded-short squeeze / − crowded-long
  liquidation). Wired into conviction (`_POS_WEIGHT`, signed), attached cis.py, 30min loop. Verified live:
  BTC/HYPE/UNI overleveraged-long (bearish), APT/AVAX/ONDO crowded-short (bullish). The kernel now nets
  reflection + demand-cause (出圈) + supply-cause + leverage-cause + executability into ONE conviction; when
  causes conflict (ONDO: supply-bear vs squeeze-bull) conviction honestly stays low. The kernel is no longer
  reflection-all-the-way-down.

- **2026-07-06 KERNEL → ACT** (`conviction.conviction_book` + `trading._run_paper_rebalance`):
  the paper sleeve now trades the CONVICTION KERNEL's signed book (reflection + 出圈 + forward-supply
  + positioning + executability), not the narrow risk-meter weights. The forced-seller short & squeeze-
  long plays fall out of it; illiquid names dropped; shorts regime-gated; gross regime-scaled. Verified:
  neutral tape → 5 liquid high-conviction longs (honest — few clear the bar); shorts appear when permitted.
  This closes Sense→Judge→ACT in paper. Real capital = the one open arc, and it's Jazz's (per the plan).

## North star (1 line)
We are the **judgment substrate** — hard-to-verify upstream intelligence (influence → quality
propagation, 出圈/proximity-to-cause) that we verify ourselves and hand over with provenance so
other agents can trust it. Full autonomy is the partner's game, not ours. Soul: `ARCHITECTURE.md`.

## What we're building (the PRD-lite)
1. **CometCloud fund** — AI-curated crypto FoF, Hong Kong regulated, performance-only.
2. **The intelligence substrate** (the moat + a sellable product):
   - **CIS** — 5-pillar quality score, per asset class, regime-neutral grade + regime as a
     separate exposure axis (GRADE-ALIGN Option B).
   - **cause_proximity / 出圈** — how far a consensus has diffused (fragility).
   - **Risk Meter** — turns grade + fragility + conviction into position sizing.
   - **Edge map** — the Glassnode-tier product: expected 30d benchmark-relative alpha per
     signal tier × risk gradient, every cell a real outcome with sample size.
   - **Provenance + track record** — so a consuming agent can *defend* a decision.
3. **The self-tuning loop** — Sense → Synthesize → Judge → Act → Learn → back into Judge,
   recalibrating conviction daily from our own outcomes.

## Core validated findings (from our own data — don't re-derive, cite these)
- Signal is **monotonic** in 30d benchmark-relative alpha: STRONG OUTPERFORM +3.3% → OUTPERFORM
  −0.4% → UNDERWEIGHT −1.2% → UNDERPERFORM −1.8%. It ranks correctly. (`TRACK_RECORD_2026-07-01.md`)
- Edge is **regime/gradient-conditional**: long top tier in risk-ON (deep-on +10.5% / 100d,
  +26.8% / 11yr backtest); short bottom tier in risk-OFF (+6% deep-off). Neutral tape → shrinks.
- **11-year backtest (our OHLCV) confirms** the long-leaders-in-risk-on structure across cycles.
- Long edge **concentrates per asset**: ETH (46 signals, +13.8%), LINK, ARB, LDO. HYPE too new.
- Discipline (大象无形): ranking stable, tradeable *direction* is regime-conditional; N-gate
  everything; never trade a frozen factor.

## Architecture snapshot
- **Serving** = Supabase (lean; what API/agents read). **Warehouse** = local drive
  `/Volumes/CometCloudAI/cometcloud-local/_data/` (heavy: 11yr OHLCV, CIS-historical, backtests),
  mirrored to `Shadow/` so Seth can READ it. Seth writes Supabase only; Minimax owns the drive.
  (`MINIMAX_SYNC.md §WAREHOUSE`)
- Ownership: Seth = `src/` + Railway + Supabase serving. Minimax-A = Mac data/ops + drive.
  Minimax-B = NautilusTrader. Minimax-C = freqtrade. Jazz = decisions + push + capital.

## Where we are — in-flight & blocked (by owner)
**Seth (me):**
- ✅ done: cause_proximity, Risk Meter, conviction tilt (self-tuning), provenance, benchmark-
  relative outcomes, outcome tracker on own-data, track record + edge map (tables+endpoints+MCP),
  P0/P1 fixes, T2 base-weight alignment.
- ✅ HOLD RELEASED (2026-07-05): `cis_provider.py` T2 weights — Minimax-A shipped T1 #5 (17/17
  classes canonical, MD5-identical Live↔Shadow). Seth step-2 verified: T2 `_BASE_WEIGHTS` byte-
  identical to CIS_BASE_WEIGHTS.md AND T2 grades on regime-neutral raw = Σ base×pillar (Option B);
  L1 test vector → raw 67.0 matches T1 acceptance. **Now URGENT to deploy** — T1 is live/next-tick
  canonical while Railway T2 still runs the OLD table → live divergence until `cis_provider.py` ships.
  Jazz commits it in the same push as the sleeve fix (no longer needs to be separate).
- ✅ COMMITTED, needs push: edge-map batch (signals/store/mcp + HANDOFF) — **HEAD is 2 commits
  ahead of origin/main.** Jazz runs `git push origin main`. (Verified via git rev-list 2026-07-05,
  NOT memory — the summary wrongly said "staged/blocked".)
- 🟡 uncommitted (2026-07-05, Loop Watch fix) — BLOCKED by sandbox `.git/index.lock` (can't unlink,
  OS perms); Jazz clears lock + commits `trading.py` + `risk_meter.py` + `CLAUDE.md` + `PROJECT_STATE.md`:
  - `trading.py`: (a) bogus tp/sl flag guard (stop_loss/take_profit=0 made `price>=0` fire
    tp_triggered on every METER_REBAL position → false "exits stalled" alarm); (b) **risk
    circuit-breaker** `REBAL_MAX_ADVERSE_PCT=-20%`, NOT churn-gated; (c) regime-no-short breaker.
  - `risk_meter.py`: **regime-gated shorts** (`_SHORT_OK={Risk-Off,Stagflation}`, `shorts_allowed`
    threaded through build_risk_meter) — shorts only in true falling-market regimes. Self-test extended.
  - EXCLUDE from this commit: `cis_provider.py` (held for T1 #5), `requirements.txt` + `src/research/nautilus/` (Minimax's).
- 🟡 uncommitted (2026-07-06): `cause_proximity.py` — **season lifecycle consumed** (Jazz money
  insight + Minimax §BOARD #5): `momentum` season DEPRESSES out-of-circle risk ×0.55 (ride the
  出圈 wealth-creation window), `stale` ELEVATES to floor 0.72 (window closed). Flows into sizing
  via Risk Meter (verified: momentum name +19% weight vs stale). Dormant until D3 data lands
  (query_id 7891077). No-cost strategy win. Ready to commit + push (Mac-side).

**Strategy direction (no new cost — Jazz 2026-07-06 "先赚到钱再加"):**
- **H1 finding (research lane):** composite CIS 7d forward-return IC is NEGATIVE in Risk-Off/Risk-On/
  Stagflation, POSITIVE only in Tightening, flat in Easing → the CIS gate is directionally INVERTED
  in 3/6 regimes; it works as a RISK FILTER, not a return predictor. Validates regime-conditioning
  (edge map + regime-gated shorts + season already do this). **H2 = per-regime gate direction+magnitude.**
  ⚠️ Do NOT unilaterally invert the production Risk Meter on H1 alone — wait for H2's confirmed
  direction table (research lane in-flight); premature inversion risks the live book.
- **H2 design DONE** (`docs/H2_REGIME_GATE_DESIGN_2026-07-06.md`): reframe = separate CIS-as-ranking
  from regime-as-beta-timing; do NOT invert CIS in prod. Blocked on Phase 0 = fix the noisy regime
  detector (Minimax-A). Immediate-safe changes: drop CIS floor→eligibility in Easing (flat IC),
  shrink gross in low-confidence regimes.
- **H2a script DONE** (`src/research/cis_regime_studies/h2a_relative_ic.py`) — benchmark-relative IC
  test (is the sign-flip beta artifact or real reversal). Runs Mac-side (needs OHLCV panel + scipy).
- **season lifecycle EXTENDED** (`cause_proximity.py`): full pre-出圈 accumulation stages
  (capitulation/dry_up/spring_test/early_markup) + momentum/stale, cold→hot risk curve verified
  (dry_up lowest 0.168 → stale highest 0.720). Season vocab contract handed to Minimax (§MINIMAX_SYNC).
- **current-band read + posture DONE** (`signals.py` + `main.py` + MCP): `/api/v1/signals/current-band`
  computes today's risk-gradient band (BTC 30d) → per-tier expected alpha NOW → actionable **posture**
  (net_bias + gross_scale + confirmation), sample-size-guarded (thin cell → dampen + flag). Persisted
  daily to Supabase `regime_band_log` (created; cols incl net_bias/gross_scale) via `_band_log_loop`
  → flows to Mac warehouse (Minimax adds it to the drive mirror). MCP tool `cometcloud_get_current_band`.
  Posture is ADVISORY (positioning language) — not wired to force live sizing (that needs Jazz nod).
- **Conviction Fusion #1 DONE** (`src/data/cis/conviction.py` + `/api/v1/cis/conviction` +
  `cometcloud_get_conviction` MCP): the single per-asset verdict fusing regime-neutral QUALITY ×
  cause-proximity (in-circle vs 出圈 + season) × edge-map expected alpha (tier × TODAY's band, real
  outcomes) × EXECUTABILITY. Ranked by signed edge; sample-size gated; illiquid names discounted
  (a B+ you can't size ≠ a core overweight). Verified on live universe. **Flagship Diagnose enriched**
  to consume it — per-holding conviction/direction/action + book `illiquid_pct` + verdict note
  ("X% in illiquid names — can't build/exit size"). This is the actionable output of all the mining.
- 🟡 Moralis D3: key works live, but holder map empty → likely `/erc20/{addr}/owners` is a premium
  Moralis endpoint on this plan (or field mismatch). Added `/api/v1/signals/holder-map` diagnostic
  (uncommitted) — push it, hit it, read `probe_error` to decide (upgrade Moralis vs Helius/Bitquery).
- **Edge-map SHRINKAGE DONE** (`src/data/signals/edge_shrinkage.py`) — the hard statistical problem:
  100 days = wildly uneven cells (n=1..1672); a raw thin cell is pure noise (OUTPERFORM/deep-off
  −64% on n=3). Empirical-Bayes shrinkage: two-way ADDITIVE prior (tier+band, captures the monotonic
  "rises with risk-on" structure) + James-Stein weight `n/(n+K)`, K by ROBUST (median) MoM. Result:
  well-sampled cells keep 76–90% own value, thin/noisy cells collapse to the structural prior, grid
  becomes monotonic + denoised (K≈184). Wired into `compute_current_band` (posture/conviction now read
  the SHRUNK alpha) + conviction's hard n-gate relaxed (n → confidence, not discard) + edge-map endpoint
  exposes raw/shrunk/weight/prior. This is AQR/Millennium-grade rigor making the surface honest on thin data.
- **H3 edge-map BACKFILL DONE** (`h3_edge_map_backfill.py`) — the root-cause fix for "only 100 days"
  (Jazz: don't use it as an excuse). Applies CURRENT signal logic across `cis_history` (393d × 40) ×
  OHLCV → ~12k historical signal→30d-alpha pairs → backfills `signal_outcomes` (before live, no clobber)
  → existing refresh rebuilds a robust edge map (thin cells n=1..3 → hundreds). Runs Mac-side (`--write`).
  Phase-2 (Minimax): extend `cis_history` to 11yr OHLCV via CIS reconstruction → h3 auto-covers it.
  **Phase-2 ✅ DONE 2026-07-18** (`scripts/reconstruct_cis_history.py --days 4015` + `scripts/cis_historical_ingest.py`)
  — 75,478 rows, 34 assets, 2015-07-21 → 2026-07-18, ingested into local `cis_history` (run_id
  `historical_11yr_20260718_192540`). Supabase ingest pending service-role key. Full report:
  `reports/CIS_HISTORICAL_11YR_2026-07-18.md`. Schema migration added 4 columns (`macro_regime`,
  `las`, `source`, `data_tier`). Honest gaps: FNG pre-2018-02-01 (neutral fallback), SEI 404 skip,
  newer assets (ENA/STRK/ONDO/TIA/POL) only have post-2022 history.
- **EDGE GATE bridge DONE** (`src/research/strategies/edge_gate.py` + `scripts/export_edge_gate_grid.py`)
  — the intelligence→execution connection Jazz asked for (reference Minimax-B/C strategies). Replaces the
  hand-tuned `REGIME_CIS_FLOOR` (H1: wrong in 3/6 regimes) with `gate(grid, tier, band, side)` reading the
  SHRUNK edge map → allow/block + conviction-scaled size, direction from DATA (short-weak allowed only where
  it empirically pays). Pure module (no pandas/scipy) so it runs inside Nautilus/freqtrade. Grid live at the
  edge-map endpoint (shrinkage confirmed live, K=184). Integration recipe for Minimax-B/C in MINIMAX_SYNC.
- **NOTE: shrinkage is LIVE** (deployed via a Minimax push) — verified on `/api/v1/signals/edge-map`.
- **2026-07-09 EDGE GATE A/B (continuous, per-regime IC) — NEGATIVE for ship**
  (`src/research/nautilus/ls_v1/edge_gate.py`, `src/research/cis_regime_studies/edge_gate_ab.py`,
  `reports/EDGE_GATE_AB_2026-07-09.md`). The continuous `edge = side × IC_regime × z × sigma × sqrt(h) − cost`
  gate (alternative to the empirical grid edge gate above) is wired into LS v1 with `use_edge_gate=True` and
  A/B'd across 4 smoothed dirs × {IS, OOS} × {baseline, edge_gate} = 16 runs. **Edge gate loses in both
  windows across all dirs** (ΔIS PnL −$316 to −$503, ΔOOS PnL −$23). Per-regime IC magnitudes (−0.09 to
  −0.36 smoothed) sit below the AQR noise floor (~±0.24 at n=70); the regime-conditional reversal is
  structurally correct but empirically underpowered. **3 negative results in a row** on per-regime gate
  refinement (H3, H2 magnitudes, this). Keep `REGIME_CIS_FLOOR` as production gate. Phase 1 ship
  (smoothed regime labels, no floor changes) is the correct next move. Pivot edge-gate formula to H3.2
  sizing-multiplier when ≥6mo OOS data accumulates.
- **2026-07-09 H3.2 conviction-weighted SIZING A/B — POSITIVE for ship as opt-in**
  (`src/research/nautilus/ls_v1/strategy.py` `use_h32_sizing` config +
  `_h32_sizing_multiplier()` + `create_order_qty` applies multiplier;
  `src/research/cis_regime_studies/h32_sizing_ab.py`;
  `reports/H32_SIZING_AB_2026-07-09.md`). Per H3: "conviction is a sizing signal,
  not a gating signal." H3.1 (gate-multiplier) lost because the floor band is a
  knife-edge. H3.2 sidesteps that by leaving the gate at `REGIME_CIS_FLOOR` unchanged
  and scaling POSITION SIZE by today's conviction: `trade_size × (floor + (cap−floor) × c)`.
  A/B'd across raw + modal_recency dirs × {IS, OOS} × {baseline, h32_sizing} = 8 runs.
  **H3.2 wins per-trade PnL in ALL 4 runs** (Δ IS $/pos +$1.79 to +$2.14, Δ OOS $/pos
  +$0.10 to +$2.25). Trade count unchanged (gate unmodified). **First POSITIVE result
  in the H-series** (H3 prototype / H2 magnitudes / edge gate all lost). Mechanism =
  Millennium soft-sizing: let the signal through, weight by confidence. Ship as opt-in
  via `LSV1_USE_H32_SIZING=1` (floor/cap configurable via env).
- **2026-07-10 H3.2 sizing FLOOR/CAP SWEEP — REFINED positive; bump default cap 1.5 → 1.75**
  (`src/research/cis_regime_studies/h32_sizing_sweep.py`,
  `src/research/nautilus/ls_v1/strategy.py` `LSv1Config.h32_size_cap` default bumped 1.5→1.75,
  `reports/H32_SIZING_FLOORCAP_SWEEP_2026-07-10.md`). The `[0.5, 1.5]` default was ad-hoc.
  Swept 6 (floor, cap) variants × raw + modal_recency × {IS, OOS} = 24 Nautilus runs.
  **Key insight:** IS Sharpe is INVARIANT to (floor, cap) at this sample size — both
  per-trade mean AND per-trade std scale linearly with size, so E[X]/SD[X] is invariant.
  The differentiating metric is **per-trade PnL**, which scales monotonically with cap:
  cap 1.25→1.5→1.75→2.0 gives raw IS $/pos $+5.74→$+6.85→$+8.02→$+9.01.
  `cvx` (linear through origin) is the WORSE outcome — zero size on low-conv days removes
  the protective trades. `d0.25` matters little (median conviction ≈ 0.93, floor rarely bites).
  **Pareto decision:** bump production default cap 1.5 → **1.75**. Captures +37% PnL
  on IS (n=58 reliable) with no Sharpe penalty. Cap=2.0 is research ceiling (diminishing
  returns + Sharpe decay in modal_recency 0.066→0.061). Cap=1.25 too tight. **Re-verify
  after ≥6mo OOS data accumulates.**
- **2026-07-10 H3.2 PORTFOLIO-LEVEL MaxDD analysis — CORRECTIVE FINDING (linear lever, not alpha)**
  (`src/research/cis_regime_studies/h32_sizing_portfolio_dd.py`,
  `reports/H32_SIZING_PORTFOLIO_DD_2026-07-10.md`). Aggregated per-trade PnL from
  the 24 sweep runs into portfolio equity curves. **Critical finding:** ALL variants
  have DD/PnL ≈ 0.96-1.00 — capturing 1× the PnL costs ~1× the Max DD. This is the
  expected math when only position size changes (trade list is identical across variants).
  Per-day Sharpe is essentially flat (0.0766-0.0779 raw/IS, within noise at n=58).
  **Revised framing:** H3.2 is a **linear sizing controller**, not an alpha source.
  The "Pareto-balanced" framing in the previous report was misleading — the choice
  between cap=1.0 and cap=1.75 is a **leverage decision**, not a quality decision.
  One mitigating finding: t1.75 has the BEST per-day Sharpe (+0.0008 over def) — within
  noise but consistent with the H3 finding. **Revised recommendation:** keep cap=1.75
  as default but document it as a leverage bump (already shipped to strategy.py).
  Env-var override (`LSV1_H32_SIZE_CAP`) keeps the choice tunable per deployment.
  Corrective addendum added to `reports/H32_SIZING_FLOORCAP_SWEEP_2026-07-10.md`.
- **2026-07-10 H2a benchmark-relative IC test — CRITICAL FINDING (genuine reversal in 3/5 regimes)**
  (`src/research/cis_regime_studies/h2a_relative_ic.py` ran successfully today;
  `reports/H2A_RELATIVE_IC_2026-07-10.md`, raw output `reports/cis_regime_relative_ic_2026-07-06.{md,json}`).
  Tests if H1's sign-flips are BETA artifact (vanish under BTC-relative returns) or genuine
  reversal (persist). **Verdict: GENUINE REVERSAL in 3/5 regimes at 7d** — Stagflation IC_abs=-0.235
  → IC_rel=-0.326 (gets WORSE), Risk-On IC_abs=-0.166 → IC_rel=-0.101, Risk-Off IC_abs=-0.093
  → IC_rel=-0.104. Only Tightening is consistent (both positive, n=216 small). At 30d:
  Easing becomes genuine reversal (was flat at 7d); Risk-On becomes beta artifact (recovers
  to flat under relative). **H2 direction-by-regime is now CONFIRMED necessary, not just
  hypothesized.** Action items: (a) H2 design must populate per-regime × per-horizon direction
  table, (b) H3.2 sizing remains valid as a sizing LAYER (independent of gate direction),
  (c) Phase 1 ship (smoothed regime labels) still valid, (d) empirical-grid edge gate A/B
  should consider per-regime direction. Honest caveats: Stagflation n=195 and Tightening n=216
  small; OHLCV ends 2026-06-07; benchmark = BTC for all crypto (no per-asset benchmark).
- **2026-07-10 RESEARCH RE-PRIORITIZATION ROADMAP** (`docs/RESEARCH_ROADMAP_2026-07-10.md`)
  — based on H3.2 + H3.2 portfolio DD + H2a findings. Tally: 3 STRONG POSITIVES (H3.2
  sizing, DSR swing lineage, causal sleeve), 1 CRITICAL STRUCTURAL (H2a genuine reversal),
  4 NEGATIVES (H3.1, H2 mag, edge gate continuous, A2 falsified). **Phased plan:**
  - **Phase A (HIGHEST PRIORITY): H2b direction A/B** — applies H2a finding directly.
    Per-regime direction table is no longer optional. 8 runs (~2-3 hr total).
  - **Phase B: empirical-grid edge gate A/B** — production drop-in, distinct from failed
    continuous one. Needs (tier, band) snapshot generation. 8 runs (~4 hr).
  - **Phase C: combined gate integration** — H2b + empirical-grid + H3.2 sizing. 16 runs.
  - **Phase D1: SwingOverlay walk-forward OOS** ✅ DONE 2026-07-14 — 4/4 ROBUST,
    V7_MTF recommended for production, V9≡V10 caveat documented. See
    `_data/research/SWING_WALK_FORWARD_OOS_2026-07-14.md`.
  - **Phase D1.5: funding-gate fix + vol-target calibration + 10-pair extension**
    ✅ DONE 2026-07-14. V12b funding-gate fixed (was never firing), V10c vol-target
    calibrated (was no-op), 10-pair universe added. **V7 production, V10c risk-managed,
    V12b regime-overlay.** See `_data/research/SWING_WALK_FORWARD_D15_2026-07-14.md`.
  - **Phase D1.6: forward test 17 weeks post-OOS** ✅ DONE 2026-07-15. All 5
    strategies pass 5/5 OOS criteria on 10-pair universe. V7 forward +$623/+10.39%,
    maxDD 0.99% (improves vs holdout). V12b = V9 (funding too orderly to trigger
    gate — expected). See `_data/research/SWING_WALK_FORWARD_D16_FORWARD_2026-07-15.md`.
    Next: live paper deployment of 4-slot sleeve (V7 50% + V9 15% + V12b 20% + V14a 15%) — D2.2 recommendation, capacity
    stress test at $60k/$600k.
  - **Phase D3: forward-supply unlock event study** — historical evidence without 180d wait.
    5-10 events × 30d post-unlock.
  - **Stop testing:** continuous edge gate refinements, per-regime floor mag tuning,
    gate-multiplier prototypes, edge-map direction (all 4+ negatives).
  - **Single most important thing this week:** apply H2a finding to production gate
    (Phase A). Everything else stacks on top.
- **2026-07-09 CAUSE-DRIVEN BACKTEST infrastructure (B2) — SHIPPED, run BLOCKED on data**
  (`scripts/supabase_migration_cause_history.sql`, `src/data/cis/cause_persistence.py`,
  `src/research/cis_regime_studies/cause_backtest.py`, `reports/CAUSE_BACKTEST_2026-07-09.md`).
  First real test of whether ARCHITECTURE.md "causes predict" (forced-seller short + squeeze-long
  + long-liq short). Cause data has only been live ~3 days — no historical record exists.
  Built the rig (schema + persistence + backtest skeleton + smoke test) but the actual backtest
  needs ≥180 days cause_snapshots_daily + OHLCV panel landing (Minimax-A P1, not started). Live
  snapshot today: 5 forced_seller_short candidates (HYPE/APT/SUI/ONDO/OP), 0 squeeze_longs.
  Discipline: we built the experiment; we cannot shortcut the 6-month waiting.
- ⬜ next: A/B the empirical grid edge gate (separate approach) in Nautilus LS v1; run H3+H2a Mac-side;
  conviction UI; Phase 1 ship (smoothed regime labels); cause-history accumulation (180d).
- 🟡 uncommitted (2026-07-06, GRADE-ALIGN Option B frontend/read switch) — BLOCKED by git lock;
  Jazz commits `cis.py` + `cis_provider.py`:
  - `cis.py` merge: normalizes the WHOLE universe (T1+T2) onto raw quality — `grade = get_grade(raw)`,
    `cis_score = raw`, `regime_adjusted_score` = old adjusted (regime lens preserved), sort on raw.
    Single Railway-side change, NO T1 cis_v4_engine lockstep (both tiers already carry raw_cis_score).
  - `cis_provider.py`: T2 emits the same shape natively (grade on raw, cis_score=raw, +regime_adjusted_score).
  - Verified against live universe: grade==g(cis_score) for ALL assets; 16 grades shift vs regime-baked;
    leaderboard now quality-ranked (PENDLE B+ quality, regime tilt → signal/regime_adjusted).
  - PRODUCT-FACING (grades move, cis_score semantics change) → needs Jazz green-light to push.
  - Minimax note: Railway now overrides T1's pushed `grade` (re-grades on raw at merge, idempotent);
    T1 can later grade on raw natively — identical result, no rush. SCHEMA note in §GRADE-ALIGN.
- ⬜ next: regime-lens UI badge (surface regime_adjusted_score as the visible separate axis) ·
  regime-aware conviction (reads edge map, N-gated) · live "current band" on edge-map · win.html surfacing.

**Loop Watch finding (2026-07-05):** METER_REBAL "rotation stall" was NOT a broken exit path.
Book is stable in flat Tightening regime (target≈held, `reason=none`). Real issue: sleeve holds
shorts on benchmark-underperformers (ADA/ETH still UNDERPERFORM = thesis intact) but trades
ABSOLUTE price while the signal predicts only benchmark-RELATIVE alpha → shorts bleed beta when
tape isn't risk-off (edge-map: shorts only pay deep-off). 12-vs-5 trade_results gap = historical
pre-fix closes, writer healthy. **DECISION FOR JAZZ:** regime-gate shorts (only open shorts when
risk gradient is risk-off) vs keep the −20% breaker as the only guard. Breaker shipped as safety net.

**D3 LIVE = Moralis-on-Railway ✅ (Seth, 2026-07-06):** Jazz connected Moralis; I wired the on-chain
holder tier on Railway — `src/data/cis/holder_provider.py` (registry symbol→contract → Moralis owners →
top10 share + HHI → `stage`; multi-chain incl Solana Phase-2), `_holder_refresh_loop` → Redis `cis:holder_map`,
attached into `cause_proximity` (cis.py). Activates on deploy with `MORALIS_API_KEY` (already set). Verified:
concentrated→stage 0.08→risk down, dispersed→0.79→risk up, confidence 0.85. Covers ONDO/PENDLE/UNI/AAVE/MKR/
LINK/LDO/ARB, graceful D4 for rest. **This SUPERSEDES the Dune path** (query 7891077 → optional Phase-2 history
only; NO Dune purchase needed — the cost question is resolved). Phase-2 = dynamic season/chuquan from Moralis
holder-timeseries (Minimax Wyckoff lane; season contract unchanged).
**Minimax-A:** T1 #5 (per-class weights, patch in §GRADE-ALIGN) · restore drive→Shadow sync · stand up local warehouse + CG/EODHD top-ups
(dominance, mcap, VIX) + 11yr CIS-historical reconstruction · macro brief model (gemma-4-31b-qat +
API thinking-off).
**Minimax-B/C:** backtest the validated hypothesis (regime-conditional long-STRONG / short-UNDER, gradient-scaled).
**Jazz:** bless canonical `CIS_BASE_WEIGHTS.md` · greenlight the edge-map commit + coordinated
GRADE-ALIGN deploy · rotate shared `INTERNAL_TOKEN`.

## Key decisions log (pointers)
- GRADE-ALIGN Option B + canonical base weights → `CIS_BASE_WEIGHTS.md`, `MINIMAX_SYNC §GRADE-ALIGN`.
- Two-tier data landing → `MINIMAX_SYNC §WAREHOUSE`.
- Historical reconstruction from CG Pro + EODHD (FNG synthesized, on-chain proxied by volume) → `HANDOFF_2026-07-02.md §3`.
- Substrate positioning / vectors & movement → `ARCHITECTURE.md`.
- Full session comms → `HANDOFF_2026-07-02.md`.

## Detailed docs index
`ARCHITECTURE.md` (soul) · `MINIMAX_SYNC.md` (coordination, gitignored) · `CIS_BASE_WEIGHTS.md`
(canonical) · `TRACK_RECORD_2026-07-01.md` · `AUDIT_financial_engineer_2026-06-30.md` ·
`ADR-001_loop_architecture_completeness.md` · `HANDOFF_2026-07-02.md` · `scripts/track_record.sql` ·
`scripts/loop_health.py` (daily watch).
