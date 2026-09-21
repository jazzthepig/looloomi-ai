"""Per-symbol factor signals for the simple-factor strategy arm.

JAZZ 2026-09-21 wants a 3-arm comparison: Jev-gated A-17 vs no-Jev baseline vs
"simple factor AND gate". This module is the building block for arm C.

Design constraints (per docs/SPINE.md §5b + CLAUDE.md rule 9):
- Pure stdlib (no pandas/numpy/DB) → CI-portable, replay-deterministic.
- Reuses `src.data.vector.market_state.pct_change` and `.realized_vol` rather
  than reinventing (per DRY — those are stdlib-only helpers, NaN-safe via
  `_finite()`).
- Each factor check returns a `bool` (pass/fail). The aggregate `all_ok` is
  the AND of the three (SMA60 + mom_60 > 0 + realized_vol_30 < threshold).
- NaN / insufficient-history bars return `False` for the affected factor
  rather than raising — a symbol that's too short to compute SMA60 should be
  filtered, not crashed on.

Factors (JAZZ 2026-09-21, simple-factor design):
    SMA60_ok   = close_{d_lag1} > SMA(60) of closes up to d_lag1
    mom_60_ok  = (close_{d_lag1} / close_{d_lag1 - 60}) - 1 > 0
    vol_30_ok  = realized_vol(daily_returns_30, annualize=False) < threshold
    all_ok     = SMA60_ok AND mom_60_ok AND vol_30_ok

Lag-1 PIT (S-114 / S-122): signals use bars <= d_lag1 (= d - 1 day). The
strategy will use `as_of` as the eval date and look back one day for the
signal. `compute_factor_signals` accepts `as_of` and the dict-of-closes
mapping; it filters internally.

Why annualize=False for vol gate: the threshold is a "daily-stdev cutoff",
not an annualized number. Annualizing would conflate the threshold with
calendar time and tie it to whatever the user expects annualized vol to be.
Caller picks the threshold in whatever units make sense (e.g. 0.05 = 5%
daily stdev → roughly 95% annualised). For the comparison we use a per-arm
threshold that's stable in units.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Mapping, Optional

from src.data.vector.market_state import (
    _finite,
    pct_change,
    realized_vol,
)


def _bars_upto(closes: Mapping[str, float], upto: str) -> list[str]:
    """Return sorted list of bar dates <= `upto`. NaN/None dates dropped."""
    return sorted(d for d in closes if d <= upto and d)


def _safe_close(closes: Mapping[str, float], day: str) -> Optional[float]:
    """PIT-safe read: returns close at `day` if present, else None.

    A None result is a "we can't compute this factor", NOT a 0.0 (which
    would distort mom_60 via division by near-zero).
    """
    v = closes.get(day)
    if v is None or not isinstance(v, (int, float)) or v <= 0:
        return None
    return float(v)


def _sma(closes_ordered: list[float], window: int) -> Optional[float]:
    """Plain SMA on a time-ordered list of closes. None if insufficient depth."""
    if len(closes_ordered) < window or window < 1:
        return None
    return sum(closes_ordered[-window:]) / window


def compute_factor_signals(
    closes: Mapping[str, float],                # {YYYY-MM-DD: close}, not pre-sorted
    as_of: date,
    *,
    sma_window: int = 60,
    mom_window: int = 60,
    vol_window: int = 30,
    vol_threshold: float = 0.05,                # daily stdev cutoff
    sma_ok_rule: str = "above",                 # "above" → close > SMA
) -> dict[str, bool]:
    """Per-symbol pass/fail for each of the three factors.

    Args:
        closes: symbol → {date_iso: close} mapping. Should contain bars from
                at least `mom_window + sma_window + 1` trading days back from
                `as_of - 1`.
        as_of: evaluation date (signal uses bars <= as_of - 1 day).
        sma_window: lookback for the SMA trend filter (default 60).
        mom_window: lookback for the momentum filter (default 60).
        vol_window: rolling window for realized vol (default 30).
        vol_threshold: max daily stdev to pass the vol gate (default 0.05).
        sma_ok_rule: "above" = close > SMA passes (trend up);
                          "below_or_equal" = close <= SMA passes (mean-reversion;
                          NOT shipped in v1, kept for future extension).

    Returns:
        dict with keys 'sma_ok', 'mom_ok', 'vol_ok', 'all_ok'. Each value is
        bool. If any factor is uncomputable (insufficient depth / zero divide),
        that factor is False (filter, don't crash).

    The function is **pure** — no I/O, no DB, no datetime.now() — so it's
    deterministic and replay-safe.
    """
    d_lag1 = (as_of - timedelta(days=1)).isoformat()

    # Build a time-ordered closes list up to d_lag1 (PIT)
    ordered_dates = _bars_upto(closes, d_lag1)
    ordered_closes = [closes[d] for d in ordered_dates
                      if isinstance(closes[d], (int, float)) and closes[d] > 0]
    if len(ordered_closes) < max(sma_window, mom_window + 1, vol_window + 1):
        # Not enough history → all three fail.
        return {"sma_ok": False, "mom_ok": False, "vol_ok": False, "all_ok": False}

    # SMA60_ok — signal uses bars <= d_lag1 (NOT today's mark).
    last_close = ordered_closes[-1]
    sma_n = _sma(ordered_closes, sma_window)
    if sma_n is None or sma_n <= 0:
        sma_ok = False
    elif sma_ok_rule == "above":
        sma_ok = last_close > sma_n
    elif sma_ok_rule == "below_or_equal":
        sma_ok = last_close <= sma_n
    else:
        raise ValueError(
            f"sma_ok_rule='{sma_ok_rule}' 非法 — 只接 'above' / 'below_or_equal'")

    # mom_60_ok — pct_change over `mom_window` bars up to d_lag1.
    # We build a sub-list of closes up to d_lag1 for pct_change.
    mom = pct_change(ordered_closes, lag=mom_window)
    mom_ok = (mom is not None and mom > 0.0)

    # vol_30_ok — daily stdev of last `vol_window` returns, must be < threshold.
    # We compute returns directly: r_t = closes[t] / closes[t-1] - 1.
    if len(ordered_closes) >= vol_window + 1:
        rets = [ordered_closes[i] / ordered_closes[i - 1] - 1.0
                for i in range(-vol_window, 0)]
        rv = realized_vol(rets, annualize=False)
        vol_ok = (rv is not None and rv < vol_threshold)
    else:
        vol_ok = False

    all_ok = bool(sma_ok and mom_ok and vol_ok)
    return {"sma_ok": bool(sma_ok), "mom_ok": bool(mom_ok),
            "vol_ok": bool(vol_ok), "all_ok": all_ok}


def passes_factor_gate(closes: Mapping[str, float], as_of: date, **kwargs
                       ) -> dict[str, dict[str, bool]]:
    """Per-symbol factor signals. Convenience wrapper for arm C.

    Returns: {symbol: {sma_ok, mom_ok, vol_ok, all_ok}}. Same shape per symbol.
    For use by `decide_panel_long_only_simple_factor` in spec_runner.py.
    """
    return {sym: compute_factor_signals(c, as_of, **kwargs)
            for sym, c in closes.items()}


__all__ = ["compute_factor_signals", "passes_factor_gate"]
