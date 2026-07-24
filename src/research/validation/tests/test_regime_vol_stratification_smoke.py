"""
Smoke tests — S-78 regime×vol stratification (the sizing layer). Sandbox-safe, pure.
Run: python3 -m src.research.validation.tests.test_regime_vol_stratification_smoke
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")))

from src.research.validation.regime_vol_stratification import (  # noqa: E402
    vol_regime, size_multiplier, stratify, S78_MAP,
)


def test_vol_regime_terciles():
    # alternating ±x ⇒ std ≈ x, so we can hit each tercile deterministically
    assert vol_regime([0.010, -0.010] * 20) == "calm"     # std ~1.0% < 2.8%
    assert vol_regime([0.035, -0.035] * 20) == "normal"   # ~3.5% in [2.8, 4.5)
    assert vol_regime([0.060, -0.060] * 20) == "storm"    # ~6.0% > 4.5%
    assert vol_regime([0.01, -0.01]) is None, "too few obs ⇒ None, never a guessed regime"
    assert vol_regime(None) is None


def test_size_multiplier_presses_winning_cells():
    """EASING×calm and RISK_OFF×storm are the validated ✅ corners ⇒ size UP; ✗ cells ⇒ DOWN."""
    assert size_multiplier("EASING", "calm")["size_mult"] == 1.5      # t +8.0
    assert size_multiplier("RISK_OFF", "storm")["size_mult"] == 1.5   # t +17.6
    assert size_multiplier("EASING", "normal")["size_mult"] == 0.5    # t −8.4
    assert size_multiplier("EASING", "calm")["basis"] == "two_way(macro×vol)"


def test_size_multiplier_fallback_and_neutral():
    # unmeasured macro (RISK_ON) ⇒ one-way vol fallback (storm is +15 ⇒ up)
    r = size_multiplier("RISK_ON", "storm")
    assert r["size_mult"] == 1.5 and r["basis"] == "one_way(vol)"
    # weak cell (RISK_OFF×normal, t≈1.0) ⇒ neutral 1.0
    assert size_multiplier("RISK_OFF", "normal")["size_mult"] == 1.0
    # no vol regime ⇒ neutral, flagged
    assert size_multiplier("EASING", None)["size_mult"] == 1.0


def test_stratify_reproduces_cells():
    rows = ([{"edge": 6.0, "macro_regime": "EASING", "vol_regime": "calm"}] * 30 +
            [{"edge": -6.0, "macro_regime": "EASING", "vol_regime": "normal"}] * 30 +
            [{"edge": None, "macro_regime": "EASING", "vol_regime": "calm"}])   # NaN dropped
    m = {(c["macro_regime"], c["vol_regime"]): c for c in stratify(rows)}
    assert m[("EASING", "calm")]["n"] == 30 and m[("EASING", "calm")]["mean_edge"] == 6.0
    assert m[("EASING", "normal")]["mean_edge"] == -6.0


def test_map_has_both_winning_corners():
    assert S78_MAP[("EASING", "calm")][1] > 3 and S78_MAP[("RISK_OFF", "storm")][1] > 3


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    p = 0
    for t in TESTS:
        t(); print(f"  ✓ {t.__name__}"); p += 1
    print(f"\n✅ {p}/{len(TESTS)} S-78 regime×vol smoke tests passed")
