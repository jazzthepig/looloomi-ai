"""
H2b — Per-Regime CIS Gate Direction A/B (Seth, 2026-07-10)
============================================================

Applies the H2a finding (genuine reversal in 3/5 regimes at 7d) to the LS v1
Nautilus gate. A/B tests:

    A: baseline (current LS v1 — all regimes use "high" direction)
    B: H2a direction table (Risk-Off, Risk-On, Stagflation → "inverted")
    C: baseline + H3.2 sizing (cap=1.75)
    D: H2a direction table + H3.2 sizing

Each on IS (2025-05-03 → 2025-12-31) and OOS (2026-01-01 → 2026-03-12) windows.
Total: 4 variants × 2 windows × 3 instruments = 24 Nautilus backtests (8 unique configs × 3 instruments).

Reuses the existing h2_floor_calibration.py infrastructure (nautilus_runner,
per_instrument.json, summary.json). Driver is run via:

    python3 -m src.research.cis_regime_studies.h2b_regime_direction_ab

Output: reports/h2b_regime_direction/<date>/ with summary.json, summary.md, per-variant raw results.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# Make the cis_regime_studies common helpers importable
THIS_DIR = Path(__file__).parent
sys.path.insert(0, str(THIS_DIR))

from common.nautilus_runner import run_with_config, summarise_run  # noqa: E402


logger = logging.getLogger(__name__)


# ── Defaults (mirror h2_floor_calibration.py) ───────────────────────────────

# Walk-forward windows — must match the freqtrade LS V4 baseline + H2 sweep.
DEFAULT_START_IS = "2025-05-03T00:00:00Z"
DEFAULT_END_IS = "2025-12-31T00:00:00Z"
DEFAULT_START_OOS = "2026-01-01T00:00:00Z"
DEFAULT_END_OOS = "2026-03-12T00:00:00Z"

# Default CIS history dir (env-overridable for H1.5 smoothed-label re-runs)
DEFAULT_CIS_HISTORY_DIR = os.getenv(
    "H2B_CIS_HISTORY_DIR",
    "/Volumes/CometCloudAI/cometcloud-local/_data/cis_history/",
)

REPORTS_DIR = Path(os.getenv("REPORTS_DIR", "reports"))


# ── The H2a direction table (single source of truth) ────────────────────────
# Mirror of src/research/nautilus/ls_v1/strategy.py:DEFAULT_PER_REGIME_DIRECTION_H2A
# — kept here too so the driver is self-contained for inspection. If the
# strategy module changes, update both. The strategy always uses ITS table
# (the H2b driver doesn't override the per-regime dict; it just toggles the flag).
H2A_DIRECTION_TABLE = {
    "Tightening":  "high",
    "Easing":      "high",
    "Risk-Off":    "inverted",
    "Risk-On":     "inverted",
    "Stagflation": "inverted",
    "Neutral":     "high",
    "Goldilocks":  "high",
}


# ── Variants (the A/B matrix) ──────────────────────────────────────────────
# A = baseline (current production behaviour — all "high")
# B = H2a direction table (the new wire-up)
# C = baseline + H3.2 sizing (so we can diff-in-diff the H3.2 lever)
# D = H2a + H3.2 (the combined-gate preview, also for Phase C prep)

VARIANTS = [
    {
        "label": "A_baseline",
        "use_h2_direction": False,
        "use_h32_sizing": False,
        "description": "Baseline: current LS v1 production (all 'high' direction, no H3.2).",
    },
    {
        "label": "B_h2a_direction",
        "use_h2_direction": True,
        "use_h32_sizing": False,
        "description": "H2a direction table applied (Risk-Off/Risk-On/Stagflation → inverted).",
    },
    {
        "label": "C_baseline_h32",
        "use_h2_direction": False,
        "use_h32_sizing": True,
        "description": "Baseline + H3.2 conviction-weighted sizing (cap=1.75).",
    },
    {
        "label": "D_h2a_h32",
        "use_h2_direction": True,
        "use_h32_sizing": True,
        "description": "H2a direction table + H3.2 sizing (preview of combined gate).",
    },
]


# ── Sweep driver ───────────────────────────────────────────────────────────

def run_sweep(
    skip_existing: bool = True,
    out_dir: Optional[Path] = None,
    cis_history_dir: Optional[str] = None,
) -> dict:
    """Run the 4-variant × 2-window H2b sweep. Returns aggregated results."""
    cis_history_dir = cis_history_dir or DEFAULT_CIS_HISTORY_DIR
    date_tag = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_dir = Path(out_dir) if out_dir else REPORTS_DIR / "h2b_regime_direction" / date_tag
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = out_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    # Persist the run config for reproducibility
    (out_dir / "sweep_config.json").write_text(json.dumps({
        "cis_history_dir": cis_history_dir,
        "variants": VARIANTS,
        "h2a_direction_table": H2A_DIRECTION_TABLE,
        "windows": {
            "is": (DEFAULT_START_IS, DEFAULT_END_IS),
            "oos": (DEFAULT_START_OOS, DEFAULT_END_OOS),
        },
        "n_variants": len(VARIANTS),
        "n_windows": 2,
        "n_total_runs": len(VARIANTS) * 2,
    }, indent=2))

    # Window tuples
    windows = [
        ("is", DEFAULT_START_IS, DEFAULT_END_IS),
        ("oos", DEFAULT_START_OOS, DEFAULT_END_OOS),
    ]

    runs: dict[str, dict] = {}
    n_done = 0
    n_total = len(VARIANTS) * len(windows)
    started = time.monotonic()

    for variant in VARIANTS:
        label = variant["label"]
        runs[label] = {"config": variant}
        for win_name, start, end in windows:
            cache_path = raw_dir / f"{label}__{win_name}.json"
            if skip_existing and cache_path.exists():
                runs[label][win_name] = json.loads(cache_path.read_text())
                logger.info(f"  [cached] {label} [{win_name}]")
                n_done += 1
                continue

            n_done += 1
            logger.info(f"  [{n_done}/{n_total}] {label} [{win_name}]")
            try:
                extra_env = {
                    "NAUTILUS_LS_V1_START": start,
                    "NAUTILUS_LS_V1_END": end,
                    "CIS_HISTORY_DIR": cis_history_dir,
                    "LSV1_USE_H2_DIRECTION": "1" if variant["use_h2_direction"] else "0",
                    "LSV1_USE_H32_SIZING": "1" if variant["use_h32_sizing"] else "0",
                    "LSV1_H32_SIZE_FLOOR": "0.5",
                    "LSV1_H32_SIZE_CAP": "1.75",
                }
                # Note: gate_directions is empty here because the H2a table is
                # applied via the strategy's `use_h2_direction` flag + the
                # DEFAULT_PER_REGIME_DIRECTION_H2A table inside the strategy.
                # For Variant A (baseline), we explicitly set "high" via env
                # so the behaviour is exactly the legacy default.
                if not variant["use_h2_direction"]:
                    for regime in H2A_DIRECTION_TABLE:
                        env_key = f"LSV1_GATE_DIRECTION_{regime.upper().replace('-', '_')}"
                        extra_env[env_key] = "high"

                result = run_with_config(
                    gate_directions={},  # env vars carry the direction
                    out_dir=out_dir / f"runs_{win_name}",
                    extra_env=extra_env,
                )
                summary = summarise_run(result)
                # Also stash the per-instrument detail for downstream analysis
                summary["per_instrument"] = result["per_instrument"]
                summary["skip_summary"] = result["skip_summary"]
                runs[label][win_name] = summary
                cache_path.write_text(json.dumps(summary, indent=2, default=str))
            except Exception as exc:  # noqa: BLE001
                logger.error(f"    FAIL: {exc!r}")
                runs[label][win_name] = {"error": repr(exc)}

    elapsed = round(time.monotonic() - started, 2)

    # Aggregate comparison table
    comparison = _build_comparison(runs)
    (out_dir / "full_results.json").write_text(json.dumps(runs, indent=2, default=str))
    (out_dir / "comparison.json").write_text(json.dumps(comparison, indent=2, default=str))
    (out_dir / "summary.md").write_text(_render_markdown(runs, comparison, elapsed))
    (out_dir / "summary.json").write_text(json.dumps({
        "elapsed_sec": elapsed,
        "n_runs": n_total,
        "n_succeeded": sum(
            1 for v in runs.values()
            for w in ("is", "oos")
            if w in v and "error" not in v[w]
        ),
        "n_failed": sum(
            1 for v in runs.values()
            for w in ("is", "oos")
            if w in v and "error" in v[w]
        ),
        "variants": [v["label"] for v in VARIANTS],
        "out_dir": str(out_dir),
    }, indent=2, default=str))

    logger.info(f"\nwrote {out_dir}/")
    logger.info(f"  full_results.json ({n_total} runs)")
    logger.info(f"  comparison.json")
    logger.info(f"  summary.md")
    logger.info(f"  elapsed: {elapsed}s")
    return {"runs": runs, "comparison": comparison, "out_dir": str(out_dir)}


# ── Aggregation helpers ────────────────────────────────────────────────────

def _safe_pnl(run: dict) -> float:
    pnl = run.get("pnl_usd")
    if pnl is None or (isinstance(pnl, float) and pnl != pnl):  # NaN check
        return 0.0
    try:
        return float(pnl)
    except (TypeError, ValueError):
        return 0.0


def _safe_orders(run: dict) -> int:
    n = run.get("n_orders", 0) or 0
    try:
        return int(n)
    except (TypeError, ValueError):
        return 0


def _build_comparison(runs: dict) -> dict:
    """Build the A/B comparison: B vs A, D vs A, D vs C.

    Output: {pair: {is: {pnl_delta, ...}, oos: {...}}}
    """
    pairs = [
        ("B_h2a_direction", "A_baseline", "h2a_vs_baseline"),
        ("D_h2a_h32",      "A_baseline", "h2a+h32_vs_baseline"),
        ("D_h2a_h32",      "C_baseline_h32", "h32_with_h2a_vs_h32_alone"),
        ("B_h2a_direction", "C_baseline_h32", "h2a_alone_vs_h32_alone"),
    ]
    out: dict = {}
    for new_l, base_l, key in pairs:
        out[key] = {}
        new_runs = runs.get(new_l, {})
        base_runs = runs.get(base_l, {})
        for win in ("is", "oos"):
            new_run = new_runs.get(win, {})
            base_run = base_runs.get(win, {})
            new_pnl = _safe_pnl(new_run)
            base_pnl = _safe_pnl(base_run)
            new_orders = _safe_orders(new_run)
            base_orders = _safe_orders(base_run)
            out[key][win] = {
                "new_label": new_l,
                "base_label": base_l,
                "new_pnl_usd": new_pnl,
                "base_pnl_usd": base_pnl,
                "pnl_delta_usd": round(new_pnl - base_pnl, 2),
                "pnl_pct_change": round(
                    100.0 * (new_pnl - base_pnl) / max(abs(base_pnl), 1.0), 2
                ),
                "new_orders": new_orders,
                "base_orders": base_orders,
                "order_delta": new_orders - base_orders,
            }
    return out


def _render_markdown(runs: dict, comparison: dict, elapsed: float) -> str:
    """Render the H2b A/B summary as markdown."""
    rows = []
    for v in VARIANTS:
        label = v["label"]
        r = runs.get(label, {})
        is_r = r.get("is", {})
        oos_r = r.get("oos", {})
        rows.append({
            "label": label,
            "use_h2_direction": v["use_h2_direction"],
            "use_h32_sizing": v["use_h32_sizing"],
            "is_pnl": _safe_pnl(is_r),
            "is_orders": _safe_orders(is_r),
            "oos_pnl": _safe_pnl(oos_r),
            "oos_orders": _safe_orders(oos_r),
        })

    md = []
    md.append(f"# H2b — Per-Regime Direction A/B (Nautilus LS v1, 2026-07-10)\n")
    md.append("**H2a finding (genuine reversal in 3/5 regimes at 7d) → applied to LS v1 gate.**\n")
    md.append(f"_Elapsed: {elapsed}s_\n")
    md.append("\n## A/B matrix (4 variants × 2 windows = 8 configs)\n")
    md.append("| variant | H2a dir | H3.2 sizing | IS PnL ($) | IS orders | OOS PnL ($) | OOS orders |")
    md.append("|---|:---:|:---:|---:|---:|---:|---:|")
    for r in rows:
        md.append(
            f"| `{r['label']}` | {'✓' if r['use_h2_direction'] else '·'} | "
            f"{'✓' if r['use_h32_sizing'] else '·'} | "
            f"{r['is_pnl']:+.2f} | {r['is_orders']} | "
            f"{r['oos_pnl']:+.2f} | {r['oos_orders']} |"
        )

    md.append("\n## Pairwise comparisons\n")
    md.append("| comparison | window | base PnL | new PnL | Δ $ | Δ % | Δ orders |")
    md.append("|---|---|---:|---:|---:|---:|---:|")
    for pair_key, win_results in comparison.items():
        for win, d in win_results.items():
            md.append(
                f"| `{pair_key}` | {win} | "
                f"{d['base_pnl_usd']:+.2f} | {d['new_pnl_usd']:+.2f} | "
                f"{d['pnl_delta_usd']:+.2f} | {d['pnl_pct_change']:+.1f}% | "
                f"{d['order_delta']:+d} |"
            )

    md.append("\n## Interpretation guide\n")
    md.append("- **B vs A** = pure H2a direction effect (no H3.2)")
    md.append("- **D vs A** = H2a + H3.2 stacked (Phase C preview)")
    md.append("- **D vs C** = H2a direction effect, controlling for H3.2")
    md.append("- **B vs C** = direction alone vs sizing alone (which lever is bigger?)")
    md.append("\n### Pass criteria (from H2_DIRECTION_TABLE §5)")
    md.append("1. IS Δ ≥ +$100 across 3 instruments (sum)")
    md.append("2. OOS Δ ≥ +$10 across 3 instruments")
    md.append("3. OOS Sharpe not worse (Δ ≥ -0.05)")
    md.append("4. Trade count not collapse (n_orders ≥ 50% of baseline)")
    md.append("\n### Stop rules")
    md.append("- ❌ Direction flip hurts OOS by > 25% on either reversal regime")
    md.append("- ❌ Inversion adds zero-edge trades (high DD, low win rate)")
    md.append("- ❌ Improvement is IS-only, OOS collapses")

    md.append("\n## Per-variant configuration\n")
    for v in VARIANTS:
        md.append(f"\n### `{v['label']}`\n")
        md.append(f"- description: {v['description']}")
        md.append(f"- use_h2_direction: `{v['use_h2_direction']}`")
        md.append(f"- use_h32_sizing: `{v['use_h32_sizing']}`")

    md.append("\n## H2a direction table (single source of truth)\n")
    md.append("```python")
    md.append("H2A_DIRECTION_TABLE = " + repr(H2A_DIRECTION_TABLE))
    md.append("```\n")
    md.append("Mirrors `src/research/nautilus/ls_v1/strategy.py:DEFAULT_PER_REGIME_DIRECTION_H2A`.")

    md.append("\n## Citations\n")
    md.append("- H2a (the finding): `reports/H2A_RELATIVE_IC_2026-07-10.md`")
    md.append("- H2 design (the framework): `docs/H2_REGIME_GATE_DESIGN_2026-07-06.md`")
    md.append("- H2a table (this dir): `docs/H2_REGIME_DIRECTION_TABLE_2026-07-10.md`")
    md.append("- Reused infra: `src/research/cis_regime_studies/common/nautilus_runner.py`")
    md.append("- H2 sweep (parent driver, similar pattern): `src/research/cis_regime_studies/h2_floor_calibration.py`")
    return "\n".join(md) + "\n"


# ── CLI ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    import argparse
    parser = argparse.ArgumentParser(description="H2b per-regime direction A/B sweep")
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--no-skip-existing", action="store_true",
                        help="Re-run all configs even if cached")
    parser.add_argument("--cis-history-dir", type=str, default=None)
    args = parser.parse_args()

    result = run_sweep(
        skip_existing=not args.no_skip_existing,
        out_dir=args.out_dir,
        cis_history_dir=args.cis_history_dir,
    )
    print(f"\nH2b sweep complete → {result['out_dir']}")
