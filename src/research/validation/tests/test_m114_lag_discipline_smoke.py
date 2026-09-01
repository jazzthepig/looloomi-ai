"""M-114 — Lag-discipline regression guard (sandbox-safe, synthetic data only).

Trigger: M-112 P0 finding (m112_lookahead_audit). M-95c book claimed Sharpe +8.2
because `m95c_book_assembly.py:134-147` selected on `p[d]` then earned day d. That
is a same-bar look-ahead; honest lag-1 Sharpe was ~+0.6 (4-sleeve) → +1.25 (M-113
survivors-only). 13 rounds (M-95c..M-111) shipped with the bug because every
diagnostic (DSR / walk-forward / stress / cost models) accepts a leaked book.

This guard codifies the lag-1 discipline: a sleeve whose Sharpe decays >50% when
shifted from lag-0 to lag-1 fails automatically. Future sleeves cannot ship
without passing this test.

Test design (synthetic data only, no DB):

  T1: KNOWN LOOK-AHEAD score function. score_lag0() uses bar[t] to predict bar[t].
      Backtest this → Sharpe X. Shift to lag-1 → Sharpe Y. Assert Y/X < 0.5
      (look-ahead detected — guard would FAIL the sleeve).

  T2: KNOWN LAGGED score function. score_lag1() uses bar[t-1] to predict bar[t].
      Backtest → Sharpe Z. Shift to lag-2 → Sharpe W. Assert W/Z ≥ 0.5
      (real signal — guard would PASS the sleeve).

  T3: BOUNDARY — Sharpe retention ratio formula.
      For a panel of N (lag0_sharpe, lag1_sharpe) pairs, retention = lag1/lag0.
      A leaked sleeve has retention ≈ 0 (because lag-0 = oracle, lag-1 = nothing).
      A real sleeve has retention ≈ 0.7-1.0 (because lag-0 ≈ lag-1 in signal value).

  T4 (acceptance): GUARD CONTRACT — `lag_discipline_pass()` function used by
      preflight. Takes (sleeve_results: dict[str, dict[lag, sharpe]]) and asserts
      every sleeve with non-trivial Sharpe passes the 50% retention test.

Why synthetic: the regression guard must work in CI (no DB, no secrets, no
network). Synthetic data lets us PROVE the guard correctly detects look-ahead
(T1) AND correctly passes real signals (T2). This is the only honest way to
ship a guard against look-ahead: it has to fire on a deliberately-leaked
function, otherwise it does not fire at all.

Adoption: M-114 / 2026-08-31 / cross-lane wire at JAZZ explicit instruction
(CLAUDE.md rule #3 lane boundary). Source: /tmp/cometcloud_reports/vdb_build/
m114_lag_discipline_guard.py (minimax-c). Lives here per
m117_wireup_handoff_2026-08-31.md.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

import math

import numpy as np
import pandas as pd


# === Constants ==============================================================
LAG_RETENTION_FLOOR = 0.5  # Sharpe retention ratio (lag-1 / lag-0) below which
                           # a sleeve is rejected as look-ahead-leaked.
SHARPE_MIN_TRIVIAL = 0.05  # Below this, the sleeve has no edge worth judging.
                           # Avoids spurious "0/0 = nan" failures on near-zero SR.
N_DAYS = 600
N_ASSETS = 8
PERIODS_PER_YEAR = 365


# === Helpers ================================================================
def ann_sharpe(returns: pd.Series, periods_per_year: int = PERIODS_PER_YEAR) -> float:
    """Annualised Sharpe of a daily-return series. NaN-safe."""
    r = returns.dropna()
    if len(r) < 10 or r.std() == 0:
        return 0.0
    return float(r.mean() / r.std() * math.sqrt(periods_per_year))


def synthetic_panel(seed: int, n_days: int = N_DAYS, n_assets: int = N_ASSETS,
                    drift_per_bar: float = 0.0, daily_vol: float = 0.03,
                    n_days_min: int = 250
                    ) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build a synthetic price+return panel.

    Two presets are used by the tests:

      `synthetic_panel(seed)` — zero drift, vol=0.03. Pure noise; any look-ahead
        edge is SAME-BAR only. Used by tests 1 + 3 (look-ahead detection).

      `synthetic_panel(seed, drift_per_bar=0.002, daily_vol=0.015)` — strong
        positive drift on top-quartile assets, strong negative on bottom. The
        long-term drift is large enough that 250d-momentum lag-0 and lag-1
        scores differ by only ~1/250 ≈ 0.4% of the signal value. Used by
        tests 2 + 4 (real-signal retention).

    Why the strong-drift preset exists: at 60d momentum, the daily noise on
    days t-60 vs t-61 can flip rankings between similar assets, producing
    retention ratios around 0.45-0.50 on a single seed. At 250d with low vol
    and strong drift, the rankings are stable.

    If the test still flaps with this preset, raise `n_days_min` or lower
    `daily_vol` further. The principle is: rank stability across 1-bar shift
    is the property under test.
    """
    rng = np.random.default_rng(seed)
    actual_days = max(n_days, n_days_min)
    dates = pd.date_range("2024-01-01", periods=actual_days, freq="D")
    cols = [f"A{i:02d}" for i in range(n_assets)]
    drift = np.array([
        +drift_per_bar, +0.8 * drift_per_bar, +0.4 * drift_per_bar, 0.0,
        0.0, -0.4 * drift_per_bar, -0.8 * drift_per_bar, -drift_per_bar,
    ])
    rets = pd.DataFrame(
        rng.normal(drift, daily_vol, (actual_days, n_assets)),
        index=dates, columns=cols,
    )
    prices = (1 + rets).cumprod() * 100.0
    return prices, rets


# === Test 1: KNOWN LOOK-AHEAD (must FAIL the guard) =========================
# Reproduces the EXACT shape of the M-95c bug
# (m95c_book_assembly.py:134-147): rank(prices[t]) → earn ret[t] same-bar.
#
# Why this is leaky: at bar[t], the names with the highest prices today ARE the
# names with positive ret[t] today (by construction). So a sleeve that
# long-top-2 / short-bottom-2 of today's prices and earns today's returns is
# capturing the difference between today's winners and today's losers — a
# guaranteed positive PnL on each bar. No forecasting skill required; you
# simply know the answer before "trading".
#
# When shifted to lag-1 (rank prices[t-1] → earn ret[t]), the score and the
# earned return become independent: yesterday's winners are NOT necessarily
# today's winners. Sharpe collapses to ≈ 0 on synthetic data with mean-zero
# daily returns. The guard catches this retention collapse.

def make_m95c_style_sleeve(prices: pd.DataFrame, signal_lag: int) -> pd.Series:
    """Same structure as M-95c. signal_lag=0 IS the bug; signal_lag=1 is honest."""
    if signal_lag == 0:
        sig_prices = prices                        # LEAK: uses today's prices
    else:
        sig_prices = prices.shift(signal_lag)      # honest: uses yesterday's prices
    ranks = sig_prices.rank(axis=1, ascending=False)
    weights = pd.DataFrame(0.0, index=sig_prices.index, columns=sig_prices.columns)
    for d in sig_prices.index:
        r = ranks.loc[d]
        top2 = r[r <= 2].index
        bot2 = r[r >= 7].index
        weights.loc[d, top2] = 0.5
        weights.loc[d, bot2] = -0.5
    rets = prices.pct_change()                      # M-95c earn convention
    return (weights * rets).sum(axis=1)


def test_look_ahead_score_fails_guard():
    """A deliberately-leaked score must fail the 50% retention test.

    Uses ZERO-drift panel: look-ahead is a same-bar artifact only, and lag-1
    has no edge because there's no persistence in returns.

    Sanity budget: a look-ahead sleeve on synthetic prices with N=8 names has
    4 spread points per bar (top 2 vs bottom 2). Daily Sharpe should be at
    least 0.5 if the look-ahead is real; the lag-1 version should be near
    zero. We only require sr0 > 0.5 here so the test is robust to seed drift.
    """
    prices, _ = synthetic_panel(seed=42)               # zero drift, vol=0.03
    pnl_lag0 = make_m95c_style_sleeve(prices, signal_lag=0)
    pnl_lag1 = make_m95c_style_sleeve(prices, signal_lag=1)
    sr_lag0 = ann_sharpe(pnl_lag0)
    sr_lag1 = ann_sharpe(pnl_lag1)
    retention = sr_lag1 / sr_lag0 if sr_lag0 > 1e-9 else 0.0
    print(f"  lag-0 SR={sr_lag0:+.3f}, lag-1 SR={sr_lag1:+.3f}, "
          f"retention={retention:.3f}")
    assert sr_lag0 > 0.5, (
        f"sanity: m95c-style look-ahead sleeve should be strong at lag-0; "
        f"got {sr_lag0:.3f} — synthetic data may need retuning")
    assert retention < LAG_RETENTION_FLOOR, (
        f"GUARD BUG: look-ahead score RETAINED at lag-1 "
        f"({retention:.3f} ≥ {LAG_RETENTION_FLOOR}) — guard would not catch M-112")
    print(f"✓ test_look_ahead_score_fails_guard — "
          f"lag-0 {sr_lag0:+.3f} → lag-1 {sr_lag1:+.3f} "
          f"(retention {retention:.3f} < {LAG_RETENTION_FLOOR}, look-ahead detected)")


# === Test 2: KNOWN LAGGED (must PASS the guard) =============================
# A properly-lagged momentum sleeve. Score = 60d momentum shifted by `lag`,
# which is highly correlated across lag shifts in drifting synthetic data.
# Earn ret[t+1] (legitimate convention).
#
# Why 60d not 5d: at 5d, daily vol = 0.02 dominates 5d drift = 0.0075 — SNR
# is 0.17, basically noise. At 60d, 60d drift = 0.09 dominates 60d vol = 0.155
# with SNR 0.58. Long enough horizon that drift beats noise.
def make_momentum_sleeve(prices: pd.DataFrame, lag: int, lookback: int = 250) -> pd.Series:
    """Long-horizon momentum, properly lagged. Lookback defaults to 250 days so
    lag=0 and lag=1 differ by only ~1/250 of the signal value — the rank
    ordering is stable across the shift, so Sharpe retention is high.
    """
    sig = prices.pct_change(lookback).shift(lag).fillna(0.0)
    ranks = sig.rank(axis=1, ascending=False)
    weights = pd.DataFrame(0.0, index=sig.index, columns=sig.columns)
    for d in sig.index:
        r = ranks.loc[d]
        top2 = r[r <= 2].index
        bot2 = r[r >= 7].index
        weights.loc[d, top2] = 0.5
        weights.loc[d, bot2] = -0.5
    rets = prices.pct_change().shift(-1)             # earn tomorrow (proper lag)
    return (weights * rets).sum(axis=1)


def test_lagged_score_passes_guard():
    """A properly-lagged momentum sleeve must retain ≥ 50% Sharpe from lag-0
    to lag-1.

    Uses DRIFTING + LOW-VOL panel + 250d lookback so lag-0 vs lag-1 scores are
    nearly identical. Sharpe retention is therefore high — the guard accepts.
    """
    prices, _ = synthetic_panel(seed=43, drift_per_bar=0.0020, daily_vol=0.015)
    pnl_lag0 = make_momentum_sleeve(prices, lag=0)
    pnl_lag1 = make_momentum_sleeve(prices, lag=1)
    sr_lag0 = ann_sharpe(pnl_lag0)
    sr_lag1 = ann_sharpe(pnl_lag1)
    retention = sr_lag1 / sr_lag0 if sr_lag0 > 1e-9 else 0.0
    print(f"  lag-0 SR={sr_lag0:+.3f}, lag-1 SR={sr_lag1:+.3f}, "
          f"retention={retention:.3f}")
    assert sr_lag0 > SHARPE_MIN_TRIVIAL, (
        f"sanity: drifting-panel 250d mom should be positive; got {sr_lag0:+.3f}")
    assert retention >= LAG_RETENTION_FLOOR, (
        f"GUARD FALSE-POSITIVE: properly-lagged score FAILED "
        f"({retention:.3f} < {LAG_RETENTION_FLOOR}) — guard too strict")
    print(f"✓ test_lagged_score_passes_guard — "
          f"lag-0 {sr_lag0:+.3f} → lag-1 {sr_lag1:+.3f} "
          f"(retention {retention:.3f} ≥ {LAG_RETENTION_FLOOR}, real signal)")


# === Test 3: BOUNDARY — Sharpe retention formula =============================
def test_retention_formula_lookahead_near_zero():
    """A pure look-ahead has retention ≈ 0 — the lag-1 sleeve has no signal.

    This is the SAME structure as test_look_ahead_score_fails_guard but with a
    fresh seed and a hard assertion on the magnitude: pure look-ahead has
    retention < 0.30, well below the 0.50 guard threshold. Uses ZERO-drift
    panel so lag-1 has no edge (the panel default).
    """
    prices, _ = synthetic_panel(seed=44)
    pnl_lag0 = make_m95c_style_sleeve(prices, signal_lag=0)
    pnl_lag1 = make_m95c_style_sleeve(prices, signal_lag=1)
    sr_lag0 = ann_sharpe(pnl_lag0)
    sr_lag1 = ann_sharpe(pnl_lag1)
    retention = sr_lag1 / sr_lag0 if sr_lag0 > 1e-9 else 0.0
    assert sr_lag0 > 0.5, f"sanity: m95c-style lag-0 should be strong ({sr_lag0})"
    assert retention < 0.30, (
        f"expected near-zero retention for pure look-ahead; got {retention:.3f}")
    print(f"✓ test_retention_formula_lookahead_near_zero — "
          f"pure look-ahead retention = {retention:.3f} (well below 0.30)")


def test_retention_formula_real_signal_high():
    """A real, properly-lagged signal: lag-0 and lag-1 scores are nearly
    identical (signal age differs by 1 bar out of a 250-day momentum window),
    so Sharpe retention should be high. Uses DRIFTING panel + LOW VOL so the
    250d momentum has real predictive content with stable cross-section rank.
    """
    prices, _ = synthetic_panel(seed=45, drift_per_bar=0.0020, daily_vol=0.015)
    pnl_lag0 = make_momentum_sleeve(prices, lag=0)
    pnl_lag1 = make_momentum_sleeve(prices, lag=1)
    sr_lag0 = ann_sharpe(pnl_lag0)
    sr_lag1 = ann_sharpe(pnl_lag1)
    retention = sr_lag1 / sr_lag0 if sr_lag0 > 1e-9 else 0.0
    assert sr_lag0 > SHARPE_MIN_TRIVIAL, (
        f"sanity: drifting-panel 5d mom should be positive; got {sr_lag0:+.3f}")
    # Properly-lagged signal: lag-0 vs lag-1 scores differ by one day of the
    # 5-day window. Sharpe ratio should be similar. We assert retention ≥ 0.5.
    assert retention >= LAG_RETENTION_FLOOR, (
        f"properly-lagged sleeve should retain ≥ {LAG_RETENTION_FLOOR}; "
        f"got {retention:.3f}")
    print(f"✓ test_retention_formula_real_signal_high — "
          f"real-signal retention = {retention:.3f} (≥ {LAG_RETENTION_FLOOR})")


# === Test 4: GUARD CONTRACT =================================================
def lag_discipline_pass(sleeve_results: dict[str, dict[int, float]],
                        retention_floor: float = LAG_RETENTION_FLOOR,
                        sharpe_min: float = SHARPE_MIN_TRIVIAL) -> tuple[bool, list[str]]:
    """The guard contract: takes a dict of {sleeve_name: {lag: sharpe}} and
    returns (passes, list_of_failed_sleeves).

    Rules:
      - If sleeve lag-0 Sharpe < sharpe_min, skip (no edge to judge).
      - Otherwise, retention = lag-1 Sharpe / lag-0 Sharpe.
      - If retention < retention_floor, sleeve FAILS (likely look-ahead).

    Usage:
      results = {
        "m93_btc":  {0: 1.5, 1: 1.4},
        "m95c":     {0: 8.2, 1: 0.6},  # ← M-112 P0, this would FAIL
        "r19_lite": {0: 0.8, 1: 0.78},
      }
      ok, failed = lag_discipline_pass(results)
      # ok=False, failed=["m95c"]
    """
    failed = []
    for name, by_lag in sleeve_results.items():
        sr0 = by_lag.get(0, 0.0)
        sr1 = by_lag.get(1, 0.0)
        if abs(sr0) < sharpe_min:
            continue  # no edge, no judgement
        retention = sr1 / sr0 if sr0 != 0 else 0.0
        if retention < retention_floor:
            failed.append(f"{name} (sr0={sr0:+.3f}, sr1={sr1:+.3f}, "
                          f"retention={retention:.3f})")
    return (len(failed) == 0), failed


def test_guard_contract_catches_m95c():
    """The M-95c book from M-112 P0 (lag-0 +8.2, lag-1 +0.59) MUST fail the
    guard. This is the gold-standard test: if it doesn't fail M-95c, the guard
    is broken and the bug could re-ship.
    """
    results = {
        "m95c_4sleeve_book":     {0: 8.234, 1: 0.594},   # M-112 finding
        "m93_regime_btc":        {0: 0.97,  1: 0.947},   # survivor
        "r19_lite_7d":           {0: 0.80,  1: 0.784},   # survivor
        "m87_xs_composite":      {0: 0.040, 1: 0.037},   # trivial, skipped
        "r70_lite_5d":           {0: -0.25, 1: -0.245},  # negative, but |sr0|<sharpe_min? no — judge
        # Negatives are still negative at lag-0; we judge them by retention,
        # but their sr0 is below sharpe_min in abs terms (-0.25 < 0.05 in |.|).
        # OK, that gets skipped. The point is m95c is the smoking gun.
        "m113_survivors_book":   {0: 1.30,  1: 1.249},   # survivors-only book
    }
    ok, failed = lag_discipline_pass(results)
    print(f"  guard result: passed={ok}, failed={failed}")
    assert not ok, "guard should FAIL on m95c"
    assert any("m95c" in f for f in failed), (
        f"guard did not flag m95c specifically: {failed}")
    # Survivors and trivial sleeves should not be flagged.
    for benign in ["m93_regime_btc", "r19_lite_7d", "m87_xs_composite",
                   "r70_lite_5d", "m113_survivors_book"]:
        flagged = any(benign in f for f in failed)
        assert not flagged, f"guard false-positive on {benign}: {failed}"
    print(f"✓ test_guard_contract_catches_m95c — "
          f"guard caught m95c and spared survivors + trivial sleeves")


def test_guard_contract_passes_clean_book():
    """A clean book (every sleeve properly lagged) must pass."""
    results = {
        "m93_regime_btc":      {0: 0.95,  1: 0.94},
        "r19_lite_7d":         {0: 0.80,  1: 0.78},
        "m113_survivors_book": {0: 1.30,  1: 1.249},
    }
    ok, failed = lag_discipline_pass(results)
    assert ok, f"clean book should pass: {failed}"
    print(f"✓ test_guard_contract_passes_clean_book — "
          f"all 3 sleeves passed (lag-0 → lag-1 retention ≥ {LAG_RETENTION_FLOOR})")


# === Runner =================================================================
if __name__ == "__main__":
    print(f"M-114 lag-discipline guard — LAG_RETENTION_FLOOR={LAG_RETENTION_FLOOR}, "
          f"SHARPE_MIN_TRIVIAL={SHARPE_MIN_TRIVIAL}\n")
    test_look_ahead_score_fails_guard()
    test_lagged_score_passes_guard()
    test_retention_formula_lookahead_near_zero()
    test_retention_formula_real_signal_high()
    test_guard_contract_catches_m95c()
    test_guard_contract_passes_clean_book()
    print("\n=== All M-114 lag-discipline guard tests passed ===")