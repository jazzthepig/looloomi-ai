"""
Smoke tests — S-78 regime×vol stratification (the sizing layer). Sandbox-safe, pure.
Run: python3 -m src.research.validation.tests.test_regime_vol_stratification_smoke
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")))

from src.research.validation.regime_vol_stratification import (  # noqa: E402
    vol_regime, size_multiplier, stratify, S78_CELLS,
)


def test_vol_regime_terciles():
    # alternating ±x ⇒ std ≈ x, so we can hit each tercile deterministically
    assert vol_regime([0.010, -0.010] * 20) == "calm"     # std ~1.0% < 2.8%
    assert vol_regime([0.035, -0.035] * 20) == "normal"   # ~3.5% in [2.8, 4.5)
    assert vol_regime([0.060, -0.060] * 20) == "storm"    # ~6.0% > 4.5%
    assert vol_regime([0.01, -0.01]) is None, "too few obs ⇒ None, never a guessed regime"
    assert vol_regime(None) is None


def test_size_multiplier_is_oos_gated():
    """ONLY the OOS-confirmed cell (RISK_OFF×storm) presses; in-sample-only cells stay neutral."""
    rs = size_multiplier("RISK_OFF", "storm")
    assert rs["size_mult"] == 1.5 and rs["status"] == "oos_confirmed"
    # EASING×calm looked great in-sample but has ZERO OOS obs ⇒ NOT tradeable ⇒ neutral
    ec = size_multiplier("EASING", "calm")
    assert ec["size_mult"] == 1.0 and ec["status"] == "in_sample_only"
    # consistently-negative cell ⇒ cut
    assert size_multiplier("RISK_OFF", "normal")["size_mult"] == 0.5


def test_size_multiplier_neutral_paths():
    # unmeasured macro (RISK_ON) ⇒ neutral (no OOS-confirmed evidence to press on)
    assert size_multiplier("RISK_ON", "storm")["size_mult"] == 1.0
    # unstable (sign-flip) cell ⇒ neutral, not pressed
    assert size_multiplier("EASING", "normal")["size_mult"] == 1.0
    # no vol regime ⇒ neutral
    assert size_multiplier("EASING", None)["size_mult"] == 1.0


def test_stratify_reproduces_cells():
    rows = ([{"edge": 6.0, "macro_regime": "EASING", "vol_regime": "calm"}] * 30 +
            [{"edge": -6.0, "macro_regime": "EASING", "vol_regime": "normal"}] * 30 +
            [{"edge": None, "macro_regime": "EASING", "vol_regime": "calm"}])   # NaN dropped
    m = {(c["macro_regime"], c["vol_regime"]): c for c in stratify(rows)}
    assert m[("EASING", "calm")]["n"] == 30 and m[("EASING", "calm")]["mean_edge"] == 6.0
    assert m[("EASING", "normal")]["mean_edge"] == -6.0


def test_only_riskoff_storm_survives_oos():
    """The disciplined result: exactly ONE cell is oos_confirmed (RISK_OFF×storm)."""
    confirmed = [k for k, v in S78_CELLS.items() if v["status"] == "oos_confirmed"]
    assert confirmed == [("RISK_OFF", "storm")], f"only RISK_OFF×storm survives OOS, got {confirmed}"


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    p = 0
    for t in TESTS:
        t(); print(f"  ✓ {t.__name__}"); p += 1
    print(f"\n✅ {p}/{len(TESTS)} S-78 regime×vol smoke tests passed")
