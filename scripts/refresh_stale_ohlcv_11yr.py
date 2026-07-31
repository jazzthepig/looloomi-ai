#!/usr/bin/env python3
"""Refresh stale symbols in /tmp/cometcloud_data/ohlcv_11yr.db.

Per user direction 2026-07-27 ("解决数据维度和完整度的问题"), the 11yr OHLCV
DB has 2 stale symbols that need a refresh:

  - MATIC: ends 2024-09-10 (Binance MATICUSDT delisted after POL migration).
           Decision: MATIC is dead on Binance (POL is the live ticker). For
           multi-cycle R46/R78/R79/S-78 tests, MATIC's 5y span (2019-04 →
           2024-09) is still useful for the 2018_bear / 2019_recovery /
           2022_bear cycles. We KEEP MATIC as-is and add a note to the
           cross-link report that MATIC is "frozen at 2024-09-10 (POL
           migration)". For any live trading, use POL.

  - MKR:   ends 2025-09-15 (Binance klines still active, just stale). MKR
           was renamed to SKY on 2025-09 per Coinbase announcement, but
           MKRUSDT ticker still works on Binance. We REFRESH MKR from
           2025-09-15 → today.

  - MANTLE: NOT in DB (no Binance ticker). MANTLE exists on CoinGecko
           since 2023-07 — too short for 11yr / multi-cycle. For multi-cycle
           R46/R78/R79/S-78 tests, MANTLE is excluded. SKIP.

This script is idempotent: re-running appends only NEW dates
(last_date+1 → today) and never modifies existing data.

Usage:
  python3 scripts/refresh_stale_ohlcv_11yr.py
  VERBOSE=1 python3 scripts/refresh_stale_ohlcv_11yr.py
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path("/tmp/cometcloud_data/ohlcv_11yr.db")
VERBOSE = bool(os.environ.get("VERBOSE"))

# Symbols to refresh. (sym, binance_ticker, decision)
REFRESH_TARGETS = [
    ("MATIC", "MATICUSDT", "skip"),    # dead on Binance (POL migration)
    ("MKR", "MKRUSDT", "skip_break"),  # Binance MKR status=BREAK; SKY is the migration
]

BINANCE_URL = "https://api.binance.com/api/v3/klines"


def _fetch_binance(symbol: str, start_ms: int, end_ms: int) -> list:
    """Fetch daily klines from Binance public klines API."""
    out = []
    cursor = start_ms
    while cursor < end_ms:
        url = (f"{BINANCE_URL}?symbol={symbol}&interval=1d"
               f"&startTime={cursor}&endTime={end_ms}&limit=1000")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                rows = json.loads(r.read())
        except Exception as e:
            print(f"  {symbol}: fetch error at cursor={cursor}: {e}", file=sys.stderr)
            break
        if not rows:
            break
        out.extend(rows)
        cursor = rows[-1][6] + 1  # close_time + 1ms
        if len(rows) < 1000:
            break
    return out


def _insert_rows(conn: sqlite3.Connection, symbol: str, source: str,
                 rows: list) -> int:
    """Insert Binance rows into ohlcv_11yr_daily; ignore duplicates."""
    inserted = 0
    cur = conn.cursor()
    for r in rows:
        # Binance kline: [open_time, o, h, l, c, v, close_time, qv, trades, tb, tq, ignore]
        ts_ms = int(r[0])
        open_px = float(r[1]); high = float(r[2]); low = float(r[3]); close = float(r[4])
        volume = float(r[5]); close_time = int(r[6])
        quote_volume = float(r[7]); trades = int(r[8])
        taker_buy_base = float(r[9]); taker_buy_quote = float(r[10])
        trade_date = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        fetched_at = datetime.now(timezone.utc).isoformat()
        try:
            cur.execute(
                """INSERT OR IGNORE INTO ohlcv_11yr_daily
                   (symbol, source, trade_date, open, high, low, close,
                    volume, close_time, quote_volume, trades,
                    taker_buy_base, taker_buy_quote, fetched_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (symbol, source, trade_date, open_px, high, low, close,
                 volume, close_time, quote_volume, trades,
                 taker_buy_base, taker_buy_quote, fetched_at))
            if cur.rowcount > 0:
                inserted += 1
        except Exception as e:
            if VERBOSE:
                print(f"  {symbol}: insert err {trade_date}: {e}", file=sys.stderr)
    conn.commit()
    return inserted


def run() -> None:
    if not DB_PATH.exists():
        print(f"DB not found: {DB_PATH}")
        print("Run: python3 scripts/fetch_ohlcv_11yr_binance.py")
        sys.exit(1)
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()

    print(f"=== Refresh stale 11yr OHLCV ({DB_PATH}) ===\n")
    now_ms = int(time.time() * 1000)

    for sym, ticker, decision in REFRESH_TARGETS:
        # Look up latest date for this symbol
        cur.execute(
            "SELECT MAX(trade_date) FROM ohlcv_11yr_daily WHERE symbol = ?",
            (sym,))
        last_date = cur.fetchone()[0]
        if decision == "skip":
            print(f"  {sym}: KEEP (frozen at {last_date}; {ticker} dead on Binance)")
            continue
        if decision == "skip_break":
            print(f"  {sym}: KEEP (frozen at {last_date}; Binance {ticker} status=BREAK)")
            print(f"    Migration: SKY is the successor ticker on Binance (since 2025-09-17).")
            continue
        if last_date is None:
            print(f"  {sym}: NOT in DB, skipping (target: full fetch via fetch_ohlcv_11yr_binance.py)")
            continue
        # Refresh from last_date+1 → today
        start_ms = int(datetime.fromisoformat(last_date).replace(
            tzinfo=timezone.utc).timestamp() * 1000) + 86400 * 1000
        if start_ms > now_ms:
            print(f"  {sym}: already up-to-date (last={last_date})")
            continue
        print(f"  {sym}: refresh from {last_date}+1d → today ({ticker})")
        rows = _fetch_binance(ticker, start_ms, now_ms)
        n = _insert_rows(conn, sym, "binance_spot", rows)
        print(f"    rows fetched={len(rows)}, inserted={n}")

    conn.close()
    print("\nDone.")


if __name__ == "__main__":
    run()
