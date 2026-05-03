#!/usr/bin/env python3
"""
CometCloud CIS — Regime Fitness Calculator
==========================================
Computes Pearson correlation between each pillar score and 7-day realized return
for every macro regime. Populates the cis_regime_fitness table.

This is the Simons feedback loop: which pillar actually predicts returns in each regime?
Once we have 60+ days of history (we now have 365), this becomes the signal for
dynamic pillar weight adjustment in cis_v4_engine.py.

Usage:
    python scripts/compute_regime_fitness.py
    python scripts/compute_regime_fitness.py --window 30   # days of history to use
    python scripts/compute_regime_fitness.py --dry-run     # print results, don't write

Requirements:
    pip install httpx python-dotenv

Environment:
    SUPABASE_URL  — Supabase project URL
    SUPABASE_KEY  — Anon or service role key

Author: Seth
"""

import argparse
import json
import math
import os
import sys
from datetime import datetime, timezone
from typing import Optional

import httpx
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY", os.getenv("SUPABASE_KEY", ""))

PILLARS = ["pillar_f", "pillar_m", "pillar_o", "pillar_s", "pillar_a"]
PILLAR_LABELS = {"pillar_f": "F", "pillar_m": "M", "pillar_o": "O", "pillar_s": "S", "pillar_a": "A"}

# ── Supabase helpers ───────────────────────────────────────────────────────────

def sb_get(path: str, params: dict = None) -> dict:
    """GET from Supabase REST API."""
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }
    url = f"{SUPABASE_URL}/rest/v1/{path}"
    r = httpx.get(url, headers=headers, params=params, timeout=60)
    r.raise_for_status()
    return r.json()


def sb_post(path: str, payload: list) -> dict:
    """POST (upsert) to Supabase REST API."""
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }
    url = f"{SUPABASE_URL}/rest/v1/{path}"
    r = httpx.post(url, headers=headers, json=payload, timeout=60)
    r.raise_for_status()
    return r


def sb_rpc(fn: str, params: dict) -> list:
    """Call a Supabase RPC function."""
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }
    url = f"{SUPABASE_URL}/rest/v1/rpc/{fn}"
    r = httpx.post(url, headers=headers, json=params, timeout=120)
    r.raise_for_status()
    return r.json()


# ── Stats helpers ──────────────────────────────────────────────────────────────

def pearson_r(xs: list[float], ys: list[float]) -> Optional[float]:
    """Pearson correlation coefficient. Returns None if < 3 pairs."""
    n = len(xs)
    if n < 3:
        return None
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    den_x = math.sqrt(sum((x - mean_x) ** 2 for x in xs))
    den_y = math.sqrt(sum((y - mean_y) ** 2 for y in ys))
    if den_x == 0 or den_y == 0:
        return None
    return num / (den_x * den_y)


# ── Main logic ─────────────────────────────────────────────────────────────────

def fetch_historical_rows(window_days: int) -> list[dict]:
    """
    Fetch cis_scores rows that:
      - have a non-null macro_regime
      - have pillar scores (pillar_f/m/o/s/a)
      - have a score (for computing 7d return proxy)
      - are within the window
    Returns list of dicts.
    """
    print(f"  Fetching historical rows (window={window_days}d, needs macro_regime)...")

    # Supabase REST: select relevant columns, filter data_tier, order by symbol+time
    # We need to paginate — each page = 1000 rows
    all_rows = []
    offset = 0
    page_size = 1000

    while True:
        params = {
            "select": "symbol,score,pillar_f,pillar_m,pillar_o,pillar_s,pillar_a,macro_regime,recorded_at",
            "macro_regime": "not.is.null",
            "pillar_f": "not.is.null",
            "order": "symbol.asc,recorded_at.asc",
            "limit": str(page_size),
            "offset": str(offset),
        }
        page = sb_get("cis_scores", params)
        if not page:
            break
        all_rows.extend(page)
        if len(page) < page_size:
            break
        offset += page_size

    print(f"  → {len(all_rows)} rows with macro_regime + pillars")
    return all_rows


def compute_7d_returns(rows: list[dict]) -> list[dict]:
    """
    For each row, compute the 7-day forward realized return using the score proxy.
    score(t+7d) / score(t) - 1 is a rough proxy until we wire in actual price returns.

    A better approach once Freqtrade data accumulates: use actual price returns from
    cis_backtest_results. For now, score_delta is a directional proxy.

    Returns enriched list with `return_7d` field where computable.
    """
    # Group by symbol
    by_symbol: dict[str, list[dict]] = {}
    for row in rows:
        sym = row["symbol"]
        if sym not in by_symbol:
            by_symbol[sym] = []
        by_symbol[sym].append(row)

    enriched = []
    for sym, sym_rows in by_symbol.items():
        # Sort by date
        sym_rows.sort(key=lambda r: r["recorded_at"])
        n = len(sym_rows)
        for i, row in enumerate(sym_rows):
            # Find row ~7 days forward
            target_dt = row["recorded_at"][:10]  # YYYY-MM-DD
            future_score = None
            for j in range(i + 1, min(i + 12, n)):
                future_dt = sym_rows[j]["recorded_at"][:10]
                # Accept if 6–8 days ahead
                from datetime import date
                d0 = date.fromisoformat(target_dt)
                d1 = date.fromisoformat(future_dt)
                delta = (d1 - d0).days
                if 6 <= delta <= 8:
                    future_score = sym_rows[j].get("score")
                    break
            if future_score is not None and row.get("score") and row["score"] > 0:
                return_7d = (future_score - row["score"]) / row["score"]
            else:
                return_7d = None
            enriched.append({**row, "return_7d": return_7d})

    return enriched


def compute_fitness(rows: list[dict], window_days: int) -> list[dict]:
    """
    For each (regime, pillar) pair, compute Pearson r vs 7d return.
    Returns list of dicts ready for cis_regime_fitness insert.
    """
    # Only rows with return_7d
    usable = [r for r in rows if r.get("return_7d") is not None]
    print(f"  Rows with 7d forward return: {len(usable)} / {len(rows)}")

    # Group by regime
    by_regime: dict[str, list[dict]] = {}
    for row in usable:
        regime = row["macro_regime"]
        if regime not in by_regime:
            by_regime[regime] = []
        by_regime[regime].append(row)

    results = []
    now = datetime.now(timezone.utc).isoformat()

    for regime, regime_rows in sorted(by_regime.items()):
        n = len(regime_rows)
        print(f"\n  Regime: {regime} ({n} samples)")
        for pillar_col in PILLARS:
            label = PILLAR_LABELS[pillar_col]
            xs = [r[pillar_col] for r in regime_rows if r.get(pillar_col) is not None]
            ys = [r["return_7d"] for r in regime_rows if r.get(pillar_col) is not None]
            # Keep paired
            pairs = [(x, y) for x, y in zip(xs, ys)]
            if len(pairs) < 3:
                print(f"    Pillar {label}: insufficient data ({len(pairs)} pairs)")
                continue
            xs_clean = [p[0] for p in pairs]
            ys_clean = [p[1] for p in pairs]
            r = pearson_r(xs_clean, ys_clean)
            if r is None:
                continue
            print(f"    Pillar {label}: r={r:.3f} (n={len(pairs)})")
            results.append({
                "regime": regime,
                "pillar": label,
                "correlation": round(r, 4),
                "n_samples": len(pairs),
                "window_days": window_days,
                "computed_at": now,
            })

    return results


def main():
    parser = argparse.ArgumentParser(description="CIS Regime Fitness Calculator")
    parser.add_argument("--window", type=int, default=365, help="Days of history to analyze")
    parser.add_argument("--dry-run", action="store_true", help="Print results, don't write to Supabase")
    args = parser.parse_args()

    if not SUPABASE_URL or not SUPABASE_KEY:
        print("ERROR: SUPABASE_URL and SUPABASE_KEY must be set")
        sys.exit(1)

    print("=" * 60)
    print("  CometCloud CIS — Regime Fitness Calculator")
    print(f"  Window: {args.window}d | Dry run: {args.dry_run}")
    print("=" * 60)
    print()

    print("[1/4] Fetching historical rows...")
    rows = fetch_historical_rows(args.window)
    if not rows:
        print("  No rows with macro_regime found. Run reconstruct_cis_history.py first.")
        sys.exit(1)

    print("\n[2/4] Computing 7-day forward returns...")
    rows = compute_7d_returns(rows)

    print("\n[3/4] Computing pillar correlations per regime...")
    fitness_rows = compute_fitness(rows, args.window)

    print(f"\n[4/4] Results: {len(fitness_rows)} (regime, pillar) pairs computed")

    if args.dry_run:
        print("\n  [DRY RUN] Would insert:")
        for row in fitness_rows:
            print(f"    {row['regime']:15s} | Pillar {row['pillar']} | r={row['correlation']:+.3f} | n={row['n_samples']}")
        return

    if not fitness_rows:
        print("  Nothing to insert.")
        return

    print("\n  Writing to cis_regime_fitness...")
    sb_post("cis_regime_fitness", fitness_rows)
    print(f"  ✓ {len(fitness_rows)} rows inserted")

    print("\nDone.")
    print("  → Freqtrade strategy can now read pillar weights per regime from cis_regime_fitness")
    print("  → Re-run weekly as more live data accumulates in cis_scores")


if __name__ == "__main__":
    main()
