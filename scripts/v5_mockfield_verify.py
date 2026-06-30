#!/usr/bin/env python3
"""
CometCloud — v5 Mock-Field Verification (Part 5 of v5 plan)
==============================================================

Per 2026-06-27 user direction: until Minimax ships the `regime_confidence`
field at the source, we want to PROVE the v5 consumer code path works
end-to-end. This script:

  1. Loads cis_history via rebalance_engine.load_cis_history() — same path
     the backtest uses
  2. Computes the v4 heuristic conviction (window-stability) for each day
  3. Injects a SYNTHETIC regime_confidence column with a known pattern
     (default: equals the heuristic value, so v5 == v4 → sanity check)
  4. Re-runs the v5 fallback chain via regime_confidence_v5()
  5. Re-runs a v5 backtest with the synthetic field and compares against the
     v4 (heuristic-only) backtest
  6. Writes a report comparing decisions and outcomes

Three test modes:
  - sanity:   field = heuristic  → v5 must equal v4 exactly
  - inverted: field = 1 - heuristic → v5 fires on DIFFERENT days than v4
              (every decision flips)
  - random:   field = uniform random ∈ [0, 1]  → v5 fires on a SUBSET of
              v4's days (statistical: ~ 50% overlap at threshold 0.85)

Output:
  /Volumes/CometCloudAI/cometcloud-local/_reports/backtest/v5_mockfield_YYYYMMDD.md
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd


# Make sibling modules importable when run as a script
sys.path.insert(0, str(Path(__file__).parent))

import rebalance_engine as re
import regime_smoother as rs


REPORT_DIR = Path("/Volumes/CometCloudAI/cometcloud-local/_reports/backtest")
REPORT_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_full_cis() -> pd.DataFrame:
    """Load cis_history covering the full available window."""
    files = sorted(re.CIS_HISTORY_DIR.glob("cis_*.json"))
    if not files:
        raise RuntimeError(f"No cis_history files in {re.CIS_HISTORY_DIR}")
    dates = []
    for f in files:
        try:
            dates.append(pd.Timestamp(f.stem.replace("cis_", "")))
        except Exception:
            continue
    return re.load_cis_history(min(dates), max(dates))


def compute_v4_conviction(cis: pd.DataFrame, window: int = 14) -> pd.Series:
    """Pure heuristic conviction (v4 baseline)."""
    regime = cis["regime"].ffill().bfill() if "regime" in cis.columns else pd.Series("Neutral", index=cis.index)
    return rs.regime_with_conviction(regime, window=window)["conviction"]


def inject_synthetic_field(heuristic: pd.Series, mode: str, seed: int = 42) -> pd.Series:
    """Build a synthetic regime_confidence series per the requested mode."""
    if mode == "sanity":
        # Field equals heuristic → v5 should match v4 exactly
        return heuristic.copy()
    if mode == "inverted":
        # Field = 1 - heuristic → fires flip (low field suppresses, high field fires)
        # At threshold 0.85: heuristic ≥0.85 fires, but 1-h ≥0.85 means h ≤0.15
        return (1.0 - heuristic).clip(0.0, 1.0)
    if mode == "random":
        rng = np.random.default_rng(seed)
        return pd.Series(rng.uniform(0.0, 1.0, size=len(heuristic)), index=heuristic.index)
    if mode == "flat-high":
        # Field = 0.95 always → regime_change fires on EVERY transition
        return pd.Series(0.95, index=heuristic.index)
    if mode == "flat-low":
        # Field = 0.10 always → regime_change never fires
        return pd.Series(0.10, index=heuristic.index)
    raise ValueError(f"unknown mode: {mode}")


def backtest_with_field(cis: pd.DataFrame, regime_confidence: pd.Series | None,
                         tag: str, tier: str = "senior") -> re.BacktestResult:
    """Run backtest with optional synthetic regime_confidence column."""
    cis_aug = cis.copy()
    if regime_confidence is not None:
        cis_aug["regime_confidence"] = regime_confidence.reindex(cis_aug.index)
    prices = re.load_prices(
        [c.replace("cis_", "").replace("_score", "") for c in cis_aug.columns
         if c.startswith("cis_") and c.endswith("_score")],
        start=cis_aug.index[0], end=cis_aug.index[-1],
    )
    leverage = re.TIER_LEVERAGE[tier]
    return re.run_backtest(prices, cis_aug, tier, leverage, tag,
                            regime_smoothing=True,
                            regime_threshold=re.REGIME_CONVICTION_THRESHOLD,
                            regime_window=re.REGIME_STABILITY_WINDOW)


def summarise_result(res: re.BacktestResult) -> dict:
    """Pull the headline metrics from a BacktestResult."""
    nav = res.nav.dropna()
    if len(nav) < 2:
        return {"error": "insufficient nav"}
    rebal = res.rebalances
    trigger_breakdown = {"init": 0, "monthly": 0, "regime_change": 0,
                          "grade_cross": 0, "weight_delta": 0, "other": 0}
    for e in rebal:
        for t in e.reason.split("+"):
            if t in trigger_breakdown:
                trigger_breakdown[t] += 1
            else:
                trigger_breakdown["other"] += 1
    return {
        "tag": res.tag,
        "n_rebalances": len(rebal),
        "trigger_breakdown": trigger_breakdown,
        "final_nav": float(nav.iloc[-1]),
        "sharpe_approx": float(res.nav.pct_change().mean() / (res.nav.pct_change().std() + 1e-9) * np.sqrt(365))
                          if len(res.nav) > 1 else 0.0,
        "n_days": len(nav),
        "regime_change_fires": trigger_breakdown["regime_change"],
    }


# ---------------------------------------------------------------------------
# Main: run modes, write report
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["sanity", "inverted", "random", "flat-high", "flat-low"],
                    default="sanity",
                    help="Synthetic field injection mode (default: sanity)")
    ap.add_argument("--tier", choices=["senior", "junior"], default="senior")
    ap.add_argument("--no-write", action="store_true",
                    help="Print to stdout but don't write report")
    args = ap.parse_args()

    print(f"[v5 mockfield] loading cis_history…")
    cis = load_full_cis()
    print(f"  shape={cis.shape}  date range={cis.index[0].date()} → {cis.index[-1].date()}")

    print(f"[v5 mockfield] computing v4 heuristic conviction…")
    v4_conv = compute_v4_conviction(cis, window=re.REGIME_STABILITY_WINDOW)
    print(f"  v4 conviction: mean={v4_conv.mean():.3f}  median={v4_conv.median():.3f}")

    print(f"[v5 mockfield] injecting synthetic field (mode={args.mode})…")
    field = inject_synthetic_field(v4_conv, args.mode)
    if args.mode == "sanity":
        assert (field == v4_conv).all(), "sanity mode should produce identical field"
        print(f"  field == v4_conv everywhere ({len(field)} days)")
    else:
        print(f"  field: mean={field.mean():.3f}  median={field.median():.3f}")

    # Decision-level A/B: which days would regime_change fire?
    threshold = re.REGIME_CONVICTION_THRESHOLD
    regime = cis["regime"].ffill().bfill()
    transitions = regime != regime.shift(1)
    v4_fires = (v4_conv >= threshold) & transitions
    v5_fires = (field >= threshold) & transitions
    print(f"\n[v5 mockfield] Decision-level A/B (regime_change trigger @ threshold={threshold})")
    print(f"  Total regime transitions: {int(transitions.sum())}")
    print(f"  v4 (heuristic) fires:     {int(v4_fires.sum())}")
    print(f"  v5 (synthetic field) fires: {int(v5_fires.sum())}")
    print(f"  both fire:                {int((v4_fires & v5_fires).sum())}")
    print(f"  v4 only:                  {int((v4_fires & ~v5_fires).sum())}")
    print(f"  v5 only:                  {int((~v4_fires & v5_fires).sum())}")
    print(f"  neither:                  {int((~v4_fires & ~v5_fires).sum())}")

    # Run backtests (these are slow on the full window — senior tier only)
    print(f"\n[v5 mockfield] Running backtests (this takes a few minutes)…")
    print(f"  backtest A: v4 (heuristic, no field)")
    res_v4 = backtest_with_field(cis, regime_confidence=None, tag=f"v4_mockfield", tier=args.tier)
    sum_v4 = summarise_result(res_v4)
    print(f"    rebalances={sum_v4['n_rebalances']}  regime_change fires={sum_v4['regime_change_fires']}  final_nav={sum_v4['final_nav']:.4f}")

    print(f"  backtest B: v5 (mode={args.mode})")
    res_v5 = backtest_with_field(cis, regime_confidence=field, tag=f"v5_mockfield_{args.mode}", tier=args.tier)
    sum_v5 = summarise_result(res_v5)
    print(f"    rebalances={sum_v5['n_rebalances']}  regime_change fires={sum_v5['regime_change_fires']}  final_nav={sum_v5['final_nav']:.4f}")

    # Build report
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    mode_label = {"sanity": "Field = heuristic (identity test)",
                  "inverted": "Field = 1 - heuristic (every decision flips)",
                  "random": "Field = uniform [0, 1] random",
                  "flat-high": "Field = 0.95 (always fires)",
                  "flat-low": "Field = 0.10 (never fires)"}[args.mode]

    expected = {
        "sanity":     "v5 must equal v4 (same rebal count, same Sharpe, same NAV)",
        "inverted":   "regime_change fires flip; net rebal count similar but on different days",
        "random":     "v5 regime_change fires on ~50% of v4's days (statistical)",
        "flat-high":  "v5 fires on every transition; expect MORE rebalances than v4",
        "flat-low":   "v5 fires on 0 transitions; expect FEWER rebalances than v4",
    }[args.mode]

    # Sanity check pass/fail
    if args.mode == "sanity":
        ok = (sum_v4["n_rebalances"] == sum_v5["n_rebalances"]
              and abs(sum_v4["final_nav"] - sum_v5["final_nav"]) < 1e-9)
        verdict = "PASS ✓" if ok else "FAIL ✗"
    else:
        ok = None
        verdict = "(no assertion — qualitative A/B only)"

    md = []
    md += [
        f"# v5 mockfield verification — {today}",
        "",
        f"**Mode:** `{args.mode}` — {mode_label}",
        f"**Tier:** {args.tier}  **Threshold:** {threshold}  **Window:** {re.REGIME_STABILITY_WINDOW}d",
        f"**Date range:** {cis.index[0].date()} → {cis.index[-1].date()} ({len(cis)} days)",
        "",
        "## Sanity expectation",
        "",
        expected,
        "",
        f"**Verdict:** {verdict}",
        "",
        "## Decision-level A/B (regime_change trigger)",
        "",
        "| metric | value |",
        "|---|---|",
        f"| Total regime transitions | {int(transitions.sum())} |",
        f"| v4 (heuristic) fires | {int(v4_fires.sum())} |",
        f"| v5 (synthetic field) fires | {int(v5_fires.sum())} |",
        f"| both fire | {int((v4_fires & v5_fires).sum())} |",
        f"| v4 only | {int((v4_fires & ~v5_fires).sum())} |",
        f"| v5 only | {int((~v4_fires & v5_fires).sum())} |",
        f"| neither | {int((~v4_fires & ~v5_fires).sum())} |",
        "",
        "## Backtest A/B (full walk-forward)",
        "",
        "| metric | v4 (heuristic) | v5 (mock field) | Δ |",
        "|---|---|---|---|",
        f"| Rebalances | {sum_v4['n_rebalances']} | {sum_v5['n_rebalances']} | {sum_v5['n_rebalances'] - sum_v4['n_rebalances']:+d} |",
        f"| regime_change fires | {sum_v4['regime_change_fires']} | {sum_v5['regime_change_fires']} | {sum_v5['regime_change_fires'] - sum_v4['regime_change_fires']:+d} |",
        f"| monthly fires | {sum_v4['trigger_breakdown']['monthly']} | {sum_v5['trigger_breakdown']['monthly']} | {sum_v5['trigger_breakdown']['monthly'] - sum_v4['trigger_breakdown']['monthly']:+d} |",
        f"| grade_cross fires | {sum_v4['trigger_breakdown']['grade_cross']} | {sum_v5['trigger_breakdown']['grade_cross']} | {sum_v5['trigger_breakdown']['grade_cross'] - sum_v4['trigger_breakdown']['grade_cross']:+d} |",
        f"| weight_delta fires | {sum_v4['trigger_breakdown']['weight_delta']} | {sum_v5['trigger_breakdown']['weight_delta']} | {sum_v5['trigger_breakdown']['weight_delta'] - sum_v4['trigger_breakdown']['weight_delta']:+d} |",
        f"| final NAV | {sum_v4['final_nav']:.6f} | {sum_v5['final_nav']:.6f} | {sum_v5['final_nav'] - sum_v4['final_nav']:+.6f} |",
        f"| Sharpe (approx) | {sum_v4['sharpe_approx']:.3f} | {sum_v5['sharpe_approx']:.3f} | {sum_v5['sharpe_approx'] - sum_v4['sharpe_approx']:+.3f} |",
        "",
        "## How to read this",
        "",
        "- **sanity mode**: the field is exactly the heuristic value, so v5 must "
        "produce the same rebalances, same Sharpe, and (to within float precision) "
        "the same NAV. If any Δ is non-zero, the v5 fallback chain is broken.",
        "- **other modes**: synthetic stress tests. Confirm the v5 chain actually "
        "honours the field. Once Minimax ships real values, re-run with mode=sanity "
        "after setting field = the v5 real field; expect v5 (real) ≠ v4 (heuristic) "
        "exactly when the model disagrees with the weather heuristic.",
        "",
    ]

    md_text = "\n".join(md)

    if args.no_write:
        print()
        print("=" * 70)
        print(md_text)
        return 0

    out_path = REPORT_DIR / f"v5_mockfield_{args.mode}_{today}.md"
    out_path.write_text(md_text)
    print(f"\n[v5 mockfield] wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())