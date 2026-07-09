#!/usr/bin/env python3
"""
H3 — Conviction-Weighted Regime Gate (Seth, 2026-07-06)
========================================================

Per H2 design §3 self-flag:
    "What's MISSING is wiring the regime-conditional IC confidence into the
     cross-sectional spread's sizing."

This script runs Nautilus LS v1 with the H3 conviction-weighted gate:
per-day conviction (window-stability from `scripts/regime_smoother.py`)
multiplies the regime_cis_floor. Five variants tested:

  baseline     : no scaling, current H2 behaviour (control)
  linear       : floor * (0.5 + conviction)        ∈ [0.5, 1.5]
  asymmetric   : floor * conviction                 ∈ [0.0, 1.0]
  sigmoid      : floor * sigmoid(4*(c-0.5)) scaled  ∈ [0.0, 1.0]
  step@0.85    : floor * 1.0 if c≥0.85 else 0.0    (binary gate)

Two CIS history dirs (raw + modal_recency). The H3 hypothesis: conviction
scaling should ADD value in the RAW world (where conviction dips to 0.5 on
noisy days); in the SMOOTHED world (where conviction ≈ 1.0 always) it should
be a no-op or a near-no-op (sanity check that smoothed + H3 don't double-count).

Walk-forward: IS = 2025-05-03 → 2025-12-31, OOS = 2026-01-01 → 2026-03-12.

Usage:
  source venv/bin/activate
  python3 -m src.research.cis_regime_studies.h3_conviction_weighted_gate

Run log: reports/h3_conviction/2026-07-06/{runs,summary}.json
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


VARIANTS = ["baseline", "linear", "asymmetric", "sigmoid", "step@0.85"]

DIRS = {
    "raw":            "/Volumes/CometCloudAI/cometcloud-local/_data/cis_history/",
    "modal_recency":  "/Volumes/CometCloudAI/cometcloud-local/_data/cis_history_smoothed/",
}

WINDOWS = [
    ("is",  "2025-05-03T00:00:00Z", "2025-12-31T00:00:00Z"),
    ("oos", "2026-01-01T00:00:00Z", "2026-03-12T00:00:00Z"),
]

OUT_ROOT = Path("/Users/sbb/Projects/looloomi-ai/reports/h3_conviction/2026-07-06")
CONV_DIR = OUT_ROOT / "_conv"


@dataclass(frozen=True)
class Variant:
    label: str           # baseline | linear | asymmetric | sigmoid | step@0.85
    env_variant: str     # value for LSV1_CONV_VARIANT (no @threshold suffix)
    env_step_threshold: str | None = None  # only for step@T variants


def _parse_variant(label: str) -> Variant:
    if label.startswith("step@"):
        thr = label.split("@", 1)[1]
        return Variant(label=label, env_variant="step", env_step_threshold=thr)
    return Variant(label=label, env_variant=label)


def run_one(*, dir_label: str, dir_path: str, variant: Variant,
            win_label: str, win_start: str, win_end: str) -> dict:
    """Run a single Nautilus LS v1 backtest with H3 conviction-weighted gate."""
    out_dir = OUT_ROOT / "runs" / dir_label / variant.label / win_label
    out_dir.mkdir(parents=True, exist_ok=True)

    conv_path = CONV_DIR / f"cis_conv_{dir_label}_w14.json"
    if not conv_path.exists():
        raise FileNotFoundError(f"conviction file missing: {conv_path}. "
                                "Run scripts/compute_cis_conviction.py first.")

    env = os.environ.copy()
    env.update({
        "NAUTILUS_LS_V1_START": win_start,
        "NAUTILUS_LS_V1_END":   win_end,
        "CIS_HISTORY_DIR":      dir_path,
        "NAUTILUS_LS_V1_OUT_DIR": str(out_dir),
        "LSV1_CONVICTION_PATH": str(conv_path),
        "LSV1_CONV_VARIANT":    variant.env_variant,
    })
    if variant.env_step_threshold:
        env["LSV1_CONV_STEP_THRESHOLD"] = variant.env_step_threshold

    cmd = [sys.executable, "-m", "src.research.nautilus.ls_v1.runner"]
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=300)

    # Find the summary.json — runner names them with timestamp
    summary_path = None
    for run_dir in sorted(out_dir.glob("run_*")):
        cand = run_dir / "summary.json"
        if cand.exists():
            summary_path = cand
    if summary_path is None:
        return {"error": "no_summary", "stderr_tail": proc.stderr[-500:],
                "stdout_tail": proc.stdout[-500:]}
    return {"summary_path": str(summary_path),
            "summary": json.loads(summary_path.read_text())}


def _sharpe_from_positions(run_dir: Path) -> float:
    """Compute per-position Sharpe from realised_pnl array."""
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


def main():
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []

    for win_label, win_start, win_end in WINDOWS:
        for dir_label, dir_path in DIRS.items():
            for variant_label in VARIANTS:
                variant = _parse_variant(variant_label)
                logger.info(f"[H3] {dir_label}/{variant.label}/{win_label}")
                r = run_one(dir_label=dir_label, dir_path=dir_path,
                            variant=variant, win_label=win_label,
                            win_start=win_start, win_end=win_end)
                if "error" in r:
                    results.append({"dir": dir_label, "variant": variant.label,
                                    "window": win_label, "error": r["error"]})
                    continue
                run_dir = Path(r["summary_path"]).parent
                s = r["summary"]
                sh = _sharpe_from_positions(run_dir)
                sk = _skip_summary(run_dir)
                results.append({
                    "dir": dir_label, "variant": variant.label, "window": win_label,
                    "orders": s.get("n_orders_total", 0),
                    "positions": s.get("n_positions_total", 0),
                    "pnl_usd": round(s.get("pnl_usd_total", 0), 2),
                    "sharpe": round(sh, 4),
                    "skip_cis": sk.get("skipped_cis"),
                    "skip_adx": sk.get("skipped_adx"),
                    "out_dir": str(run_dir),
                })

    # ── write outputs ──────────────────────────────────────────────────────
    summary_md = ["# H3 — Conviction-Weighted Regime Gate (Nautilus LS v1)\n",
                  f"_Generated {datetime.now(timezone.utc).isoformat()}_\n",
                  "Window: IS = 2025-05-03 → 2025-12-31 (8mo) · "
                  "OOS = 2026-01-01 → 2026-03-12 (2mo)\n",
                  "Dirs: raw + modal_recency · Variants: 5 · "
                  "Total runs: 2 × 5 × 2 = 20\n"]
    summary_md.append("## Per-variant summary\n")
    summary_md.append("| dir | variant | IS PnL | IS ord | IS Sharpe | OOS PnL | OOS ord | OOS Sharpe |")
    summary_md.append("|---|---|---:|---:|---:|---:|---:|---:|")
    by_key: dict[tuple, dict] = {}
    for r in results:
        if "error" in r:
            continue
        by_key[(r["dir"], r["variant"])] = r
    for dir_label in DIRS:
        for variant_label in VARIANTS:
            r = by_key.get((dir_label, variant_label))
            if not r:
                continue
            # Find IS + OOS
            is_r = next((x for x in results if x.get("dir")==dir_label
                         and x.get("variant")==variant_label and x.get("window")=="is"), None)
            oos_r = next((x for x in results if x.get("dir")==dir_label
                          and x.get("variant")==variant_label and x.get("window")=="oos"), None)
            if is_r and oos_r:
                summary_md.append(
                    f"| {dir_label} | {variant_label} | "
                    f"${is_r['pnl_usd']:.2f} | {is_r['orders']} | {is_r['sharpe']:.3f} | "
                    f"${oos_r['pnl_usd']:.2f} | {oos_r['orders']} | {oos_r['sharpe']:.3f} |"
                )

    # Write outputs
    (OUT_ROOT / "full_results.json").write_text(json.dumps(results, indent=2, default=str))
    (OUT_ROOT / "summary.md").write_text("\n".join(summary_md))
    print(f"\nH3 sweep complete: {len(results)} runs")
    print(f"Output: {OUT_ROOT}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    main()