"""
Depth divergence — a measured UNDERWEIGHT condition, and the record that will
either confirm or kill it (S-173, 2026-08-18).

WHAT WAS MEASURED (S-172, full ledger entry there). Over 262 crypto symbols,
2023-2026, PIT, benchmarked against hold-the-panel and with the DAY as the unit
of independence:

    depth_z >= 1.5  AND  |20d price move| < 10%
      → 20-day excess vs panel  -1.85%   t = -5.23   (1,134 days)

    depth_z >= 1.5  AND  20d price move >= +10%
      → 20-day excess           -0.75%   t = -1.56   (indistinguishable from 0)

The hypothesis being tested was the OPPOSITE: that depth arriving before price
marks a window where you can size in before the move. It does not exist. Depth
accompanies price 3.3x more often than it precedes it, and when depth arrives
WITHOUT price the name subsequently underperforms. The plain reading is
distribution — volume without price is someone getting out.

    at $10k deployable   -2.31%
    at $10M              -4.03%
    at $100M             -7.54%

Consistent across all five AUM scenarios and getting WORSE with size, which is
the opposite of an edge that decays into capacity.

WHY THIS IS AN UNDERWEIGHT AND NOT A SHORT. CLAUDE.md's return hierarchy is
long-only by default: tilt, do not neutralize. A -1.85% conditional in a
long-only book means "do not add here", which is a weight decision, not a
direction. It is also the only compliant reading — we hold no 投顾 license and
the signal vocabulary is positioning-only.

THE NUMBERS ABOVE ARE IN-SAMPLE AND THIS MODULE DOES NOT CLAIM THEM FORWARD.
That is the entire point of the log below. S-172 was one pass over history with
thresholds fixed in advance and no re-scanning — good discipline, still not a
forward record. `tests/test_strategy_discipline.py` requires >=60d paper before
any SHIP verdict, so this ships as an OBSERVATION that starts a clock on
2026-08-18, resolvable 2026-10-17.

AND THE SECOND REASON THE LOG EXISTS. Every failure this repo found this week
was something computed and discarded: activation_z has no write path,
holder_provider fetches concentration and drops it into a Redis map whose own
docstring says the dynamic timeseries is "Phase 2 (needs timeseries)", eleven
tables the code wrote to did not exist. A signal with no stored history cannot
be refuted, and an unrefutable signal is not evidence — it is a belief with a
number attached.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Compliance rule #1: positioning vocabulary only. Never BUY/SELL/HOLD/AVOID.
SIGNAL_UNDERWEIGHT = "UNDERWEIGHT"
SIGNAL_NEUTRAL = "NEUTRAL"

# Fixed 2026-08-18 BEFORE the study ran, and not re-scanned afterwards.
# Re-tuning these against outcomes would convert a measurement into a fit, and
# `experiment_runs.dsr` — the deflated Sharpe column that exists precisely to
# charge for that — has never been populated in 43 rows.
DEPTH_Z_MIN = 1.5
PRICE_FLAT_ABS = 0.10

RULE_VERSION = "depth_divergence_v1"
INCEPTION = "2026-08-18"
GATE_DAYS = 60          # resolvable 2026-10-17


@dataclass(frozen=True)
class DepthObservation:
    """One (symbol, date) reading. `signal` is what a surface may show; the rest
    is what makes it auditable later."""
    symbol: str
    d: str
    depth_z: float | None
    px20: float | None
    adv20_usd: float | None
    signal: str
    cell: str
    rule_version: str = RULE_VERSION
    problems: list[str] = field(default_factory=list)

    @property
    def is_measured(self) -> bool:
        """False when an input was missing. A NEUTRAL from 'no signal' and a
        NEUTRAL from 'no data' are different states and must never render the
        same — that collapse is S-131's cap_source and S-141's moat band."""
        return not self.problems


def classify(symbol: str, d: str, *,
             depth_z: float | None,
             px20: float | None,
             adv20_usd: float | None = None) -> DepthObservation:
    """Classify one point. Never raises: a bad input yields a NEUTRAL that says
    it is unmeasured, because a sleeve that crashes on one asset is a sleeve
    that stops marking the book."""
    problems: list[str] = []
    if depth_z is None or depth_z != depth_z:          # None or NaN
        problems.append("depth_z unavailable — needs >=80 prior daily bars")
    if px20 is None or px20 != px20:
        problems.append("px20 unavailable — needs >=21 prior daily bars")

    if problems:
        return DepthObservation(symbol.upper(), d, None, None, adv20_usd,
                                SIGNAL_NEUTRAL, "unmeasured", problems=problems)

    if depth_z >= DEPTH_Z_MIN and abs(px20) < PRICE_FLAT_ABS:
        cell, signal = "depth_up_price_flat", SIGNAL_UNDERWEIGHT
    elif depth_z >= DEPTH_Z_MIN and px20 >= PRICE_FLAT_ABS:
        cell, signal = "depth_up_price_up", SIGNAL_NEUTRAL
    elif depth_z >= DEPTH_Z_MIN:
        cell, signal = "depth_up_price_down", SIGNAL_NEUTRAL
    else:
        cell, signal = "depth_flat", SIGNAL_NEUTRAL

    return DepthObservation(symbol.upper(), d, round(float(depth_z), 4),
                            round(float(px20), 6), adv20_usd, signal, cell)


def to_row(o: DepthObservation) -> dict[str, Any]:
    """Shape for `depth_divergence_log`. Forward columns are deliberately absent:
    they are written by the resolver 20 trading days later, and a row that
    carries its own outcome at creation time is a row nobody can trust."""
    return {
        "d": o.d,
        "symbol": o.symbol,
        "rule_version": o.rule_version,
        "depth_z": o.depth_z,
        "px20": o.px20,
        "adv20_usd": o.adv20_usd,
        "cell": o.cell,
        "signal": o.signal,
        "is_measured": o.is_measured,
        "problems": "; ".join(o.problems) or None,
    }


def summarise(obs: list[DepthObservation]) -> dict[str, Any]:
    """A daily banner that reports coverage, not just hits. `unmeasured` is a
    first-class number: a day where the rule fired on 3 names out of 12 measured
    is a different day from one where it fired on 3 out of 240."""
    total = len(obs)
    measured = [o for o in obs if o.is_measured]
    cells: dict[str, int] = {}
    for o in measured:
        cells[o.cell] = cells.get(o.cell, 0) + 1
    return {
        "rule_version": RULE_VERSION,
        "inception": INCEPTION,
        "gate_days": GATE_DAYS,
        "n_total": total,
        "n_measured": len(measured),
        "n_unmeasured": total - len(measured),
        "cells": cells,
        "n_underweight": sum(1 for o in measured if o.signal == SIGNAL_UNDERWEIGHT),
        "claim": ("IN-SAMPLE ONLY. S-172 measured -1.85% 20d excess (t=-5.23) for "
                  "depth_up_price_flat over 2023-2026. This log exists to test that "
                  "forward; no forward claim is made before "
                  f"{INCEPTION} + {GATE_DAYS}d."),
    }
