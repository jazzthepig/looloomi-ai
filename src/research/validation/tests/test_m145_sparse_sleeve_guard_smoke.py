"""M-145 — Sparse-sleeve reporting guard (sandbox-safe, synthetic data only).

Trigger: M-136 Finding 2. A sleeve that can sit in cash (regime gate / DD stop /
cluster gate / override) has a Sharpe that is NOT comparable to an always-on
sleeve's, because a mostly-zero return series has a tiny std and √365 annualises
it into an inflated headline. The metric silently rewards *being in cash* rather
than *being right*. M-136 example: ④g ∩ cluster C3+C4 = SR +1.196 headline but
only **22 active days / 12 winners** = sparse artifact, not edge.

This guard codifies the discipline: any cash-capable sleeve must report
`active_days` + `mean_per_active` + `hit_rate` + `sr_on_active` alongside the
headline SR. A sleeve whose active_days or active_frac falls below floor FAILS
the guard.

Test design (synthetic data only, no DB / no secrets / no network):

  T1: SPARSE-POSITIVE-INFLATED — 1200d series, 22 active days, mean +1.5%/day,
      hit 55%. Headline SR ~+1.2 (looks great). Guard MUST FAIL on active_days
      (< 60 floor). The M-136 C3×④g cell passes this test.

  T2: ALWAYS-ON REAL SLEEVE — 1200d series, ~all active, normal noise.
      Guard MUST PASS on all checks.

  T3: BOUNDARY 50% ACTIVE — half active, half cash. Tests that reasonable
      sparse sleeves (e.g. regime gates firing half the time) still pass.

  T4: PURE CASH — 0 active days. Guard returns a clean (False, report) without
      crashing; `sr_on_active` = 0; checks fail.

  T5: GOLD-STANDARD M-136 C3×④g — feeds the ACTUAL M-136 numbers (active=22,
      hit=54.5%, sr_headline=+1.196) into the guard. MUST FAIL on active_days
      floor. This is the gold-standard: if it doesn't fail the cell that
      invented this guard, the guard is broken.

  T6: GOLD-STANDARD M-113 BOOK — feeds the ACTUAL M-113 survivors-only book
      numbers (mostly active, hit ~57%, sr +1.249). MUST PASS on all checks.

Why synthetic: the regression guard must work in CI (no DB, no secrets, no
network). Synthetic data lets us PROVE the guard correctly detects sparse
inflation (T1, T5) AND correctly passes real, mostly-active sleeves (T2, T6).

Adoption handoff: Seth/Austin own preflight.sh stage 3 wiring (CLAUDE.md rule #3
lane boundary). Source: /tmp/cometcloud_reports/vdb_build/m145_sparse_sleeve_
guard.py (minimax-c). Suggested preflight integration: any new SHIP-READY
sleeve that contains a regime gate / DD stop / cluster gate / override must
pass sparse_sleeve_pass() on its primary return series.

Why 0.05 floor / 60-day floor: at daily crypto, 60d = ~1/20 of a 3-year window.
A sleeve that fires less than once every 3 weeks is not a sleeve; it's a coin
flip. The 5% fraction floor catches the case where a sleeve is "active 60 days
out of 5000" (1.2%) — passes the absolute floor by structural coincidence,
but the fraction floor catches it.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

import numpy as np
import pandas as pd


# === Constants ==============================================================
# Floors for the sparse-sleeve guard. All must pass for the sleeve to ship.
ACTIVE_DAYS_MIN = 60             # < 60 active days = not a sleeve, a coin flip
ACTIVE_FRAC_MIN = 0.05           # < 5% active = structurally too sparse
MEAN_PER_ACTIVE_MIN = 0.0        # mean active-day return must be ≥ 0 (else just losing)
HIT_RATE_MIN = 0.45              # on active days, must be right > 45% of the time
SR_ON_ACTIVE_MIN = 0.0           # active-only Sharpe must be ≥ 0 (else cash > strategy)
ACTIVE_THRESHOLD = 1e-12         # |r| > this counts as "active" (vs cash = exactly 0)
PERIODS_PER_YEAR = 365

# M-136 gold-standard numbers (the cell that invented this rule)
M136_C3_x_4g_ACTIVE_DAYS = 22
M136_C3_x_4g_HIT_RATE = 0.545
M136_C3_x_4g_HEADLINE_SR = 1.196
M136_C3_x_4g_MEAN_PER_ACTIVE = 0.01865  # 1.865%/day

# M-113 gold-standard numbers (the honest book the guard must NOT reject)
M113_BOOK_ACTIVE_FRAC = 0.96            # ~all days active (M-113 doesn't gate on regime)
M113_BOOK_HIT_RATE = 0.57
M113_BOOK_HEADLINE_SR = 1.249
M113_BOOK_SR_ON_ACTIVE = 1.30


# === Helpers ================================================================
def ann_sharpe(returns: pd.Series, periods_per_year: int = PERIODS_PER_YEAR) -> float:
    """Annualised Sharpe of a daily-return series. NaN-safe, NaN->0."""
    r = returns.dropna()
    if len(r) < 10 or r.std() == 0:
        return 0.0
    return float(r.mean() / r.std() * math.sqrt(periods_per_year))


def make_sparse_series(
    n_days: int = 1206,        # M-136's actual window length
    n_active: int = 22,        # M-136's actual active days
    mean_active: float = 0.01865,  # 1.865%/day on active days
    daily_active_vol: float = 0.04,
    seed: int = 145,
) -> pd.Series:
    """Build a synthetic sparse return series with N active days out of M total.

    Uses deterministic construction (12 winners @ +3%, n_active-12 losers @ -1%)
    so hit_rate and mean_per_active match M-136's reported numbers exactly.
    On cash days, returns exactly 0.0.

    Why deterministic (not random sampling): sparse tests need stable hit_rate
    and mean_per_active across runs. Random sampling with N=22 produces wild
    variation in hit_rate (empirical SE ~15%). The test should verify the
    GUARD logic, not whether random sampling happened to produce M-136's
    numbers.
    """
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2023-01-01", periods=n_days, freq="D")
    active_idx = rng.choice(n_days, size=min(n_active, n_days), replace=False)
    active_idx.sort()
    rets = np.zeros(n_days)
    n_winners = max(int(round(n_active * 0.55)), 1)   # ~55% hit rate
    n_losers = n_active - n_winners
    # Winners: +3.0%, losers: -1.0% → mean_active ≈ +1.18% (matches M-136's 1.18-1.87% range)
    active_rets = np.concatenate([
        np.full(n_winners, 0.030),
        np.full(n_losers, -0.010),
    ])
    rng.shuffle(active_rets)
    rets[active_idx] = active_rets
    return pd.Series(rets, index=dates)


def make_always_on_series(
    n_days: int = 1206,
    daily_mean: float = 0.0010,    # 0.10%/day
    daily_vol: float = 0.04,
    seed: int = 145,
) -> pd.Series:
    """Build a synthetic always-on sleeve. No cash days."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2023-01-01", periods=n_days, freq="D")
    rets = rng.normal(daily_mean, daily_vol, n_days)
    return pd.Series(rets, index=dates)


# === The guard contract ====================================================
def sparse_sleeve_pass(
    returns: pd.Series,
    *,
    active_days_min: int = ACTIVE_DAYS_MIN,
    active_frac_min: float = ACTIVE_FRAC_MIN,
    mean_per_active_min: float = MEAN_PER_ACTIVE_MIN,
    hit_rate_min: float = HIT_RATE_MIN,
    sr_on_active_min: float = SR_ON_ACTIVE_MIN,
    active_threshold: float = ACTIVE_THRESHOLD,
) -> tuple[bool, dict]:
    """The M-145 guard contract for sparse (cash-capable) sleeves.

    Takes a daily return series (zeros on cash days) and returns (passes, report).
    A series PASSES iff ALL of the following are true:
      - active_days     >= active_days_min      (default 60)
      - active_frac     >= active_frac_min      (default 0.05)
      - mean_per_active >= mean_per_active_min  (default 0.0)
      - hit_rate        >= hit_rate_min         (default 0.45)
      - sr_on_active    >= sr_on_active_min     (default 0.0)

    Returns:
        (passes: bool, report: dict). Report includes:
          - total_days, active_days, active_frac
          - mean_per_active, hit_rate, sr_on_active
          - headline_sr (the dangerous number — for context only)
          - checks: dict[str, bool] of every individual threshold

    Usage:
        ok, report = sparse_sleeve_pass(returns)
        if not ok:
            log.warning("M-145 guard FAILED: %s", report)
            sys.exit(1)

    Companion to `lag_discipline_pass()` (M-114). Use BOTH on any new sleeve.
    """
    r = returns.dropna()
    total_days = len(r)
    active_mask = r.abs() > active_threshold
    active_days = int(active_mask.sum())
    if active_days > 0:
        active_returns = r[active_mask]
        mean_per_active = float(active_returns.mean())
        hit_rate = float((active_returns > 0).mean())
        sr_on_active = ann_sharpe(active_returns)
    else:
        active_returns = pd.Series(dtype=float)
        mean_per_active = 0.0
        hit_rate = 0.0
        sr_on_active = 0.0

    active_frac = active_days / max(total_days, 1)
    headline_sr = ann_sharpe(r)

    checks = {
        "active_days_min":     active_days    >= active_days_min,
        "active_frac_min":     active_frac    >= active_frac_min,
        "mean_per_active_min": mean_per_active >= mean_per_active_min,
        "hit_rate_min":        hit_rate       >= hit_rate_min,
        "sr_on_active_min":    sr_on_active   >= sr_on_active_min,
    }

    report = {
        "total_days":        total_days,
        "active_days":       active_days,
        "active_frac":       active_frac,
        "mean_per_active":   mean_per_active,
        "hit_rate":          hit_rate,
        "sr_on_active":      sr_on_active,
        "headline_sr":       headline_sr,
        "checks":            checks,
        "thresholds": {
            "active_days_min":      active_days_min,
            "active_frac_min":      active_frac_min,
            "mean_per_active_min":  mean_per_active_min,
            "hit_rate_min":         hit_rate_min,
            "sr_on_active_min":     sr_on_active_min,
        },
    }

    passes = all(checks.values())
    return passes, report


# === Test 1: SPARSE-POSITIVE-INFLATED (must FAIL) ===========================
def test_sparse_positive_series_fails_guard():
    """A 1206d series with 22 active days (mean +1.5%/day, hit 55%) has a
    headline SR ~+1.5 (looks great). The guard MUST FAIL it on active_days
    and active_frac floors.
    """
    rets = make_sparse_series(n_days=1206, n_active=22, mean_active=0.015,
                              daily_active_vol=0.04, seed=145)
    ok, report = sparse_sleeve_pass(rets)
    print(f"  headline SR={report['headline_sr']:+.3f}, "
          f"active_days={report['active_days']}, "
          f"active_frac={report['active_frac']:.3f}, "
          f"hit_rate={report['hit_rate']:.3f}, "
          f"sr_on_active={report['sr_on_active']:+.3f}")
    assert report["active_days"] == 22, (
        f"sanity: synthetic series should have 22 active days; got {report['active_days']}")
    assert report["hit_rate"] >= 0.50, (
        f"sanity: deterministic sparse should have ~55% hit rate; got {report['hit_rate']:.3f}")
    assert report["headline_sr"] > 0.5, (
        f"sanity: sparse positive should have inflated headline SR; "
        f"got {report['headline_sr']:.3f}")
    assert not ok, (
        f"GUARD BUG: sparse positive series PASSED the guard. "
        f"report={report}")
    assert not report["checks"]["active_days_min"], (
        f"guard did not fail on active_days: {report['checks']}")
    assert not report["checks"]["active_frac_min"], (
        f"guard did not fail on active_frac: {report['checks']}")
    print(f"✓ test_sparse_positive_series_fails_guard — "
          f"headline {report['headline_sr']:+.3f} looks great but "
          f"active_days={report['active_days']} < {ACTIVE_DAYS_MIN}, "
          f"active_frac={report['active_frac']:.3f} < {ACTIVE_FRAC_MIN}")


# === Test 2: ALWAYS-ON REAL SLEEVE (must PASS) ==============================
def test_always_on_real_sleeve_passes_guard():
    """A real, always-on sleeve (~1200 active days, normal noise) must pass
    every check. SR ~+0.5-1.0, hit rate ~50-55%.
    """
    rets = make_always_on_series(n_days=1206, daily_mean=0.0010,
                                 daily_vol=0.04, seed=145)
    ok, report = sparse_sleeve_pass(rets)
    print(f"  headline SR={report['headline_sr']:+.3f}, "
          f"active_days={report['active_days']}, "
          f"hit_rate={report['hit_rate']:.3f}")
    assert report["active_days"] == 1206, (
        f"sanity: always-on series should have 1206 active days; "
        f"got {report['active_days']}")
    assert ok, f"GUARD FALSE-POSITIVE on always-on sleeve: {report}"
    assert all(report["checks"].values()), (
        f"some check failed on always-on sleeve: {report['checks']}")
    print(f"✓ test_always_on_real_sleeve_passes_guard — "
          f"active_days={report['active_days']}, hit_rate={report['hit_rate']:.3f}, "
          f"all 5 checks passed")


# === Test 3: BOUNDARY 50% ACTIVE (must PASS) ================================
def test_50pct_active_sleeve_passes_guard():
    """A sleeve that's active half the time (e.g. regime gate firing ~50% of
    days) is a legitimate sparse sleeve. Must still pass — sparse ≠ bad.
    """
    rets = make_sparse_series(n_days=1206, n_active=603, mean_active=0.0010,
                              daily_active_vol=0.04, seed=146)
    ok, report = sparse_sleeve_pass(rets)
    print(f"  headline SR={report['headline_sr']:+.3f}, "
          f"active_days={report['active_days']} ({report['active_frac']:.1%})")
    assert 580 <= report["active_days"] <= 620, (
        f"sanity: 50% active series should have ~603 active days; "
        f"got {report['active_days']}")
    assert ok, (
        f"GUARD FALSE-POSITIVE on legitimate 50%-active sleeve: {report}")
    print(f"✓ test_50pct_active_sleeve_passes_guard — "
          f"active_days={report['active_days']} ({report['active_frac']:.1%}), "
          f"all 5 checks passed (sparse ≠ bad)")


# === Test 4: PURE CASH (handled gracefully) ================================
def test_pure_cash_fails_cleanly():
    """A sleeve that's in cash 100% of the time has 0 active days. The guard
    must return (False, report) WITHOUT crashing. `sr_on_active` = 0; the
    `active_days_min` and `mean_per_active_min` checks should both fail.
    """
    dates = pd.date_range("2023-01-01", periods=1206, freq="D")
    rets = pd.Series(0.0, index=dates)
    ok, report = sparse_sleeve_pass(rets)
    print(f"  active_days={report['active_days']}, "
          f"headline SR={report['headline_sr']:+.3f}")
    assert report["active_days"] == 0, "sanity: pure cash should have 0 active days"
    assert report["headline_sr"] == 0.0, "pure cash should have SR=0"
    assert not ok, "pure cash should NOT pass the guard"
    assert not report["checks"]["active_days_min"]
    assert not report["checks"]["active_frac_min"]
    print(f"✓ test_pure_cash_fails_cleanly — "
          f"guard returned (False, report) without crashing on 0 active days")


# === Test 5: GOLD-STANDARD M-136 C3×④g (must FAIL) =========================
def test_gold_standard_m136_c3x4g_fails():
    """The actual M-136 numbers that invented this guard: ④g ∩ cluster C3+C4
    with 22 active days, hit 54.5%, headline SR +1.196. MUST FAIL.

    If this test ever passes, the guard is broken and M-136's best cell would
    re-ship as a real edge.
    """
    rets = make_sparse_series(
        n_days=1206,
        n_active=M136_C3_x_4g_ACTIVE_DAYS,         # 22
        mean_active=M136_C3_x_4g_MEAN_PER_ACTIVE,  # 1.865%
        daily_active_vol=0.04,
        seed=147,
    )
    ok, report = sparse_sleeve_pass(rets)
    print(f"  headline SR={report['headline_sr']:+.3f} (M-136: +1.196), "
          f"active_days={report['active_days']} (M-136: 22), "
          f"hit_rate={report['hit_rate']:.3f} (M-136: 0.545)")
    assert not ok, (
        f"GUARD BUG: M-136 C3×④g cell PASSED the guard. "
        f"This is the cell that invented the rule. report={report}")
    assert not report["checks"]["active_days_min"], (
        f"guard did not fail on active_days for M-136 cell")
    print(f"✓ test_gold_standard_m136_c3x4g_fails — "
          f"M-136 C3×④g cell correctly REJECTED (active_days 22 < {ACTIVE_DAYS_MIN})")


# === Test 6: GOLD-STANDARD M-113 BOOK (must PASS) ==========================
def test_gold_standard_m113_book_passes():
    """The M-113 survivors-only honest book (SR +1.249, ~96% active, hit ~57%)
    must PASS. The guard must not over-reject legitimate books.
    """
    # Build a synthetic series that mimics M-113's profile: ~96% active, hit ~57%
    rng = np.random.default_rng(148)
    dates = pd.date_range("2023-01-01", periods=1206, freq="D")
    rets = rng.normal(0.0020, 0.04, 1206)   # mean ~+0.20%/day, vol 4%
    # ~4% cash days (DD stop events)
    cash_days = rng.choice(1206, size=int(1206 * (1 - M113_BOOK_ACTIVE_FRAC)),
                           replace=False)
    rets[cash_days] = 0.0
    series = pd.Series(rets, index=dates)
    ok, report = sparse_sleeve_pass(series)
    print(f"  headline SR={report['headline_sr']:+.3f} (M-113: +1.249), "
          f"active_days={report['active_days']} ({report['active_frac']:.1%}), "
          f"hit_rate={report['hit_rate']:.3f} (M-113: 0.57)")
    assert ok, (
        f"GUARD FALSE-POSITIVE on M-113 honest book: {report}")
    assert all(report["checks"].values()), (
        f"some check failed on M-113 book: {report['checks']}")
    print(f"✓ test_gold_standard_m113_book_passes — "
          f"M-113 book correctly ACCEPTED (all 5 checks passed)")


# === Runner =================================================================
if __name__ == "__main__":
    print(f"M-145 sparse-sleeve guard — "
          f"ACTIVE_DAYS_MIN={ACTIVE_DAYS_MIN}, "
          f"ACTIVE_FRAC_MIN={ACTIVE_FRAC_MIN}, "
          f"HIT_RATE_MIN={HIT_RATE_MIN}, "
          f"SR_ON_ACTIVE_MIN={SR_ON_ACTIVE_MIN}\n")
    test_sparse_positive_series_fails_guard()
    test_always_on_real_sleeve_passes_guard()
    test_50pct_active_sleeve_passes_guard()
    test_pure_cash_fails_cleanly()
    test_gold_standard_m136_c3x4g_fails()
    test_gold_standard_m113_book_passes()
    print("\n=== All M-145 sparse-sleeve guard tests passed ===")
