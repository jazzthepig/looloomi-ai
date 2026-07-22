"""
Empirical-Grid Gate — freqtrade-compatible wrapper around `src/research/strategies/edge_gate.py`.

DROPPED IN 2026-07-18 by Minimax-B (Austin) — this is the **freqtrade parity** of the
Nautilus LS v1 empirical-grid gate drop-in (`reports/EMPIRICAL_GRID_DROP_IN_2026-07-18.md`).

WHY THIS EXISTS
  §ASSIGNMENTS 2026-07-06 (Minimax-B/C P0/C1): the empirical-grid gate replaces the
  hand-tuned `REGIME_CIS_FLOOR` across both engines. Nautilus LS v1 (B1) is done;
  freqtrade V-family parity (C1) needs the same gate accessible from a freqtrade
  strategy. This module is the bridge.

WHAT IT DOES
  Loads two JSON artifacts once (at strategy startup):
    - `reports/edge_gate_grid.json`        — shrunk edge-map grid (4 tiers × 19 cells, K=184.5)
    - `reports/btc_band_snapshot.json`     — daily BTC trailing-30d-bucketed band labels

  Exposes a single function `gate_passes(tier, band, side) -> EdgeDecision` that
  any freqtrade strategy can call from `confirm_trade_entry` or `populate_entry_trend`.
  Same call signature as the Nautilus wire-up → true parity between engines.

USAGE (from a freqtrade strategy — Minimax-C applies):
    from src.research.freqtrade.empirical_grid_gate import EmpiricalGridGate

    class SwingOverlayV14(Strategy):
        def __init__(self, config: dict) -> None:
            super().__init__(config)
            # Empirical-grid gate (Phase B drop-in, optional via env var)
            if os.getenv("FT_USE_EMPIRICAL_GRID_GATE", "0") == "1":
                self._grid_gate = EmpiricalGridGate(
                    grid_path="reports/edge_gate_grid.json",
                    band_snapshot_path="reports/btc_band_snapshot.json",
                )
            else:
                self._grid_gate = None

        def confirm_trade_entry(self, pair, order_type, amount, rate, time_in_force,
                                current_time, entry_tag, side, **kwargs):
            if self._grid_gate is None:
                return True
            tier = self._cis_signal_tier(pair, current_time)  # from cis_scores_latest.json
            band = self._grid_gate.band_for_date(current_time)
            side_str = "SHORT" if side == "short" else "LONG"
            decision = self._grid_gate.gate_passes(tier, band, side_str)
            if not decision.allow:
                logger.info(f"[emp-grid] BLOCKED {pair} {side_str}: {decision.reason}")
                return False
            return True

PARITY CONTRACT (per §STRATEGY-REVIVE reply addendum, B-S1 acceptance gate):
  - Both engines load the SAME grid JSON.
  - Both engines load the SAME band snapshot JSON.
  - Both engines call `gate(grid, tier, band, side)` with identical args.
  - Differences in decision must come from ENGINE-INTRINSIC reasons (data shape,
    fill timing, slippage) — not from gate logic. The shared `gate()` makes
  engine-intrinsic differences the ONLY source of parity drift.

ENV VARS (parity with Nautilus `LSV1_USE_EMPIRICAL_GRID_GATE=1`)
  - FT_USE_EMPIRICAL_GRID_GATE  (default 0)  — set to "1" to enable
  - FT_EMPIRICAL_GRID_PATH      (default reports/edge_gate_grid.json)
  - FT_BAND_SNAPSHOT_PATH       (default reports/btc_band_snapshot.json)
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

# Engine-agnostic gate logic lives in src/research/strategies/edge_gate.py.
# Make it importable regardless of where this module is invoked from.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.research.strategies.edge_gate import (  # noqa: E402
    EdgeDecision,
    gate,
    size_multiplier,
)


# ── Public API ───────────────────────────────────────────────────────────────

@dataclass
class EmpiricalGridGate:
    """Freqtrade-compatible wrapper for the empirical-grid edge gate.

    Loads the grid + band snapshot at construction; subsequent calls are
    O(1) dict lookups. Same interface contract as the Nautilus wire-up
    (`src/research/nautilus/ls_v1/strategy.py:_empirical_grid_passes`).

    Attributes:
        grid:           shrunk edge-map grid (dict-of-dict).
        band_by_date:   {date_str: band} where band ∈ {1_deep_off, 2_off, 3_neutral, 4_on, 5_deep_on}.
        min_edge:       minimum |alpha %| to count as actionable edge (default 1.0).
    """

    grid: dict
    band_by_date: dict
    min_edge: float = 1.0

    @classmethod
    def from_env(
        cls,
        grid_path: Optional[str] = None,
        band_snapshot_path: Optional[str] = None,
        min_edge: float = 1.0,
    ) -> "EmpiricalGridGate":
        """Construct from env vars (parity with Nautilus LSV1_GRID_PATH / LSV1_BAND_SNAPSHOT_PATH).

        Default paths match the canonical reports/ locations; override with env vars
        FT_EMPIRICAL_GRID_PATH and FT_BAND_SNAPSHOT_PATH.
        """
        grid_p = Path(grid_path or os.getenv(
            "FT_EMPIRICAL_GRID_PATH",
            "reports/edge_gate_grid.json",
        ))
        band_p = Path(band_snapshot_path or os.getenv(
            "FT_BAND_SNAPSHOT_PATH",
            "reports/btc_band_snapshot.json",
        ))
        return cls.from_paths(grid_p, band_p, min_edge=min_edge)

    @classmethod
    def from_paths(
        cls,
        grid_path: Path,
        band_snapshot_path: Path,
        min_edge: float = 1.0,
    ) -> "EmpiricalGridGate":
        """Load grid + band snapshot from explicit paths (test-friendly)."""
        grid_data = json.loads(Path(grid_path).read_text())
        grid = grid_data.get("grid", grid_data)
        band_data = json.loads(Path(band_snapshot_path).read_text())
        bands = band_data.get("bands", band_data)
        return cls(grid=grid, band_by_date=bands, min_edge=min_edge)

    def band_for_date(self, ts) -> str:
        """Map a timestamp (datetime, pd.Timestamp, str, or epoch-s) to today's BTC band.

        Falls back to '3_neutral' if the date is missing from the snapshot
        (defensive — same fall-through as Nautilus `_current_band()`).
        """
        if isinstance(ts, (int, float)):
            # epoch seconds
            d = datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d")
        elif isinstance(ts, str):
            d = ts[:10]
        else:
            # datetime or pd.Timestamp
            d = ts.strftime("%Y-%m-%d")
        return self.band_by_date.get(d, "3_neutral")

    def gate_passes(self, tier: str, band: str, side: str) -> EdgeDecision:
        """The one-line gate call. Same semantics as the Nautilus `_empirical_grid_passes`."""
        return gate(self.grid, tier, band, side, min_edge=self.min_edge)

    def size_for(self, decision: EdgeDecision) -> float:
        """Conviction → position size multiplier (Millennium soft sizing)."""
        return size_multiplier(decision)


# ── Module-level convenience (matches Nautilus one-liner style) ───────────────

_GATE_SINGLETON: Optional[EmpiricalGridGate] = None


def get_gate() -> EmpiricalGridGate:
    """Lazy singleton — the strategy calls this once and caches the result."""
    global _GATE_SINGLETON
    if _GATE_SINGLETON is None:
        _GATE_SINGLETON = EmpiricalGridGate.from_env()
    return _GATE_SINGLETON


def gate_passes(tier: str, band: str, side: str) -> EdgeDecision:
    """One-shot call without explicit gate construction (matches `empirical_gate(...)`
    in Nautilus LS v1). Uses the lazy singleton; the strategy should call `get_gate()`
    once at startup if it wants to pre-load."""
    return get_gate().gate_passes(tier, band, side)


def band_for_date(ts) -> str:
    """One-shot band lookup using the lazy singleton."""
    return get_gate().band_for_date(ts)


__all__ = [
    "EmpiricalGridGate",
    "EdgeDecision",
    "gate",
    "size_multiplier",
    "gate_passes",
    "band_for_date",
    "get_gate",
]
