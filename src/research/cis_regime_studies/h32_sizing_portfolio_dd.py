#!/usr/bin/env python3
"""
H3.2 sizing PORTFOLIO-LEVEL DRAW-DOWN (Nautilus LS v1, 2026-07-10)
=================================================================

Per H3.2 floor/cap sweep (H32_SIZING_FLOORCAP_SWEEP_2026-07-10.md): the rough
per-trade stat showed $[0.5, 1.75] as Pareto-balanced, but the rough MaxDD in the
runner was $0.00 because it summed per-position not the equity curve. The cap=1.75
+17% peak-exposure bump needs a proper equity-curve MaxDD to be defensible.

This script:
    1. Loads the 24 sweep runs from reports/h32_sizing_sweep/2026-07-10/runs/
    2. Aggregates per-trade PnL across instruments into ONE equity curve per run
       (sorted by ts_closed)
    3. Computes portfolio-level MaxDD (USD and % of running peak), total return,
       CAGR-equivalent, per-day PnL Sharpe
    4. Compares all 6 variants head-to-head per (dir, window)
    5. Identifies the PARETO-BALANCED variant at the PORTFOLIO level (which may
       differ from the per-trade story)

Usage:
    source venv/bin/activate
    python3 -m src.research.cis_regime_studies.h32_sizing_portfolio_dd
"""
from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Tuple

logger = logging.getLogger(__name__)


# ── Config ────────────────────────────────────────────────────────────────────
RUNS_ROOT = Path("/Users/sbb/Projects/looloomi-ai/reports/h32_sizing_sweep/2026-07-10/runs")
BASELINE_ROOT = Path("/Users/sbb/Projects/looloomi-ai/reports/h32_sizing/2026-07-09/runs")

DIRS = ["raw", "modal_recency"]
WINDOWS = ["is", "oos"]
VARIANTS = ["def", "t1.25", "t1.75", "t2.0", "d0.25", "cvx"]
STARTING_CAPITAL = 10_000.0  # for % DD (rough — same across all runs)

OUT_ROOT = Path("/Users/sbb/Projects/looloomi-ai/reports/h32_sizing_portfolio_dd/2026-07-10")


# ── Equity-curve helpers ─────────────────────────────────────────────────────

def load_positions(run_dir: Path) -> List[dict]:
    """Load all positions from per_instrument.json, sorted by ts_closed."""
    pi_path = next(run_dir.glob("per_instrument.json"), None)
    if pi_path is None:
        return []
    per_inst = json.loads(pi_path.read_text())
    positions: List[dict] = []
    for inst in per_inst:
        for pos in inst.get("positions", []):
            positions.append(pos)
    positions.sort(key=lambda p: p.get("ts_closed", 0))
    return positions


def build_equity_curve(positions: List[dict], starting_capital: float = STARTING_CAPITAL) -> List[Tuple[int, float, float]]:
    """Build (ts_closed_ns, cum_pnl_usd, equity_usd) triples.

    Starting capital is added once. cum_pnl starts at 0 and equity = starting_cap + cum_pnl.
    """
    out: List[Tuple[int, float, float]] = []
    cum = 0.0
    for p in positions:
        pnl = float(p.get("realized_pnl") or 0.0)
        cum += pnl
        out.append((p.get("ts_closed", 0), cum, starting_capital + cum))
    return out


def max_drawdown(equity: List[Tuple[int, float, float]]) -> Tuple[float, float]:
    """Max drawdown in USD and as % of running peak.

    Returns (max_dd_usd, max_dd_pct). pct = dd / peak (negative).
    """
    if not equity:
        return 0.0, 0.0
    min_dd_usd = 0.0
    min_dd_pct = 0.0
    peak = equity[0][2]
    for _ts, _cum, eq in equity:
        if eq > peak:
            peak = eq
        dd_usd = eq - peak  # always <= 0
        dd_pct = dd_usd / peak if peak > 0 else 0.0
        if dd_usd < min_dd_usd:
            min_dd_usd = dd_usd
        if dd_pct < min_dd_pct:
            min_dd_pct = dd_pct
    return min_dd_usd, min_dd_pct


def per_day_pnl_sharpe(positions: List[dict]) -> float:
    """Aggregate PnL by trading-day (UTC), compute mean/std → Sharpe-style ratio.

    Uses the roughest possible Sharpe (numpy's std with ddof=1). NOT annualized.
    """
    if not positions:
        return 0.0
    from collections import defaultdict
    by_day: dict = defaultdict(float)
    for p in positions:
        ts_ns = p.get("ts_closed", 0)
        day = datetime.utcfromtimestamp(ts_ns / 1e9).strftime("%Y-%m-%d")
        by_day[day] += float(p.get("realized_pnl") or 0.0)
    pnls = list(by_day.values())
    if len(pnls) < 2:
        return 0.0
    mean = sum(pnls) / len(pnls)
    var = sum((x - mean) ** 2 for x in pnls) / (len(pnls) - 1)
    sd = var ** 0.5
    return mean / sd if sd > 0 else 0.0


def date_range_days(positions: List[dict]) -> float:
    """Approximate number of days from first ts_opened to last ts_closed."""
    if not positions:
        return 0.0
    ts_opens = [p.get("ts_opened", 0) for p in positions if p.get("ts_opened")]
    ts_closes = [p.get("ts_closed", 0) for p in positions if p.get("ts_closed")]
    if not ts_opens or not ts_closes:
        return 0.0
    span_ns = max(ts_closes) - min(ts_opens)
    return span_ns / 1e9 / 86400.0


# ── Run-level aggregation ────────────────────────────────────────────────────

def summarize_run(run_dir: Path, label: str) -> dict:
    """Compute portfolio-level metrics for a single run."""
    positions = load_positions(run_dir)
    equity = build_equity_curve(positions, STARTING_CAPITAL)
    dd_usd, dd_pct = max_drawdown(equity)
    days = date_range_days(positions)
    total_pnl = equity[-1][1] if equity else 0.0
    final_eq = equity[-1][2] if equity else STARTING_CAPITAL
    peak_eq = max((eq for _, _, eq in equity), default=STARTING_CAPITAL)
    sharpe = per_day_pnl_sharpe(positions)
    n_trades = len(positions)
    return {
        "label": label,
        "n_trades": n_trades,
        "total_pnl_usd": round(total_pnl, 2),
        "final_equity_usd": round(final_eq, 2),
        "peak_equity_usd": round(peak_eq, 2),
        "max_dd_usd": round(dd_usd, 2),
        "max_dd_pct": round(dd_pct * 100, 3),  # %
        "per_day_sharpe": round(sharpe, 4),
        "span_days": round(days, 1),
        "out_dir": str(run_dir),
    }


# ── Driver ────────────────────────────────────────────────────────────────────

def resolve_run_dir(root: Path, dir_label: str, variant: str, win_label: str) -> Path | None:
    """Resolve the latest run_X dir under root/<dir>/<variant or baseline>/<win>/."""
    if variant == "baseline":
        cand = root / dir_label / "baseline" / win_label
    else:
        cand = root / dir_label / variant / win_label
    if not cand.exists():
        return None
    runs = sorted(cand.glob("run_*"))
    if not runs:
        return None
    return runs[-1]


def main() -> None:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    rows: List[dict] = []

    for dir_label in DIRS:
        for win_label in WINDOWS:
            # Baseline re-use from original H3.2 A/B
            base_run = resolve_run_dir(BASELINE_ROOT, dir_label, "baseline", win_label)
            if base_run:
                rows.append(summarize_run(base_run, f"baseline/{dir_label}/{win_label}"))
            # 6 variants from sweep
            for v in VARIANTS:
                run = resolve_run_dir(RUNS_ROOT, dir_label, v, win_label)
                if run is None:
                    logger.warning(f"missing run: {dir_label}/{v}/{win_label}")
                    continue
                rows.append(summarize_run(run, f"{v}/{dir_label}/{win_label}"))

    # ── Δ vs baseline (per dir, variant, window) ──────────────────────────────
    def _key(r):
        # Parse label like "t1.75/raw/is" → (dir, win, variant)
        parts = r["label"].split("/")
        return parts[1], parts[2], parts[0]

    def _find(dir_label, win_label, variant):
        return next((r for r in rows if r["label"] == f"{variant}/{dir_label}/{win_label}"), None)

    # ── Write summary ────────────────────────────────────────────────────────
    summary_md: list[str] = [
        "# H3.2 — Portfolio-Level Draw-Down (Nautilus LS v1)\n",
        f"_Generated {datetime.now(timezone.utc).isoformat()}_\n",
        "Window: IS = 2025-05-03 → 2025-12-31 (8mo) · "
        "OOS = 2026-01-01 → 2026-03-12 (2mo)\n",
        f"Starting capital (for % DD): ${STARTING_CAPITAL:,.0f}\n",
        "",
        "Per-trade stats showed `[0.5, 1.75]` as Pareto-balanced. This script computes",
        "**portfolio-level** equity curve + Max DD + per-day Sharpe from the same runs.",
        "",
    ]

    # Headline table
    summary_md.append("## Headline (PnL / Final Equity / Peak / Max DD / Per-day Sharpe)\n")
    summary_md.append("| dir | win | variant | n trades | Total PnL | Final Eq | Peak Eq | Max DD ($) | Max DD (%) | Per-day Sharpe |")
    summary_md.append("|---|---|---|---:|---:|---:|---:|---:|---:|---:|")
    for dir_label in DIRS:
        for win_label in WINDOWS:
            for v in (["baseline"] + VARIANTS):
                r = _find(dir_label, win_label, v)
                if r is None:
                    continue
                summary_md.append(
                    f"| {dir_label} | {win_label} | {v} | {r['n_trades']} | "
                    f"${r['total_pnl_usd']:+.2f} | ${r['final_equity_usd']:.2f} | "
                    f"${r['peak_equity_usd']:.2f} | ${r['max_dd_usd']:+.2f} | "
                    f"{r['max_dd_pct']:+.2f}% | {r['per_day_sharpe']:.4f} |"
                )

    # Δ vs baseline — Max DD especially
    summary_md.append("\n## Δ vs baseline (variant − baseline)\n")
    summary_md.append("| dir | win | variant | Δ Total PnL | Δ Max DD ($) | Δ Max DD (%) | Δ Per-day Sharpe |")
    summary_md.append("|---|---|---|---:|---:|---:|---:|")
    for dir_label in DIRS:
        for win_label in WINDOWS:
            base = _find(dir_label, win_label, "baseline")
            if base is None:
                continue
            for v in VARIANTS:
                r = _find(dir_label, win_label, v)
                if r is None:
                    continue
                d_pnl = r["total_pnl_usd"] - base["total_pnl_usd"]
                d_dd_usd = r["max_dd_usd"] - base["max_dd_usd"]
                d_dd_pct = r["max_dd_pct"] - base["max_dd_pct"]
                d_sh = r["per_day_sharpe"] - base["per_day_sharpe"]
                summary_md.append(
                    f"| {dir_label} | {win_label} | {v} | "
                    f"${d_pnl:+.2f} | ${d_dd_usd:+.2f} | {d_dd_pct:+.2f}% | {d_sh:+.4f} |"
                )

    # Worst Max DD across all configs — risk profile
    summary_md.append("\n## Risk profile (worst Max DD by variant, raw/IS)\n")
    summary_md.append("| variant | floor | cap | worst-case Max DD (%) | n trades |")
    summary_md.append("|---|---:|---:|---:|---:|")
    floorcap = {
        "def": (0.5, 1.5), "t1.25": (0.5, 1.25), "t1.75": (0.5, 1.75),
        "t2.0": (0.5, 2.0), "d0.25": (0.25, 1.5), "cvx": (0.0, 2.0),
    }
    for v in VARIANTS:
        r = _find("raw", "is", v)
        if r is None:
            continue
        f, c = floorcap[v]
        summary_md.append(f"| {v} | {f} | {c} | {r['max_dd_pct']:+.2f}% | {r['n_trades']} |")

    # Recommendation placeholder — filled in after results
    summary_md.append("\n## Recommendation\n")
    summary_md.append("(Filled in after results.)")

    (OUT_ROOT / "full_results.json").write_text(json.dumps(rows, indent=2))
    (OUT_ROOT / "summary.md").write_text("\n".join(summary_md))
    print(f"\nH3.2 portfolio-level DD analysis complete: {len(rows)} runs")
    print(f"Output: {OUT_ROOT}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    main()