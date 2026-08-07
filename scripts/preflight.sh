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
