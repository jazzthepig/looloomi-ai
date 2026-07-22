"""Smoke tests for fusion_paper_tracking.py (R66 module).

Verifies:
  1. Module + symbols import cleanly
  2. R64 forward reference constants are correct
  3. Live Sharpe: flat → None; non-flat → finite
  4. Sharpe gap status: WARMING_UP < 20d; on_track; DRIFT
  5. Detector fire status: WARMING_UP, normal, elevated, PERSISTENT_HIGH
  6. Capacity evolution: ok, EROSION, BREACH
  7. Validation countdown: 0d, 45d, 60d (validated=true)
  8. Max DD: returns negative for losing series, None for empty
  9. detect_lifecycle_events emits BOOK_INCEPTION, DETECTOR_PERSISTENT_HIGH, VALIDATED
  10. R64 cell reference unchanged from R64 verdict
  11. Validation threshold = 60 days (matches fusion_paper.py)
  12. No forbidden signal language in module source

Pure Python + numpy + pandas; no scipy / nautilus / freqtrade. Sandbox-safe.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

import numpy as np

from src.research.validation.fusion_paper_tracking import (
    R64_OOS_ALPHA_T, R64_OOS_DAYS, R64_OOS_ANN_SHARPE_PROXY,
    R62_DETECTOR_FIRE_RATE, R62_DETECTOR_HIGH_THRESHOLD,
    VALIDATION_MIN_DAYS, WARMUP_MIN_DAYS, SHARPE_GAP_DRIFT_THRESHOLD,
    CAP_FILL_OK, CAP_FILL_EROSION, CAP_SLIP_OK_BPS, CAP_SLIP_EROSION_BPS,
    _live_sharpe, _sharpe_gap_status, _detector_fire_status,
    _capacity_evolution, _validation_countdown, _max_drawdown_pct,
    detect_lifecycle_events, compute_tracking_snapshot,
)


def test_imports():
    from src.research.validation import fusion_paper_tracking as m
    for sym in (
        "R64_OOS_ALPHA_T", "R64_OOS_DAYS", "R64_OOS_ANN_SHARPE_PROXY",
        "R62_DETECTOR_FIRE_RATE", "R62_DETECTOR_HIGH_THRESHOLD",
        "VALIDATION_MIN_DAYS", "WARMUP_MIN_DAYS",
        "_live_sharpe", "_sharpe_gap_status", "_detector_fire_status",
        "_capacity_evolution", "_validation_countdown", "_max_drawdown_pct",
        "detect_lifecycle_events", "compute_tracking_snapshot",
    ):
        assert hasattr(m, sym), f"missing symbol: {sym}"
    print("✓ imports OK")


def test_r64_forward_reference_constants():
    """R64 forward reference must match the R64 verdict (R65 depends on these)."""
    assert R64_OOS_ALPHA_T == 2.38, f"R64 OOS α_t must be 2.38, got {R64_OOS_ALPHA_T}"
    assert R64_OOS_DAYS == 219, f"R64 OOS days must be 219, got {R64_OOS_DAYS}"
    assert abs(R64_OOS_ANN_SHARPE_PROXY - 1.69) < 0.01, (
        f"R64 OOS ann Sharpe proxy must be ≈ 1.69, got {R64_OOS_ANN_SHARPE_PROXY}")
    assert R62_DETECTOR_FIRE_RATE == 0.082, "R62 detector reference hit-rate must be 8.2%"
    assert R62_DETECTOR_HIGH_THRESHOLD == 0.30, "Detector PERSISTENT_HIGH threshold = 30%"
    assert VALIDATION_MIN_DAYS == 60, "Validation gate at 60 days (matches fusion_paper.py)"
    assert WARMUP_MIN_DAYS == 20, "Warmup threshold at 20 days"
    assert SHARPE_GAP_DRIFT_THRESHOLD == -0.75, "Drift threshold at gap < -0.75"
    print(f"✓ R64 forward reference: OOS α_t={R64_OOS_ALPHA_T}, Sharpe≈{R64_OOS_ANN_SHARPE_PROXY}, "
          f"R62 fire ref={R62_DETECTOR_FIRE_RATE}, validation={VALIDATION_MIN_DAYS}d")


def test_live_sharpe_basics():
    """Flat series → None; non-trivial returns → finite Sharpe."""
    assert _live_sharpe([0.0] * 10) is None, "Flat series → None"
    assert _live_sharpe([0.0, 0.0, 0.0]) is None, "Too few points → None"
    s = _live_sharpe([0.01, -0.005, 0.002, 0.001, -0.003, 0.004, -0.001, 0.0, 0.002, -0.002])
    assert s is not None and isinstance(s, float)
    # Manually compute for sanity
    arr = np.array([0.01, -0.005, 0.002, 0.001, -0.003, 0.004, -0.001, 0.0, 0.002, -0.002])
    expected = float(arr.mean() / arr.std() * np.sqrt(365))
    assert abs(s - expected) < 1e-9, f"Sharpe should equal manual computation"
    print(f"✓ live Sharpe: finite={s:.3f}, expected={expected:.3f}")


def test_sharpe_gap_status_progression():
    """Status progresses: WARMING_UP < 20d → on_track → DRIFT."""
    g_warm = _sharpe_gap_status(None, 10)
    assert g_warm["status"] == "WARMING_UP"
    assert g_warm["n_days"] == 10

    g_warm2 = _sharpe_gap_status(0.5, 19)  # still < WARMUP
    assert g_warm2["status"] == "WARMING_UP"

    g_on = _sharpe_gap_status(2.0, 50)  # gap = 2.0 - 1.69 = +0.31
    assert g_on["status"] == "on_track"
    assert g_on["gap"] == round(2.0 - R64_OOS_ANN_SHARPE_PROXY, 3)

    g_drift = _sharpe_gap_status(0.5, 50)  # gap = 0.5 - 1.69 = -1.19
    assert g_drift["status"] == "DRIFT"
    print(f"✓ sharpe gap: warmup<20d → on_track(2.0) → DRIFT(0.5)")


def test_detector_fire_status():
    """Detector fire status: WARMING_UP / normal / elevated / PERSISTENT_HIGH."""
    d_warm = _detector_fire_status([], 10)
    assert d_warm["status"] == "WARMING_UP"

    d_normal = _detector_fire_status([False] * 100, 100)  # 0% fires
    assert d_normal["status"] == "normal"

    d_elev = _detector_fire_status([True] * 15 + [False] * 85, 100)  # 15%
    assert d_elev["status"] == "elevated", "15% (1.8× ref) = elevated"
    assert 0.14 < d_elev["fire_rate"] < 0.16

    d_high = _detector_fire_status([True] * 50 + [False] * 50, 100)  # 50%
    assert d_high["status"] == "PERSISTENT_HIGH"
    print(f"✓ detector fire: normal(0%) → elevated(15%) → PERSISTENT(50%)")


def test_capacity_evolution():
    """Capacity status: ok / EROSION / BREACH based on fill + slip + BREACH days."""
    c_warm = _capacity_evolution([], [], [], 10)
    assert c_warm["status"] == "WARMING_UP"

    c_ok = _capacity_evolution([0.99] * 50, [5.0] * 50, ["ok"] * 50, 50)
    assert c_ok["status"] == "ok"
    assert c_ok["breach_days"] == 0

    c_erosion = _capacity_evolution([0.90] * 50, [12.0] * 50, ["ok"] * 50, 50)
    assert c_erosion["status"] == "EROSION", "fill=0.90 + slip=12bps = EROSION"

    c_breach = _capacity_evolution([0.99] * 49 + [0.5], [5.0] * 50,
                                    ["ok"] * 49 + ["BREACHED"], 50)
    assert c_breach["status"] == "BREACH", "Any BREACH day → BREACH"
    assert c_breach["breach_days"] == 1
    print(f"✓ capacity: ok → EROSION → BREACH (1 breach day)")


def test_validation_countdown():
    """Validation gate at 60 days — matches fusion_paper.py exactly."""
    v0 = _validation_countdown(0)
    assert v0["days_remaining"] == 60 and not v0["validated"]

    v45 = _validation_countdown(45)
    assert v45["days_remaining"] == 15 and not v45["validated"]

    v60 = _validation_countdown(60)
    assert v60["days_remaining"] == 0 and v60["validated"]

    v99 = _validation_countdown(99)
    assert v99["days_remaining"] == 0 and v99["validated"]
    print(f"✓ validation: 0d→60d remaining, 60d→validated=true, 99d→still validated")


def test_max_drawdown_pct():
    """Max DD: empty → None; losing series → negative %."""
    assert _max_drawdown_pct([]) is None
    dd = _max_drawdown_pct([1.0, 1.1, 1.2, 1.0, 0.95, 1.05])
    assert dd is not None and dd < 0
    # Series that goes 1.0 → 0.95 should have DD = -5%
    dd_simple = _max_drawdown_pct([1.0, 0.95, 1.0])
    assert abs(dd_simple - (-5.0)) < 0.01, f"DD should be -5%, got {dd_simple}"
    print(f"✓ max DD: empty=None, [1.0→0.95]={dd_simple:.2f}%, mixed={dd:.2f}%")


def test_detect_lifecycle_events_book_inception():
    """First day (n_days_marked=1) → BOOK_INCEPTION event."""
    snap = {
        "validation_countdown": {"n_days_marked": 1},
        "sharpe_gap": {"status": "WARMING_UP"},
        "detector_fire": {"status": "WARMING_UP"},
        "capacity": {"status": "WARMING_UP"},
        "r64_cell_reference": "...",
        "declared_capacity_usd": 5_000_000.0,
    }
    evs = detect_lifecycle_events(snap, None)
    types = {e["event_type"] for e in evs}
    assert "BOOK_INCEPTION" in types, f"BOOK_INCEPTION missing on day 1, got {types}"
    assert "WARMING_UP" in types
    print(f"✓ BOOK_INCEPTION on day 1: {types}")


def test_detect_lifecycle_events_persistent_high():
    """Detector fire-rate > 30% → DETECTOR_PERSISTENT_HIGH event."""
    snap = {
        "validation_countdown": {"n_days_marked": 80, "validated": True},
        "sharpe_gap": {"status": "on_track", "live_sharpe": 1.5},
        "detector_fire": {"status": "PERSISTENT_HIGH", "fire_rate": 0.45,
                          "r62_reference": 0.082, "high_threshold": 0.30, "n_days": 80},
        "capacity": {"status": "ok", "breach_days": 0, "breach_rate": 0},
        "r64_cell_reference": "...",
        "declared_capacity_usd": 5_000_000.0,
    }
    evs = detect_lifecycle_events(snap, {"validation_countdown": {"validated": True}})
    types = {e["event_type"] for e in evs}
    assert "DETECTOR_PERSISTENT_HIGH" in types, f"PERSISTENT_HIGH missing, got {types}"
    # No BOOK_INCEPTION (not day 1)
    assert "BOOK_INCEPTION" not in types
    print(f"✓ DETECTOR_PERSISTENT_HIGH emitted: {types}")


def test_detect_lifecycle_events_validated_transition():
    """Crossing 60d threshold from not-validated → VALIDATED event."""
    snap = {
        "validation_countdown": {"n_days_marked": 60, "validated": True},
        "sharpe_gap": {"status": "on_track", "live_sharpe": 1.5},
        "detector_fire": {"status": "normal"},
        "capacity": {"status": "ok"},
        "r64_cell_reference": "...",
        "declared_capacity_usd": 5_000_000.0,
    }
    prev = {"validation_countdown": {"validated": False}}
    evs = detect_lifecycle_events(snap, prev)
    types = {e["event_type"] for e in evs}
    assert "VALIDATED" in types, f"VALIDATED event missing on transition, got {types}"
    # Re-run with previous already validated → no second VALIDATED event
    prev2 = {"validation_countdown": {"validated": True}}
    evs2 = detect_lifecycle_events(snap, prev2)
    types2 = {e["event_type"] for e in evs2}
    assert "VALIDATED" not in types2, "VALIDATED should NOT re-emit"
    print(f"✓ VALIDATED transition: emitted on flip=True, suppressed on flip=False")


def test_r64_cell_constants_match_fusion_paper():
    """R66's R64 reference must match what R65 deploys (no drift)."""
    from src.data.signals.fusion_paper import (
        FUSION_W_R46, R46_CAD, R46_BPS, R62_CAD, R62_BPS, R62_ZWIN, R62_Z, R62_MF,
        DEFAULT_DECLARED_CAPACITY_USD, VALIDATION_MIN_DAYS as R65_VALIDATION,
    )
    assert FUSION_W_R46 == 0.25
    assert R46_CAD == 5 and R46_BPS == 5.0
    assert R62_CAD == 21 and R62_BPS == 0.0
    assert R62_ZWIN == 30 and R62_Z == 0.5 and R62_MF == 2
    assert DEFAULT_DECLARED_CAPACITY_USD == 5_000_000.0
    assert VALIDATION_MIN_DAYS == R65_VALIDATION, (
        f"R66 validation gate ({VALIDATION_MIN_DAYS}) must match R65 ({R65_VALIDATION})")
    print(f"✓ R64 cell constants match R65 fusion_paper.py exactly")


def test_no_buy_sell_language_in_module():
    """Compliance: no BUY/SELL/ACCUMULATE/AVOID/REDUCE in module source."""
    import re
    # test file is at src/research/validation/tests/test_fusion_paper_tracking_smoke.py
    # module is at src/research/validation/fusion_paper_tracking.py
    src_file = (Path(__file__).resolve().parent.parent
                / "fusion_paper_tracking.py")
    assert src_file.exists(), f"Source not found at {src_file}"
    text = src_file.read_text()
    forbidden = [r"\bBUY\b", r"\bSELL\b", r"\bSTRONG BUY\b",
                 r"\bACCUMULATE\b", r"\bAVOID\b", r"\bREDUCE\b"]
    found = []
    for pat in forbidden:
        for m in re.finditer(pat, text, re.IGNORECASE):
            ctx = text[max(0, m.start() - 25):m.end() + 25].lower()
            # Allow meta-negations + numpy/numerical operations
            if any(neg in ctx for neg in ["no ", "not ", "forbid", "prohibit",
                                            "compliance", ".accumulate"]):
                continue
            found.append((pat, m.start()))
    assert not found, f"Forbidden signal language: {found}"
    print("✓ no forbidden signal language in module")


def main():
    tests = [
        test_imports,
        test_r64_forward_reference_constants,
        test_live_sharpe_basics,
        test_sharpe_gap_status_progression,
        test_detector_fire_status,
        test_capacity_evolution,
        test_validation_countdown,
        test_max_drawdown_pct,
        test_detect_lifecycle_events_book_inception,
        test_detect_lifecycle_events_persistent_high,
        test_detect_lifecycle_events_validated_transition,
        test_r64_cell_constants_match_fusion_paper,
        test_no_buy_sell_language_in_module,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as exc:
            print(f"✗ {t.__name__}: {exc!r}")
            import traceback
            traceback.print_exc()
            failed += 1
    if failed:
        print(f"\n{failed} test(s) FAILED, {passed} passed")
        return 1
    print(f"\n{passed} test(s) passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
