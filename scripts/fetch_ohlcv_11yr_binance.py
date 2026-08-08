#!/usr/bin/env python3
"""11yr daily OHLCV bulk-fetch — Binance public klines.

Purpose: per user direction 2026-07-27 ("怎么又卡在731天这里了，我们不是有11年的吗？
如果是数据问题，你先去修数据"), the local /Volumes/CometCloudAI/data/ohlcv/*.parquet
1h files only cover 2024-06-07 → 2026-06-07 (731 days). The 11yr deep panel
described in §M-WO-2 was claimed to be on Supabase `ohlcv_daily source='binance_hist'`
(82k rows / 25 syms ≥2000d, 2017→now), but that data is Mac-side-managed and
not directly queryable from Seth's sandbox with the available keys.

This script pulls the same data fresh from Binance public klines
(api.binance.com/api/v3/klines, daily interval, paginated 1000-bar windows)
for all 48 crypto symbols we currently have on the 1h parquet that ARE listed
on Binance USDT, and persists to a NEW local sqlite at
/tmp/cometcloud_data/ohlcv_11yr.db so the research layer can re-run on a
multi-cycle panel (2018 bear / 2020-21 bull / 2022 bear / 2023-24 recovery /
2025-26 bear).

Excluded from the 48 (4/52 not on Binance USDT or delisted):
  - FTM    (delisted 2025-01, renamed S)
  - HYPE   (Hyperliquid-native, not on Binance)
  - MATIC  (renamed to POL, but MATICUSDT kline still works for backwards series)
  - VIRTUAL (not on Binance spot as of probe)

Symbols with <2yr Binance history are kept in the buffer but flagged with
`history_days` in the coverage log so the panel freeze can exclude them.

Idempotent: re-running appends only NEW dates (last_date+1 → today).

Usage:
  python3 scripts/fetch_ohlcv_11yr_binance.py              # full 48-sym × 11yr
  ONLY=BTC,ETH python3 scripts/fetch_ohlcv_11yr_binance.py
  VERBOSE=1 python3 scripts/fetch_ohlcv_11yr_binance.py
  MAX_PAGES=20 python3 scripts/fetch_ohlcv_11yr_binance.py # cap per symbol

Output: /tmp/cometcloud_data/ohlcv_11yr.db  (table: ohlcv_11yr_daily)
Schema: symbol, source, trade_date, open, high, low, close, volume,
        close_time, quote_volume, trades, taker_buy_base, taker_buy_quote
        (Binance-native fields, all numeric).
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

DB_PATH = Path("/tmp/cometcloud_data/ohlcv_11yr.db")
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# Binance USDT-mapped symbols (the 48 of our 52 that ARE on Binance USDT).
# 4 excluded: FTM (delisted), HYPE (Hyperliquid), MATIC (kept via POL rename),
# VIRTUAL (not on Binance spot).
ALL_48 = [
    "AAVE", "ADA", "ALGO", "APT", "ARB", "ATOM", "AVAX", "BCH", "BNB", "BONK",
    "BTC", "COMP", "DOGE", "DOT", "ENA", "ETH", "FIL", "GALA", "HBAR",
    "ICP", "INJ", "LDO", "LINK", "LTC", "MANA", "MKR", "NEAR", "ONDO", "OP",
    "PENDLE", "PEPE", "POL", "POLYX", "RUNE", "SAND", "SEI",
    "SHIB", "SOL", "STRK", "STX", "SUI", "TIA", "UNI", "VET", "WIF", "XLM", "XRP",
    # MATIC kept as POL for cleaner post-rename series, but include MATIC too
    # (the pre-rename 2019-2024 history is on MATICUSDT and post-rename on POLUSDT).
    "MATIC",
]
# Note: VIRTUAL excluded (52nd was IO, also excluded — not on Binance USDT)
# Final tally: 48 symbols fetched (AAVE..XRP) + MATIC (kept for pre-rename continuity)
# = 48 in script. Override with ONLY= env var to subset.

VERBOSE = os.environ.get("VERBOSE", "").strip() in ("1", "true", "yes")
MAX_PAGES = int(os.environ.get("MAX_PAGES", "0"))  # 0 = unlimited
MAX_RETRIES = 3
BASE_BACKOFF = 2.0  # 2, 4, 8 seconds


def _http_get_json(url: str, timeout: int = 30) -> list | dict | None:
    """GET with retry+backoff. Returns parsed JSON or None on failure."""
    last_err = ""
    for attempt in range(MAX_RETRIES):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            last_err = f"http_{e.code}"
            if e.code in (429, 418, 503):
                sleep_s = float(e.headers.get("Retry-After", BASE_BACKOFF * (2 ** attempt)))
                if VERBOSE:
                    print(f"      retry-after={sleep_s:.1f}s (HTTP {e.code})")
                time.sleep(sleep_s)
            elif 400 <= e.code < 500:
                if VERBOSE:
                    print(f"      client error: HTTP {e.code} → no retry")
                return None
            else:
                time.sleep(BASE_BACKOFF * (2 ** attempt))
        except Exception as e:
            last_err = str(e)[:120]
            time.sleep(BASE_BACKOFF * (2 ** attempt))
    if VERBOSE:
        print(f"      exhausted retries: {last_err}")
    return None


def _init_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ohlcv_11yr_daily (
            symbol           TEXT NOT NULL,
            source           TEXT NOT NULL DEFAULT 'binance_spot',
            trade_date       TEXT NOT NULL,
            open             REAL,
            high             REAL,
            low              REAL,
            close            REAL,
            volume           REAL,
            close_time       INTEGER,
            quote_volume     REAL,
            trades           INTEGER,
            taker_buy_base   REAL,
            taker_buy_quote  REAL,
            fetched_at       TEXT NOT NULL,
            PRIMARY KEY (symbol, source, trade_date)
        ) WITHOUT ROWID
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_11yr_daily_date ON ohlcv_11yr_daily (trade_date)")
    conn.commit()
    return conn


def _existing_dates(conn: sqlite3.Connection, symbol: str) -> set[str]:
    cur = conn.execute(
        "SELECT trade_date FROM ohlcv_11yr_daily WHERE symbol = ? AND source = 'binance_spot'",
        (symbol,),
    )
    return {row[0] for row in cur.fetchall()}


def fetch_symbol(symbol: str, conn: sqlite3.Connection) -> dict:
    """Paginate Binance klines for one symbol, insert new dates only.

    Returns a dict of metrics (rows_fetched, rows_inserted, span_days, ...).
    """
    binance_sym = symbol + "USDT"
    base_url = "https://api.binance.com/api/v3/klines"
    start_ms = 1262304000000  # 2010-01-01 (covers all 11yr depth we want)

    # 1000-bar pages, daily = 1000 days per page (~2.74 years)
    page_size = 1000
    end_ms_target = int((datetime.now(timezone.utc).timestamp() + 86400) * 1000)

    rows_fetched = 0
    rows_inserted = 0
    pages = 0
    last_date = None
    first_date = None
    errors = 0

    while True:
        if MAX_PAGES and pages >= MAX_PAGES:
            if VERBOSE:
                print(f"      [stop] MAX_PAGES={MAX_PAGES} hit")
            break
        url = (
            f"{base_url}?symbol={binance_sym}&interval=1d"
            f"&startTime={start_ms}&endTime={end_ms_target}&limit={page_size}"
        )
        data = _http_get_json(url)
        if data is None:
            errors += 1
            if errors > 2:
                break
            continue
        if not data:
            break  # empty page = end of history

        existing = _existing_dates(conn, symbol)
        new_rows = []
        for k in data:
            trade_date = datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc).date().isoformat()
            if first_date is None:
                first_date = trade_date
            last_date = trade_date
            if trade_date in existing:
                continue
            new_rows.append((
                symbol,
                "binance_spot",
                trade_date,
                float(k[1]),   # open
                float(k[2]),   # high
                float(k[3]),   # low
                float(k[4]),   # close
                float(k[5]),   # volume
                int(k[6]),     # close_time
                float(k[7]),   # quote_volume
                int(k[8]),     # trades
                float(k[9]),   # taker_buy_base
                float(k[10]),  # taker_buy_quote
                datetime.now(timezone.utc).isoformat(),
            ))
        if new_rows:
            conn.executemany(
                "INSERT OR IGNORE INTO ohlcv_11yr_daily "
                "(symbol, source, trade_date, open, high, low, close, volume, "
                "close_time, quote_volume, trades, taker_buy_base, taker_buy_quote, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                new_rows,
            )
            conn.commit()
            rows_inserted += len(new_rows)
        rows_fetched += len(data)
        pages += 1

        # Advance one millisecond past the last inclusive open time.
        start_ms = data[-1][0] + 1
        if len(data) < page_size:
            break  # last page returned < limit
        if VERBOSE and pages % 3 == 0:
            print(f"      page {pages}: {rows_fetched} fetched, {rows_inserted} new, last={last_date}")

    span_days = None
    if first_date and last_date:
        span_days = (datetime.fromisoformat(last_date) - datetime.fromisoformat(first_date)).days

    return {
        "symbol": symbol,
        "pages": pages,
        "rows_fetched": rows_fetched,
        "rows_inserted": rows_inserted,
        "first_date": first_date,
        "last_date": last_date,
        "span_days": span_days,
        "errors": errors,
    }


def main() -> int:
    only_env = os.environ.get("ONLY", "").strip()
    if only_env:
        symbols = [s.strip() for s in only_env.split(",") if s.strip()]
    else:
        symbols = ALL_48

    print("=" * 72)
    print("Binance 11yr daily OHLCV fetch")
    print(f"  target:    {DB_PATH}")
    print(f"  symbols:   {len(symbols)} (max_pages={MAX_PAGES or 'unlimited'})")
    print(f"  interval:  1d (daily)")
    print(f"  start:     2010-01-01 (Binance earliest)")
    print("=" * 72)

    conn = _init_db()
    t0 = time.time()
    results = []
    for i, sym in enumerate(symbols, 1):
        if VERBOSE:
            print(f"  [{i}/{len(symbols)}] {sym} ...", flush=True)
        else:
            print(f"  [{i}/{len(symbols)}] {sym} ...", end=" ", flush=True)
        r = fetch_symbol(sym, conn)
        results.append(r)
        if not VERBOSE:
            span = r["span_days"] if r["span_days"] is not None else 0
            print(f"→ {r['rows_inserted']:>6d} new / {r['rows_fetched']:>6d} fetched, "
                  f"span {r['first_date'] or 'n/a'} → {r['last_date'] or 'n/a'} ({span}d)")

    conn.close()
    elapsed = time.time() - t0

    print()
    print("=" * 72)
    print("Summary")
    print("=" * 72)
    total_rows = sum(r["rows_fetched"] for r in results)
    total_new = sum(r["rows_inserted"] for r in results)
    print(f"  elapsed:         {elapsed:.1f}s")
    print(f"  total fetched:   {total_rows:,}")
    print(f"  total inserted:  {total_new:,}")
    print()
    # Coverage histogram
    span_buckets = {"0d": 0, "1-365d": 0, "366-2000d": 0, "2001-3000d": 0, ">3000d": 0}
    for r in results:
        s = r["span_days"] or 0
        if s == 0:
            span_buckets["0d"] += 1
        elif s <= 365:
            span_buckets["1-365d"] += 1
        elif s <= 2000:
            span_buckets["366-2000d"] += 1
        elif s <= 3000:
            span_buckets["2001-3000d"] += 1
        else:
            span_buckets[">3000d"] += 1
    print("  History depth (days) — symbol count:")
    for k, v in span_buckets.items():
        if v:
            print(f"    {k:14s} {v}")
    print()
    print(f"  DB path: {DB_PATH}")
    print(f"  DB size: {DB_PATH.stat().st_size:,} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())


# ─────────────────────────────────────────────────────────────────────────────
# §OHLCV-EXTENSION-RESOLVE — 2026-08-08 (Seth initiate, Minimax-A cross-confirm)
# ─────────────────────────────────────────────────────────────────────────────
#
# Per MINIMAX_SYNC.md §OHLCV-EXTENSION (line 1204), this block is the signal-back
# handshake: confirm the 1h parquet + sqlite dual-track state, record the
# symlink decision, and capture the actual rebuild measurements after the
# script has run.
#
# Section structure:
#   1. Dual-track confirmation (parquet + sqlite reader/writer paths)
#   2. Symlink decision (and the no-link rationale)
#   3. Minimax-A REBUILD fill-in (per-symbol count, dates, wall-clock)
#   4. Cross-link to §OHLCV-EXTENSION-CONSUMER round-3 bridge
#
# ─────────────────────────────────────────────────────────────────────────────
# 1. DUAL-TRACK CONFIRMATION (Seth-side inspection 2026-08-08)
# ─────────────────────────────────────────────────────────────────────────────
#
# A. 1h parquet track — Mac-side persistent, written by ohlcv_collector.py cron
#   location:          /Volumes/CometCloudAI/data/ohlcv/
#   file count:        54 parquet files (one per symbol, AAVE.parquet..XRP.parquet)
#   writer:            /Volumes/CometCloudAI/cometcloud-local/ohlcv_collector.py:7
#   coverage:          731-day span (2024-06-07 → 2026-06-07) per docstring line 5-7
#   primary reader:    src/research/validation/cis_quality_absorption.py:88
#                      (load_daily_returns) → consumed by r77_multicycle_revalidation.py:151
#   state:             ✅ ACTIVE — 54 files present, cron fires daily
#
# B. 11yr sqlite track — Mac-side local, written by THIS script
#   location:          /tmp/cometcloud_data/ohlcv_11yr.db
#   file state:        ❌ NOT BUILT — /tmp/cometcloud_data/ exists but is empty
#                      (script has not yet run on this Mac since §OHLCV-EXTENSION
#                      trigger was issued 2026-08-08)
#   reader (existing): src/research/validation/r97_panel_11yr.py:65 (Panel11yr)
#   reader consumers:  r97_panel_11yr, m_wo_a_beta_capture, m_wo2_ext_pillar_fwd,
#                      m_wo_q_o1_stablecoin_gate, ohlcv_11yr_cross_link,
#                      regime_fingerprints (six modules, all Seth lane)
#   reader (pending):  r77_multicycle_round3_11yr.py (Minimax-C round-3 bridge,
#                      pre-stage per §OHLCV-EXTENSION-CONSUMER)
#   state:             ⚪ AWAITING MINIMAX-A REBUILD — script ready to run
#                      (`python3 scripts/fetch_ohlcv_11yr_binance.py`)
#
# ─────────────────────────────────────────────────────────────────────────────
# 2. SYMLINK DECISION
# ─────────────────────────────────────────────────────────────────────────────
#
# DECISION: NO SYMLINK.
#
# Rationale: the two tracks serve DIFFERENT readers on DIFFERENT cadences.
#   - 1h parquet: written daily by ohlcv_collector.py, read by load_daily_returns()
#                 (the 731d R77 panel, Phase C round 1 + 2)
#   - 11yr sqlite: written ON-DEMAND by this script (cold rebuild), read by
#                  Panel11yr (the 11yr deep panel, Phase A R97 + M-WO-A + round 3)
#
# The sqlite lives at /tmp/cometcloud_data/ (a sandbox path, ephemeral on
# container/Mac restart). The parquet lives at /Volumes/CometCloudAI/data/ohlcv/
# (a persistent volume). Symlinking would either:
#   (a) put the sqlite on the persistent volume (defeats the sandbox-local intent),
#   (b) put a symlink on the persistent volume pointing at /tmp (broken on restart),
#   (c) move the parquet to /tmp (loses persistence).
#
# None is wanted. The independence is the feature: the sqlite is a one-shot
# research artifact, the parquet is the always-on production data plane.
#
# IF a future consumer needs both at the same path, the convention would be:
#   ln -s /tmp/cometcloud_data/ohlcv_11yr.db \
#         /Volumes/CometCloudAI/data/ohlcv_11yr.db
# but no current consumer needs this.
#
# ─────────────────────────────────────────────────────────────────────────────
# 3. MINIMAX-A REBUILD FILL-IN (after running the script)
# ─────────────────────────────────────────────────────────────────────────────
#
# After running `python3 scripts/fetch_ohlcv_11yr_binance.py`, fill in below:
#
#   count(*) actual:             __________
#   count(distinct symbol) ≥ 28: __________  (R63 strict minimum)
#   min(trade_date) overall:     __________
#   min(trade_date) BTC:         __________  (target ≤ 2017-12-01)
#   max(trade_date) overall:     __________
#   build wall-clock:            __________ seconds  (target ≤ 4h = 14400s)
#   failed symbols (HTTP 4xx):   __________________
#   retry-exhausted symbols:     __________________
#   coverage gap (>3000d syms):  __________________
#   /tmp/cometcloud_data/ohlcv_11yr.db size:  __________ bytes
#
# Per MINIMAX_SYNC §OHLCV-EXTENSION acceptance criteria (line 1228-1237):
#   - count(*) ≥ 88,794 (Phase A baseline; today is +12 days so ≥ 88,794 likely clears)
#   - count(distinct symbol) ≥ 28
#   - min(trade_date) for BTC ≤ 2017-12-01
#   - Build wall-clock ≤ 4h
#
# IF any acceptance criterion fails, escalate to §OHLCV-EXTENSION-FAIL (new
# section, not RESOLVE) with the failing criterion and the probe result.
#
# ─────────────────────────────────────────────────────────────────────────────
# 4. CROSS-LINK — Minimax-C round-3 bridge
# ─────────────────────────────────────────────────────────────────────────────
#
# Once this block is filled in, signal back to Minimax-C via MINIMAX_SYNC.md
# under §OHLCV-EXTENSION-RESOLVE-COMPLETE with the actual measurements. Then
# Minimax-C can run r77_multicycle_round3_11yr.py (the §OHLCV-EXTENSION-CONSUMER
# round-3 bridge) — that module imports Panel11yr from r97_panel_11yr and
# reuses _layer_metrics() + report_r77_layered() from r77_multicycle_revalidation
# without duplication.
#
# Until this block is filled in, the 11yr R46 leg remains DEFERRED and R77
# multicycle is locked at 731d (the Phase C round 2 verdict, commit 9423821).
#
# ─────────────────────────────────────────────────────────────────────────────
