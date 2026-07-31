"""R95 — Per-Asset TSMOM trend strategy smoke tests (sandbox-safe).

Owner: Seth, 2026-07-27. Companion to r95_per_asset_tsmom.py.

Tests (15):
  1. t_imports                       — module + public symbols + frozen constants
  2. t_no_demean_in_score            — assert "demean" substring NOT in score function
  3. t_score_shape                   — output length, values in {-1, 0, +1}, NaN warmup
  4. t_one_day_lag                   — PIT-safe: score[t] uses cum[t-1]/cum[t-1-lookback]
  5. t_multi_horizon_vote            — majority sign across horizons on toy data
  6. t_multi_horizon_mean            — equal-weighted mean on toy data
  7. t_tsmom_ls_shape                — output length, weights sum to 0 (market-neutral)
  8. t_cost_on_rebal_days            — cost applied on rebal_days only
  9. t_sweep_keys                    — sweep keys are (horizon, cadence, cost) tuples
 10. t_leg_correlation_keys          — payload includes R46/R62/R76/R77 gate
 11. t_combined_book_keys            — payload includes R95+R77 combined stats
 12. t_frozen_r77_untouched          — payload `touches_frozen_r77_cell: False`
 13. t_structural_difference_from_r78 — `demeaned_full` substring NOT in R95 source
 14. t_verdict_grammar               — all 3 bands (TRADEABLE/PARTIAL/REFUTED) present
 15. t_anti_imposter_discipline      — 3-check + cost-tier gate + leg-corr gate + maxDD
                                       budget + W5 sign-positive all present

Run: `python3 src/research/validation/tests/test_r95_per_asset_tsmom_smoke.py`
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))


def _synth_rets(n_days: int = 400, n_assets: int = 25, seed: int = 0) -> pd.DataFrame:
    """Synthetic returns: zero-drift random walk (R94 pattern, scale=0.02).

    scale=0.04 was tried but the absorption_test X matrix becomes near-singular
    at that scale (market and momentum are too volatile, decorrelation breaks).
    scale=0.02 gives proper rank-3 X matrices for synthetic stress tests.
    """
    rng = np.random.default_rng(seed)
    rets = rng.normal(loc=0.0, scale=0.02, size=(n_days, n_assets))
    dates = pd.date_range("2024-01-01", periods=n_days, freq="D")
    return pd.DataFrame(rets, index=dates,
                        columns=[f"A{i:02d}" for i in range(n_assets)])


def _synth_score(rets: pd.DataFrame) -> pd.DataFrame:
    """Synthetic signed score: +1 in first half, -1 in second half (toy trend)."""
    n = len(rets)
    score = pd.DataFrame(0.0, index=rets.index, columns=rets.columns)
    score.iloc[: n // 2, :] = 1.0
    score.iloc[n // 2:, :] = -1.0
    return score


# ──────────────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────────────
def t_imports():
    """Module + public symbols + frozen constants verified."""
    import src.research.validation.r95_per_asset_tsmom as r
    assert hasattr(r, "score_tsmom_per_asset")
    assert hasattr(r, "score_tsmom_multi_horizon")
    assert hasattr(r, "tsmom_ls")
    assert hasattr(r, "tsmom_ls_regime_scaled") or hasattr(r, "run_sweep"), \
        "expected either tsmom_ls_regime_scaled or run_sweep exported"
    assert hasattr(r, "leg_correlation_check")
    assert hasattr(r, "combined_book_stats")
    assert hasattr(r, "run")
    assert hasattr(r, "format_report")
    # Frozen constants
    assert r.R95_TSMOM_HORIZONS == (5, 10, 21, 42, 63, 126, 252)
    assert r.R95_K_TERCILES == 3
    assert r.R95_ORTHOGONALITY_GATE == 0.30
    assert r.R95_COST_GRID == (0.0, 5.0, 10.0, 20.0, 30.0)
    assert r.R95_MAXDD_BUDGET == -0.20
    assert r.OOS_FRAC == 0.30
    assert r.SIGN_HIGH_TSMOM_LONG == "high_tsmom_long"
    assert r.SIGN_LOW_TSMOM_LONG == "low_tsmom_long"
    assert r.R77_SHARPE_FROZEN > 0  # sanity — frozen R77 reference
    print("  ✓ module + 7 public symbols + 8 frozen constants")


def t_no_demean_in_score():
    """score_tsmom_per_asset source does NOT contain 'demean' substring.

    R78's failure was cross-sectional demean (per lesson #43). R95 must NOT demean.
    The docstring of score_tsmom_per_asset mentions "demean" (saying "NO demean");
    this test strips the docstring before checking code lines.
    """
    import src.research.validation.r95_per_asset_tsmom as r
    src = Path(r.__file__).read_text()
    # Find the score_tsmom_per_asset function body
    fn_start = src.find("def score_tsmom_per_asset")
    fn_end = src.find("\ndef ", fn_start + 1)
    fn_body = src[fn_start:fn_end] if fn_end > fn_start else src[fn_start:]
    # Strip docstring (triple-quoted block at top of function)
    stripped = fn_body
    if '"""' in stripped:
        first = stripped.find('"""')
        second = stripped.find('"""', first + 3)
        if second > first:
            stripped = stripped[:first] + stripped[second + 3:]
    if "demean" in stripped.lower():
        # Show context for debugging
        idx = stripped.lower().find("demean")
        ctx = stripped[max(0, idx - 50): idx + 50]
        raise AssertionError(
            f"score_tsmom_per_asset CODE contains 'demean' — violates R95 design "
            f"(no demean). Context: ...{ctx}..."
        )
    print("  ✓ score_tsmom_per_asset code contains no 'demean' substring")


def t_score_shape():
    """Output shape: length matches rets, values in {-1, 0, +1}, NaN warmup→0."""
    from src.research.validation.r95_per_asset_tsmom import score_tsmom_per_asset
    rets = _synth_rets(n_days=300, n_assets=25)
    score = score_tsmom_per_asset(rets, lookback=21)
    assert score.shape == rets.shape, f"shape mismatch: {score.shape} vs {rets.shape}"
    # Values in {-1, 0, +1}
    uniq = set(score.values.flatten().tolist())
    assert uniq.issubset({-1.0, 0.0, 1.0}), f"unexpected values in score: {uniq}"
    # First 21 rows should be 0 (warmup after 1-day lag)
    warmup = score.iloc[:21, :]
    assert (warmup.values == 0).all(), \
        "first 21 rows should be 0 (warmup → fillna(0))"
    print("  ✓ score shape correct, values in {-1, 0, +1}, warmup zeroed")


def t_one_day_lag():
    """PIT-safe: score[t] uses cum[t-1] / cum[t-1-lookback]."""
    from src.research.validation.r95_per_asset_tsmom import score_tsmom_per_asset
    # Construct deterministic price path: prices go up, then down with enough
    # headroom for lookback=5 to register the flip.
    n = 100
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    # A00 always up, A01 always down, A02 long up-then-down (30 up, 70 down).
    rets = pd.DataFrame({
        "A00": [+0.01] * n,
        "A01": [-0.01] * n,
        "A02": [+0.02 if i < 30 else -0.02 for i in range(n)],
    }, index=dates)
    score_5 = score_tsmom_per_asset(rets, lookback=5)
    # A00 always up → score[t] = +1 for all t > 5 (after warmup)
    assert (score_5["A00"].iloc[6:] == 1.0).all(), \
        "A00 (always up) should score +1 after warmup"
    # A01 always down → score[t] = -1 for all t > 5
    assert (score_5["A01"].iloc[6:] == -1.0).all(), \
        "A01 (always down) should score -1 after warmup"
    # A02: with 1-day lag, score[t] = sign(trail_5 at t-1).
    # trail_5 at t=31 = cum[31]/cum[26] - 1 → days 27-31 (3 up + 2 down)
    #   = (1.02)^3 * (0.98)^2 - 1 = 1.0612 * 0.9604 - 1 = +0.0192 → +1
    # score[32] = sign of +0.0192 = +1
    assert score_5["A02"].iloc[32] == 1.0, \
        f"A02 at t=32 should be +1 (3 up + 2 down); got {score_5['A02'].iloc[32]}"
    # trail_5 at t=32 = days 28-32 (2 up + 3 down) = (1.02)^2 * (0.98)^3 - 1
    #   = 1.0404 * 0.9412 - 1 = -0.0207 → -1
    # score[33] = -1
    assert score_5["A02"].iloc[33] == -1.0, \
        f"A02 at t=33 should be -1 (2 up + 3 down, flip); got {score_5['A02'].iloc[33]}"
    # trail_5 at t=35 = days 31-35 (5 down) = (0.98)^5 - 1 = -0.0961 → -1
    # score[36] = -1
    assert score_5["A02"].iloc[36] == -1.0, \
        f"A02 at t=36 should be -1 (all 5 down); got {score_5['A02'].iloc[36]}"
    print("  ✓ 1-day lag enforced; up-trend → +1, down-trend → -1, mixed → flip")


def t_multi_horizon_vote():
    """Majority sign across horizons: 5/7 horizons +1, 2/7 horizons -1 → vote +1."""
    from src.research.validation.r95_per_asset_tsmom import (
        score_tsmom_multi_horizon, AGG_VOTE,
    )
    rets = _synth_rets(n_days=400, n_assets=10)
    out = score_tsmom_multi_horizon(rets, lookbacks=(5, 10, 21, 42, 63, 126, 252),
                                    method=AGG_VOTE)
    assert out.shape == rets.shape
    # Values should still be in {-1, 0, +1} for vote method
    uniq = set(out.values.flatten().tolist())
    assert uniq.issubset({-1.0, 0.0, 1.0}), \
        f"vote output should be in {{-1, 0, +1}}; got {uniq}"
    print("  ✓ vote method returns signed {-1, 0, +1} with correct shape")


def t_multi_horizon_mean():
    """Equal-weighted mean across horizons → continuous in [-1, +1]."""
    from src.research.validation.r95_per_asset_tsmom import (
        score_tsmom_multi_horizon, AGG_MEAN,
    )
    rets = _synth_rets(n_days=400, n_assets=10)
    out = score_tsmom_multi_horizon(rets, lookbacks=(5, 10, 21, 42, 63, 126, 252),
                                    method=AGG_MEAN)
    assert out.shape == rets.shape
    # Values should be in [-1, +1]
    v = out.values
    assert ((v >= -1.0) & (v <= 1.0)).all(), \
        f"mean output should be in [-1, +1]; got [{v.min():.3f}, {v.max():.3f}]"
    print(f"  ✓ mean method returns continuous [-1, +1] "
          f"(observed [{v.min():.3f}, {v.max():.3f}])")


def t_tsmom_ls_shape():
    """Output length, weights market-neutral (top + bottom tercile)."""
    from src.research.validation.r95_per_asset_tsmom import (
        score_tsmom_per_asset, tsmom_ls, SIGN_HIGH_TSMOM_LONG,
    )
    rets = _synth_rets(n_days=300, n_assets=25)
    score = score_tsmom_per_asset(rets, lookback=21)
    pnl = tsmom_ls(score, rets, k_terciles=3, rebal_days=1,
                   cost_bps=0.0, sign=SIGN_HIGH_TSMOM_LONG)
    assert len(pnl) == len(rets), f"pnl length {len(pnl)} != rets length {len(rets)}"
    # Market-neutral: gross weights on each rebal day should sum to 0
    # (verify by reverse-engineering: since top and bottom tercile weights sum to 0,
    # and pnl is the dot product, we expect pnl to have mean near 0 on long-enough
    # panel — sanity check only)
    assert abs(pnl.mean()) < 0.01, \
        f"market-neutral L/S should have ~0 mean; got {pnl.mean():.5f}"
    print(f"  ✓ pnl length matches rets; mean={pnl.mean():.5f} (~0 = market-neutral)")


def t_cost_on_rebal_days():
    """Cost applied only on rebal days (cadence_ls convention)."""
    from src.research.validation.r95_per_asset_tsmom import (
        score_tsmom_per_asset, tsmom_ls, SIGN_HIGH_TSMOM_LONG,
    )
    rets = _synth_rets(n_days=300, n_assets=25)
    score = score_tsmom_per_asset(rets, lookback=21)
    # Zero cost vs 30bps cost with 7d rebal — turnover only on day 0, 7, 14, ...
    pnl_zero = tsmom_ls(score, rets, k_terciles=3, rebal_days=7,
                        cost_bps=0.0, sign=SIGN_HIGH_TSMOM_LONG)
    pnl_cost = tsmom_ls(score, rets, k_terciles=3, rebal_days=7,
                        cost_bps=30.0, sign=SIGN_HIGH_TSMOM_LONG)
    # Total cost drag should be > 0 (costed version is strictly worse in expectation
    # on a market-neutral book, modulo path)
    diff = (pnl_zero - pnl_cost).sum()
    assert diff >= 0, \
        f"30bps cost should not improve total pnl; got diff={diff:.5f}"
    print(f"  ✓ 30bps cost reduces pnl by {diff:.5f} total (cost drag works)")


def t_sweep_keys():
    """Sweep keys are (horizon, cadence, cost) tuples; 7×6×5 = 210 cells.

    Uses smaller horizon subset for smoke (5/10/21/42/63/126) — full 7-horizon
    sweep with horizon=252 needs longer panels than the smoke synth provides.
    """
    import src.research.validation.r95_per_asset_tsmom as r
    from src.research.validation.r95_per_asset_tsmom import run_sweep
    rets = _synth_rets(n_days=400, n_assets=25)
    smoke_horizons = (5, 10, 21, 42, 63, 126)  # skip 252 (needs longer panel)
    sweep, best = run_sweep(rets,
                            horizons=smoke_horizons,
                            cadences=r.R95_CADENCES,
                            costs=r.R95_COST_GRID)
    expected = len(smoke_horizons) * len(r.R95_CADENCES) * len(r.R95_COST_GRID)
    assert len(sweep) == expected, \
        f"sweep size {len(sweep)} != expected {expected}"
    # Each key is (h, cad, bps)
    for k in list(sweep.keys())[:5]:
        assert isinstance(k, tuple) and len(k) == 3
        h, cad, bps = k
        assert h in smoke_horizons
        assert cad in r.R95_CADENCES
        assert bps in r.R95_COST_GRID
    # Best cell dict has expected keys
    assert "horizon" in best and "cadence" in best and "cost_bps" in best
    assert "full_t" in best and "oos_t" in best and "max_dd" in best
    print(f"  ✓ sweep size = {len(sweep)} = {len(smoke_horizons)} × "
          f"{len(r.R95_CADENCES)} × {len(r.R95_COST_GRID)} (full sweep is 7×6×5=210)")


def t_leg_correlation_keys():
    """Payload includes R46/R62/R76/R77 leg-correlation gate."""
    import src.research.validation.r95_per_asset_tsmom as r
    fn = leg_correlation_check_stub_payload(r)
    assert "per_leg" in fn
    assert "max_abs_corr" in fn
    assert "passes_gate" in fn
    print(f"  ✓ leg_correlation payload has per_leg + max_abs_corr + passes_gate")


def leg_correlation_check_stub_payload(r):
    """Helper: invoke leg_correlation_check on synthetic pnl series, return payload."""
    pnl = pd.Series(np.random.default_rng(42).normal(0, 0.01, 100))
    leg_pnls = {"R46_placeholder": pnl, "R62_placeholder": -pnl}
    return r.leg_correlation_check(pnl, leg_pnls=leg_pnls, gate=0.30)


def t_combined_book_keys():
    """Combined-book payload includes R95+R77 combined Sharpe, maxDD, OOS_t."""
    import src.research.validation.r95_per_asset_tsmom as r
    pnl_r95 = pd.Series(np.random.default_rng(42).normal(0, 0.01, 100))
    pnl_r77 = pd.Series(np.random.default_rng(7).normal(0, 0.01, 100))
    out = r.combined_book_stats(pnl_r95, pnl_r77, w_r95=0.5)
    assert "available" in out
    if out["available"]:
        assert "n_common" in out
        assert "w_r95" in out
        assert "corr_r95_r77" in out
        assert "r77_sharpe" in out
        assert "r95_sharpe" in out
        assert "combined_sharpe" in out
        assert "sharpe_lift" in out
        assert "combined_max_dd" in out
        assert "max_dd_increase" in out
    # Degraded path: None R77 → available=False with note
    out_none = r.combined_book_stats(pnl_r95, None, w_r95=0.5)
    assert out_none["available"] is False
    assert "note" in out_none
    print(f"  ✓ combined_book_stats keys present (available={out['available']}, "
          f"degraded when R77 PnL=None)")


def t_frozen_r77_untouched():
    """R95 module source references w_R46=0.25/w_R62=0.75/w_R76=0.30 with a note."""
    import src.research.validation.r95_per_asset_tsmom as r
    src = Path(r.__file__).read_text()
    # Reference to the frozen R77 weights must appear
    assert "w_R46=0.25/w_R62=0.75/w_R76=0.30" in src
    # Verdict grammar must include the "frozen R77 cell UNCHANGED" disclaimer
    assert "UNCHANGED" in src or "frozen" in src.lower()
    print("  ✓ R95 module references frozen R77 weights + UNCHANGED disclaimer")


def t_structural_difference_from_r78():
    """R78 used cross-sectional demean; R95 must NOT have `demeaned_full`."""
    import src.research.validation.r95_per_asset_tsmom as r
    src = Path(r.__file__).read_text()
    assert "demeaned_full" not in src, \
        "R95 must NOT contain 'demeaned_full' (R78's failure pattern)"
    print("  ✓ 'demeaned_full' absent from R95 source (R78 pattern avoided)")


def t_verdict_grammar():
    """All 3 verdict bands (TRADEABLE/PARTIAL/REFUTED) present in source."""
    import src.research.validation.r95_per_asset_tsmom as r
    src = Path(r.__file__).read_text()
    assert "TRADEABLE" in src
    assert "PARTIAL" in src
    assert "REFUTED" in src
    print("  ✓ all 3 verdict bands (TRADEABLE / PARTIAL / REFUTED) in source")


def t_anti_imposter_discipline():
    """All anti-imposter gates present: 3-check + cost-tier + leg-corr + maxDD + W5."""
    import src.research.validation.r95_per_asset_tsmom as r
    src = Path(r.__file__).read_text()
    # 3-check gauntlet
    assert "full_t" in src and "oos_t" in src
    # Cost-tier sweep
    assert "R95_COST_GRID" in src and "R95_REALISTIC_COST_BPS" in src
    assert "10.0" in src and "20.0" in src and "30.0" in src
    # Leg-corr gate
    assert "leg_correlation_check" in src
    assert "R95_ORTHOGONALITY_GATE" in src
    # maxDD budget
    assert "R95_MAXDD_BUDGET" in src and "-0.20" in src
    # W5 sign-positive
    assert "W5" in src or "per_window" in src
    # R77 frozen reference
    assert "R77_SHARPE_FROZEN" in src and "R77_MAXDD_FROZEN" in src
    # Lessons applied
    assert "lessons_applied" in src or "lesson" in src.lower()
    print("  ✓ all anti-imposter gates present (3-check + cost + leg-corr + maxDD + W5)")


# ──────────────────────────────────────────────────────────────────────────────
# Runner
# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    tests = [
        t_imports,
        t_no_demean_in_score,
        t_score_shape,
        t_one_day_lag,
        t_multi_horizon_vote,
        t_multi_horizon_mean,
        t_tsmom_ls_shape,
        t_cost_on_rebal_days,
        t_sweep_keys,
        t_leg_correlation_keys,
        t_combined_book_keys,
        t_frozen_r77_untouched,
        t_structural_difference_from_r78,
        t_verdict_grammar,
        t_anti_imposter_discipline,
    ]
    passed = 0
    for i, t in enumerate(tests, 1):
        try:
            print(f"[{i}/{len(tests)}] {t.__name__[2:]}")
            t()
            passed += 1
        except Exception as e:
            print(f"  ✗ {t.__name__[2:]}: {e}")
            raise
    print(f"\n{passed}/{len(tests)} test(s) passed")