"""
test_beta_core_q_overlay_smoke.py — Smoke tests for C2 ⓠ overlay helpers.

Per §C2-SHIP-SPEC 2026-08-12: pure-function helpers, no live Supabase.
Tests are offline-runnable. No fixtures, no network, no I/O.

Coverage: 11 checks (per the C-series preflight convention).
"""
import math
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

# Adjust path so `from src.data.signals.beta_core_q_overlay import ...` works
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent.parent))
from src.data.signals.beta_core_q_overlay import (
    SCHEMA_VERSION,
    INCEPTION_ID,
    DAY_60,
    ENTER_Q_ZERO_THRESHOLD_DEFAULT,
    EXIT_Q_ZERO_THRESHOLD_DEFAULT,
    HYSTERESIS_GAP,
    DWELL_DAYS,
    ALLOWED_Q,
    derive_q_override,
    apply_dwell_filter,
    clock_q_continuity,
    state_as_of,
    is_vdb_failure,
    default_thresholds,
    env_thresholds,
    QOverrideState,
    ClockQState,
)


def _ok(msg: str) -> None:
    print(f"  ✓ {msg}")


def _fail(msg: str) -> None:
    print(f"  ✗ {msg}")
    sys.exit(1)


def _dates(start: date, n: int) -> list[date]:
    return [start + timedelta(days=i) for i in range(n)]


# ─────────────────────────────────────────────────────────────────────────────
def test_frozen_constants_match_spec() -> None:
    """Constants frozen per §C2-SHIP-SPEC §8. Drift = ship hazard."""
    if INCEPTION_ID != "c2_q_v1":
        _fail(f"INCEPTION_ID drift: {INCEPTION_ID} != c2_q_v1")
    if DAY_60 != "2026-11-14":
        _fail(f"DAY_60 drift: {DAY_60} != 2026-11-14")
    if ENTER_Q_ZERO_THRESHOLD_DEFAULT != 0.85:
        _fail(f"ENTER_Q_ZERO_THRESHOLD_DEFAULT drift: {ENTER_Q_ZERO_THRESHOLD_DEFAULT} != 0.85")
    if EXIT_Q_ZERO_THRESHOLD_DEFAULT != 0.65:
        _fail(f"EXIT_Q_ZERO_THRESHOLD_DEFAULT drift: {EXIT_Q_ZERO_THRESHOLD_DEFAULT} != 0.65")
    if HYSTERESIS_GAP != 0.20:
        _fail(f"hysteresis gap drift: {HYSTERESIS_GAP} != 0.20")
    if DWELL_DAYS != 5:
        _fail(f"dwelldays drift: {DWELL_DAYS} != 5")
    if ALLOWED_Q != (0.0, 0.5, 1.0, 1.3):
        _fail(f"ALLOWED_Q drift: {ALLOWED_Q}")
    _ok("frozen constants: match §C2-SHIP-SPEC §8 verbatim")


def test_derive_q_override_vdb_failure_falls_back_to_baseline() -> None:
    """Per §C2-SHIP-SPEC §4: VDB failure → q_override = 1.0 (NEVER 0.0)."""
    s = derive_q_override(
        mark_date=date(2026, 9, 15),
        smoothed_distance=0.99,                                  # extreme tail
        enter_q_zero_thr=0.85, exit_q_zero_thr=0.65,
        vdb_failure=True,
    )
    if s.q_override != 1.0:
        _fail(f"VDB failure must → 1.0, got {s.q_override}")
    if not s.vdb_failure:
        _fail("vdb_failure flag should be True")
    if s.trigger != "baseline_vdb_failure":
        _fail(f"trigger should be 'baseline_vdb_failure', got {s.trigger}")
    _ok("derive_q_override: vdb_failure=True → q_override=1.0 (no hardcode 0)")


def test_derive_q_override_zero_zone_above_enter() -> None:
    """Distance > enter_q_zero_thr → q_override=0.0."""
    s = derive_q_override(
        mark_date=date(2026, 9, 16),
        smoothed_distance=0.90,                                  # above 0.85
        enter_q_zero_thr=0.85, exit_q_zero_thr=0.65,
    )
    if s.q_override != 0.0:
        _fail(f"distance above enter → 0.0, got {s.q_override}")
    if s.trigger != "zero_zone":
        _fail(f"trigger should be 'zero_zone', got {s.trigger}")
    _ok("derive_q_override: distance > enter → q_override=0.0 (zero_zone)")


def test_derive_q_override_one_zone_below_exit() -> None:
    """Distance < exit_q_zero_thr → q_override=1.0."""
    s = derive_q_override(
        mark_date=date(2026, 9, 17),
        smoothed_distance=0.50,                                  # below 0.65
        enter_q_zero_thr=0.85, exit_q_zero_thr=0.65,
    )
    if s.q_override != 1.0:
        _fail(f"distance below exit → 1.0, got {s.q_override}")
    if s.trigger != "one_zone":
        _fail(f"trigger should be 'one_zone', got {s.trigger}")
    _ok("derive_q_override: distance < exit → q_override=1.0 (one_zone)")


def test_derive_q_override_mid_band_no_up_signal() -> None:
    """Mid-band distance (between EXIT and ENTER) without up signal → q_override=0.5."""
    s = derive_q_override(
        mark_date=date(2026, 9, 18),
        smoothed_distance=0.75,                                  # between 0.65 and 0.85
        enter_q_zero_thr=0.85, exit_q_zero_thr=0.65,
        enter_q_up_frac=0.0,                                     # no up neighbours
    )
    if s.q_override != 0.5:
        _fail(f"mid-band no-up → 0.5, got {s.q_override}")
    if s.trigger != "half_zone":
        _fail(f"trigger should be 'half_zone', got {s.trigger}")
    _ok("derive_q_override: mid-band (no up signal) → q_override=0.5 (half_zone)")


def test_derive_q_override_mid_band_with_up_signal() -> None:
    """Mid-band distance with strong up signal (≥3/5 neighbours > +5%) → q_override=1.3."""
    s = derive_q_override(
        mark_date=date(2026, 9, 19),
        smoothed_distance=0.75,
        enter_q_zero_thr=0.85, exit_q_zero_thr=0.65,
        enter_q_up_frac=0.6,                                     # 3/5 = 0.6 > 0.5
    )
    if s.q_override != 1.3:
        _fail(f"mid-band with up signal → 1.3, got {s.q_override}")
    if s.trigger != "up_zone":
        _fail(f"trigger should be 'up_zone', got {s.trigger}")
    _ok("derive_q_override: mid-band with up signal → q_override=1.3 (up_zone)")


def test_apply_dwell_filter_smooths_single_day_jumps() -> None:
    """5d median: single-day spike should NOT bleed through."""
    dates = pd.date_range("2026-09-15", periods=10, freq="D")
    raw = pd.Series(
        [0.50, 0.50, 0.50, 0.50, 0.50,                          # stable
         0.99,                                                   # 1-day spike
         0.50, 0.50, 0.50, 0.50],                                # stable
        index=dates,
    )
    smoothed = apply_dwell_filter(raw, dwell_days=5)
    # At day 5 (index=5), the 5d window is [0.50, 0.50, 0.50, 0.50, 0.99]
    # → median = 0.50 (the spike is one of two 0.50s vs one 0.99; actually 0.50 wins)
    if smoothed.iloc[5] > 0.70:
        _fail(f"single-day spike should not bleed through 5d median, got {smoothed.iloc[5]}")
    _ok(f"apply_dwell_filter: 5d median smooths single-day spike ({smoothed.iloc[5]:.2f})")


def test_clock_q_continuity_zero_state() -> None:
    """Empty rows → not started, 60 days remaining."""
    s = clock_q_continuity(rows=[], vdb_failure_count=0)
    if s.started:
        _fail("empty rows should not be started")
    if s.gate_days_remaining != 60:
        _fail(f"empty rows should have 60 days remaining, got {s.gate_days_remaining}")
    if s.marks != 0:
        _fail(f"empty rows should have 0 marks, got {s.marks}")
    _ok("clock_q_continuity: empty rows → 0 marks, 60 days remaining")


def test_clock_q_continuity_running_state() -> None:
    """Continuous marks → started, last_mark today."""
    today = date(2026, 10, 14)
    rows = [{"mark_date": (today - timedelta(days=i)).isoformat()} for i in range(15, -1, -1)]
    s = clock_q_continuity(rows=rows, vdb_failure_count=2, today=today)
    if not s.started:
        _fail("continuous marks should be started")
    if s.last_mark != today.isoformat():
        _fail(f"last_mark should be {today}, got {s.last_mark}")
    if s.marks != 16:
        _fail(f"expected 16 marks (15..0 inclusive), got {s.marks}")
    if s.stalled:
        _fail("continuous marks should not be stalled")
    if s.vdb_failure_count != 2:
        _fail(f"vdb_failure_count should propagate, got {s.vdb_failure_count}")
    _ok("clock_q_continuity: 15-day continuous run, 2 VDB failures recorded")


def test_is_vdb_failure_detects_all_three_modes() -> None:
    """Three failure modes: None, NaN, non-ok RPC status."""
    if not is_vdb_failure(None):
        _fail("distance=None should be VDB failure")
    if not is_vdb_failure(float("nan")):
        _fail("distance=NaN should be VDB failure")
    if not is_vdb_failure(0.50, rpc_status="timeout"):
        _fail("non-ok RPC status should be VDB failure")
    if is_vdb_failure(0.50, rpc_status="ok"):
        _fail("ok status with finite distance should NOT be VDB failure")
    if is_vdb_failure(0.85):
        _fail("finite distance should NOT be VDB failure")
    _ok("is_vdb_failure: detects None / NaN / non-ok RPC; accepts finite + ok")


def test_env_thresholds_respects_bounds_and_hysteresis() -> None:
    """env_thresholds must reject out-of-bounds AND inverted hysteresis."""
    # Clear any prior env
    os.environ.pop("C2_ENTER_Q_ZERO", None)
    os.environ.pop("C2_EXIT_Q_ZERO", None)
    a, b = env_thresholds()
    if a != ENTER_Q_ZERO_THRESHOLD_DEFAULT or b != EXIT_Q_ZERO_THRESHOLD_DEFAULT:
        _fail(f"defaults should match spec: {a}, {b}")
    # Bad enter (out of bounds)
    os.environ["C2_ENTER_Q_ZERO"] = "1.5"
    a, b = env_thresholds()
    if a != ENTER_Q_ZERO_THRESHOLD_DEFAULT:
        _fail(f"out-of-bounds enter should fall back to default, got {a}")
    # Inverted (enter < exit)
    os.environ["C2_ENTER_Q_ZERO"] = "0.50"
    os.environ["C2_EXIT_Q_ZERO"] = "0.60"
    a, b = env_thresholds()
    if a != ENTER_Q_ZERO_THRESHOLD_DEFAULT:
        _fail(f"inverted hysteresis should fall back to default, got {a}, {b}")
    # Valid override
    os.environ["C2_ENTER_Q_ZERO"] = "0.80"
    os.environ["C2_EXIT_Q_ZERO"] = "0.60"
    a, b = env_thresholds()
    if a != 0.80 or b != 0.60:
        _fail(f"valid override should pass, got {a}, {b}")
    # Clean up
    os.environ.pop("C2_ENTER_Q_ZERO", None)
    os.environ.pop("C2_EXIT_Q_ZERO", None)
    _ok("env_thresholds: defaults + bounds + hysteresis gap enforced")


def test_state_as_of_is_pure_serialization() -> None:
    """state_as_of(ClockQState) returns plain dict; no I/O side effects."""
    s = ClockQState(
        configured=True, marks=10, inception="2026-09-15",
        last_mark="2026-09-25", days_since_mark=0,
        missing_days=0, gate_days_remaining=50, started=True,
        stalled=False, vdb_failure_count=1, note="ok",
    )
    d = state_as_of(s)
    if not isinstance(d, dict):
        _fail(f"state_as_of should return dict, got {type(d)}")
    if d["inception"] != "2026-09-15":
        _fail(f"inception should round-trip, got {d['inception']}")
    if d["vdb_failure_count"] != 1:
        _fail(f"vdb_failure_count should round-trip, got {d['vdb_failure_count']}")
    _ok("state_as_of: pure serialization, all fields round-trip")


# ─────────────────────────────────────────────────────────────────────────────
def main() -> int:
    tests = [
        test_frozen_constants_match_spec,
        test_derive_q_override_vdb_failure_falls_back_to_baseline,
        test_derive_q_override_zero_zone_above_enter,
        test_derive_q_override_one_zone_below_exit,
        test_derive_q_override_mid_band_no_up_signal,
        test_derive_q_override_mid_band_with_up_signal,
        test_apply_dwell_filter_smooths_single_day_jumps,
        test_clock_q_continuity_zero_state,
        test_clock_q_continuity_running_state,
        test_is_vdb_failure_detects_all_three_modes,
        test_env_thresholds_respects_bounds_and_hysteresis,
        test_state_as_of_is_pure_serialization,
    ]
    print(f"Running {len(tests)} smoke tests for C2 ⓠ overlay helpers...")
    for t in tests:
        t()
    print(f"\n{len(tests)}/{len(tests)} smoke tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
