"""
C1 Parity A/B — smoothed-CIS variant.

Per Minimax-C reply (2026-07-19, §C1 PARITY): empirical grid lowers Sharpe by 0.32
on V7 HOLD-OUT by blocking 33 trades that legacy allows AND that turn out to have
mean +0.38% PnL each (60.6% win rate). The R17 fallback hypothesis: smoothed CIS
labels reduce day-to-day tier whiplash → empirical grid decision stabilizes → the
calibrated gate stops killing winners on noise.

This is a thin variant of `c1_parity_ab.py` that swaps the CIS history directory
from `_data/cis_history/` (raw daily tiers) to `_data/cis_history_smoothed/`
(smoothed tiers, lower noise). SAME gate logic, SAME grid, SAME band snapshot.
Only the input CIS tier source differs.

USAGE (Mac-side or sandbox):
    python3 -m src.research.freqtrade.c1_parity_ab_smoothed \\
        --backtest-zip /path/to/backtest-result-XXX.zip \\
        --cis-snapshot /Volumes/.../cis_scores_latest.json \\
        --cis-history-smoothed /Volumes/.../cis_history_smoothed/ \\
        --grid-path reports/edge_gate_grid.json \\
        --band-snapshot reports/btc_band_snapshot.json \\
        --out-dir reports/c1_parity_ab/<date>-smoothed/

The driver does NOT need freqtrade installed — reads standard backtest JSON.

OWNER
  minimax-b (Austin). Sandbox-safe (pure numpy + pandas + json, ~30s for 200 trades).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

import pandas as pd

# Engine-agnostic gate logic (SAME module used by Nautilus LS v1 + freqtrade c1).
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Re-use ALL helpers from c1_parity_ab.py — only the CIS source differs.
from src.research.freqtrade.c1_parity_ab import (
    CISTierLookup,
    GateOutcome,
    REGIME_CIS_FLOOR,
    PER_REGIME_DIRECTION,
    evaluate_trade_with_empirical_grid,
    evaluate_trade_with_legacy_floor,
    legacy_floor_pass,
    load_freqtrade_backtest,
    summarize,
    trades_to_df,
    _format_verdict,
    run_parity_ab as _orig_run_parity_ab,
)


def build_smoothed_cis_lookup(smoothed_dir: Path) -> CISTierLookup:
    """Build CISTierLookup directly from `_data/cis_history_smoothed/cis_YYYY-MM-DD.json`.

    The smoothed directory has the SAME schema as the regular one but the tier
    labels are smoothed (longer-horizon averaging, less day-to-day whiplash).
    Each file is a JSON dict with `scores: [{symbol, cis_score, signal, macro_regime}, ...]`.

    No historical CSV fallback here — smoothed data only covers the 11yr historical
    reconstruction window. Pre-CIS dates fall through to NEUTRAL default.
    """
    idx = CISTierLookup(by_date={})
    files = sorted(smoothed_dir.glob("cis_*.json"))
    if not files:
        raise FileNotFoundError(f"No cis_*.json files in {smoothed_dir}")
    for f in files:
        # filename → date_str
        date_str = f.stem.replace("cis_", "")  # 'cis_2025-05-03' → '2025-05-03'
        if len(date_str) != 10:
            continue
        try:
            data = json.loads(f.read_text())
        except Exception:
            continue
        for s in data.get("scores", []):
            sym = s.get("symbol") or s.get("asset")
            if not sym:
                continue
            score = float(s.get("cis_score", 0) or 0)
            tier = (s.get("signal") or "NEUTRAL").upper()
            regime = (s.get("macro_regime") or "Neutral").upper()
            idx.by_date.setdefault(date_str, {})[sym] = {
                "cis_score": score,
                "signal": tier,
                "macro_regime": regime,
            }
    return idx


def run_parity_ab_smoothed(
    bt_zip: Path,
    cis_snapshot: Path,
    cis_history_smoothed_dir: Path,
    grid_path: Path,
    band_snapshot_path: Path,
    out_dir: Path,
) -> dict:
    """Identical to c1_parity_ab.run_parity_ab but uses smoothed CIS history."""
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"=== C1 Parity A/B — SMOOTHED CIS variant ===")
    print(f"Backtest:                {bt_zip}")
    print(f"CIS snapshot:            {cis_snapshot}")
    print(f"CIS history (smoothed):  {cis_history_smoothed_dir}")
    print(f"Grid:                    {grid_path}")
    print(f"Band snapshot:           {band_snapshot_path}")
    print(f"Output:                  {out_dir}")

    # 1. Load backtest
    bt, strat_name = load_freqtrade_backtest(bt_zip)
    trades_df = trades_to_df(bt, strat_name)
    if trades_df.empty:
        raise ValueError(f"No trades in {bt_zip}")
    print(f"\nLoaded {len(trades_df)} trades from {strat_name}")
    print(f"Window: {trades_df['open_date'].min().date()} → {trades_df['open_date'].max().date()}")

    # 2. Load grid + band snapshot
    grid = json.loads(grid_path.read_text()).get("grid", {})
    bands = json.loads(band_snapshot_path.read_text()).get("bands", {})

    # 3. Build SMOOTHED CIS lookup (the only difference from c1_parity_ab.run_parity_ab)
    cis_lookup = build_smoothed_cis_lookup(cis_history_smoothed_dir)
    print(f"CIS smoothed lookup: {len(cis_lookup.by_date)} daily snapshots indexed")

    # Coverage diagnostic: how many trades land on a date that has smoothed CIS data?
    coverage_hits = 0
    coverage_total = len(trades_df)
    for _, t in trades_df.iterrows():
        d = t["open_date"].strftime("%Y-%m-%d")
        if cis_lookup.look(d, t["base_symbol"]) is not None:
            coverage_hits += 1
    coverage_pct = coverage_hits / coverage_total if coverage_total else 0
    print(f"Smoothed CIS coverage: {coverage_hits}/{coverage_total} trades ({coverage_pct:.1%})")
    if coverage_pct < 0.5:
        print(f"  ⚠️  <50% coverage: many trades will default to NEUTRAL × band → empirical grid becomes near no-op.")

    # 4. Evaluate each trade under both gates
    rows = []
    for _, trade in trades_df.iterrows():
        legacy = evaluate_trade_with_legacy_floor(trade, cis_lookup)
        empirical = evaluate_trade_with_empirical_grid(trade, grid, bands, cis_lookup)
        rows.append({
            "pair": trade["pair"],
            "open_date": trade["open_date"].strftime("%Y-%m-%d"),
            "is_short": trade["is_short"],
            "enter_tag": trade["enter_tag"],
            "profit_ratio": trade["profit_ratio"],
            "profit_abs": trade["profit_abs"],
            "legacy_blocked": legacy.blocked,
            "legacy_reason": legacy.decision.reason,
            "empirical_blocked": empirical.blocked,
            "empirical_expected_edge_pct": empirical.decision.expected_edge_pct,
            "empirical_conviction": empirical.decision.conviction,
            "empirical_reason": empirical.decision.reason,
        })
    per_trade_df = pd.DataFrame(rows)

    # 5. Verdict
    n_total = len(per_trade_df)
    n_legacy_block = int(per_trade_df["legacy_blocked"].sum())
    n_emp_block = int(per_trade_df["empirical_blocked"].sum())
    n_both_pass = int((~per_trade_df["legacy_blocked"] & ~per_trade_df["empirical_blocked"]).sum())
    n_legacy_only = int((per_trade_df["legacy_blocked"] & ~per_trade_df["empirical_blocked"]).sum())
    n_empirical_only = int((~per_trade_df["legacy_blocked"] & per_trade_df["empirical_blocked"]).sum())
    n_both_block = int((per_trade_df["legacy_blocked"] & per_trade_df["empirical_blocked"]).sum())

    # 6. Per-gate PnL summary
    legacy_summary = summarize(per_trade_df, "legacy")
    empirical_summary = summarize(per_trade_df, "empirical")

    # 7. Persist
    per_trade_path = out_dir / "per_trade.csv"
    per_trade_df.to_csv(per_trade_path, index=False, float_format="%.6f")

    summary_df = pd.DataFrame([
        {"gate": "LEGACY (REGIME_CIS_FLOOR)", **legacy_summary},
        {"gate": "EMPIRICAL_GRID (smoothed CIS)", **empirical_summary},
    ])
    summary_path = out_dir / "summary.csv"
    summary_df.to_csv(summary_path, index=False, float_format="%.4f")

    verdict_md = out_dir / "verdict.md"
    verdict_md.write_text(_format_verdict(
        strat_name, n_total,
        n_legacy_block, n_emp_block,
        n_both_pass, n_legacy_only, n_empirical_only, n_both_block,
        legacy_summary, empirical_summary,
    ) + f"""

## Smoothed-CIS variant diagnostic

- **CIS coverage on backtest window:** {coverage_hits}/{coverage_total} trades ({coverage_pct:.1%})
- **CIS source:** `{cis_history_smoothed_dir}` (smoothed labels)
- **Compare to raw-CIS run:** `reports/c1_parity_ab/2026-07-18-v7-holdout/verdict.md`
  (raw CIS: Δ Sharpe = -0.32, empirical blocks 33 winners with mean +0.38% each)

## Mechanism (R17 fallback hypothesis)

Raw daily CIS tiers flip OUTPERFORM → NEUTRAL → OUTPERFORM across consecutive
days for noise reasons (CIS recalc, regime reclassification, data refresh). The
empirical grid treats each tier as a discrete state, so day-to-day whiplash
produces churn in the gate decision: a trade that would have been allowed on
day N is blocked on day N+1, even though the underlying fundamental didn't
change. Smoothed CIS labels dampen this whiplash; the gate stabilizes.
""")

    print(f"\nPer-trade:    {per_trade_path}  ({n_total} rows)")
    print(f"Summary:      {summary_path}")
    print(f"Verdict:      {verdict_md}")

    # 8. Console verdict
    print(f"\n{'─'*72}")
    print(f"  C1 PARITY A/B VERDICT (SMOOTHED CIS) — {strat_name}")
    print(f"{'─'*72}")
    print(f"  Total trades:        {n_total}")
    print(f"  Both pass:           {n_both_pass}")
    print(f"  Both block:          {n_both_block}")
    print(f"  Legacy-only pass:    {n_legacy_only}  (empirical blocks; gate is STRICTER)")
    print(f"  Empirical-only pass: {n_empirical_only}  (legacy blocks; gate is LOOSER)")
    print(f"")
    print(f"  Legacy (CIS floor):        n_pass={legacy_summary['n_passed']} "
          f"Σ pnl=${legacy_summary['total_pnl']:+.2f} "
          f"Sharpe={legacy_summary['sharpe']:+.2f} "
          f"max_loss={legacy_summary['max_loss']*100:+.2f}%")
    print(f"  Empirical (smoothed CIS):  n_pass={empirical_summary['n_passed']} "
          f"Σ pnl=${empirical_summary['total_pnl']:+.2f} "
          f"Sharpe={empirical_summary['sharpe']:+.2f} "
          f"max_loss={empirical_summary['max_loss']*100:+.2f}%")
    delta_sharpe = empirical_summary['sharpe'] - legacy_summary['sharpe']
    print(f"  Δ Sharpe (empirical − legacy): {delta_sharpe:+.2f}")
    print(f"{'─'*72}")

    return {
        "n_total": n_total,
        "both_pass": n_both_pass,
        "both_block": n_both_block,
        "legacy_only_pass": n_legacy_only,
        "empirical_only_pass": n_empirical_only,
        "legacy_summary": legacy_summary,
        "empirical_summary": empirical_summary,
        "delta_sharpe": delta_sharpe,
        "coverage_hits": coverage_hits,
        "coverage_total": coverage_total,
        "coverage_pct": coverage_pct,
        "summary_csv": str(summary_path),
        "per_trade_csv": str(per_trade_path),
        "verdict_md": str(verdict_md),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="C1 Parity A/B with smoothed CIS history.")
    ap.add_argument("--backtest-zip", type=Path, required=True,
                    help="freqtrade backtest-result ZIP")
    ap.add_argument("--cis-snapshot", type=Path,
                    default=Path("/Volumes/CometCloudAI/cometcloud-local/_data/cis_scores_latest.json"),
                    help="Latest CIS scores JSON (live engine output)")
    ap.add_argument("--cis-history-smoothed", type=Path,
                    default=Path("/Volumes/CometCloudAI/cometcloud-local/_data/cis_history_smoothed/"),
                    help="Smoothed CIS history directory")
    ap.add_argument("--grid-path", type=Path,
                    default=Path("reports/edge_gate_grid.json"),
                    help="Shrunk edge-map grid JSON")
    ap.add_argument("--band-snapshot", type=Path,
                    default=Path("reports/btc_band_snapshot.json"),
                    help="BTC band snapshot JSON (date → band)")
    ap.add_argument("--out-dir", type=Path, required=True,
                    help="Output directory")
    args = ap.parse_args(argv)

    run_parity_ab_smoothed(
        bt_zip=args.backtest_zip,
        cis_snapshot=args.cis_snapshot,
        cis_history_smoothed_dir=args.cis_history_smoothed,
        grid_path=args.grid_path,
        band_snapshot_path=args.band_snapshot,
        out_dir=args.out_dir,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
