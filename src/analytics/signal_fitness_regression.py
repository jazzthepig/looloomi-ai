"""
Signal Fitness Regression Engine — Simons Upgrade P0.3
=======================================================
Measures which pillars predict realized returns per regime.
Runs Pearson correlation between pillar score changes and 7d realized returns
across all trade_results rows grouped by macro regime.

Output: regime_pillar_weights.json mapping regime → {F, M, O, S, A} weights.
These weights feed back into CIS scoring to improve predictiveness over time.

Usage:
    python signal_fitness_regression.py              # run analysis + print results
    python signal_fitness_regression.py --write      # write to Redis
    python signal_fitness_regression.py --dry-run     # show what would run
"""

import os
import json
import logging
import numpy as np
from datetime import datetime, timezone
from typing import Optional

import httpx

_log = logging.getLogger(__name__)

# ── Config ─────────────────────────────────────────────────────────────────────
SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY  = os.getenv("SUPABASE_KEY", os.getenv("SUPABASE_SERVICE_KEY", ""))
UPSTASH_URL   = os.getenv("UPSTASH_REDIS_REST_URL", "").rstrip("/")
UPSTASH_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN", "")

REDIS_KEY_PILLAR_FITNESS = "analytics:pillar_fitness"
_PILLAR_COLS = ["pillar_f_at_entry", "pillar_m_at_entry", "pillar_o_at_entry",
                "pillar_s_at_entry", "pillar_a_at_entry"]
_PILLAR_KEYS = ["F", "M", "O", "S", "A"]


def _fetch_trade_results() -> list[dict]:
    """Fetch all trade_results with realized_return_7d from Supabase."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        _log.warning("[PILLAR_FITNESS] SUPABASE_URL or SUPABASE_KEY not set")
        return []

    url = f"{SUPABASE_URL}/rest/v1/trade_results"
    params = {
        "select": "symbol,macro_regime_at_entry,realized_return_7d,"
                  "pillar_f_at_entry,pillar_m_at_entry,pillar_o_at_entry,"
                  "pillar_s_at_entry,pillar_a_at_entry",
        "realized_return_7d": "not.is.null",
        "limit": "10000",
    }
    headers = {
        "apikey":        SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
    }

    try:
        with httpx.Client(timeout=30) as client:
            resp = client.get(url, params=params, headers=headers)
        if resp.status_code == 200:
            rows = resp.json()
            _log.info(f"[PILLAR_FITNESS] Loaded {len(rows)} trade results with realized_return_7d")
            return rows
        _log.warning(f"[PILLAR_FITNESS] fetch failed: {resp.status_code}")
    except Exception as e:
        _log.warning(f"[PILLAR_FITNESS] fetch exception: {e}")
    return []


def _pearson(x: list[float], y: list[float]) -> float:
    """Pearson correlation coefficient. Returns 0.0 on insufficient data."""
    if len(x) < 5 or len(y) < 5:
        return 0.0
    try:
        return float(np.corrcoef(x, y)[0, 1])
    except Exception:
        return 0.0


def compute_regime_weights(rows: list[dict]) -> dict:
    """
    For each regime, compute Pearson correlation of each pillar's score
    against realized_return_7d. Normalize to weights that sum to 1.0.
    """
    # Group by regime
    by_regime: dict[str, dict] = {}
    for r in rows:
        reg = r.get("macro_regime_at_entry") or "UNKNOWN"
        by_regime.setdefault(reg, []).append(r)

    result = {}

    for regime, regime_rows in by_regime.items():
        correlations = {}
        for col, key in zip(_PILLAR_COLS, _PILLAR_KEYS):
            vals = [r[col] for r in regime_rows if r[col] is not None]
            rets = [r["realized_return_7d"] for r in regime_rows
                    if r[col] is not None and r["realized_return_7d"] is not None]
            correlations[key] = _pearson(vals, rets)

        # Convert to weights: positive correlations → weight, negative → 0
        raw_weights = {k: max(v, 0.0) for k, v in correlations.items()}
        total = sum(raw_weights.values())
        if total > 0:
            weights = {k: round(v / total, 4) for k, v in raw_weights.items()}
        else:
            # Uniform fallback when no positive correlations
            weights = {k: 0.2 for k in _PILLAR_KEYS}

        result[regime] = {
            "correlations": {k: round(v, 4) for k, v in correlations.items()},
            "weights":     weights,
            "sample_size": len(regime_rows),
        }

    return result


def compute_universe_pillar_weights(rows: list[dict]) -> dict:
    """
    Also compute cross-regime weights across all data.
    """
    correlations = {}
    for col, key in zip(_PILLAR_COLS, _PILLAR_KEYS):
        vals = [r[col] for r in rows if r[col] is not None]
        rets = [r["realized_return_7d"] for r in rows
                if r[col] is not None and r["realized_return_7d"] is not None]
        correlations[key] = _pearson(vals, rets)

    raw_weights = {k: max(v, 0.0) for k, v in correlations.items()}
    total = sum(raw_weights.values())
    weights = {k: round(v / total, 4) for k, v in raw_weights.items()} if total > 0 else {}
    return {
        "correlations": {k: round(v, 4) for k, v in correlations.items()},
        "weights":      weights,
        "sample_size":  len(rows),
    }


def build_pillar_fitness_output(rows: list[dict]) -> dict:
    """Build complete pillar fitness output with regime-specific + universe weights."""
    regime_weights = compute_regime_weights(rows)
    universe_weights = compute_universe_pillar_weights(rows)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "universe":     universe_weights,
        "by_regime":    regime_weights,
        "total_trades": len(rows),
        "regimes_seen": list(regime_weights.keys()),
    }


async def write_to_redis(data: dict) -> bool:
    """Write pillar fitness result to Upstash Redis."""
    if not UPSTASH_URL or not UPSTASH_TOKEN:
        return False
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.post(
                f"{UPSTASH_URL}/set/{REDIS_KEY_PILLAR_FITNESS}",
                content=json.dumps(data),
                headers={
                    "Authorization": f"Bearer {UPSTASH_TOKEN}",
                    "Content-Type": "application/json",
                },
                params={"EX": 86400},  # 24h TTL
            )
        return resp.status_code == 200
    except Exception as e:
        _log.warning(f"[PILLAR_FITNESS] Redis write failed: {e}")
        return False


def run_analysis(write_redis: bool = False) -> dict:
    """
    Main entry point: fetch trade results → compute weights → optionally write to Redis.
    Returns the pillar fitness dict.
    """
    rows = _fetch_trade_results()
    if not rows:
        return {"error": "No trade results with realized_return_7d found in Supabase"}

    result = build_pillar_fitness_output(rows)

    if write_redis:
        import asyncio
        ok = asyncio.run(write_to_redis(result))
        result["redis_written"] = ok

    return result


def print_report(data: dict):
    """Pretty-print the pillar fitness report."""
    print("\n" + "=" * 60)
    print("PILLAR FITNESS REPORT — Simons Upgrade")
    print("=" * 60)
    print(f"Generated: {data.get('generated_at', 'unknown')}")
    print(f"Total trades analyzed: {data.get('total_trades', 0)}")

    u = data.get("universe", {})
    uw = u.get("weights", {})
    uc = u.get("correlations", {})
    print(f"\nUniverse weights (n={u.get('sample_size', 0)}):")
    for k in _PILLAR_KEYS:
        print(f"  {k}: weight={uw.get(k, 0):.4f}  corr={uc.get(k, 0):.4f}")

    by_regime = data.get("by_regime", {})
    for regime, rw in sorted(by_regime.items()):
        print(f"\n  [{regime}] (n={rw.get('sample_size', 0)})")
        w = rw.get("weights", {})
        c = rw.get("correlations", {})
        for k in _PILLAR_KEYS:
            print(f"    {k}: weight={w.get(k, 0):.4f}  corr={c.get(k, 0):.4f}")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Pillar fitness regression engine")
    parser.add_argument("--write", action="store_true", help="Write results to Redis")
    parser.add_argument("--dry-run", action="store_true", help="Show what would run")
    args = parser.parse_args()

    if args.dry_run:
        print("[DRY RUN] Would fetch trade_results where realized_return_7d is not null")
        print("         Then compute Pearson(Δpillar_X, realized_return_7d) per regime")
        print("         Output: regime_pillar_weights.json")
    else:
        result = run_analysis(write_redis=args.write)
        print_report(result)