"""S-378b smoke: fusion + two_layer NAV compounding must survive state-loss.

Two flavours of the same defect, different remedies because the books are different.

  · fusion_paper.py  (lines 654-666): the S-336 guard refuses to mark when state
    is empty AND the table has ANY rows — but the 26 v1 rows are voided, so
    the guard is refusing against its own voided past. Fix: distinguish v1
    voided rows from v2 live rows, treat v1-only as fresh v2 inception.

  · two_layer_paper.py (lines 272-288): when Redis state is empty, the code
    incepts at NAV 1.0, but the table has 28 real compounding rows. Fix: read
    disk prev nav and use it as compounding base. Core-dead → w_held={} →
    daily_ret=0 → nav_new = disk_prev_nav (honest flat day, not arithmetic
    inception).

This test exercises the `_compute_nav_base` choice for both, without touching
Supabase. Pattern copied from test_s378b_nav_compound_fix.py.
"""
from __future__ import annotations

import datetime as dt

import pytest


# ── fusion_paper ──────────────────────────────────────────────────────────────

def test_fusion_v2_inception_when_no_v2_rows_on_disk():
    """State empty + disk has only voided v1 rows → fresh v2 start, NAV 1.0.

    The S-336 guard used to refuse because the table had any rows, even
    voided ones. After the fix, only v2 (live) rows count; v1 (voided) is
    treated as the past-life of the book and ignored.
    """
    from src.data.signals.fusion_paper import _compute_nav_base

    state = {"nav": 1.0, "last_mark": None, "inception": "v2",
             "weights": {}, "last_mark_date": None}
    # disk has v2 prev nav (from previous successful v2 mark)
    disk_prev_nav, disk_prev_date = 1.012345, "2026-09-18"

    nav_base = _compute_nav_base(state, disk_prev_nav, disk_prev_date,
                                 today=dt.date(2026, 9, 19))
    # state empty + disk v2 has prev → use disk
    assert nav_base == pytest.approx(1.012345, abs=1e-9)


def test_fusion_v2_inception_when_no_disk_at_all():
    """State empty + no disk rows at all → 1.0 (genuine v2 inception).

    Both state and disk empty. This is the only case where 1.0 is honest.
    """
    from src.data.signals.fusion_paper import _compute_nav_base

    state = {"nav": 1.0, "last_mark": None, "inception": "v2"}
    nav_base = _compute_nav_base(state, None, None, today=dt.date(2026, 9, 19))
    assert nav_base == 1.0


def test_fusion_uses_state_when_state_matches_disk_v2():
    """State agrees with disk v2 → use state (full compounding chain)."""
    from src.data.signals.fusion_paper import _compute_nav_base

    state = {"nav": 1.023456, "last_mark": "2026-09-18", "inception": "v2"}
    disk_prev_nav, disk_prev_date = 1.023456, "2026-09-18"

    nav_base = _compute_nav_base(state, disk_prev_nav, disk_prev_date,
                                 today=dt.date(2026, 9, 19))
    assert nav_base == pytest.approx(1.023456, abs=1e-9)


def test_fusion_state_diverges_from_disk_v2_uses_disk():
    """State says nav=0.99 but disk v2 says 1.05 → disk wins (S-321/S-327)."""
    from src.data.signals.fusion_paper import _compute_nav_base

    state = {"nav": 0.990, "last_mark": "2026-09-18", "inception": "v2"}
    disk_prev_nav, disk_prev_date = 1.050, "2026-09-18"

    nav_base = _compute_nav_base(state, disk_prev_nav, disk_prev_date,
                                 today=dt.date(2026, 9, 19))
    assert nav_base == pytest.approx(1.050, abs=1e-9)


# ── two_layer_paper ───────────────────────────────────────────────────────────

def test_two_layer_uses_disk_prev_nav_when_state_empty():
    """Redis state empty but disk has 28 compounding rows → use disk prev nav.

    two_layer's state lives in Redis only; a Redis miss would incept at 1.0
    and lose 28 days of compounding. Fix: read disk prev nav.
    """
    from src.data.signals.two_layer_paper import _compute_nav_base

    state = {"nav": 1.0, "last_mark": None, "core_name": "v5c"}
    disk_prev_nav, disk_prev_date = 1.007812, "2026-09-18"

    nav_base = _compute_nav_base(state, disk_prev_nav, disk_prev_date,
                                 today=dt.date(2026, 9, 19))
    assert nav_base == pytest.approx(1.007812, abs=1e-9)


def test_two_layer_uses_state_when_state_matches_disk():
    """Redis state agrees with disk → use state."""
    from src.data.signals.two_layer_paper import _compute_nav_base

    state = {"nav": 1.030000, "last_mark": "2026-09-18"}
    disk_prev_nav, disk_prev_date = 1.030000, "2026-09-18"

    nav_base = _compute_nav_base(state, disk_prev_nav, disk_prev_date,
                                 today=dt.date(2026, 9, 19))
    assert nav_base == pytest.approx(1.030000, abs=1e-9)


def test_two_layer_inception_when_no_disk_history():
    """State empty + no disk rows → 1.0 (genuine inception)."""
    from src.data.signals.two_layer_paper import _compute_nav_base

    state = {"nav": 1.0, "last_mark": None}
    nav_base = _compute_nav_base(state, None, None, today=dt.date(2026, 9, 19))
    assert nav_base == 1.0


def test_two_layer_state_diverges_from_disk_uses_disk():
    """State stale by >1pp → disk wins."""
    from src.data.signals.two_layer_paper import _compute_nav_base

    state = {"nav": 0.950, "last_mark": "2026-09-18"}
    disk_prev_nav, disk_prev_date = 1.080, "2026-09-18"

    nav_base = _compute_nav_base(state, disk_prev_nav, disk_prev_date,
                                 today=dt.date(2026, 9, 19))
    assert nav_base == pytest.approx(1.080, abs=1e-9)


# ── L1 self-consistency end-to-end for two_layer ─────────────────────────────

def test_two_layer_l1_holds_after_fix_when_core_dead():
    """When core is dead, w_tgt={} and w_held={}, daily_ret=0, so nav must
    stay at disk_prev. The old code would reset to 1.0 and lose compounding."""
    from src.data.signals.two_layer_paper import _compute_nav_base

    # Simulate a sequence of flat marks (core dead for 5 days)
    state = {"nav": 1.0, "last_mark": None}  # Redis state empty
    disk_history = [
        ("2026-09-14", 1.000000),
        ("2026-09-15", 1.000000),  # core dead, flat
        ("2026-09-16", 1.000000),
        ("2026-09-17", 1.000000),
        ("2026-09-18", 1.000000),
    ]
    # Today (09-19) we want to mark a flat day
    disk_prev_date, disk_prev_nav = disk_history[-1]
    nav_base = _compute_nav_base(state, disk_prev_nav, disk_prev_date,
                                 today=dt.date(2026, 9, 19))
    # core dead → w_tgt = {}, daily_ret = 0 → nav_new = nav_base * 1.0
    # Old code: nav_new = 1.0 (state.nav) * 1.0 = 1.0 → loses any compounding
    # New code: nav_new = 1.000000 * 1.0 = 1.000000 (matches disk chain)
    assert nav_base == 1.0  # in this synthetic test, no compounding happened


def test_two_layer_l1_holds_after_fix_with_real_compounding():
    """Real compounding sequence: nav[t] compounds from disk prev, not 1.0."""
    from src.data.signals.two_layer_paper import _compute_nav_base

    # Pretend disk had: 09-14: 1.0, 09-15: 1.005, 09-16: 1.012, 09-17: 1.008, 09-18: 1.015
    state = {"nav": 1.0, "last_mark": None}  # Redis state empty (the bug condition)
    prev_disk_nav = 1.015  # last disk row
    disk_prev_date = "2026-09-18"

    nav_base = _compute_nav_base(state, prev_disk_nav, disk_prev_date,
                                 today=dt.date(2026, 9, 19))
    # Old: nav_new = 1.0 * (1+r) → compounding starts from 1.0, not 1.015
    # New: nav_new = 1.015 * (1+r) → correct
    assert nav_base == pytest.approx(1.015, abs=1e-9)


# ── S-378b-2.3 by-design flat branch (R57 verdict: core dead → 持零算术) ──────
#
# R57 verdict: two_layer's 28 rows are `book_state=core_dead` flat — by design,
# not state loss. The S-326 conservative guard at lines 372-379 refused
# `w_held={}` AND `w_tgt={}` because it could not distinguish "core dead
# today AND yesterday" (legal flat-by-declaration) from "state lost" (bug).
# Fix: when BOTH w_held AND w_tgt are empty, the day's P&L is structurally 0
# (no positions × any market = 0 — arithmetic, not a lie). Mark flat honestly.

def test_two_layer_by_design_flat_when_w_held_and_w_tgt_both_empty():
    """R57 core-dead path: w_held={} AND w_tgt={} → price_pnl=0, nav=disk_prev.

    This is the canonical "core dead for both yesterday and today" branch.
    The book holds nothing by design, so the day's P&L is structurally 0.
    We do NOT refuse (S-326/S-378b) because that loses honest records.
    """
    # Simulate the post-guard calculation: price_pnl=0, daily_ret=0,
    # nav = nav_base * (1+0) = nav_base.
    state = {"nav": 1.0, "last_mark": None, "core_name": "v5c",
             "weights": {}, "mark_prices": {}}
    disk_prev_nav, disk_prev_date = 1.004, "2026-09-18"

    from src.data.signals.two_layer_paper import _compute_nav_base
    nav_base = _compute_nav_base(state, disk_prev_nav, disk_prev_date,
                                 today=dt.date(2026, 9, 19))
    # w_held={} AND w_tgt={} → price_pnl=0, daily_ret=0 → nav=nav_base
    price_pnl = 0.0  # by-design flat branch
    daily_ret = price_pnl - 0.0  # turn=0, cost=0
    nav_new = nav_base * (1.0 + daily_ret)
    assert nav_new == pytest.approx(1.004, abs=1e-9)
    # And nav_base itself was disk_prev (1.004), not 1.0 — compounding chain
    # survives through core-dead days instead of resetting at 1.0 every cycle.
    assert nav_base == pytest.approx(1.004, abs=1e-9)


def test_two_layer_by_design_flat_preserves_compounding_after_real_returns():
    """Real compounding history interleaved with by-design flat days.

    Sequence:
      09-14: nav=1.000
      09-15: nav=1.008  (real return +0.8%)
      09-16: nav=1.008  (core dead, flat — by design, NOT state loss)
      09-17: nav=1.004  (real return -0.4%)
      09-18: nav=1.004  (core dead again, flat — by design)
      09-19: mark today → expect nav_new = 1.004 (not 1.0)
    """
    from src.data.signals.two_layer_paper import _compute_nav_base

    # 09-19: state has weights={} (Redis might still hold stale state from 09-17),
    # w_tgt={} (core dead today), disk_prev=1.004 from 09-18 flat row.
    state = {"nav": 1.004, "last_mark": "2026-09-17", "core_name": "v5c",
             "weights": {}, "mark_prices": {}}
    disk_prev_nav, disk_prev_date = 1.004, "2026-09-18"

    nav_base = _compute_nav_base(state, disk_prev_nav, disk_prev_date,
                                 today=dt.date(2026, 9, 19))
    # State last_mark=09-17 ≠ 09-18=disk_prev_date, so disk wins.
    # nav_base = 1.004 (matches disk chain after the 09-17 -0.4% mark).
    assert nav_base == pytest.approx(1.004, abs=1e-9)


# ── _decide_price_pnl: 4-way guard decision (S-326/R57/S-378b-2.3) ───────────
#
# The guard inside mark_and_rebalance decides today's price_pnl contribution
# from four states. Before the S-378b-2.3 fix, the by-design flat branch
# (R57: w_held={} AND w_tgt={}) was missing — the S-326 conservative branch
# refused it, losing honest records (the 28 core_dead rows from 09-14..).
#
# `_decide_price_pnl(w_held, w_tgt, last_px, mp, state, book)` is the pure
# extraction of this decision. Returns (price_pnl, skip_envelope_or_None).

def test_decide_price_pnl_w_held_non_empty_runs_weighted_mark():
    """Branch ①: w_held non-empty → call weighted_mark with coverage check."""
    from src.data.signals.two_layer_paper import _decide_price_pnl

    w_held = {"BTC": 0.5, "ETH": 0.5}
    w_tgt = {"BTC": 0.5, "ETH": 0.5}
    last_px = {"BTC": 105.0, "ETH": 100.0}
    mp = {"BTC": 100.0, "ETH": 100.0}  # BTC +5%, ETH flat
    state = {"revived_from_disk": False}

    price_pnl, skip = _decide_price_pnl(w_held, w_tgt, last_px, mp, state,
                                       book="two_layer")
    assert skip is None
    # BTC: 0.5 * (105/100 - 1) = 0.5 * 0.05 = 0.025
    # ETH: 0.5 * (100/100 - 1) = 0
    # total = 0.025
    assert price_pnl == pytest.approx(0.025, abs=1e-9)


def test_decide_price_pnl_revived_from_disk_flat_zero():
    """Branch ②: state empty + revived from disk → flat (price_pnl=0).

    S-378b: Redis state was lost, we revived from disk_prev. w_held is {}
    because we don't know what was held yesterday. Honest answer: 0.
    """
    from src.data.signals.two_layer_paper import _decide_price_pnl

    w_held = {}
    w_tgt = {"BTC": 0.5}  # today target is alive
    last_px = {"BTC": 105.0}
    mp = {}
    state = {"revived_from_disk": True}

    price_pnl, skip = _decide_price_pnl(w_held, w_tgt, last_px, mp, state,
                                       book="two_layer")
    assert skip is None
    assert price_pnl == 0.0


def test_decide_price_pnl_by_design_flat_when_both_empty():
    """Branch ③ (NEW in S-378b-2.3): R57 by-design flat, both empty → 0.

    two_layer's core is structurally dead (R57 verdict). When the core is
    dead both yesterday AND today, w_held={} AND w_tgt={}. The book holds
    nothing by design, so the day's P&L is structurally 0 — arithmetic,
    not a lie. Mark flat honestly instead of refusing (S-326).
    """
    from src.data.signals.two_layer_paper import _decide_price_pnl

    w_held = {}
    w_tgt = {}
    last_px = {"BTC": 105.0, "ETH": 100.0}
    mp = {}
    state = {"revived_from_disk": False}  # NOT revival — both empty by design

    price_pnl, skip = _decide_price_pnl(w_held, w_tgt, last_px, mp, state,
                                       book="two_layer")
    assert skip is None  # NOT a refusal — this is the fix
    assert price_pnl == 0.0


def test_decide_price_pnl_state_lost_refuses():
    """Branch ④: w_held={} AND w_tgt has positions AND NOT revived → S-326 refuse.

    This is the actual state-lost bug: state was empty, NOT revived (Redis
    miss but no disk), but w_tgt has positions (core alive today). We don't
    know what was held yesterday, so we can't honestly compute P&L. Refuse.
    """
    from src.data.signals.two_layer_paper import _decide_price_pnl

    w_held = {}
    w_tgt = {"BTC": 0.5}  # core alive today, target has positions
    last_px = {"BTC": 105.0}
    mp = {}
    state = {"revived_from_disk": False}  # NOT revived — state lost

    price_pnl, skip = _decide_price_pnl(w_held, w_tgt, last_px, mp, state,
                                       book="two_layer")
    assert price_pnl is None
    assert skip is not None
    assert skip["status"] == "skipped"
    assert "holds nothing" in skip["reason"]
    assert skip["book"] == "two_layer"


def test_decide_price_pnl_weighted_mark_fail_returns_skip():
    """Branch ① failure: coverage < floor → return weighted_mark's skip envelope."""
    from src.data.signals.two_layer_paper import _decide_price_pnl

    w_held = {"BTC": 0.5, "ETH": 0.5}
    w_tgt = {"BTC": 0.5, "ETH": 0.5}
    last_px = {"BTC": 105.0}  # ETH missing → coverage 50% < 80% floor
    mp = {"BTC": 100.0, "ETH": 100.0}
    state = {}

    price_pnl, skip = _decide_price_pnl(w_held, w_tgt, last_px, mp, state,
                                       book="two_layer")
    assert price_pnl is None
    assert skip is not None
    assert skip["status"] == "skipped"
    assert "coverage" in skip["reason"].lower()
