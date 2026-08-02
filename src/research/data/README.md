# src/research/data/ — Off-Engine Data Loaders

> **Lane boundary (2026-07-26):** Production reads from Supabase `ohlcv_daily`
> (Mac-side daily loop covers 22 crypto + AAPL). Research code that needs the
> **full 58-symbol universe** (especially the 35 TradFi symbols Mac-side does
> NOT write) reads from **local SQLite at `/tmp/cometcloud_data/ohlcv.db`**
> via this module. Per Jazz: do NOT push to Supabase; do NOT fix Railway
> httpx UA bug; §SEC hardening stays.

---

## What's here

| File | Purpose |
|---|---|
| `ohlcv_local.py` | Active loader — read full 58-symbol universe from local SQLite |
| `tests/test_ohlcv_local_smoke.py` | 10 smoke tests (all PASS) |

---

## Quick start

```python
from src.research.data.ohlcv_local import (
    load_local_daily, load_local_panel, get_coverage,
    check_local_buffer_freshness, validate_local_buffer, refresh,
)

# Single symbol — daily OHLCV (Date-indexed DataFrame)
df = load_local_daily("SPY")
print(df.tail())  # columns: open, high, low, close, volume, source

# Multi-symbol close panel (Date × symbol) — for cross-asset / factor work
panel = load_local_panel(["BTC", "ETH", "SPY", "TLT", "GLD"])
returns = panel.pct_change()

# Audit: what's in the buffer?
cov = get_coverage()  # per-symbol rows + date range + source

# Check freshness before trusting results
status = check_local_buffer_freshness(max_age_days=7)
print(status["verdict"])  # "fresh" | "warning" | "stale"

# Data quality scan — outliers, gaps, source conflicts, stale symbols
issues = validate_local_buffer()
if not issues.empty:
    print(f"⚠️ {len(issues)} quality issues:")
    print(issues.head(10))

# Manual refresh (when stale)
refresh(days=365)
```

---

## API reference

### `load_local_daily(symbol, source=None, start=None, end=None) -> DataFrame`

- **`symbol`** — ticker (e.g. `"BTC"`, `"SPY"`, `"TLT"`)
- **`source`** — filter by source (`"coingecko" | "hyperliquid" | "eodhd" | None`)
- **`start/end`** — ISO date strings (`"2024-06-01"`), inclusive start, exclusive end
- **returns** — DataFrame with columns `[open, high, low, close, volume, source]`,
  indexed by UTC tz-aware `trade_date`. Empty DataFrame (not error) if no rows.

### `load_local_panel(symbols, source=None, start=None, end=None) -> DataFrame`

Multi-symbol **close-price** panel pivoted to `Date × symbol`. Missing values
become NaN. Useful for cross-asset returns, correlations, factor work.

### `get_coverage() -> DataFrame`

Per `(symbol, asset_class, source)` audit: row count, first/last date. Use
this to discover what's available before designing a study.

### `check_local_buffer_freshness(max_age_days=7) -> dict`

Lightweight probe — does NOT re-fetch. Returns:
```python
{
    "last_trade_date": "2026-07-26",
    "buffer_age_days": 0,
    "max_age_days": 7,
    "verdict": "fresh",        # "fresh" | "warning" | "stale"
    "symbols": 58,
    "rows_total": 17375,
}
```

Use at the top of research scripts to fail-fast on stale data.

Set env var `LOUD_LOCAL_OHLCV=1` to auto-warn on every `load_local_daily()`
/ `load_local_panel()` call (default: silent unless buffer is very stale).

### `validate_local_buffer(outlier_ratio=10.0, source_divergence_pct=5.0, max_date_gap_days=5) -> DataFrame`

Scan the buffer for quality issues. Returns a DataFrame with columns
`issue_type, symbol, asset_class, source, trade_date, details, magnitude`.
Empty DataFrame if clean. `issue_type` is one of:

- **`outlier`** — close moved >`outlier_ratio`× vs prior close (default 10x).
  Catches 99% of legit moves; flags BTC halving pumps, exchange glitches,
  bad splits, etc.
- **`date_gap`** — consecutive-day gap exceeds `max_date_gap_days` (default 5,
  covers weekend+1 holiday for TradFi). Crypto should never trigger this;
  if it does, the source feed died.
- **`source_conflict`** — same (symbol, date) from 2+ sources with prices
  diverging >`source_divergence_pct`% (default 5%). Catches source-bug or
  API versioning issues.
- **`stale`** — last_date > 14 days old.

Sorted by `issue_type` priority: source_conflict > outlier > date_gap > stale.

### `refresh(days=365, only=None) -> dict`

Re-run the upstream fetcher (`scripts/fetch_ohlcv_to_local.py`). Idempotent
INSERT OR REPLACE. ~60s for full 58×365d. Returns subprocess result.

---

## Source ladder (mirrors `src/api/routers/ohlcv.py`)

Crypto (`ASSETS_CONFIG` entries with `coingecko:` field):
1. **CoinGecko Pro** `market_chart/range` — primary, requires
   `COINGECKO_API_KEY` from Mac-side `.env`, must set explicit
   `User-Agent: cc-ohlcv-fetch/1.0 (+cometcloud)` (CG Pro blocks Python UAs).
2. **Hyperliquid** `candleSnapshot` — fallback if CG Pro fails / rate-limits.
   Coverage: BTC/ETH/SOL/BNB/XRP/ADA/AVAX/DOT/NEAR/SUI/APT/HYPE/ARB/OP/POL/
   STRK/UNI/AAVE/LDO/PENDLE/LINK/INJ/TIA/ONDO/MKR.

TradFi (`ASSETS_CONFIG` entries with `yfinance:` field):
1. **EODHD** `/eod` — primary, requires `EODHD_API_KEY` from Mac-side `.env`.
2. (yfinance is a Railway-side fallback that is rate-limited and not used here.)

---

## Refresh cadence

- **Default:** manual. Run `bash scripts/refresh_local_ohlcv.sh` whenever
  the buffer is stale (>7 days). This is research lane, no cron.
- **Incremental mode:** `fetch_ohlcv_to_local.py` is incremental-aware — only
  fetches from `(last_buffer_date + 1)` for each symbol. Daily refresh takes
  ~5s instead of ~60s. Pass `FORCE_FULL=1` to ignore incremental and re-fetch.
- **Retry-with-backoff:** all 3 sources (CG Pro / Hyperliquid / EODHD) retry
  3× with 2/4/8s sleeps and respect `Retry-After` headers on 429/503.
- **Why not cron'd:** production freshness is Mac-side `ohlcv_collector.py`'s
  responsibility. Local SQLite is a research convenience; auto-refreshing it
  would mask gaps in the production path.
- **If you need fresh data:** `python3 scripts/fetch_ohlcv_to_local.py` (or
  call `refresh()` from the loader).

### Status check (no fetch)

```bash
bash scripts/check_local_ohlcv.sh
```

Prints: buffer size, rows, symbol count, per-asset-class breakdown,
last_date, age in days, freshness verdict (✅ FRESH / 🟡 WARNING / 🔴 STALE),
plus remediation hint if stale.

---

## Coverage (as of 2026-07-26)

| Asset class | In Supabase | In local SQLite |
|---|---|---|
| L1 / L2 / DeFi / RWA (crypto) | 22/22 covered | 22/22 covered |
| US Equity | 1/9 (only AAPL) | 9/9 covered |
| US Bond | 0/6 | 6/6 covered |
| Commodity | 0/6 | 6/6 covered |
| FX | 0/4 | 4/4 covered |
| Real Estate | 0/3 | 3/3 covered |
| EM Equity | 0/3 | 3/3 covered |
| **Total** | **23/58** | **58/58** |

**Missing from Supabase (35 symbols):** SPY, QQQ, MSFT, NVDA, GOOGL, AMZN,
META, TSLA, XLF, TLT, IEF, SHY, TIP, HYG, LQD, GLD, SLV, USO, UNG, CPER, DBA,
UUP, FXE, FXY, FXI, VNQ, IYR, VNQI, EEM, VWO, INDA, EWZ.

---

## Testing

```bash
python3 -m pytest src/research/data/tests/test_ohlcv_local_smoke.py -v
```

10 tests covering: buffer exists, coverage shape, asset-class coverage,
single-symbol load (crypto + TradFi), source filter, date filter, panel
shape, PIT correctness (no future-dated rows), missing-symbol empty
result, staleness detection, multiple sources per symbol, panel with
mixed available/missing symbols.

(Actually 21 tests as of 2026-07-26: + staleness shape/custom-threshold/
default-fresh, panel-tz-aware-UTC, no-duplicate-dates, coverage-row-count-
matches-loader, validate_local_buffer default-clean + returns-expected-
columns + strict-gap-flags-crypto + strict-outlier.)

---

## Background (the full story)

- **CLAUDE.md** §"Operational loop" — the daily discipline
- **MEMORY.md** index — `[2026-07-26 Local OHLCV Off-Engine]` pointer
- **memory/2026-07-26-local-ohlcv-off-engine.md** — full decision memo
- **PROJECT_STATE.md** "Last updated" header — `§OHLCV-OFF-ENGINE` paragraph
- **REFUTATION_LEDGER.md** — historical context for R76/R77 fusion lane
  that motivated the cross-asset data need

The short version: Mac-side writes 22 crypto + AAPL daily; Railway daily
loop has been dead 7+ days (httpx UA bug + publishable-key GRANT denial);
35 TradFi symbols are missing from Supabase and will STAY missing per
Jazz decision. Local SQLite is the lighter path forward.

---

*Build things that feel alive.*