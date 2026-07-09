"""
Edge gate — continuous per-trade expected-edge filter for Nautilus LS v1
(Seth, 2026-07-06 — H2 design §3 + H3 finding pivot)

REPLACES the discrete `REGIME_CIS_FLOOR` dict with a continuous edge measure:
    edge = side × IC_regime × z × sigma × sqrt(horizon) - cost
where:
    side      = +1 (long) | -1 (short)  — from EMA cross
    IC_regime = per-regime composite CIS 7d IC (from H1 sweep)
    z         = (asset CIS - regime peer mean) / regime peer std  (cross-sectional)
    sigma     = asset's recent realised vol in return units (ATR/price)
    horizon   = trade expected hold in days (default 1d)
    cost      = round-trip fee (default 0.001 = 0.1% taker per side)

WHY THIS REPLACES THE FLOOR:
    H1 sweep showed composite CIS IC flips sign by regime (positive in
    Tightening, negative in Risk-Off/Risk-On/Stagflation). The static
    `REGIME_CIS_FLOOR` map hard-codes "high CIS is good" for every regime
    — directionally wrong in 4 of 5 observed regimes.

    H3 prototype (gate-multiplier) failed because the floor band [50, 65]
    is too tight relative to BTC/ETH/SOL CIS scores [60-70] — even small
    multipliers move trade count ±90%.

    The edge gate is a continuous z-score threshold: it naturally flips
    direction by regime (since IC is signed) AND by side (long/short).
    No hard floor band, no manual direction-flip, no magic numbers.

USAGE (in Nautilus LS v1):
    gate = EdgeGate(per_regime_ic={"Risk-Off": -0.13, ...},
                    cost=0.001, horizon_days=1.0)
    if gate.passes(z=z, regime="Risk-Off", side=+1, sigma=0.02):
        # trade passes — expected edge > cost
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, Optional


# Default per-regime IC (7d, smoothed) — from H1.5 sweep
# 2026-07-06. Stagflation n=0 under smoothing, sourced from raw (n=195).
# Tightening n=72, flagged underpowered — value may be noise.
DEFAULT_PER_REGIME_IC: Dict[str, float] = {
    "Tightening":  -0.09,   # smoothed; underpowered (n=72)
    "Easing":      -0.13,   # smoothed
    "Risk-Off":    -0.13,   # smoothed
    "Risk-On":     -0.36,   # smoothed
    "Stagflation": -0.23,   # raw only; n=0 under smoothing
    "Neutral":     +0.05,   # default (noisy, never observed)
    "Goldilocks":  +0.10,   # default (never observed)
}


@dataclass(frozen=True)
class EdgeGate:
    """Continuous per-trade expected-edge gate.

    Replaces the discrete REGIME_CIS_FLOOR dict. The gate's sign comes
    from `side × IC_regime`: positive when the trade direction aligns
    with the regime's predictive signal, negative otherwise.
    """
    per_regime_ic: Dict[str, float] = field(default_factory=lambda: dict(DEFAULT_PER_REGIME_IC))
    cost: float = 0.001           # round-trip fee (Binance taker, 0.05% × 2)
    horizon_days: float = 1.0     # expected hold time
    neutral_ic: float = 0.0       # IC for unknown regimes (default: 0 = no signal)

    def ic_for(self, regime: str) -> float:
        """Lookup per-regime IC; fall back to neutral for unknown."""
        return self.per_regime_ic.get(regime, self.neutral_ic)

    def edge(
        self,
        *,
        z: float,
        regime: str,
        side: int,
        sigma: float,
    ) -> float:
        """Expected edge per unit risk. Positive = trade has positive EV.

        Formula:
            edge = side × IC × z × sigma × sqrt(horizon) - cost
        All inputs in z-score / return units. Result in return units.
        """
        ic = self.ic_for(regime)
        sqrt_h = math.sqrt(max(0.0, self.horizon_days))
        return (side * ic * z * sigma * sqrt_h) - self.cost

    def passes(self, *, z: float, regime: str, side: int, sigma: float) -> bool:
        """Decision: does this trade have positive expected edge?

        Edge gate: only PASSES if `side × IC × z × sigma × sqrt(horizon) > cost`.
        i.e., only when the asset's z-score aligns with the regime signal
        strongly enough to overcome the round-trip fee.

        For a long (side=+1) in a positive-IC regime, this requires z > 0
        (high CIS). In a negative-IC regime, it requires z < 0 (low CIS).
        For shorts, the sign of z flips. This naturally implements the
        regime-conditional reversal finding from H1.
        """
        if sigma <= 0.0:
            return False
        return self.edge(z=z, regime=regime, side=side, sigma=sigma) > 0.0


def compute_z_score(
    asset_cis: float,
    peer_cis_values: list[float],
) -> float:
    """Cross-sectional z-score for an asset vs its regime peers.

    Returns 0.0 if peers are missing or constant (no signal).
    """
    if not peer_cis_values or len(peer_cis_values) < 2:
        return 0.0
    n = len(peer_cis_values)
    mean = sum(peer_cis_values) / n
    var = sum((x - mean) ** 2 for x in peer_cis_values) / (n - 1)
    sd = var ** 0.5
    if sd <= 0:
        return 0.0
    return (asset_cis - mean) / sd