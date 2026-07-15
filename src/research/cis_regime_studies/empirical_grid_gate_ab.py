"""
Phase B — Empirical-Grid Edge Gate A/B (Minimax-B, 2026-07-14)
================================================================

Wires the empirical-grid shrunk-alpha gate (K=184.5 Empirical-Bayes shrinkage,
4 tiers × 5 risk bands = 19 cells) into LS v1 and A/B tests it against the
current production gate (REGIME_CIS_FLOOR table).

Three variants:
    A: baseline (current LS v1 — REGIME_CIS_FLOOR, no grid)
    B: empirical-grid gate ONLY (replaces REGIME_CIS_FLOOR with shrunk-alpha
        per (tier × band); no size scaling on top)
    C: empirical-grid gate + size_multiplier (the user's Phase B ship target —
        gate shrinks/caps `trade_size` based on grid conviction, defaults
        [0.4, 1.3] — conservative sizing on weak-edge cells, capped on strong)

Each on IS (2025-05-03 → 2025-12-31) and OOS (2026-01-01 → 2026-03-12) windows.
Total: 3 variants × 2 windows × 3 instruments = 18 Nautilus backtests
(6 unique configs × 3 instruments).

Reuses the existing common/nautilus_runner.py infrastructure.

Driver is run via:
    python3 -m src.research.cis_regime_studies.empirical_grid_gate_ab

Output: reports/empirical_grid_gate/<date>/ with summary.json, summary.md,
per-variant raw results.
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


# ── Defaults (mirror h2_floor_calibration.py + h2b_regime_direction_ab.py) ──

# Walk-forward windows — must match the freqtrade LS V4 baseline + H2 sweep.
DEFAULT_START_IS = "2025-05-03T00:00:00Z"
DEFAULT_END_IS = "2025-12-31T00:00:00Z"
DEFAULT_START_OOS = "2026-01-01T00:00:00Z"
DEFAULT_END_OOS = "2026-03-12T00:00:00Z"

# Default CIS history dir (env-overridable for H1.5 smoothed-label re-runs)
DEFAULT_CIS_HISTORY_DIR = os.getenv(
    "PHASEB_CIS_HISTORY_DIR",
    "/Volumes/CometCloudAI/cometcloud-local/_data/cis_history/",
)

# Artifact paths — must match scripts/build_btc_band_snapshot.py output
DEFAULT_GRID_PATH = os.getenv(
    "PHASEB_GRID_PATH",
    "reports/edge_gate_grid.json",
)
DEFAULT_BAND_PATH = os.getenv(
    "PHASEB_BAND_PATH",
    "reports/btc_band_snapshot.json",
)

# Size scaling defaults for Variant C — chosen to be conservative on the
# downside (cap at 1.3x baseline, not the 1.5x H3.2 default) because the
# empirical grid is a NEW signal source we're shipping for the first time.
DEFAULT_SIZE_FLOOR = "0.4"
DEFAULT_SIZE_CAP = "1.3"

REPORTS_DIR = Path(os.getenv("REPORTS_DIR", "reports"))


# ── Variants (the A/B matrix) ──────────────────────────────────────────────
# A = baseline (current production behaviour — REGIME_CIS_FLOOR table only)
# B = empirical-grid gate ONLY (no size scaling) — pure gate-replacement test
# C = empirical-grid gate + size_multiplier (the user's Phase B ship target)

VARIANTS = [
    {
        "label": "A_baseline",
        "use_empirical_grid_gate": False,
        "use_grid_size_multiplier": False,
        "use_h32_sizing": False,
        "description": (
            "Baseline: current LS v1 production (REGIME_CIS_FLOOR table, "
            "no empirical-grid gate, no H3.2 sizing)."
        ),
    },
    {
        "label": "B_grid_gate_only",
        "use_empirical_grid_gate": True,
        "use_grid_size_multiplier": False,  # gate only, no size scaling
        "use_h32_sizing": False,
        "description": (
            "Empirical-grid gate ONLY (replaces REGIME_CIS_FLOOR with "
            "shrunk-alpha per (tier × band)). No size scaling — tests the "
            "gate replacement in isolation."
        ),
    },
    {
        "label": "C_grid_gate_plus_size",
        "use_empirical_grid_gate": True,
        "use_grid_size_multiplier": True,  # full Phase B ship target
        "use_h32_sizing": False,
        "description": (
            "Empirical-grid gate + size_multiplier (Phase B ship target). "
            f"Default range [{DEFAULT_SIZE_FLOOR}, {DEFAULT_SIZE_CAP}] — "
            "size shrinks on weak-edge cells, caps on strong-edge cells."
        ),
    },
]


# ── Sweep driver ───────────────────────────────────────────────────────────

def run_sweep(
    skip_existing: bool = True,
    out_dir: Optional[Path] = None,
    cis_history_dir: Optional[str] = None,
    grid_path: Optional[str] = None,
    band_path: Optional[str] = None,
) -> dict:
    """Run the 3-variant × 2-window Phase B sweep. Returns aggregated results.

    Artifacts (grid + band snapshot) must exist before running. If not, the
    script will surface a clear error rather than silently falling back.
    """
    cis_history_dir = cis_history_dir or DEFAULT_CIS_HISTORY_DIR
    grid_path = grid_path or DEFAULT_GRID_PATH
    band_path = band_path or DEFAULT_BAND_PATH

    # Pre-flight: artifacts must exist
    grid_p = Path(grid_path)
    band_p = Path(band_path)
    missing = []
    if not grid_p.exists():
        missing.append(f"grid: {grid_p}")
    if not band_p.exists():
        missing.append(f"band_snapshot: {band_p}")
    if missing:
        raise FileNotFoundError(
            "Phase B artifacts missing — build them first:\n"
            + "\n".join(f"  - {m}" for m in missing)
            + "\n\n  python3 scripts/build_btc_band_snapshot.py"
        )

    date_tag = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_dir = Path(out_dir) if out_dir else REPORTS_DIR / "empirical_grid_gate" / date_tag
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = out_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    # Persist the run config for reproducibility
    (out_dir / "sweep_config.json").write_text(json.dumps({
        "cis_history_dir": cis_history_dir,
        "grid_path": str(grid_p),
        "band_path": str(band_p),
        "variants": VARIANTS,
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
                    "LSV1_USE_EMPIRICAL_GRID_GATE": "1" if variant["use_empirical_grid_gate"] else "0",
                    "LSV1_USE_GRID_SIZE_MULTIPLIER": "1" if variant.get("use_grid_size_multiplier") else "0",
                    "LSV1_GRID_PATH": str(grid_p),
                    "LSV1_BAND_SNAPSHOT_PATH": str(band_p),
                    # H3.2 stays off for all Phase B variants — the grid
                    # size_multiplier is the sizing lever in Variant C.
                    "LSV1_USE_H32_SIZING": "0",
                    "LSV1_H32_SIZE_FLOOR": "0.5",
                    "LSV1_H32_SIZE_CAP": "1.5",
                }
                # Explicitly disable H2a direction for all variants — this
                # sweep is purely about the empirical-grid gate, not the
                # direction-flip lever (which falsified 2026-07-13 as R16).
                for regime in (
                    "TIGHTENING", "RISK_OFF", "RISK_ON", "STAGFLATION",
                    "EASING", "NEUTRAL", "GOLDILOCKS",
                ):
                    extra_env[f"LSV1_GATE_DIRECTION_{regime}"] = "high"

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
    """Build the A/B comparison pairs for the empirical-grid gate sweep.

    Pairs:
        - B vs A: pure gate-replacement effect (no size scaling)
        - C vs A: gate + size multiplier (the ship target)
        - C vs B: marginal value of the size multiplier on top of the gate

    Output: {pair: {is: {pnl_delta, ...}, oos: {...}}}
    """
    pairs = [
        ("B_grid_gate_only",     "A_baseline",          "grid_gate_vs_baseline"),
        ("C_grid_gate_plus_size","A_baseline",          "grid_gate+size_vs_baseline"),
        ("C_grid_gate_plus_size","B_grid_gate_only",     "size_multiplier_marginal"),
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
    """Render the Phase B A/B summary as markdown."""
    rows = []
    for v in VARIANTS:
        label = v["label"]
        r = runs.get(label, {})
        is_r = r.get("is", {})
        oos_r = r.get("oos", {})
        rows.append({
            "label": label,
            "use_grid_gate": v["use_empirical_grid_gate"],
            "use_grid_size": v.get("use_grid_size_multiplier", False),
            "is_pnl": _safe_pnl(is_r),
            "is_orders": _safe_orders(is_r),
            "oos_pnl": _safe_pnl(oos_r),
            "oos_orders": _safe_orders(oos_r),
        })

    md = []
    md.append("# Phase B — Empirical-Grid Edge Gate A/B (Nautilus LS v1, 2026-07-14)\n")
    md.append("**Empirical-Bayes shrunk-alpha grid (K=184.5, 4 tiers × 5 risk bands = 19 cells) "
              "wired into LS v1 gate + size_multiplier.**\n")
    md.append(f"_Elapsed: {elapsed}s_\n")
    md.append("\n## A/B matrix (3 variants × 2 windows = 6 configs)\n")
    md.append("| variant | grid gate | grid size | IS PnL ($) | IS orders | OOS PnL ($) | OOS orders |")
    md.append("|---|:---:|:---:|---:|---:|---:|---:|")
    for r in rows:
        md.append(
            f"| `{r['label']}` | {'✓' if r['use_grid_gate'] else '·'} | "
            f"{'✓' if r['use_grid_size'] else '·'} | "
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
    md.append("- **B vs A** = pure gate-replacement effect (grid shrinks α to a yes/no)")
    md.append("- **C vs A** = full Phase B (gate + size_multiplier [0.4, 1.3])")
    md.append("- **C vs B** = marginal value of the size multiplier on top of the gate")
    md.append("\n### Pass criteria (from H2 / Phase B spec)")
    md.append("1. IS Δ ≥ +$100 across 3 instruments (sum)")
    md.append("2. OOS Δ ≥ +$10 across 3 instruments")
    md.append("3. OOS trade count not collapse (n_orders ≥ 60% of baseline — gate is a filter, "
              "not a noise-amplifier)")
    md.append("4. No instrument-level PnL flip > -50% (variant must not crater any single book)")
    md.append("\n### Stop rules")
    md.append("- ❌ Grid gate crashes OOS by > 25% on either reversal regime (Risk-Off / Stagflation)")
    md.append("- ❌ Size multiplier turns small wins into losses (cap > 1.0 amplifies downside)")
    md.append("- ❌ Improvement is IS-only, OOS collapses")
    md.append("- ❌ Variant lets through zero-edge trades (high DD, low win rate per-trade)")

    md.append("\n## Per-variant configuration\n")
    for v in VARIANTS:
        md.append(f"\n### `{v['label']}`\n")
        md.append(f"- description: {v['description']}")
        md.append(f"- use_empirical_grid_gate: `{v['use_empirical_grid_gate']}`")
        md.append(f"- use_grid_size_multiplier: `{v.get('use_grid_size_multiplier', False)}` "
                  f"(Phase B ship-target flag — only on for Variant C)")
        md.append(f"- use_h32_sizing: `{v['use_h32_sizing']}` (Phase B does NOT enable H3.2; "
                  f"the grid size_multiplier is the sizing lever in Variant C)")

    md.append("\n## Artifacts\n")
    md.append(f"- Edge gate grid: `reports/edge_gate_grid.json` "
              f"(K={184.5} Empirical-Bayes shrinkage, 19 cells)")
    md.append(f"- BTC band snapshot: `reports/btc_band_snapshot.py` output → "
              f"`reports/btc_band_snapshot.json`")

    md.append("\n## Citations\n")
    md.append("- Strategy wire-up: `src/research/nautilus/ls_v1/strategy.py` "
              "(`_empirical_grid_passes` + `_current_band` + grid size branch in `create_order_qty`)")
    md.append("- Grid + size helper module: `src/research/strategies/edge_gate.py`")
    md.append("- BTC band builder: `scripts/build_btc_band_snapshot.py`")
    md.append("- R16 falsification (what we're NOT testing here): `reports/H2B_REGIME_DIRECTION_2026-07-13.md`")
    md.append("- Reused infra: `src/research/cis_regime_studies/common/nautilus_runner.py`")
    return "\n".join(md) + "\n"


# ── CLI ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    import argparse
    parser = argparse.ArgumentParser(description="Phase B empirical-grid edge gate A/B sweep")
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--no-skip-existing", action="store_true",
                        help="Re-run all configs even if cached")
    parser.add_argument("--cis-history-dir", type=str, default=None)
    parser.add_argument("--grid-path", type=str, default=None)
    parser.add_argument("--band-path", type=str, default=None)
    args = parser.parse_args()

    result = run_sweep(
        skip_existing=not args.no_skip_existing,
        out_dir=args.out_dir,
        cis_history_dir=args.cis_history_dir,
        grid_path=args.grid_path,
        band_path=args.band_path,
    )
    print(f"\nPhase B sweep complete → {result['out_dir']}")