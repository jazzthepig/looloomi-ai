"""
AUM tripwire — the capacity ceiling, recomputed, with an alarm (S-154).

WHY IT EXISTS. On 2026-08-12 R66-C's realised edge was measured to sit almost
entirely in names too small to hold at institutional size: sub-$20M ADV
contributed +186.5% of a +154.6% total, and the ten names passing a $5M ADV
floor summed to **−21.3%**. At $500M AUM that is disqualifying. At the $10k Jazz
is starting with next week it is irrelevant — $10k against a $1.4M ADV name is
0.7% participation, not 10%.

Both statements are true and they expire at different times. That is the whole
problem this module solves: **a constraint that does not bind today will bind
later, silently, on a day when nobody is thinking about it.** The sleeve will
not announce that it has outgrown its universe; the fills will just get worse,
and worse fills look exactly like a decaying edge. By the time it is visible in
the P&L, the diagnosis is already ambiguous.

THE CEILING IS RECOMPUTED, NEVER STORED. ADV moves, and not slowly: COMP
measured $1.4M on a 180-day median and $0.3M on a 30-day one in the same hour.
A capacity number written down in a strategy record on the day it shipped is a
number that describes a market which no longer exists. So the ceiling is a
function of (weights, today's ADV, participation) — the same discipline as
`investable_universe(as_of)`: recompute, do not look up.

WHAT IS RECORDED IS THE RULE, NOT THE NUMBER: participation limit, the trading
window, and the warn/breach fractions live in `strategy_params` (versioned,
append-only, validated on load), so "when did we decide 5% was prudent" has a
dated answer and every book carries the version that sized it.

TWO COSTS, AND ONLY ONE OF THEM SHRINKS WITH SIZE. This module bounds MARKET
IMPACT, which does scale with participation and therefore vanishes at $10k. It
does NOT bound SPREAD, which you cross regardless of size and which is WIDER on
the thin names — so a small account is free of the capacity constraint and more
exposed to the cost assumption, not less. `spread_drag_pct_yr` is here so that
the two are never again reported as one number.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

_log = logging.getLogger("aum_tripwire")

NS_TRIPWIRE = "capacity_tripwire_v1"

FALLBACK_PARAMS = {
    "participation": 0.05,        # ≤5% of ADV — prudent, low-impact
    "rebal_trade_days": 3,        # a rebalance may be spread over ~3 sessions
    "warn_fraction": 0.50,        # tell me at half the ceiling, not at the ceiling
    "breach_fraction": 1.00,
}

OK, APPROACHING, BREACH, UNKNOWN = "ok", "approaching", "breach", "unknown"


def validate_tripwire(v: dict) -> list[str]:
    problems: list[str] = []
    try:
        part = float(v["participation"]); days = int(v["rebal_trade_days"])
        warn = float(v["warn_fraction"]); brea = float(v["breach_fraction"])
    except (KeyError, TypeError, ValueError):
        return ["participation / rebal_trade_days / warn_fraction / breach_fraction "
                "missing or non-numeric"]
    if not 0 < part <= 0.25:
        problems.append(f"participation={part} — above ~25% of ADV you are the market, "
                        f"and the backtest's fills stop being achievable")
    if days < 1:
        problems.append("rebal_trade_days < 1")
    if not 0 < warn < brea:
        problems.append(f"warn_fraction ({warn}) must sit strictly below breach_fraction "
                        f"({brea}) — a warning that fires at the breach is not a warning")
    if brea > 1.5:
        problems.append(f"breach_fraction={brea} — a breach threshold above the ceiling "
                        f"means the alarm fires after the damage")
    return problems


@dataclass(frozen=True)
class Headroom:
    status: str
    aum_usd: float
    ceiling_usd: float | None          # None when ADV coverage is incomplete
    utilisation: float | None          # aum / ceiling
    binding: tuple[str, ...]           # the names that set the ceiling
    unpriced: tuple[str, ...]          # no ADV — see the partial-coverage note
    param_version: int = 0
    param_source: str = "code_fallback"
    note: str = ""

    def stamp(self) -> dict:
        return {"capacity_status": self.status,
                "capacity_ceiling_usd": self.ceiling_usd,
                "capacity_utilisation": self.utilisation,
                "capacity_param_version": self.param_version}


def headroom(aum_usd: float, weights: dict[str, float],
             adv_usd: dict[str, float], params=None) -> Headroom:
    """How close is this book to the size at which it starts trading against
    itself?

    PARTIAL ADV COVERAGE REFUSES TO PRODUCE A CEILING. A minimum taken over the
    names we happen to have volume for is an UPPER BOUND on capacity, not
    capacity — and it is biased in the dangerous direction, because the name we
    are missing volume for is usually the thin one. Same rule as
    `research.factory.capacity` after S-132; stated here too because the two
    are read in different places.
    """
    if params is None:
        from src.data.signals.strategy_params import load
        params = load(NS_TRIPWIRE, FALLBACK_PARAMS, fallback_version=0)
    p = params.values
    part = float(p["participation"]); days = int(p["rebal_trade_days"])
    warn = float(p["warn_fraction"]); brea = float(p["breach_fraction"])
    pv = getattr(params, "version", 0); ps = getattr(params, "source", "code_fallback")

    held = {s: abs(w) for s, w in weights.items() if abs(w) > 1e-9}
    if not held:
        return Headroom(UNKNOWN, aum_usd, None, None, (), (), pv, ps,
                        "no positions")

    unpriced = tuple(sorted(s for s in held if not adv_usd.get(s)))
    if unpriced:
        return Headroom(
            UNKNOWN, aum_usd, None, None, (), unpriced, pv, ps,
            f"no ADV for {len(unpriced)} held name(s): {', '.join(unpriced[:6])}. "
            f"A minimum over the priced subset is an upper bound on capacity, not "
            f"capacity — and the missing name is usually the thin one.")

    per_name = {s: part * adv_usd[s] * days / w for s, w in held.items()}
    ceiling = min(per_name.values())
    binding = tuple(sorted(s for s, c in per_name.items() if c <= ceiling * 1.05))
    util = aum_usd / ceiling if ceiling > 0 else float("inf")

    if util >= brea:
        status, note = BREACH, (
            f"AUM ${aum_usd:,.0f} is {util:.0%} of the ${ceiling:,.0f} ceiling set by "
            f"{', '.join(binding)}. Fills will degrade, and degrading fills look "
            f"exactly like a decaying edge — which is why this fires on size rather "
            f"than on P&L.")
    elif util >= warn:
        status, note = APPROACHING, (
            f"AUM ${aum_usd:,.0f} is {util:.0%} of the ${ceiling:,.0f} ceiling "
            f"({', '.join(binding)}). Decide now, while it is still a choice: cap the "
            f"sleeve, widen the universe, or accept worse fills knowingly.")
    else:
        status, note = OK, (
            f"AUM ${aum_usd:,.0f} vs ${ceiling:,.0f} ceiling ({util:.1%}). "
            f"Capacity does not bind. Note it bounds IMPACT only — spread is crossed "
            f"at any size and is wider on the thin names.")
    return Headroom(status, aum_usd, ceiling, util, binding, (), pv, ps, note)


def spread_drag_pct_yr(spread_bps: float, rebalances_per_yr: float,
                       legs: int = 2, sides: int = 2) -> float:
    """The cost that does NOT shrink with account size.

    Kept beside the capacity ceiling deliberately. R66-C assumed 10bps
    round-trip and its S4 ladder showed break-even at 150bps, which reads as 15x
    headroom — but the names carrying its edge trade $1-2M a day, where the
    spread alone is routinely 25-50bps. At ~28 rebalances a year that is 28-56%
    annually, against a realised ~96%/yr. A small account removes impact and
    keeps every basis point of this.
    """
    return (spread_bps / 10_000.0) * legs * sides * rebalances_per_yr * 100.0
