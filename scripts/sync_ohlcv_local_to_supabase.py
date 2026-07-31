#!/usr/bin/env python3
"""⚠️  DEPRECATED — DO NOT USE — kept for resilience only.

Per Jazz 2026-07-26 decision, local SQLite is the OFF-ENGINE data source for
research code. We do NOT push to Supabase. See:
  - `src/research/data/ohlcv_local.py` (the active loader)
  - `src/research/data/README.md` (boundary doc)
  - `memory/2026-07-26-local-ohlcv-off-engine.md` (decision memo)

Why this script was written: the user's first hypothesis was that publishable-
key rate limit was the blocker. The actual blocker is GRANT: the publishable
key has no INSERT permission on `ohlcv_daily` (Postgres code 42501, HTTP 401).
Both Mac-side `.env` and Railway env vars only have `SUPABASE_KEY` (publishable),
no `SUPABASE_SERVICE_KEY` — by design (MINIMAX_SYNC §SEC hardening).

What this script does: chunked POST of local SQLite rows → Supabase. Same
`Prefer: resolution=ignore-duplicates` upsert as `src/api/routers/ohlcv.py`.
Will fail every run with HTTP 401 until/unless service_role key is added to
Mac-side `.env`. Don't add it without Jazz authorization.

If you find yourself wanting to run this, the right action is one of:
  1. Use `src/research/data/ohlcv_local.py` for off-engine research
  2. Ask Jazz to authorize adding service_role + new Railway bulk-upsert endpoint
  3. Wait for Mac-side daily loop to write (crypto + AAPL only)

Original docstring preserved below for reference:
---
Sync local OHLCV SQLite buffer → Supabase ohlcv_daily.

Respects publishable-key rate limit (~120 rows / 60s window, then 1-2h reset).
Default cadence: 80 rows/chunk × 65s gap. Sequential chunks (no parallelism —
parallel would multiply request rate and burn the budget faster).

Reads from /tmp/cometcloud_data/ohlcv.db (built by fetch_ohlcv_to_local.py).
Schema (idempotent via Prefer: resolution=ignore-duplicates):
  (symbol, asset_class, source, trade_date, open, high, low, close, volume)

Usage:
  python3 scripts/sync_ohlcv_local_to_supabase.py              # full sync (will 401)
  CHUNK=120 SLEEP=55 python3 scripts/sync_ohlcv_local_to_supabase.py
  ONLY=BTC,ETH python3 scripts/sync_ohlcv_local_to_supabase.py
  PROBE=1 python3 scripts/sync_ohlcv_local_to_supabase.py      # 50-row dry run (will 401)
  SOURCE=coingecko python3 scripts/sync_ohlcv_local_to_supabase.py
"""
from __future__ import annotations

import os
import sys
import json
import time
import sqlite3
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

# Read API keys from Mac-side .env (publishable key only — service_role NOT
# exposed per MINIMAX_SYNC §SEC hardening)
from dotenv import dotenv_values
MAC_ENV = Path("/Volumes/CometCloudAI/cometcloud-local/.env")
_keys = dotenv_values(MAC_ENV) if MAC_ENV.exists() else {}
SUPABASE_URL = _keys.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = _keys.get("SUPABASE_KEY", "")

DB_PATH = Path("/tmp/cometcloud_data/ohlcv.db")

CHUNK = int(os.environ.get("CHUNK", "80"))
SLEEP = int(os.environ.get("SLEEP", "65"))
ONLY = os.environ.get("ONLY", "").strip()
SOURCE_FILTER = os.environ.get("SOURCE", "").strip()
PROBE = os.environ.get("PROBE", "").strip() == "1"


def post_chunk(rows: list[dict]) -> tuple[bool, int, str]:
    """POST a chunk to Supabase. Returns (ok, status_code, body_excerpt)."""
    url = f"{SUPABASE_URL}/rest/v1/ohlcv_daily"
    body = json.dumps(rows).encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "resolution=ignore-duplicates,return=minimal",
            "User-Agent": "cc-ohlcv-sync/1.0 (+cometcloud)",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return True, r.status, ""
    except urllib.error.HTTPError as e:
        body_excerpt = e.read().decode("utf-8", errors="replace")[:200]
        return False, e.code, body_excerpt
    except Exception as e:
        return False, -1, str(e)[:200]


def main():
    print("⚠️  DEPRECATED — this script will 401 on every chunk (no service_role in Mac .env).")
    print("    Per Jazz 2026-07-26: local SQLite is off-engine, NOT pushed to Supabase.")
    print("    Use src/research/data/ohlcv_local.py instead.")
    print()
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("ERROR: SUPABASE_URL or SUPABASE_KEY missing from Mac-side .env")
        sys.exit(1)
    if not DB_PATH.exists():
        print(f"ERROR: local DB not found at {DB_PATH}")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    where, params = [], []
    if ONLY:
        wanted = tuple(s.strip().upper() for s in ONLY.split(",") if s.strip())
        where.append("symbol IN ({})".format(",".join("?" * len(wanted))))
        params.extend(wanted)
    if SOURCE_FILTER:
        where.append("source = ?")
        params.append(SOURCE_FILTER)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    c.execute(f"SELECT COUNT(*) FROM ohlcv_daily {where_sql}", params)
    total = c.fetchone()[0]
    print(f"Local DB rows to sync: {total:,}  chunk={CHUNK}  sleep={SLEEP}s")
    print(f"SUPABASE_URL: {SUPABASE_URL}")
    if PROBE:
        print("PROBE MODE: stopping after first chunk (50 rows)")
    print()

    if total == 0:
        print("Nothing to sync.")
        return

    c.execute(
        f"SELECT symbol, asset_class, source, trade_date, open, high, low, close, volume "
        f"FROM ohlcv_daily {where_sql} ORDER BY symbol, trade_date",
        params,
    )

    started = time.time()
    written = 0
    chunks = 0
    errors = 0
    buf: list[dict] = []
    sym_buf: list[str] = []

    def flush():
        nonlocal buf, sym_buf, written, chunks, errors
        if not buf:
            return
        chunks += 1
        ok, status, body = post_chunk(buf)
        if ok:
            written += len(buf)
            print(f"  [chunk {chunks:3d}] {len(buf):3d} rows  status={status}  total_written={written:,}/{total:,}")
        else:
            errors += 1
            print(f"  [chunk {chunks:3d}] ❌ HTTP {status}  body={body!r}  total_written={written:,}/{total:,}")
        buf = []
        sym_buf = []
        if not PROBE:
            time.sleep(SLEEP)

    for row in c:
        buf.append({
            "symbol":      row["symbol"],
            "asset_class": row["asset_class"],
            "source":      row["source"],
            "trade_date":  row["trade_date"],
            "open":        row["open"],
            "high":        row["high"],
            "low":         row["low"],
            "close":       row["close"],
            "volume":      row["volume"],
        })
        sym_buf.append(row["symbol"])
        if len(buf) >= CHUNK:
            flush()
        if PROBE and chunks >= 1:
            break

    flush()  # remaining

    elapsed = time.time() - started
    print()
    print(f"Done. {written:,}/{total:,} rows written in {chunks} chunks ({errors} errors)  {elapsed:.1f}s")
    print(f"Effective rate: {written / max(elapsed, 0.1):.1f} rows/s")
    if errors:
        print("⚠️  Some chunks failed — re-run is safe (idempotent via ignore-duplicates)")


if __name__ == "__main__":
    main()