#!/usr/bin/env python3
"""
Data extender — download Binance USDT-margined perp klines for new symbols.

Source: Binance public API (no auth needed for klines).
Output: /Volumes/CometCloudAI/data/ohlcv/{SYMBOL}.parquet (1h bars)

Usage:
    # Download a specific list of symbols
    python scripts/data_extend.py --symbols BTC,ETH,SOL

    # Download all 20 active universe symbols
    python scripts/data_extend.py --active

    # Download a single symbol
    python scripts/data_extend.py --symbol NEAR

    # Use 1d timeframe instead of 1h
    python scripts/data_extend.py --symbol BTC --timeframe 1d

    # Custom start date
    python scripts/data_extend.py --symbols BTC,ETH --start 2024-01-01

Note: Binance blocks US IPs. Run from the Mac Mini which is not US-blocked.
On Railway, Binance API is not accessible — use ccxt / CryptoRank / CoinGecko
fallbacks instead.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Sequence

import requests

import pandas as pd


BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
OHLCV_DIR = Path("/Volumes/CometCloudAI/data/ohlcv")

logger = logging.getLogger("data_extend")


def _binance_to_df(klines: list) -> pd.DataFrame:
    """Convert raw Binance klines JSON to DataFrame (UTC, ms timestamps)."""
    rows = []
    for k in klines:
        # kline: [openTime, open, high, low, close, volume, closeTime,
        #         quoteVolume, nTrades, takerBuyBase, takerBuyQuote, ignore]
        rows.append({
            "timestamp": pd.to_datetime(k[0], unit="ms", utc=True),
            "open":      float(k[1]),
            "high":      float(k[2]),
            "low":       float(k[3]),
            "close":     float(k[4]),
            "volume":    float(k[5]),
        })
    df = pd.DataFrame(rows).sort_values("timestamp").reset_index(drop=True)
    return df


def fetch_klines(
    symbol: str,
    interval: str = "1h",
    start: Optional[str] = None,
    end: Optional[str] = None,
    max_per_request: int = 1000,
) -> pd.DataFrame:
    """Fetch klines from Binance with pagination.

    Args:
        symbol: BASE symbol, e.g. "BTC" (we'll request "BTCUSDT").
        interval: "1h", "4h", "1d", etc.
        start: start date string YYYY-MM-DD (default 2 years ago).
        end: end date string YYYY-MM-DD (default now).
        max_per_request: Binance API limit per call.

    Returns:
        DataFrame with columns [timestamp, open, high, low, close, volume].
    """
    pair = f"{symbol}USDT"
    if start:
        start_ms = int(datetime.strptime(start, "%Y-%m-%d")
                       .replace(tzinfo=timezone.utc).timestamp() * 1000)
    else:
        start_ms = int((datetime.now(timezone.utc) - timedelta(days=730)).timestamp() * 1000)
    end_ms = int(datetime.strptime(end, "%Y-%m-%d")
                 .replace(tzinfo=timezone.utc).timestamp() * 1000) if end else None

    all_rows: list = []
    cursor = start_ms
    page = 0
    while True:
        page += 1
        params = {
            "symbol": pair,
            "interval": interval,
            "startTime": cursor,
            "limit": max_per_request,
        }
        if end_ms is not None:
            params["endTime"] = end_ms
        resp = requests.get(BINANCE_KLINES_URL, params=params, timeout=15)
        resp.raise_for_status()
        klines = resp.json()
        if not klines:
            break
        all_rows.extend(klines)
        cursor = klines[-1][0] + 1   # next bar after last close-open
        if len(klines) < max_per_request:
            break
        if end_ms is not None and cursor >= end_ms:
            break
        time.sleep(0.1)  # rate-limit friendliness

    if not all_rows:
        raise RuntimeError(f"no data returned for {pair} ({interval})")
    df = _binance_to_df(all_rows)
    logger.info(f"  fetched {len(df)} {interval} bars for {pair}")
    return df


def save_parquet(df: pd.DataFrame, symbol: str, timeframe: str = "1h") -> Path:
    """Save DataFrame to the standard OHLCV location as parquet.

    Filename includes the timeframe suffix when not 1h, to keep both
    resolutions on disk without clobbering each other.
    """
    OHLCV_DIR.mkdir(parents=True, exist_ok=True)
    suffix = "" if timeframe == "1h" else f"_{timeframe}"
    out_path = OHLCV_DIR / f"{symbol}{suffix}.parquet"
    df.to_parquet(out_path, index=False)
    logger.info(f"  saved → {out_path}")
    return out_path


def extend_symbol(
    symbol: str,
    interval: str = "1h",
    start: Optional[str] = None,
    end: Optional[str] = None,
    overwrite: bool = False,
) -> Path:
    """Download + save one symbol. Skips if data already exists (unless overwrite)."""
    suffix = "" if interval == "1h" else f"_{interval}"
    target = OHLCV_DIR / f"{symbol}{suffix}.parquet"
    if target.exists() and not overwrite:
        logger.info(f"  {symbol}: already exists at {target} (use --overwrite to replace)")
        return target
    df = fetch_klines(symbol, interval, start, end)
    return save_parquet(df, symbol, interval)


def extend_symbols(
    symbols: Sequence[str],
    interval: str = "1h",
    start: Optional[str] = None,
    end: Optional[str] = None,
    overwrite: bool = False,
) -> list[Path]:
    """Download + save multiple symbols. Failures are logged and skipped."""
    out = []
    for i, sym in enumerate(symbols):
        try:
            out.append(extend_symbol(sym, interval, start, end, overwrite))
        except Exception as exc:
            logger.error(f"  {sym}: FAILED — {exc}")
        if i < len(symbols) - 1:
            time.sleep(0.5)  # be polite to Binance
    return out


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Download Binance perp klines for new symbols.")
    parser.add_argument("--symbol", help="single symbol to download, e.g. NEAR")
    parser.add_argument("--symbols", help="comma-separated list, e.g. BTC,ETH,SOL")
    parser.add_argument("--active", action="store_true",
                        help="download the curated ACTIVE_UNIVERSE (20 symbols)")
    parser.add_argument("--interval", default="1h", help="kline interval (1h, 4h, 1d)")
    parser.add_argument("--start", help="start date YYYY-MM-DD (default 2y ago)")
    parser.add_argument("--end", help="end date YYYY-MM-DD (default now)")
    parser.add_argument("--overwrite", action="store_true",
                        help="replace existing parquet files")
    args = parser.parse_args()

    # Build list of symbols
    if args.symbol:
        symbols = [args.symbol.upper()]
    elif args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",")]
    elif args.active:
        # Lazy import to avoid pulling universe module when --symbol is used
        from src.research.universe import ACTIVE_UNIVERSE
        symbols = ACTIVE_UNIVERSE
    else:
        parser.print_help()
        print()
        print("Error: specify --symbol, --symbols, or --active")
        return 1

    logger.info(f"Downloading {len(symbols)} symbols @ {args.interval}: {symbols}")
    if args.start:
        logger.info(f"  range: {args.start} → {args.end or 'now'}")
    paths = extend_symbols(symbols, args.interval, args.start, args.end, args.overwrite)
    logger.info(f"Done. {len(paths)}/{len(symbols)} files written.")
    return 0


if __name__ == "__main__":
    sys.exit(main())