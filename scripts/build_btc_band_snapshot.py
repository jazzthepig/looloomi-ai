#!/usr/bin/env python3
"""
Build a `{date_str: band}` snapshot of BTC's daily risk-gradient band for the
empirical-grid edge gate (LS v1, Phase B).

The band buckets BTC's trailing-30d return into the same 5 levels the edge-map
grid uses (`1_deep_off` ... `5_deep_on`). Same logic as
`src/api/routers/signals.py::_band_of`. LS v1 loads this JSON in
`_load_cis_history()` and looks up `band[today]` per bar.

Why pre-compute vs compute inline:
    LS v1 is per-instrument (BTC, ETH, SOL strategies run independently); the
    band must be available to all three. A pre-computed snapshot means each
    instance loads the same JSON instead of needing a cross-instrument BTC
    subscription (which Nautilus LS v1 doesn't currently support).

Usage:
    python3 scripts/build_btc_band_snapshot.py
    # writes reports/btc_band_snapshot.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


# Band thresholds — must match src/api/routers/signals.py::_band_of
def _band_of(trail_30d: float) -> str:
    if trail_30d < -15:
        return "1_deep_off"
    if trail_30d < -5:
        return "2_off"
    if trail_30d < 5:
        return "3_neutral"
    if trail_30d < 15:
        return "4_on"
    return "5_deep_on"


DEFAULT_FEATHER = Path(
    "/Volumes/CometCloudAI/freqtrade/user_data/data/binance/futures/BTC_USDT_USDT-4h-futures.feather"
)
DEFAULT_OUT = Path("reports/btc_band_snapshot.json")


def build_snapshot(feather_path: Path = DEFAULT_FEATHER,
                   out_path: Path = DEFAULT_OUT) -> dict:
    df = pd.read_feather(feather_path)
    df["date"] = pd.to_datetime(df["date"], utc=True)
    df = df.set_index("date").sort_index()
    # Resample 4h bars → daily close (last 4h-bar of each UTC day)
    daily = df["close"].resample("1D").last().dropna()
    # 30d trailing return (close[t] / close[t-30] - 1), in %
    trail30_pct = (daily / daily.shift(30) - 1.0) * 100.0
    # First 30 days have no value (NaN); LS v1 has access from 2025-05-03 so
    # we get ≥240 valid daily entries across the IS/OOS windows.
    snapshot = {}
    n_skipped = 0
    for date_idx, value in trail30_pct.items():
        if pd.isna(value):
            n_skipped += 1
            continue
        date_str = date_idx.strftime("%Y-%m-%d")
        snapshot[date_str] = _band_of(float(value))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "source": str(feather_path),
        "method": "BTC daily close resampled from 4h feather, "
                  "30d trailing return %, banded per _band_of() thresholds",
        "thresholds_pct": {
            "1_deep_off": "<-15",
            "2_off":      "-15..-5",
            "3_neutral":  "-5..+5",
            "4_on":       "+5..+15",
            "5_deep_on":  ">+15",
        },
        "n_days": len(snapshot),
        "n_skipped_warmup": n_skipped,
        "first_date": min(snapshot.keys()) if snapshot else None,
        "last_date": max(snapshot.keys()) if snapshot else None,
        "bands": snapshot,
    }
    out_path.write_text(json.dumps(payload, indent=2))
    # Summary
    from collections import Counter
    counts = Counter(snapshot.values())
    summary = ", ".join(f"{b}={n}" for b, n in sorted(counts.items()))
    print(f"wrote {out_path}  ({len(snapshot)} days, warmup-skipped={n_skipped})")
    print(f"  band distribution: {summary}")
    return payload


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--feather", type=Path, default=DEFAULT_FEATHER)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args(argv)
    if not args.feather.exists():
        print(f"ERROR: feather not found: {args.feather}", file=sys.stderr)
        return 1
    build_snapshot(args.feather, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())