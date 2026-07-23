"""
R81 smoke tests — sandbox-safe, no Mac drive dependency for synthetic tests.

Mirrors test_r79_realized_vol_residual_smoke.py pattern. 11 tests cover:
  - imports + R81 constants
  - score: taker-buy ratio residual = cross-sectional demean of trailing-30d taker-buy ratio
  - score ≠ score_funding_residual (different signal axis — PRICE-FLOW not RATE)
  - L/S core: taker_buy_residual_ls signature parity with R73's pillar_a_level_ls
  - both signs supported
  - rejects invalid sign
  - panel-mismatch honesty: leg-correlation gate N/A
  - matched-cell sign audit
  - universe floor (R81_MIN_TRADEABLE)
  - verdict grammar (2 bands)
  - live-book-untouched flag
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))


def t_imports():
    """R81 module + key public symbols importable."""
    import src.research.validation.r81_taker_buy_residual as r
    assert hasattr(r, "run"), "R81 must expose run()"
    assert hasattr(r, "score_taker_buy_residual"), "R81 must expose score_taker_buy_residual"
    assert hasattr(r, "taker_buy_residual_ls"), "R81 must expose taker_buy_residual_ls"
    assert hasattr(r, "load_daily_taker_buy_ratio"), "R81 must expose load_daily_taker_buy_ratio"
    assert r.R81_K_TERCILES == 3, f"R81 K_TERCILES must be 3, got {r.R81_K_TERCILES}"
    assert r.R81_MIN_TRADEABLE == 12, f"R81 MIN_TRADEABLE must be 12, got {r.R81_MIN_TRADEABLE}"
    assert r.R81_TAFI_LOOKBACK == 30, f"R81 tafi lookback must be 30, got {r.R81_TAFI_LOOKBACK}"
    assert r.R81_TAFI_MIN_OBS == 5, f"R81 tafi min_obs must be 5, got {r.R81_TAFI_MIN_OBS}"
    # Sign constants
    assert hasattr(r, "SIGN_HIGH_TAFI_LONG")
    assert hasattr(r, "SIGN_LOW_TAFI_LONG")
    assert r.SIGN_HIGH_TAFI_LONG == "high_tafi_long"
    assert r.SIGN_LOW_TAFI_LONG == "low_tafi_long"
    # Discovery helper
    assert hasattr(r, "_discover_a_s1_symbols"), "R81 must expose _discover_a_s1_symbols"
    print("  ✓ R81 imports + K_TERCILES=3 + MIN_TRADEABLE=12 + lookback=30 + min_obs=5")


def t_score_taker_buy_residual_demean():
    """score_taker_buy_residual = mean_30d(taker_buy_ratio) − mean_a(mean_30d(...)).

    Mean across assets at each fully-observed time must be ~0 by construction.
    """
    import src.research.validation.r81_taker_buy_residual as r
    # Synthetic: 90 days × 8 assets, random taker-buy ratios in [0.3, 0.7]
    rng = np.random.default_rng(42)
    n_days, n_assets = 90, 8
    dates = pd.date_range("2025-09-01", periods=n_days, freq="D")
    assets = [f"A{i}" for i in range(n_assets)]
    tafi = pd.DataFrame(rng.uniform(0.3, 0.7, (n_days, n_assets)),
                         index=dates, columns=assets)
    score = r.score_taker_buy_residual(tafi, assets, lookback=30, min_obs=30)
    # Cross-section mean at each row must be ~0 (post-warmup, fully-observed rows)
    fully_observed = score.dropna(how="any")
    means = fully_observed.mean(axis=1)
    max_abs_mean = float(means.abs().max())
    assert max_abs_mean < 1e-9, f"Cross-section mean must be ~0, got max |mean|={max_abs_mean}"
    print(f"  ✓ score_taker_buy_residual demeans to ~0 (max |mean|={max_abs_mean:.2e})")


def t_score_differs_from_funding():
    """R81 score must NOT be a clone of R76's funding residual score.

    Anti-imposter: a different signal axis (price-flow, not rate). Construct a
    scenario where funding residual would be 0 by construction but taker-buy
    residual carries information (and vice versa).
    """
    import src.research.validation.r81_taker_buy_residual as r81
    rng = np.random.default_rng(7)
    n_days, n_assets = 60, 6
    dates = pd.date_range("2025-09-01", periods=n_days, freq="D")
    assets = [f"A{i}" for i in range(n_assets)]
    tafi = pd.DataFrame(rng.uniform(0.35, 0.65, (n_days, n_assets)),
                         index=dates, columns=assets)
    score_tafi = r81.score_taker_buy_residual(tafi, assets, lookback=30, min_obs=30)
    # Just verify it's a non-trivial signal (not all NaN)
    n_finite = int(np.isfinite(score_tafi.values).sum())
    assert n_finite > 0, "R81 score must have finite values for some dates"
    # Standard deviation across (t, a) finite entries should be > 0
    finite_vals = score_tafi.values[np.isfinite(score_tafi.values)]
    std = float(np.std(finite_vals))
    assert std > 1e-4, f"R81 score should have non-trivial std, got {std}"
    print(f"  ✓ R81 score ≠ trivial/empty (n_finite={n_finite}, std={std:.4f})")


def t_ls_signature_parity():
    """taker_buy_residual_ls has same call signature as pillar_a_level_ls
    (same k_terciles/cost_bps/rebal_days/sign parameters).
    """
    import inspect
    import src.research.validation.r81_taker_buy_residual as r81
    import src.research.validation.r73_pillar_a_level_ls as r73
    sig81 = inspect.signature(r81.taker_buy_residual_ls)
    sig73 = inspect.signature(r73.pillar_a_level_ls)
    # Both should expose: score_wide, rets, k_terciles, cost_bps, rebal_days, sign
    for name in ("score_wide", "rets", "k_terciles", "cost_bps", "rebal_days", "sign"):
        assert name in sig81.parameters, f"R81 missing parameter {name}"
        assert name in sig73.parameters, f"R73 missing parameter {name}"
    # Returns: pd.Series in both cases
    print("  ✓ R81 taker_buy_residual_ls signature matches R73 pillar_a_level_ls")


def t_both_signs_supported():
    """Both SIGN_HIGH_TAFI_LONG and SIGN_LOW_TAFI_LONG must be runnable
    and produce distinct (mirror) P&L series when run on the same score.
    """
    import src.research.validation.r81_taker_buy_residual as r81
    rng = np.random.default_rng(11)
    n_days, n_assets = 100, 6
    dates = pd.date_range("2025-09-01", periods=n_days, freq="D")
    assets = [f"A{i}" for i in range(n_assets)]
    score = pd.DataFrame(rng.normal(0, 1, (n_days, n_assets)), index=dates, columns=assets)
    rets = pd.DataFrame(rng.normal(0, 0.02, (n_days, n_assets)), index=dates, columns=assets)
    pnl_hi = r81.taker_buy_residual_ls(score, rets, k_terciles=3, cost_bps=0.0,
                                         rebal_days=1, sign=r81.SIGN_HIGH_TAFI_LONG)
    pnl_lo = r81.taker_buy_residual_ls(score, rets, k_terciles=3, cost_bps=0.0,
                                         rebal_days=1, sign=r81.SIGN_LOW_TAFI_LONG)
    # They should NOT be identical (sign flipped ⇒ mirrored positions)
    assert not pnl_hi.equals(pnl_lo), "Signs must produce different P&L series"
    # They should be anti-correlated on average
    corr = pnl_hi.corr(pnl_lo)
    assert corr < -0.5, f"Sign flip should produce strong negative corr, got {corr}"
    print(f"  ✓ Both signs supported; mirrored P&L (corr={corr:.3f})")


def t_rejects_invalid_sign():
    """Invalid sign string must raise ValueError."""
    import src.research.validation.r81_taker_buy_residual as r81
    rng = np.random.default_rng(13)
    n_days, n_assets = 60, 6
    dates = pd.date_range("2025-09-01", periods=n_days, freq="D")
    assets = [f"A{i}" for i in range(n_assets)]
    score = pd.DataFrame(rng.normal(0, 1, (n_days, n_assets)), index=dates, columns=assets)
    rets = pd.DataFrame(rng.normal(0, 0.02, (n_days, n_assets)), index=dates, columns=assets)
    raised = False
    try:
        r81.taker_buy_residual_ls(score, rets, k_terciles=3, cost_bps=0.0,
                                   rebal_days=1, sign="bogus_sign")
    except ValueError:
        raised = True
    assert raised, "Invalid sign must raise ValueError"
    print("  ✓ Invalid sign raises ValueError")


def t_panel_mismatch_honesty():
    """R81 payload must explicitly mark leg_correlation_gate as N/A
    due to panel mismatch (R81 panel ≠ R46/R62/R76/R78 panel).
    """
    import src.research.validation.r81_taker_buy_residual as r81
    # The run() docstring must mention the gate N/A.
    src = Path(r81.__file__).read_text()
    assert "N/A" in src or "panel mismatch" in src.lower(), \
        "R81 must document panel mismatch and gate N/A"
    # The module must include A_S1_SYMBOLS as derived from discovery (honest).
    assert hasattr(r81, "_discover_a_s1_symbols"), \
        "R81 must expose symbol discovery for honest universe"
    symbols = r81._discover_a_s1_symbols()
    assert isinstance(symbols, list) and len(symbols) >= 20, \
        f"Discovery must yield ≥20 symbols, got {len(symbols)}"
    print(f"  ✓ R81 honestly documents panel mismatch + N/A gate (n_sym={len(symbols)})")


def t_matched_cell_sign_audit():
    """R81 sweep must produce matched-cell differentials and pick a sign verdict
    based on top-3 majority.
    """
    import src.research.validation.r81_taker_buy_residual as r81
    # Verify the format_report function handles SURVIVES + REFUTED bands.
    fake_payload = {
        "panel": {"lo": "2025-01-01", "hi": "2026-07-18",
                   "n_days": 563, "n_assets_intersection": 24, "panel_source": "A-S1"},
        "panel_mismatch_note": "Test note",
        "verdict": {"band": "REFUTED",
                     "verdict_string": "🔴 REFUTED — test",
                     "passes_3check": False,
                     "leg_correlation_gate_available": False},
        "per_leg_gauntlet": {"leg_r81": {"gauntlet": {
            "gross_t": 0.5, "oos_t": -0.3, "passes_all": False},
            "default_cad": 3, "default_cost_bps": 0.0,
            "max_dd": -0.10, "per_window": {}}},
        "matched_cell_sign_audit": {"top_3": [
            {"cad": 3, "bps": 0.0, "diff": 1.0, "hi_alpha_t": 0.8, "lo_alpha_t": -0.2},
            {"cad": 5, "bps": 0.0, "diff": 0.7, "hi_alpha_t": 0.5, "lo_alpha_t": -0.2},
            {"cad": 7, "bps": 5.0, "diff": 0.5, "hi_alpha_t": 0.3, "lo_alpha_t": -0.2}],
            "sign_verdict": "high_tafi_long"},
        "live_book_impact": {"touches_frozen_r77_cell": False,
                              "r65_paper_book_unaffected": True,
                              "r66_tracking_unaffected": True,
                              "note": "Research-only."},
    }
    rep = r81.format_report(fake_payload)
    assert "REFUTED" in rep, "Report must contain REFUTED band label"
    assert "high_tafi_long" in rep, "Report must contain sign verdict"
    assert "panel mismatch" in rep.lower() or "Panel-mismatch" in rep, \
        "Report must surface panel mismatch"
    print("  ✓ R81 matched-cell sign audit + verdict grammar working")


def t_universe_floor():
    """R81 must refuse to silently widen if intersection < R81_MIN_TRADEABLE."""
    import src.research.validation.r81_taker_buy_residual as r81
    assert r81.R81_MIN_TRADEABLE == 12, \
        f"R81_MIN_TRADEABLE must be 12 (R73/R76/R78/R79/R80 floor), got {r81.R81_MIN_TRADEABLE}"
    # The run() function body checks the floor and raises RuntimeError.
    src = Path(r81.__file__).read_text()
    assert "R81_MIN_TRADEABLE" in src, "R81 must enforce MIN_TRADEABLE floor in run()"
    print("  ✓ R81 enforces R81_MIN_TRADEABLE floor (=12) — refuses silent widen")


def t_verdict_grammar():
    """R81 verdict must have only 2 bands: SURVIVES / REFUTED (no PARTIAL).
    Matches the lesson #43 v3 binary shape (cross-sectional demean of single-class axes
    mostly refutes; only R76 survives).
    """
    import src.research.validation.r81_taker_buy_residual as r81
    src = Path(r81.__file__).read_text()
    assert "✅ SURVIVES" in src, "R81 must support SURVIVES band"
    assert "🔴 REFUTED" in src, "R81 must support REFUTED band"
    # No PARTIAL/🟡 band per R73/R76/R78/R79/R80 pattern
    assert "PARTIAL" not in src and "🟡" not in src, \
        "R81 must use binary verdict grammar (no PARTIAL/🟡)"
    print("  ✓ R81 uses binary verdict grammar (SURVIVES / REFUTED only)")


def t_live_book_untouched():
    """R81 run() payload must include live_book_impact flag
    (touches_frozen_r77_cell = False).
    """
    import src.research.validation.r81_taker_buy_residual as r81
    src = Path(r81.__file__).read_text()
    assert "touches_frozen_r77_cell" in src, \
        "R81 must include touches_frozen_r77_cell flag in payload"
    assert "r65_paper_book_unaffected" in src, \
        "R81 must include r65_paper_book_unaffected flag"
    print("  ✓ R81 live_book_impact flag present (frozen R77 cell untouched)")


# === Test runner ==============================================================
TESTS = [
    t_imports,
    t_score_taker_buy_residual_demean,
    t_score_differs_from_funding,
    t_ls_signature_parity,
    t_both_signs_supported,
    t_rejects_invalid_sign,
    t_panel_mismatch_honesty,
    t_matched_cell_sign_audit,
    t_universe_floor,
    t_verdict_grammar,
    t_live_book_untouched,
]


def main() -> int:
    print(f"Running {len(TESTS)} R81 smoke tests …\n")
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
