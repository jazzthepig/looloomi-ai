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
        "_hl_book_loop":          "S-413",
        "_tokenization_tilt_loop": "S-427",
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
        # legitimately (source_freshness.classify line 190-193), but the dispatch
        # table at scripts/ops_console.py was closed against it and surfaced the
        # row as 'unrecognised source verdict'. Add it to the same test row list
        # so this never regresses to a 144/202 panel hole.
        #
        # S-378b-6 (2026-09-20) SUPERSEDES the S-323n precedent for THIS source:
        # coingecko_pro_ohlc is now in SOURCE_DOCKETED_BY_POLICY (maintained
        # crypto feed, partial by coin_id mapping not data). Degraded on a
        # docked source is no_action with the docket reason, NOT act_now.
        {"source": "coingecko_pro_ohlc", "verdict": "degraded",
         "symbols_recent": 144, "symbols_typical": 202, "last_bar": "2026-09-16",
         "usable_for_returns": True},
    ]}
    got = {i["name"]: i for i in oc._classify_sources(src)}
    assert got["hyperliquid"]["remedy_class"] == "no_action", "retired by policy is not an incident"
    assert got["some_new_feed"]["remedy_class"] == "act_now", (
        "a source that stopped with no policy explaining it IS an incident"
    )
    assert got["coingecko_pro_ohlc"]["remedy_class"] == "no_action", (
        "S-378b-6: coingecko_pro_ohlc is in SOURCE_DOCKETED_BY_POLICY; degraded "
        "verdict short-circuits to no_action with the docket reason. (Prior S-323n "
        "behaviour — act_now on partial panel — is superseded for THIS source. "
        "Other degraded-but-undocketed sources still hit act_now, see "
        "test_an_undocketed_degraded_source_still_lands_act_now.)"
    )
    assert "S-378b-6" in got["coingecko_pro_ohlc"]["note"], (
        f"docket note must carry its S-number so the operator can find the "
        f"rationale; got: {got['coingecko_pro_ohlc']['note']!r}"
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


def test_two_layer_paper_nav_dead_is_no_action_with_r57_note():
    """R57: two_layer_paper_nav is structurally dead (V5c core retired). The
    loop-side REFUSAL_POLICY entry for _two_layer_paper_loop already says so;
    the book-side mirror here must agree. Otherwise the same object renders
    differently on its two views (an incident on one, no_action on the other)."""
    producers = {"tables": {
        "two_layer_paper_nav": {
            "verdict": "dead",
            "n_rows": 28,
            "event": {"last": "2026-08-14"},
            "write": {"last": "2026-08-14"},
        },
    }}
    rows = oc._classify_books(producers)
    got = {r["name"]: r for r in rows}
    assert "two_layer_paper_nav" in got
    item = got["two_layer_paper_nav"]
    assert item["remedy_class"] == "no_action", (
        f"R57 retired book must not render as act_now; got {item['remedy_class']!r}"
    )
    assert "R57" in item["note"], (
        f"no_action without R57 is just 'silent' — note must name the retirement "
        f"so the operator knows it's by design. Got: {item['note']!r}"
    )
    # Also verify the loop-side policy and book-side note cite the SAME R-number
    # (mirror check — same retirement, same reference, two angles).
    assert "R57" in oc.REFUSAL_POLICY["_two_layer_paper_loop"]["reason"]


def test_other_dead_book_is_still_act_now():
    """Regression guard: the two_layer_paper_nav carve-out is specific. A
    different book with a 'dead' verdict must still render as act_now. If this
    test fails, somebody widened the carve-out without thinking — likely a
    refactor to BOOK_RETIRED_BY_POLICY that incorrectly classified something."""
    producers = {"tables": {
        "third_paper_nav": {
            "verdict": "dead",
            "n_rows": 5,
            "event": {"last": "2026-08-01"},
            "write": {"last": "2026-08-01"},
        },
    }}
    rows = oc._classify_books(producers)
    got = {r["name"]: r for r in rows}
    assert "third_paper_nav" in got
    item = got["third_paper_nav"]
    assert item["remedy_class"] == "act_now", (
        f"a book that isn't retired-by-policy but stopped marking IS an "
        f"incident (gap in the record cannot be backfilled, §3). "
        f"Got: {item['remedy_class']!r} for {item['name']!r}"
    )
    assert "R57" not in item["note"], (
        "R57 must not appear on a book that wasn't the R57 retirement — that "
        "would be a misattribution"
    )


# ─── S-378b-5: REFUSAL_POLICY auto-escalate rule (parallel signal) ──────────
#
# S-296: 「一个只拦不导的守卫,会把违规变成缺口」. The existing rule escalates
# when a refusal PERSISTS past its `stale_after_days` TIME window. But a guard
# can also fail systematically in a tight loop — 3 refusals in 3 days, window
# is 30d — and the time-only rule says "no_action, sit and wait". That hides
# a real pattern. S-378b-5 adds a parallel opt-in signal:
#
#     pol["escalate_after_n_refusals"]: int
#
# When `n_consecutive_refusals >= escalate_after_n_refusals`, the refusal
# escalates to `act_now` EVEN INSIDE the time window. Absent key = no
# refusal-count escalation (conservative default — opt-in, not silent on).
#
# The two signals are OR'd: a stale-or-piling-up refusal is an alarm;
# a fresh AND low-count refusal is no_action (the guard is working).
#
# _two_layer_paper_loop DELIBERATELY has no `escalate_after_n_refusals` —
# it is R57-retired (V5c core dead by design), so piling-up refusals is
# not an incident, it is the spec.


def test_escalate_after_n_refusals_above_threshold_is_act_now_inside_window():
    """Parallel signal: 5 consecutive refusals inside a 30d window against an
    escalate_after_n_refusals=3 threshold is `act_now`. Time-only rule says
    no_action (1d < 30d); count rule says act_now (5 > 3). Count wins."""
    import time
    rows = {"rows": [{
        "loop": "_escalation_count_test",
        "verdict": "refused",
        "stale_build": False,
        "last_ok_at": time.time() - 1 * 86400,        # 1d ago — INSIDE window
        "n_consecutive_refusals": 5,
    }]}
    # Inject a synthetic policy entry with the new key, then classify.
    pol = {
        "reason": "S-378b-5 synthetic — refusing 5x, threshold 3",
        "clears_when": "the count test removes this entry",
        "owner": "Seth",
        "stale_after_days": 30,
        "escalate_after_n_refusals": 3,
    }
    oc.REFUSAL_POLICY["_escalation_count_test"] = pol
    try:
        got = oc._classify_loops(rows)[0]
        assert got["remedy_class"] == "act_now", (
            f"5 consecutive refusals against threshold 3 inside a 30d window "
            f"is a systematic failure (count signal beat time signal); "
            f"got {got['remedy_class']!r}"
        )
        assert "CONSECUTIVE REFUSALS" in got["note"], (
            f"act_now note must explain WHICH signal fired (count, not time); "
            f"got note: {got['note']!r}"
        )
    finally:
        oc.REFUSAL_POLICY.pop("_escalation_count_test", None)


def test_escalate_after_n_refusals_below_threshold_is_no_action_inside_window():
    """Count below threshold + inside time window = no_action. Both signals
    silent = the guard is working (refusing correctly for the right reason)."""
    import time
    rows = {"rows": [{
        "loop": "_escalation_below_test",
        "verdict": "refused",
        "stale_build": False,
        "last_ok_at": time.time() - 1 * 86400,        # 1d ago
        "n_consecutive_refusals": 2,                  # < threshold 3
    }]}
    pol = {
        "reason": "S-378b-5 synthetic — refusing 2x, threshold 3",
        "clears_when": "the below test removes this entry",
        "owner": "Seth",
        "stale_after_days": 30,
        "escalate_after_n_refusals": 3,
    }
    oc.REFUSAL_POLICY["_escalation_below_test"] = pol
    try:
        got = oc._classify_loops(rows)[0]
        assert got["remedy_class"] == "no_action", (
            f"2 refusals < 3 threshold AND 1d < 30d window = guard is working. "
            f"got {got['remedy_class']!r}"
        )
        # no_action note should NOT carry the alarm signals
        assert "CONSECUTIVE REFUSALS" not in got["note"], (
            "below-threshold refusal must not render the alarm note"
        )
        assert "REFUSING LONGER THAN" not in got["note"], (
            "inside-window refusal must not render the time-alarm note"
        )
    finally:
        oc.REFUSAL_POLICY.pop("_escalation_below_test", None)


def test_escalate_after_n_refusals_absent_key_means_no_count_escalation():
    """Absent `escalate_after_n_refusals` key = NO count escalation. Existing
    entries without the key must behave exactly as before (regression)."""
    import time
    rows = {"rows": [{
        "loop": "_no_count_key_test",
        "verdict": "refused",
        "stale_build": False,
        "last_ok_at": time.time() - 1 * 86400,        # 1d ago
        "n_consecutive_refusals": 999,                # huge, but no key
    }]}
    pol = {
        "reason": "r", "clears_when": "c", "owner": "o",
        "stale_after_days": 30,
        # NOTE: no escalate_after_n_refusals
    }
    oc.REFUSAL_POLICY["_no_count_key_test"] = pol
    try:
        got = oc._classify_loops(rows)[0]
        assert got["remedy_class"] == "no_action", (
            f"no-key entries must NOT escalate by count; got {got['remedy_class']!r}"
        )
    finally:
        oc.REFUSAL_POLICY.pop("_no_count_key_test", None)


def test_both_signals_firing_still_act_now_with_both_in_note():
    """Both signals firing (time overdue AND count above threshold) = act_now
    with both reasons in the note (operator sees which signals are firing)."""
    import time
    rows = {"rows": [{
        "loop": "_both_signals_test",
        "verdict": "refused",
        "stale_build": False,
        "last_ok_at": time.time() - 60 * 86400,       # 60d — past 30d window
        "n_consecutive_refusals": 10,                 # > threshold 3
    }]}
    pol = {
        "reason": "r", "clears_when": "c", "owner": "o",
        "stale_after_days": 30,
        "escalate_after_n_refusals": 3,
    }
    oc.REFUSAL_POLICY["_both_signals_test"] = pol
    try:
        got = oc._classify_loops(rows)[0]
        assert got["remedy_class"] == "act_now"
        # Time signal fires FIRST in the note (S-296: persistent refusal
        # is the canonical outage; count is the secondary signal).
        assert "REFUSING LONGER THAN ITS 30d WINDOW" in got["note"], (
            f"both-signals note must cite the time-window signal first; "
            f"got note: {got['note']!r}"
        )
    finally:
        oc.REFUSAL_POLICY.pop("_both_signals_test", None)


def test_every_refusal_policy_keeps_its_stale_after_days():
    """S-378b-5 is ADDITIVE: every existing REFUSAL_POLICY entry still has its
    `stale_after_days` (the existing time-only rule must not regress). A missing
    integer `stale_after_days` is what test_every_refusal_policy_declares_...
    already enforces; this test only confirms none were dropped."""
    for name, pol in oc.REFUSAL_POLICY.items():
        assert "stale_after_days" in pol, (
            f"{name} lost stale_after_days — time-only auto-escalate regressed"
        )
        assert isinstance(pol["stale_after_days"], int), name


# ─── S-378b-6: SOURCE_DOCKETED_BY_POLICY (different slot from RETIRED) ──────
#
# Retirement = "STOP carrying this source" (S-296 / S-323n). Strong move.
# Docket     = "CONTINUE carrying this source; current state is known and
#             acceptable as-is for some defined window." Weaker move — the
#             operator is still on the hook to revisit, but not now.
#
# Concretely: coingecko_pro_ohlc today is `verdict=degraded /
# usable=True / 159/203`. It is our maintained crypto feed (no other
# covers the same panel); the gap is coin_id-mapping, not data. The
# existing dispatch renders it `act_now` per test_a_retired_source_is_not_...
# S-378b-6 says: docket it. The dispatch must short-circuit `degraded`
# to `no_action` when the source is in SOURCE_DOCKETED_BY_POLICY, before
# falling through to the act_now "investigate before next cadence" path.
#
# Three tests:
#   1. docketed + degraded → no_action (with docket reason)
#   2. undocketed + degraded → act_now (regression)
#   3. docketed but verdict moves from degraded → flowing → still ok
#      (flowing is the GOOD state; docket must not over-rule)
#
# Dispatch position: docketed-degraded branch sits between
#   "degraded AND retired"  (no_action, retired reason)
# and
#   "degraded"              (act_now, generic reason)
# so retired → docketed → undocketed in descending strength (retirement
# beats docket because retirement means "don't carry at all").


def test_a_docketed_degraded_source_is_no_action():
    """S-378b-6: coingecko_pro_ohlc (maintained crypto feed, panel 159/203 by
    coin_id mapping not by data gap) is `degraded / usable_for_returns=True`.
    Without docket, this lands as `act_now` (the old behaviour). With docket,
    it is no_action and the operator knows WHY (the docket reason quotes
    S-377 evidence: the partial panel is by design)."""
    src = {"sources": [{
        "source": "coingecko_pro_ohlc", "verdict": "degraded",
        "symbols_recent": 159, "symbols_typical": 203,
        "last_bar": "2026-09-19", "usable_for_returns": True,
    }]}
    # Inject a synthetic docket entry with the new key, then classify.
    docket = ("S-378b-6 synthetic — coin_id mapping gap, not a data gap; "
              "159/203 covers all required returns for the panel")
    oc.SOURCE_DOCKETED_BY_POLICY["coingecko_pro_ohlc"] = docket
    try:
        got = {i["name"]: i for i in oc._classify_sources(src)}
        assert got["coingecko_pro_ohlc"]["remedy_class"] == "no_action", (
            f"a docketed degraded source must short-circuit to no_action "
            f"(not act_now); got {got['coingecko_pro_ohlc']['remedy_class']!r}"
        )
        assert docket in got["coingecko_pro_ohlc"]["note"], (
            f"note must cite the docket reason so the operator can SEE it's "
            f"deferred-by-policy, not silently excused. got note: "
            f"{got['coingecko_pro_ohlc']['note']!r}"
        )
    finally:
        oc.SOURCE_DOCKETED_BY_POLICY.pop("coingecko_pro_ohlc", None)


def test_an_undocketed_degraded_source_still_lands_act_now():
    """Regression: a degraded source NOT in SOURCE_DOCKETED_BY_POLICY must
    keep its old behaviour (act_now with 'investigate before next cadence').
    S-378b-6 is scoped: opt-in per source, not a global reclassification."""
    src = {"sources": [{
        "source": "some_new_feed_we_dont_know_about",
        "verdict": "degraded",
        "symbols_recent": 12, "symbols_typical": 80,
        "last_bar": "2026-09-19", "usable_for_returns": True,
    }]}
    got = {i["name"]: i for i in oc._classify_sources(src)}
    assert got["some_new_feed_we_dont_know_about"]["remedy_class"] == "act_now", (
        f"a degraded source not in the docket must still escalate; got "
        f"{got['some_new_feed_we_dont_know_about']['remedy_class']!r}"
    )


def test_a_docketed_source_does_not_overrule_a_flowing_verdict():
    """Defensive: docketing only matters when the source is in trouble. A
    docketed source that recovers to `flowing` is `ok`, not `no_action` —
    because the operator WANTS to see the green when it returns (the docket
    is about deferring pain, not about never showing green)."""
    src = {"sources": [{
        "source": "coingecko_pro_ohlc", "verdict": "flowing",
        "symbols_recent": 203, "symbols_typical": 203,
        "last_bar": "2026-09-19", "usable_for_returns": True,
    }]}
    oc.SOURCE_DOCKETED_BY_POLICY["coingecko_pro_ohlc"] = (
        "S-378b-6 synthetic — would-be docket; test confirms flowing still wins"
    )
    try:
        got = {i["name"]: i for i in oc._classify_sources(src)}
        assert got["coingecko_pro_ohlc"]["remedy_class"] == "ok", (
            f"flowing on a docketed source must still be ok (operator wants "
            f"to see recovery); got {got['coingecko_pro_ohlc']['remedy_class']!r}"
        )
    finally:
        oc.SOURCE_DOCKETED_BY_POLICY.pop("coingecko_pro_ohlc", None)


# ── S-378b-A2 ──────────────────────────────────────────────────────────────
# 4 paper-book force-mark beats (_book_factor_tilt_loop, _book_fusion_loop,
# _book_pod_aggregator_loop, _book_two_layer_loop) all land at stale_build=True
# after the S-378b force-mark verifications. The dashboard was rendering them
# as 4 of the "8 broken loops" because it counted every verdict != ok —
# including fossils. _classify_loops already maps stale_build→waiting, but a
# specific regression test pins the four known offenders.

def test_s378b_a2_book_force_mark_fossils_are_waiting_not_broken():
    """S-378b-A2: S-378b-1.3 / 2.4 / 3 / 4 force-mark verification left four
    `_book_*_loop` stale fossil beats (build 3161dd93 vs current 4b6bba55).
    Even with HTTP 409 or empty-error conditions, they MUST classify as
    `waiting` — the loop hasn't run on the current build yet, so any verdict
    is the previous build's news, not an actionable failure."""
    fossil_loops = [
        "_book_factor_tilt_loop",
        "_book_fusion_loop",
        "_book_pod_aggregator_loop",
        "_book_two_layer_loop",
    ]
    rows = {"rows": []}
    for name in fossil_loops:
        rows["rows"].append({
            "loop": name,
            "verdict": "failing",
            "stale_build": True,
            "build": "3161dd93",
            "n_consecutive_failures": 1,
            "last_error": "" if name != "_book_fusion_loop" else
                "durable_write_failed :: HTTP 409 duplicate key (mark_date)=2026-09-20",
            "last_ok_at": None,
            "last_run_at": 1789890948,
        })
    out = {it["name"]: it for it in oc._classify_loops(rows)}
    for name in fossil_loops:
        assert name in out, f"missing entry for {name}"
        assert out[name]["remedy_class"] == "waiting", (
            f"{name} is a stale fossil (build 3161dd93 != current 4b6bba55) and "
            f"MUST be `waiting` not `act_now`; got {out[name]['remedy_class']!r}. "
            f"This is the S-322 / S-378b-A2 fossil-not-broken discipline — a "
            f"verdict from the old build is not a judgement on the new one."
        )


# ── S-378b-A1 ──────────────────────────────────────────────────────────────
# force_mark.py used to pass `(result or {}).get("error")` directly to beat.
# Many books write the failure reason into `reason` / `note` / `phase` instead
# of `error` — the beat landed in Redis with `last_error=""`, and the dashboard
# could not diagnose ("you cannot debug a blank"). Verify the helper derives a
# non-empty string from any of the four plausible fields, and synthesizes a
# clear "book returned <status> with no error field" if all are empty.

def test_s378b_a1_force_mark_derives_error_from_error_field():
    """Most direct path: book returns {"error": "..."}."""
    from src.api.routers import force_mark as fm
    _err = fm._derive_force_mark_error(
        book="factor_tilt", ok=False, status="mark_failed",
        result={"error": "missing_price:BTC"},
    )
    assert _err == "missing_price:BTC", (
        f"direct .error field should pass through; got {_err!r}"
    )


def test_s378b_a1_force_mark_falls_back_to_reason_note_phase():
    """Books that write into reason / note / phase must still surface context."""
    from src.api.routers import force_mark as fm
    for field, value in [
        ("reason", "insufficient_live_data"),
        ("note", "no_rows"),
        ("phase", "write"),
    ]:
        _err = fm._derive_force_mark_error(
            book="two_layer", ok=False, status="skipped",
            result={field: value},
        )
        assert _err == value, (
            f"fallback to {field!r} should surface {value!r}; got {_err!r}"
        )


def test_s378b_a1_force_mark_synthesizes_when_all_fields_empty():
    """When the book returns no error/reason/note/phase, the helper synthesizes
    a clear, actionable message — never an empty string. This is the S-323z
    'you cannot debug a blank' discipline at the source."""
    from src.api.routers import force_mark as fm
    _err = fm._derive_force_mark_error(
        book="pod_aggregator", ok=False, status="degraded",
        result={"status": "degraded", "nav_persisted": False},
    )
    assert _err and _err.strip(), (
        f"empty-input must still produce non-empty error context; got {_err!r}"
    )
    assert "pod_aggregator" in _err, (
        f"synthesized message must name the book (so operator knows WHICH book "
        f"has the failure-shape wrong); got {_err!r}"
    )
    assert "degraded" in _err, (
        f"synthesized message must include the status (the operator needs the "
        f"state, not just the book name); got {_err!r}"
    )
    assert ("error" in _err and "reason" in _err and "note" in _err
            and "phase" in _err), (
        f"synthesized message must point at which fields the book SHOULD have "
        f"written into; got {_err!r}"
    )


def test_s378b_a1_force_mark_no_error_when_ok():
    """When ok=True, the helper returns None — beats store last_error=None then."""
    from src.api.routers import force_mark as fm
    assert fm._derive_force_mark_error(
        book="factor_tilt", ok=True, status="ok",
        result={"status": "ok"},
    ) is None


# ── S-378b-B ───────────────────────────────────────────────────────────────
# force_mark.py used to invoke the book even when today's row already existed
# (cron wrote at 00:05 UTC; operator-verified at 07:55 UTC). That caused
# `durable_write_failed :: HTTP 409` to land on the liveness beat as the
# last_error for every force-mark verification. The fix short-circuits with
# `{"status": "already_marked", ...}` and fires the beat as refused (so the
# failure counter stays clean).

def test_s378b_b_force_mark_short_circuits_when_today_row_exists():
    """S-378b-B: when nav_row_exists returns True for today, force_mark must
    NOT invoke the book; it returns already_marked, ok=True, no HTTP 409.

    Pure-function level: verify `_already_marked_response` builds the right
    shape (no I/O — the actual call path uses nav_row_exists which is mocked
    in the higher-level integration test)."""
    from src.api.routers import force_mark as fm
    resp = fm._already_marked_response(
        book="fusion", today="2026-09-20", nav_table="fusion_paper_nav",
    )
    assert resp["ok"] is True, (
        f"already_marked must be ok=True (the work is done); got {resp['ok']!r}"
    )
    assert resp["wrote"] is False, (
        f"already_marked must NOT have written (the row was already there); "
        f"got wrote={resp['wrote']!r}"
    )
    assert resp["phase"] == "idempotent_short_circuit", (
        f"phase must say 'idempotent_short_circuit' so the operator can "
        f"distinguish this from a real mark; got {resp['phase']!r}"
    )
    assert resp["mark_status"] == "already_marked", (
        f"mark_status must surface 'already_marked' (so dashboard classify() "
        f"maps to NO_WORK_STATUS → refused=True, failure counter clean); "
        f"got {resp['mark_status']!r}"
    )
    assert resp["result"]["status"] == "already_marked", (
        f"result.status must be 'already_marked' for the inner book-shape "
        f"contract; got {resp['result']['status']!r}"
    )
    assert "force_overwrite" in resp["reading"], (
        f"reading must tell the operator how to force-replace (rare but real); "
        f"got reading: {resp['reading']!r}"
    )


def test_s378b_b_force_mark_does_not_short_circuit_on_force_overwrite():
    """force_overwrite=true must skip the already_marked short-circuit and
    proceed to actually invoke the book (or, when no row exists, to behave
    normally). The signal is the function-level skip — verify the public API
    exposes force_overwrite as a query parameter that flows through."""
    import inspect
    from src.api.routers.force_mark import force_mark
    sig = inspect.signature(force_mark)
    assert "force_overwrite" in sig.parameters, (
        f"force_mark must accept force_overwrite query param; got params: "
        f"{list(sig.parameters.keys())!r}"
    )
    assert sig.parameters["force_overwrite"].default is False, (
        f"force_overwrite default must be False (idempotent by default); "
        f"got default: {sig.parameters['force_overwrite'].default!r}"
    )


def test_s378b_b_force_mark_force_overwrite_skips_short_circuit(monkeypatch):
    """End-to-end-ish: with force_overwrite=True, the short-circuit is
    skipped even when nav_row_exists returns True. We mock nav_row_exists
    to always return True, and assert that import_module gets called (proving
    the short-circuit was bypassed)."""
    import asyncio
    from src.api.routers import force_mark as fm

    # Mock nav_row_exists to always say "row exists"
    async def _always_exists(table, day):
        return True

    # Mock importlib.import_module to record the call
    import importlib
    import_calls: list[str] = []
    real_import_module = importlib.import_module

    def _spy(name, *args, **kwargs):
        import_calls.append(name)
        # Return a fake module with a mark_and_rebalance that records it was called
        if "fusion_paper" in name:
            mod = real_import_module(name)
            orig = mod.mark_and_rebalance

            async def _fake(*a, **kw):
                import_calls.append("book_called")
                return {"status": "ok", "nav": 1.0}
            mod.mark_and_rebalance = _fake
            return mod
        return real_import_module(name, *args, **kwargs)

    monkeypatch.setattr("src.data.signals.nav_persist.nav_row_exists", _always_exists)
    monkeypatch.setattr(importlib, "import_module", _spy)

    # Use the X-Internal-Token header — must come from env
    import os
    os.environ.setdefault("INTERNAL_TOKEN", "cometcloud_internal_2026")

    resp = asyncio.run(fm.force_mark(
        book="fusion",
        dry_run=False,
        force_overwrite=True,
        x_internal_token="cometcloud_internal_2026",
    ))
    # With force_overwrite=True, the short-circuit was skipped and the book
    # was actually invoked (or attempted to be).
    assert resp.get("phase") != "idempotent_short_circuit", (
        f"force_overwrite=True must skip the short-circuit; got phase: "
        f"{resp.get('phase')!r}. Full response: {resp!r}"
    )


def test_s378b_b_force_mark_short_circuit_path(monkeypatch):
    """Without force_overwrite, when nav_row_exists returns True, the
    response is the already_marked short-circuit (no book invocation)."""
    import asyncio
    import importlib
    from src.api.routers import force_mark as fm

    async def _always_exists(table, day):
        return True

    import_calls: list[str] = []
    real_import_module = importlib.import_module

    def _spy(name, *args, **kwargs):
        import_calls.append(name)
        return real_import_module(name, *args, **kwargs)

    monkeypatch.setattr("src.data.signals.nav_persist.nav_row_exists", _always_exists)
    monkeypatch.setattr(importlib, "import_module", _spy)
    import os
    os.environ.setdefault("INTERNAL_TOKEN", "cometcloud_internal_2026")

    resp = asyncio.run(fm.force_mark(
        book="fusion",
        dry_run=False,
        force_overwrite=False,
        x_internal_token="cometcloud_internal_2026",
    ))
    assert resp.get("phase") == "idempotent_short_circuit", (
        f"with no force_overwrite and row-exists, the short-circuit MUST fire; "
        f"got phase: {resp.get('phase')!r}. Full response: {resp!r}"
    )
    assert resp.get("ok") is True
    # importlib.import_module must NOT have been called for the book module
    book_imports = [c for c in import_calls if "fusion_paper" in c]
    assert not book_imports, (
        f"short-circuit must skip the book import; got: {book_imports!r}"
    )
