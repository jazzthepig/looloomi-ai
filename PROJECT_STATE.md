# PROJECT_STATE.md — the living single source of truth

**Last updated:** 2026-08-18 (Seth/Cowork lane) — **S-172 REFUTED the resonance window.**
"Depth arrives before price so you can size in early" is false and *backwards*:
depth-up/price-flat = **−1.85% 20d excess vs hold-the-panel, t = −5.23**, and it gets worse with
size (−2.31% at $10k → −7.54% at $100M). Depth accompanies price 3.3× more often than it precedes
it. **One sleeve saved, graveyard +1** — Mac-A's P3 NarrativeMomentum loses its main cause.
**S-173** started two forward clocks (`depth_divergence_log` inception 08-18 gate 10-17,
`holder_concentration_history`): both directions were blocked on the same thing — *nothing was
ever stored*. The first write exposed that the **Crypto feed is 10 days stale** (25 of 262
symbols). **S-171** Asset Radar blank page (import lost in the App.jsx split). **S-169** Mac-lane
write wrappers + the RPC was dropping `measured_dims`. **S-168** production was READ-ONLY
08-12→08-17 until `APP_ROLE=production`; ① book marks again.
> ⚠️ **S-168 is used twice** — here for the read-only production and, below, by the dashboard
> lane for R540-R547. Neither had claimed a ledger heading. See the collision note at the top of
> `REFUTATION_LEDGER.md`; one of them needs a new number. Not renumbered unilaterally.

**Last updated:** 2026-08-18 — **S-168: R540-R547 "production book" FAILS on raw LIQUID16 wide** (8 of 9 legs negative without BTC-MA gate; B10_R547 SR=+2.5 claim was BTC-MA-conditional, not unconditional). **★ NEW ANCHOR: R554 taker imbalance (imb7 K3 h21) on LIQUID16** — only signal in R540-R555 series that survives LIQUID16-wide-no-gate (SR=+1.035, +350.68%, DD=-58.98%, ρ<0.10 with every other leg, cost breakeven >50bps). **R70 + R19 strategies UNAFFECTED** — the CLAUDE.md "two profitable" pair remains valid. **S-166** Supabase tables fixed. **S-165 cold-start split**: this file ~50,000 chars, history in `PROJECT_STATE_LOG.md`, capped by `test_cold_start_contract`. **S-164 research intake shipped** (mining lanes land without service_role key; SHIP verdicts refused at boundary). **Diagnose-route retired** (dashboard lane): CIS Engine at NAV_ITEMS[0]. **R557**: BTC-MA(150) gate on R554 (next production-spec candidate). **R558**: regime signal for 2024H2/2026YTD weakness clusters. **R559**: re-test R540-R547 legs WITH the gate.

> This header used to live 150 lines deep inside `## LANDED`, which is why it went stale without
> anyone seeing it — the one line whose job is to tell you how old the file is was itself buried
> in the part of the file nobody reads to the end. It sits at the top now, and
> `test_project_state_header_not_older_than_newest_ledger_entry` fails if it falls behind the
> ledger. (S-165)

## OPEN RISKS  (≤7 · cold-start first screen · every item ships a VERIFY command)

*Why this block is first: measured on 2026-07-30, a cold agent following CLAUDE.md exactly could
not reach S-92 or the still-open security hole — the header was dated older than the incident and
the lessons lived only in a 5,672-line ledger. **Don't transmit memory, transmit verification.**
Contract + failure-path walkthrough: `docs/AMNESIA_PROTOCOL.md`; enforced by
`tests/test_cold_start_contract.py`.*

*RETIRED 2026-08-12 to make room for #0: **#5 MCP streamable-transport migration** — closed
2026-08-09, no open follow-on, and its VERIFY (`grep -c 'mcp/sse' src/mcp/*.py` → 0) is a
regression check, not a risk. Moved to the ledger. Structural note while retiring it: **5 of
the 8 entries were 🟢 closed.** A cap of 7 does not bind on risk, it binds on the list, so
resolved items crowd out live ones and a cold agent reads eight entries to find three risks.
The cap is doing its job only if closure is as routine as addition.*

0. **🔴 C3 sizing table was INVERTED ON BOTH AXES (S-151, 2026-08-12).** Measured by
   execution: `lookup_size(regime=5 out-of-distribution, signal=1 weakest) = 1.30` and
   `(regime=1 in-dist, signal=5 strongest) = 0.10` — exactly backwards from the module's own
   stated design; `compute_size(None, None) = 1.20`, i.e. **no information produced leverage**,
   and `beta_core_size_hook` documented that 1.20 as the intended first-ship baseline.
   It survived because table + smoke test + hook docstring all agreed with EACH OTHER; only the
   stated intent dissented. **A frozen-value check could not have caught it — the table was
   transposed before it was frozen, and freezing preserves it.** Fixed by making the wrong
   ORIENTATION unable to load (`src/data/signals/strategy_params.py`, behavioural invariants
   validated at load), not by editing Minimax-C's 25 values. Until C seeds a re-oriented table,
   C3 runs the neutral table = ① baseline, no edge. Reversing both axes yields a passing table
   from the SAME 25 values — the magnitudes were designed right, the assembly was not.
   **AWAITING MINIMAX-C** (`MINIMAX_SYNC.md` §C3-SIZE-INVERSION-2026-08-12, items C6/C7).
   VERIFY: `python3 -m tests.test_sizing_cannot_invert` → green ⇒ an inverted orientation
   cannot load · `python3 -c "from src.data.signals.beta_core_size import compute_size as c;
   print(c('x',None,None,1.0).size_final)"` → ≤1.0 ⇒ no information buys no leverage
   OWNER: Seth (the gate) · Minimax-C (the 25 values + C7 polarity call)

1. **🟢 Service_role RESOLVED in production 2026-08-09 13:57Z.** `/health.strategy_library:
   pg_configured:true, degraded:false, consecutive:0`. ① clock live (OPEN RISK #4 below),
   §BETA-METRIC-AGG track record populated (66 signals, 60 scored). Kept here as the lesson +
   the local-Mac-side follow-on: **local `.env` still missing the real service_role key** —
   Mac-side Seth backfills (D1, D2, §OHLCV-DEAD backfill) remain blocked until Jazz pastes
   the real key. Downgraded from P0 to P2 because: (a) the immediate P0 consequence (Railway
   writes blocked, ① ② ③ unable to start) is RESOLVED, (b) all Mac-side-only work can be
   deferred without blocking product surface. **Lesson #72: a JWT that decodes is not a JWT
   that verifies.** The token carried `iss=supabase`, `ref=soupjamxlfsmgmmtoeok`,
   `role=service_role`, exp 2036 — every local check passed. It was the **anon key's signature
   spliced onto an edited payload**: byte-identical header, byte-identical 43-char signature,
   only the `role` claim differed. A signature is an HMAC over header+payload, so it cannot
   survive a payload edit — proof it was hand-assembled, not issued. Server verdict:
   `401 Invalid API key`. Almost certainly an earlier agent that needed service_role, had only
   anon, and produced one. **Never validate a credential by decoding it; validate it against
   the server that issued it.** Now enforced in `build_l1_observations.py --diagnose`, which
   probes for ROWS (real anon returns 200/0 rows under S-94 RLS, so status alone also proves
   nothing). Forged copies purged from `.env` and both `.claude/**/settings.local.json`
   (12 entries); never git-tracked (`.gitignore:42`).
   VERIFY: `bash -c 'set -a; . .env; set +a; curl -s -H "apikey: $SUPABASE_KEY" "$SUPABASE_URL/rest/v1/ohlcv_daily?select=symbol&limit=1"'`
   → `[{...}]` = real service_role · `401` = forged/stale · `[]` = anon under RLS, still blocked
   → **currently returns `401` (no local key) — expected, deferred**
   OWNER: Jazz (dashboard → Project Settings → API Keys → service_role → paste into `.env` —
   follow-on, not P0)

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
   information.**

   **🔴→🟢 THE CLASS, NOT THE INSTANCE (S-166, 2026-08-15).** This entry described ONE table
   that was never created. On 2026-08-15 the same check run across the whole codebase found
   **ELEVEN more** — `beta_core_nav_q(_meta)`, `beta_core_nav_size(_meta)`, `strategy_params`,
   `execution_intents/outcomes`, `fusion_paper_nav/lifecycle`, `crowd_clock_log`. This file's
   own header had called C2 and C3 "complete; 79/79 smoke green" while neither sleeve had
   anywhere to write a row. **The risk was written here, the lesson was recorded, and it still
   recurred eleven times — because what got fixed was that table, not the absence of any
   comparison between the set of tables the code writes and the set that exists.** Fixing an
   instance and calling the class closed is how one bug gets renamed eleven times.
   All 11 created; verified live `23/23 present, missing: []`.
   VERIFY: `python3 -m tests.test_every_written_table_exists` (offline: manifest matches source)
   · `curl -s -H "X-Internal-Token: $INTERNAL_TOKEN" $RAILWAY/internal/schema-drift` → `missing: []`
   OWNER: Seth (both halves shipped) · still open: `scripts/supabase_fusion_paper.sql` grants
   `FOR INSERT WITH CHECK (true)` to PUBLIC on a forward NAV table — the DB was built without it,
   the file still needs correcting or the next person to run it re-opens public writes.

   Migration now applied (RLS on, anon revoked); `/health` gained
   `data_layer.strategy_library`; `tests/test_strategy_durability.py` 4/4 in preflight. Kept OUT of
   `degraded` on purpose: losing durable research does not make the API unhealthy, and conflating
   them would either 503 a healthy API or bury data loss under a green tick.
   **Service_role RESOLVED on Railway 2026-08-09** (see risk #1 below) — Railway-side writes work.
   `/health.strategy_library: pg_configured:true, degraded:false, total:0, last_ok_ts:null` (no
   records yet because no record has been written since the migration). **Mac-side backfill remains
   P2** awaiting local `.env` service_role key (Jazz's call). DUAL_WRITE=0 flip safe to schedule
   once first record lands and Postgres ≥ Redis is verified.
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

4. **🟢 ① beta_core: v2 inception LIVE 2026-08-09 13:57Z.** `/internal/beta-core-clock`
   returns `{"configured":true,"marks":1,"started":true,"inception":"2026-08-09",
   "last_mark":"2026-08-09","days_since_mark":0,"missing_days":0,
   "gate_days_remaining":59,"stalled":false}`. Migration ran (v2 row present),
   service_role works (`/health.strategy_library.pg_configured:true, degraded:false`),
   the loop fires and writes. **60-day SHIP-ready gate opens 2026-10-08** (was
   2026-10-初 per OVERSIGHT §3). Kept here as a verification record + monitor; if
   `marks` stops advancing or `stalled:true` flips back, escalate P0.
   VERIFY: `curl -sm 15 -H "X-Internal-Token: $INTERNAL_TOKEN" "$BASE/internal/beta-core-clock"`
   ⇒ `marks≥1, started:true, gate_days_remaining:59-58-...` ⇒ loop firing.
   `stalled:true` ⇒ escalate P0.
   OWNER: Seth (verify) · Jazz (service_role → resolved 2026-08-09)

   *Original entry, for the record (kept as the lesson, not the status — see header above).*
   S-103 + S-105 refuted the ④-layer cross-sectional market-neutral L/S construction (β confounded
   across all 5 tiers, cost 4.6 %/yr > ~3 % best-case effect). **3 of 5 live L/S paper books
   (causal_paper / combined_book / scalable_paper) demoted to RESEARCH RECORDS on 2026-08-08**
   (commit `fc4d331`). The product book `beta_core_paper` (commit `121b54c`) is the only forward-clock
   with a SHIP floor in mind: equal-weight hold-the-panel (no short, no neutralisation) + ex-ante
   vol target + ⓠ regime override caps gross at {0.0, 0.5, 1.0, 1.3}, marked daily to Supabase
   `beta_core_nav` with `benchmark_nav` alongside `nav` so excess is arithmetic. S-123 fix in code
   (commits b8af18b + c0516f9) AND migration `scripts/supabase_beta_core_reinception.sql` BOTH
   deployed & applied by 2026-08-09 13:57Z. **A book that is silent cannot be told from a book
   that is alive but writes were dropped on the floor (S-105 redux) — the silent period
   (2026-08-08 → 2026-08-09) was both; the S-123 fix was the half that was visible. The migration
   was the other half, and was the harder dependency to see because it sat in Supabase, not in
   code.** Full audit (S-103, S-105, S-106, demotion reasoning, anti-amnesia state recovery,
   S-123 inception identity) lives in OVERSIGHT_2026-08.md §0 + §3 + §7 + REFUTATION_LEDGER.md S-124.
   · Seth (verification probe — see VERIFY; re-run once Jazz pastes key) · Minimax-A
   (M1: keep T1 engine push alive — Mac T1 health drives this loop's panel).

5. **🟢 `ohlcv_daily` multi-source duplicates — FIXED 2026-08-12.** `_ohlcv_close_at` now
   reads `ohlcv_daily_canonical` view (the deterministic one-row-per-entity SELECT with source
   precedence binance_hist > hyperliquid > eodhd > coingecko > yfinance, computed server-side).
   Fix covers all 4 call sites at once (outcome_tracker.py:321 benchmark, :366 entry, :377 exit,
   prediction_resolver.py:125 daily resolver). 8/8 contract tests in `tests/test_outcome_canonical.py`
   pass: URL routes to canonical view (not raw table), window ±window_days, nearest-day close,
   null-close defensive skip, graceful None on empty/500, no-op when SUPABASE_URL unset, and a
   caller-regression scan that fails if any other path re-introduces the raw-table read. Preflight
   green. `ohlcv_local.load_local_panel` remains a research-side footgun (no consumers in
   production paths) — kept on the queue as part of the broader canonicalization work, not
   required for this fix to close.
   VERIFY: `python3 -m pytest tests/test_outcome_canonical.py -v` → 8/8 pass.
   `grep -n "f\"{_SB_URL}/rest/v1/ohlcv_daily\"" src/data/signals/outcome_tracker.py` → no match
   (must NOT regress to raw table). `select count(*) from ohlcv_daily_canonical;` → 181,334
   (vs 229,916 base) = 21 % deduped, view is live.
   OWNER: Seth (closed) · backfill of `signal_outcomes` (Risk #3 follow-on) remains P2
   awaiting local key.

   *Original entry, for the record (kept as the lesson, not the status — see header above).*
   48,582 duplicate `(symbol, trade_date)` pairs across 57 symbols, 2017→2026 (~21 % of 229,916 rows).
   Not a schema bug: the unique key is `(symbol, trade_date, source)`, so multiple sources per day
   is by design. The bug is that every consumer must pick one, and forgetting is invisible —
   duplicated trading days, volume columns ~62,000× apart (CoinGecko USD notional vs Binance base
   units), and same-day closes differing by up to 5 % (ETH 4.8 %, SOL 5.0 %). Fixed forward with
   the `ohlcv_daily_canonical` view (229,916 → 181,334 rows, 0 remaining duplicates, deterministic
   precedence: native venue > aggregator, paid > free). **Lesson #76: any table permitting
   multiple rows per entity must ship a deterministic one-row-per-entity view, or the choice
   of source is silently delegated to every reader.**

   **AUDIT 2026-08-09 — consumer categorization (kept for the audit trail):**

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
   - `src/data/signals/outcome_tracker.py::_ohlcv_close_at` (line 219) — CRITICAL → **FIXED
     2026-08-12** (now reads `ohlcv_daily_canonical` view). 4 call sites covered at once.
   - `src/research/data/ohlcv_local.py::load_local_panel` (line 119) — DEFAULT no filter;
     `pivot(index="trade_date", columns="symbol")` on the local sqlite mirror will fail
     (`ValueError: Index contains duplicate entries`) or silently keep the last source, depending
     on pandas version. Has `source=` param but defaults to None. **Affects all research that
     uses `load_local_panel` without an explicit source** — same shape as outcome_tracker but
     less central. Kept on the queue, not blocking OPEN RISK #6 closure.

   **D. Reference / metadata only (NOT readers):**
   - `src/api/routers/admin.py:44` (config), `src/mcp/cometcloud_mcp.py:1022+` (descriptive text),
     `src/data/vector/market_state.py:23+` (docs), `src/data/vector/state_l1.py:29+` (Series source
     tags — actual reads go through `build_l1_observations.py`, not from this file),
     `src/data/vector/embedder.py` (uses `asset_edge_moments` view, a separate computation, not
     the base table).

   **Resolution path (record of what was done):**
   - ✅ Fix `outcome_tracker._ohlcv_close_at` to use `ohlcv_daily_canonical` view (the durable
     option — new sources just need to be added to the view's precedence, not patched into
     every reader).
   - Pending: Fix `ohlcv_local.load_local_panel` to default to canonical-source (highest
     precedence) when no `source` is passed, or raise a loud error if multiple sources exist.
   - Pending: Re-run `refresh_signal_track_record()` (P0 #241) to repopulate `signal_outcomes`
     with source-deterministic closes. **Note: `signal_outcomes` is currently DEAD 80+ days per
     `main.py:1229`**, so a full backfill is needed regardless; the question is whether the
     backfill uses the fixed or unfixed path — now the path is fixed.
   - The original OPEN RISK #6 "S-83→S-91 used ohlcv_11yr.db, probably unaffected" guess was
     CORRECT — S-83→S-91 read from local Binance, not Supabase. S-113 (S-108/S-109 re-run)
     reads `source=eq.binance_hist` explicitly and is SAFE. Only `asset_edge_moments` and
     `signal_outcomes` were flagged, and `asset_edge_moments` uses a separate view (not
     the base table) — so the ONLY critical path was `signal_outcomes` via `_ohlcv_close_at`,
     and that path is now fixed.
   48,582 duplicate `(symbol, trade_date)` pairs across 57 symbols, 2017→2026 (~21 % of 229,916 rows).
   Not a schema bug: the unique key is `(symbol, trade_date, source)`, so multiple sources per day
   is by design. The bug is that
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

6. **🟢 S-104 T2 fan-out fix VERIFIED IN PRODUCTION 2026-08-09 07:05Z.** `git_sha=5a54d1c1`
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

## History moved out (S-165, 2026-08-15)

`## LANDED` and `## Building log` now live in **`PROJECT_STATE_LOG.md`** — append-only,
never read at session start. They were 266,028 of this file's 315,708 characters, and both
described themselves as history in their own headings ("kept for the lessons, not for the
status"). CLAUDE.md tells every agent to read this file on start; that was ~99k tokens of
cold-start tax per lane per session, most of it settled.

Look there for: what landed and why, the terse build log, the lessons behind each fix.
Do not read it to find out what is true now — that is what the sections above are for.

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
