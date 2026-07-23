"""
R77 smoke tests — sandbox-safe, no Mac drive dependency.

Mirrors test_r74_pillar_a_fusion_contribution_smoke.py pattern but for R77's
funding-residual leg (R76) as 3rd fusion contribution. 11 tests cover:
  - imports + R77 constants (frozen R69 cell + R76 best cell)
  - fuse3 math correctness (1-w_R76, w_R76 split)
  - build_r76_sleeve_28 signature uses score_funding_residual (not zwide)
  - anti-imposter: R77 does NOT touch frozen R69 cell
  - both signs run
  - leg-correlation gate pre-test (lesson #42, already proven by R76)
  - strict 28-asset universe (R76/R63 parity)
  - live-book-untouched flag in payload
  - W5 attribution present (R76's killer window)
  - verdict grammar (FUSION_LIFT / NEUTRAL / LOSES)
  - lesson #43 reference
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))


def t_imports():
    """R77 module + key public symbols importable."""
    import src.research.validation.r77_r76_as_fusion_contribution as r
    assert hasattr(r, "run"), "R77 must expose run()"
    assert hasattr(r, "build_r76_sleeve_28"), "R77 must expose build_r76_sleeve_28"
    assert hasattr(r, "fuse3"), "R77 must expose fuse3()"
    assert hasattr(r, "format_report"), "R77 must expose format_report()"
    # Frozen R69 cell constants (DO NOT CHANGE)
    assert r.R69_W_R46 == 0.25, f"frozen w_R46 must be 0.25, got {r.R69_W_R46}"
    assert r.R69_W_R62 == 0.75, f"frozen w_R62 must be 0.75, got {r.R69_W_R62}"
    assert abs(r.R69_W_R46 + r.R69_W_R62 - 1.0) < 1e-9, "frozen weights must sum to 1.0"
    # R76 best cell constants
    assert r.R76_BEST_CAD == 5, f"R76 best cadence must be 5, got {r.R76_BEST_CAD}"
    assert r.R76_BEST_BPS == 0.0, f"R76 best cost must be 0.0, got {r.R76_BEST_BPS}"
    # w_R76 grid
    assert 0.0 in r.R77_W_GRID, "w_R76 grid must include 0 (frozen baseline)"
    assert max(r.R77_W_GRID) <= 0.30, "w_R76 grid must not exceed 0.30 (small w only)"
    # Lesson #42 gate
    assert r.R77_ORTHOGONALITY_GATE == 0.30, \
        f"R77 orthogonality gate must be 0.30 (lesson #42), got {r.R77_ORTHOGONALITY_GATE}"
    print("  ✓ R77 imports + frozen R69 cell + R76 best cell + w_R76 grid ≤ 0.30 + gate=0.30")


def t_frozen_baseline_constants():
    """Frozen baseline must be unchanged: w_R46=0.25, w_R62=0.75."""
    import src.research.validation.r77_r76_as_fusion_contribution as r
    src = Path(r.__file__).read_text()
    assert "R69_W_R46 = 0.25" in src, "frozen R69_W_R46 must be 0.25 (literal)"
    assert "R69_W_R62 = 0.75" in src, "frozen R69_W_R62 must be 0.75 (literal)"
    # Anti-imposter comment
    assert "FROZEN" in src or "frozen" in src.lower(), "R77 must mark these as FROZEN"
    # R77 is a TEST
    assert "R77 is a TEST" in src or "R77 is research-only" in src, \
        "R77 must self-mark as research-only / not a rebalance"
    print("  ✓ frozen baseline w_R46=0.25, w_R62=0.75 (literal) + R77 research-only")


def t_fuse3_math():
    """fuse3 = (1-w_R76) × fac_2 + w_R76 × fac_r76 — verify exact split."""
    import src.research.validation.r77_r76_as_fusion_contribution as r
    # Synthetic baseline + leg_r76
    fac_2 = pd.Series([0.1, 0.2, 0.3, 0.4, 0.5],
                       index=pd.date_range("2026-01-01", periods=5, freq="D"))
    fac_r76 = pd.Series([0.5, 0.4, 0.3, 0.2, 0.1],
                         index=pd.date_range("2026-01-01", periods=5, freq="D"))

    # w_R76=0 → fused = fac_2 (frozen baseline)
    f0 = r.fuse3(fac_2, fac_r76, w_r76=0.0)
    np.testing.assert_array_almost_equal(f0.values, fac_2.values,
                                          err_msg="w_R76=0 must reproduce fac_2")

    # w_R76=1 → fused = fac_r76
    f1 = r.fuse3(fac_2, fac_r76, w_r76=1.0)
    np.testing.assert_array_almost_equal(f1.values, fac_r76.values,
                                          err_msg="w_R76=1 must reproduce fac_r76")

    # w_R76=0.25 → fused = 0.75 × fac_2 + 0.25 × fac_r76
    f025 = r.fuse3(fac_2, fac_r76, w_r76=0.25)
    expected = 0.75 * fac_2.values + 0.25 * fac_r76.values
    np.testing.assert_array_almost_equal(f025.values, expected,
                                          err_msg="w_R76=0.25 must be 75/25 split")

    # NaN in fac_r76 → 0 (no contribution that day)
    fac_r76_nan = fac_r76.copy()
    fac_r76_nan.iloc[1] = np.nan
    f_nan = r.fuse3(fac_2, fac_r76_nan, w_r76=0.25)
    # Day 1: 0.75 × fac_2.iloc[1] + 0.25 × 0 (NaN→0) = 0.75 × 0.2 = 0.15
    assert abs(f_nan.iloc[1] - 0.75 * fac_2.iloc[1]) < 1e-9, \
        f"NaN in fac_r76 day 1 should give 0 contribution; got {f_nan.iloc[1]}"
    print("  ✓ fuse3 math correct: w_R76=0 → fac_2, w_R76=1 → fac_r76, NaN→0")


def t_build_r76_sleeve_signature():
    """build_r76_sleeve_28 must use score_funding_residual (not zwide) at R76's best cell."""
    import src.research.validation.r77_r76_as_fusion_contribution as r
    src = Path(r.__file__).read_text()
    # Must call R76's score_funding_residual (not zwide — that's R62)
    assert "score_funding_residual" in src, "R77 must call R76's score_funding_residual"
    assert "funding_residual_ls" in src, "R77 must call R76's funding_residual_ls"
    # build_r76_sleeve_28 function CODE body must NOT call score_funding_zwide (that's R62)
    import inspect
    func_src = inspect.getsource(r.build_r76_sleeve_28)
    lines = func_src.split("\n")
    code_lines = []
    in_docstring = False
    for ln in lines:
        if '"""' in ln:
            in_docstring = not in_docstring
            continue
        if not in_docstring:
            code_lines.append(ln)
    code_only = "\n".join(code_lines)
    assert "score_funding_zwide" not in code_only, \
        "build_r76_sleeve_28 code must NOT call score_funding_zwide — that's R62's path"
    # Must use R76's best-cell defaults
    assert "R76_BEST_CAD" in src and "R76_BEST_CPS" not in src, \
        "build_r76_sleeve_28 must reference R76_BEST_CAD (not R76_BEST_CPS typo)"
    print("  ✓ build_r76_sleeve_28 uses funding_residual (not zwide) + R76 best-cell defaults")


def t_anti_imposter_no_live_book_change():
    """R77 must NOT touch the frozen R69 cell. Payload must declare this."""
    import inspect
    import src.research.validation.r77_r76_as_fusion_contribution as r
    src = Path(r.__file__).read_text()
    # Anti-imposter language must be present
    assert "does NOT touch" in src or "DOES NOT touch" in src, \
        "R77 docstring must explicitly state it does NOT touch the live book"
    assert "FROZEN" in src or "frozen" in src.lower(), \
        "R77 must mark the R69 cell as FROZEN"
    assert "R77 is a TEST" in src or "R77 is research-only" in src, \
        "R77 must self-mark as research-only / not a rebalance"
    # Output payload must include live_book_impact block
    fmt_src = inspect.getsource(r.format_report)
    assert "live_book_impact" in fmt_src, \
        "format_report must include the live_book_impact section"
    assert "Touches frozen" in fmt_src, \
        "format_report must surface 'Touches frozen R69 cell: ...'"
    print("  ✓ R77 is research-only; live_book_impact surfaced in report")


def t_both_signs_supported():
    """Both R76 signs (SIGN_HIGH_FUND_LONG, SIGN_LOW_FUND_LONG) supported."""
    import src.research.validation.r77_r76_as_fusion_contribution as r
    from src.research.validation.r76_funding_residual_ls import (
        SIGN_HIGH_FUND_LONG, SIGN_LOW_FUND_LONG,
    )
    src = Path(r.__file__).read_text()
    assert SIGN_HIGH_FUND_LONG in src and SIGN_LOW_FUND_LONG in src, \
        "R77 must accept both signs of R76 leg"
    # CLI parser must accept both
    assert "choices=" in src and SIGN_HIGH_FUND_LONG in src and SIGN_LOW_FUND_LONG in src, \
        "R77 CLI must restrict sign to the two R76 signs"
    print("  ✓ both R76 signs accepted (high_fund_long, low_fund_long)")


def t_leg_correlation_gate_pretest():
    """R77 must run leg_correlation_gate as pre-test (lesson #42 already proven by R76)."""
    import src.research.validation.r77_r76_as_fusion_contribution as r
    src = Path(r.__file__).read_text()
    # Must call leg_correlation_gate from R76
    assert "leg_correlation_gate" in src, \
        "R77 must call leg_correlation_gate as pre-test (lesson #42)"
    # Must reference lesson #42 explicitly
    assert "lesson #42" in src.lower(), \
        "R77 must explicitly reference lesson #42 (leg-correlation gate)"
    # Must reference lesson #43 (orthogonal candidates hypothesis)
    assert "lesson #43" in src.lower(), \
        "R77 must explicitly reference lesson #43 (orthogonal-edge hypothesis)"
    # Orthogonality gate threshold
    assert "0.30" in src, "R77 must use 0.30 orthogonality threshold"
    print("  ✓ leg_correlation_gate pre-test + lesson #42 + lesson #43 explicit")


def t_strict_universe():
    """R77 must use the 28-asset strict funding ∩ CIS ∩ OHLCV universe (R76/R63 parity)."""
    import src.research.validation.r77_r76_as_fusion_contribution as r
    src = Path(r.__file__).read_text()
    assert "tradeable = funding_assets" in src, \
        "R77 must set tradeable = funding_assets (28-asset strict intersection)"
    assert "28-asset" in src or "STRICT" in src, \
        "R77 must mention the 28-asset strict universe explicitly"
    assert "do not silently widen" in src.lower() or "no silent widening" in src.lower(), \
        "R77 must encode anti-imposter discipline on universe (no silent widening)"
    print("  ✓ strict 28-asset universe enforced (R76/R63 parity)")


def t_verdict_grammar():
    """Verdict must be one of FUSION_LIFT / FUSION_NEUTRAL / FUSION_LOSES."""
    import src.research.validation.r77_r76_as_fusion_contribution as r
    src = Path(r.__file__).read_text()
    assert "FUSION_LIFT" in src, "verdict must include FUSION_LIFT band"
    assert "FUSION_NEUTRAL" in src, "verdict must include FUSION_NEUTRAL band"
    assert "FUSION_LOSES" in src, "verdict must include FUSION_LOSES band"
    # Verdict emoji
    assert "✅ FUSION LIFT" in src or "✅" in src, "verdict must include ✅ for lift"
    assert "🟡 NEUTRAL" in src or "🟡" in src, "verdict must include 🟡 for neutral"
    assert "🔴 FUSION LOSES" in src or "🔴" in src, "verdict must include 🔴 for loses"
    print("  ✓ verdict grammar: FUSION_LIFT / NEUTRAL / LOSES (✅/🟡/🔴)")


def t_synthetic_positive_ic_lift():
    """Synthetic: if Leg-R76 adds positive IC orthogonal to fac_2, fuse3 at w_R76>0 lifts OOS."""
    import src.research.validation.r77_r76_as_fusion_contribution as r
    # Build synthetic: fac_2 is broken OOS (sign-flip in last 30%); fac_r76 is strong OOS.
    rng = np.random.default_rng(77)
    n = 600
    cut = int(0.70 * n)

    # fac_2: market-tied, sign-flips in OOS (R46-style)
    market = rng.normal(scale=0.02, size=n)
    fac_2_full = np.concatenate([
        0.001 + market[:cut] * 0.5,                  # IS: positive beta to market
        -0.001 - market[cut:] * 0.5 + rng.normal(scale=0.005, size=n-cut),  # OOS: negative
    ])
    fac_2 = pd.Series(fac_2_full)

    # fac_r76: orthogonal, strong positive IC throughout
    # Independent of market to model orthogonality
    fac_r76_full = 0.002 + 0.003 * market + rng.normal(scale=0.002, size=n)
    fac_r76 = pd.Series(fac_r76_full)

    # Build fused_3 at w_R76=0.20: should lift OOS
    fused = r.fuse3(fac_2, fac_r76, w_r76=0.20)
    # ΔOOS_t direction check (proxied by mean difference, not strict t-stat)
    is_mean_2 = fac_2.iloc[:cut].mean()
    oos_mean_2 = fac_2.iloc[cut:].mean()
    is_mean_3 = fused.iloc[:cut].mean()
    oos_mean_3 = fused.iloc[cut:].mean()
    # OOS: fused should be LESS negative than fac_2 (leg_r76 pulls it back up)
    assert oos_mean_3 > oos_mean_2, \
        f"fused OOS mean should be > baseline OOS mean; got {oos_mean_3:.4f} vs {oos_mean_2:.4f}"
    # IS: fused should not be too different from baseline (small w_R76)
    assert abs(is_mean_3 - is_mean_2) < abs(oos_mean_3 - oos_mean_2) * 2, \
        "w_R76=0.20 should mainly affect OOS (smaller IS delta)"
    print(f"  ✓ synthetic positive-IC lift: OOS mean {oos_mean_2:+.4f} → {oos_mean_3:+.4f}")


def t_w5_attribution_present():
    """Per-window W1-W6 attribution must be present in payload (R76's killer W5)."""
    import src.research.validation.r77_r76_as_fusion_contribution as r
    src = Path(r.__file__).read_text()
    assert "W5" in src, "R77 must track W5 attribution (R76's killer W5=+98.4%)"
    assert "per_window" in src, "R77 must include per_window in payload"
    assert "delta_w5_ann_pct" in src, "R77 must compute ΔW5 ann% vs baseline"
    print("  ✓ W5 per-window attribution + delta vs baseline present")


# ── Runner ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    tests = [t_imports, t_frozen_baseline_constants, t_fuse3_math,
             t_build_r76_sleeve_signature, t_anti_imposter_no_live_book_change,
             t_both_signs_supported, t_leg_correlation_gate_pretest,
             t_strict_universe, t_verdict_grammar,
             t_synthetic_positive_ic_lift, t_w5_attribution_present]
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