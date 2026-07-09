#!/usr/bin/env python3
"""
H3.2 — Conviction-Weighted SIZING (Nautilus LS v1, 2026-07-09)
================================================================

Per H3 finding (H3_CONVICTION_WEIGHTED_GATE_2026-07-06.md):
    "Conviction is a sizing signal, not a gating signal."

H3.1 (gate-multiplier) FAILED — every variant lost to baseline because the
floor band [50, 65] is too tight relative to CIS scores [60, 70]; a 0.5-1.5×
multiplier on the floor moves the trade count by ±90% (a turnover tax).

H3.2 (this study) keeps the gate at REGIME_CIS_FLOOR unchanged, and instead
scales the POSITION SIZE by per-day conviction:
    trade_size_today = base_trade_size * (h32_size_floor + (h32_size_cap - h32_size_floor) * c)
                       = base_trade_size * (0.5 + c)            # defaults: [0.5, 1.5]×

Hypothesis:
    - Trade count stays at baseline (gate unchanged)
    - PnL holds or improves (full conviction days size up)
    - Drawdown on low-conviction days reduces (low conviction days size down)
    - Mechanism is the same as Millennium soft sizing: let the signal through, weight
      it by confidence

Two CIS history dirs (most informative):
    cis_history/ (raw, conviction dips to 0.5 on noisy days) — H3.2 has teeth
    cis_history_smoothed/ (modal_recency, conviction ≈ 1.0) — sanity check (no-op)

Walk-forward:
    IS  = 2025-05-03 → 2025-12-31  (8 months, 244 days)
    OOS = 2026-01-01 → 2026-03-12  (2 months, 71 days)

Total: 2 dirs × 2 variants × 2 windows = 8 Nautilus LS v1 runs.

Usage:
    source venv/bin/activate
    python3 -m src.research.cis_regime_studies.h32_sizing_ab
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

VARIANTS = ["baseline", "h32_sizing"]

DIRS = {
    "raw":            "/Volumes/CometCloudAI/cometcloud-local/_data/cis_history/",
    "modal_recency":  "/Volumes/CometCloudAI/cometcloud-local/_data/cis_history_smoothed/",
}

WINDOWS = [
    ("is",  "2025-05-03T00:00:00Z", "2025-12-31T00:00:00Z"),
    ("oos", "2026-01-01T00:00:00Z", "2026-03-12T00:00:00Z"),
]

OUT_ROOT = Path("/Users/sbb/Projects/looloomi-ai/reports/h32_sizing/2026-07-09")
CONV_DIR = Path("/Users/sbb/Projects/looloomi-ai/reports/h3_conviction/2026-07-06/_conv")


# ── Helpers ──────────────────────────────────────────────────────────────────

def run_one(*, dir_label: str, dir_path: str, variant: str,
            win_label: str, win_start: str, win_end: str) -> dict:
    """Run a single Nautilus LS v1 backtest with the H3.2 sizing variant."""
    out_dir = OUT_ROOT / "runs" / dir_label / variant / win_label
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
    })
    if variant == "h32_sizing":
        env["LSV1_USE_H32_SIZING"] = "1"
        # defaults: floor=0.5, cap=1.5 → multiplier = 0.5 + c

    cmd = [sys.executable, "-m", "src.research.nautilus.ls_v1.runner"]
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        logger.warning(f"[h32] {dir_label}/{variant}/{win_label} → nonzero exit ({proc.returncode})")

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


def _skip_summary(run_dir: Path) -> dict:
    ss_path = next(run_dir.glob("skip_summary.json"), None)
    if ss_path is None:
        return {}
    d = json.loads(ss_path.read_text())
    if d:
        return list(d.values())[0]
    return {}


def _max_drawdown_usd(per_inst_payload: dict) -> float:
    """Max drawdown in $ across the realised P&L series (rough — equity curve)."""
    pnls: list[float] = []
    for inst in per_inst_payload.values() if isinstance(per_inst_payload, dict) else []:
        for p in inst.get("positions", []):
            pnls.append(p.get("realized_pnl", 0) or 0)
    if not pnls:
        return 0.0
    equity = 0.0
    peak = 0.0
    dd = 0.0
    for p in pnls:
        equity += p
        peak = max(peak, equity)
        dd = min(dd, equity - peak)
    return dd


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []

    for win_label, win_start, win_end in WINDOWS:
        for dir_label, dir_path in DIRS.items():
            for variant in VARIANTS:
                logger.info(f"[h32] {dir_label}/{variant}/{win_label}")
                r = run_one(dir_label=dir_label, dir_path=dir_path,
                            variant=variant, win_label=win_label,
                            win_start=win_start, win_end=win_end)
                if "error" in r:
                    results.append({"dir": dir_label, "variant": variant,
                                    "window": win_label, "error": r["error"]})
                    continue
                run_dir = Path(r["summary_path"]).parent
                s = r["summary"]
                sh = _sharpe_from_positions(run_dir)
                sk = _skip_summary(run_dir)
                # Max drawdown (rough)
                pi_path = next(run_dir.glob("per_instrument.json"), None)
                if pi_path:
                    pi = json.loads(pi_path.read_text())
                    dd = _max_drawdown_usd(pi)
                else:
                    dd = 0.0
                # Total notional traded (rough proxy for "size at risk")
                tot_pnl = s.get("pnl_usd_total", 0) or 0
                n_pos = s.get("n_positions_total", 0) or 0
                avg_size = (s.get("pnl_usd_total", 0) / max(n_pos, 1)) if n_pos else 0.0
                results.append({
                    "dir": dir_label, "variant": variant, "window": win_label,
                    "orders": s.get("n_orders_total", 0),
                    "positions": n_pos,
                    "pnl_usd": round(s.get("pnl_usd_total", 0), 2),
                    "avg_pnl_per_pos": round(avg_size, 3),
                    "sharpe": round(sh, 4),
                    "max_dd_usd": round(dd, 2),
                    "skip_cis": sk.get("skipped_cis"),
                    "skip_adx": sk.get("skipped_adx"),
                    "out_dir": str(run_dir),
                })

    # ── write outputs ──────────────────────────────────────────────────────
    summary_md: list[str] = [
        "# H3.2 — Conviction-Weighted SIZING (Nautilus LS v1)\n",
        f"_Generated {datetime.now(timezone.utc).isoformat()}_\n",
        "Window: IS = 2025-05-03 → 2025-12-31 (8mo) · "
        "OOS = 2026-01-01 → 2026-03-12 (2mo)\n",
        f"Dirs: {', '.join(DIRS.keys())} · Variants: {VARIANTS} · "
        f"Total runs: {len(DIRS)} × {len(VARIANTS)} × {len(WINDOWS)} = 8\n",
        "",
        "Hypothesis (per H3 report, §'Conviction is a sizing signal'):",
        "H3.2 keeps the gate at REGIME_CIS_FLOOR unchanged, scales POSITION SIZE",
        "by per-day conviction. Trade count stays at baseline; PnL should hold or",
        "improve; drawdown on low-conviction days should reduce.",
        "",
    ]

    summary_md.append("## Per-config summary\n")
    summary_md.append("| dir | variant | IS PnL | IS pos | IS $/pos | IS Sharpe | IS MaxDD | OOS PnL | OOS pos | OOS $/pos | OOS Sharpe | OOS MaxDD |")
    summary_md.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for dir_label in DIRS:
        for variant in VARIANTS:
            is_r = next((x for x in results if x.get("dir") == dir_label
                         and x.get("variant") == variant and x.get("window") == "is"), None)
            oos_r = next((x for x in results if x.get("dir") == dir_label
                          and x.get("variant") == variant and x.get("window") == "oos"), None)
            if is_r is None or oos_r is None:
                summary_md.append(f"| {dir_label} | {variant} | — | — | — | — | — | — | — | — | — | — |")
                continue
            summary_md.append(
                f"| {dir_label} | {variant} | "
                f"${is_r['pnl_usd']:.2f} | {is_r['positions']} | ${is_r['avg_pnl_per_pos']:+.2f} | "
                f"{is_r['sharpe']:.3f} | ${is_r['max_dd_usd']:.2f} | "
                f"${oos_r['pnl_usd']:.2f} | {oos_r['positions']} | ${oos_r['avg_pnl_per_pos']:+.2f} | "
                f"{oos_r['sharpe']:.3f} | ${oos_r['max_dd_usd']:.2f} |"
            )

    summary_md.append("\n## Δ (h32_sizing − baseline)\n")
    summary_md.append("| dir | ΔIS PnL | ΔIS pos | ΔIS $/pos | ΔOOS PnL | ΔOOS pos | ΔOOS $/pos |")
    summary_md.append("|---|---:|---:|---:|---:|---:|---:|")
    for dir_label in DIRS:
        base_is = next((x for x in results if x.get("dir") == dir_label
                        and x.get("variant") == "baseline" and x.get("window") == "is"), None)
        h32_is = next((x for x in results if x.get("dir") == dir_label
                       and x.get("variant") == "h32_sizing" and x.get("window") == "is"), None)
        base_oos = next((x for x in results if x.get("dir") == dir_label
                         and x.get("variant") == "baseline" and x.get("window") == "oos"), None)
        h32_oos = next((x for x in results if x.get("dir") == dir_label
                        and x.get("variant") == "h32_sizing" and x.get("window") == "oos"), None)
        if not all([base_is, h32_is, base_oos, h32_oos]):
            summary_md.append(f"| {dir_label} | — | — | — | — | — | — |")
            continue
        d_is_pnl = h32_is['pnl_usd'] - base_is['pnl_usd']
        d_is_pos = h32_is['positions'] - base_is['positions']
        d_is_pps = h32_is['avg_pnl_per_pos'] - base_is['avg_pnl_per_pos']
        d_oos_pnl = h32_oos['pnl_usd'] - base_oos['pnl_usd']
        d_oos_pos = h32_oos['positions'] - base_oos['positions']
        d_oos_pps = h32_oos['avg_pnl_per_pos'] - base_oos['avg_pnl_per_pos']
        summary_md.append(
            f"| {dir_label} | ${d_is_pnl:+.2f} | {d_is_pos:+d} | ${d_is_pps:+.2f} | "
            f"${d_oos_pnl:+.2f} | {d_oos_pos:+d} | ${d_oos_pps:+.2f} |"
        )

    (OUT_ROOT / "full_results.json").write_text(json.dumps(results, indent=2, default=str))
    (OUT_ROOT / "summary.md").write_text("\n".join(summary_md))
    print(f"\nH3.2 sizing A/B sweep complete: {len(results)} runs")
    print(f"Output: {OUT_ROOT}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    main()
