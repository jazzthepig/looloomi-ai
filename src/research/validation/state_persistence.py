"""
State-variable persistence: measure it, then smooth it.

WHY (S-117). A proposed layer-③ sleeve keyed off `macro_regime` was studying its
transitions. Measured first: **49 regime runs, median 3 days, 25 of them ≤3 days.**
More than half the "transitions" were label chatter that reverted inside three days.
A 3-day trigger cannot open a 30-day position — the book is overturned before the
position matures, and the holding period on the record becomes a fiction.

That generalises past this one field, which is why this module is about STATE
VARIABLES rather than about regimes:

  · `run_lengths()` — measure before designing. Cheap, and it decides whether a
    detector is worth building at all.
  · `dwell_filter()` — accept a switch only after the new state has persisted for
    `min_dwell` observations. One parameter, and it is a DELAY not a threshold, so
    it cannot be tuned toward a return.
  · `transitions()` — count what survives, because the honest question after
    smoothing is "how much sample is left", not "is the line prettier".

DESIGN CHOICE THAT MATTERS. `dwell_filter` is causal: at time t it may only use
observations up to t, so the smoothed series is usable as a live trigger. A
centred filter would look smoother and leak the future — the smoothing itself
would become the edge, which is the R76–R94 error wearing new clothes.

THE COST IS STATED, NOT HIDDEN. Dwell filtering delays every switch by up to
`min_dwell` days. For a trigger meant to cut exposure in a drawdown, a 5-day delay
is 5 days of the drawdown taken at full size. The right filter length is therefore
a function of how fast the thing being avoided arrives, and `dwell_cost_days()`
reports it rather than leaving it implicit.
"""
from __future__ import annotations

from collections.abc import Sequence


def run_lengths(states: Sequence) -> list[tuple]:
    """[(state, length), …] in order. The first thing to compute about any state
    variable, and cheaper than any detector built on top of it."""
    out: list[tuple] = []
    for s in states:
        if out and out[-1][0] == s:
            out[-1] = (s, out[-1][1] + 1)
        else:
            out.append((s, 1))
    return out


def persistence_summary(states: Sequence) -> dict:
    """Run-length distribution. `median_run` is the number that decides whether a
    state variable can drive anything slower than itself."""
    runs = run_lengths(states)
    if not runs:
        return {"n_runs": 0, "median_run": float("nan"), "mean_run": float("nan"),
                "pct_runs_le_3": float("nan"), "longest_run": 0}
    lens = sorted(r[1] for r in runs)
    n = len(lens)
    median = float(lens[n // 2] if n % 2 else (lens[n // 2 - 1] + lens[n // 2]) / 2)
    return {
        "n_runs": n,
        "median_run": median,
        "mean_run": sum(lens) / n,
        # the chatter share: what fraction of "state changes" revert almost at once
        "pct_runs_le_3": 100.0 * sum(1 for x in lens if x <= 3) / n,
        "longest_run": lens[-1],
    }


def dwell_filter(states: Sequence, min_dwell: int = 5) -> list:
    """Accept a state switch only after the candidate has persisted `min_dwell`
    consecutive observations. CAUSAL: index t uses only 0..t.

    Returns a series of the same length. The first `min_dwell-1` entries hold the
    initial state because nothing has yet persisted long enough to displace it —
    they are not a prediction, and callers evaluating the filter should drop them
    rather than count them as correct.
    """
    if min_dwell <= 1 or not states:
        return list(states)
    out: list = []
    confirmed = states[0]
    candidate = states[0]
    streak = 1
    for s in states:
        if s == candidate:
            streak += 1
        else:
            candidate, streak = s, 1
        if candidate != confirmed and streak >= min_dwell:
            confirmed = candidate
        out.append(confirmed)
    return out


def transitions(states: Sequence) -> dict[tuple, int]:
    """{(from, to): count}. Run AFTER smoothing to answer the only question that
    matters there: how much sample survives."""
    out: dict[tuple, int] = {}
    prev = None
    for s in states:
        if prev is not None and s != prev:
            out[(prev, s)] = out.get((prev, s), 0) + 1
        prev = s
    return out


def dwell_cost_days(states: Sequence, min_dwell: int) -> dict:
    """What the filter costs, in the currency that matters for a risk trigger.

    A dwell filter buys persistence with LATENCY. If the trigger exists to cut
    exposure during a drawdown, every day of delay is a day taken at full size —
    so the filter length must be justified against how fast the avoided event
    arrives, not chosen for how clean the chart looks.
    """
    raw = transitions(states)
    smoothed = transitions(dwell_filter(states, min_dwell))
    raw_n = sum(raw.values())
    sm_n = sum(smoothed.values())
    return {
        "min_dwell": min_dwell,
        "transitions_raw": raw_n,
        "transitions_after": sm_n,
        "pct_removed": 100.0 * (raw_n - sm_n) / raw_n if raw_n else float("nan"),
        # every surviving switch is late by up to min_dwell-1 observations
        "max_delay_obs": max(0, min_dwell - 1),
        "surviving": smoothed,
    }
