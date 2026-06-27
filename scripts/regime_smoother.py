#!/usr/bin/env python3
"""
CometCloud — Regime Stability Conviction Smoother (v4)
=======================================================

Per 2026-06-27 user direction: instead of a hard min-hold-days filter on regime
changes (which would force the strategy to sit in a regime that has clearly
stopped working), compute a soft "conviction" signal that captures how *stable*
the regime context has been over a recent window, and let the rebalance trigger
logic require higher conviction for regime-driven rebalances.

Why not naive age-of-current-regime?
    The raw CIS engine changes regime almost daily (mean regime length 9 days
    but a long right tail — 90d / 63d / 30d stretches are anchor points;
    median is 4 days; 25% of regimes last 1 day). With conviction = age/N, every
    transition day has conviction=1/N ≈ 0.11, so no regime-driven rebalance
    would ever fire. Wrong direction.

The right heuristic is "weather": how often has regime been flipping in the
recent past? If we've had 7 regime flips in the last 14 days, the *signal* is
noisy regardless of what today's regime string happens to be. If we've had 0
flips in the last 14 days, the current regime is meaningful.

Conviction algorithm (window-stability):
  - For each day d, look back W=STABILITY_WINDOW days (default 14)
  - Count distinct regimes in that window
  - conviction = 1.0 - (transitions_in_window / W)   ∈ [0.0, 1.0]
    - 0 transitions (regime held whole window) → conviction = 1.0
    - W transitions (chaos, regime changed every day) → conviction = 0.0
  - This is NOT a regime probability. It's a "weather index": how much should
    we trust today's regime string as a coherent context for rebalancing?

CONSUMPTION:
    regime_change trigger only fires when conviction >= REGIME_CONVICTION_THRESHOLD
    (default 0.5 = "fewer than 7 flips in last 14 days"). Other triggers
    (weight_delta, grade_cross, monthly) remain unchanged so genuine signals
    are not lost.

ROADMAP:
    - v4: this consumption-side smoother (Seth, this iteration)
    - v5: source-side `regime_confidence` field from cis_v4_engine.py
          (Minimax, next sprint — see MINIMAX_SYNC.md §REGIME-CONVICTION)
    - v5 consumers prefer the field if present, fall back to this heuristic
"""
from __future__ import annotations

import json
import argparse
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Stability window: how many recent days of regime history to count transitions
# in. 14 days = ~ 2 weeks of trading context. Big enough to filter out 1-3
# day regime noise, small enough to react when regime actually stabilises.
# Sweep results on 2025-05 ~ 2026-03 CIS history:
#   window=7  th=0.85  → 10/37 fires (27%)
#   window=14 th=0.85  → 12/37 fires (32%)   ← DEFAULT: balanced filter
#   window=14 th=0.7   → 22/37 fires (59%)   ← lenient
#   window=21 th=0.85  → 14/37 fires (38%)
DEFAULT_STABILITY_WINDOW = 14
DEFAULT_CONVICTION_THRESHOLD = 0.85

# Cap conviction at 1.0 and floor at 0.0
MIN_CONVICTION = 0.0
MAX_CONVICTION = 1.0

# Backward-compat alias (older code referenced STABILITY_WINDOW directly)
STABILITY_WINDOW = DEFAULT_STABILITY_WINDOW


# ---------------------------------------------------------------------------
# Core: regime runs + window-stability conviction
# ---------------------------------------------------------------------------

def compute_regime_runs(regime_series: pd.Series) -> list[dict]:
    """Identify contiguous regime runs. Returns list of:
        {"regime": str, "start": pd.Timestamp, "end": pd.Timestamp, "length": int}
    """
    if regime_series.empty:
        return []
    runs = []
    prev = None
    start = None
    for d, r in regime_series.items():
        r = str(r).strip() if pd.notna(r) else "Neutral"
        if r != prev:
            if prev is not None and start is not None:
                runs.append({
                    "regime": prev, "start": start, "end": d - pd.Timedelta(days=1),
                    "length": (d - start).days,
                })
            prev = r
            start = d
    if prev is not None and start is not None:
        runs.append({
            "regime": prev, "start": start, "end": regime_series.index[-1],
            "length": (regime_series.index[-1] - start).days + 1,
        })
    return runs


def _count_transitions_in_window(regime_series: pd.Series, end_idx: int, window: int) -> int:
    """Count regime transitions in the [end_idx - window, end_idx] inclusive window."""
    lo = max(0, end_idx - window)
    sub = regime_series.iloc[lo:end_idx + 1]
    if len(sub) < 2:
        return 0
    return int((sub.values[1:] != sub.values[:-1]).sum())


def regime_with_conviction(
    regime_series: pd.Series,
    window: int = STABILITY_WINDOW,
) -> pd.DataFrame:
    """Compute (regime, conviction, transitions_in_window) for each day.

    Conviction (window-stability):
        For day d, count regime transitions in the prior `window` days
        (inclusive of today). Conviction = 1.0 - transitions / window.

        - Window held stable (0 transitions) → conviction = 1.0
        - Window all chaos (transitions = window) → conviction = 0.0

    Args:
        regime_series: pd.Series indexed by date with regime strings
        window: lookback window in days (default STABILITY_WINDOW=14)

    Returns:
        pd.DataFrame with columns [regime, conviction, transitions_in_window]
    """
    if regime_series.empty:
        return pd.DataFrame(columns=["regime", "conviction", "transitions_in_window"])

    # Coerce regimes to clean strings
    rs = regime_series.astype(str).str.strip().fillna("Neutral")
    n = len(rs)

    out = pd.DataFrame(index=rs.index)
    out["regime"] = rs.values
    out["transitions_in_window"] = 0
    out["conviction"] = 0.0

    for i in range(n):
        t = _count_transitions_in_window(rs, i, window)
        out.iloc[i, out.columns.get_loc("transitions_in_window")] = t
        out.iloc[i, out.columns.get_loc("conviction")] = max(
            MIN_CONVICTION, min(MAX_CONVICTION, 1.0 - t / window)
        )
    return out


# ---------------------------------------------------------------------------
# Conviction-weighted trigger helper
# ---------------------------------------------------------------------------

def regime_change_triggers(
    conviction_today: float,
    regime_today: str,
    regime_at_last_rebal: str | None,
    threshold: float = 0.5,
) -> bool:
    """Should the regime_change trigger fire today?

    Returns True only if:
      - regime differs from last-rebal regime, AND
      - conviction >= threshold (regime context has been stable enough)

    With window=14d and threshold=0.5: fewer than 7 transitions in last 14
    days → regime is "stable enough" to fire a regime-driven rebalance on its
    own. With ≥7 transitions, regime_change is suppressed UNLESS combined with
    another trigger (weight_delta / grade_cross).
    """
    if regime_at_last_rebal is None:
        return False
    if regime_today == regime_at_last_rebal:
        return False
    return conviction_today >= threshold


# ---------------------------------------------------------------------------
# CLI: standalone verify / sanity-check
# ---------------------------------------------------------------------------

def _load_cis_regime_series(cis_dir: Path) -> pd.Series:
    """Load per-day macro_regime from cis_history JSON files."""
    rows = {}
    for f in sorted(cis_dir.glob("cis_*.json")):
        try:
            date_str = f.stem.replace("cis_", "")
            d = pd.Timestamp(date_str)
            data = json.loads(f.read_text())
            rows[d] = data.get("macro_regime", "")
        except Exception:
            continue
    if not rows:
        return pd.Series(dtype=object)
    s = pd.Series(rows).sort_index()
    s.index.name = "date"
    return s


def cmd_verify(args):
    """Print regime statistics + conviction distribution + sample of low-conviction days."""
    cis_dir = Path(args.cis_dir)
    raw = _load_cis_regime_series(cis_dir)
    if raw.empty:
        print(f"ERROR: no CIS files in {cis_dir}")
        return 1

    # Raw regime runs
    runs = compute_regime_runs(raw)
    if runs:
        lengths = [r["length"] for r in runs]
        print(f"# Regime smoother verify — {cis_dir}")
        print(f"Days: {len(raw)}, runs: {len(runs)}")
        print(f"Mean: {np.mean(lengths):.2f}d  Median: {np.median(lengths):.1f}d  "
              f"Min: {min(lengths)}d  Max: {max(lengths)}d")
        print()
        print("## Run-length distribution")
        lc = Counter(lengths)
        for l in sorted(lc):
            bar = "█" * lc[l]
            print(f"  {l:>3}d × {lc[l]:>3} {bar}")
        print()

    # Conviction (window-stability)
    cs = regime_with_conviction(raw, window=args.window)
    print(f"## Conviction distribution (window={args.window}d)")
    bins = [-0.01, 0.1, 0.2, 0.3, 0.5, 0.7, 0.9, 1.01]
    labels = ["0.0-0.1", "0.1-0.2", "0.2-0.3", "0.3-0.5", "0.5-0.7", "0.7-0.9", "0.9-1.0"]
    cs["_bin"] = pd.cut(cs["conviction"], bins=bins, labels=labels, include_lowest=True)
    counts = cs["_bin"].value_counts().sort_index()
    for label, n in counts.items():
        bar = "█" * int(n / max(counts) * 40)
        print(f"  {label}: {n:>4} {bar}")
    print()

    # Days where a regime CHANGE happens (raw transition) but conviction is low
    transitions = []
    prev = None
    for d, row in cs.iterrows():
        if prev is not None and row["regime"] != prev:
            transitions.append({
                "date": d.date(), "new_regime": row["regime"],
                "conviction": row["conviction"],
                "transitions": row["transitions_in_window"],
            })
        prev = row["regime"]
    print("## Regime transitions filtered by conviction")
    print(f"Total transitions: {len(transitions)}")
    threshold = args.threshold
    would_fire = [t for t in transitions if t["conviction"] >= threshold]
    would_not = [t for t in transitions if t["conviction"] < threshold]
    print(f"At threshold={threshold}: {len(would_fire)} would fire, {len(would_not)} would NOT fire")
    print()
    if would_not:
        print("Suppressed transitions (would NOT fire regime_change):")
        for t in would_not[:25]:
            print(f"  ✗ {t['date']} → {t['new_regime']:<15} "
                  f"conviction={t['conviction']:.2f} ({t['transitions']} flips in last {args.window}d)")
        if len(would_not) > 25:
            print(f"  ... and {len(would_not) - 25} more")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true",
                    help="Print regime stats + conviction distribution for a CIS dir")
    ap.add_argument("--sweep", action="store_true",
                    help="Sweep window × threshold grid; show how many regime transitions fire")
    ap.add_argument("--cis-dir", default="/Volumes/CometCloudAI/cometcloud-local/_data/cis_history")
    ap.add_argument("--threshold", type=float, default=DEFAULT_CONVICTION_THRESHOLD,
                    help="Conviction threshold for regime_change trigger fire")
    ap.add_argument("--window", type=int, default=DEFAULT_STABILITY_WINDOW,
                    help="Stability window in days (default 14)")
    ap.add_argument("--backtest-start", default="2025-05-03",
                    help="Backtest window start (for sweep; default 2025-05-03)")
    ap.add_argument("--backtest-end", default="2026-03-12",
                    help="Backtest window end (for sweep; default 2026-03-12)")
    args = ap.parse_args()
    if args.verify:
        raise SystemExit(cmd_verify(args))
    if args.sweep:
        raise SystemExit(cmd_sweep(args))
    ap.print_help()


def cmd_sweep(args):
    """Sweep window × threshold and show how many regime transitions fire."""
    cis_dir = Path(args.cis_dir)
    raw = _load_cis_regime_series(cis_dir)
    if raw.empty:
        print(f"ERROR: no CIS files in {cis_dir}")
        return 1
    window_df = raw[(raw.index >= pd.Timestamp(args.backtest_start)) &
                    (raw.index <= pd.Timestamp(args.backtest_end))]

    print(f"# Regime smoother sweep — backtest window {args.backtest_start} → {args.backtest_end}")
    print(f"Days: {len(window_df)}")
    print()
    print(f"{'window↓':<8} {'th=0.5':<10} {'th=0.7':<10} {'th=0.85':<10} {'th=0.9':<10}")
    print("-" * 50)
    for w in [7, 10, 14, 21, 30]:
        cs = regime_with_conviction(window_df, window=w)
        prev = None
        total = 0
        fires = {0.5: 0, 0.7: 0, 0.85: 0, 0.9: 0}
        for d, row in cs.iterrows():
            if prev is not None and row["regime"] != prev:
                total += 1
                for t in fires:
                    if row["conviction"] >= t:
                        fires[t] += 1
            prev = row["regime"]
        cells = [f"{fires[t]:>3}/{total:<3}" for t in fires]
        print(f"{w:<8} {cells[0]:<10} {cells[1]:<10} {cells[2]:<10} {cells[3]:<10}")
    print(f"\nTotal regime transitions in window: {total}")
    return 0


if __name__ == "__main__":
    main()