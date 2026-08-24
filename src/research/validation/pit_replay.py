"""Replay a FROZEN decision function over data as it was known at the time (S-207).

THIS IS NOT A BACKTEST, and the distinction is the entire point.

    backtest                          replay
    ────────────────────────────      ────────────────────────────────────────
    the rule is CHOSEN on this data   the rule is FROZEN today, then run
    input = the whole history table   input = rows with recorded_at <= D only
    asks: what return                 asks: did the machine emit a decision,
                                            on which days, and when not — WHY
    failure looks like: bad curve     failure looks like: NO curve

Jazz, 2026-08-24:「重点是看我们的组合和工程是否通,程序是否运作中,而不单是结果。」
He is also right that the 60-day requirement is an INSTITUTIONAL COMPLIANCE clock,
not a technical one. Nothing stops us from asking today whether the machine would
have produced 60 honest marks — and that question has a measurable answer.

WHAT A REPLAY CAN AND CANNOT ESTABLISH. Stated here because it will be quoted
later and the caveat must travel with the number:

  CAN   · did a decision get emitted on day D, or did the pipeline stall
        · trigger frequency, position count, turnover, regime exposure
        · was each input actually PRESENT at D, or only present now
        · a census of blocking reasons — the thing nobody has ever had

  CANNOT · out-of-sample performance. The CIS weights, the universe and the
           parameters were all set with knowledge of this window. Any RETURN
           from a replay is in-sample and may not be shown to an LP.

THE ONE DISTINCTION THIS MODULE EXISTS TO PRESERVE. A day with no position has
two utterly different causes:

    FLAT     the rule looked and said no. The machine worked.
    BLOCKED  the machine could not answer. The rule never got to speak.

Collapsing those two is the defect shape behind every incident this month:
`two_layer` recorded 28 marks at exactly 0.00% and it read as a quiet market;
the IC chain returned `ok=True rows=0` for four months. A flat NAV and a dead
feed produce the same picture, and the picture is the one nobody investigates.
So DayOutcome cannot represent "no position" without also carrying which of the
two it was. There is no default; the caller must say.

POINT-IN-TIME IS ENFORCED ON recorded_at, NEVER ON trade_date. Measured
2026-08-24: `ohlcv_daily.binance_hist` rows carry a median recorded_at **28.2
days after** their trade_date — the June prices were written in late July. A
replay keyed on trade_date would hand the rule prices that did not exist for
another four weeks and call the result a simulation. `cis_scores.recorded_at` is
the Mac engine's push time, so scores are PIT by construction; prices are not.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Any, Callable, Iterable, Mapping, Sequence


class Verdict(str, Enum):
    """Why the book looks the way it does on one day. Three values, never two."""

    FIRED = "fired"        # the rule produced positions
    FLAT = "flat"          # the rule ran, and chose nothing. Working as designed.
    BLOCKED = "blocked"    # the rule could not run. An engineering fact, not a market one.


#: A verdict of BLOCKED without a reason is the failure this module prevents, so
#: the reason is required at construction rather than validated afterwards.
@dataclass(frozen=True)
class DayOutcome:
    day: date
    verdict: Verdict
    reason: str
    n_positions: int = 0
    regime: str | None = None
    inputs_seen: int = 0
    detail: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.reason:
            raise ValueError(
                f"{self.day}: a {self.verdict.value} day with no reason is exactly "
                "the ambiguity this type exists to remove")
        if self.verdict is Verdict.FIRED and self.n_positions <= 0:
            raise ValueError(f"{self.day}: FIRED with {self.n_positions} positions")
        if self.verdict is not Verdict.FIRED and self.n_positions:
            raise ValueError(
                f"{self.day}: {self.verdict.value} cannot carry {self.n_positions} positions")


# A decision function is frozen production logic. It receives ONLY the snapshot
# and must not read the clock, the network, or a database — if it can reach
# today's data it is no longer a replay. Raising is how it reports BLOCKED.
DecisionFn = Callable[[date, Sequence[Mapping[str, Any]]], "Decision"]


class InputUnavailable(RuntimeError):
    """The rule could not run. Distinct from the rule declining to trade."""


@dataclass(frozen=True)
class Decision:
    positions: Mapping[str, float]
    reason: str
    regime: str | None = None
    detail: Mapping[str, Any] = field(default_factory=dict)


@dataclass
class ReplayReport:
    outcomes: list[DayOutcome]

    @property
    def n_days(self) -> int:
        return len(self.outcomes)

    def count(self, verdict: Verdict) -> int:
        return sum(1 for o in self.outcomes if o.verdict is verdict)

    @property
    def fire_rate(self) -> float:
        """Share of days the rule TOOK a position, over days it could run.

        BLOCKED days are excluded from the denominator on purpose: they measure
        our plumbing, not the rule, and averaging the two produces a number that
        improves when the pipeline breaks.
        """
        ran = self.n_days - self.count(Verdict.BLOCKED)
        return (self.count(Verdict.FIRED) / ran) if ran else 0.0

    def blocking_reasons(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for o in self.outcomes:
            if o.verdict is Verdict.BLOCKED:
                out[o.reason] = out.get(o.reason, 0) + 1
        return dict(sorted(out.items(), key=lambda kv: -kv[1]))

    def flat_reasons(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for o in self.outcomes:
            if o.verdict is Verdict.FLAT:
                out[o.reason] = out.get(o.reason, 0) + 1
        return dict(sorted(out.items(), key=lambda kv: -kv[1]))

    def summary(self) -> dict[str, Any]:
        return {
            "days": self.n_days,
            "fired": self.count(Verdict.FIRED),
            "flat": self.count(Verdict.FLAT),
            "blocked": self.count(Verdict.BLOCKED),
            # Named `fire_rate_of_runnable_days`, not `fire_rate`, because the
            # denominator is the part a reader gets wrong.
            "fire_rate_of_runnable_days": round(self.fire_rate, 4),
            "blocking_reasons": self.blocking_reasons(),
            "flat_reasons": self.flat_reasons(),
            # A replay reports no NAV. See the module docstring: the return would
            # be in-sample, and a number present in a payload gets quoted.
            "return_pct": None,
            "return_omitted_because": "in-sample; the rule was specified knowing this window",
        }


def replay(
    days: Iterable[date],
    snapshot_for: Callable[[date], Sequence[Mapping[str, Any]]],
    decide: DecisionFn,
) -> ReplayReport:
    """Run `decide` once per day on a point-in-time snapshot.

    `snapshot_for(D)` must already have applied `recorded_at <= D`. It is passed
    in rather than queried here so the harness stays offline-testable and so the
    PIT filter lives in exactly one place per data source.
    """
    outcomes: list[DayOutcome] = []
    for d in days:
        try:
            rows = snapshot_for(d)
        except Exception as e:                                    # noqa: BLE001
            outcomes.append(DayOutcome(d, Verdict.BLOCKED,
                                       f"snapshot unavailable: {type(e).__name__}"))
            continue

        if not rows:
            # An empty snapshot is NOT a market with nothing in it. On this
            # window it means the engine did not push that day, which is the
            # thing a replay is built to surface.
            outcomes.append(DayOutcome(d, Verdict.BLOCKED, "no rows visible at this date"))
            continue

        try:
            dec = decide(d, rows)
        except InputUnavailable as e:
            outcomes.append(DayOutcome(d, Verdict.BLOCKED, str(e)[:160],
                                       inputs_seen=len(rows)))
            continue
        except Exception as e:                                    # noqa: BLE001
            outcomes.append(DayOutcome(d, Verdict.BLOCKED,
                                       f"rule raised {type(e).__name__}: {str(e)[:120]}",
                                       inputs_seen=len(rows)))
            continue

        n = len(dec.positions)
        outcomes.append(DayOutcome(
            d,
            Verdict.FIRED if n else Verdict.FLAT,
            dec.reason,
            n_positions=n,
            regime=dec.regime,
            inputs_seen=len(rows),
            detail=dec.detail,
        ))
    return ReplayReport(outcomes)
