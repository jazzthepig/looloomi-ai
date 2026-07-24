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


def test_size_multiplier_presses_nothing_after_event_count():
    """No cell cleared OOS + event-count, so NOTHING presses — honest neutral 1.0 everywhere."""
    # RISK_OFF×storm passed OOS but FAILED event-count (2/4 episodes) ⇒ event_refuted ⇒ neutral, not pressed
    rs = size_multiplier("RISK_OFF", "storm")
    assert rs["size_mult"] == 1.0 and rs["status"] == "event_refuted"
    # EASING×calm: in-sample-only ⇒ neutral
    assert size_multiplier("EASING", "calm")["size_mult"] == 1.0
    # nothing anywhere returns an up/down multiplier
    for mr in ("EASING", "RISK_OFF", "RISK_ON", "TIGHTENING"):
        for v in ("calm", "normal", "storm"):
            assert size_multiplier(mr, v)["size_mult"] == 1.0


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


def test_no_cell_survives_event_count():
    """The honest end state: NO cell is event_confirmed. RISK_OFF×storm passed OOS but is event_refuted."""
    assert not [k for k, v in S78_CELLS.items() if v["status"] == "event_confirmed"]
    assert S78_CELLS[("RISK_OFF", "storm")]["status"] == "event_refuted"


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    p = 0
    for t in TESTS:
        t(); print(f"  ✓ {t.__name__}"); p += 1
    print(f"\n✅ {p}/{len(TESTS)} S-78 regime×vol smoke tests passed")
