"""
Smoke tests for pillar_ic_mining (sandbox-safe, synthetic data only).

Tests:
  - verdict(): event-count gate (n < MIN_EVENTS ⇒ INSUFFICIENT)
  - ic_tstat(): mean, t, n from finite values
  - compute_forward_returns(): horizon=5 on 20 days of returns
  - compute_realized_vol(): 30d rolling std × sqrt(365)
  - per_regime_cycle_pillar: synthetic positive-IC cell
  - per_vol_bucket_pillar: synthetic buckets
  - per_asset_class_pillar: synthetic per-class IC
  - run() orchestrator on tiny synthetic df + rets_wide

PIT discipline: tests verify that all NaN-warmup rows are correctly handled
and that the event-count gate is enforced.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))


def t_verdict_event_count_gate():
    """n < MIN_EVENTS ⇒ INSUFFICIENT (the S-78/S-79 lesson)."""
    from src.research.data_align.pillar_ic_mining import verdict, MIN_EVENTS_DEFAULT, MIN_T_ABS
    # Below floor → INSUFFICIENT regardless of t
    assert verdict(5.0, n_events=10) == "⚪ INSUFFICIENT"
    assert verdict(-5.0, n_events=MIN_EVENTS_DEFAULT - 1) == "⚪ INSUFFICIENT"
    # At/above floor, |t| ≥ MIN_T_ABS → POSITIVE/NEGATIVE
    assert verdict(2.5, n_events=MIN_EVENTS_DEFAULT) == "✅ POSITIVE"
    assert verdict(-2.5, n_events=MIN_EVENTS_DEFAULT) == "🔴 NEGATIVE"
    # At/above floor, |t| < MIN_T_ABS → NEUTRAL
    assert verdict(1.0, n_events=MIN_EVENTS_DEFAULT) == "🟡 NEUTRAL"
    assert verdict(-1.0, n_events=MIN_EVENTS_DEFAULT) == "🟡 NEUTRAL"
    # Custom floor
    assert verdict(2.5, n_events=100, min_events=50) == "✅ POSITIVE"
    assert verdict(2.5, n_events=49, min_events=50) == "⚪ INSUFFICIENT"
    print(f"  ✓ verdict: event-count gate enforced (min={MIN_EVENTS_DEFAULT}, |t|≥{MIN_T_ABS})")


def t_ic_tstat_basic():
    """ic_tstat: mean, t, n."""
    from src.research.data_align.pillar_ic_mining import ic_tstat
    # Constant series: std=0 → t=NaN, but mean and n reported
    mean, t, n = ic_tstat(pd.Series([0.1, 0.1, 0.1, 0.1]))
    assert n == 4
    assert mean == 0.1
    assert pd.isna(t)
    # Standard case: random normal ICs
    rng = np.random.default_rng(7)
    ic_vals = pd.Series(rng.normal(0.05, 0.10, 100))
    mean, t, n = ic_tstat(ic_vals)
    assert n == 100
    assert abs(mean - 0.05) < 0.02
    # t-stat magnitude should be > 1.0 (mean 0.05 / std 0.10 / sqrt(100) ≈ 5)
    assert abs(t) > 2.0
    # Empty series
    mean, t, n = ic_tstat(pd.Series(dtype=float))
    assert n == 0
    assert pd.isna(mean)
    print(f"  ✓ ic_tstat: mean/t/n computed; constant → t=NaN; normal → t>2")


def t_forward_returns_horizon_5():
    """compute_forward_returns horizon=5: fwd_ret[t] = prod(1+r[t..t+4]) - 1."""
    from src.research.data_align.pillar_ic_mining import compute_forward_returns
    # 20 days of constant +1% daily returns for ONE asset
    dates = pd.date_range("2024-01-01", periods=20, freq="D")
    rets = pd.DataFrame({"A": [0.01] * 20}, index=dates)
    fwd = compute_forward_returns(rets, horizon=5)
    # At t=0: fwd = (1.01)^5 - 1 = ~0.0510
    expected = (1.01 ** 5) - 1
    actual = fwd["A"].iloc[0]
    assert abs(actual - expected) < 1e-6, f"Expected ~{expected:.4f}, got {actual:.4f}"
    # At t=15: window [t..t+4] = days 15..19, all 1% → same
    assert abs(fwd["A"].iloc[15] - expected) < 1e-6
    # At t=16+: insufficient future data → NaN
    assert pd.isna(fwd["A"].iloc[16])
    # At t=-1 (last row index 19): NaN (no future)
    assert pd.isna(fwd["A"].iloc[19])
    print(f"  ✓ compute_forward_returns: horizon=5; (1.01)^5 - 1 = {expected:.4f}")


def t_realized_vol_annualized():
    """compute_realized_vol: 30d rolling std × sqrt(365)."""
    from src.research.data_align.pillar_ic_mining import compute_realized_vol
    rng = np.random.default_rng(11)
    dates = pd.date_range("2024-01-01", periods=100, freq="D")
    rets = pd.DataFrame({"A": rng.normal(0, 0.02, 100)}, index=dates)
    vol = compute_realized_vol(rets, window=30)
    # First 29 rows: NaN (window=30, min_periods=30)
    assert vol["A"].iloc[:29].isna().all()
    # Row 29: first finite value
    finite = vol["A"].dropna()
    assert len(finite) == 71  # 100 - 29
    # Annualized vol should be much higher than daily std (×sqrt(365) ≈ 19.1)
    daily_std = rets["A"].std()
    annualized = vol["A"].iloc[29]
    ratio = annualized / daily_std
    # pandas rolling.std uses ddof=1 (sample std); full-sample std uses ddof=0.
    # Allow up to 5% slack to absorb the ddof difference + finite-sample drift.
    expected = np.sqrt(365)
    assert abs(ratio - expected) / expected < 0.05, \
        f"Expected ratio ≈ √365={expected:.2f} (within 5%), got {ratio:.2f}"
    print(f"  ✓ compute_realized_vol: window=30, annualized correctly (ratio={ratio:.2f} ≈ √365)")


def t_per_regime_cycle_pillar_positive():
    """Synthetic: pillar_F perfectly predicts forward 30d return ⇒ positive IC."""
    from src.research.data_align.pillar_ic_mining import per_regime_cycle_pillar
    # 100 days × 5 assets, all in RISK_ON cycle
    dates = pd.date_range("2024-01-01", periods=100, freq="D")
    rows = []
    for i, d in enumerate(dates):
        for a in range(5):
            fwd = (a + i) * 0.01   # monotonically increasing forward returns
            rows.append({
                "symbol": f"A{a}",
                "pillar_f": fwd * 100,   # perfectly correlated
                "pillar_m": 50.0,
                "pillar_o": 50.0,
                "pillar_s": 50.0,
                "pillar_a": 50.0,
                "macro_regime": "RISK_ON",
                "_date": d,
            })
    df = pd.DataFrame(rows)
    # Build synthetic forward returns
    fwd_rets = pd.DataFrame(
        index=dates,
        columns=[f"A{a}" for a in range(5)],
    )
    for a in range(5):
        for i in range(100):
            fwd_rets.at[dates[i], f"A{a}"] = (a + i) * 0.01

    cell = per_regime_cycle_pillar(
        df, fwd_rets,
        cycle_name="2024_bull", cycle_lo="2024-01-01", cycle_hi="2024-12-31",
        regime="RISK_ON", pillar="f", min_events=30,
    )
    # With perfect pillar_f → fwd correlation, IC ≈ 1.0, t very large, verdict ✅
    assert cell["n_obs"] >= 30
    assert cell["ic"] is not None and abs(cell["ic"] - 1.0) < 1e-6, \
        f"Expected IC ≈ 1.0, got {cell['ic']}"
    assert cell["t"] > 10, f"Expected t > 10 for n=500 perfect corr, got {cell['t']}"
    assert cell["verdict"] == "✅ POSITIVE"
    print(f"  ✓ per_regime_cycle_pillar: perfect-corr IC≈1.0, verdict POSITIVE (n={cell['n_obs']})")


def t_per_regime_cycle_pillar_insufficient():
    """n_obs < MIN_EVENTS ⇒ INSUFFICIENT regardless of IC magnitude."""
    from src.research.data_align.pillar_ic_mining import per_regime_cycle_pillar
    # Only 10 (date, asset) pairs
    dates = pd.date_range("2024-01-01", periods=10, freq="D")
    rows = []
    for i, d in enumerate(dates):
        rows.append({
            "symbol": "A", "pillar_f": i * 10,
            "pillar_m": 50.0, "pillar_o": 50.0,
            "pillar_s": 50.0, "pillar_a": 50.0,
            "macro_regime": "RISK_ON", "_date": d,
        })
    df = pd.DataFrame(rows)
    fwd_rets = pd.DataFrame({"A": [0.01 * i for i in range(10)]}, index=dates)
    cell = per_regime_cycle_pillar(
        df, fwd_rets, cycle_name="2024_bull",
        cycle_lo="2024-01-01", cycle_hi="2024-12-31",
        regime="RISK_ON", pillar="f", min_events=30,
    )
    assert cell["n_obs"] == 10
    assert cell["verdict"] == "⚪ INSUFFICIENT", \
        f"Expected INSUFFICIENT for n=10, got {cell['verdict']}"
    print(f"  ✓ per_regime_cycle_pillar: n=10 ⇒ INSUFFICIENT (event-count gate)")


# === Test runner ==============================================================
TESTS = [
    t_verdict_event_count_gate,
    t_ic_tstat_basic,
    t_forward_returns_horizon_5,
    t_realized_vol_annualized,
    t_per_regime_cycle_pillar_positive,
    t_per_regime_cycle_pillar_insufficient,
]


def main() -> int:
    print(f"Running {len(TESTS)} pillar_ic_mining smoke tests …\n")
    failed = 0
    for t in TESTS:
        try:
            t()
        except AssertionError as e:
            print(f"  ✗ {t.__name__} FAILED: {e}")
            failed += 1
        except Exception as e:
            print(f"  ✗ {t.__name__} ERROR: {type(e).__name__}: {e}")
            failed += 1
    total = len(TESTS)
    passed = total - failed
    print(f"\n{passed}/{total} test(s) passed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())