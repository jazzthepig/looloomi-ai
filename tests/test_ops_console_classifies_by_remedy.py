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
    ]}
    got = {i["name"]: i["remedy_class"] for i in oc._classify_sources(src)}
    assert got["hyperliquid"] == "no_action", "retired by policy is not an incident"
    assert got["some_new_feed"] == "act_now", (
        "a source that stopped with no policy explaining it IS an incident"
    )
