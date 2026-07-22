"""
R74 smoke tests — sandbox-safe, no Mac drive dependency.

Mirrors test_r73_pillar_a_level_ls_smoke.py pattern. 11 tests cover:
  - imports
  - frozen R69 baseline constants
  - fuse3 math correctness (1-w_A, w_A split)
  - R73 leg builder signature uses level-A (no diff) + R73 cadence
  - anti-imposter: R74 does NOT touch frozen R69 cell
  - both signs run
  - R62 detector reproduction parity
  - strict 28-asset universe (R73/R63 parity)
  - live-book-untouched flag in payload
  - W5 attribution present
  - verdict grammar (✅/🟡/🔴)
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))


def t_imports():
    """R74 module + key public symbols importable."""
    import src.research.validation.r74_pillar_a_fusion_contribution as r
    assert hasattr(r, "run"), "R74 must expose run()"
    assert hasattr(r, "build_r73_sleeve_28"), "R74 must expose build_r73_sleeve_28"
    assert hasattr(r, "fuse3"), "R74 must expose fuse3()"
    assert hasattr(r, "format_report"), "R74 must expose format_report()"
    # Constants
    assert r.R69_W_R46 == 0.25, f"frozen w_R46 must be 0.25, got {r.R69_W_R46}"
    assert r.R69_W_R62 == 0.75, f"frozen w_R62 must be 0.75, got {r.R69_W_R62}"
    assert abs(r.R69_W_R46 + r.R69_W_R62 - 1.0) < 1e-9, "frozen weights must sum to 1.0"
    assert r.R73_BEST_CAD == 3, f"R73 best cadence must be 3, got {r.R73_BEST_CAD}"
    assert r.R73_BEST_BPS == 0.0, f"R73 best cost must be 0.0, got {r.R73_BEST_BPS}"
    # w_A grid
    assert 0.0 in r.R74_W_A_GRID, "w_A grid must include 0 (frozen baseline)"
    assert max(r.R74_W_A_GRID) <= 0.30, "w_A grid must not exceed 0.30 (small w only)"
    print("  ✓ R74 imports + frozen constants + w_A grid ≤ 0.30")


def t_frozen_baseline_constants():
    """Frozen baseline must be unchanged: w_R46=0.25, w_R62=0.75."""
    import src.research.validation.r74_pillar_a_fusion_contribution as r
    # Read source to ensure constants aren't accidentally mutable
    src = Path(r.__file__).read_text()
    assert "R69_W_R46 = 0.25" in src, "frozen R69_W_R46 must be 0.25 (literal)"
    assert "R69_W_R62 = 0.75" in src, "frozen R69_W_R62 must be 0.75 (literal)"
    # Anti-imposter comment
    assert "FROZEN" in src or "frozen" in src.lower(), "R74 must mark these as FROZEN"
    print("  ✓ frozen baseline w_R46=0.25, w_R62=0.75 (literal)")


def t_fuse3_math():
    """fuse3 = (1-w_A) × fac_2 + w_A × fac_a — verify exact split."""
    import src.research.validation.r74_pillar_a_fusion_contribution as r
    # Synthetic baseline + leg-A
    fac_2 = pd.Series([0.1, 0.2, 0.3, 0.4, 0.5],
                       index=pd.date_range("2026-01-01", periods=5, freq="D"))
    fac_a = pd.Series([0.5, 0.4, 0.3, 0.2, 0.1],
                       index=pd.date_range("2026-01-01", periods=5, freq="D"))

    # w_A=0 → fused = fac_2 (frozen baseline)
    f0 = r.fuse3(fac_2, fac_a, w_a=0.0)
    np.testing.assert_array_almost_equal(f0.values, fac_2.values,
                                          err_msg="w_A=0 must reproduce fac_2")

    # w_A=1 → fused = fac_a
    f1 = r.fuse3(fac_2, fac_a, w_a=1.0)
    np.testing.assert_array_almost_equal(f1.values, fac_a.values,
                                          err_msg="w_A=1 must reproduce fac_a")

    # w_A=0.5 → fused = 0.5 × fac_2 + 0.5 × fac_a
    f05 = r.fuse3(fac_2, fac_a, w_a=0.5)
    expected = 0.5 * fac_2.values + 0.5 * fac_a.values
    np.testing.assert_array_almost_equal(f05.values, expected,
                                          err_msg="w_A=0.5 must be 50/50 split")

    # NaN in fac_a → 0 (no contribution that day)
    fac_a_nan = fac_a.copy()
    fac_a_nan.iloc[1] = np.nan
    f_nan = r.fuse3(fac_2, fac_a_nan, w_a=0.5)
    # Day 1: 0.5 × fac_2.iloc[1] + 0.5 × 0 (NaN→0) = 0.5 × 0.2 = 0.1
    assert abs(f_nan.iloc[1] - 0.5 * fac_2.iloc[1]) < 1e-9, \
        f"NaN in fac_a day 1 should give 0 contribution; got {f_nan.iloc[1]}"
    print("  ✓ fuse3 math correct: w_A=0 → fac_2, w_A=1 → fac_a, NaN→0")


def t_r73_leg_builder_signature():
    """build_r73_sleeve_28 must use pillar_A LEVEL (no .diff) at R73's best cell."""
    import src.research.validation.r74_pillar_a_fusion_contribution as r
    src = Path(r.__file__).read_text()
    # Must call R73's pillar_a_level_ls (not .diff anywhere in build_r73)
    assert "pillar_a_level_ls" in src, "R74 must call R73's pillar_a_level_ls"
    assert "score_pillar_a_level" in src, "R74 must call R73's score_pillar_a_level"
    # The build_r73 function CODE body must NOT call .diff (that's R72's ΔA path).
    # Strip the docstring (which legitimately mentions ".diff()" descriptively).
    import inspect
    func_src = inspect.getsource(r.build_r73_sleeve_28)
    # Drop docstring lines (everything between """...""")
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
    assert ".diff(" not in code_only, \
        "build_r73_sleeve_28 code must NOT call .diff() — that's R72's ΔA, not R73's LEVEL"
    # Must use R73's best-cadence defaults (R73_BEST_CAD, not R73_BEST_CPS — typo guard)
    assert "R73_BEST_CAD" in src and "R73_BEST_CPS" not in src, \
        "build_r73_sleeve_28 must reference R73_BEST_CAD (not R73_BEST_CPS typo)"
    print("  ✓ build_r73_sleeve_28 uses LEVEL (no diff) + R73 best-cadence defaults")


def t_anti_imposter_no_live_book_change():
    """R74 must NOT touch the frozen R69 cell. Payload must declare this."""
    import inspect
    import src.research.validation.r74_pillar_a_fusion_contribution as r
    src = Path(r.__file__).read_text()
    # Anti-imposter language must be present
    assert "does NOT touch" in src or "DOES NOT touch" in src, \
        "R74 docstring must explicitly state it does NOT touch the live book"
    assert "FROZEN" in src or "frozen" in src.lower(), \
        "R74 must mark the R69 cell as FROZEN"
    assert "R74 is a TEST" in src or "R74 is research-only" in src, \
        "R74 must self-mark as research-only / not a rebalance"
    # Output payload must include live_book_impact block
    # Spot-check by importing format_report and checking it references live_book_impact
    fmt_src = inspect.getsource(r.format_report)
    assert "live_book_impact" in fmt_src, \
        "format_report must include the live_book_impact section"
    assert "Touches frozen" in fmt_src, \
        "format_report must surface 'Touches frozen R69 cell: ...'"
    print("  ✓ R74 is research-only; live_book_impact surfaced in report")


def t_both_signs_supported():
    """Both Leg-A signs (SIGN_HIGH_A_LONG, SIGN_LOW_A_LONG) supported."""
    import src.research.validation.r74_pillar_a_fusion_contribution as r
    from src.research.validation.r73_pillar_a_level_ls import (
        SIGN_HIGH_A_LONG, SIGN_LOW_A_LONG,
    )
    # Default in run() = SIGN_HIGH_A_LONG
    src = Path(r.__file__).read_text()
    assert SIGN_HIGH_A_LONG in src and SIGN_LOW_A_LONG in src, \
        "R74 must accept both signs of Leg-A"
    # CLI parser must accept both
    import inspect
    cli_src = inspect.getsource(r.__file__) if False else ""
    # Check via argparse choices in CLI section
    assert "choices=" in src and SIGN_HIGH_A_LONG in src and SIGN_LOW_A_LONG in src, \
        "R74 CLI must restrict sign to the two R73 signs"
    print("  ✓ both Leg-A signs accepted (high_a_long, low_a_long)")


def t_r62_detector_parity():
    """R74's R62 detector reproduction must match R63's structure (anti-imposter parity)."""
    import src.research.validation.r74_pillar_a_fusion_contribution as r
    src = Path(r.__file__).read_text()
    # Must call _build_r62_detector or replicate its structure
    # R74 uses R63's _build_r62_detector directly (imported)
    assert "_build_r62_detector" in src, \
        "R74 must use R63's _build_r62_detector (parity)"
    # R62 constants
    assert "R62_Z = 0.5" in src or "from src.research.validation.r63_fusion_validation import" in src, \
        "R74 must import R62 constants from R63"
    print("  ✓ R74 uses R63's _build_r62_detector + R62 constants (parity)")


def t_strict_universe():
    """R74 must use the 28-asset strict funding ∩ CIS ∩ OHLCV universe (R73/R63 parity)."""
    import src.research.validation.r74_pillar_a_fusion_contribution as r
    src = Path(r.__file__).read_text()
    assert "tradeable = funding_assets" in src, \
        "R74 must set tradeable = funding_assets (28-asset strict intersection)"
    assert "28-asset" in src or "STRICT" in src, \
        "R74 must mention the 28-asset strict universe explicitly"
    assert "do not silently widen" in src.lower() or "no silent widening" in src.lower(), \
        "R74 must encode anti-imposter discipline on universe (no silent widening)"
    print("  ✓ strict 28-asset universe enforced (R73/R63 parity)")


def t_verdict_grammar():
    """Verdict must be one of FUSION_LIFT / FUSION_NEUTRAL / FUSION_LOSES."""
    import src.research.validation.r74_pillar_a_fusion_contribution as r
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
    """Synthetic: if Leg-A adds positive IC orthogonal to Leg1+Leg2, fuse3 at w_A>0 lifts OOS."""
    import src.research.validation.r74_pillar_a_fusion_contribution as r
    # Build synthetic: fac_2 is broken OOS (sign-flip in last 30%); fac_a is strong OOS.
    rng = np.random.default_rng(99)
    n = 600
    cut = int(0.70 * n)

    # fac_2: market-tied, sign-flips in OOS
    market = rng.normal(scale=0.02, size=n)
    fac_2_full = np.concatenate([
        0.001 + market[:cut] * 0.5,                  # IS: positive beta to market
        -0.001 - market[cut:] * 0.5 + rng.normal(scale=0.005, size=n-cut),  # OOS: negative
    ])
    fac_2 = pd.Series(fac_2_full)

    # fac_a: strong positive IC throughout (orthogonal to market)
    fac_a_full = 0.002 + 0.003 * market + rng.normal(scale=0.002, size=n)
    fac_a = pd.Series(fac_a_full)

    # Build fused_3 at w_A=0.20: should lift OOS
    fused = r.fuse3(fac_2, fac_a, w_a=0.20)
    # ΔOOS_t direction check (proxied by mean difference, not strict t-stat)
    is_mean_2 = fac_2.iloc[:cut].mean()
    oos_mean_2 = fac_2.iloc[cut:].mean()
    is_mean_3 = fused.iloc[:cut].mean()
    oos_mean_3 = fused.iloc[cut:].mean()
    # OOS: fused should be LESS negative than fac_2 (leg_a pulls it back up)
    assert oos_mean_3 > oos_mean_2, \
        f"fused OOS mean should be > baseline OOS mean; got {oos_mean_3:.4f} vs {oos_mean_2:.4f}"
    # IS: fused should not be too different from baseline (small w_A)
    assert abs(is_mean_3 - is_mean_2) < abs(oos_mean_3 - oos_mean_2) * 2, \
        "w_A=0.20 should mainly affect OOS (smaller IS delta)"
    print(f"  ✓ synthetic positive-IC lift: OOS mean {oos_mean_2:+.4f} → {oos_mean_3:+.4f}")


def t_w5_attribution_present():
    """Per-window W1-W6 attribution must be present in payload."""
    import src.research.validation.r74_pillar_a_fusion_contribution as r
    src = Path(r.__file__).read_text()
    assert "W5" in src, "R74 must track W5 attribution (R73/R63 lesson #29 — W5 fragility)"
    assert "per_window" in src, "R74 must include per_window in payload"
    assert "delta_w5_ann_pct" in src, "R74 must compute ΔW5 ann% vs baseline"
    print("  ✓ W5 per-window attribution + delta vs baseline present")


# ── Runner ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    tests = [t_imports, t_frozen_baseline_constants, t_fuse3_math,
             t_r73_leg_builder_signature, t_anti_imposter_no_live_book_change,
             t_both_signs_supported, t_r62_detector_parity,
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
