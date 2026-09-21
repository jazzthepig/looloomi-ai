"""Smoke test for `paper_trading/factors.py` — pure-stdlib factor signals.

These tests exercise the building block for arm C of the 3-arm comparison
(S-393 Jev vs baseline vs simple-factor). They run without DB / Supabase /
pandas — pure stdlib + numpy not even needed.

Three claims worth testing (each = one realistic failure mode):
  1. `compute_factor_signals` returns the right per-factor booleans on a
     controlled price series (uptrend → all_ok, downtrend → not all_ok,
     high-vol → vol_ok fails).
  2. NaN / insufficient history returns all-False instead of raising.
  3. `passes_factor_gate` returns the same shape per symbol and respects
     independent failure modes (different symbols fail different factors).
  4. `sma_ok_rule="below_or_equal"` flips the SMA direction.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from paper_trading.factors import (
    compute_factor_signals,
    passes_factor_gate,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _uptrend_closes(start: float, n: int, daily_pct: float = 0.01) -> dict[str, float]:
    """Build a {date: close} dict for a synthetic uptrend with daily_pct gain."""
    out: dict[str, float] = {}
    px = start
    for i in range(n):
        d = (date(2026, 1, 1) + timedelta(days=i)).isoformat()
        px *= (1 + daily_pct)
        out[d] = round(px, 4)
    return out


def _downtrend_closes(start: float, n: int, daily_pct: float = -0.01) -> dict[str, float]:
    return _uptrend_closes(start, n, daily_pct)


def _high_vol_closes(start: float, n: int) -> dict[str, float]:
    """Alternating ±5% days → vol ≈ 5% daily stdev > 5% threshold → vol_ok False."""
    out: dict[str, float] = {}
    px = start
    for i in range(n):
        d = (date(2026, 1, 1) + timedelta(days=i)).isoformat()
        px *= (1.05 if i % 2 == 0 else 0.95)
        out[d] = round(px, 4)
    return out


# Default eval date — 100 days into the series so all 3 windows (60/60/30) all pass.
EVAL = date(2026, 4, 10)


# ── 1. Uptrend series → all three factors pass ──────────────────────────────

def test_uptrend_all_three_pass():
    """Steady +1%/day for 100 days → SMA60 above, mom_60 > 0, vol low."""
    closes = _uptrend_closes(100.0, 100, daily_pct=0.01)
    sig = compute_factor_signals(closes, EVAL)
    assert sig["sma_ok"] is True, f"uptrend should be above SMA60; got {sig}"
    assert sig["mom_ok"] is True, f"uptrend mom_60 should be > 0; got {sig}"
    assert sig["vol_ok"] is True, f"steady uptrend vol should be < 5%; got {sig}"
    assert sig["all_ok"] is True, f"all three pass → all_ok True; got {sig}"


def test_downtrend_all_three_fail():
    """Steady -1%/day for 100 days → below SMA, negative mom, vol low (vol still passes)."""
    closes = _downtrend_closes(100.0, 100, daily_pct=-0.01)
    sig = compute_factor_signals(closes, EVAL)
    assert sig["sma_ok"] is False, f"downtrend should be below SMA60; got {sig}"
    assert sig["mom_ok"] is False, f"downtrend mom_60 should be ≤ 0; got {sig}"
    # Vol is low (steady downtrend), so vol_ok True. all_ok False because sma+mom failed.
    assert sig["vol_ok"] is True, f"steady downtrend vol should still be low; got {sig}"
    assert sig["all_ok"] is False, f"sma+mom failed → all_ok False; got {sig}"


def test_high_vol_vol_fails():
    """Alternating ±5%/day for 100 days → vol exceeds 5% threshold → vol_ok False."""
    closes = _high_vol_closes(100.0, 100)
    sig = compute_factor_signals(closes, EVAL)
    assert sig["vol_ok"] is False, (
        f"±5% alternating → vol ≈ 5%, threshold is 5% strict-less; got {sig}"
    )
    # Whether sma/mom pass depends on starting point — just assert shape
    assert isinstance(sig["all_ok"], bool)


# ── 2. NaN / insufficient history → all False, no crash ─────────────────────

def test_insufficient_history_returns_all_false():
    """Series with only 30 days → can't compute SMA60 → all_ok False."""
    closes = _uptrend_closes(100.0, 30, daily_pct=0.01)
    sig = compute_factor_signals(closes, EVAL)
    assert sig == {"sma_ok": False, "mom_ok": False, "vol_ok": False, "all_ok": False}, (
        f"30 days < sma_window=60 → all four False; got {sig}"
    )


def test_empty_closes_returns_all_false():
    """Empty dict → all four False, no exception."""
    sig = compute_factor_signals({}, EVAL)
    assert sig == {"sma_ok": False, "mom_ok": False, "vol_ok": False, "all_ok": False}


def test_zero_or_negative_close_handled():
    """A 0 close in the series → division by zero in mom/pct_change → handled.

    The 0 may or may not fall inside the active windows (sma=60/mom=60/vol=30);
    we only assert that the function returns the expected shape without raising.
    Per `_safe_close` (factors.py:54-61) any non-positive close drops out of
    the ordered list, so pct_change and SMA compute on the remaining bars.
    """
    closes = _uptrend_closes(100.0, 100, daily_pct=0.01)
    # Inject a 0 near the END so it WILL fall inside the SMA60 window
    keys = list(closes.keys())
    for i in (-1, -5, -10):                                  # last 10 bars
        closes[keys[i]] = 0.0
    sig = compute_factor_signals(closes, EVAL)               # should NOT raise
    assert set(sig.keys()) == {"sma_ok", "mom_ok", "vol_ok", "all_ok"}
    assert all(isinstance(v, bool) for v in sig.values())


# ── 3. Independent per-symbol failure modes (passes_factor_gate) ────────────

def test_passes_factor_gate_per_symbol_independent():
    """BTC uptrend, ETH downtrend, SOL high-vol → each fails for different reasons."""
    btc = _uptrend_closes(100.0, 100, daily_pct=0.01)
    eth = _downtrend_closes(100.0, 100, daily_pct=-0.01)
    sol = _high_vol_closes(100.0, 100)
    closes_by_sym = {"BTC": btc, "ETH": eth, "SOL": sol}
    out = passes_factor_gate(closes_by_sym, EVAL)
    assert set(out.keys()) == {"BTC", "ETH", "SOL"}
    assert out["BTC"]["all_ok"] is True
    assert out["ETH"]["all_ok"] is False   # sma + mom fail
    assert out["SOL"]["all_ok"] is False   # vol fails
    # Per-factor verification — ETH fails on sma+mom but passes vol
    assert out["ETH"]["sma_ok"] is False
    assert out["ETH"]["mom_ok"] is False
    assert out["ETH"]["vol_ok"] is True
    # SOL passes sma+mom (depends on starting point — only vol is the strict gate)
    assert out["SOL"]["vol_ok"] is False


# ── 4. sma_ok_rule="below_or_equal" flips direction ────────────────────────

def test_below_or_equal_rule_inverts_sma():
    """Same uptrend; with sma_ok_rule='below_or_equal', sma_ok flips to False."""
    closes = _uptrend_closes(100.0, 100, daily_pct=0.01)
    sig_above = compute_factor_signals(closes, EVAL, sma_ok_rule="above")
    sig_below = compute_factor_signals(closes, EVAL, sma_ok_rule="below_or_equal")
    assert sig_above["sma_ok"] is True, f"above SMA → sma_ok True; got {sig_above}"
    assert sig_below["sma_ok"] is False, (
        f"uptrend is above SMA, so below_or_equal → False; got {sig_below}"
    )


def test_bogus_sma_ok_rule_rejected():
    """Unknown rule string raises ValueError (fail loud, not silent)."""
    closes = _uptrend_closes(100.0, 100, daily_pct=0.01)
    with pytest.raises(ValueError, match="sma_ok_rule"):
        compute_factor_signals(closes, EVAL, sma_ok_rule="sideways")


# ── 5. Default-window assertions (catch accidental window drift) ────────────

def test_default_windows_match_docstring():
    """If defaults silently change (e.g. mom_window=30), the 3-arm replay
    would shift in a way that looks like a market move but isn't. Pin them."""
    closes = _uptrend_closes(100.0, 200, daily_pct=0.005)
    sig = compute_factor_signals(closes, EVAL)  # all defaults
    assert sig["all_ok"] is True, (
        f"200-day +0.5%/day steady uptrend should pass all 3 default filters "
        f"(sma=60, mom=60, vol=30<0.05); got {sig}"
    )


# ── 6. Lag-1 PIT discipline ────────────────────────────────────────────────

def test_signal_uses_bars_up_to_d_lag1():
    """The eval date is INCLUDED in `closes` but the signal must use bars ≤ d-1.

    If the implementation accidentally uses today's bar, the result would
    differ. We verify by running with and without `today` in the series and
    asserting the result is the same (signal ignores the today bar).
    """
    closes_with_today = _uptrend_closes(100.0, 100, daily_pct=0.01)
    # Append EVAL itself to the series — should be ignored by signal
    closes_with_today[EVAL.isoformat()] = 999.0
    sig_with = compute_factor_signals(closes_with_today, EVAL)

    closes_without_today = {k: v for k, v in closes_with_today.items()
                             if k != EVAL.isoformat()}
    sig_without = compute_factor_signals(closes_without_today, EVAL)
    assert sig_with == sig_without, (
        f"signal must use bars ≤ d-1; result should not depend on whether "
        f"today's bar is in the series. with={sig_with} without={sig_without}"
    )
