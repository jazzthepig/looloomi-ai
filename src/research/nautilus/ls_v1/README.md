# `src/research/nautilus/ls_v1/` — NautilusTrader LS V1 parity skeleton (Minimax-B, 2026-07-04)

End-to-end runnable skeleton that ports `freqtrade/user_data/strategies/CometCloudLongShortV4.py`
to Nautilus Trader 1.229+ for **parity verification**. This is engine plumbing,
not strategy framework work — the strategy is **intentionally not registered**
with `src/research/strategy_registry.py` (different lane).

## What it does

- `strategy.py` — `CometCloudNautilusLongShortV1`: Nautilus Strategy that mirrors the
  freqtrade LS V4 entry logic (EMA 9/21 cross + ADX gate + ATR SL/TP bracket) and
  re-introduces the **CIS gate** with regime-aware `min_cis_score` (date-keyed lookup
  against `cis_history/cis_YYYY-MM-DD.json`, with backtest-bypass soft floor when the
  cache is sparse).
- `data_adapter.py` — converts freqtrade feather files to a Nautilus
  `ParquetDataCatalog`. Idempotent (wipe + rewrite). Env-overridable paths.
- `runner.py` — runs `BacktestNode` over the 3 LS V4 instruments
  (BTC/ETH/SOL perpetuals) on the OOS window 2025-05-03 → 2026-03-12, 4h bars.
  Emits **structured JSON + CSV** to `OUT_DIR/run_<timestamp>/`.
- `parity_check.py` — diffs the Nautilus run against a freqtrade baseline (JSON or CSV),
  produces `parity_report.json` / `.csv` / `.md`.

## Handoff open items — status

| # | Item | Status | Notes |
|---|---|---|---|
| 1 | ADX gate workaround (Nautilus 1.229 has `DirectionalMovement` but no ADX aggregate) | ✅ Implemented | Inline DX + Wilder smoothing in `strategy._update_adx`; toggle via `LSV1_ENABLE_ADX_GATE` env |
| 2 | CIS gate wire-in (regime-aware `min_cis_score`) | ✅ Implemented | `strategy._cis_passes` — date-keyed, dense-cache bypass, regime floor from `REGIME_CIS_FLOOR` |
| 3 | Side-by-side equity curve | ⏳ Skeleton-only | `parity_check.py` produces the diff in JSON/CSV/MD; the matplotlib equity curve is a separate script |
| 4 | Rename to `CometCloudNautilusLongShortV1` and ship | ✅ Done | Lives here in `src/research/nautilus/ls_v1/` |

## How to run

### 1. Set up the Python env (once)

```bash
cd /Users/sbb/Projects/looloomi-ai
python3 -m venv venv  # if not already created
source venv/bin/activate
pip install -r requirements.txt
```

`nautilus_trader>=1.229` is now in `requirements.txt`. The venv at `venv/` is
already present and Python 3.14.3 / pip 26.0 are confirmed working.

### 2. Build the Nautilus ParquetDataCatalog (once per data refresh)

```bash
source venv/bin/activate
python -m src.research.nautilus.ls_v1.data_adapter
```

Defaults to:
- Source: `/Volumes/CometCloudAI/freqtrade/user_data/data/binance/futures/{BTC,ETH,SOL}_USDT_USDT-4h-futures.feather`
- Output: `/Volumes/CometCloudAI/cometcloud-local/_data/nautilus_catalog/`

Override via `NAUTILUS_FEATHER_DIR` / `NAUTILUS_CATALOG_DIR` env vars. The adapter
wipes `instruments/` and `bars/` on every run to avoid stale rows.

### 3. Run the parity backtest

```bash
source venv/bin/activate
python -m src.research.nautilus.ls_v1.runner
```

Emits to `OUT_DIR/run_<timestamp>/`:
- `per_instrument.json` / `.csv` — per-instrument counts + PnL
- `summary.json` — totals across all instruments
- `skip_summary.json` — strategy skip counters (ADX, CIS, position-state)
- `run_metadata.json` — window, instruments, feature flags

Override `OUT_DIR` via `NAUTILUS_LS_V1_OUT_DIR` env var.

### 4. Diff against the freqtrade LS V4 baseline

```bash
source venv/bin/activate
python -m src.research.nautilus.ls_v1.parity_check \
    /path/to/nautilus_run_dir \
    /path/to/freqtrade_baseline.json   # optional; auto-discovers from defaults
```

If no freqtrade baseline is found, the report is one-sided (Nautilus only)
and the report's `notes` field flags it. Export the freqtrade LS V4 backtest
to JSON (or CSV) and re-run.

## Feature flags

All three are env-overridable for A/B comparison:

| Flag | Default | Effect when OFF |
|---|---|---|
| `LSV1_ENABLE_ADX_GATE` | `1` | Entry fires on every EMA cross (Shadow stub behaviour) |
| `LSV1_ENABLE_CIS_GATE` | `1` | All entries pass regardless of regime / CIS score |
| `LSV1_ENABLE_FUNDING_FILTER` | `0` (no funding data in catalog yet) | n/a (always on when data exists) |

## Expected parity gap

Per Shadow's earlier note: with all gates ON, Nautilus LS v1 should produce
**fewer** trades than the freqtrade LS V4 (ADX + CIS both filter). With both
gates OFF, Nautilus produces more (alpha-only run). The `parity_check.py`
auto-note surfaces which regime you're in based on `run_metadata.json`.

## File map

```
src/research/nautilus/ls_v1/
├── __init__.py        — public surface (strategy, config, build_catalog, run_parity)
├── strategy.py        — CometCloudNautilusLongShortV1 (Strategy + LSv1Config)
├── data_adapter.py    — feather → Nautilus ParquetDataCatalog
├── runner.py          — BacktestNode runner, structured JSON/CSV output
├── parity_check.py    — Nautilus vs freqtrade diff (JSON/CSV/MD report)
├── tests/
│   ├── __init__.py
│   └── test_strategy_smoke.py  — import + duck-type contract check
└── README.md          — this file
```

## What's NOT in this skeleton (next sessions)

- **Matplotlib equity-curve side-by-side plot** (handoff open item 3 visual half)
- **Walk-forward harness** wired through `src/research/walk_forward.py` (the framework
  exists; this strategy just needs to plug into it)
- **Per-regime P&L attribution** (Nautilus backtest results + regime lookup)
- **Minimax-A's drive sync** — the LS V1 only runs on a fresh catalog build
  right now; once `Shadow/cometcloud-local/_data/` syncs back to the live drive,
  the catalog will have current data
- **Real CIS history wire-in** — `CIS_HISTORY_DIR` defaults to the Mac Mini
  volume; backtest-bypass mode kicks in if the dir is missing

## Compliance

Strategy classmethods + tags use positioning-language only (no
`buy` / `sell` / `accumulate` / `avoid`) per CLAUDE.md. `compliance_tag()`
returns `"CC_LS_V1_NAUTILUS"`. Order tags use `LONG_ENTRY` / `SHORT_ENTRY` /
`STOP_LOSS` / `TAKE_PROFIT_TP1` — no directional action verbs.
