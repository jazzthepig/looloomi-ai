"""
State-persistence guard — the trigger-side of the executability floor.

WHY (S-117). A proposed layer-③ sleeve was studying `macro_regime` transitions.
Measured before anything else: **49 runs, median 3 days, 51 % of runs ≤3 days.**
More than half the "transitions" were label chatter reverting inside three days.

Then measured what a causal dwell filter does to that series:

    dwell   runs  median  ≤3d     transitions   EASING↔RISK_OFF
    raw      49     3d    51.0%       48             8 / 8
    3d       24    8.5d   16.7%       23             3 / 3
    5d       14   19.0d    0.0%       13             3 / 3
    7d        8   66.5d    0.0%        7             2 / 2
    10d       5   70.0d    0.0%        4             1 / 0

Two conclusions that must not be collapsed into one:

  · at dwell=5 the regime becomes a LEGITIMATE trigger — median 19 days against
    the gate's 5-day minimum hold, zero sub-3-day runs;
  · and the sample collapses from 8/8 to 3/3, because 5 of every 8 "transitions"
    were chatter.

**Smoothing makes the trigger usable. It does not make the evidence sufficient.**
Those are separate problems and only the first is solved by a filter.

Run: python3 -m tests.test_state_persistence
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.research.validation.state_persistence import (  # noqa: E402
    dwell_cost_days, dwell_filter, persistence_summary, run_lengths, transitions,
)


def test_run_lengths_and_median_are_the_first_thing_measured():
    """The cheapest possible check on a state variable, and the one that decides
    whether a detector built on it is worth writing at all."""
    s = ["A", "A", "A", "B", "C", "C"]
    assert run_lengths(s) == [("A", 3), ("B", 1), ("C", 2)]
    p = persistence_summary(s)
    assert p["n_runs"] == 3 and p["median_run"] == 2.0 and p["longest_run"] == 3
    assert persistence_summary([])["n_runs"] == 0, "empty must not raise"


def test_chatter_share_is_reported_because_it_is_the_headline():
    """`pct_runs_le_3` exists because 'median 3 days' understates the problem: on
    the real regime series 51 % of runs were ≤3 days, i.e. half the state changes
    were not state changes."""
    chattery = ["A", "B", "A", "B", "A", "B"]
    steady = ["A"] * 20 + ["B"] * 20
    assert persistence_summary(chattery)["pct_runs_le_3"] == 100.0
    assert persistence_summary(steady)["pct_runs_le_3"] == 0.0


def test_dwell_filter_is_causal_so_it_can_drive_a_live_book():
    """A centred filter looks smoother and leaks the future — the smoothing would
    become the edge, which is the R76–R94 error in new clothes. Every output at t
    must be reproducible from inputs up to t."""
    s = ["A"] * 5 + ["B"] * 5 + ["A"] * 5
    full = dwell_filter(s, 3)
    for t in range(1, len(s) + 1):
        prefix = dwell_filter(s[:t], 3)
        assert prefix == full[:t], f"filter used future information at t={t}"


def test_a_brief_excursion_is_rejected_and_a_persistent_one_accepted():
    """The whole point: a 2-day flip must not move the book, a 6-day one must."""
    brief = ["A"] * 10 + ["B"] * 2 + ["A"] * 10
    assert set(dwell_filter(brief, 5)) == {"A"}, "2-day excursion must be filtered out"
    real = ["A"] * 10 + ["B"] * 8
    assert "B" in dwell_filter(real, 5), "an 8-day switch must be accepted"
    # and accepted LATE, not retroactively — the delay is the price of persistence
    sm = dwell_filter(real, 5)
    assert sm.index("B") > real.index("B"), "acceptance must lag, never backdate"


def test_the_filter_reports_what_it_costs_in_sample_and_in_latency():
    """A filter that only reports how much prettier the series became is a sales
    pitch. Both costs are real: sample destroyed, and every surviving switch made
    late — which for a drawdown trigger is days taken at full size."""
    s = ["A"] * 10 + ["B"] * 2 + ["A"] * 10 + ["B"] * 8
    c = dwell_cost_days(s, 5)
    assert c["transitions_raw"] > c["transitions_after"], "chatter must be removed"
    assert c["pct_removed"] > 0
    assert c["max_delay_obs"] == 4, "dwell=5 delays every accepted switch by up to 4"
    assert isinstance(c["surviving"], dict), "surviving transitions must be enumerable"


def test_smoothing_fixes_the_trigger_and_not_the_sample():
    """S-117's actual finding, pinned so nobody reads the filter as a rescue.
    On the real series a 5-day dwell took the median run from 3 to 19 days — the
    trigger became legitimate — while EASING↔RISK_OFF transitions fell from 8/8 to
    3/3. n=3 is an anecdote. A filter buys persistence with sample, always."""
    # 8 alternations, each side persistent enough to survive a 5-day dwell, plus
    # chatter between them that must not
    seq = []
    for _ in range(4):
        seq += ["EASING"] * 12 + ["RISK_OFF"] * 2 + ["EASING"] * 2 + ["RISK_OFF"] * 12
    raw_t = transitions(seq)
    sm_t = transitions(dwell_filter(seq, 5))
    raw_n = raw_t.get(("EASING", "RISK_OFF"), 0)
    sm_n = sm_t.get(("EASING", "RISK_OFF"), 0)
    assert sm_n < raw_n, "smoothing must cost sample, and the cost must be visible"
    assert persistence_summary(dwell_filter(seq, 5))["median_run"] > \
        persistence_summary(seq)["median_run"], "and must buy persistence with it"


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    p = f = 0
    for t in TESTS:
        try:
            t(); print(f"  ✓ {t.__name__}"); p += 1
        except AssertionError as e:
            print(f"  ✗ {t.__name__}\n      {e}"); f += 1
    print(f"\n{'✅' if not f else '🔴'} {p}/{len(TESTS)} state-persistence checks passed")
    sys.exit(1 if f else 0)
