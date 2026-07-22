"""Smoke tests for funding_crowding_ls.py (R60 module).

Verifies:
  1. Module imports cleanly + all public symbols present
  2. score_funding_zwide shapes + sane coverage
  3. score_funding_zwide sign convention (fade_crowd → high score = LOW funding)
  4. funding_ls shapes + cost monotonicity (gross ≥ 5bps ≥ 10bps)
  5. funding_cadence_sweep returns dict keyed by (cad, bps)
  6. funding_ls is a "fade the crowd" signal: synthetic data where high funding
     ⇒ low next-day return → L/S gross PnL > 0 (long low-funding wins)
  7. R46 cell parity: gauntlet_3check returns expected fields
  8. score_funding_zwide ride_crowd sign inverts the ranking
  9. funding_ls handles empty / underpopulated inputs gracefully

Pure Python + numpy + pandas; no scipy / nautilus / freqtrade. Sandbox-safe.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

import numpy as np
import pandas as pd

from src.research.validation.funding_crowding_ls import (
    score_funding_zwide, funding_ls, funding_cadence_sweep,
    R46_REBAL_DAYS, R46_COST_BPS, R46_K, DEFAULT_ZWIN,
    SIGN_FADE_CROWD, SIGN_RIDE_CROWD,
)
from src.research.validation.w5_forensics import gauntlet_3check


def _synthetic_funding(n_assets=28, n_days=200, seed=42):
    """Synthetic daily funding panel [date × asset]."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2024-01-01", periods=n_days, freq="D")
    assets = [f"A{i:02d}" for i in range(n_assets)]
    return pd.DataFrame(
        rng.normal(0, 0.0005, (n_days, n_assets)),
        index=dates, columns=assets,
    )


def _synthetic_rets(n_assets=28, n_days=200, seed=0, funding=None, zwin=30):
    """Synthetic returns with embedded negative funding → next-day-return relation.

    If `funding` (wide) is provided, the next-day return is biased by -funding_z
    (the R60 hypothesis: high funding ⇒ low next-day return ⇒ short the high-funding,
    long the low-funding L/S should be profitable).
    """
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2024-01-01", periods=n_days, freq="D")
    assets = [f"A{i:02d}" for i in range(n_assets)]
    base = rng.normal(0, 0.02, (n_days, n_assets))
    if funding is not None:
        # z-score per asset
        mu = funding.rolling(zwin, min_periods=max(5, zwin // 3)).mean()
        sd = funding.rolling(zwin, min_periods=max(5, zwin // 3)).std()
        z = ((funding - mu) / (sd + 1e-12)).shift(1)  # lag to avoid look-ahead
        # Negative funding → higher next-day return (crowded shorts get squeezed)
        return pd.DataFrame(base + (-z.fillna(0.0).values * 0.5),
                            index=dates, columns=assets)
    return pd.DataFrame(base, index=dates, columns=assets)


def test_imports():
    from src.research.validation import funding_crowding_ls as m
    for sym in ("score_funding_zwide", "funding_ls", "funding_cadence_sweep",
                "R46_REBAL_DAYS", "R46_COST_BPS", "R46_K", "DEFAULT_ZWIN",
                "SIGN_FADE_CROWD", "SIGN_RIDE_CROWD"):
        assert hasattr(m, sym), f"missing symbol: {sym}"
    assert R46_REBAL_DAYS == 5
    assert R46_COST_BPS == 5.0
    assert R46_K == 3
    assert DEFAULT_ZWIN == 30
    assert SIGN_FADE_CROWD == "fade_crowd"
    assert SIGN_RIDE_CROWD == "ride_crowd"
    print(f"✓ imports OK (R46 cell = {R46_REBAL_DAYS}d/{R46_COST_BPS}bps k={R46_K}, "
          f"zwin={DEFAULT_ZWIN}d, sign={SIGN_FADE_CROWD})")


def test_score_funding_zwide_shapes():
    fd = _synthetic_funding(n_assets=28, n_days=200)
    score = score_funding_zwide(fd, zwin=30)
    assert score.shape == fd.shape, f"shape mismatch: {score.shape} vs {fd.shape}"
    # After warmup (zwin=30), coverage should be high
    valid = score.notna().sum().sum() / score.size
    assert valid > 0.85, f"coverage too low: {valid:.0%}"
    # Per-asset z-score mean should be ≈0 std ≈1 after warmup
    means = score.iloc[30:].mean()
    stds = score.iloc[30:].std()
    assert all(abs(means) < 0.3), f"per-asset mean drift: {means.abs().max():.2f}"
    assert all((stds - 1.0).abs() < 0.4), f"per-asset std drift: {(stds-1).abs().max():.2f}"
    print(f"✓ score_funding_zwide shapes OK ({score.shape}, post-warmup coverage={valid:.0%}, "
          f"μ_range=[{means.min():+.2f},{means.max():+.2f}], σ_range=[{stds.min():.2f},{stds.max():.2f}])")


def test_score_funding_zwide_sign_fade_crowd():
    """CRITICAL: at higher funding, score should be LOWER (so top tercile = low funding = LONG)."""
    fd = _synthetic_funding(n_assets=10, n_days=200, seed=42)
    score_fade = score_funding_zwide(fd, zwin=30, sign="fade_crowd")
    # Synthesize a day with funding range from -3σ to +3σ per asset
    # Check: at a date, the asset with HIGHEST funding should have LOWEST score (fade_crowd)
    score_ride = score_funding_zwide(fd, zwin=30, sign="ride_crowd")
    # Pick a post-warmup date
    test_date = fd.index[100]
    funds = fd.loc[test_date]
    s_fade = score_fade.loc[test_date]
    s_ride = score_ride.loc[test_date]
    # Drop NaNs
    valid = funds.notna() & s_fade.notna()
    f = funds[valid]
    sf = s_fade[valid]
    sr = s_ride[valid]
    # Rank corr: fade should be negative, ride should be positive
    rho_fade = pd.Series(f.values).rank().corr(pd.Series(sf.values).rank())
    rho_ride = pd.Series(f.values).rank().corr(pd.Series(sr.values).rank())
    assert rho_fade < -0.5, f"fade_crowd should produce negative funding→score corr, got {rho_fade:.2f}"
    assert rho_ride > 0.5, f"ride_crowd should produce positive funding→score corr, got {rho_ride:.2f}"
    print(f"✓ sign convention correct "
          f"(corr[funding→score]: fade={rho_fade:.2f}, ride={rho_ride:+.2f})")


def test_funding_ls_shapes_and_cost():
    fd = _synthetic_funding(n_assets=28, n_days=200)
    rets = _synthetic_rets(n_assets=28, n_days=200, funding=fd)
    score = score_funding_zwide(fd, zwin=30)
    fac_gross = funding_ls(score, rets, k_terciles=3, cost_bps=0.0, rebal_days=1)
    fac_5 = funding_ls(score, rets, k_terciles=3, cost_bps=5.0, rebal_days=1)
    fac_10 = funding_ls(score, rets, k_terciles=3, cost_bps=10.0, rebal_days=1)
    assert len(fac_gross) == len(rets)
    # Cost monotonicity: gross PnL ≥ 5bps PnL ≥ 10bps PnL
    pnl_gross = float(fac_gross.sum())
    pnl_5 = float(fac_5.sum())
    pnl_10 = float(fac_10.sum())
    assert pnl_gross >= pnl_5 >= pnl_10 - 1e-9, (
        f"cost monotonicity broken: gross={pnl_gross:.4f}, 5bps={pnl_5:.4f}, 10bps={pnl_10:.4f}"
    )
    print(f"✓ funding_ls shapes OK + cost monotonic "
          f"(gross={pnl_gross:+.4f} ≥ 5bps={pnl_5:+.4f} ≥ 10bps={pnl_10:+.4f})")


def test_funding_ls_positive_pnl_fade_crowd():
    """Synthetic where high funding → low return → long-low/short-high L/S should profit."""
    fd = _synthetic_funding(n_assets=28, n_days=300, seed=7)
    rets = _synthetic_rets(n_assets=28, n_days=300, seed=1, funding=fd, zwin=30)
    score = score_funding_zwide(fd, zwin=30, sign="fade_crowd")
    fac = funding_ls(score, rets, k_terciles=3, cost_bps=5.0, rebal_days=5)
    # Drop warmup
    pnl = float(fac.iloc[60:].sum())
    assert pnl > 0, f"L/S gross should profit when high funding → low return, got {pnl:.4f}"
    print(f"✓ fade_crowd L/S is profitable on synthetic fade-funding data "
          f"(post-warmup PnL={pnl:+.4f})")


def test_funding_cadence_sweep_keys():
    fd = _synthetic_funding(n_assets=28, n_days=200)
    rets = _synthetic_rets(n_assets=28, n_days=200, funding=fd)
    score = score_funding_zwide(fd, zwin=30)
    f_market = rets.mean(axis=1).fillna(0.0)
    cum = (1 + f_market).cumprod()
    trail30 = cum / cum.shift(30) - 1
    f_momentum = (np.sign(trail30.shift(1)).fillna(0.0) * f_market)
    known = {"market": f_market.values, "momentum": f_momentum.values}
    sweep = funding_cadence_sweep(score, rets, known,
                                  cadences=(1, 3, 5, 7, 14, 21),
                                  cost_grid=(0.0, 5.0, 10.0),
                                  k_terciles=3)
    assert len(sweep) == 6 * 3, f"expected 18 cells, got {len(sweep)}"
    for key in [(1, 0.0), (5, 5.0), (21, 10.0)]:
        assert key in sweep, f"missing cell: {key}"
        r = sweep[key]
        assert {"alpha_t", "alpha_ann_pct", "turnover_ann", "cadence", "cost_bps"}.issubset(set(r.keys()))
    # R46 cell (5d, 5bps) should be in the sweep
    r46 = sweep[(5, 5.0)]
    assert r46["cadence"] == 5 and r46["cost_bps"] == 5.0
    print(f"✓ funding_cadence_sweep keys OK (18 cells, R46 5d/5bps α_t={r46['alpha_t']:+.2f}, "
          f"turnover≈{r46['turnover_ann']:.1f})")


def test_gauntlet_3check_r46_parity():
    """gauntlet_3check should run end-to-end on a synthetic R60 factor."""
    fd = _synthetic_funding(n_assets=28, n_days=400, seed=7)
    rets = _synthetic_rets(n_assets=28, n_days=400, seed=1, funding=fd, zwin=30)
    score = score_funding_zwide(fd, zwin=30)
    fac = funding_ls(score, rets, k_terciles=3, cost_bps=5.0, rebal_days=5)
    fac = fac.reindex(rets.index).fillna(0.0)
    f_market = rets.mean(axis=1).fillna(0.0)
    cum = (1 + f_market).cumprod()
    trail30 = cum / cum.shift(30) - 1
    f_momentum = (np.sign(trail30.shift(1)).fillna(0.0) * f_market)
    known = {"market": f_market.values, "momentum": f_momentum.values}
    g = gauntlet_3check(fac.values, known, int(0.7 * len(rets)))
    assert {"gross_t", "oos_t", "passes_gross", "passes_oos", "passes_all"}.issubset(set(g.keys()))
    assert isinstance(g["passes_all"], bool)
    # On synthetic positive-IC data, gross_t should be positive
    assert g["gross_t"] > 0, f"synthetic positive-IC should give gross_t > 0, got {g['gross_t']:.2f}"
    print(f"✓ gauntlet_3check R60 parity OK "
          f"(gross_t={g['gross_t']:+.2f}, OOS_t={g['oos_t']:+.2f}, passes_all={g['passes_all']})")


def test_score_ride_crowd_inverts_ranking():
    """ride_crowd should produce opposite sign on synthetic data with embedded relation."""
    fd = _synthetic_funding(n_assets=28, n_days=300, seed=7)
    rets = _synthetic_rets(n_assets=28, n_days=300, seed=1, funding=fd, zwin=30)
    score_fade = score_funding_zwide(fd, zwin=30, sign="fade_crowd")
    score_ride = score_funding_zwide(fd, zwin=30, sign="ride_crowd")
    fac_fade = funding_ls(score_fade, rets, k_terciles=3, cost_bps=5.0, rebal_days=5)
    fac_ride = funding_ls(score_ride, rets, k_terciles=3, cost_bps=5.0, rebal_days=5)
    pnl_fade = float(fac_fade.iloc[60:].sum())
    pnl_ride = float(fac_ride.iloc[60:].sum())
    # On data where high funding → low return, fade_crowd (LONG low funding) profits;
    # ride_crowd (LONG high funding) loses.
    assert pnl_fade > pnl_ride, (
        f"ride_crowd should underperform fade_crowd on this synthetic data "
        f"(fade={pnl_fade:+.4f}, ride={pnl_ride:+.4f})"
    )
    print(f"✓ ride_crowd underperforms fade_crowd on synthetic fade-funding data "
          f"(fade={pnl_fade:+.4f}, ride={pnl_ride:+.4f})")


def test_funding_ls_handles_tiny_inputs():
    """funding_ls should not crash on degenerate inputs."""
    # Empty score
    fd_empty = pd.DataFrame()
    rets = _synthetic_rets(n_assets=28, n_days=200)
    score_empty = score_funding_zwide(fd_empty)
    fac = funding_ls(score_empty, rets)
    assert len(fac) == len(rets)
    assert (fac == 0.0).all()
    # Score with < 6 valid assets → returns zeros (R45/R46 contract)
    fd_tiny = pd.DataFrame(
        np.random.default_rng(0).normal(0, 0.0005, (100, 3)),
        index=pd.date_range("2024-01-01", periods=100, freq="D"),
        columns=["X", "Y", "Z"],
    )
    rets_tiny = pd.DataFrame(
        np.random.default_rng(1).normal(0, 0.02, (100, 5)),
        index=pd.date_range("2024-01-01", periods=100, freq="D"),
        columns=["A", "B", "C", "D", "E"],
    )
    score_tiny = score_funding_zwide(fd_tiny, zwin=30)
    fac_tiny = funding_ls(score_tiny, rets_tiny)
    assert (fac_tiny == 0.0).all(), "tiny universe should return zero series"
    print(f"✓ degenerate-input handling OK (empty → zeros, <6 valid → zeros)")


def main():
    tests = [
        test_imports,
        test_score_funding_zwide_shapes,
        test_score_funding_zwide_sign_fade_crowd,
        test_funding_ls_shapes_and_cost,
        test_funding_ls_positive_pnl_fade_crowd,
        test_funding_cadence_sweep_keys,
        test_gauntlet_3check_r46_parity,
        test_score_ride_crowd_inverts_ranking,
        test_funding_ls_handles_tiny_inputs,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as exc:
            print(f"✗ {t.__name__}: {exc!r}")
            failed += 1
    if failed:
        print(f"\n{failed} test(s) FAILED, {passed} passed")
        return 1
    print(f"\n{passed} test(s) passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
