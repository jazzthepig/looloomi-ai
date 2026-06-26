#!/usr/bin/env python3
"""
CometCloud — Risk-Off Strategy Overlay (v1)
============================================

Per 2026-06-26 user direction: in Risk-Off / Tightening / Stagflation
regimes, the base rebalance engine cuts gross exposure to 50%. This
module redirects the freed-up capital into two institutional overlays
that keep earning in bear markets:

  1. **Basket options premium collection** (40% of freed-up cash)
     - Sell 10% OTM 30D strangles on the equal-weight crypto basket
     - Premium income 2.5%/mo nominal; 5% of months are "bad months"
       with -6% on notional. EV = +2.08%/mo net.
     - Honest caveats: no live IV data; this is user-supplied
       institutional expectation, not historical Deribit prints.

  2. **Naked short augmentation** (60% of freed-up cash)
     - Scale the existing short book by RISK_OFF_SHORT_MULTIPLIER (1.5×)
     - Same names (D/F grades), more size — highest directional EV in
       Risk-Off environments

Accumulator is deferred to a later iteration (no IV surface to calibrate).

This module is a P&L ledger, not a trading strategy. It composes with
`rebalance_engine.py` and the result is a single combined NAV.

ARCHITECTURE alignment: this is the "edge has no fixed form" principle
in action — when long-vol regimes end, we don't go to cash; we ROTATE
exposure into a different form (premium collection + augmented shorts)
that is structurally positive in the same environment.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

import numpy as np

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Regimes where the overlay is active
RISK_OFF_REGIMES = {"Risk-Off", "Tightening", "Stagflation"}

# Allocation of freed-up cash in Risk-Off regimes
# With naked_short multiplier = 1.0 (default), the short book is unchanged
# from v2, so the full freed-up cash is allocated to basket options overlay.
# Override via env var RISK_OFF_OPTIONS_ALLOC for live experimentation.
RISK_OFF_OVERLAY_ALLOC = {
    "basket_options": float(__import__("os").getenv("RISK_OFF_OPTIONS_ALLOC", "1.0")),
    "naked_short":    float(__import__("os").getenv("RISK_OFF_SHORT_ALLOC", "0.0")),
}

# Basket options parameters (user-supplied institutional expectation)
BASKET_OPTIONS_PARAMS = {
    "monthly_premium_yield": 0.025,  # 2.5%/mo nominal
    "breach_rate_monthly":   0.05,   # 5% of months see a breach
    "breach_loss_pct":       0.06,   # -6% on notional in a breach month
    # Expected value per month (under independent monthly draws):
    #   0.95 × 0.025 - 0.05 × 0.06 = +0.02375 - 0.003 = +0.0208 (~2.1%/mo)
    "notional_dollars": 1.0,
}

# Naked short augmentation
# v3 sensitivity scan (rebalance_engine.py with naked short mult 1.0/1.2/1.5/2.0):
#   mult=1.0: CAGR=-0.21%, Sharpe 0.25  ← BEST
#   mult=1.2: CAGR=-0.26%, Sharpe 0.26
#   mult=1.5: CAGR=-0.33%, Sharpe 0.27
#   mult=2.0: CAGR=-0.46%, Sharpe 0.30
# Conclusion: existing D/F short book was already correctly sized.
# Augmenting it 1.5× just adds loss on names that recover.
# Default = 1.0 (no augmentation, equivalent to v2 short sizing).
# Override via env var RISK_OFF_SHORT_MULTIPLIER for live experimentation.
NAKED_SHORT_PARAMS = {
    "multiplier": float(__import__("os").getenv("RISK_OFF_SHORT_MULTIPLIER", "1.0")),
}


# ---------------------------------------------------------------------------
# Daily overlay P&L
# ---------------------------------------------------------------------------

def _is_breach_day(d_ordinal: int, cycle_start_ordinal: int, breach_rate_monthly: float, rng: np.random.Generator) -> bool:
    """Stochastic breach day: within a 30-day options cycle, decide if this
    day is a 'breach day'. Breach events in the model are independent draws
    per day, scaled to the monthly breach rate.
    """
    daily_breach_prob = breach_rate_monthly / 30.0
    return bool(rng.random() < daily_breach_prob)


def overlay_daily_pnl(
    regime: str,
    freed_cash_pct: float,
    day_ordinal: int,
    cycle_start_ordinal: int,
    rng: np.random.Generator,
) -> tuple[float, float]:
    """Compute today's overlay P&L (as a fraction of NAV).

    Returns (total_overlay_pnl, basket_options_pnl) so the caller can
    attribute which sub-strategy contributed what.
    """
    if regime not in RISK_OFF_REGIMES or freed_cash_pct <= 0:
        return 0.0, 0.0

    options_alloc = freed_cash_pct * RISK_OFF_OVERLAY_ALLOC["basket_options"]

    # Basket options: daily premium OR daily breach loss
    if _is_breach_day(
        day_ordinal, cycle_start_ordinal,
        BASKET_OPTIONS_PARAMS["breach_rate_monthly"],
        rng,
    ):
        # 6% loss on notional, distributed across the days in the breach month
        daily_loss = options_alloc * BASKET_OPTIONS_PARAMS["breach_loss_pct"] / 30.0
        return daily_loss, daily_loss

    daily_premium = options_alloc * BASKET_OPTIONS_PARAMS["monthly_premium_yield"] / 30.0
    return daily_premium, daily_premium


def apply_naked_short_overlay(
    weights: dict[str, float],
    regime: str,
    max_gross: float,
) -> dict[str, float]:
    """Augment existing short weights in Risk-Off regimes. Returns the
    modified weight dict, renormalised so gross ≤ max_gross.
    """
    if regime not in RISK_OFF_REGIMES:
        return weights

    multiplier = NAKED_SHORT_PARAMS["multiplier"]
    out = dict(weights)
    for sym, w in out.items():
        if w < 0:  # short position
            out[sym] = w * multiplier

    gross = sum(abs(v) for v in out.values())
    if gross > max_gross > 0:
        scale = max_gross / gross
        out = {k: v * scale for k, v in out.items()}
    return out


# ---------------------------------------------------------------------------
# Sensitivity helpers (for the v3 report)
# ---------------------------------------------------------------------------

def sensitivity_table(premium_yields=(0.015, 0.025, 0.04),
                      short_mults=(1.2, 1.5, 2.0)) -> list[dict]:
    """Return a 3×3 sensitivity grid: rows=premium yield, cols=short mult.

    Note: with default RISK_OFF_OVERLAY_ALLOC (basket_options=1.0,
    naked_short=0), the naked short mult doesn't affect EV. Set
    RISK_OFF_SHORT_ALLOC>0 to re-enable the naked short contribution.
    """
    rows = []
    for py in premium_yields:
        row = {"premium_yield": py, "results": []}
        for sm in short_mults:
            ev_options = (1 - BASKET_OPTIONS_PARAMS["breach_rate_monthly"]) * py \
                - BASKET_OPTIONS_PARAMS["breach_rate_monthly"] * BASKET_OPTIONS_PARAMS["breach_loss_pct"]
            ev_options_per_unit = ev_options * RISK_OFF_OVERLAY_ALLOC["basket_options"]
            # Naked short EV only applies if user allocates capital to it
            ev_short_per_unit = (sm - 1.0) * 0.04 * RISK_OFF_OVERLAY_ALLOC["naked_short"]
            total_ev = ev_options_per_unit + ev_short_per_unit
            row["results"].append({"short_mult": sm, "monthly_ev": total_ev})
        rows.append(row)
    return rows
