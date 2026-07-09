#!/usr/bin/env python3
"""
Edge Gate A/B — Regime-Floor vs Continuous Expected-Edge
========================================================

Per H2 design §3 (Seth, 2026-07-06): the discrete `REGIME_CIS_FLOOR`
hard-codes "high CIS is good" for every regime, which is directionally
wrong in 4 of 5 observed regimes (H1 sweep: composite CIS IC is
negative in Risk-Off / Risk-On / Easing / Tightening).

This script replaces the regime floor with a continuous expected-edge
gate:

    edge = side × IC_regime × z × sigma × sqrt(horizon) - cost

where:
    side      ±1 (from EMA cross)
    IC_regime per-regime composite CIS 7d IC (H1.5 sweep)
    z         cross-sectional z-score (asset vs regime peers)
    sigma     ATR(14) / close (asset's own return-unit vol)
    horizon   trade expected hold (default 1d)
    cost      round-trip fee (default 0.001)

Setup:
  A) `baseline` — current behaviour: discrete REGIME_CIS_FLOOR gate.
  B) `edge_gate` — continuous expected-edge gate (Seth, 2026-07-06).

CIS history dirs (4):
  raw            (4-day median regime length — noisy)
  modal_recency  (14d — Phase 1 ship target)
  modal_majority (window-mode — safety check)
  persistence    (14d persistence — natural counterfactual)

Walk-forward:
  IS  = 2025-05-03 → 2025-12-31 (8 months, 244 days)
  OOS = 2026-01-01 → 2026-03-12 (2 months, 71 days)

Total: 4 dirs × 2 variants × 2 windows = 16 Nautilus LS v1 runs.

Usage:
  source venv/bin/activate
  python3 -m src.research.cis_regime_studies.edge_gate_ab
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


logger = logging.getLogger(__name__)


# ── Config ────────────────────────────────────────────────────────────────────

VARIANTS = ["baseline", "edge_gate"]

DIRS = {
    "raw":             "/Volumes/CometCloudAI/cometcloud-local/_data/cis_history/",
    "modal_recency":   "/Volumes/CometCloudAI/cometcloud-local/_data/cis_history_smoothed/",
    "modal_majority":  "/Volumes/CometCloudAI/cometcloud-local/_data/cis_history_smoothed_majority/",
    "persistence":     "/Volumes/CometCloudAI/cometcloud-local/_data/cis_history_smoothed_persistence/",
}

WINDOWS = [
    ("is",  "2025-05-03T00:00:00Z", "2025-12-31T00:00:00Z"),
    ("oos", "2026-01-01T00:00:00Z", "2026-03-12T00:00:00Z"),
]

OUT_ROOT = Path("/Users/sbb/Projects/looloomi-ai/reports/edge_gate_ab/2026-07-06")


# ── Helpers ──────────────────────────────────────────────────────────────────

def run_one(*, dir_label: str, dir_path: str, variant: str,
            win_label: str, win_start: str, win_end: str) -> dict:
    """Run a single Nautilus LS v1 backtest under one (dir, variant, window).

    Returns a dict with either {'error': ...} on failure or
    {'summary_path': ..., 'summary': ...} on success.
    """
    out_dir = OUT_ROOT / "runs" / dir_label / variant / win_label
    out_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env.update({
        "NAUTILUS_LS_V1_START": win_start,
        "NAUTILUS_LS_V1_END":   win_end,
        "CIS_HISTORY_DIR":      dir_path,
        "NAUTILUS_LS_V1_OUT_DIR": str(out_dir),
    })
    if variant == "edge_gate":
        env["LSV1_USE_EDGE_GATE"] = "1"
        # Defaults: edge_cost=0.001, edge_horizon_days=1.0, ic_path=(default)

    cmd = [sys.executable, "-m", "src.research.nautilus.ls_v1.runner"]
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        logger.warning(f"[edge_ab] {dir_label}/{variant}/{win_label} → nonzero exit ({proc.returncode})")

    # Find the most recent summary.json
    summary_path = None
    for run_dir in sorted(out_dir.glob("run_*")):
        cand = run_dir / "summary.json"
        if cand.exists():
            summary_path = cand
    if summary_path is None:
        return {"error": "no_summary",
                "stderr_tail": proc.stderr[-500:],
                "stdout_tail": proc.stdout[-500:]}
    return {"summary_path": str(summary_path),
            "summary": json.loads(summary_path.read_text())}


def _sharpe_from_positions(run_dir: Path) -> float:
    """Per-position Sharpe from realised_pnl array (mirrors H3 driver)."""
    pi_path = next(run_dir.glob("per_instrument.json"), None)
    if pi_path is None:
        return 0.0
    per_inst = json.loads(pi_path.read_text())
    pnls = [p.get("realized_pnl", 0) for inst in per_inst for p in inst.get("positions", [])]
    if len(pnls) < 2:
        return 0.0
    mean = sum(pnls) / len(pnls)
    var = sum((x - mean) ** 2 for x in pnls) / (len(pnls) - 1)
    sd = var ** 0.5
    return mean / sd if sd > 0 else 0.0


def _skip_summary(run_dir: Path) -> dict:
    ss_path = next(run_dir.glob("skip_summary.json"), None)
    if ss_path is None:
        return {}
    d = json.loads(ss_path.read_text())
    if d:
        return list(d.values())[0]
    return {}


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []

    for win_label, win_start, win_end in WINDOWS:
        for dir_label, dir_path in DIRS.items():
            for variant in VARIANTS:
                logger.info(f"[edge_ab] {dir_label}/{variant}/{win_label}")
                r = run_one(dir_label=dir_label, dir_path=dir_path,
                            variant=variant, win_label=win_label,
                            win_start=win_start, win_end=win_end)
                if "error" in r:
                    results.append({"dir": dir_label, "variant": variant,
                                    "window": win_label, "error": r["error"],
                                    "stderr_tail": r.get("stderr_tail", "")[-300:]})
                    continue
                run_dir = Path(r["summary_path"]).parent
                s = r["summary"]
                sh = _sharpe_from_positions(run_dir)
                sk = _skip_summary(run_dir)
                results.append({
                    "dir": dir_label, "variant": variant, "window": win_label,
                    "orders": s.get("n_orders_total", 0),
                    "positions": s.get("n_positions_total", 0),
                    "pnl_usd": round(s.get("pnl_usd_total", 0), 2),
                    "sharpe": round(sh, 4),
                    "skip_cis": sk.get("skipped_cis"),
                    "skip_adx": sk.get("skipped_adx"),
                    "current_regime_final": sk.get("current_regime_final"),
                    "out_dir": str(run_dir),
                })

    # ── write outputs ──────────────────────────────────────────────────────
    summary_md: list[str] = [
        "# Edge Gate A/B — Regime-Floor vs Continuous Expected-Edge (Nautilus LS v1)\n",
        f"_Generated {datetime.now(timezone.utc).isoformat()}_\n",
        "Window: IS = 2025-05-03 → 2025-12-31 (8mo) · "
        "OOS = 2026-01-01 → 2026-03-12 (2mo)\n",
        f"Dirs: {', '.join(DIRS.keys())} · Variants: {VARIANTS} · "
        f"Total runs: {len(DIRS)} × {len(VARIANTS)} × {len(WINDOWS)} = 16\n",
        "",
        "Hypothesis: edge gate (continuous, sign-flipped by regime+side) "
        "should beat regime floor (discrete, hardcoded 'high CIS is good') "
        "on per-trade PnL, especially in smoothed regime labels where the "
        "noise that made the floor work is removed.",
        "",
    ]

    # Per-dir × per-variant summary table
    summary_md.append("## Per-config summary\n")
    summary_md.append("| dir | variant | IS PnL | IS ord | IS Sharpe | OOS PnL | OOS ord | OOS Sharpe |")
    summary_md.append("|---|---|---:|---:|---:|---:|---:|---:|")
    by_key = {(r["dir"], r["variant"]): r for r in results if "error" not in r}
    for dir_label in DIRS:
        for variant in VARIANTS:
            is_r = next((x for x in results if x.get("dir") == dir_label
                         and x.get("variant") == variant and x.get("window") == "is"), None)
            oos_r = next((x for x in results if x.get("dir") == dir_label
                          and x.get("variant") == variant and x.get("window") == "oos"), None)
            if is_r is None or oos_r is None:
                summary_md.append(f"| {dir_label} | {variant} | — | — | — | — | — | — |")
                continue
            summary_md.append(
                f"| {dir_label} | {variant} | "
                f"${is_r['pnl_usd']:.2f} | {is_r['orders']} | {is_r['sharpe']:.3f} | "
                f"${oos_r['pnl_usd']:.2f} | {oos_r['orders']} | {oos_r['sharpe']:.3f} |"
            )

    # Δ-edge_gate − baseline per dir
    summary_md.append("\n## Δ (edge_gate − baseline)\n")
    summary_md.append("| dir | ΔIS PnL | ΔIS ord | ΔOOS PnL | ΔOOS ord |")
    summary_md.append("|---|---:|---:|---:|---:|")
    for dir_label in DIRS:
        base_is = next((x for x in results if x.get("dir") == dir_label
                        and x.get("variant") == "baseline" and x.get("window") == "is"), None)
        edge_is = next((x for x in results if x.get("dir") == dir_label
                        and x.get("variant") == "edge_gate" and x.get("window") == "is"), None)
        base_oos = next((x for x in results if x.get("dir") == dir_label
                         and x.get("variant") == "baseline" and x.get("window") == "oos"), None)
        edge_oos = next((x for x in results if x.get("dir") == dir_label
                         and x.get("variant") == "edge_gate" and x.get("window") == "oos"), None)
        if base_is is None or edge_is is None or base_oos is None or edge_oos is None:
            summary_md.append(f"| {dir_label} | — | — | — | — |")
            continue
        d_is_pnl = edge_is['pnl_usd'] - base_is['pnl_usd']
        d_is_ord = edge_is['orders'] - base_is['orders']
        d_oos_pnl = edge_oos['pnl_usd'] - base_oos['pnl_usd']
        d_oos_ord = edge_oos['orders'] - base_oos['orders']
        summary_md.append(
            f"| {dir_label} | ${d_is_pnl:+.2f} | {d_is_ord:+d} | "
            f"${d_oos_pnl:+.2f} | {d_oos_ord:+d} |"
        )

    (OUT_ROOT / "full_results.json").write_text(json.dumps(results, indent=2, default=str))
    (OUT_ROOT / "summary.md").write_text("\n".join(summary_md))
    print(f"\nedge gate A/B sweep complete: {len(results)} runs")
    print(f"Output: {OUT_ROOT}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    main()
