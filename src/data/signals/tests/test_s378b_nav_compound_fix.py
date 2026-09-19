"""S-378b smoke: state.nav must compound from disk, not reset to 1.0.

factor_tilt_paper.py:439 and pod_aggregator_paper.py:390 had the same L1
self-consistency bug: `_load_state()` returned a default `{nav: 1.0}` every
cycle because their *_state tables were empty on disk. The fix reads disk
prev nav and uses it as the compounding base. This test exercises that
choice with synthetic state, without touching Supabase.
"""
from __future__ import annotations

import asyncio
import datetime as dt
from unittest.mock import AsyncMock, patch

import pytest


# ── factor_tilt_paper ─────────────────────────────────────────────────────────

def test_factor_tilt_uses_disk_prev_nav_when_state_empty():
    """State nav=1.0 but disk prev nav=0.999018 → new_nav = 0.999018 * (1+r),
    not 1.0 * (1+r)."""
    from src.data.signals.factor_tilt_paper import _compute_nav_base

    state = {"nav": 1.0, "last_mark_date": None, "inception_date": "2026-09-14"}
    disk_prev_nav, disk_prev_date = 0.999018, "2026-09-18"

    nav_base = _compute_nav_base(state, disk_prev_nav, disk_prev_date,
                                 today=dt.date(2026, 9, 19))
    # state empty + disk prev present → use disk
    assert nav_base == pytest.approx(0.999018, abs=1e-9)


def test_factor_tilt_uses_state_when_state_matches_disk():
    """State agrees with disk → use state (full compounding chain)."""
    from src.data.signals.factor_tilt_paper import _compute_nav_base

    state = {"nav": 1.012345, "last_mark_date": "2026-09-18",
             "inception_date": "2026-09-14"}
    disk_prev_nav, disk_prev_date = 1.012345, "2026-09-18"

    nav_base = _compute_nav_base(state, disk_prev_nav, disk_prev_date,
                                 today=dt.date(2026, 9, 19))
    assert nav_base == pytest.approx(1.012345, abs=1e-9)


def test_factor_tilt_inception_when_no_disk_history():
    """No disk history → 1.0 (genuine inception, never crash to None)."""
    from src.data.signals.factor_tilt_paper import _compute_nav_base

    state = {"nav": 1.0, "last_mark_date": None, "inception_date": "2026-09-19"}
    nav_base = _compute_nav_base(state, None, None, today=dt.date(2026, 9, 19))
    assert nav_base == 1.0


def test_factor_tilt_state_diverges_from_disk_uses_disk():
    """State says nav=0.99 but disk says 1.05 (state stale, >1pp diff) → disk wins.
    This is the case where the old code produced silent L1 errors."""
    from src.data.signals.factor_tilt_paper import _compute_nav_base

    state = {"nav": 0.990, "last_mark_date": "2026-09-18",
             "inception_date": "2026-09-14"}
    disk_prev_nav, disk_prev_date = 1.050, "2026-09-18"

    nav_base = _compute_nav_base(state, disk_prev_nav, disk_prev_date,
                                 today=dt.date(2026, 9, 19))
    assert nav_base == pytest.approx(1.050, abs=1e-9)


# ── pod_aggregator_paper ──────────────────────────────────────────────────────

def test_pod_aggregator_uses_disk_prev_nav_when_state_empty():
    """Same pattern for pod_aggregator."""
    from src.data.signals.pod_aggregator_paper import _compute_nav_base

    state = {"nav": 1.0, "last_mark_date": None, "inception_date": "2026-09-14"}
    nav_base = _compute_nav_base(state, 1.025940, "2026-09-18",
                                 today=dt.date(2026, 9, 19))
    assert nav_base == pytest.approx(1.025940, abs=1e-9)


def test_pod_aggregator_uses_state_when_state_matches_disk():
    from src.data.signals.pod_aggregator_paper import _compute_nav_base

    state = {"nav": 1.030000, "last_mark_date": "2026-09-18",
             "inception_date": "2026-09-14"}
    nav_base = _compute_nav_base(state, 1.030000, "2026-09-18",
                                 today=dt.date(2026, 9, 19))
    assert nav_base == pytest.approx(1.030000, abs=1e-9)


# ── L1 self-consistency end-to-end ───────────────────────────────────────────

def test_factor_tilt_l1_holds_after_fix():
    """Simulate 6-day sequence with state empty (real condition).
    Old code: nav[t] = 1.0 * (1+r[t]) → not compounding, L1 fails.
    New code: nav[t] = disk_prev * (1+r[t]) → compounding, L1 holds."""
    from src.data.signals.factor_tilt_paper import _compute_nav_base

    # Real disk sequence observed 2026-09-19
    daily_returns = {
        "2026-09-14": None,  # inception
        "2026-09-15": -0.0009822299405145148,
        "2026-09-16": 0.0028522841006728863,
        "2026-09-17": -0.0037395112291854563,
        "2026-09-18": -0.0020130441295634484,
        "2026-09-19": 0.009234714565025054,
    }
    # Simulate that state is empty every cycle (the actual bug condition)
    state = {"nav": 1.0, "last_mark_date": None, "inception_date": "2026-09-14"}

    prev_disk_nav = None  # Before any mark, disk is empty
    dates = list(daily_returns.keys())
    navs = {}
    for i, d in enumerate(dates):
        r = daily_returns[d]
        today = dt.date.fromisoformat(d)
        # disk_prev_nav is what was written last cycle
        nav_base = _compute_nav_base(state, prev_disk_nav, dates[i-1] if i > 0 else None,
                                     today=today)
        if r is None:
            # inception: nav_base = 1.0, but first mark has today_ret = "first day's r"
            # In the real code this is actually: state.nav * (1+r) where state.nav=1.0
            navs[d] = nav_base
        else:
            navs[d] = nav_base * (1.0 + r)
        prev_disk_nav = navs[d]

    # L1 check: nav[t]/nav[t-1] - 1 ≈ daily_return[t] within 0.01 pp
    for i in range(1, len(dates)):
        d = dates[i]
        prev_d = dates[i-1]
        r = daily_returns[d]
        if r is None:
            continue
        implied = navs[d] / navs[prev_d] - 1
        err_pp = (implied - r) * 100
        assert abs(err_pp) < 0.01, (
            f"L1 fail on {d}: nav={navs[d]:.6f}, prev={navs[prev_d]:.6f}, "
            f"daily_return={r:.6f}, implied={implied:.6f}, err={err_pp:.4f}pp"
        )
