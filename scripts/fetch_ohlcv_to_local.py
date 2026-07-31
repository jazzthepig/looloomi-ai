#!/usr/bin/env python3
"""Local OHLCV bulk-fetch — bypass Supabase rate limit by writing to SQLite.

Sources (in priority, mirror Railway ohlcv.py):
  1. CoinGecko Pro market_chart/range (interval=daily) — crypto
  2. Hyperliquid candleSnapshot                            — crypto fallback
  3. EODHD /eod                                            — TradFi

Output: /tmp/cometcloud_data/ohlcv.db (idempotent, key = (symbol, trade_date, source))

Features:
  - Retry-with-exponential-backoff on transient errors (3 attempts: 2/4/8s)
  - Respects Retry-After header from 429/503 responses
  - Incremental refresh: if buffer exists, only fetches from (last_date+1) → today
  - Per-symbol fetch metrics: source used, rows, elapsed, retry count
  - Final summary table: source breakdown, success rate, slowest symbol

Usage:
  python3 scripts/fetch_ohlcv_to_local.py                 # full universe 365d
  DAYS=90 ONLY=BTC,ETH python3 scripts/fetch_ohlcv_to_local.py
  FORCE_FULL=1 python3 scripts/fetch_ohlcv_to_local.py    # skip incremental mode
  VERBOSE=1 python3 scripts/fetch_ohlcv_to_local.py       # per-symbol detail
"""
from __future__ import annotations

import os
import sys
import json
import time
import sqlite3
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta, date as date_cls
from pathlib import Path

# Read API keys from Mac-side .env (Seth-side .env is placeholder)
from dotenv import dotenv_values
MAC_ENV = Path("/Volumes/CometCloudAI/cometcloud-local/.env")
_keys = dotenv_values(MAC_ENV) if MAC_ENV.exists() else {}
CG_API_KEY    = _keys.get("COINGECKO_API_KEY") or _keys.get("CG_PRO_API_KEY") or ""
EODHD_API_KEY = _keys.get("EODHD_API_KEY", "")

DB_PATH = Path("/tmp/cometcloud_data/ohlcv.db")
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.data.cis.cis_provider import ASSETS_CONFIG  # noqa: E402

VERBOSE = os.environ.get("VERBOSE", "").strip() in ("1", "true", "yes")
MAX_RETRIES = 3
BASE_BACKOFF = 2.0  # seconds; 2, 4, 8 for attempts 1/2/3


# ── Retry-aware HTTP fetch ───────────────────────────────────────────────────
def _http_get_with_retry(url: str, headers: dict, timeout: int = 30) -> tuple[list | dict | None, str]:
    """GET with retry+backoff. Returns (parsed_json, last_error_str)."""
    last_err = ""
    for attempt in range(MAX_RETRIES):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read()), ""
        except urllib.error.HTTPError as e:
            last_err = f"http_{e.code}"
            if e.code in (429, 503):
                # Respect Retry-After header if present
                retry_after = e.headers.get("Retry-After")
                sleep_s = float(retry_after) if retry_after and retry_after.replace(".", "").isdigit() else BASE_BACKOFF * (2 ** attempt)
                if VERBOSE:
                    print(f"      retry-after={sleep_s}s (HTTP {e.code})")
                time.sleep(sleep_s)
            elif 400 <= e.code < 500:
                # Don't retry client errors (4xx other than 429) — they're deterministic
                return None, last_err
            else:
                time.sleep(BASE_BACKOFF * (2 ** attempt))
        except Exception as e:
            last_err = str(e)[:120]
            time.sleep(BASE_BACKOFF * (2 ** attempt))
    return None, last_err


def _http_post_with_retry(url: str, body: bytes, headers: dict, timeout: int = 20) -> tuple[list | dict | None, str]:
    """POST with retry+backoff (Hyperliquid)."""
    last_err = ""
    for attempt in range(MAX_RETRIES):
        try:
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read()), ""
        except urllib.error.HTTPError as e:
            last_err = f"http_{e.code}"
            if e.code in (429, 503):
                retry_after = e.headers.get("Retry-After")
                sleep_s = float(retry_after) if retry_after and retry_after.replace(".", "").isdigit() else BASE_BACKOFF * (2 ** attempt)
                if VERBOSE:
                    print(f"      retry-after={sleep_s}s (HTTP {e.code})")
                time.sleep(sleep_s)
            elif 400 <= e.code < 500:
                return None, last_err
            else:
                time.sleep(BASE_BACKOFF * (2 ** attempt))
        except Exception as e:
            last_err = str(e)[:120]
            time.sleep(BASE_BACKOFF * (2 ** attempt))
    return None, last_err


# ── Source fetchers ──────────────────────────────────────────────────────────
def fetch_cg_pro(coin_id: str, days: int) -> list[dict]:
    """Fetch from CoinGecko Pro. Retry-aware."""
    now = int(time.time())
    frm = now - days * 86400
    url = (f"https://pro-api.coingecko.com/api/v3/coins/{coin_id}/market_chart/range"
           f"?vs_currency=usd&from={frm}&to={now}&interval=daily")
    raw, err = _http_get_with_retry(url, headers={
        "x-cg-pro-api-key": CG_API_KEY,
        "User-Agent": "cc-ohlcv-fetch/1.0 (+cometcloud)",
    })
    if raw is None:
        return [{"_error": err or "empty", "_src": "coingecko", "_coin": coin_id}]
    prices = raw.get("prices", [])
    vols = raw.get("total_volumes", [])
    vol_by_ms = {int(v[0]): float(v[1]) for v in vols if len(v) >= 2}
    out = []
    for row in prices:
        if len(row) < 2:
            continue
        ts_ms, px = int(row[0]), float(row[1])
        d = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).date().isoformat()
        out.append({
            "trade_date": d, "open": px, "high": px, "low": px, "close": px,
            "volume": vol_by_ms.get(ts_ms),
        })
    return out


def fetch_hyperliquid(coin: str, days: int) -> list[dict]:
    """Fetch from Hyperliquid. Retry-aware."""
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - (days + 2) * 86_400_000
    body = json.dumps({
        "type": "candleSnapshot",
        "req": {"coin": coin.upper(), "interval": "1d",
                "startTime": start_ms, "endTime": end_ms},
    }).encode()
    raw, err = _http_post_with_retry(
        "https://api.hyperliquid.xyz/info",
        body=body,
        headers={"Content-Type": "application/json",
                 "User-Agent": "cc-ohlcv-fetch/1.0 (+cometcloud)"},
    )
    if raw is None:
        return [{"_error": err or "empty", "_src": "hyperliquid", "_coin": coin}]
    if not isinstance(raw, list):
        return []
    out = []
    for k in raw:
        t, close = k.get("t"), k.get("c")
        if t is None or close is None:
            continue
        d = datetime.fromtimestamp(t / 1000, tz=timezone.utc).date().isoformat()
        out.append({
            "trade_date": d,
            "open":   float(k.get("o") or close),
            "high":   float(k.get("h") or close),
            "low":    float(k.get("l") or close),
            "close":  float(close),
            "volume": float(k.get("v") or 0),
        })
    return out


def fetch_eodhd(symbol: str, days: int) -> list[dict]:
    """Fetch from EODHD. Retry-aware."""
    if not EODHD_API_KEY:
        return [{"_error": "no_eodhd_key", "_src": "eodhd"}]
    frm = (datetime.now(timezone.utc).date() - timedelta(days=days)).isoformat()
    url = (f"https://eodhd.com/api/eod/{symbol}.US"
           f"?fmt=json&api_token={EODHD_API_KEY}&period=d&from={frm}")
    rows, err = _http_get_with_retry(url, headers={
        "User-Agent": "cc-ohlcv-fetch/1.0 (+cometcloud)",
    })
    if rows is None:
        return [{"_error": err or "empty", "_src": "eodhd", "_sym": symbol}]
    if not isinstance(rows, list):
        return []
    out = []
    for x in rows:
        d, close = x.get("date"), x.get("close")
        if not d or close is None:
            continue
        out.append({
            "trade_date": d,
            "open":   float(x.get("open")  or close),
            "high":   float(x.get("high")  or close),
            "low":    float(x.get("low")   or close),
            "close":  float(close),
            "volume": float(x.get("volume") or 0),
        })
    return out


# ── SQLite buffer ────────────────────────────────────────────────────────────
def init_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS ohlcv_daily (
        symbol TEXT NOT NULL, asset_class TEXT, source TEXT,
        trade_date TEXT NOT NULL,
        open REAL, high REAL, low REAL, close REAL, volume REAL,
        fetched_at TEXT,
        PRIMARY KEY (symbol, trade_date, source)
    )""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_symbol_date ON ohlcv_daily(symbol, trade_date)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_date ON ohlcv_daily(trade_date)")
    conn.commit()
    return conn


def upsert_rows(conn, sym, asset_class, source, rows) -> int:
    if not rows:
        return 0
    if "_error" in rows[0]:
        return 0
    now_iso = datetime.now(timezone.utc).isoformat()
    n = 0
    for r in rows:
        conn.execute(
            "INSERT OR REPLACE INTO ohlcv_daily "
            "(symbol, asset_class, source, trade_date, open, high, low, close, volume, fetched_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (sym, asset_class, source, r["trade_date"],
             r["open"], r["high"], r["low"], r["close"], r.get("volume"),
             now_iso),
        )
        n += 1
    conn.commit()
    return n


def last_buffer_date(conn, symbol: str, source: str | None = None) -> str | None:
    """Return the MAX(trade_date) for a symbol in the buffer, or None."""
    if source:
        row = conn.execute(
            "SELECT MAX(trade_date) FROM ohlcv_daily WHERE symbol=? AND source=?",
            (symbol, source),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT MAX(trade_date) FROM ohlcv_daily WHERE symbol=?",
            (symbol,),
        ).fetchone()
    return row[0] if row and row[0] else None


# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    days = int(os.environ.get("DAYS", "365"))
    only = os.environ.get("ONLY", "").strip()
    force_full = os.environ.get("FORCE_FULL", "").strip() in ("1", "true", "yes")
    conn = init_db()
    print(f"Local DB: {DB_PATH}  size: {DB_PATH.stat().st_size:,} bytes")
    print(f"CG key: {'set' if CG_API_KEY else 'MISSING'}  "
          f"EODHD key: {'set' if EODHD_API_KEY else 'MISSING'}")
    print(f"Days: {days}  Universe: {len(ASSETS_CONFIG)}  "
          f"Mode: {'FORCE FULL' if force_full else 'incremental-aware'}")
    print()
    todo = list(ASSETS_CONFIG.items())
    if only:
        wanted = {s.strip().upper() for s in only.split(",")}
        todo = [(s, c) for s, c in todo if s in wanted]
    print(f"Processing {len(todo)} symbols")
    print()

    started = time.time()
    total_rows = 0
    failed = []
    src_counts = {"coingecko": 0, "hyperliquid": 0, "eodhd": 0}
    slowest = {"sym": None, "elapsed": 0.0}

    for i, (sym, cfg) in enumerate(todo, 1):
        asset_class = cfg.get("class", "Unknown")
        cg_id, yf_sym = cfg.get("coingecko"), cfg.get("yfinance")
        rows_in, source = [], None
        sym_started = time.time()

        # Incremental mode: compute fetch window from buffer's last_date + 1
        existing_last = last_buffer_date(conn, sym)
        if existing_last and not force_full:
            last_dt = date_cls.fromisoformat(existing_last)
            target_start = last_dt + timedelta(days=1)
            today = datetime.now(timezone.utc).date()
            delta_days = (today - target_start).days + 1
            if delta_days < 1:
                # Buffer is already current — skip
                if VERBOSE:
                    print(f"  [{i:2d}] {sym:6s} → up-to-date (last={existing_last})")
                continue
            fetch_days = delta_days
            mode_str = f"+{delta_days}d"
        else:
            fetch_days = days
            mode_str = f"full {days}d"

        if cg_id:
            rows_in = fetch_cg_pro(cg_id, fetch_days)
            source = "coingecko"
            if not rows_in or "_error" in rows_in[0]:
                err_msg = (rows_in[0].get("_error") if rows_in else "empty")
                if VERBOSE:
                    print(f"  [{i:2d}] {sym:6s} CG={cg_id:30s} → {err_msg}, try HL")
                rows_in = fetch_hyperliquid(sym, fetch_days)
                source = "hyperliquid" if rows_in and "_error" not in rows_in[0] else None
        if not rows_in and yf_sym:
            rows_in = fetch_eodhd(yf_sym, fetch_days)
            source = "eodhd" if rows_in and "_error" not in rows_in[0] else None
        if not rows_in or "_error" in (rows_in[0] if rows_in else {}):
            failed.append(sym)
            print(f"  [{i:2d}] {sym:6s} → FAILED ({mode_str}, all sources empty)")
            continue
        # Filter out any rows older than existing_last (safety against overlap)
        if existing_last and not force_full:
            rows_in = [r for r in rows_in if r["trade_date"] > existing_last]
        if not rows_in:
            if VERBOSE:
                print(f"  [{i:2d}] {sym:6s} → no new rows (already in buffer)")
            continue
        n = upsert_rows(conn, sym, asset_class, source, rows_in)
        total_rows += n
        src_counts[source] = src_counts.get(source, 0) + 1
        sym_elapsed = time.time() - sym_started
        if sym_elapsed > slowest["elapsed"]:
            slowest = {"sym": sym, "elapsed": sym_elapsed}
        date_range = f"{rows_in[0]['trade_date']} → {rows_in[-1]['trade_date']}"
        print(f"  [{i:2d}] {sym:6s} src={source:11s} {mode_str:>10s}  rows={n:3d}  "
              f"{sym_elapsed:.2f}s  {date_range}")

    elapsed = time.time() - started
    print()
    print(f"=== Summary ===")
    print(f"Total:    {total_rows:,} rows in {elapsed:.1f}s  "
          f"({total_rows / max(elapsed, 0.1):.1f} rows/s)")
    print(f"Sources:  " + "  ".join(f"{k}={v}" for k, v in src_counts.items() if v))
    print(f"Slowest:  {slowest['sym']} @ {slowest['elapsed']:.2f}s")
    print(f"Failed:   {len(failed)} {failed if failed else ''}")
    print(f"Local DB: {DB_PATH.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()