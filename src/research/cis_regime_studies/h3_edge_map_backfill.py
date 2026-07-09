#!/usr/bin/env python3
"""
H3 — Edge-map backfill (Seth/Austin, 2026-07-06)
================================================

"Don't use 'only 100 days' as an excuse." (Jazz) — right. The edge map was built only from
the ~100 days of LIVE signal_outcomes. But we have STRUCTURED inputs (CIS history 393d × 40
assets) + 11yr OHLCV. Apply our CURRENT signal logic across that history and every edge-map
cell's n jumps from single digits to thousands — the sparse-data problem solved at the SOURCE,
not just regularized.

What it does:
  1. Load the research panel (cis_history × OHLCV) with 30d forward returns.
  2. Per (asset, date): re-derive signal/grade from the historical cis_score using the CURRENT
     get_grade/get_signal (so the edge map is an honest backtest of TODAY's logic), compute the
     benchmark-relative 30d alpha (asset − BTC/SPY) and the benchmark trailing-30d (the risk band).
  3. Write the rows into Supabase `signal_outcomes` (the same table the live tracker feeds), then
     the existing `refresh_signal_edge_map()` aggregates the full history into a robust edge map.
  4. Print the reconstructed grid so we SEE the n-per-cell jump.

De-dup: only inserts dates strictly BEFORE the earliest live row (so it backfills history without
touching what the live tracker already recorded). Idempotent-ish: re-runs replace the historical
block (delete-then-insert over the backfill window).

Runs where the OHLCV panel lives (Mac / drive). Needs SUPABASE_URL + SUPABASE_KEY env for the write.

Usage:
  python3 -m src.research.cis_regime_studies.h3_edge_map_backfill              # dry-run: print grid, no write
  python3 -m src.research.cis_regime_studies.h3_edge_map_backfill --write      # backfill signal_outcomes
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from src.research.cis_regime_studies.common.data_loader import (
    load_cis_history, load_ohlcv_panel, build_research_panel,
)

logger = logging.getLogger(__name__)

_TRADFI = {"US Equity", "US Bond", "EM Equity", "DM Equity", "Commodity", "TradFi", "FX", "Real Estate"}
BENCH_CRYPTO = os.getenv("BENCH_CRYPTO", "BTC").upper()
BENCH_TRADFI = os.getenv("BENCH_TRADFI", "SPY").upper()
HORIZON = 30


def _band_of(x: float) -> str:
    if x < -15: return "1_deep_off"
    if x < -5:  return "2_off"
    if x < 5:   return "3_neutral"
    if x < 15:  return "4_on"
    return "5_deep_on"


def _resolve_signal(cis_score: float):
    """Current logic on the historical score — honest backtest of TODAY's grade/signal."""
    from src.data.cis.cis_provider import get_grade, get_signal
    g = get_grade(cis_score)
    return get_signal(cis_score, g), g


def build_rows(horizon: int = HORIZON) -> pd.DataFrame:
    cis = load_cis_history()
    ohlcv = load_ohlcv_panel()
    panel = build_research_panel(cis, ohlcv, horizons=(horizon,))   # has fwd_<h>d per asset (a_ret)

    daily = ohlcv.copy()
    daily["timestamp"] = pd.to_datetime(daily["timestamp"], utc=True)
    daily = daily.sort_values(["asset", "timestamp"])
    # benchmark forward + trailing 30d series, per benchmark, by date
    def _series(sym):
        b = daily[daily["asset"] == sym][["timestamp", "close"]].dropna().set_index("timestamp")["close"]
        fwd = b.shift(-horizon) / b - 1.0
        trail = b / b.shift(horizon) - 1.0
        return fwd, trail
    bc_fwd, bc_trail = _series(BENCH_CRYPTO)
    bt_fwd, bt_trail = (_series(BENCH_TRADFI) if (daily["asset"] == BENCH_TRADFI).any() else (None, None))

    rows = []
    for _, r in panel.iterrows():
        a_ret = r.get(f"fwd_{horizon}d")
        if a_ret is None or pd.isna(a_ret):
            continue
        ts = r["timestamp"]
        ac = r.get("asset_class")
        is_tradfi = ac in _TRADFI
        if is_tradfi and bt_fwd is not None:
            bench, b_ret, trail = BENCH_TRADFI, bt_fwd.get(ts), bt_trail.get(ts)
        else:
            bench, b_ret, trail = BENCH_CRYPTO, bc_fwd.get(ts), bc_trail.get(ts)
        if b_ret is None or pd.isna(b_ret) or trail is None or pd.isna(trail):
            continue
        cis_score = r.get("cis_score")
        if cis_score is None or pd.isna(cis_score):
            continue
        signal, grade = _resolve_signal(float(cis_score))
        rows.append({
            "symbol": r["asset"], "asset_class": ac, "signal": signal, "grade": grade,
            "macro_regime": r.get("regime"), "d": ts.date().isoformat(), "bench": bench,
            "a_ret": round(float(a_ret) * 100, 4), "b_ret": round(float(b_ret) * 100, 4),
            "alpha": round((float(a_ret) - float(b_ret)) * 100, 4),
            "pillar_f": r.get("pillar_f"), "pillar_m": r.get("pillar_m"), "pillar_o": r.get("pillar_o"),
            "pillar_s": r.get("pillar_s"), "pillar_a": r.get("pillar_a"),
            "cis_score": round(float(cis_score), 3),
            "bench_trail_30d": round(float(trail) * 100, 4),
        })
    df = pd.DataFrame(rows)
    logger.info(f"reconstructed {len(df)} signal→30d-outcome rows over {df['d'].nunique() if len(df) else 0} days")
    return df


def print_grid(df: pd.DataFrame) -> None:
    if df.empty:
        print("  (no rows)"); return
    df = df.copy()
    df["band"] = df["bench_trail_30d"].map(_band_of)
    g = df.groupby(["signal", "band"]).agg(n=("alpha", "size"),
                                           avg_alpha=("alpha", "mean"),
                                           win=("alpha", lambda s: (s > 0).mean() * 100)).reset_index()
    print(f"\n  Reconstructed edge map ({len(df)} pairs, {df['d'].nunique()} days):")
    print(f"  {'signal':18}{'band':12}{'n':>6}{'avg_alpha':>11}{'win%':>7}")
    for _, r in g.sort_values(["signal", "band"]).iterrows():
        print(f"  {r['signal'][:17]:18}{r['band']:12}{int(r['n']):>6}{r['avg_alpha']:>11.2f}{r['win']:>7.1f}")


def write_outcomes(df: pd.DataFrame) -> int:
    """Insert historical rows into signal_outcomes for dates strictly before the earliest live row."""
    import httpx
    url = os.getenv("SUPABASE_URL") or os.getenv("UPSTASH_REDIS_REST_URL", "")
    key = os.getenv("SUPABASE_KEY") or os.getenv("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        print("  [write] SUPABASE_URL / SUPABASE_KEY not set — skipping write"); return 0
    base = url.rstrip("/") + "/rest/v1/signal_outcomes"
    hdr = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    # earliest live date → only backfill strictly before it (don't touch live rows)
    with httpx.Client(timeout=30) as c:
        r = c.get(base, headers=hdr, params={"select": "d", "order": "d.asc", "limit": "1"})
        live_min = (r.json()[0]["d"] if r.status_code == 200 and r.json() else None)
    hist = df[df["d"] < live_min] if live_min else df
    print(f"  [write] live_min_date={live_min} → backfilling {len(hist)} rows before it")
    written = 0
    recs = hist.replace({np.nan: None}).to_dict("records")
    with httpx.Client(timeout=60) as c:
        for i in range(0, len(recs), 500):
            chunk = recs[i:i + 500]
            resp = c.post(base, headers={**hdr, "Prefer": "return=minimal"}, json=chunk)
            if resp.status_code in (200, 201, 204):
                written += len(chunk)
            else:
                print(f"  [write] chunk {i} failed: {resp.status_code} {resp.text[:200]}"); break
    print(f"  [write] inserted {written} rows. Now run refresh_signal_edge_map() to rebuild the grid.")
    return written


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="write to signal_outcomes (else dry-run)")
    args = ap.parse_args(argv)
    df = build_rows()
    print_grid(df)
    if args.write:
        write_outcomes(df)
    else:
        print("\n  (dry-run — pass --write to backfill signal_outcomes, then refresh_signal_edge_map())")
    return 0


if __name__ == "__main__":
    sys.exit(main())
