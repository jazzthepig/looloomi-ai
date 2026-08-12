"""
test_beta_core_q_hook_smoke.py — Smoke tests for C2 ⓠ hook.

Per §C2-SHIP-SPEC 2026-08-12: pure-function hook, default first-ship behavior
is q_override = 1.0 (VDB matcher offline). Smoke tests cover the PURE path
(compute_q_hook_state) and the contract boundaries (I/O wrappers).

The I/O wrappers (write_q_overlay_row, log_q_meta_event) are tested for
their shape/contract; the live Supabase call is mocked to keep tests offline.

Coverage: 11 checks.
"""
import asyncio
import datetime as dt
import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent.parent))
from src.data.signals.beta_core_q_hook import (
    q_hook_config,
    compute_q_hook_state,
    write_q_overlay_row,
    log_q_meta_event,
    QHookConfig,
)
from src.data.signals.beta_core_q_overlay import (
    INCEPTION_ID,
    ENTER_Q_ZERO_THRESHOLD_DEFAULT,
    EXIT_Q_ZERO_THRESHOLD_DEFAULT,
)


def _ok(msg: str) -> None:
    print(f"  ✓ {msg}")


def _fail(msg: str) -> None:
    print(f"  ✗ {msg}")
    sys.exit(1)


# ─────────────────────────────────────────────────────────────────────────────
def test_q_hook_config_default_is_baseline_only() -> None:
    """First-ship: vdb_matcher_live = False (no behavior change yet)."""
    cfg = q_hook_config()
    if cfg.vdb_matcher_live:
        _fail("first-ship vdb_matcher_live should be False (no behavior change)")
    if cfg.enter_q_zero_thr != ENTER_Q_ZERO_THRESHOLD_DEFAULT:
        _fail(f"enter_q_default mismatch: {cfg.enter_q_zero_thr}")
    if cfg.exit_q_zero_thr != EXIT_Q_ZERO_THRESHOLD_DEFAULT:
        _fail(f"exit_q_default mismatch: {cfg.exit_q_zero_thr}")
    if cfg.inception_id != INCEPTION_ID:
        _fail(f"inception_id mismatch: {cfg.inception_id}")
    _ok("q_hook_config: first-ship default = matcher offline, baseline preserved")


def test_compute_q_hook_state_first_ship_returns_baseline() -> None:
    """First-ship: ANY input → q_override = 1.0 (VDB matcher offline)."""
    today = dt.date(2026, 9, 15)
    s = compute_q_hook_state(
        today=today, gross=0.65, regime="RISK_ON",
        smoothed_distance=0.99,                                  # tail event
        vdb_matcher_live=False,
    )
    if s.q_override != 1.0:
        _fail(f"first-ship should return 1.0, got {s.q_override}")
    if s.trigger != "baseline_vdb_matcher_offline":
        _fail(f"trigger should be 'baseline_vdb_matcher_offline', got {s.trigger}")
    _ok("compute_q_hook_state: first-ship vdb_matcher_live=False → q_override=1.0")


def test_compute_q_hook_state_matcher_live_no_failure_returns_override() -> None:
    """Matcher live + tail event → q_override = 0.0 (zero_zone)."""
    today = dt.date(2026, 9, 16)
    s = compute_q_hook_state(
        today=today, gross=0.65, regime="TIGHTENING",
        smoothed_distance=0.90,                                  # above 0.85
        vdb_matcher_live=True,
    )
    if s.q_override != 0.0:
        _fail(f"tail event should → 0.0, got {s.q_override}")
    if s.trigger != "zero_zone":
        _fail(f"trigger should be 'zero_zone', got {s.trigger}")
    _ok("compute_q_hook_state: matcher live + tail dist → q_override=0.0 (zero_zone)")


def test_compute_q_hook_state_matcher_live_vdb_failure_falls_back() -> None:
    """Matcher live + VDB failure → q_override = 1.0 (never hardcode 0)."""
    today = dt.date(2026, 9, 17)
    s = compute_q_hook_state(
        today=today, gross=0.65, regime="RISK_OFF",
        smoothed_distance=float("nan"),                         # VDB failure
        vdb_matcher_live=True, vdb_failure=True,
    )
    if s.q_override != 1.0:
        _fail(f"VDB failure must → 1.0, got {s.q_override}")
    if not s.vdb_failure:
        _fail("vdb_failure flag should be True")
    _ok("compute_q_hook_state: matcher live + VDB failure → q_override=1.0 (safely)")


def test_compute_q_hook_state_matcher_live_baseline_band() -> None:
    """Matcher live + low distance → q_override = 1.0 (one_zone, baseline)."""
    today = dt.date(2026, 9, 18)
    s = compute_q_hook_state(
        today=today, gross=0.65, regime="GOLDILOCKS",
        smoothed_distance=0.30,                                  # below 0.65
        vdb_matcher_live=True,
    )
    if s.q_override != 1.0:
        _fail(f"low distance should → 1.0, got {s.q_override}")
    if s.trigger != "one_zone":
        _fail(f"trigger should be 'one_zone', got {s.trigger}")
    _ok("compute_q_hook_state: matcher live + low dist → q_override=1.0 (one_zone)")


def test_compute_q_hook_state_matcher_live_mid_band_with_up_signal() -> None:
    """Matcher live + mid-band + up signal → q_override = 1.3 (up_zone)."""
    today = dt.date(2026, 9, 19)
    s = compute_q_hook_state(
        today=today, gross=0.65, regime="RISK_ON",
        smoothed_distance=0.75,                                  # between 0.65 and 0.85
        enter_q_up_frac=0.6,                                     # 3/5 = 0.6 > 0.5
        vdb_matcher_live=True,
    )
    if s.q_override != 1.3:
        _fail(f"mid-band with up signal should → 1.3, got {s.q_override}")
    if s.trigger != "up_zone":
        _fail(f"trigger should be 'up_zone', got {s.trigger}")
    _ok("compute_q_hook_state: matcher live + mid-band + up → q_override=1.3 (up_zone)")


def test_compute_q_hook_state_never_exceeds_allowed_set() -> None:
    """The output q_override must always be in ALLOWED_Q = {0.0, 0.5, 1.0, 1.3}."""
    import math
    today = dt.date(2026, 9, 20)
    for dist in [0.0, 0.1, 0.3, 0.5, 0.7, 0.83, 0.85, 0.92, 0.99, float("nan")]:
        for up_frac in [0.0, 0.4, 0.6, 1.0]:
            s = compute_q_hook_state(
                today=today, gross=0.65, regime=None,
                smoothed_distance=dist, enter_q_up_frac=up_frac,
                vdb_matcher_live=True,
            )
            if s.q_override not in (0.0, 0.5, 1.0, 1.3):
                _fail(f"q_override={s.q_override} not in ALLOWED_Q for dist={dist}, up={up_frac}")
    _ok("compute_q_hook_state: q_override ∈ {0.0, 0.5, 1.0, 1.3} across all inputs")


def test_write_q_overlay_row_shapes_payload_correctly() -> None:
    """write_q_overlay_row: payload shape matches `beta_core_nav_q` schema."""
    captured = {}

    async def _capture(table, rows):
        captured["table"] = table
        captured["rows"] = rows
        return True

    from src.data.signals.beta_core_q_overlay import QOverrideState
    today = dt.date(2026, 9, 21)
    q_state = QOverrideState(
        mark_date=today, q_override=0.5,
        vdb_distance=0.75, smoothed_distance=0.75,
        enter_q_zero_thr=0.85, exit_q_zero_thr=0.65,
        trigger="half_zone", vdb_failure=False,
    )
    with patch("src.api.store.supabase_insert_table", _capture):
        rc = asyncio.run(write_q_overlay_row(
            today=today, q_state=q_state,
            baseline_gross=0.65, nav=1.05, benchmark_nav=1.04,
            daily_return=0.001, excess_return=0.0005,
        ))
    if not rc:
        _fail("write_q_overlay_row should return True on success")
    if captured.get("table") != "beta_core_nav_q":
        _fail(f"wrong table: {captured.get('table')}")
    row = captured["rows"][0]
    required = ["mark_date", "inception_id", "q_override", "vdb_distance",
                "enter_q_zero_thr", "exit_q_zero_thr", "baseline_gross",
                "gross_total", "nav", "benchmark_nav", "daily_return",
                "excess_return", "note"]
    for f in required:
        if f not in row:
            _fail(f"write_q_overlay_row missing field: {f}")
    if row["gross_total"] != round(0.65 * 0.5, 6):
        _fail(f"gross_total = baseline × q_override: got {row['gross_total']}")
    _ok(f"write_q_overlay_row: payload shape correct, gross_total={row['gross_total']}")


def test_write_q_overlay_row_returns_false_on_supabase_false() -> None:
    """Write fails → returns False (NOT a silent True). Per Lesson #107."""
    async def _fail_to_write(table, rows):
        return False

    from src.data.signals.beta_core_q_overlay import QOverrideState
    today = dt.date(2026, 9, 22)
    q_state = QOverrideState(
        mark_date=today, q_override=1.0,
        vdb_distance=None, smoothed_distance=None,
        enter_q_zero_thr=0.85, exit_q_zero_thr=0.65,
        trigger="baseline_vdb_matcher_offline", vdb_failure=False,
    )
    with patch("src.api.store.supabase_insert_table", _fail_to_write):
        rc = asyncio.run(write_q_overlay_row(
            today=today, q_state=q_state,
            baseline_gross=0.65, nav=1.0, benchmark_nav=1.0,
            daily_return=0.0, excess_return=0.0,
        ))
    if rc is not False:
        _fail("Lesson #107: failed write must return False (not silent True)")
    _ok("write_q_overlay_row: failed Supabase insert → returns False (Lesson #107)")


def test_log_q_meta_event_shape() -> None:
    """log_q_meta_event: payload matches `beta_core_nav_q_meta` schema."""
    captured = {}

    async def _capture(table, rows):
        captured["table"] = table
        captured["rows"] = rows
        return True

    from src.data.signals.beta_core_q_overlay import QOverrideState
    today = dt.date(2026, 9, 23)
    q_state = QOverrideState(
        mark_date=today, q_override=1.0,
        vdb_distance=None, smoothed_distance=None,
        enter_q_zero_thr=0.85, exit_q_zero_thr=0.65,
        trigger="baseline_vdb_failure", vdb_failure=True,
    )
    with patch("src.api.store.supabase_insert_table", _capture):
        rc = asyncio.run(log_q_meta_event(
            today=today, event_type="vdb_failure",
            q_state=q_state, reason="match RPC timeout",
        ))
    if not rc:
        _fail("log_q_meta_event should return True on success")
    if captured.get("table") != "beta_core_nav_q_meta":
        _fail(f"wrong table: {captured.get('table')}")
    row = captured["rows"][0]
    if row["event_type"] != "vdb_failure":
        _fail(f"event_type should propagate: {row['event_type']}")
    if row["reason"] != "match RPC timeout":
        _fail(f"reason should propagate: {row['reason']}")
    _ok("log_q_meta_event: payload shape correct, event_type + reason propagate")


def test_q_hook_state_first_ship_preserves_c1_baseline() -> None:
    """First-ship invariant: with matcher offline, q_override=1.0 → gross_total == baseline_gross."""
    today = dt.date(2026, 9, 24)
    gross = 0.65
    s = compute_q_hook_state(
        today=today, gross=gross, regime="ANY",
        smoothed_distance=0.99,                                  # extreme tail
        vdb_matcher_live=False,
    )
    if s.q_override != 1.0:
        _fail(f"first-ship must hold q_override=1.0, got {s.q_override}")
    if gross * s.q_override != gross:
        _fail("gross_total = baseline × 1.0 must equal baseline")
    _ok("first-ship safety: gross_total = baseline (no behavior change yet)")


# ─────────────────────────────────────────────────────────────────────────────
def main() -> int:
    tests = [
        test_q_hook_config_default_is_baseline_only,
        test_compute_q_hook_state_first_ship_returns_baseline,
        test_compute_q_hook_state_matcher_live_no_failure_returns_override,
        test_compute_q_hook_state_matcher_live_vdb_failure_falls_back,
        test_compute_q_hook_state_matcher_live_baseline_band,
        test_compute_q_hook_state_matcher_live_mid_band_with_up_signal,
        test_compute_q_hook_state_never_exceeds_allowed_set,
        test_write_q_overlay_row_shapes_payload_correctly,
        test_write_q_overlay_row_returns_false_on_supabase_false,
        test_log_q_meta_event_shape,
        test_q_hook_state_first_ship_preserves_c1_baseline,
    ]
    print(f"Running {len(tests)} smoke tests for C2 ⓠ hook...")
    for t in tests:
        t()
    print(f"\n{len(tests)}/{len(tests)} smoke tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
