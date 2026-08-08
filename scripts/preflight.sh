#!/usr/bin/env bash
# Preflight — the MANDATORY pre-push gate. The app must IMPORT and BOOT, not just
# compile. `py_compile` only checks syntax; it MISSES import-time NameErrors (e.g. a
# name used in a function annotation that isn't imported) — exactly the class that
# 502'd production on 2026-07-13 (`Response` unimported in main.py, py_compile passed).
#
# Run this before EVERY push. It is the same check CI runs, but locally, before the
# broken commit ever reaches Railway (which auto-deploys on push regardless of CI).
#
#   bash scripts/preflight.sh   &&   git push origin main
set -euo pipefail
cd "$(dirname "$0")/.."

echo "→ [1/2] byte-compile all src ..."
python3 -m py_compile $(git ls-files 'src/**/*.py') && echo "  ✓ syntax OK"

echo "→ [2/3] import + boot smoke (the real gate py_compile can't do) ..."
INTERNAL_TOKEN=preflight ENVIRONMENT=ci python3 scripts/smoke_test.py

echo "→ [3/3] discipline + schema-drift guard (philosophy compiled to CI, 2026-07-27) ..."
# 3a. strategy discipline — cause/OOS/paper/regime evidence floor on every SHIP record
python3 -m tests.test_strategy_discipline
# 3a-bis. resilience — the 2026-07-29 P0 (Supabase saturation → 33s hangs → retry storm,
#         while /health lied "healthy"). Guards: no retry on timeout, breaker opens, fails
#         fast, RECOVERS after cooldown, 4xx doesn't trip it, health reflects reality.
python3 -m tests.test_supabase_breaker
python3 -m tests.test_cis_universe_lock
# 3a-bis-2. T2 fan-out bounds (2026-08-07, S-104). The lock test above bounds the
#           CALLER; this bounds the CALLEE. `/cis/universe` returned 200 for 56 min
#           while serving a payload frozen at 01:03 — the build never completed
#           because one 24h-cadence decoration branch (cg_dev: 25 coins, sem 4,
#           15s each) overran the budget and cancelled the nine branches that had
#           already succeeded. Guards: per-branch timeout, degradation reported not
#           swallowed, failures negative-cached so a down provider costs once.
python3 -m tests.test_t2_fanout_bounds
# 3a-ter. cold-start contract — the amnesia path (docs/AMNESIA_PROTOCOL.md). Every agent starts
#         every session at zero; a lesson that lives only in a 5,672-line ledger changes nothing.
python3 -m tests.test_cold_start_contract
# 3a-quater. undefined names on the serving path — a NameError on a rarely-taken branch is
#            invisible to py_compile AND to production when the caller logs a warning. That
#            combination silently killed the T2 universe fallback (2026-08-06).
python3 -m tests.test_no_undefined_names
# 3a-quinquies. neutralisation (2026-08-07, S-103). `neutralize()` was cited in 71
#               files and defined in none, so no claim of alpha had ever been
#               separated from exposure. Guards both directions: pure beta must
#               neutralise to zero, and real alpha must survive — a neutraliser
#               that strips everything would refute every strategy including a
#               working one.
python3 -m tests.test_neutralize
# 3a-sexies. strategy-library durability (2026-08-07, S-105). The record library —
#            the graveyard CLAUDE.md calls the asset — spent 12 days in a 24h-TTL
#            Redis key because its Postgres migration (written 2026-07-26) was
#            never applied, so every write hit the fallback and logged a warning
#            that fired every time and therefore carried no information.
#            Guards: the fallback is COUNTED not just logged, and one failure is
#            already degraded — there is no acceptable rate of losing research.
python3 -m tests.test_strategy_durability
# 3a-septies. L0 data architecture (2026-08-07). asset_class lived on OBSERVATION rows,
#             where it actually recorded the SOURCE - 24 symbols carried conflicting
#             labels, and source determines candle convention (>1% open gaps: Crypto
#             31.3% vs DeFi 83.5%). So `where asset_class=...` was a source filter in a
#             class filter's clothing, which is how S-106 read a splice between two bar
#             conventions as market structure. Class now lives only in `assets`.
python3 -m tests.test_data_architecture
# 3a-octies-2. ① beta-core book (2026-08-07, oversight review). All five books accruing
#              a forward record were long/short market-neutral - the ④ construction that
#              produced the R76-R94 graveyard - while layer ①, the FoF core AND the
#              benchmark for every other book, had ZERO forward days. Guards the product
#              book's invariants: long only, exposure in [0,1.3], the vol scalar may
#              de-lever freely but never lever past the ceiling, unmeasured inputs resolve
#              to NEUTRAL rather than to large, and the benchmark leg is structural so
#              excess is arithmetic rather than a benchmark chosen at analysis time.
python3 -m tests.test_beta_core_book
# 3a-nonies. effective breadth (2026-08-08, S-115). Three ledger entries quoted
#            N/(1+(N-1)rho) as "independent bets". It is not: that formula is the
#            exact answer for equal-weight VARIANCE REDUCTION (long-only book), while
#            breadth in IR = IC*sqrt(breadth) is the correlation matrix's SPECTRUM
#            (neutral book). They diverge even when equicorrelation HOLDS - 2.99 vs
#            7.38 at rho=0.3 - so the error was never arithmetic, it was quoting a
#            breadth number without saying which book it constrains.
python3 -m tests.test_effective_breadth
# 3a-decies. storage hygiene (2026-08-08). Supabase hit 90% of its tier and the
#            obvious move was archiving rows. Measurement said otherwise: ~84 MB of
#            dead indexes plus ~128 MB of bloat from a same-day bulk UPDATE that
#            populated asset_id - autovacuum had already cleared the dead tuples, so
#            the waste was invisible to the usual check while the pages stayed fat.
#            449 -> 237 MB with zero rows archived. Guards the generalisable parts:
#            a bulk UPDATE on a large table must declare its storage cost, index
#            scan counts are evidence only when the stats are old enough, and the
#            archive order is set by REFETCHABILITY rather than by size.
python3 -m tests.test_storage_hygiene
# 3a-undecies. state persistence (2026-08-08, S-117/S-118). A layer-③ sleeve was
#              being built on `macro_regime`, whose median run is 3 DAYS with 51%
#              of runs ≤3d — more than half its "transitions" were label chatter.
#              A causal 5-day dwell filter takes the median to 19d and makes the
#              trigger legitimate, but drops EASING↔RISK_OFF from 8/8 to 3/3.
#              Guards: the filter is CAUSAL (a centred one would leak the future and
#              become the edge), and it reports BOTH costs — sample destroyed and
#              latency added — because reporting only the smoother chart is a pitch.
python3 -m tests.test_state_persistence
# 3a-duodecies. strategy intake (2026-08-08). Minimax-A asked for the service_role
#               key to write beta-strategy records. Declined; this endpoint replaces
#               it and is better on two counts. Blast radius: service_role bypasses
#               RLS on every table while a scoped token appends records and rotates
#               freely (Lesson #72 - a forged JWT passed every local check). And the
#               gate becomes unbypassable: with a raw DB key a SHIP record failing
#               the discipline floor can be written anyway, because the floor lives
#               in CI and CI is not in the write path. Here validate() runs BEFORE
#               the insert - a gate the writer can route around is a suggestion.
python3 -m tests.test_strategy_intake
# 3a-quater. venue consolidation — the wrong-ASSET class (2026-08-01). cis_provider
#            mapped HYPE to Binance spot HYPERUSDT, which is Hyperlane: $0.0558 vs
#            Hyperliquid's $52.32, a 937x error that scored the asset D/UNDERWEIGHT
#            through a +256% run while every completeness check stayed green. A
#            populated wrong number is invisible to "is the field set?" and obvious
#            to "do independent venues agree?". Offline/deterministic — the LIVE
#            cross-venue probe belongs in loop_health SENSE, not in a code gate.
python3 -m tests.test_venue_consolidation
# 3a-quinquies. CIS drift detector (the HYPE case, 2026-07-30): pure detection
#              logic must regress-safe; live supabase probe lives in scheduled cron,
#              not in a code gate (offline/deterministic only here).
python3 -m tests.test_cis_drift_detector
# 3a-sexies. ⓠ REGIME OVERRIDE enforcer (2026-08-06, first cut): wraps research-side
#             m_wo_q_o1_stablecoin_gate.assign_band_hysteresis into production-shape
#             API (apply_regime_override, apply_regime_override_series). PIT-safe,
#             allows only the v1 allowed-cap set {0.0, 0.5, 1.0, 1.3}.
python3 -m tests.test_regime_override_enforcer
# 3a-septies. ⓠ REGIME OVERRIDE paper track (2026-08-06, parallel paper NAV under
#              enforcer). Tests pure backtest/aggregation logic; live paper runner
#              is wired into daily_runner.py post-validation (60d forward paper).
python3 -m tests.test_fusion_paper_regime_track
# 3a-octies. build_l1_observations.py smoke (2026-08-07, Lesson #72 follow-up): the
#             script's --diagnose probe verifies the live Supabase key against the
#             server (the 2026-08-02 forged-key class). It cannot run inside the
#             offline gate; this test pins the script shape (imports, constants,
#             resolve_panel_source('none'), compute_panel_series, diagnose()
#             contract) so a structural regression can't reach Railway. The actual
#             network probe belongs in the scheduled cron path.
python3 -m tests.test_build_l1_observations_smoke
# 3b. contract schema echo — the drift class preflight previously couldn't see (Mac push schema
#     changed, Railway didn't follow). Prints the canonical SCHEMA_VERSION so it's in every log,
#     and fails loudly if the contract module stops importing.
python3 - <<'PY'
from src.api.contracts.cis_push import SCHEMA_VERSION
from src.data.vector.embedder import SCHEMA_VERSION as VEC_SCHEMA, ASSET_DIMS_V2
print(f"  ✓ cis_push contract SCHEMA_VERSION={SCHEMA_VERSION} · vector schema v{VEC_SCHEMA} ({ASSET_DIMS_V2}-dim)")
PY

echo ""
echo "✅ PREFLIGHT PASSED — imports + boots + discipline green. Safe to push."
