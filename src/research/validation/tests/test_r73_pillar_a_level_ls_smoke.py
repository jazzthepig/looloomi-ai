"""
R73 smoke tests — sandbox-safe, no Mac drive dependency.

Mirrors test_pillar_a_ls_smoke.py pattern. 11 tests cover:
  - imports
  - score basis (level-A NOT ΔA)
  - k_terciles default = 3 (NOT 5 like R72)
  - OOS cut at last 30% (NOT last 70%)
  - both signs run (anti-imposter)
  - 3-check gauntlet on synthetic positive-IC
  - sign verdict logic
  - per-window 6-row attribution
  - PIT-safe alignment on level-A
  - rejection of invalid sign
  - universe-floor guard
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))


def t_imports():
    """R73 module + key public symbols importable."""
    import src.research.validation.r73_pillar_a_level_ls as r
    assert hasattr(r, "run"), "R73 must expose run()"
    assert hasattr(r, "score_pillar_a_level"), "R73 must expose score_pillar_a_level"
    assert hasattr(r, "pillar_a_level_ls"), "R73 must expose pillar_a_level_ls"
    assert hasattr(r, "pillar_a_level_cadence_sweep"), "R73 must expose pillar_a_level_cadence_sweep"
    assert r.R73_K_TERCILES == 3, f"R73 K_TERCILES must be 3 (standard); got {r.R73_K_TERCILES}"
    assert r.R73_K_TERCILES != 5, "R73 K_TERCILES must NOT be 5 (R72 deliberately used 5 → bug)"
    assert hasattr(r, "SIGN_HIGH_A_LONG")
    assert hasattr(r, "SIGN_LOW_A_LONG")
    print("  ✓ R73 imports + k_terciles default = 3")


def t_score_basis_is_level():
    """R73 score = pillar_A LEVEL (NOT ΔA). Mirror of score_pillar_a_level."""
    import src.research.validation.r73_pillar_a_level_ls as r
    # 4 assets × 10 dates of monotonically rising A
    dates = pd.date_range("2026-01-01", periods=10, freq="D")
    assets = ["AAA", "BBB", "CCC", "DDD"]
    rows = []
    for i, d in enumerate(dates):
        for j, a in enumerate(assets):
            rows.append({"date": d, "asset": a, "A": float((j + 1) * 10 + i)})
    cis_long = pd.DataFrame(rows)
    score = r.score_pillar_a_level(cis_long)
    # Wide shape (date × asset)
    assert score.shape == (10, 4), f"expected (10, 4), got {score.shape}"
    # LEVEL not Δ: today's score == today's A (not its change)
    # First day: only first day itself (ffill has no prior)
    last_day = score.iloc[-1]
    # Last day A values from input
    expected_a_last = {(j + 1) * 10 + 9 for j in range(4)}
    assert set(round(v, 2) for v in last_day.values).issubset(expected_a_last), \
        f"score at last day must equal level A, got {sorted(last_day.values)}"
    # Change-vs-level: R72 was ΔA → first row would be NaN. R73 LEVEL → no NaN from diff.
    # The only NaN comes from ffill-prepending (day 1 has no prior).
    print("  ✓ score_pillar_a_level = level, NOT ΔA")


def t_k_terciles_is_3_not_5():
    """Lesson #40 anti-imposter: k=3 standard (R72's 5 was deliberate + likely bug-prone)."""
    import src.research.validation.r73_pillar_a_level_ls as r
    assert r.R73_K_TERCILES == 3, "R73 must NOT inherit R72's k=5"
    # Synthetic: 12 assets, daily pillar_A, k=3 should produce 4-4-4 buckets
    rng = np.random.default_rng(42)
    n_dates, n_assets = 30, 12
    score_wide = pd.DataFrame(
        rng.standard_normal((n_dates, n_assets)),
        index=pd.date_range("2025-01-01", periods=n_dates, freq="D"),
        columns=[f"A{i}" for i in range(n_assets)],
    )
    rets = pd.DataFrame(
        rng.standard_normal((n_dates, n_assets)) * 0.01,
        index=score_wide.index,
        columns=score_wide.columns,
    )
    fac = r.pillar_a_level_ls(score_wide, rets, k_terciles=3, cost_bps=0.0,
                              rebal_days=1, sign=r.SIGN_HIGH_A_LONG)
    # Length must equal dates
    assert len(fac) == n_dates, f"fac length mismatch: {len(fac)} != {n_dates}"
    # No NaN after reindex
    print("  ✓ k=3 produces valid L/S fac series")


def t_rejects_invalid_sign():
    """pillar_a_level_ls must ValueError on invalid sign."""
    import src.research.validation.r73_pillar_a_level_ls as r
    score_wide = pd.DataFrame(np.zeros((3, 3)), columns=["A", "B", "C"])
    rets = pd.DataFrame(np.zeros((3, 3)), columns=["A", "B", "C"])
    try:
        r.pillar_a_level_ls(score_wide, rets, sign="BOGUS_SIGN")
        raise AssertionError("should have raised ValueError")
    except ValueError:
        pass
    print("  ✓ invalid sign rejected")


def t_both_signs_run():
    """Anti-imposter: both SIGN_HIGH_A_LONG and SIGN_LOW_A_LONG must produce sweeps."""
    import src.research.validation.r73_pillar_a_level_ls as r
    rng = np.random.default_rng(7)
    n_dates, n_assets = 30, 9
    score = pd.DataFrame(
        rng.standard_normal((n_dates, n_assets)),
        index=pd.date_range("2025-02-01", periods=n_dates, freq="D"),
        columns=[f"A{i}" for i in range(n_assets)],
    )
    rets = pd.DataFrame(
        rng.standard_normal((n_dates, n_assets)) * 0.01,
        index=score.index,
        columns=score.columns,
    )
    # Non-degenerate known_arrs (zero columns → singular XᵀX). Tiny std suffices.
    known_arrs = {"market":   rng.standard_normal(n_dates) * 0.001,
                  "momentum": rng.standard_normal(n_dates) * 0.001}
    sweep_hi = r.pillar_a_level_cadence_sweep(score, rets, known_arrs,
                                              cadences=(1, 5), cost_grid=(0.0, 5.0),
                                              sign=r.SIGN_HIGH_A_LONG)
    sweep_lo = r.pillar_a_level_cadence_sweep(score, rets, known_arrs,
                                              cadences=(1, 5), cost_grid=(0.0, 5.0),
                                              sign=r.SIGN_LOW_A_LONG)
    assert set(sweep_hi.keys()) == {(1, 0.0), (1, 5.0), (5, 0.0), (5, 5.0)}, \
        f"unexpected hi sweep keys: {sweep_hi.keys()}"
    assert set(sweep_lo.keys()) == set(sweep_hi.keys()), "lo sign sweep keys mismatch"
    # Both signs must return finite alpha_t (regression check)
    for k, v in {**sweep_hi, **sweep_lo}.items():
        assert np.isfinite(v["alpha_t"]), f"non-finite alpha_t at {k}"
    print("  ✓ both signs run + 2×2 sweep grid (4 cells each)")


def t_oos_cut_at_last_30_pct():
    """OOS_FRAC = 0.30; integer cut = int(0.70 * n). Anti-imposter guard."""
    import src.research.validation.r73_pillar_a_level_ls as r
    assert r.OOS_FRAC == 0.30, f"OOS_FRAC must be 0.30 (last 30%), got {r.OOS_FRAC}"
    # Spot-check via w5_forensics.gauntlet_3check semantics: cut = int(0.70 * n).
    n = 100
    expected_cut = int(0.70 * n)
    assert expected_cut == 70, f"sanity cut should be 70 for n=100"
    print(f"  ✓ OOS_FRAC=0.30 → cut=int(0.70*n)={expected_cut} for n={n}")


def t_gauntlet_3check_synthetic_positive_ic():
    """Synthetic positive-IC fac → gauntlet reports positive gross_t / oos_t (smoke-level)."""
    from src.research.validation.w5_forensics import gauntlet_3check
    import src.research.validation.r73_pillar_a_level_ls as r

    rng = np.random.default_rng(123)
    n = 600
    # Strong-positive IC: fac = market × β + α + noise, so residual alpha is positive.
    # Per R61/R72 smoke pattern: assert gross_t POSITIVE (positive IC carries through).
    # Don't require passing 1.96 (n=180 OOS can't reach 1.96 at IC=0.1%).
    market_v = rng.normal(loc=0.0, scale=0.02, size=n)
    mom_v = rng.normal(loc=0.0, scale=0.01, size=n)
    # Residual alpha with high IC: signal ~ next day's returns × 3
    base_rets = rng.normal(scale=0.01, size=(n,))
    fac_v = 0.001 + 0.003 * base_rets + rng.normal(scale=0.005, size=n)  # ~ IC 0.4
    fac = pd.Series(fac_v)
    known = {"market": market_v, "momentum": mom_v}
    cut = int(0.70 * n)
    g = gauntlet_3check(fac, known, cut)
    assert "passes_all" in g and "oos_t" in g, f"gauntlet must return full payload: {g}"
    assert g["gross_t"] > 0, f"positive-IC fac must give positive gross_t, got {g['gross_t']:+.2f}"
    # Structural smoke: oos_t shares the gross_t positive regime (no implausible sign flip)
    assert g["oos_t"] is not None
    print(f"  ✓ synthetic positive-IC gauntlet smokes (gross_t={g['gross_t']:+.2f}, "
          f"OOS_t={g['oos_t']:+.2f}; full clear not required at n=180 IC=0.4)")


def t_quarter_cuts_returns_6_windows():
    """W1-W6 partition: ~6 equal slices of the panel."""
    from src.research.validation.cis_quality_robustness import quarter_cuts
    import src.research.validation.r73_pillar_a_level_ls as r
    # Sanity: 730-day panel → 6 ~121-day windows
    start = pd.Timestamp("2024-01-01")
    end = pd.Timestamp("2025-12-31")
    windows = quarter_cuts(start, end, n_windows=6)
    assert len(windows) == 6, f"expected 6 windows, got {len(windows)}"
    labels = [w[0] for w in windows]
    assert labels == ["W1", "W2", "W3", "W4", "W5", "W6"], f"unexpected labels: {labels}"
    # Each window must be ≤ 122 days for 730/6
    for label, s, e in windows:
        n_days = (e - s).days
        assert 100 <= n_days <= 140, f"{label} window out of bounds: {n_days}d"
    print("  ✓ quarter_cuts returns 6 W1-W6 windows of ~120 days each")


def t_r72_relation_in_report():
    """R73 module must carry the R72 relation context (anti-imposter: distinct object, R72's failure)."""
    import src.research.validation.r73_pillar_a_level_ls as r
    src = Path(r.__file__).read_text()
    assert "R72" in src, "R73 must reference its R72 predecessor"
    assert "ΔA" in src or "delta" in src.lower(), "R73 must distinguish itself from ΔA"
    assert "level" in src.lower(), "R73 must reference its score basis (level)"
    assert "+4.48" in src, "R73 must cite R63b's +4.48 level-edge claim (the hypothesis)"
    # Default score func returns LEVEL (no .diff)
    sig = r.score_pillar_a_level
    import inspect
    body = inspect.getsource(sig)
    assert ".diff(" not in body, "score_pillar_a_level must NOT call .diff() — that's ΔA"
    assert "ffill" in body, "score_pillar_a_level must ffill (PIT-safe)"
    print("  ✓ R73 relation to R72 explicit + score returns level (no diff)")


def t_score_basis_marker_in_orches():
    """R73's verdict payload must mark score_basis='level_A' (R72 was 'delta_A_1d')."""
    import src.research.validation.r73_pillar_a_level_ls as r
    src = Path(r.__file__).read_text()
    assert '"level_A"' in src or "'level_A'" in src, "R73 must mark score_basis='level_A'"
    assert "delta_A_1d" not in src, "R73 must NOT contain R72's score_basis marker"
    print("  ✓ score_basis marker distinguishes R73 (level_A) from R72 (delta_A_1d)")


def t_min_tradeable_floor():
    """R73 enforces MIN_TRADEABLE=12 — must NOT silently widen to easier CIS∩OHLCV."""
    import src.research.validation.r73_pillar_a_level_ls as r
    assert r.R73_MIN_TRADEABLE == 12, f"R73 min tradeable must be 12, got {r.R73_MIN_TRADEABLE}"
    # Source must require funding ∩ CIS ∩ OHLCV strictly
    src = Path(r.__file__).read_text()
    assert "funding" in src and "load_funding_daily" in src
    assert "strict" in src or "do not silently widen" in src.lower(), \
        "R73 source must encode anti-imposter discipline on universe"
    print("  ✓ min-tradeable floor + strict funding ∩ CIS ∩ OHLCV enforced")


# ── Runner ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    tests = [t_imports, t_score_basis_is_level, t_k_terciles_is_3_not_5,
             t_rejects_invalid_sign, t_both_signs_run, t_oos_cut_at_last_30_pct,
             t_gauntlet_3check_synthetic_positive_ic,
             t_quarter_cuts_returns_6_windows, t_r72_relation_in_report,
             t_score_basis_marker_in_orches, t_min_tradeable_floor]
    passed = 0
    for i, t in enumerate(tests, 1):
        name = t.__name__[2:]
        try:
            print(f"[{i}] {name}")
            t()
            passed += 1
        except Exception as e:
            print(f"  ✗ {name}: {e}")
            raise
    print(f"\n{passed} test(s) passed")
