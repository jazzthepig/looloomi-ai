#!/usr/bin/env python3
"""
Fetch extended 4h OHLCV history for LS v1 strategy validation
(Minimax-B, 2026-07-15).

Pulls 9 years of BTC/ETH spot 4h bars (2017-08-17 → today) and 6 years of
SOL (2020-08-11 → today) from Binance via CCXT (free public API).

Why this exists:
    The existing `freqtrade/user_data/data/binance/futures/*-4h-futures.feather`
    files only cover 2.5 years (2024-01-01 → 2026-07-15) — that's because
    freqtrade's bulk-downloader pulls from the futures endpoint, and Binance
    USDT-margined perps only started in 2019-09 (BTC) / 2019-11 (ETH) /
    2020-09 (SOL).

    For Phase B validation we need ≥ 5 years of independent OOS windows.
    Spot 4h bars from Binance go back to 2017-08-17 (BTC/ETH) / 2020-08-11
    (SOL). The LS v1 signal layer (EMA cross + ADX + CIS gate) does not
    depend on funding rate (ENABLE_FUNDING_FILTER=False by default), so
    spot bars are a valid input for strategy validation — the live engine
    still trades perps, but the alpha signal is exchange-agnostic.

Output:
    /Volumes/CometCloudAI/cometcloud-local/_data/ohlcv/4h-spot/{ASSET}_USDT-4h-spot.feather

Usage:
    python3 scripts/fetch_extended_history.py
    python3 scripts/fetch_extended_history.py --assets BTC ETH
    python3 scripts/fetch_extended_history.py --since 2017-08-17
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import ccxt
import pandas as pd


# ── Constants ────────────────────────────────────────────────────────────────

# Output dir (lives on the external CometCloudAI SSD under a new dedicated
# subtree `looloomi-research/`. The `cometcloud-local/` and `data/` subtrees
# of the SSD are Minimax's territory per CLAUDE.md §5 ownership rule; this
# new dir is Seth/Austin's research-data holding area and is documented in
# MINIMAX_SYNC §11.9 as the "extended OHLCV" lineage. NOT committed to git
# — this is raw data, 1.8 MB total.)
DEFAULT_OUT_DIR = Path(
    "/Volumes/CometCloudAI/looloomi-research/data/ohlcv/4h-spot/"
)

# Binance spot earliest 4h bar per asset. Dates reflect Binance spot listing
# (or CCXT earliest available 4h bar — Binance's `klines` endpoint returns
# up to the listing date). L1s are ~2017-08, L2s / DeFi tokens are 2019-2020,
# newer L2s are 2023+. The dates below are the dates where 4h bars exist;
# some assets pre-date Binance spot (e.g. XLM, LTC on other venues) but we
# only need Binance for backtest continuity with the live venue.
#
# Strategy grid (R21 fallout) needs ≥20 names for cross-sectional pair-trade.
# The 13 added here are the L1 majors + L2/DeFi that:
#   1. Have ≥ 3 years of Binance spot 4h bars (long enough for OOS)
#   2. Are in the live CIS universe (so a future live pair-trade can run)
#   3. Have liquidity deep enough for realistic backtest fill assumptions
SPOT_EARLIEST = {
    # Original 3 (have)
    "BTC": "2017-08-17",
    "ETH": "2017-08-17",
    "SOL": "2020-08-11",
    # L1 majors (deep liquidity, long history)
    "LTC": "2017-12-13",
    "BNB": "2017-11-06",
    "XRP": "2018-05-04",
    "ADA": "2018-04-17",
    "DOGE": "2019-07-08",
    "DOT": "2020-08-19",
    "LINK": "2019-01-16",
    "AVAX": "2020-09-22",
    "ATOM": "2019-04-29",
    "NEAR": "2020-10-13",
    # L2 / DeFi (regime-orthogonal vol)
    "MATIC": "2019-04-26",
    "UNI": "2020-09-17",
    "AAVE": "2020-10-15",
    "MKR": "2017-12-12",
    # Newer L1 / L2 (shorter history but regime coverage)
    "APT": "2022-10-19",
    "ARB": "2023-03-23",
    "OP": "2023-05-31",
    "SUI": "2023-05-03",
}


# ── Fetch helper ────────────────────────────────────────────────────────────

def fetch_4h_spot(symbol: str, since_iso: str) -> pd.DataFrame:
    """Fetch all 4h bars for `symbol` from `since_iso` to now.

    Returns a DataFrame with columns [date, open, high, low, close, volume].
    """
    exchange = ccxt.binance({"enableRateLimit": True, "enableCORS": False})
    since_ts = int(exchange.parse8601(since_iso + "T00:00:00Z"))
    all_bars = []
    page_count = 0
    started = time.monotonic()

    while True:
        try:
            batch = exchange.fetch_ohlcv(symbol, "4h", since=since_ts, limit=1000)
        except Exception as exc:  # noqa: BLE001
            print(f"  WARN: {symbol} page {page_count} failed: {exc!r}; retry in 5s")
            time.sleep(5)
            continue
        if not batch:
            break
        all_bars.extend(batch)
        page_count += 1
        # Move since_ts past the last bar's timestamp (+1ms to avoid duplicate)
        last_ts = batch[-1][0]
        if last_ts <= since_ts:
            # No progress — bail
            print(f"  WARN: {symbol} stalled at page {page_count}; aborting pagination")
            break
        since_ts = last_ts + 1
        # If the batch returned < limit, we've reached the present
        if len(batch) < 1000:
            break
        # Rate-limit courtesy pause (CCXT enableRateLimit handles most of this)
        time.sleep(0.05)

    if not all_bars:
        raise RuntimeError(f"{symbol}: no bars returned from {since_iso}")

    df = pd.DataFrame(all_bars, columns=["ts", "open", "high", "low", "close", "volume"])
    df["date"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    df = df.drop(columns=["ts"])
    df = df[["date", "open", "high", "low", "close", "volume"]]
    df = df.sort_values("date").reset_index(drop=True)
    # De-dup
    df = df.drop_duplicates(subset=["date"], keep="last").reset_index(drop=True)

    elapsed = round(time.monotonic() - started, 2)
    print(f"  {symbol}: {len(df):,} bars, "
          f"{df['date'].min().date()} → {df['date'].max().date()}, "
          f"{elapsed}s ({page_count} pages)")
    return df


# ── Main ─────────────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--assets", nargs="+", default=["BTC", "ETH", "SOL"],
        help="Assets to fetch (default: BTC ETH SOL)",
    )
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    ap.add_argument("--since", type=str, default=None,
                    help="Override start date (YYYY-MM-DD) for all assets")
    args = ap.parse_args(argv)

    args.out_dir.mkdir(parents=True, exist_ok=True)

    summary = []
    for asset in args.assets:
        asset = asset.upper()
        if asset not in SPOT_EARLIEST and args.since is None:
            print(f"ERROR: {asset} not in SPOT_EARLIEST and no --since given; "
                  f"known: {list(SPOT_EARLIEST.keys())}", file=sys.stderr)
            return 1
        since = args.since or SPOT_EARLIEST[asset]
        symbol = f"{asset}/USDT"
        out_path = args.out_dir / f"{asset}_USDT-4h-spot.feather"
        print(f"[{asset}] fetching {symbol} 4h spot from {since} →")
        df = fetch_4h_spot(symbol, since)
        df.to_feather(out_path)
        summary.append({
            "asset": asset,
            "rows": len(df),
            "first": str(df["date"].min().date()),
            "last": str(df["date"].max().date()),
            "out": str(out_path),
        })

    # Write index file
    index_path = args.out_dir / "INDEX.json"
    index_path.write_text(pd.DataFrame(summary).to_json(orient="records", indent=2))
    print(f"\nwrote {len(summary)} feather files to {args.out_dir}")
    print(f"index → {index_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
