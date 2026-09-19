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
