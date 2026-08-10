"""
Value added, in dollars (S-132, 2026-08-10).
============================================

WHY THIS EXISTS. Every sleeve we have ever measured has been denominated in
percent: IC, Sharpe, `net_effect_pct_yr`. Berk & Green (JPE 2004) and Berk &
van Binsbergen (JFE 2015) are the reason that is the wrong unit for a fund:

  - Percentage alpha is competed away by inflows. It does NOT predict itself:
    a manager's past percentage alpha is close to useless for its own future.
  - Dollars extracted from markets — gross alpha × assets under management —
    DOES persist, measurably, out to about ten years.

The mechanism is simple and it applies to us exactly. Skill is a fixed thing;
the percentage it earns shrinks as the capital chasing it grows, until the
percentage is competed to the cost of capital. What survives the competition
is the SIZE of the pie the manager can extract. Percentage is the price of
skill; dollars are the quantity of it.

WHY IT MATTERS MORE IN CRYPTO THAN ANYWHERE. The characteristic deception here
is a large percentage on a notional that could never be deployed: 40 %/yr on a
$150k book that is bounded by a $3m/day order book. A gate denominated in
percent CANNOT SEE THAT — 40 is greater than every threshold we own. It is not
even dishonest; the backtest is arithmetically correct. It is simply answering
a question no allocator asked. `deployable_notional_usd` is the missing second
axis, and it collides with liquidity data we already have (ADV, LAS,
`max_notional_at`), so it costs no new pipeline.

WHAT COUNTS AS A BASIS. `notional_basis` must name the derivation. "assumed AUM"
is not a basis — it is the same unmeasured-substituted-with-a-plausible-value
pattern the S-122 guard exists to catch, wearing a dollar sign. The two honest
derivations are implemented below; both bottom out in an observed order book.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from src.data.vector.strategy_schema import MIN_MEANINGFUL_NOTIONAL_USD
from src.research.factory.capacity import PARTICIPATION, REBAL_TRADE_DAYS, capacity

# MIN_MEANINGFUL_NOTIONAL_USD is imported, not redefined: below it a sleeve is a
# research result rather than a sleeve, and the SHIP gate in strategy_schema
# enforces the same floor. Two copies of a threshold is one copy that goes stale.
__all__ = ["MIN_MEANINGFUL_NOTIONAL_USD", "deployable_notional",
           "value_added_usd_yr", "assess"]


def deployable_notional(
    weights: Dict[str, float],
    adv_usd: Dict[str, float],
    *,
    participation: float = PARTICIPATION,
    trade_days: int = REBAL_TRADE_DAYS,
) -> Tuple[Optional[float], str]:
    """
    Largest book notional whose HARDEST-to-trade leg still clears inside the
    participation budget. Returns (notional_usd | None, basis).

    Binding constraint, per name:  participation × ADV × trade_days / |weight|
    Book notional = min over names. A minimum is only valid over a COMPLETE set,
    so an incomplete ADV map returns None — not a number computed over the
    names that happened to resolve. This is the whole point: the missing names
    are the ones that would have bound.
    """
    live = {s: w for s, w in (weights or {}).items() if abs(float(w)) >= 1e-4}
    if not live:
        return None, "no_positions"

    res = capacity(live, participation=participation, adv_usd=adv_usd or {})
    if res.get("status") in (None, "no_liquidity_data") or "book_capacity_usd_m" not in res:
        return None, f"no_liquidity_data (unpriced={res.get('unpriced', [])})"
    if res.get("status") == "partial":
        # Refuse rather than under-constrain. See module docstring.
        return None, (f"partial_adv_coverage {res.get('coverage_pct')}% — "
                      f"unpriced={res.get('unpriced')}; a minimum over a subset "
                      f"is an upper bound, not a capacity")

    notional = float(res["book_capacity_usd_m"]) * 1e6
    basis = (f"min over {len(live)} legs of {participation:.0%} ADV × {trade_days}d "
             f"/ |w|; binding={res.get('binding_names')}; "
             f"gross={res.get('gross')}")
    return notional, basis


def value_added_usd_yr(net_effect_pct_yr: float, notional_usd: float) -> float:
    """Dollars per year the sleeve adds at its own capacity. Net of turnover cost —
    `net_effect_pct_yr` is already gross-minus-cost upstream."""
    return float(net_effect_pct_yr) / 100.0 * float(notional_usd)


def assess(
    weights: Dict[str, float],
    adv_usd: Dict[str, float],
    net_effect_pct_yr: Optional[float],
    **kw: Any,
) -> Dict[str, Any]:
    """
    One call producing the three fields `StrategyRecord.validate()` demands for a
    SHIP verdict, plus the verdict on whether the capacity is worth staffing.
    """
    notional, basis = deployable_notional(weights, adv_usd, **kw)
    out: Dict[str, Any] = {
        "deployable_notional_usd": notional,
        "notional_basis": basis,
        "value_added_usd_yr": None,
        "meaningful": False,
        "note": "",
    }
    if notional is None:
        out["note"] = f"capacity unavailable: {basis}"
        return out
    if net_effect_pct_yr is None:
        out["note"] = "capacity known but net_effect_pct_yr missing — no dollar figure"
        return out

    va = value_added_usd_yr(net_effect_pct_yr, notional)
    out["value_added_usd_yr"] = round(va, 0)
    out["meaningful"] = notional >= MIN_MEANINGFUL_NOTIONAL_USD and va > 0
    if notional < MIN_MEANINGFUL_NOTIONAL_USD:
        out["note"] = (f"{net_effect_pct_yr:.1f}%/yr is real but caps at "
                       f"${notional:,.0f} — a research result, not a sleeve")
    elif va <= 0:
        out["note"] = "negative dollars at capacity"
    else:
        out["note"] = (f"${va:,.0f}/yr at ${notional:,.0f} capacity "
                       f"({net_effect_pct_yr:.2f}%/yr)")
    return out
