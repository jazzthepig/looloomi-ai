"""
Thin wrapper to run the Nautilus LS v1 backtest with custom gate config (Seth, 2026-07-06)
=============================================================================================

Lets H2 / H3 sweep regimes by setting env vars (LSV1_GATE_DIRECTION_<REGIMENAME>=high|inverted|drop)
and reading structured output (per_instrument.json, summary.json, skip_summary.json) without
duplicating the Nautilus runner.

Public surface:
    run_with_config(gate_directions: dict[str, str], out_dir: Path | None = None,
                   instrument_subset: list[str] | None = None) -> dict
        Returns aggregated metrics: per-instrument + summary (PnL, orders, positions,
        max DD, sharpe — all from Nautilus result).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional


# ── Default paths (env-overridable) ──────────────────────────────────────────

DEFAULT_NAUTILUS_OUT_DIR = Path(
    os.getenv("NAUTILUS_LS_V1_OUT_DIR", "/tmp/ls_v1_h2_sweep")
)


def run_with_config(
    gate_directions: dict[str, str],
    out_dir: Optional[Path] = None,
    instrument_subset: Optional[list[str]] = None,
    extra_env: Optional[dict[str, str]] = None,
) -> dict:
    """Run the Nautilus LS v1 backtest with the given gate config.

    gate_directions: maps regime name (e.g. "Risk-Off", "Tightening") to
                     "high" | "inverted" | "drop".  The wrapper sets the
                     matching LSV1_GATE_DIRECTION_<REGIME> env vars and then
                     invokes the runner as a subprocess.

    Returns: dict with per-instrument + summary metrics.
    """
    out_dir = Path(out_dir) if out_dir else DEFAULT_NAUTILUS_OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    for regime, direction in gate_directions.items():
        key = f"LSV1_GATE_DIRECTION_{regime.upper().replace('-', '_')}"
        env[key] = direction
    if extra_env:
        env.update(extra_env)

    # Use a unique subdirectory so multiple sweeps don't overwrite
    import time
    sub_dir = out_dir / f"run_{int(time.time() * 1000)}"
    sub_dir.mkdir(parents=True, exist_ok=True)
    env["NAUTILUS_LS_V1_OUT_DIR"] = str(sub_dir)
    # Make sure CIS_HISTORY_DIR is inherited if user set it before
    # importing this module (env was copied above so already there).

    # Invoke the existing Nautilus runner as a subprocess — cleanest way to
    # avoid Nautilus's BacktestNode reusing state from a prior call in the
    # same Python process.
    cmd = [sys.executable, "-m", "src.research.nautilus.ls_v1.runner"]
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=300)

    # Read the structured output
    run_dir = sorted(sub_dir.glob("run_*"))[-1]
    per_inst = json.loads((run_dir / "per_instrument.json").read_text())
    summary = json.loads((run_dir / "summary.json").read_text())
    skip = json.loads((run_dir / "skip_summary.json").read_text())

    # Filter instruments if asked
    if instrument_subset:
        wanted = set(instrument_subset)
        per_inst = [r for r in per_inst if r.get("instrument") in wanted]

    return {
        "per_instrument": per_inst,
        "summary": summary,
        "skip_summary": skip,
        "out_dir": str(run_dir),
        "config": {"gate_directions": gate_directions, "extra_env": extra_env or {}},
        "subprocess_rc": proc.returncode,
        "subprocess_stderr_tail": proc.stderr[-500:] if proc.returncode != 0 else "",
    }


# ── Helpers for sweeps ───────────────────────────────────────────────────────

def _aggregate_pnl(per_inst: list[dict]) -> float:
    """Sum 'PnL (total)' across per_instrument rows."""
    total = 0.0
    for row in per_inst:
        pnl_dict = row.get("stats_pnls_USD", {}) or {}
        p = pnl_dict.get("PnL (total)")
        if p is not None:
            try:
                total += float(p)
            except (TypeError, ValueError):
                pass
    return total


def _aggregate_orders(per_inst: list[dict]) -> int:
    return sum(int(r.get("n_orders", 0) or 0) for r in per_inst)


def _aggregate_positions(per_inst: list[dict]) -> int:
    return sum(int(r.get("n_positions", 0) or 0) for r in per_inst)


def _aggregate_realized_pnls(per_inst: list[dict]) -> list[float]:
    """Collect realised PnLs across positions per instrument.

    Nautilus doesn't expose per-position PnL in the per_instrument.json output
    by default; this is best-effort, returning empty list if not available.
    """
    pnls: list[float] = []
    for row in per_inst:
        positions = row.get("positions") or []
        for p in positions:
            try:
                pnls.append(float(p.get("realized_pnl", 0)))
            except (TypeError, ValueError):
                continue
    return pnls


def summarise_run(result: dict) -> dict:
    """Compact summary metrics from a `run_with_config` result."""
    realised = _aggregate_realized_pnls(result["per_instrument"])
    return {
        "n_orders": _aggregate_orders(result["per_instrument"]),
        "n_positions": _aggregate_positions(result["per_instrument"]),
        "pnl_usd": round(_aggregate_pnl(result["per_instrument"]), 2),
        "pnl_per_trade": realised,
        "config": result["config"],
    }