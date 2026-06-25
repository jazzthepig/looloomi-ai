#!/usr/bin/env python3
"""
CometCloud CIS — Prepare Per-Day Historical Snapshots for Backtesting
=====================================================================

Pulls cis_scores rows from Supabase and writes per-day JSON files to
CIS_HISTORY_DIR so freqtrade strategies can do proper walk-forward backtests
where each candle uses the CIS state AS OF that candle's date (not today's
snapshot).

This is the S1 prerequisite. Without it, every backtest candle uses today's
CIS — which is a constant-signal pseudo-backtest, not a walk-forward.

Output:
  /Volumes/CometCloudAI/cometcloud-local/_data/cis_history/cis_YYYY-MM-DD.json
  Each file has the same shape as cis_scores_latest.json:
    {"scores": [...], "macro_regime": "...", "timestamp": "...", "source": "..."}

Usage:
  # Use service_role key (bypasses RLS, can read all rows)
  SUPABASE_SERVICE_KEY=... python3 scripts/prepare_cis_history.py
  # Date range
  python3 scripts/prepare_cis_history.py --start 2025-06-01 --end 2026-06-25
  # Dry-run (don't write files)
  python3 scripts/prepare_cis_history.py --dry-run
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import httpx

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://soupjamxlfsmgmmtoeok.supabase.co")
SUPABASE_KEY = os.getenv(
    "SUPABASE_SERVICE_KEY",  # prefer service_role
    os.getenv("SUPABASE_KEY", ""),  # fallback to anon (may be RLS-restricted)
)
OUTPUT_DIR = Path(os.getenv(
    "CIS_HISTORY_DIR",
    "/Volumes/CometCloudAI/cometcloud-local/_data/cis_history/",
))
TABLE = "cis_scores"

PILLAR_MAP = {"pillar_f": "f", "pillar_m": "m", "pillar_o": "r", "pillar_s": "s", "pillar_a": "a"}
GRADE_TO_SIGNAL = {
    "A+": "STRONG OUTPERFORM", "A": "OUTPERFORM", "B+": "OUTPERFORM",
    "B": "NEUTRAL", "C+": "NEUTRAL", "C": "UNDERPERFORM",
    "D": "UNDERPERFORM", "F": "UNDERWEIGHT",
}


def fetch_rows(start_date: str, end_date: str) -> list[dict]:
    """Pull all cis_scores rows in the date window, paginated."""
    if not SUPABASE_KEY:
        print("ERROR: SUPABASE_KEY or SUPABASE_SERVICE_KEY must be set.", file=sys.stderr)
        sys.exit(2)

    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }
    all_rows: list[dict] = []
    offset = 0
    page_size = 1000
    while True:
        params = {
            "select": "symbol,score,grade,signal,pillar_f,pillar_m,pillar_o,pillar_s,pillar_a,macro_regime,recorded_at,asset_class,data_tier",
            "recorded_at": f"gte.{start_date}",
            "order": "recorded_at.asc",
            "limit": page_size,
            "offset": offset,
        }
        if end_date:
            # list value → httpx expands to two `recorded_at=` params
            params["recorded_at"] = [f"gte.{start_date}", f"lte.{end_date}"]

        r = httpx.get(
            f"{SUPABASE_URL}/rest/v1/{TABLE}",
            headers=headers, params=params, timeout=30,
        )
        if r.status_code != 200:
            print(f"Supabase error {r.status_code}: {r.text[:300]}", file=sys.stderr)
            sys.exit(3)
        rows = r.json()
        all_rows.extend(rows)
        if len(rows) < page_size:
            break
        offset += page_size
    return all_rows


def rows_to_per_day(rows: list[dict]) -> dict[str, dict]:
    """Group rows by date. For each (date, symbol), keep the latest snapshot."""
    by_date: dict[str, dict[str, dict]] = {}  # date -> symbol -> row
    by_date_regime: dict[str, str] = {}  # date -> latest macro_regime

    for row in rows:
        ts = row.get("recorded_at")
        if not ts:
            continue
        date_key = ts[:10]  # YYYY-MM-DD
        sym = row.get("symbol")
        if not sym:
            continue
        if date_key not in by_date:
            by_date[date_key] = {}
        # Keep latest per (date, symbol) — since rows are sorted asc, last wins
        by_date[date_key][sym] = row
        if row.get("macro_regime"):
            by_date_regime[date_key] = row["macro_regime"]

    # Convert to cis_scores_latest.json shape per day
    snapshots = {}
    for date_key, sym_rows in by_date.items():
        scores = []
        for sym, row in sym_rows.items():
            pillars = {}
            for k_full, k_short in PILLAR_MAP.items():
                if row.get(k_full) is not None:
                    pillars[k_short] = row[k_full]
            scores.append({
                "asset": sym,
                "symbol": sym,
                "asset_class": row.get("asset_class", ""),
                "cis_score": row.get("score", 0),
                "cis_grade": row.get("grade", "N/A"),
                "grade": row.get("grade", "N/A"),
                "signal": row.get("signal") or GRADE_TO_SIGNAL.get(row.get("grade", ""), "NEUTRAL"),
                "pillars": pillars,
                "pillar_f": row.get("pillar_f"),
                "pillar_m": row.get("pillar_m"),
                "pillar_o": row.get("pillar_o"),
                "pillar_s": row.get("pillar_s"),
                "pillar_a": row.get("pillar_a"),
                "data_tier": row.get("data_tier", 2),
                "macro_regime": row.get("macro_regime"),
            })
        snapshots[date_key] = {
            "scores": scores,
            "macro_regime": by_date_regime.get(date_key, "Unknown"),
            "timestamp": f"{date_key}T00:00:00Z",
            "source": "supabase_cis_scores_history",
        }
    return snapshots


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=(datetime.now(timezone.utc) - timedelta(days=180)).strftime("%Y-%m-%d"))
    ap.add_argument("--end", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    ap.add_argument("--dry-run", action="store_true", help="don't write files, just print summary")
    args = ap.parse_args()

    print(f"Fetching cis_scores rows {args.start} → {args.end}...")
    rows = fetch_rows(args.start, args.end)
    print(f"  fetched {len(rows)} rows")

    snapshots = rows_to_per_day(rows)
    print(f"  grouped into {len(snapshots)} per-day snapshots")
    if snapshots:
        first = min(snapshots.keys())
        last = max(snapshots.keys())
        sample_count = len(next(iter(snapshots.values()))["scores"])
        print(f"  date range: {first} → {last} (avg {sample_count} assets/day)")

    if args.dry_run:
        print("\nDRY RUN — no files written")
        return

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    written = 0
    for date_key, snapshot in snapshots.items():
        out = OUTPUT_DIR / f"cis_{date_key}.json"
        with open(out, "w") as f:
            json.dump(snapshot, f)
        written += 1
    print(f"\nWrote {written} files to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
