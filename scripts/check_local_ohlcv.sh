#!/usr/bin/env bash
# One-liner status check for the local OHLCV buffer (no fetch).
#
# Returns:
#   buffer size, symbol count, asset-class breakdown, last trade_date,
#   age in days, freshness verdict (fresh/warning/stale).
#
# Use this BEFORE running research scripts that need full-universe OHLCV.
# If verdict is "warning" or "stale", run: bash scripts/refresh_local_ohlcv.sh
#
# Usage:
#   bash scripts/check_local_ohlcv.sh
#   MAX_AGE_DAYS=3 bash scripts/check_local_ohlcv.sh
set -euo pipefail

MAX_AGE_DAYS="${MAX_AGE_DAYS:-7}"
DB_PATH="/tmp/cometcloud_data/ohlcv.db"

echo "================================================================"
echo "Local OHLCV buffer status"
echo "  path:       ${DB_PATH}"
echo "  max_age:    ${MAX_AGE_DAYS}d (warning > ${MAX_AGE_DAYS}d, stale > 14d)"
echo "================================================================"

if [ ! -f "${DB_PATH}" ]; then
    echo "❌ BUFFER NOT FOUND"
    echo "    Build it:  bash scripts/refresh_local_ohlcv.sh"
    exit 1
fi

python3 - <<PY
from pathlib import Path
import sqlite3, datetime as dt

db = Path("${DB_PATH}")
max_age = int("${MAX_AGE_DAYS}")

print(f"  size:    {db.stat().st_size:,} bytes")
conn = sqlite3.connect(db)
last = conn.execute("SELECT MAX(trade_date) FROM ohlcv_daily").fetchone()[0]
n = conn.execute("SELECT COUNT(DISTINCT symbol) FROM ohlcv_daily").fetchone()[0]
r = conn.execute("SELECT COUNT(*) FROM ohlcv_daily").fetchone()[0]
# asset-class breakdown
classes = conn.execute("""
    SELECT asset_class, COUNT(DISTINCT symbol), SUM(rows)
    FROM (SELECT asset_class, symbol, COUNT(*) AS rows
          FROM ohlcv_daily GROUP BY asset_class, symbol)
    GROUP BY asset_class ORDER BY asset_class
""").fetchall()
conn.close()

print(f"  rows:    {r:,}")
print(f"  symbols: {n}")
print(f"  last:    {last}")
print()
print(f"  asset-class breakdown:")
for cls, nsym, srows in classes:
    print(f"    {cls:14s}  {nsym:2d} symbols  {srows:>5,} rows")

if last:
    last_date = dt.date.fromisoformat(last)
    age = (dt.date.today() - last_date).days
    print()
    print(f"  age:     {age} days")
    if age <= max_age:
        print(f"  verdict: ✅ FRESH (within {max_age}d)")
    elif age <= 14:
        print(f"  verdict: 🟡 WARNING (>{max_age}d, ≤14d)")
        print(f"    action: bash scripts/refresh_local_ohlcv.sh")
    else:
        print(f"  verdict: 🔴 STALE (>14d)")
        print(f"    action: bash scripts/refresh_local_ohlcv.sh")
else:
    print()
    print(f"  verdict: 🔴 EMPTY — no rows in buffer")
PY
echo "================================================================"