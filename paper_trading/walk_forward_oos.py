"""Walk-forward anchored OOS harness — S-397 §5b ④ L/S overlay validation.

Per `s397-jev-ls-overlay-redesign-2026-09-21.md`: Jev L/S overlay must be
validated with **anchored walk-forward** (arXiv 2110.14914, Chalkidis & Savani)
before any promote claim. Single-window backtest is the graveyard we've been
in (M-112 REFUTED same-bar leak; M-116 OOS split on Book B).

## Methodology

- **Anchored walk-forward**: anchor = earliest data point, train window expands
- **Train**: 6 months  (panel + Jev state context)
- **Validate**: 2 months (calibrate coverage/score/thesis thresholds)
- **Test**: 6 months    (OUT-OF-SAMPLE — the only number that counts)
- **Folds**: 5          (5 test windows × 6 months = 30 months OOS coverage)
- **Step**: 1 month between fold starts (roll forward)

## Per-fold output

For each arm (A: base / B: base + vanilla L/S / C: base + Jev L/S / C0:
always_abstain):
  - in_sample_sharpe    (train window)
  - oos_sharpe          (test window — the only honest number)
  - oos_calmar
  - oos_max_dd
  - coverage_at_sharpe_pos  (selective classification primary metric)
  - n_trades_oos
  - hit_rate_oos
  - brier_c (only for Jev — has probabilities)
  - fee_adjusted_oos_sharpe at 5/10/15/20 bps

## Aggregate

  - oos_sharpe_mean, std, [5%, 95%] percentile
  - oos/IS ratio per arm (overfit detector: >1 means OOS beats IS, healthy;
    <0.5 means severe overfit)
  - hit_rate across folds (fraction of folds where arm beats base)
  - promote_decision: "promote" | "drop" | "needs_review"

## Output

Per run_id dir:
  walk_forward_oos/
    _meta.json            — config (start, end, arms, folds, anchors)
    folds/
      fold_00.json        — per-arm per-fold metrics
      fold_01.json
      ...
    aggregate.json        — across-fold stats + promote decision
    report.md             — markdown summary
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import statistics
import sys
from pathlib import Path
from typing import Any, Optional

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent if _HERE.name == "paper_trading" else _HERE
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# ── Fold construction ──────────────────────────────────────────────────────


def build_folds(
    start: dt.date,
    end: dt.date,
    *,
    train_months: int = 6,
    val_months: int = 2,
    test_months: int = 6,
    step_months: int = 1,
    n_folds: int = 5,
) -> list[dict[str, str]]:
    """Build anchored walk-forward folds.

    Each fold: anchor = `start`, train expands from anchor.
      - train: [start, train_end]
      - val:   [train_end+1d, val_end]
      - test:  [val_end+1d, test_end]

    Returns list of {train_start, train_end, val_start, val_end, test_start, test_end}.
    All dates ISO YYYY-MM-DD.
    """
    from datetime import timedelta as _td

    def add_months(d: dt.date, months: int) -> dt.date:
        """Add N calendar months (last-day clamp)."""
        m_total = d.month - 1 + months
        y = d.year + m_total // 12
        m = m_total % 12 + 1
        # last-day clamp: try (y, m, d.day); if invalid, use last day of month
        try:
            return dt.date(y, m, d.day)
        except ValueError:
            # last day of month
            if m == 12:
                return dt.date(y, 12, 31)
            next_month = dt.date(y, m + 1, 1)
            return next_month - _td(days=1)

    folds: list[dict[str, str]] = []
    # First test_start = day after val_end (no overlap)
    train_end = add_months(start, train_months)
    val_end = add_months(train_end, val_months)
    test_start = val_end + _td(days=1)
    for i in range(n_folds):
        test_end = add_months(test_start, test_months)
        if test_end > end:
            break  # last fold would exceed window — partial fold is dishonest
        test_end = min(test_end, end)
        train_end = add_months(start, train_months)
        val_end = add_months(train_end, val_months)
        val_start = train_end + _td(days=1)
        folds.append({
            "fold": f"{i:02d}",
            "train_start": start.isoformat(),
            "train_end": train_end.isoformat(),
            "val_start": val_start.isoformat(),
            "val_end": val_end.isoformat(),
            "test_start": test_start.isoformat(),
            "test_end": test_end.isoformat(),
        })
        test_start = add_months(test_start, step_months)
    return folds


# ── Per-fold simulation (skeleton — wire to replay_three_arms or new replay) ─


def simulate_fold(
    fold: dict[str, str],
    arms: list[str],
    *,
    panel_rows: list[dict[str, Any]],
    panel_source: str,
) -> dict[str, Any]:
    """Simulate one fold for each arm. Returns per-arm metrics.

    This is a SKELETON — actual wiring reuses `replay_three_arms` per arm with
    `--start fold.test_start --end fold.test_end`. Per-fold metrics come from
    `compare_three_arms.compute_metrics` (Sharpe / cum / MaxDD / hit_rate /
    coverage@>0).

    Returns: {arm_name: {oos_sharpe, oos_calmar, oos_max_dd, n_trades,
                         coverage_at_sharpe_pos, hit_rate, brier (Jev only)}}
    """
    from paper_trading.spec_runner import build_panel
    from paper_trading.replay_three_arms import (
        SPEC_A17, SPEC_ARMC, replay_one_arm,
    )

    panel = build_panel(panel_rows, source=panel_source)
    test_start = dt.date.fromisoformat(fold["test_start"])
    test_end = dt.date.fromisoformat(fold["test_end"])

    out: dict[str, Any] = {}

    # Arm A: base ① only (no Jev, no factor)
    spec_a = _load_spec(SPEC_A17)
    decisions_a = replay_one_arm(
        spec_a, panel, test_start, test_end,
        cadence_days=spec_a.raw["parameters"]["rebalance_cadence"],
        jev_decision_fn=None,
    )
    out["A_base"] = _metrics_from_decisions(decisions_a)

    # Arm B: base + simple factor gate (S-396 arm C)
    spec_c = _load_spec(SPEC_ARMC)
    decisions_c = replay_one_arm(
        spec_c, panel, test_start, test_end,
        cadence_days=spec_c.raw["parameters"]["rebalance_cadence"],
        jev_decision_fn=None,
    )
    out["B_base_plus_simple_factor"] = _metrics_from_decisions(decisions_c)

    # Arms C / C0 are arm-specific (Jev L/S overlay); they require their own
    # decide function (decide_panel_long_short_jev_overlay). Wiring that is
    # the next step; for now we leave them as None so the harness can be
    # smoke-tested with A+B only.
    for arm in arms:
        if arm.startswith("C_") or arm == "C0":
            out[arm] = None  # wired in S-397 Phase 2

    return out


def _load_spec(path: Path):
    from paper_trading.spec_runner import Spec
    return Spec.load(str(path))


def _metrics_from_decisions(decisions: list[dict[str, Any]]) -> dict[str, Any]:
    """Pull per-arm metrics out of a decision list. Naive MTM (no fill sim)."""
    n_entered = sum(1 for r in decisions if "ENTERED" in str(r.get("verdict", "")))
    n_blocked = sum(1 for r in decisions if "BLOCKED" in str(r.get("verdict", "")))
    n_skipped = sum(1 for r in decisions if "SKIPPED" in str(r.get("verdict", "")))
    return {
        "n_decisions": len(decisions),
        "n_entered": n_entered,
        "n_blocked": n_blocked,
        "n_skipped": n_skipped,
        "frequency": n_entered / len(decisions) if decisions else 0.0,
        # Sharpe / MaxDD / cum computed by compare_three_arms.compute_metrics
        # downstream; this is the per-decision summary.
    }


# ── Aggregate across folds ──────────────────────────────────────────────────


def aggregate_folds(fold_metrics: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate per-fold metrics across folds. Returns per-arm aggregate stats
    + a `promote_decision` per arm.

    promote_decision ∈ {"promote", "drop", "needs_review"}:
      - "promote":   oos_sharpe > 0 AND oos/IS_ratio > 0.5 AND hit_rate > 0.6
      - "drop":      oos_sharpe ≤ 0 OR oos/IS_ratio < 0.2
      - "needs_review": middle ground
    """
    # Group per-arm metrics
    by_arm: dict[str, list[dict[str, Any]]] = {}
    for fm in fold_metrics:
        for arm, metrics in fm.items():
            if metrics is None:
                continue
            by_arm.setdefault(arm, []).append(metrics)

    aggregate: dict[str, Any] = {}
    for arm, metrics_list in by_arm.items():
        freqs = [m.get("frequency", 0.0) for m in metrics_list]
        # Sharpe / MaxDD aggregation comes from compare_three_arms downstream;
        # here we just aggregate what's available per-fold.
        if not metrics_list:
            aggregate[arm] = {"n_folds": 0, "promote_decision": "needs_review"}
            continue
        mean_freq = statistics.mean(freqs) if freqs else 0.0
        aggregate[arm] = {
            "n_folds": len(metrics_list),
            "mean_frequency": round(mean_freq, 4),
            "promote_decision": "needs_review",  # default until Sharpe wired
        }
    return aggregate


# ── Main ────────────────────────────────────────────────────────────────────


def main() -> int:
    p = argparse.ArgumentParser(description="S-397 walk-forward anchored OOS harness")
    p.add_argument("--start", required=True, help="ISO date — earliest data (anchor)")
    p.add_argument("--end", required=True, help="ISO date — latest data")
    p.add_argument("--source", default="binance_hist")
    p.add_argument("--out", required=True, help="output dir")
    p.add_argument("--train-months", type=int, default=6)
    p.add_argument("--val-months", type=int, default=2)
    p.add_argument("--test-months", type=int, default=6)
    p.add_argument("--step-months", type=int, default=1)
    p.add_argument("--n-folds", type=int, default=5)
    p.add_argument("--arms", nargs="+",
                   default=["A_base", "B_base_plus_simple_factor",
                            "C_jev_ls_overlay", "C0_always_abstain"],
                   help="arms to simulate (C_jev_ls_overlay / C0_always_abstain "
                        "require decide_panel_long_short_jev_overlay wiring — "
                        "currently None stub)")
    args = p.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    folds = build_folds(
        dt.date.fromisoformat(args.start), dt.date.fromisoformat(args.end),
        train_months=args.train_months, val_months=args.val_months,
        test_months=args.test_months, step_months=args.step_months,
        n_folds=args.n_folds,
    )

    _meta = {
        "start": args.start, "end": args.end, "source": args.source,
        "train_months": args.train_months, "val_months": args.val_months,
        "test_months": args.test_months, "step_months": args.step_months,
        "n_folds_requested": args.n_folds, "n_folds_built": len(folds),
        "arms": args.arms,
        "ts": dt.datetime.utcnow().isoformat() + "Z",
        "runner": "paper_trading.walk_forward_oos @ 2026-09-21",
        "methodology": "anchored walk-forward (arXiv 2110.14914)",
    }
    (out_dir / "_meta.json").write_text(json.dumps(_meta, indent=2))
    print(f"[walk_forward] {len(folds)} folds built → {out_dir / '_meta.json'}")

    folds_dir = out_dir / "folds"
    folds_dir.mkdir(parents=True, exist_ok=True)
    fold_metrics: list[dict[str, Any]] = []

    for fold in folds:
        print(f"[walk_forward] fold {fold['fold']}: "
              f"test [{fold['test_start']}, {fold['test_end']}]")
        # NOTE: panel fetch + arm simulation wires up in S-397 Phase 2.
        # For now, fold_NN.json records the fold dates + a stub metrics block
        # so the harness is testable end-to-end.
        per_fold = {
            "fold": fold,
            "metrics": {arm: None for arm in args.arms},
            "note": ("panel fetch + arm simulation wires in S-397 Phase 2 — "
                     "harness is testable end-to-end now (build_folds + "
                     "fold JSON + aggregate JSON)."),
        }
        (folds_dir / f"fold_{fold['fold']}.json").write_text(
            json.dumps(per_fold, indent=2),
            encoding="utf-8",
        )
        fold_metrics.append(per_fold["metrics"])

    aggregate = aggregate_folds(fold_metrics)
    (out_dir / "aggregate.json").write_text(json.dumps(aggregate, indent=2))
    print(f"[walk_forward] aggregate → {out_dir / 'aggregate.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
