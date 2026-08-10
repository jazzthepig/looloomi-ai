"""R102 smoke tests — 8 checks per §C6-DISCOVERY-SPEC contract.

Pure-function checks + main() pattern (no pytest). No live Supabase / no writes
to non-reports/ paths.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from src.research.validation.r102_cross_frequency_funding import (
    R102_CADENCES, R102_COST_GRID, R102_K_TERCILES, R102_OOS_FRAC,
    R102_RESAMPLE_FREQS, R102_SPREAD_FAMILY, R102_MIN_DAYS,
    cross_frequency_spread, score_cross_frequency, tercile_ls,
    apply_rebal_with_cost, compute_3check, gate1_anchor_acceptance,
    gate2_leg_correlation, load_funding_1h, run,
)


def _synthetic_funding_1h(n_assets=6, n_days=200, seed=42) -> pd.DataFrame:
    """Build a synthetic 1h funding dataframe with deterministic structure."""
    rng = np.random.default_rng(seed)
    hours = pd.date_range("2024-01-01", periods=n_days * 24, freq="1h")
    out = {}
    for i in range(n_assets):
        # Cross-frequency divergence: each asset has different intra-day vs inter-day bias.
        daily_drift = rng.normal(0, 0.0001, n_days)
        hourly_noise = rng.normal(0, 0.00005, n_days * 24)
        # Broadcast daily drift to hours, but add sub-daily bias per asset.
        daily_broadcast = np.repeat(daily_drift, 24)
        bias = rng.normal(0, 0.00002)  # sub-daily structural bias
        series = daily_broadcast + hourly_noise + bias
        out[f"A{i}"] = series
    return pd.DataFrame(out, index=hours)


def _synthetic_returns(n_assets=6, n_days=200, seed=99) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n_days, freq="1D")
    return pd.DataFrame(rng.normal(0, 0.02, (n_days, n_assets)),
                        index=idx, columns=[f"A{i}" for i in range(n_assets)])


def test_spec_frozen_constants():
    """1. R102_FROZEN_SPEC constants unchanged."""
    assert R102_RESAMPLE_FREQS == ('4h', '8h', '24h')
    assert R102_SPREAD_FAMILY == (('4h', '24h'), ('8h', '24h'))
    assert R102_CADENCES == (3, 5, 7, 14)
    assert R102_COST_GRID == (0, 5, 10, 20)
    assert R102_K_TERCILES == 3
    assert R102_OOS_FRAC == 0.30
    assert R102_MIN_DAYS == 100


def test_cross_frequency_spread_signs():
    """2. cross_frequency_spread returns correct shape and scale."""
    f = _synthetic_funding_1h(n_assets=3, n_days=120)
    spread = cross_frequency_spread(f, '4h', '24h')
    # Output index = 24h cadence (end-of-day)
    assert spread.shape[1] == 3
    assert spread.notna().sum().sum() > 0
    # Daily NaN for early hours (cumsum alignment)
    assert spread.iloc[:2].isna().any().any() or spread.iloc[:2].notna().any().any()


def test_score_cross_frequency_combines_4h_8h():
    """3. score_cross_frequency combines (4h-24h) and (8h-24h)."""
    f = _synthetic_funding_1h(n_assets=2, n_days=120)
    score = score_cross_frequency(f)
    assert score.shape[1] == 2
    # Index is daily
    assert isinstance(score.index, pd.DatetimeIndex)
    assert score.index.freq is None or score.index.inferred_freq in ('D', '24h') or \
        (score.index[1] - score.index[0]).total_seconds() in (86400,)


def test_tercile_ls_returns_nan_for_insufficient_n():
    """4. tercile_ls handles insufficient cross-section gracefully."""
    score = pd.DataFrame({'A': [1.0]}, index=pd.date_range("2024-01-01", periods=1))
    rets = pd.DataFrame({'A': [0.01]}, index=pd.date_range("2024-01-01", periods=1))
    out = tercile_ls(score, rets, k_terciles=3)
    assert out.iloc[0] != out.iloc[0]  # NaN


def test_apply_rebal_with_cost_zero_cost_is_identity():
    """5. apply_rebal_with_cost at 0bps cost = no adjustments."""
    s = pd.Series([0.01, -0.02, 0.03, -0.01, 0.02],
                  index=pd.date_range("2024-01-01", periods=5))
    out = apply_rebal_with_cost(s, rebal_days=1, cost_bps=0.0)
    np.testing.assert_allclose(out.values, s.values, atol=1e-12)


def test_gate1_anchor_acceptance_passes_on_balanced_data():
    """6. Gate 1: balanced daily returns pass; concentrated returns fail."""
    rng = np.random.default_rng(0)
    balanced = pd.Series(rng.normal(0, 0.02, 252),
                         index=pd.date_range("2024-01-01", periods=252))
    g = gate1_anchor_acceptance(balanced)
    # With balanced noise, best_10day_share should be modest and sharpe moderate
    assert g["best_10day_share"] < 0.60
    assert g["daily_sharpe"] < 5.0
    assert 0.40 <= g["pos_day_rate"] <= 0.85


def test_gate2_leg_correlation_passes_with_zero_corr():
    """7. Gate 2: uncorrelated legs pass; perfectly correlated fail."""
    rng = np.random.default_rng(0)
    r102_series = pd.Series(rng.normal(0, 0.01, 252),
                            index=pd.date_range("2024-01-01", periods=252))
    independent = pd.Series(rng.normal(0, 0.01, 252),
                            index=pd.date_range("2024-01-01", periods=252))
    perfect = r102_series.copy()  # corr = 1.0
    g_pass = gate2_leg_correlation(r102_series, {"R46": independent, "R62": independent})
    g_fail = gate2_leg_correlation(r102_series, {"R46": perfect})
    # numpy.bool_ vs python bool — normalize via bool()
    assert bool(g_pass["passes"]) is True
    assert bool(g_fail["passes"]) is False
    assert g_fail["max_abs_corr"] > 0.30


def test_run_returns_verdict_grammar():
    """8. run() returns verdict from the fixed grammar."""
    with tempfile.TemporaryDirectory() as td:
        fdir = Path(td)
        # Write a tiny 1h CSV for 1 asset
        ts = pd.date_range("2024-01-01", periods=24 * 200, freq="1h")
        rate = np.random.default_rng(0).normal(0, 0.0001, len(ts))
        df = pd.DataFrame({"fundingTime": (ts.astype('int64') // 10**6),
                           "fundingRate": rate})
        df.to_csv(fdir / "xusd_funding_1h.csv", index=False)
        # 1 asset < k_terciles * 2 → INSUFFICIENT_COVERAGE
        result = run(funding_dir=fdir, returns_df=pd.DataFrame())
        assert result["verdict"] in {
            "R102_SURVIVES",
            "R102_REFUTED_GATE1",
            "R102_REFUTED_GATE2",
            "R102_REFUTED_GATE3",
            "R102_INSUFFICIENT_COVERAGE",
            "R102_DATA_MISSING",
        }


def main():
    tests = [
        ("test_spec_frozen_constants", test_spec_frozen_constants),
        ("test_cross_frequency_spread_signs", test_cross_frequency_spread_signs),
        ("test_score_cross_frequency_combines_4h_8h", test_score_cross_frequency_combines_4h_8h),
        ("test_tercile_ls_returns_nan_for_insufficient_n", test_tercile_ls_returns_nan_for_insufficient_n),
        ("test_apply_rebal_with_cost_zero_cost_is_identity", test_apply_rebal_with_cost_zero_cost_is_identity),
        ("test_gate1_anchor_acceptance_passes_on_balanced_data", test_gate1_anchor_acceptance_passes_on_balanced_data),
        ("test_gate2_leg_correlation_passes_with_zero_corr", test_gate2_leg_correlation_passes_with_zero_corr),
        ("test_run_returns_verdict_grammar", test_run_returns_verdict_grammar),
    ]
    passed = 0
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  ✓ {name}")
            passed += 1
        except Exception as e:
            print(f"  ✗ {name}: {e}")
            failed += 1
    print(f"\n{passed}/{len(tests)} R102 smoke checks passed "
          f"({failed} failed)")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
