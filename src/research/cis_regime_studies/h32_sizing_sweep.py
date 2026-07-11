#!/usr/bin/env python3
"""
H3.2 sizing FLOOR/CAP SWEEP (Nautilus LS v1, 2026-07-10)
==========================================================

Per H3.2 finding (H32_SIZING_AB_2026-07-09.md): sizing by per-day conviction
improves per-trade PnL across all 4 runs but Sharpe DROPS in raw OOS
(0.108 → 0.091). The [0.5, 1.5] default was chosen ad-hoc.

Question: is there a (floor, cap) variant that improves BOTH per-trade PnL
AND Sharpe vs baseline? The current default wins PnL but loses Sharpe on OOS.

Variants tested (floor, cap) → multiplier = floor + (cap − floor) × c:
    1. (0.5,  1.5)  — current default (re-run for sanity-check)
    2. (0.5,  1.25) — tighter upside
    3. (0.5,  1.75) — wider upside
    4. (0.5,  2.0)  — widest cap
    5. (0.25, 1.5)  — more downside protection
    6. (0.0,  2.0)  — linear through origin (most convex)

Two CIS history dirs (most informative):
    raw           — conviction varies (median 0.929, range 0.500-1.000)
    modal_recency — conviction ≈ 1.0 always (linear-leverage toggle sanity check)

Walk-forward:
    IS  = 2025-05-03 → 2025-12-31  (8 months, 244 days)
    OOS = 2026-01-01 → 2026-03-12  (2 months, 71 days)

Total: 6 variants × 2 dirs × 2 windows = 24 Nautilus LS v1 runs.
Plus baseline re-use from H32_SIZING_AB (no re-run needed).

Usage:
    source venv/bin/activate
    python3 -m src.research.cis_regime_studies.h32_sizing_sweep
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

# (label, floor, cap) — multiplier = floor + (cap - floor) * c
VARIANTS = [
    ("def",   0.5,  1.5),   # current default — re-run for sanity-check
    ("t1.25", 0.5,  1.25),  # tighter upside
    ("t1.75", 0.5,  1.75),  # wider upside
    ("t2.0",  0.5,  2.0),   # widest cap
    ("d0.25", 0.25, 1.5),   # more downside protection
    ("cvx",   0.0,  2.0),   # linear through origin (most convex)
]

DIRS = {
    "raw":            "/Volumes/CometCloudAI/cometcloud-local/_data/cis_history/",
    "modal_recency":  "/Volumes/CometCloudAI/cometcloud-local/_data/cis_history_smoothed/",
}

WINDOWS = [
    ("is",  "2025-05-03T00:00:00Z", "2025-12-31T00:00:00Z"),
    ("oos", "2026-01-01T00:00:00Z", "2026-03-12T00:00:00Z"),
]

OUT_ROOT = Path("/Users/sbb/Projects/looloomi-ai/reports/h32_sizing_sweep/2026-07-10")
CONV_DIR = Path("/Users/sbb/Projects/looloomi-ai/reports/h3_conviction/2026-07-06/_conv")


# ── Helpers ──────────────────────────────────────────────────────────────────

def run_one(*, dir_label: str, dir_path: str, variant_label: str,
            floor: float, cap: float,
            win_label: str, win_start: str, win_end: str) -> dict:
    """Run a single Nautilus LS v1 backtest with the H3.2 sizing variant."""
    out_dir = OUT_ROOT / "runs" / dir_label / variant_label / win_label
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
        "LSV1_CONV_VARIANT":    "baseline",  # gate unchanged
        "LSV1_USE_H32_SIZING":  "1",
        "LSV1_H32_SIZE_FLOOR":  str(floor),
        "LSV1_H32_SIZE_CAP":    str(cap),
    })

    cmd = [sys.executable, "-m", "src.research.nautilus.ls_v1.runner"]
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        logger.warning(f"[h32-sweep] {dir_label}/{variant_label}/{win_label} → nonzero exit ({proc.returncode})")

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


def _baseline_lookup(dir_label: str, win_label: str) -> dict | None:
    """Re-use baseline numbers from the original H3.2 A/B (already ran, no need to re-run)."""
    base_path = Path(f"/Users/sbb/Projects/looloomi-ai/reports/h32_sizing/2026-07-09/runs/{dir_label}/baseline/{win_label}")
    for run_dir in sorted(base_path.glob("run_*")):
        ss = run_dir / "summary.json"
        if ss.exists():
            s = json.loads(ss.read_text())
            n = s.get("n_positions_total", 0) or 0
            avg_size = (s.get("pnl_usd_total", 0) / max(n, 1)) if n else 0.0
            sh = _sharpe_from_positions(run_dir)
            return {
                "pnl_usd": round(s.get("pnl_usd_total", 0), 2),
                "positions": n,
                "avg_pnl_per_pos": round(avg_size, 3),
                "sharpe": round(sh, 4),
            }
    return None


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []

    # ── Run all 24 variants ─────────────────────────────────────────────────
    for win_label, win_start, win_end in WINDOWS:
        for dir_label, dir_path in DIRS.items():
            for vlabel, floor, cap in VARIANTS:
                logger.info(f"[h32-sweep] {dir_label}/{vlabel}({floor},{cap})/{win_label}")
                r = run_one(dir_label=dir_label, dir_path=dir_path,
                            variant_label=vlabel, floor=floor, cap=cap,
                            win_label=win_label, win_start=win_start, win_end=win_end)
                if "error" in r:
                    results.append({"dir": dir_label, "variant": vlabel,
                                    "floor": floor, "cap": cap,
                                    "window": win_label, "error": r["error"]})
                    continue
                run_dir = Path(r["summary_path"]).parent
                s = r["summary"]
                sh = _sharpe_from_positions(run_dir)
                n = s.get("n_positions_total", 0) or 0
                avg_size = (s.get("pnl_usd_total", 0) / max(n, 1)) if n else 0.0
                results.append({
                    "dir": dir_label, "variant": vlabel,
                    "floor": floor, "cap": cap,
                    "window": win_label,
                    "pnl_usd": round(s.get("pnl_usd_total", 0), 2),
                    "positions": n,
                    "avg_pnl_per_pos": round(avg_size, 3),
                    "sharpe": round(sh, 4),
                    "out_dir": str(run_dir),
                })

    # ── Lookup baselines from original H3.2 A/B ────────────────────────────
    baselines = {}
    for dir_label in DIRS:
        for win_label, _, _ in WINDOWS:
            baselines[(dir_label, win_label)] = _baseline_lookup(dir_label, win_label)

    # ── Δ tables: per (dir, variant) × {IS, OOS} ──────────────────────────
    def _find(dir_label, vlabel, win_label):
        return next((x for x in results if x["dir"] == dir_label
                     and x["variant"] == vlabel and x["window"] == win_label), None)

    # ── Write outputs ──────────────────────────────────────────────────────
    summary_md: list[str] = [
        "# H3.2 — Sizing FLOOR/CAP SWEEP (Nautilus LS v1)\n",
        f"_Generated {datetime.now(timezone.utc).isoformat()}_\n",
        "Window: IS = 2025-05-03 → 2025-12-31 (8mo) · "
        "OOS = 2026-01-01 → 2026-03-12 (2mo)\n",
        f"Dirs: {', '.join(DIRS.keys())} · Variants: {len(VARIANTS)} · "
        f"Total variant runs: {len(VARIANTS)} × {len(DIRS)} × {len(WINDOWS)} = 24\n",
        "",
        "Hypothesis: find a (floor, cap) variant that improves BOTH per-trade PnL AND Sharpe.",
        "Current default [0.5, 1.5] wins PnL but raw OOS Sharpe drops 0.108 → 0.091.",
        "",
    ]

    # Per-variant headline table (per dir, IS + OOS combined)
    summary_md.append("## Per-variant headline (PnL / $/pos / Sharpe)\n")
    summary_md.append("| dir | variant | floor | cap | IS PnL | IS $/pos | IS Sharpe | OOS PnL | OOS $/pos | OOS Sharpe |")
    summary_md.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for dir_label in DIRS:
        for vlabel, floor, cap in VARIANTS:
            is_r = _find(dir_label, vlabel, "is")
            oos_r = _find(dir_label, vlabel, "oos")
            if is_r is None or oos_r is None:
                summary_md.append(f"| {dir_label} | {vlabel} | {floor} | {cap} | — | — | — | — | — | — |")
                continue
            summary_md.append(
                f"| {dir_label} | {vlabel} | {floor} | {cap} | "
                f"${is_r['pnl_usd']:.2f} | ${is_r['avg_pnl_per_pos']:+.2f} | {is_r['sharpe']:.3f} | "
                f"${oos_r['pnl_usd']:.2f} | ${oos_r['avg_pnl_per_pos']:+.2f} | {oos_r['sharpe']:.3f} |"
            )

    # Δ vs baseline table
    summary_md.append("\n## Δ vs baseline (variant − baseline)\n")
    summary_md.append("| dir | variant | floor | cap | ΔIS $/pos | ΔIS Sharpe | ΔOOS $/pos | ΔOOS Sharpe |")
    summary_md.append("|---|---|---:|---:|---:|---:|---:|---:|")
    for dir_label in DIRS:
        for vlabel, floor, cap in VARIANTS:
            is_r = _find(dir_label, vlabel, "is")
            oos_r = _find(dir_label, vlabel, "oos")
            base_is = baselines.get((dir_label, "is"))
            base_oos = baselines.get((dir_label, "oos"))
            if not is_r or not oos_r or not base_is or not base_oos:
                summary_md.append(f"| {dir_label} | {vlabel} | {floor} | {cap} | — | — | — | — |")
                continue
            d_is_pps = is_r["avg_pnl_per_pos"] - base_is["avg_pnl_per_pos"]
            d_is_sh = is_r["sharpe"] - base_is["sharpe"]
            d_oos_pps = oos_r["avg_pnl_per_pos"] - base_oos["avg_pnl_per_pos"]
            d_oos_sh = oos_r["sharpe"] - base_oos["sharpe"]
            summary_md.append(
                f"| {dir_label} | {vlabel} | {floor} | {cap} | "
                f"${d_is_pps:+.2f} | {d_is_sh:+.3f} | "
                f"${d_oos_pps:+.2f} | {d_oos_sh:+.3f} |"
            )

    # Best variant by metric
    def _best(metric_key, prefer_higher=True, oos_only=False):
        best = None
        for r in results:
            if oos_only and r["window"] != "oos":
                continue
            v = r.get(metric_key)
            if v is None:
                continue
            if best is None:
                best = (r, v)
                continue
            if (prefer_higher and v > best[1]) or (not prefer_higher and v < best[1]):
                best = (r, v)
        return best

    best_is_pps = _best("avg_pnl_per_pos", prefer_higher=True, oos_only=False)
    best_oos_pps = _best("avg_pnl_per_pos", prefer_higher=True, oos_only=True)
    best_oos_sh = _best("sharpe", prefer_higher=True, oos_only=True)

    summary_md.append("\n## Best variant by metric\n")
    if best_is_pps:
        r, v = best_is_pps
        summary_md.append(f"- **Best IS $/pos:** `{r['variant']}` (floor={r['floor']}, cap={r['cap']}) dir={r['dir']} = ${v:+.2f}/trade")
    if best_oos_pps:
        r, v = best_oos_pps
        summary_md.append(f"- **Best OOS $/pos:** `{r['variant']}` (floor={r['floor']}, cap={r['cap']}) dir={r['dir']} = ${v:+.2f}/trade")
    if best_oos_sh:
        r, v = best_oos_sh
        summary_md.append(f"- **Best OOS Sharpe:** `{r['variant']}` (floor={r['floor']}, cap={r['cap']}) dir={r['dir']} = {v:.3f}")

    summary_md.append("\n## Recommendation\n")
    summary_md.append("(Filled in after results.)")

    (OUT_ROOT / "full_results.json").write_text(json.dumps(results, indent=2, default=str))
    (OUT_ROOT / "summary.md").write_text("\n".join(summary_md))
    print(f"\nH3.2 sizing FLOOR/CAP SWEEP complete: {len(results)} runs")
    print(f"Output: {OUT_ROOT}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    main()