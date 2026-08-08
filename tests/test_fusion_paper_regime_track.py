"""
ⓠ REGIME OVERRIDE Paper Track — pure-function tests (2026-08-06)
=================================================================

Per Jazz direction ("接吧"): wire the ⓠ REGIME OVERRIDE enforcer into a parallel
60-day paper NAV curve for the R64 fusion book. This module's tests cover the
pure analysis primitives so the gate catches regressions as the track is wired
into the daily paper runner.

Run:  python3 -m tests.test_fusion_paper_regime_track
"""
from __future__ import annotations

import csv
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import numpy as np
import pandas as pd

from src.research.validation.fusion_paper_regime_track import (  # noqa: E402
    R64_NOTIONAL_USD,
    TRACK_HEADER,
    _max_drawdown_pct,
    _regime_pnl_for_day,
    aggregate_regime_track,
    band_cap_for_date,
    compute_regime_track,
    compute_today_track,
)


# ── band_cap_for_date ────────────────────────────────────────────────────────
def test_band_cap_for_date_empty_signal_returns_neutral():
    empty_sig = pd.Series([], index=pd.DatetimeIndex([], freq="D"), dtype=float)
    band, cap = band_cap_for_date(pd.Timestamp("2026-08-06"), empty_sig)
    assert band == "NEUTRAL" and cap == 1.0


def test_band_cap_for_date_sustained_crisis_returns_crisis():
    """Single-day spike exits at next day (hysteresis EXIT_CRISIS=-0.025 > 0)."""
    dates = pd.date_range("2026-07-01", periods=40, freq="D")
    sig = pd.Series([0.0] * 40, index=dates)
    sig.iloc[10:30] = -0.10   # sustained CRISIS for 20 days
    band, cap = band_cap_for_date(pd.Timestamp("2026-07-25"), sig)
    assert band == "CRISIS" and cap == 0.0, f"got {band}/{cap}"


def test_band_cap_for_date_pit_lag_enforced():
    """Signal at day t must NOT influence cap at day t — shift(1) inside."""
    dates = pd.date_range("2026-07-01", periods=10, freq="D")
    sig = pd.Series([0.0] * 10, index=dates)
    sig.iloc[5:9] = -0.10   # sustained CRISIS at indices 5..8
    band_same, _ = band_cap_for_date(dates[5], sig)
    band_next, _ = band_cap_for_date(dates[6], sig)
    assert band_same == "NEUTRAL", f"same day must be NEUTRAL (PIT), got {band_same}"
    assert band_next == "CRISIS", f"next day must be CRISIS, got {band_next}"


# ── _regime_pnl_for_day (multiplicative gate, scalar weight=1.0 equivalent) ─
def test_regime_pnl_neutral_is_identity():
    pnl = _regime_pnl_for_day(1.0, 0.01)
    assert abs(pnl - 10_000.0) < 1e-6


def test_regime_pnl_crisis_is_zero():
    assert _regime_pnl_for_day(0.0, 0.05) == 0.0


def test_regime_pnl_hot_is_gross_leveraged():
    pnl = _regime_pnl_for_day(1.3, 0.01)
    assert abs(pnl - 13_000.0) < 1e-6


def test_regime_pnl_contraction_halves():
    pnl = _regime_pnl_for_day(0.5, 0.01)
    assert abs(pnl - 5_000.0) < 1e-6


# ── compute_regime_track ─────────────────────────────────────────────────────
def test_compute_regime_track_flat_signal_equals_baseline():
    nav_dates = pd.date_range("2026-07-01", periods=10, freq="D")
    r77_nav = pd.Series([100.0 + i for i in range(10)], index=nav_dates)
    sig = pd.Series([0.0] * 10, index=nav_dates)
    track = compute_regime_track(r77_nav, sig)
    assert len(track) == 9  # 10 NAV points → 9 daily returns
    assert (track["band"] == "NEUTRAL").all()
    # cap=1.0 → regime_pnl == r77_pnl (atol=0.01 for 2-decimal rounding)
    expected_pnl = r77_nav.pct_change().dropna() * R64_NOTIONAL_USD
    np.testing.assert_allclose(track["regime_pnl_usd"].values,
                               expected_pnl.values, atol=0.01)


def test_compute_regime_track_crisis_days_zero_pnl():
    nav_dates = pd.date_range("2026-07-01", periods=10, freq="D")
    r77_nav = pd.Series([100.0 + i for i in range(10)], index=nav_dates)
    sig = pd.Series([0.0] * 10, index=nav_dates)
    sig.iloc[3:8] = -0.10   # sustained CRISIS from day 3 (after PIT, day 4+)
    track = compute_regime_track(r77_nav, sig)
    crisis_days = track[track["band"] == "CRISIS"]
    if not crisis_days.empty:
        assert (crisis_days["regime_pnl_usd"] == 0.0).all(), \
            f"CRISIS days must have pnl=0, got {crisis_days['regime_pnl_usd'].tolist()}"


def test_compute_regime_track_rejects_non_series():
    try:
        compute_regime_track([100.0, 101.0], pd.Series([0.0, 0.0]))
    except TypeError as e:
        assert "pd.Series" in str(e)
    else:
        raise AssertionError("non-Series r77_nav must raise")


def test_compute_regime_track_rejects_too_few_points():
    try:
        compute_regime_track(pd.Series([100.0]), pd.Series([0.0]))
    except ValueError as e:
        assert "≥2" in str(e)
    else:
        raise AssertionError("<2 NAV points must raise")


# ── aggregate_regime_track ───────────────────────────────────────────────────
def test_aggregate_empty_returns_insufficient():
    agg = aggregate_regime_track(pd.DataFrame())
    assert agg["status"] == "INSUFFICIENT" and agg["n_days"] == 0


def test_aggregate_short_returns_warming_up():
    nav_dates = pd.date_range("2026-07-01", periods=10, freq="D")
    r77_nav = pd.Series([100.0 + i for i in range(10)], index=nav_dates)
    sig = pd.Series([0.0] * 10, index=nav_dates)
    track = compute_regime_track(r77_nav, sig)
    agg = aggregate_regime_track(track.iloc[:5])
    assert agg["status"] == "WARMING_UP" and agg["n_days"] == 5


def test_aggregate_flat_signal_alpha_near_zero():
    """Both regime and flat should be ≈equal under a flat (NEUTRAL) signal."""
    nav_long = pd.Series([100.0 + 0.5 * i for i in range(40)],
                         index=pd.date_range("2026-06-01", periods=40, freq="D"))
    sig_long = pd.Series([0.0] * 40, index=nav_long.index)
    track_long = compute_regime_track(nav_long, sig_long)
    agg = aggregate_regime_track(track_long)
    assert agg["status"] == "ok"
    assert abs(agg["mean_realized_cap"] - 1.0) < 1e-9
    assert abs(agg["regime_vs_flat_alpha_pct"]) < 0.01, \
        f"flat signal: alpha should ≈0, got {agg['regime_vs_flat_alpha_pct']}"


# ── _max_drawdown_pct ────────────────────────────────────────────────────────
def test_max_drawdown_pct_negative_on_drawdown():
    dd = _max_drawdown_pct([1.0, 1.1, 1.2, 1.0, 0.95, 1.05])
    assert dd is not None and dd < 0


def test_max_drawdown_pct_none_on_empty():
    assert _max_drawdown_pct([]) is None
    assert _max_drawdown_pct([1.0]) is None


# ── Driver ───────────────────────────────────────────────────────────────────
TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    p = 0
    for t in TESTS:
        t(); print(f"  ✓ {t.__name__}"); p += 1
    print(f"\n✅ {p}/{len(TESTS)} fusion-paper-regime-track checks passed")
