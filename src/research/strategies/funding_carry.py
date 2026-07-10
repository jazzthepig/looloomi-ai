"""
Funding-carry sleeve — the delta-neutral lane we were missing (Seth, 2026-07-10).
=================================================================================

Context (see reports/STRATEGY_COMPETITIVENESS_2026-07-10.md):
  Our directional CIS bots lose to buy-and-hold — that lane is commodity and the
  whole OSS field is roughly at zero there. The edge the field actually monetizes
  is DELTA-NEUTRAL CARRY: collect the perpetual funding payment while holding zero
  net directional exposure. ~5–15% annualized in 2026 (compressed from 30–50% in
  2020–21), market-neutral, and — crucially for an LP/family-office — UNCORRELATED
  to crypto beta. That is what a fund-of-funds allocator actually wants.

Why this is safe to build (unlike the falsified edge gate):
  The edge here is MECHANICAL market structure, not a fitted prediction. When perp
  funding is positive, longs pay shorts every funding interval; a spot-long +
  perp-short position is delta-neutral and simply COLLECTS that payment. There is
  no directional forecast to overfit. The only things the harness must still prove
  are COST and CAPACITY realism (fees, borrow, slippage, funding mean-reversion) —
  not whether a signal "predicts." So this cannot be falsified the way an alpha
  claim can; it can only be shown uneconomic after costs.

Data:
  Reuses exactly what positioning.py already fetches — CoinGecko /derivatives
  funding_rate + open_interest per asset (Redis `cis:positioning`). No new source.

Compliance: this module produces internal research constructs (target weights for a
market-neutral sleeve), never user-facing buy/sell signals.

This is a FLOOR sleeve pending the OOS harness cost/capacity pass — NOT headlined
as validated. Wire nothing to capital until it clears.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# CoinGecko /derivatives reports funding_rate as a PERCENT for the current interval
# (e.g. 0.01 == 0.01%). Most venues settle funding every 8h → 3× per day.
_FUNDING_INTERVALS_PER_YEAR = 3 * 365          # 1095
_PCT_TO_FRAC = 0.01                             # CG funding_rate is in percent

# Sleeve construction defaults
_MIN_OI_USD = 10_000_000                        # only liquid perps carry real capacity
_MIN_ABS_CARRY_APR = 0.05                       # ignore names carrying < 5% APR (noise)
_MAX_NAME_FRAC = 0.20                           # cap any single leg at 20% of gross
_MAX_LEGS = 12


@dataclass(frozen=True)
class CarryLeg:
    """One delta-neutral leg of the carry basket."""
    symbol: str
    funding_pct_interval: float     # raw per-interval funding, percent (as CG reports)
    carry_apr: float                # annualized carry FRACTION (e.g. 0.18 == 18% APR)
    side: str                       # 'short_perp' (collect + funding) / 'long_perp' (collect − funding)
    oi_usd: float
    weight: float = 0.0             # fraction of sleeve gross allocated to this leg

    @property
    def structure(self) -> str:
        # Delta-neutral construction that COLLECTS the funding:
        #   positive funding → longs pay shorts → we SHORT perp, LONG spot
        #   negative funding → shorts pay longs → we LONG perp, SHORT spot
        return ("SHORT perp / LONG spot" if self.side == "short_perp"
                else "LONG perp / SHORT spot")


def annualize_funding(funding_pct_interval: float,
                      intervals_per_year: int = _FUNDING_INTERVALS_PER_YEAR) -> float:
    """Per-interval funding (in percent, as CG reports) → annualized carry FRACTION.

    Simple (linear) annualization — deliberately NOT compounded, because funding
    mean-reverts and compounding overstates a rate that won't persist a full year.
    The harness applies decay/mean-reversion haircuts; this is the gross headline.
    """
    return funding_pct_interval * _PCT_TO_FRAC * intervals_per_year


def _capped_weights(mags: list[float], cap: float) -> list[float]:
    """Proportional weights that sum to 1.0 with no single weight above `cap`.
    Water-fill: clamp over-cap names, redistribute remainder to the rest.
    Thin baskets deliberately under-deploy (sum < 1) rather than over-concentrate."""
    n = len(mags)
    if n == 0:
        return []
    total = sum(mags) or 1.0
    w = [m / total for m in mags]
    for _ in range(n):
        over = [i for i, x in enumerate(w) if x > cap + 1e-12]
        if not over:
            break
        spill = sum(w[i] - cap for i in over)
        for i in over:
            w[i] = cap
        free = [i for i in range(n) if w[i] < cap - 1e-12]
        fbase = sum(w[i] for i in free) or 1.0
        for i in free:
            w[i] += spill * (w[i] / fbase)
    return w


def build_carry_basket(
    positioning_map: dict,
    *,
    min_oi_usd: float = _MIN_OI_USD,
    min_abs_carry_apr: float = _MIN_ABS_CARRY_APR,
    max_legs: int = _MAX_LEGS,
    max_name_frac: float = _MAX_NAME_FRAC,
) -> dict:
    """Construct a delta-neutral funding-carry basket from the positioning map.

    positioning_map: {SYM: {"funding": <per-interval pct>, "oi_usd": <float>, ...}}
                     (exactly the shape positioning.py writes to `cis:positioning`).

    Returns:
        {
          "legs": [CarryLeg, ...],          # ranked, weighted, delta-neutral
          "gross_deployed": float,          # Σ weights (≤ 1.0; < 1 when breadth thin)
          "expected_apr": float,            # weight-blended gross carry APR (pre-cost)
          "n_candidates": int,
        }

    Each leg is INDIVIDUALLY delta-neutral, so the basket has ~zero net crypto beta
    by construction — the whole point.
    """
    cands: list[CarryLeg] = []
    for sym, v in (positioning_map or {}).items():
        if not isinstance(v, dict):
            continue
        oi = float(v.get("oi_usd") or 0.0)
        f = v.get("funding")
        if f is None or oi < min_oi_usd:
            continue
        f = float(f)
        apr = annualize_funding(f)
        if abs(apr) < min_abs_carry_apr:
            continue
        side = "short_perp" if f > 0 else "long_perp"
        cands.append(CarryLeg(symbol=sym.upper(), funding_pct_interval=f,
                              carry_apr=apr, side=side, oi_usd=oi))

    # Rank by absolute carry (magnitude of the collectable funding), keep top-N.
    cands.sort(key=lambda c: abs(c.carry_apr), reverse=True)
    cands = cands[:max_legs]

    weights = _capped_weights([abs(c.carry_apr) for c in cands], max_name_frac)
    legs = [CarryLeg(**{**c.__dict__, "weight": round(w, 4)})
            for c, w in zip(cands, weights)]

    gross = round(sum(l.weight for l in legs), 4)
    exp_apr = round(sum(l.weight * abs(l.carry_apr) for l in legs), 4)
    return {
        "legs": legs,
        "gross_deployed": gross,
        "expected_apr": exp_apr,
        "n_candidates": len(legs),
    }


async def build_carry_basket_live(**kwargs) -> dict:
    """Convenience: pull the live positioning map from Redis and build the basket."""
    from src.data.cis.positioning import get_positioning_map
    return build_carry_basket(await get_positioning_map(), **kwargs)


# ── Smoke test (no network) ──────────────────────────────────────────────────

def _smoke() -> int:
    # Synthetic positioning map in the exact shape positioning.py writes.
    # funding is per-8h in percent: 0.03% ≈ 0.03*3*365/100 = 32.9% APR.
    pm = {
        "BTC":  {"funding": 0.010, "oi_usd": 8.0e9,  "positioning_pressure": -0.2},
        "ETH":  {"funding": 0.015, "oi_usd": 4.0e9,  "positioning_pressure": -0.3},
        "SOL":  {"funding": 0.030, "oi_usd": 1.2e9,  "positioning_pressure": -0.5},
        "HYPE": {"funding": 0.045, "oi_usd": 3.0e8,  "positioning_pressure": -1.0},
        "APT":  {"funding": -0.020, "oi_usd": 2.0e8, "positioning_pressure": +0.4},
        "DUST": {"funding": 0.090, "oi_usd": 2.0e6,  "positioning_pressure": -1.0},  # illiquid → dropped
        "FLAT": {"funding": 0.0005, "oi_usd": 5.0e8, "positioning_pressure": 0.0},   # < 5% APR → dropped
    }
    b = build_carry_basket(pm)
    print(f"[SMOKE] {b['n_candidates']} legs | gross={b['gross_deployed']:.2f} "
          f"| blended gross carry APR={b['expected_apr']*100:.1f}%\n")
    print(f"  {'sym':<6}{'funding%':>9}{'carryAPR':>10}{'weight':>9}   structure")
    print(f"  {'-'*52}")
    for l in b["legs"]:
        print(f"  {l.symbol:<6}{l.funding_pct_interval:>9.3f}{l.carry_apr*100:>9.1f}%"
              f"{l.weight:>9.3f}   {l.structure}")
    assert all(l.weight <= _MAX_NAME_FRAC + 1e-9 for l in b["legs"]), "name cap violated"
    assert "DUST" not in {l.symbol for l in b["legs"]}, "illiquid leg leaked in"
    assert "FLAT" not in {l.symbol for l in b["legs"]}, "sub-threshold carry leaked in"
    print("\n[SMOKE] delta-neutral carry basket construction verified.")
    print("[SMOKE] NOTE: edge = mechanical funding capture; still owes the harness a")
    print("[SMOKE]       cost/capacity/mean-reversion pass before any capital.")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_smoke())
