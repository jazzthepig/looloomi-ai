# Code Review & Mac-local Alignment — 2026-06-06

Scope: this session's Railway-side changes (signal outcome tracker, CIS push
contract normalizer, build-state, deploy health gate, QA fixes, EODHD TradFi
swap, executability layer, per-asset narratives, CryptoRank + LLM funding
extraction) reconciled against the live `/internal/cis-scores` boundary and the
Mac-local engine (per MINIMAX_SYNC).

Deployed git sha (live): `68e9bdb`. Method: read live endpoints as ground truth.

---

## 🔴 CRITICAL — missing modules in the deployed repo (fix before next push)

Prior commits landed code that imports modules which were **never committed**.
Confirmed live: `GET /api/v1/market/executability/BTC` → HTTP 500
`No module named 'src.data.market.executability'`; universe assets carry no
`narrative` / `executability` fields.

Untracked but referenced by committed code:
- `src/data/cis/narrative.py`        (imported by `cis.py`)
- `src/data/market/executability.py` (imported by `cis.py` + `market.py`)
- `src/data/market/llm_extract.py`   (imported by `data_layer.py`)
- `src/api/contracts/__init__.py`, `src/data/signals/__init__.py` (package inits)

Impact: executability endpoints 500; per-asset narratives + inline executability
absent. App does NOT crash (defensive try/except), but the features are dead.

**Unblock (Jazz — sandbox can't remove the git lock):**
```bash
cd ~/Projects/looloomi-ai
rm -f .git/index.lock                       # stale lock blocking commits
git add src/api/contracts/__init__.py src/data/signals/__init__.py \
        src/data/cis/narrative.py src/data/market/executability.py \
        src/data/market/llm_extract.py
git commit -m "fix: commit modules referenced by prior commits (narrative, executability, llm_extract)"
git push origin main
```
The deploy health gate (`scripts/deploy_health_gate.py`) will then go green on
the executability + contract checks.

---

## ✅ Validated live

- **CIS universe never-blank** — serving 58 assets via T2 "railway" path even
  with the Mac Mini push absent. The `UnboundLocalError` in
  `calculate_cis_universe` (which had silently killed T2) is fixed and deployed.
- **Contract echo** — `/internal/cis-scores/schema` live, reports `schema_version
  1.0`. Normalizer is the active ingest path.
- **build-state** — `/internal/build-state` live (routes=145), reports last-push
  freshness + provenance for ops.
- **30D sanitizer** — change fields null out on missing price (no more fake
  −100); TradFi now sourced from EODHD primary (yfinance fallback).

## 🟡 Mac-local alignment — needs a fresh push to confirm

- `last_cis_push present=False` — no Mac Mini push currently in cache, so prod
  serves pure T2. Either `cis_scheduler.py` is stopped or the 2h cache lapsed.
- MINIMAX_SYNC says `cis_push.py` now sends `schema_version` + `provenance`
  (P1 ✅). **Cannot verify until a push lands** — after the next push, check
  `/internal/build-state → last_cis_push.{schema_version, engine_git_sha,
  drift_warnings}`. `drift_warnings: 0` confirms full alignment.

**Minimax actions:**
1. Confirm `cis_scheduler.py` is running and pushing (cache should repopulate).
2. After a push, we jointly read build-state to confirm schema_version="1.0",
   provenance present, drift_warnings=0.
3. Pending (non-blocking, Railway normalizes meanwhile): send nested
   `pillars{F,M,O,S,A}` (drop `f/m/r/s/a`); attach `narrative` (small LM Studio
   model — 35B OOMs) and `executability` (order-book depth) blocks on the push.

## Code-review notes (non-blocking)

- **Universe cold-start latency** — first `/api/v1/cis/universe` after cache
  expiry recomputes T2 (many external calls) and can exceed ~25s; the 30s
  single-flight cache makes subsequent calls fast. Acceptable, but a warm-keep
  ping (or longer cache) would smooth first-load. Frontend should also dedupe
  its multi-component fetch (still fires several on load).
- **Defensive imports paid off** — the try/except around narrative/executability
  attach is exactly why the missing modules degraded gracefully instead of
  500-ing the whole universe. Keep that pattern.
- **Compliance gate** — boundary remap (HOLD→NEUTRAL etc.) + the deploy-gate
  banned-signal check are both live; Minimax also fixed HOLD at source. Defense
  in depth intact.
