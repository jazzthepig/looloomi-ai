#!/usr/bin/env python3
"""
CometCloud — Load regime_confidence from Supabase into cis_history JSONs (v5)
================================================================================

Per 2026-06-27 user direction (Part B of the v5 plan): once Minimax ships the
`regime_confidence` field at the source (cis_v4_engine.py + Supabase schema
bump), this script pulls it and writes ONLY that field into the per-day JSON
files at /Volumes/CometCloudAI/cometcloud-local/_data/cis_history/.

WHY THIS SCRIPT (vs editing Minimax's prepare_cis_history.py):
    - prepare_cis_history.py lives in /Volumes/CometCloudAI/cometcloud-local/
      scripts/ which is Minimax's territory per MINIMAX_SYNC.md §1
    - We do not want to block on Minimax's PR cycle to start getting the
      field into the consumer (rebalance_engine.py + regime_smoother.py)
    - This script is PURELY ADDITIVE: it writes regime_confidence and leaves
      everything else (scores, pillars, etc.) untouched. Running it
      repeatedly is idempotent. Running it alongside Minimax's writer is
      safe — last-write-wins, both write the same field with the same value.

DATA FLOW:
    Supabase cis_scores (column regime_confidence, added by Minimax)
      → this script (Seth, pull)
        → cis_YYYY-MM-DD.json (top-level regime_confidence + per-asset)
          → rebalance_engine.py::load_cis_history() reads field
            → regime_confidence_v5() uses field as primary, heuristic as fallback

OUTPUT:
    /Volumes/CometCloudAI/cometcloud-local/_data/cis_history/cis_YYYY-MM-DD.json
    - Adds `regime_confidence` at top-level (float ∈ [0, 1])
    - Adds `regime_confidence` to every score in `scores[]` array
    - Leaves all other fields untouched
    - Skips dates where the field is null/NaN (don't pollute empty days)

ENV:
    SUPABASE_SERVICE_KEY (preferred) or SUPABASE_KEY must be set.
    SUPABASE_URL defaults to https://soupjamxlfsmgmmtoeok.supabase.co

Usage:
    # Pull all rows from default window (180 days back)
    SUPABASE_SERVICE_KEY=... python3 scripts/load_cis_with_confidence.py

    # Specific window
    SUPABASE_SERVICE_KEY=... python3 scripts/load_cis_with_confidence.py \
        --start 2025-05-01 --end 2026-06-30

    # Dry-run (don't write files, just show what would happen)
    SUPABASE_SERVICE_KEY=... python3 scripts/load_cis_with_confidence.py --dry-run

    # Force overwrite (default: skip days where field is already set)
    SUPABASE_SERVICE_KEY=... python3 scripts/load_cis_with_confidence.py --force
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import httpx


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SUPABASE_URL = os.getenv(
    "SUPABASE_URL",
    "https://soupjamxlfsmgmmtoeok.supabase.co",
)
SUPABASE_KEY = os.getenv(
    "SUPABASE_SERVICE_KEY",
    os.getenv("SUPABASE_KEY", ""),  # fallback to anon (may be RLS-restricted)
)

OUTPUT_DIR = Path(os.getenv(
    "CIS_HISTORY_DIR",
    "/Volumes/CometCloudAI/cometcloud-local/_data/cis_history/",
))

TABLE = "cis_scores"
PAGE_SIZE = 1000
TIMEOUT = 30

# Field name as it appears in Supabase cis_scores row and our JSON files.
# Tied to: MINIMAX_SYNC.md §REGIME-CONVICTION paste-ready spec.
REGIME_CONFIDENCE_FIELD = "regime_confidence"


# ---------------------------------------------------------------------------
# Supabase fetch
# ---------------------------------------------------------------------------

def fetch_rows_with_confidence(start_date: str, end_date: str | None) -> list[dict]:
    """Pull cis_scores rows that have regime_confidence non-null.

    The 'regime_confidence' column may not exist yet on the Supabase table —
    Supabase will return 400 if we SELECT it before Minimax adds the column.
    We try with the field first; if it fails, fall back to SELECT without it
    (returning [] — there is no field to write).
    """
    if not SUPABASE_KEY:
        print("ERROR: SUPABASE_SERVICE_KEY or SUPABASE_KEY must be set.", file=sys.stderr)
        sys.exit(2)

    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }

    # Two SELECT forms: with and without regime_confidence. Try with first;
    # if schema column is missing, Supabase returns 400 with relation/column
    # error. Fall back to no-field form.
    select_with = (
        "symbol,recorded_at,macro_regime,"
        f"{REGIME_CONFIDENCE_FIELD}"
    )
    select_without = "symbol,recorded_at,macro_regime"

    for select_clause in (select_with, select_without):
        all_rows: list[dict] = []
        offset = 0
        while True:
            params: dict = {
                "select": select_clause,
                "recorded_at": f"gte.{start_date}",
                "order": "recorded_at.asc",
                "limit": PAGE_SIZE,
                "offset": offset,
            }
            if end_date:
                params["recorded_at"] = (
                    f"gte.{start_date}&recorded_at=lte.{end_date}"
                )
            try:
                r = httpx.get(
                    f"{SUPABASE_URL}/rest/v1/{TABLE}",
                    headers=headers, params=params, timeout=TIMEOUT,
                )
            except Exception as e:
                print(f"  [WARN] Supabase request failed: {e}", file=sys.stderr)
                return []
            if r.status_code != 200:
                # First attempt (with field) failed — column doesn't exist yet
                if select_clause == select_with:
                    print(f"  [INFO] Supabase rejected regime_confidence column "
                          f"({r.status_code}). Most likely Minimax hasn't added "
                          f"the column yet. Falling back to no-field query.")
                    break
                # Second attempt also failed — real error
                print(f"  [ERROR] Supabase {r.status_code}: {r.text[:300]}", file=sys.stderr)
                return []
            rows = r.json()
            all_rows.extend(rows)
            if len(rows) < PAGE_SIZE:
                break
            offset += PAGE_SIZE
        if select_clause == select_with and all_rows:
            return all_rows
        if select_clause == select_without:
            return all_rows
    return []


def group_confidence_by_date(rows: list[dict]) -> dict[str, float]:
    """Return {YYYY-MM-DD: regime_confidence} — latest push per day wins.

    Rows are sorted ASC by `recorded_at`, so last-encountered per (date, push)
    wins. All assets in a given push share the same regime_confidence (it's a
    function of MacroSnapshot, not per-asset), so we take the latest non-null.
    """
    by_date: dict[str, float] = {}
    for row in rows:
        val = row.get(REGIME_CONFIDENCE_FIELD)
        if val is None:
            continue
        try:
            conf = float(val)
        except (TypeError, ValueError):
            continue
        if conf != conf:  # NaN check
            continue
        ts = row.get("recorded_at")
        if not ts:
            continue
        date_key = ts[:10]
        by_date[date_key] = conf  # last row in ASC = latest push → wins
    return by_date


# ---------------------------------------------------------------------------
# Per-day JSON write (additive only)
# ---------------------------------------------------------------------------

def _ensure_top_confidence(payload: dict, conf: float) -> bool:
    """Set top-level regime_confidence if absent or different (in --force mode).

    Returns True iff the field was actually modified.
    """
    cur = payload.get(REGIME_CONFIDENCE_FIELD)
    if cur is None:
        payload[REGIME_CONFIDENCE_FIELD] = conf
        return True
    try:
        if abs(float(cur) - conf) > 1e-9:
            return False  # different value present, caller decides policy
    except (TypeError, ValueError):
        pass
    return False  # already present with same value


def _ensure_per_asset_confidence(payload: dict, conf: float) -> int:
    """Set regime_confidence on every score in scores[]. Returns count modified."""
    n_mod = 0
    for s in payload.get("scores", []) or []:
        if not isinstance(s, dict):
            continue
        cur = s.get(REGIME_CONFIDENCE_FIELD)
        if cur is None:
            s[REGIME_CONFIDENCE_FIELD] = conf
            n_mod += 1
    return n_mod


def write_confidence(
    json_path: Path,
    confidence: float,
    *,
    force: bool = False,
    create_if_missing: bool = True,
) -> Optional[str]:
    """Write regime_confidence into one per-day JSON.

    Returns:
        "wrote"         — file newly created with field
        "updated"       — existing file got the field added
        "skipped-set"   — already has the field with same value
        "skipped-different" — has a DIFFERENT value, --force NOT set
        "overwrote"     — had different value, --force set, updated
        "no-create"     — file doesn't exist and create_if_missing is False
    """
    if not json_path.exists():
        if not create_if_missing:
            return "no-create"
        # Create minimal payload (just regime_confidence + macro_regime placeholder)
        payload: dict = {
            "scores": [],
            "macro_regime": None,
            "timestamp": f"{json_path.stem.replace('cis_', '')}T00:00:00Z",
            "source": "supabase_cis_scores_history",
            REGIME_CONFIDENCE_FIELD: confidence,
        }
        json_path.write_text(json.dumps(payload, indent=2))
        return "wrote"

    try:
        payload = json.loads(json_path.read_text())
    except Exception as e:
        print(f"  [WARN] Could not parse {json_path.name}: {e}", file=sys.stderr)
        return None

    cur = payload.get(REGIME_CONFIDENCE_FIELD)
    if cur is not None:
        try:
            same = abs(float(cur) - confidence) < 1e-9
        except (TypeError, ValueError):
            same = False
        if same:
            return "skipped-set"
        # Different value
        if not force:
            return "skipped-different"
        payload[REGIME_CONFIDENCE_FIELD] = confidence
        n_assets = _ensure_per_asset_confidence(payload, confidence)
        json_path.write_text(json.dumps(payload, indent=2))
        return "overwrote"

    # Field absent — add it
    payload[REGIME_CONFIDENCE_FIELD] = confidence
    n_assets = _ensure_per_asset_confidence(payload, confidence)
    json_path.write_text(json.dumps(payload, indent=2))
    return "updated"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="Load regime_confidence from Supabase into cis_history JSON files"
    )
    ap.add_argument("--start", default=(datetime.now(timezone.utc) - timedelta(days=365)).strftime("%Y-%m-%d"),
                    help="Pull cis_scores >= YYYY-MM-DD (default: 365d back)")
    ap.add_argument("--end", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                    help="Pull cis_scores <= YYYY-MM-DD (default: today UTC)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Don't write files; show what would happen")
    ap.add_argument("--force", action="store_true",
                    help="Overwrite existing regime_confidence if it differs")
    ap.add_argument("--no-create", action="store_true",
                    help="Don't create new JSON files for days missing them")
    args = ap.parse_args()

    print(f"[load_cis_with_confidence] start={args.start} end={args.end}")
    print(f"[load_cis_with_confidence] Supabase URL: {SUPABASE_URL}")
    print(f"[load_cis_with_confidence] Output dir:  {OUTPUT_DIR}")
    if args.dry_run:
        print(f"[load_cis_with_confidence] DRY-RUN — no writes")
    if args.force:
        print(f"[load_cis_with_confidence] FORCE — overwrite mismatched values")

    rows = fetch_rows_with_confidence(args.start, args.end)
    if not rows:
        print("[load_cis_with_confidence] No rows with regime_confidence found.")
        print("  (If Minimax hasn't shipped the column, this is expected — pre-v5 baseline.)")
        return 0

    by_date = group_confidence_by_date(rows)
    print(f"[load_cis_with_confidence] Got regime_confidence for {len(by_date)} unique dates")

    if args.dry_run:
        # Show plan without writing
        sample = sorted(by_date.items())[:5]
        print("  First 5 dates (would write regime_confidence):")
        for d, c in sample:
            p = OUTPUT_DIR / f"cis_{d}.json"
            tag = "EXISTS" if p.exists() else "MISSING (would create)"
            print(f"    {d}  conf={c:.3f}  {tag}")
        if len(by_date) > 5:
            print(f"    ... and {len(by_date) - 5} more")
        return 0

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    counts = {
        "wrote": 0, "updated": 0, "skipped-set": 0,
        "skipped-different": 0, "overwrote": 0, "no-create": 0,
    }

    for date_key, conf in sorted(by_date.items()):
        # Clamp defensively (Minimax sends ∈ [0,1] but we don't trust the wire)
        conf = max(0.0, min(1.0, conf))
        json_path = OUTPUT_DIR / f"cis_{date_key}.json"
        result = write_confidence(
            json_path, conf, force=args.force,
            create_if_missing=not args.no_create,
        )
        if result is None:
            continue
        counts[result] = counts.get(result, 0) + 1
        verb = {
            "wrote": "+", "updated": "+", "overwrote": "Δ",
            "skipped-set": ".", "skipped-different": "!", "no-create": "?",
        }.get(result, "?")
        print(f"  {verb} {date_key}  conf={conf:.3f}  {result}")

    print()
    print(f"[load_cis_with_confidence] Summary:")
    for k, v in counts.items():
        if v:
            print(f"  {k:>20}: {v}")
    print(f"  {'total dates':>20}: {len(by_date)}")

    if counts["wrote"] > 0 and not args.no_create:
        print()
        print("[NOTE] {counts['wrote']} new files were created with minimal payload.")
        print("       These will be enriched with full CIS data when Minimax's")
        print("       prepare_cis_history.py runs next.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
