# `src/research/nautilus/sleeve_a/` — NautilusTrader Sleeve A parity skeleton (Seth, 2026-07-17)

End-to-end runnable skeleton that ports `freqtrade/user_data/strategies/CometCloudMultiFactorV2.py`
(the MVRV-mean-reversion Sleeve A per `PROFITABLE_STRATEGY_REPORT.md`) to Nautilus Trader
1.229+ for **parity verification**. This is engine plumbing, not strategy framework work —
the strategy is **intentionally not registered** with `src/research/strategy_registry.py`
(different lane).

## What it does

- `strategy.py` — `CometCloudNautilusMultiFactorV2`: Nautilus Strategy that mirrors the
  freqtrade MultiFactorV2 entry logic (3-dimension gate: trend + extreme + momentum) and
  the hard -3% stop loss. Long-only. Max 2 open trades + 2 daily trades + 15-bar cooldown.
- `data_adapter.py` — converts freqtrade feather files to a Nautilus
  `ParquetDataCatalog`. Idempotent (wipe + rewrite). Env-overridable paths.
- `runner.py` — runs `BacktestNode` over the 3 MultiFactorV2 instruments
  (BTC/ETH/SOL perpetuals) on the OOS window 2025-01-01 → 2026-03-12, 1h bars.
  Emits **structured JSON + CSV** to `OUT_DIR/run_<timestamp>/`.
- `parity_check.py` — diffs the Nautilus run against a freqtrade baseline (JSON or CSV),
  produces `parity_report.json` / `.csv` / `.md`. Includes a per-instrument parity status
  (PASS / WARN / FAIL) with the gates defined below.

## Parity gates (per MINIMAX_SYNC.md §STRATEGY-REVIVE B-S1)

Sleeve A parity is acceptable when **all three** hold:

| Gate | Threshold | Reason |
|---|---|---|
| Trade count diff | ±1 trade per pair on 14mo | The daily-cap off-by-one when UTC midnight crosses mid-bar in freqtrade's Trade-proxy lookup |
| PnL diff | ≤ 0.5% of notional (10K USD → ±50 USDT) | Microsecond-level entry timing differences when freqtrade checks the bar BEFORE indicator update vs Nautilus checks AFTER |
| Long-only invariant | 0 short entries | Sleeve A is structurally long-only per the MVRV mean-reversion thesis (long the dip, never short the bounce) |

If the per-pair report surfaces `parity_status=FAIL` for any pair, **escalate before
promoting Sleeve A to the two-layer book**.

## Why Sleeve A is the "durable core"

Per `docs/TRADER_TOM_DOCTRINE.md` (Tom Hougaard / *Best Loser Wins*, 2026-07-17):
> A durable fundamental core never sold on short-term volatility (sell only when the
> cause breaks, never on a price wobble) + a tactical trend-riding overlay whose gross
> scales with regime.

Sleeve A IS the durable core. It's intentionally simpler than the LS v1 (tactical
overlay) — no CIS gate, no short side, no edge gate, no funding filter. The 3-dimension
entry gate + hard -3% stop is enough to harvest MVRV-style oversold bounces; regime
control lives in the two-layer combiner (C-S4, owned by Minimax-C).

## What it does NOT do (compared to LS v1)

| Capability | LS v1 | Sleeve A |
|---|---|---|
| Direction | Long + short | Long only |
| Stop loss | ATR(14) × 1.5 (min 2.0%) | Hard -3% |
| Take profit | ATR(14) × 2.5 (min 3.0%) | None — relies on the stop + exit gates |
| CIS gate | Yes (regime-aware) | No — durable core |
| Edge gate (H2/H3) | Yes | No |
| Funding filter | Disabled (no data) | n/a |
| Macro regime veto | Yes | No (pass-through) |
| Position caps | Per-portfolio | MAX_OPEN_TRADES=2, MAX_DAILY_TRADES=2 |
| Cooldown | n/a | 15 bars between entries |

## How to run

### 1. Set up the Python env (once)

```bash
cd /Users/sbb/Projects/looloomi-ai
source /Volumes/CometCloudAI/freqtrade/.venv/bin/activate   # Mac venv has nautilus_trader==1.230.0
```

The Mac venv at `/Volumes/CometCloudAI/freqtrade/.venv` already has `nautilus_trader>=1.230`.
The Cowork sandbox does NOT have nautilus installed — code-only work happens here, Mac-side
runs the backtest.

### 2. Download the 14mo 1h BTC/ETH/SOL feather (Mac side, once)

```bash
cd /Volumes/CometCloudAI/cometcloud-local
source /Volumes/CometCloudAI/freqtrade/.venv/bin/activate

# 14mo × 24h × 30 days = ~10,080 bars per pair. Need 1h data going back to 2025-01-01.
freqtrade download-data \
    --exchange binance --trading-mode futures \
    -p BTC/USDT:USDT ETH/USDT:USDT SOL/USDT:USDT \
    --timeframes 1h \
    --days 540 \
    --data-format-ohlcv feather \
    --datadir user_data/data

# freqtrade 2026.3-dev writes to /Volumes/CometCloudAI/freqtrade/user_data/data/futures/
# regardless of --datadir (verified bug). Move into the canonical path:
mv /Volumes/CometCloudAI/freqtrade/user_data/data/futures/{BTC,ETH,SOL}_USDT_USDT-1h-futures.feather \
   /Volumes/CometCloudAI/cometcloud-local/user_data/data/binance/futures/
```

Verify the merge covers the full window:
```bash
python3 -c "
import pandas as pd
for s in ['BTC','ETH','SOL']:
    df = pd.read_feather(f'/Volumes/CometCloudAI/cometcloud-local/user_data/data/binance/futures/{s}_USDT_USDT-1h-futures.feather')
    print(f'{s}: {len(df):,} bars, {df[\"date\"].iloc[0]} -> {df[\"date\"].iloc[-1]}')
"
```
Expected: ≥10,000 bars each, last date ≥ 2026-03-12.

### 3. Build the Nautilus ParquetDataCatalog (Mac side, once per data refresh)

```bash
cd /Users/sbb/Projects/looloomi-ai
source /Volumes/CometCloudAI/freqtrade/.venv/bin/activate

python -m src.research.nautilus.sleeve_a.data_adapter
```

Defaults to:
- Source: `/Volumes/CometCloudAI/cometcloud-local/user_data/data/binance/futures/{BTC,ETH,SOL}_USDT_USDT-1h-futures.feather`
- Output: `/tmp/sleeve_a_catalog/`

Override via `SLEEVE_A_FEATHER_DIR` / `SLEEVE_A_CATALOG_DIR` env vars. The adapter wipes
`instruments/` and `bars/` on every run to avoid stale rows.

### 4. Run the freqtrade MultiFactorV2 baseline (Mac side, once)

This is owned by **Minimax-C** as part of §STRATEGY-REVIVE C-S1 ("honest re-scorecard").
Until C-S1 lands, the parity diff is one-sided (Nautilus only — the report's `notes` field
flags it).

```bash
cd /Volumes/CometCloudAI/cometcloud-local
source /Volumes/CometCloudAI/freqtrade/.venv/bin/activate

# Mint the freqtrade baseline (one of these per §STRATEGY-REVIVE):
freqtrade backtesting \
    --strategy CometCloudMultiFactorV2 \
    --config user_data/config_multi_factor_v2.json \
    --timerange 20250101-20260312 \
    --export trades \
    --export-filename user_data/backtest_results/multi_factor_v2.json

# Convert to the parity_check baseline format (one row per pair):
freqtrade backtesting-analysis \
    --export-filename user_data/backtest_results/multi_factor_v2.json \
    > /Volumes/CometCloudAI/cometcloud-local/_reports/backtest/multi_factor_v2_latest.json
```

### 5. Run the Nautilus parity backtest (Mac side)

```bash
cd /Users/sbb/Projects/looloomi-ai
source /Volumes/CometCloudAI/freqtrade/.venv/bin/activate

python -m src.research.nautilus.sleeve_a.runner
```

Emits to `OUT_DIR/run_<timestamp>/`:
- `per_instrument.json` / `.csv` — per-instrument counts + PnL
- `summary.json` — totals across all instruments
- `skip_summary.json` — strategy skip counters (trend, extreme, momentum, cooldown, daily_cap, open_cap)
- `run_metadata.json` — window, instruments, feature flags

Override `OUT_DIR` via `SLEEVE_A_OUT_DIR` env var.

### 6. Diff against the freqtrade MultiFactorV2 baseline

```bash
cd /Users/sbb/Projects/looloomi-ai
source /Volumes/CometCloudAI/freqtrade/.venv/bin/activate

python -m src.research.nautilus.sleeve_a.parity_check \
    /Volumes/CometCloudAI/cometcloud-local/_reports/nautilus/sleeve_a/run_<timestamp> \
    /Volumes/CometCloudAI/cometcloud-local/_reports/backtest/multi_factor_v2_latest.json
```

Output: `parity_report.{json,csv,md}` in the same run dir. The `parity_status` column per
row shows PASS / WARN / FAIL against the gates above.

## Feature flags

Both are env-overridable for A/B comparison:

| Flag | Default | Effect when OFF |
|---|---|---|
| `SLEEVE_A_ENABLE_RSI_EXIT` | `1` | No exit on RSI > 65 (relies entirely on -3% stop) |
| `SLEEVE_A_ENABLE_PRICEPOS_EXIT` | `1` | No exit on price_position > 75% (relies entirely on -3% stop) |

For maximum parity with the freqtrade baseline, leave both ON.  The freqtrade strategy's
`populate_exit_trend` is empty (only the -3% stop is active), so flipping both OFF gives the
most faithful reproduction of the freqtrade behaviour.

## File map

```
src/research/nautilus/sleeve_a/
├── __init__.py        — public surface (strategy, config, build_catalog, run_parity)
├── strategy.py        — CometCloudNautilusMultiFactorV2 (Strategy + SleeveAConfig)
├── data_adapter.py    — feather → Nautilus ParquetDataCatalog
├── runner.py          — BacktestNode runner, structured JSON/CSV output
├── parity_check.py    — Nautilus vs freqtrade diff (JSON/CSV/MD report, with PASS/WARN/FAIL)
├── tests/
│   ├── __init__.py
│   └── test_strategy_smoke.py  — 6 unit tests: import + duck-type + compliance + ADX + key-norm + freqtrade-row-find
└── README.md          — this file
```

## Smoke tests (Cowork sandbox)

```bash
cd /Users/sbb/Projects/looloomi-ai
python3 -m pytest src/research/nautilus/sleeve_a/tests/test_strategy_smoke.py -v
# or directly:
python3 -m src.research.nautilus.sleeve_a.tests.test_strategy_smoke
```

6 tests cover: imports, duck-type contract, compliance language (no buy/sell/avoid),
feature flags toggleable, ADX update converges, instrument-key normalisation. All run
in-process — no live data, no Nautilus backtest.

## Compliance

Strategy classmethods + tags use positioning-language only (no
`buy` / `sell` / `accumulate` / `avoid`) per CLAUDE.md. `compliance_tag()`
returns `"CC_SLEEVE_A_NAUTILUS"`. Order tags use `LONG_ENTRY` / `HARD_STOP_3PCT` —
no directional action verbs.

## What's NOT in this skeleton (next sessions)

- **Two-layer combiner** (Sleeve A + Sleeve B per §STRATEGY-REVIVE C-S4) — owned by Minimax-C
- **Walk-forward harness** wired through `src/research/walk_forward.py` (the framework exists;
  this strategy just needs to plug into it)
- **Per-regime P&L attribution** — requires a CIS history map with regime tags; not needed
  for Sleeve A (the durable core does NOT have a regime veto by design)
- **Minimax-A's drive sync** — the data_adapter only runs on a fresh feather download; once
  Shadow/cometcloud-local/_data/ syncs back to the live drive, the catalog will have current data
- **Real CIS history wire-in** — Sleeve A is intentionally not gated on CIS; this is a feature,
  not a TODO

## Ownership + handoff

| Owner | Responsibility |
|---|---|
| **Seth (this dir)** | Engine plumbing: strategy.py, data_adapter.py, runner.py, parity_check.py. Code-only; never runs Nautilus (sandbox missing the package) |
| **Minimax-C** | freqtrade MultiFactorV2 baseline JSON (C-S1); two-layer combiner (C-S4); final "production" verdict after C-S3 OOS walk-forward passes |
| **Mac side (Jazz or Seth)** | Run the backtest commands in §3-6 above; commit any data fixes that fall out |
| **Sandbox side (this session)** | Code, smoke tests, coordination docs — NEVER `git push` (per CLAUDE.md) |