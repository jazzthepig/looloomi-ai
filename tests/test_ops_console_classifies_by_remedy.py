"""The console must sort by REMEDY, and no refusal may sit without an expiry.

S-296: 「一个只拦不导的守卫,会把违规变成缺口」. Every outage in the S-323 chain
was a CORRECT refusal that then never cleared. For a product whose substance is
a continuous daily record, a refusal that persists is outcome-identical to a
crash — so "correct" cannot be a permanent excuse.

Run: python3 -m pytest tests/test_ops_console_classifies_by_remedy.py
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "ops_console", ROOT / "scripts" / "ops_console.py")
oc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(oc)


def test_every_refusal_policy_declares_who_clears_it_and_when():
    """A refusal with no expiry is how a guard becomes an outage."""
    for name, pol in oc.REFUSAL_POLICY.items():
        for field in ("reason", "clears_when", "owner", "stale_after_days"):
            assert pol.get(field), (
                f"{name}.{field} missing — a refusal we call 'correct' must say "
                f"what clears it, who owns it, and how long it may sit before "
                f"it is an alarm again"
            )
        assert isinstance(pol["stale_after_days"], int), name


def test_refusal_policy_reasons_carry_their_why_substring():
    """WHY-substring guard. A future refactor that drops the S-/R- reference from
    `reason` is a refactor that turned the guard back into a silent refusal.

    The substring must match by code (loop name) so the test rides on the actual
    constant, not a free-text comment. Each substring here is what a future reader
    would need to find the original refusal in code/git history.
    """
    WHY_SUBSTRINGS = {
        # loop name : substring that MUST appear in reason
        "_deep_panel_loop":       "S-323i",
        "_forward_record_loop":   "S-323f",
        "_beta_core_loop":        "S-323o",
        "_factor_tilt_loop":      "insufficient_live_data",
        "_pod_aggregator_loop":   "insufficient_live_data",
        "_two_layer_paper_loop":  "R57",
        "_market_state_loop":     "S-220",
        "_fusion_paper_loop":     "S-336",
    }
    for loop_name, why in WHY_SUBSTRINGS.items():
        assert loop_name in oc.REFUSAL_POLICY, (
            f"{loop_name} removed from REFUSAL_POLICY — the test rides on the "
            f"actual constant; if you intentionally retired this loop, remove "
            f"the entry here too"
        )
        reason = oc.REFUSAL_POLICY[loop_name]["reason"]
        assert why in reason, (
            f"{loop_name}.reason dropped its WHY ({why!r}); without it the "
            f"refusal becomes silent. Reason text was:\n{reason!r}"
        )


def test_a_refusal_past_its_window_becomes_an_alarm():
    import time
    pol = {"reason": "r", "clears_when": "c", "owner": "o", "stale_after_days": 3}
    fresh = {"last_ok_at": time.time() - 1 * 86400}
    stale = {"last_ok_at": time.time() - 9 * 86400}
    assert oc._refusal_overdue(fresh, pol) is False
    assert oc._refusal_overdue(stale, pol) is True, (
        "a guard refusing for 9 days against a 3-day window is the outage"
    )


def test_a_missing_timestamp_is_not_treated_as_healthy():
    """Unknown is not success — the defect this whole chain is made of."""
    pol = {"reason": "r", "clears_when": "c", "owner": "o", "stale_after_days": 3}
    assert oc._refusal_overdue({}, pol) is True, (
        "no last_ok_at means we cannot show it is fine, and 'cannot show it is "
        "fine' must not render as fine"
    )


def test_an_unknown_verdict_never_lands_in_ok():
    rows = {"rows": [{"loop": "_x", "verdict": "banana", "stale_build": False}]}
    got = oc._classify_loops(rows)[0]
    assert got["remedy_class"] == "unregistered", got


def test_an_unruled_refusal_is_surfaced_not_silently_excused():
    rows = {"rows": [{"loop": "_never_seen_loop", "verdict": "refused",
                      "stale_build": False, "last_ok_at": None}]}
    got = oc._classify_loops(rows)[0]
    assert got["remedy_class"] == "unregistered", (
        "an unrecognised refusal must ask a human, not assume the guard is right"
    )


def test_a_fossil_failure_is_waiting_not_broken():
    """S-322: a verdict from an older build is not a judgement on this one."""
    rows = {"rows": [{"loop": "_x", "verdict": "failing", "stale_build": True,
                      "n_consecutive_failures": 4}]}
    assert oc._classify_loops(rows)[0]["remedy_class"] == "waiting"
    rows["rows"][0]["stale_build"] = False
    assert oc._classify_loops(rows)[0]["remedy_class"] == "act_now"


def test_a_retired_source_is_not_an_alarm_but_a_dead_one_is():
    src = {"sources": [
        {"source": "hyperliquid", "verdict": "DEAD", "symbols_recent": 0,
         "symbols_typical": 177, "last_bar": "2026-08-23", "usable_for_returns": False},
        {"source": "some_new_feed", "verdict": "DEAD", "symbols_recent": 0,
         "symbols_typical": 10, "last_bar": "2026-01-01", "usable_for_returns": False},
        # 2026-09-17 dashboard incident: coingecko_pro_ohlc emits verdict='degraded'
        # legitimately (source_freshness.classify line 190-193),but the dispatch
        # table at scripts/ops_console.py was closed against it and surfaced the
        # row as 'unrecognised source verdict'. Add it to the same test row list
        # so this never regresses to a 144/202 panel hole.
        {"source": "coingecko_pro_ohlc", "verdict": "degraded",
         "symbols_recent": 144, "symbols_typical": 202, "last_bar": "2026-09-16",
         "usable_for_returns": True},
    ]}
    got = {i["name"]: i for i in oc._classify_sources(src)}
    assert got["hyperliquid"]["remedy_class"] == "no_action", "retired by policy is not an incident"
    assert got["some_new_feed"]["remedy_class"] == "act_now", (
        "a source that stopped with no policy explaining it IS an incident"
    )
    assert got["coingecko_pro_ohlc"]["remedy_class"] == "act_now", (
        "degraded but not retired is an incident (partial panel; "
        "see S-323n precedent for the usable_for_returns=but-not-full shape)"
    )


def test_a_retired_source_whose_verdict_is_degraded_stays_no_action():
    """Dispatch order regression guard: retired-policy check must come BEFORE the
    verdict-classifier branch. A 'retired-by-policy source that happens to be
    currently degraded' must NOT escalate to act_now (the policy says don't carry
    that source; the partial state is by design)."""
    # eodhd is in RETIRED_BY_POLICY in this layout; pick one that is to make
    # the test ride on real policy state, not a synthetic stub.
    src = {"sources": [
        {"source": "eodhd", "verdict": "degraded", "symbols_recent": 12,
         "symbols_typical": 80, "last_bar": "2026-09-15", "usable_for_returns": True},
    ]} if "eodhd" in oc.RETIRED_BY_POLICY else {
        "sources": [{
            "source": "_test_retired_degraded", "verdict": "degraded",
            "symbols_recent": 1, "symbols_typical": 10, "last_bar": "2026-09-15",
            "usable_for_returns": True,
        }],
    }
    # If RETIRED_BY_POLICY has neither eodhd nor a synthetic match, skip —
    # this guard tests a real shape, not an invented stub.
    if "eodhd" not in oc.RETIRED_BY_POLICY:
        # Inject a synthetic retired-policy entry just for this test, then
        # confirm dispatch puts it at no_action. After test, leave the policy
        # as-is (we did not modify the constant).
        oc.RETIRED_BY_POLICY["_test_retired_degraded"] = "synthetic retired for test"
        try:
            got = oc._classify_sources(src)[0]
            assert got["remedy_class"] == "no_action", (
                "retired-by-policy must NOT escalate on degraded verdict "
                "(dispatch order regression)"
            )
        finally:
            oc.RETIRED_BY_POLICY.pop("_test_retired_degraded", None)
    else:
        got = oc._classify_sources(src)[0]
        assert got["remedy_class"] == "no_action"


def test_market_state_loop_inside_window_is_no_action():
    """REFUSAL_POLICY entry added for _market_state_loop (23 consecutive refusals
    in the S-323 chain). Inside its 7d window the refusal is the guard working —
    no_action, with the S-220 'floor not met' reason surfaced."""
    import time
    pol = oc.REFUSAL_POLICY["_market_state_loop"]
    fresh = {"last_ok_at": time.time() - 1 * 86400}    # 1d ago < 7d window
    assert oc._refusal_overdue(fresh, pol) is False
    rows = {"rows": [{"loop": "_market_state_loop", "verdict": "refused",
                      "stale_build": False, "last_ok_at": fresh["last_ok_at"]}]}
    got = oc._classify_loops(rows)[0]
    assert got["remedy_class"] == "no_action", (
        "23 refusals inside the 7d window = the floor working, not an incident"
    )
    assert "S-220" in got.get("note", "") or "S-220" in pol["reason"]


def test_market_state_loop_past_its_7d_window_becomes_an_alarm():
    """A refusal that persists past its stale_after_days IS the outage — the
    very shape S-296 warns about. _market_state_loop: stale_after_days=7."""
    import time
    pol = oc.REFUSAL_POLICY["_market_state_loop"]
    stale = {"last_ok_at": time.time() - 9 * 86400}    # 9d > 7d
    assert oc._refusal_overdue(stale, pol) is True
    rows = {"rows": [{"loop": "_market_state_loop", "verdict": "refused",
                      "stale_build": False, "last_ok_at": stale["last_ok_at"]}]}
    got = oc._classify_loops(rows)[0]
    assert got["remedy_class"] == "act_now", (
        "the floor itself is the outage if it refuses indefinitely"
    )


def test_fusion_paper_loop_inside_window_is_no_action():
    """_fusion_paper_loop: 5 consecutive refusals, S-336 state-vs-table split.
    Inside its 14d window, no_action with the S-336 WHY surfaced so the operator
    knows the guard is correct (state read empty but nav table non-empty)."""
    import time
    pol = oc.REFUSAL_POLICY["_fusion_paper_loop"]
    fresh = {"last_ok_at": time.time() - 3 * 86400}    # 3d < 14d
    assert oc._refusal_overdue(fresh, pol) is False
    rows = {"rows": [{"loop": "_fusion_paper_loop", "verdict": "refused",
                      "stale_build": False, "last_ok_at": fresh["last_ok_at"]}]}
    got = oc._classify_loops(rows)[0]
    assert got["remedy_class"] == "no_action", (
        "5 refusals inside the 14d window = S-336 guard working, not an incident"
    )
    assert "S-336" in got.get("note", "") or "S-336" in pol["reason"]


def test_fusion_paper_loop_past_its_14d_window_becomes_an_alarm():
    """stale_after_days=14 for _fusion_paper_loop. Past it = act_now."""
    import time
    pol = oc.REFUSAL_POLICY["_fusion_paper_loop"]
    stale = {"last_ok_at": time.time() - 21 * 86400}   # 21d > 14d
    assert oc._refusal_overdue(stale, pol) is True
    rows = {"rows": [{"loop": "_fusion_paper_loop", "verdict": "refused",
                      "stale_build": False, "last_ok_at": stale["last_ok_at"]}]}
    got = oc._classify_loops(rows)[0]
    assert got["remedy_class"] == "act_now", (
        "a guard refusing past its own declared window is itself the outage"
    )
