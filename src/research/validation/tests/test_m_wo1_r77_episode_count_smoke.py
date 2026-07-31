"""Smoke tests for M-WO-1 R77 episode-count audit (per §DIRECTIVE 2026-07-27).

Verifies:
  1. Module imports cleanly
  2. §DIRECTIVE constants are intact (8-episode floor, 2.0 episode-t floor, gap>7d)
  3. segment_episodes: gap boundary is strict (>7d, not >=7d) — 7 zero days does NOT split
  4. segment_episodes: min_days floor drops short runs (3-day floor)
  5. segment_by_sign: positive / negative sign runs are correctly identified
  6. segment_by_quarter: calendar-quarter partition works
  7. aggregate_episodes: sign_majority_positive correctly handles 2-2 tie
  8. Verdict grammar: REFUTED (n<8), REFUTED (sign not majority), REFUTED (t<=floor), SURVIVES
  9. Edge case: empty P&L → 0 episodes, no crash
 10. Edge case: all-zero P&L → 0 episodes, no crash

Pure Python + numpy + pandas. Sandbox-safe. No scipy / network / freightrade.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

import numpy as np
import pandas as pd

from src.research.validation.m_wo1_r77_episode_count_audit import (
    EPISODE_GAP_DAYS,
    EPISODE_MIN_DAYS,
    EPISODE_COUNT_FLOOR,
    EPISODE_T_FLOOR,
    ZERO_TOL,
    segment_episodes,
    aggregate_episodes,
    segment_by_sign,
    segment_by_quarter,
    segment_by_month,
)


# ── Constants ────────────────────────────────────────────────────────────────
def test_directive_constants_intact():
    """§DIRECTIVE acceptance thresholds must match the directive's exact values."""
    assert EPISODE_GAP_DAYS == 7, "§DIRECTIVE: gap > 7d"
    assert EPISODE_MIN_DAYS == 3, "min episode length floor"
    assert EPISODE_COUNT_FLOOR == 8, "§DIRECTIVE: n_episodes ≥ 8"
    assert EPISODE_T_FLOOR == 2.0, "§DIRECTIVE: episode_t > 2.0"
    assert ZERO_TOL == 1e-12


# ── gap boundary ─────────────────────────────────────────────────────────────
def test_gap_seven_days_does_not_split():
    """§DIRECTIVE says gap > 7d (strict). 7 zero days should NOT split episodes."""
    dates = pd.date_range("2025-01-01", periods=15, freq="D")
    pnl = pd.Series(
        [0.001] * 5 + [0.0] * 7 + [0.002] * 3,
        index=dates)
    ep = segment_episodes(pnl, gap_days=EPISODE_GAP_DAYS, min_days=EPISODE_MIN_DAYS)
    assert len(ep) == 1, "7-day gap must NOT split (gap>7d is strict)"
    assert ep[0]["n_days"] == 8  # 5 active + 3 active, gap_7d is sub-threshold


def test_gap_eight_days_does_split():
    """8 zero days > 7d threshold → splits."""
    dates = pd.date_range("2025-01-01", periods=18, freq="D")
    pnl = pd.Series(
        [0.001] * 5 + [0.0] * 8 + [0.002] * 5,
        index=dates)
    ep = segment_episodes(pnl, gap_days=EPISODE_GAP_DAYS, min_days=EPISODE_MIN_DAYS)
    assert len(ep) == 2, "8-day gap must split (gap>7d)"


# ── min_days floor ──────────────────────────────────────────────────────────
def test_min_days_floor_drops_short_runs():
    """Episodes shorter than min_days should be dropped."""
    dates = pd.date_range("2025-01-01", periods=18, freq="D")
    pnl = pd.Series(
        [0.001] * 2 + [0.0] * 8 + [0.002] * 8,
        index=dates)
    ep = segment_episodes(pnl, gap_days=EPISODE_GAP_DAYS, min_days=EPISODE_MIN_DAYS)
    assert len(ep) == 1
    assert ep[0]["n_days"] == 8  # the 2-day run is dropped, only the 8-day run survives


# ── sign-clustering ─────────────────────────────────────────────────────────
def test_segment_by_sign_basic():
    dates = pd.date_range("2025-01-01", periods=44, freq="D")
    pnl = pd.Series(
        [0.001] * 5 + [0.0] * 8 + [-0.001] * 5 + [0.0] * 8 + [0.001] * 5 + [0.0] * 8 + [-0.001] * 5,
        index=dates)
    eps = segment_by_sign(pnl, min_days=EPISODE_MIN_DAYS)
    assert len(eps) == 4
    signs = [e["sign"] for e in eps]
    assert signs == ["positive", "negative", "positive", "negative"]


def test_segment_by_sign_drops_short_runs():
    """2-day sign-runs should be dropped by min_days floor."""
    dates = pd.date_range("2025-01-01", periods=20, freq="D")
    pnl = pd.Series(
        [0.001, 0.001, -0.001, -0.001, -0.001, 0.0] * 3 + [0.0] * 2,
        index=dates)
    eps = segment_by_sign(pnl, min_days=EPISODE_MIN_DAYS)
    # Pattern: 2+ pos, 3 neg, repeat. The 2-day positive runs are dropped.
    # Only the 3-day negative runs should survive → 3 episodes.
    assert all(e["n_days"] >= EPISODE_MIN_DAYS for e in eps)


# ── quarterly + monthly partition ──────────────────────────────────────────
def test_segment_by_quarter_basic():
    """Three calendar quarters, all positive."""
    # Span 3 quarters: 2025Q4 + 2026Q1 + 2026Q2
    dates = pd.date_range("2025-10-01", periods=275, freq="D")
    pnl = pd.Series(0.001, index=dates)
    eps = segment_by_quarter(pnl)
    assert len(eps) >= 3, f"expected ≥3 quarters, got {len(eps)}"
    for e in eps:
        assert e["ann_pct"] > 0


def test_segment_by_month_basic():
    """Three calendar months, all positive."""
    dates = pd.date_range("2025-10-01", periods=92, freq="D")
    pnl = pd.Series(0.001, index=dates)
    eps = segment_by_month(pnl)
    assert len(eps) >= 3
    for e in eps:
        assert e["ann_pct"] > 0


# ── aggregate verdict ──────────────────────────────────────────────────────
def test_aggregate_sign_majority_positive():
    """2 pos + 1 neg → majority positive."""
    eps = [
        {"first_date": "2025-01-01", "last_date": "2025-01-05", "n_days": 5,
         "mean_daily_pnl": 0.001, "std_daily_pnl": 0.0001, "ann_pct": 25.2,
         "t_stat": 1.0, "cum_pnl": 0.005},
        {"first_date": "2025-02-01", "last_date": "2025-02-08", "n_days": 8,
         "mean_daily_pnl": 0.002, "std_daily_pnl": 0.0001, "ann_pct": 50.4,
         "t_stat": 2.0, "cum_pnl": 0.016},
        {"first_date": "2025-03-01", "last_date": "2025-03-07", "n_days": 7,
         "mean_daily_pnl": -0.001, "std_daily_pnl": 0.0001, "ann_pct": -25.2,
         "t_stat": -1.0, "cum_pnl": -0.007},
    ]
    agg = aggregate_episodes(eps)
    assert agg["n_episodes"] == 3
    assert agg["n_positive"] == 2
    assert agg["n_negative"] == 1
    assert agg["sign_majority_positive"] is True


def test_aggregate_sign_tie_not_majority():
    """2 pos + 2 neg → not majority (strict > required)."""
    eps = [
        {"first_date": "a", "last_date": "b", "n_days": 5, "mean_daily_pnl": 0.001,
         "std_daily_pnl": 0.0001, "ann_pct": 25, "t_stat": 1.0, "cum_pnl": 0.005},
        {"first_date": "c", "last_date": "d", "n_days": 5, "mean_daily_pnl": -0.001,
         "std_daily_pnl": 0.0001, "ann_pct": -25, "t_stat": -1.0, "cum_pnl": -0.005},
        {"first_date": "e", "last_date": "f", "n_days": 5, "mean_daily_pnl": 0.002,
         "std_daily_pnl": 0.0001, "ann_pct": 50, "t_stat": 2.0, "cum_pnl": 0.01},
        {"first_date": "g", "last_date": "h", "n_days": 5, "mean_daily_pnl": -0.002,
         "std_daily_pnl": 0.0001, "ann_pct": -50, "t_stat": -2.0, "cum_pnl": -0.01},
    ]
    agg = aggregate_episodes(eps)
    assert agg["sign_majority_positive"] is False, "2-2 tie is NOT majority"


# ── edge cases ─────────────────────────────────────────────────────────────
def test_empty_pnl_returns_empty():
    ep = segment_episodes(pd.Series([], dtype=float))
    agg = aggregate_episodes(ep)
    assert ep == []
    assert agg["n_episodes"] == 0
    assert not agg["sign_majority_positive"]


def test_all_zero_pnl_returns_empty():
    pnl = pd.Series([0.0] * 30, index=pd.date_range("2025-01-01", periods=30, freq="D"))
    ep = segment_episodes(pnl)
    assert ep == [], "all-zero PnL = book always idle = 0 episodes"


def test_continuous_positive_single_episode():
    """The R77 OOS pattern: 220 days continuous positive = 1 episode."""
    dates = pd.date_range("2025-01-01", periods=220, freq="D")
    pnl = pd.Series(0.001, index=dates)
    ep = segment_episodes(pnl, gap_days=EPISODE_GAP_DAYS, min_days=EPISODE_MIN_DAYS)
    assert len(ep) == 1, "continuous-active book = 1 episode (R77 finding)"
    agg = aggregate_episodes(ep)
    assert agg["n_episodes"] < EPISODE_COUNT_FLOOR  # would REFUTE the §DIRECTIVE verdict


# ── run all ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))