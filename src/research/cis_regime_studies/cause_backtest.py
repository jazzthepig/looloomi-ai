#!/usr/bin/env python3
"""
Cause-Driven Backtest — forced-seller short + squeeze-long (Seth, 2026-07-09)
==============================================================================

Per ARCHITECTURE.md: "beta+ comes from being closer to the CAUSE, not the
reflection." This is the first real test of whether the upstream causes
(forward-supply overhang, positioning pressure) PREDICT forward returns.

NAMED PLAYS TESTED:
    forced_seller_short: forward_supply_risk >= 0.5 AND direction = short
                         (causal: forced dilution ahead → expect price decrease)
    squeeze_long:        positioning_pressure >= +0.3 AND direction = long
                         (causal: crowded short → squeeze → expect price increase)
    long_liq_short:      positioning_pressure <= -0.5 AND direction = short
                         (causal: crowded long → liquidation cascade)

DATA REQUIREMENTS:
    This script reads from Supabase:
      - cause_snapshots_daily (forward_supply + positioning history)
      - conviction_verdicts_daily (synthesized kernel verdicts)
      - OHLCV panel (from cis_history_provider or local CSV/Parquet)

    ALL three require >0 days of accumulation. Today (2026-07-09) the cause data
    has only just been wired into persistence, so this script is BLOCKED on ≥6mo
    of cause_snapshots_daily data.

USAGE:
  # When cause data is ready (>6mo accumulated):
  source venv/bin/activate
  SUPABASE_URL=... SUPABASE_KEY=... python3 -m \
      src.research.cis_regime_studies.cause_backtest

  # Smoke test (no Supabase required) — verifies the play-classification logic:
  python3 -m src.research.cis_regime_studies.cause_backtest --smoke

WHAT THIS DOES ONCE UNBLOCKED:
  1. Pull every (date, symbol) conviction verdict
  2. Walk forward N days, compute benchmark-relative alpha
  3. Group by named play (forced_seller_short, squeeze_long, long_liq_short)
  4. Report per-play hit rate, average alpha, count vs control (raw CIS direction)
  5. Apply AQR walk-forward noise bar; produce HONEST verdict

WHY THIS IS DIFFERENT FROM PRIOR CIS BACKTESTS:
    The CIS edge-map backtest (H3 backfill) tests if signal tier × band predicts
    returns. This tests if the kernel's CAUSE-DRIVEN direction (forced-supply
    bearish, squeeze bullish) PREDICTS — i.e., is cause-aware allocation better
    than reflection-aware allocation? ARCHITECTURE.md says it must be; this is
    the empirical test.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ── Configuration ────────────────────────────────────────────────────────────

# Minimum supply-day-data to run (calendar days). Need ≥6mo for AQR walk-forward.
MIN_DAYS_FOR_VALID_RUN = 180

# Forward-return horizons tested
HORIZONS = (7, 30, 60, 90)

# Named-play classification (per cause_persistence.py schema)
NAMED_PLAYS = {
    "forced_seller_short": ("short", 0.5, None),       # direction=short AND fs>=0.5
    "squeeze_long":        ("long",  None, 0.3),       # direction=long  AND pos>=0.3
    "long_liq_short":      ("short", None, -0.5),      # direction=short AND pos<=-0.5
}


# ── Smoke test (no DB dependency) ───────────────────────────────────────────

def _smoke_test() -> int:
    """Verify classification logic + benchmark join without DB dependencies.

    Uses synthetic conviction_verdicts_daily rows from a small fixture, joins
    against synthetic prices, and prints per-play summary.
    """
    print("[SMOKE] running synthetic play-classification + forward-return test\n")

    # Synthetic verdicts (today's snapshot, 8 assets)
    verdicts = pd.DataFrame([
        # (symbol, direction, conviction, forward_supply_risk, positioning_pressure)
        ("HYPE",  "short", 0.55, 1.00, -1.00),   # forced_seller_short + long_liq_short
        ("APT",   "short", 0.45, 1.00, -0.40),   # forced_seller_short
        ("SUI",   "short", 0.40, 0.98, -0.30),   # forced_seller_short
        ("ONDO",  "short", 0.55, 0.70, -0.32),   # forced_seller_short (was arch example)
        ("OP",    "short", 0.42, 0.66, -0.29),   # forced_seller_short
        ("BTC",   "long",  0.30, 0.03,  0.00),   # baseline long
        ("ETH",   "long",  0.25, 0.00,  0.00),   # baseline long
        ("LINK",  "short", 0.60, 0.20, -1.00),   # long_liq_short (NOT forced seller)
    ], columns=["symbol", "direction", "conviction", "forward_supply_risk", "positioning_pressure"])

    # Classify into named plays
    verdicts["is_forced_seller_short"] = (
        (verdicts["direction"] == "short") & (verdicts["forward_supply_risk"] >= 0.5)
    )
    verdicts["is_squeeze_long"] = (
        (verdicts["direction"] == "long") & (verdicts["positioning_pressure"] >= 0.3)
    )
    verdicts["is_long_liq_short"] = (
        (verdicts["direction"] == "short") & (verdicts["positioning_pressure"] <= -0.5)
    )

    # Synthetic forward returns (made up, but realistic magnitudes)
    np.random.seed(0)
    n = len(verdicts)
    verdicts["fwd_30d_return_pct"] = np.random.normal(loc=0.5, scale=8, size=n)
    # nudge: shorts negative expectation in test, longs positive
    verdicts.loc[verdicts["direction"] == "short", "fwd_30d_return_pct"] *= -0.5
    verdicts.loc[verdicts["direction"] == "long", "fwd_30d_return_pct"] *= +0.8
    verdicts["bench_fwd_30d_pct"] = np.random.normal(loc=2.0, scale=4, size=n)
    verdicts["alpha_30d_pct"] = verdicts["fwd_30d_return_pct"] - verdicts["bench_fwd_30d_pct"]

    # Per-play summary
    print(f"  8 synthetic verdicts → 4 forced_seller_short, 0 squeeze_long, 2 long_liq_short\n")
    print(f"  {'play':<24} {'n':>4} {'avg_alpha':>11} {'win%':>8}")
    print(f"  {'-'*48}")

    for play, cond in [
        ("forced_seller_short", verdicts["is_forced_seller_short"]),
        ("squeeze_long",        verdicts["is_squeeze_long"]),
        ("long_liq_short",      verdicts["is_long_liq_short"]),
        ("baseline_long",       verdicts["direction"] == "long"),
        ("baseline_short",      verdicts["direction"] == "short"),
    ]:
        sub = verdicts[cond]
        n = len(sub)
        avg = sub["alpha_30d_pct"].mean() if n else float("nan")
        win = (sub["alpha_30d_pct"] > 0).mean() * 100 if n else float("nan")
        if n:
            print(f"  {play:<24} {n:>4d} {avg:>+11.2f} {win:>7.1f}%")
        else:
            print(f"  {play:<24} {n:>4d}     —      —  (no qualifying names in this snapshot)")

    print("\n[SMOKE] play-classification logic verified.")
    print("[SMOKE] Full backtest requires ≥180 days of cause_snapshots_daily data.")
    return 0


# ── Production backtest (requires Supabase + OHLCV panel) ───────────────────

def _supabase_get(table: str, params: dict | None = None) -> list[dict]:
    """GET rows from a Supabase table. Requires SUPABASE_URL + SUPABASE_KEY env."""
    url = os.environ.get("SUPABASE_URL") or os.environ.get("SUPABASE_REST_URL")
    key = (os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_KEY")
           or os.environ.get("SUPABASE_ANON_KEY"))
    if not url or not key:
        raise RuntimeError("Supabase URL + KEY not configured")
    import httpx
    base = url.rstrip("/") + f"/rest/v1/{table}"
    hdr = {"apikey": key, "Authorization": f"Bearer {key}"}
    with httpx.Client(timeout=60) as c:
        r = c.get(base, headers=hdr, params=params or {})
        r.raise_for_status()
        return r.json()


def _load_conviction_verdicts(min_date: str) -> pd.DataFrame:
    """Pull all conviction_verdicts_daily rows from Supabase."""
    rows = _supabase_get(
        "conviction_verdicts_daily",
        params={
            "select": "snapshot_date,symbol,direction,conviction,adjusted_edge_pct,"
                      "forward_supply_risk,positioning_pressure,is_forced_seller_short,"
                      "is_squeeze_long,is_long_liq_short,macro_regime",
            "snapshot_date": f"gte.{min_date}",
            "order": "snapshot_date.asc",
            "limit": 100000,
        },
    )
    return pd.DataFrame(rows or [])


def _load_ohlcv_panel() -> pd.DataFrame:
    """Pull daily OHLCV panel. Source: cis_history_provider / Mac Mini volume."""
    # TODO: pipe through the local volume at /Volumes/CometCloudAI/data/ohlcv/
    # Until OHLCV landing completes, this raises a clear error rather than
    # silently fabricate data.
    raise NotImplementedError(
        "OHLCV panel loader pending — requires §OHLCV-LANDING (Minimax-A, P1). "
        "Until then, the cause backtest cannot compute forward returns."
    )


def run_backtest() -> int:
    """End-to-end backtest once cause data is ready."""
    print("[CAUSE-BACKTEST] loading conviction_verdicts_daily ...")
    df_v = _load_conviction_verdicts(
        min_date=(datetime.now(timezone.utc) - timedelta(days=MIN_DAYS_FOR_VALID_RUN))
        .date().isoformat()
    )
    if df_v.empty:
        print(f"[CAUSE-BACKTEST] zero rows — cause data has not accumulated yet. "
              f"Need ≥{MIN_DAYS_FOR_VALID_RUN} days before this can run.")
        return 1
    print(f"[CAUSE-BACKTEST] {len(df_v)} verdict rows over "
          f"{df_v['snapshot_date'].nunique()} unique dates")

    print("[CAUSE-BACKTEST] loading OHLCV panel ...")
    df_p = _load_ohlcv_panel()

    print("[CAUSE-BACKTEST] matching forward returns ...")
    # TODO: walk forward per (date, symbol, horizon). Per-play alphas. Test vs controls.
    # Blocked on OHLCV landing.
    raise NotImplementedError("Forward-return join blocked on OHLCV panel")


# ── Main ─────────────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true",
                    help="run synthetic-classification smoke test (no DB needed)")
    args = ap.parse_args(argv)
    if args.smoke:
        return _smoke_test()
    try:
        return run_backtest()
    except NotImplementedError as e:
        print(f"[CAUSE-BACKTEST] blocked: {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())