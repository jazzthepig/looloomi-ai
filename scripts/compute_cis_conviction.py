#!/usr/bin/env python3
"""
H3 — Compute per-day regime-stability conviction from a CIS history dir.

Reads every cis_YYYY-MM-DD.json in `src_dir`, computes `regime_with_conviction`
(per `scripts/regime_smoother.py`, window-stability, default 14d) over the
macro_regime series, and writes `{date_str: conviction}` to `dst_path`.

WHY: H3 conviction-weighted gate needs per-day conviction as a floor multiplier.
Strategy reads this via `LSV1_CONVICTION_PATH` env var.

USAGE:
  python3 scripts/compute_cis_conviction.py \
    --src-dir /Volumes/.../_data/cis_history_smoothed/ \
    --window 14 \
    --dst /tmp/cis_conv_modal_recency_w14.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

# Make sibling-importable when run directly
sys.path.insert(0, str(Path(__file__).parent))
from regime_smoother import _load_cis_regime_series, regime_with_conviction  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src-dir", required=True,
                    help="CIS history dir (raw or smoothed)")
    ap.add_argument("--dst", required=True,
                    help="Output JSON path: {date_str: conviction in [0,1]}")
    ap.add_argument("--window", type=int, default=14,
                    help="Stability window in days (default 14)")
    args = ap.parse_args()

    series = _load_cis_regime_series(Path(args.src_dir))
    if series.empty:
        print(f"ERROR: empty series from {args.src_dir}", file=sys.stderr)
        sys.exit(2)

    conv_df = regime_with_conviction(series, window=args.window)
    out = {d.strftime("%Y-%m-%d"): float(round(c, 6))
           for d, c in conv_df["conviction"].items()}

    dst = Path(args.dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(out, indent=2, sort_keys=True))

    print(f"# H3 conviction for {args.src_dir}")
    print(f"# days={len(out)}  window={args.window}")
    print(f"# written: {dst}")
    print()
    # Distribution
    import statistics
    vals = list(out.values())
    print(f"# conviction stats:")
    print(f"#   mean={statistics.mean(vals):.3f}")
    print(f"#   median={statistics.median(vals):.3f}")
    print(f"#   min={min(vals):.3f}  max={max(vals):.3f}")
    bins = [0.0, 0.3, 0.5, 0.7, 0.85, 1.01]
    labels = ["0.00-0.30", "0.30-0.50", "0.50-0.70", "0.70-0.85", "0.85-1.00"]
    counts = {l: 0 for l in labels}
    for v in vals:
        for i, b in enumerate(bins[1:]):
            if v <= b:
                counts[labels[i]] += 1
                break
    print(f"# distribution:")
    for k, n in counts.items():
        bar = "█" * int(n / max(counts.values()) * 30)
        print(f"#   {k}: {n:>4} {bar}")


if __name__ == "__main__":
    main()
