"""
test_beta_core_size_hook_smoke.py — Smoke tests for C3 size hook.

Per §C3-SHIP-SPEC 2026-08-12: pure-function hook + I/O wrapper contracts.
Tests are offline-runnable; I/O wrappers use unittest.mock.

Coverage: 11 checks.
"""
import asyncio
import datetime as dt
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent.parent))
from src.data.signals.beta_core_size_hook import (
    compute_size_for_today,
    write_size_row,
    log_size_meta_event,
    c3_hook_config,
    C3HookConfig,
)
from src.data.signals.beta_core_size import (
    INCEPTION_ID,
    DAY_60,
    compute_size,
)


def _ok(msg: str) -> None:
    print(f"  ✓ {msg}")


def _fail(msg: str) -> None:
    print(f"  ✗ {msg}")
    sys.exit(1)


# Reference table for MECHANISM tests (S-151) — the repo's 2026-08-12 table
# with both axes reversed: same 25 values, correct orientation. The live table
# is external now (it is the mined edge) and the in-code fallback is uniform,
# so arithmetic tests have nothing to bite on without this.
_REF_TABLE = [
    [0.50, 0.85, 1.05, 1.20, 1.30],
    [0.40, 0.75, 0.95, 1.10, 1.25],
    [0.30, 0.65, 0.85, 1.00, 1.20],
    [0.20, 0.50, 0.70, 0.95, 1.10],
    [0.10, 0.30, 0.50, 0.80, 1.00],
]


def _ref():
    from src.data.signals.strategy_params import ParamSet, NS_C3_SIZE
    return ParamSet(NS_C3_SIZE, {
        "size_table_2d": _REF_TABLE, "size_clip_min": 0.0,
        "size_clip_max": 1.3, "nan_regime_band": 3, "nan_signal_band": 1,
    }, version=-1, source="code_fallback")


def _cell(r: int, s: int) -> float:
    return _REF_TABLE[r - 1][s - 1]


def test_c3_hook_config_default_is_safe() -> None:
    """First-ship default: c2_q_override_source='live' (will fall back to 1.0 safely)."""
    cfg = c3_hook_config()
    if cfg.inception_id != INCEPTION_ID:
        _fail(f"inception_id drift: {cfg.inception_id}")
    if cfg.c2_q_override_source not in ("live", "default_1.0"):
        _fail(f"unexpected q_override source: {cfg.c2_q_override_source}")
    _ok("c3_hook_config: first-ship default safe (q_override falls back to 1.0)")


def test_compute_size_for_today_default_signal() -> None:
    """No R62 / no VDB signal → bands (3, 1) → size MUST NOT LEVER (S-151).

    This asserted `size_final == 1.20`, which is what the transposed table
    returned with no inputs at all. The hook docstring called it "slightly
    above 1.0" and treated it as the first-ship baseline, so the defect was
    recorded in three places — table, test, prose — and agreed with itself.

    What is actually required is a bound, not a number: with zero information
    the sleeve must not take leverage. Any correctly-oriented table satisfies
    it; every inverted one fails it.
    """
    today = dt.date(2026, 9, 10)
    s = compute_size_for_today(
        today=today, vdb_distance=None, q_override=1.0,
    )
    if s.regime_band != 3 or s.signal_band != 1:
        _fail(f"expected bands (3, 1), got ({s.regime_band}, {s.signal_band})")
    if s.size_final > 1.0 + 1e-9:
        _fail(f"no information produced leverage: size={s.size_final} > 1.0")
    _ok(f"compute_size_for_today: no inputs → bands (3,1) → size {s.size_final} ≤ 1.0")


def test_compute_size_for_today_with_r62_fragility() -> None:
    """R62 fragility + VDB distance → 2D table lookup."""
    today = dt.date(2026, 9, 11)
    s = compute_size_for_today(
        today=today, vdb_distance=0.30,                          # regime band 2
        q_override=1.0,
        r62_detector_fragility=0.50,                            # signal_band 3
        vdb_match_outcome_strength=0.50,                        # signal_band 3
        params=_ref(),
    )
    exp = _cell(2, 3)
    if s.regime_band != 2 or s.signal_band != 3:
        _fail(f"expected bands (2, 3), got ({s.regime_band}, {s.signal_band})")
    if s.size_final != exp:
        _fail(f"expected size {exp}, got {s.size_final}")
    _ok(f"compute_size_for_today: R62+VDB -> 2D table lookup ({exp})")


def test_compute_size_for_today_with_q_override_clamps() -> None:
    """q_override=1.3 × extreme corner → clip to 1.3."""
    today = dt.date(2026, 9, 12)
    s = compute_size_for_today(
        today=today, vdb_distance=0.10,                          # regime band 1
        q_override=1.3,
        r62_detector_fragility=0.90,                            # signal_band 5
        vdb_match_outcome_strength=0.90,
        params=_ref(),
    )
    if s.size_final != 1.3:
        _fail(f"expected clip to 1.3, got {s.size_final}")
    if not s.clipped:
        _fail("clip flag should be True")
    _ok("compute_size_for_today: q_override=1.3 × extreme corner → clip 1.3")


def test_compute_size_for_today_with_q_override_zero_zone() -> None:
    """q_override=0.0 → size = 0.0 regardless of band."""
    today = dt.date(2026, 9, 13)
    s = compute_size_for_today(
        today=today, vdb_distance=0.10, q_override=0.0,
        r62_detector_fragility=0.90, vdb_match_outcome_strength=0.90,
    )
    if s.size_final != 0.0:
        _fail(f"expected size 0.0 (q_override=0.0), got {s.size_final}")
    _ok("compute_size_for_today: q_override=0.0 → size 0.0 (C2 zero_zone dominates)")


def test_write_size_row_shapes_payload() -> None:
    """write_size_row: payload shape matches `beta_core_nav_size` schema."""
    captured = {}

    async def _capture(table, rows):
        captured["table"] = table
        captured["rows"] = rows
        return True

    today = dt.date(2026, 9, 14)
    s = compute_size(today.isoformat(), vdb_distance=0.30,
                     signal_strength=0.50, q_override=1.0)
    with patch("src.api.store.supabase_insert_table", _capture):
        rc = asyncio.run(write_size_row(
            today=today, size_state=s,
            nav=1.05, benchmark_nav=1.04,
            daily_return=0.001, excess_return=0.0005,
        ))
    if not rc:
        _fail("write_size_row should return True on success")
    if captured.get("table") != "beta_core_nav_size":
        _fail(f"wrong table: {captured.get('table')}")
    row = captured["rows"][0]
    required = ["mark_date", "inception_id", "regime_band", "signal_band",
                "raw_table_size", "q_override", "size_final", "clipped",
                "signal_strength", "vdb_distance", "nav", "benchmark_nav",
                "daily_return", "excess_return", "note"]
    for f in required:
        if f not in row:
            _fail(f"missing field: {f}")
    _ok("write_size_row: payload shape correct, 15 fields propagated")


def test_write_size_row_returns_false_on_supabase_false() -> None:
    """Lesson #107: a failed write must return False (not silent True)."""
    async def _fail_to_write(table, rows):
        return False

    today = dt.date(2026, 9, 15)
    s = compute_size(today.isoformat(), vdb_distance=None,
                     signal_strength=None, q_override=1.0)
    with patch("src.api.store.supabase_insert_table", _fail_to_write):
        rc = asyncio.run(write_size_row(
            today=today, size_state=s,
            nav=1.0, benchmark_nav=1.0,
            daily_return=0.0, excess_return=0.0,
        ))
    if rc is not False:
        _fail("Lesson #107: failed write must return False")
    _ok("write_size_row: failed Supabase → False (Lesson #107 honored)")


def test_log_size_meta_event_for_drift_audit() -> None:
    """Day 30 drift_audit event payload shape."""
    captured = {}

    async def _capture(table, rows):
        captured["table"] = table
        captured["rows"] = rows
        return True

    today = dt.date(2026, 9, 16)
    s = compute_size(today.isoformat(), vdb_distance=0.50,
                     signal_strength=0.50, q_override=1.0)
    with patch("src.api.store.supabase_insert_table", _capture):
        rc = asyncio.run(log_size_meta_event(
            today=today, event_type="drift_audit",
            size_state=s, reason="Day 30 drift 0.42 > 0.30 threshold",
            drift_pct=0.42,
        ))
    if not rc:
        _fail("log_size_meta_event should return True")
    row = captured["rows"][0]
    if row["event_type"] != "drift_audit":
        _fail(f"event_type should propagate: {row['event_type']}")
    if row["drift_pct"] != 0.42:
        _fail(f"drift_pct should propagate: {row['drift_pct']}")
    if captured["table"] != "beta_core_nav_size_meta":
        _fail(f"wrong table: {captured['table']}")
    _ok("log_size_meta_event: drift_audit event payload + drift_pct propagate")


def test_log_size_meta_event_for_cell_flip() -> None:
    """Day 45 cell_flip event payload shape."""
    captured = {}

    async def _capture(table, rows):
        captured["rows"] = rows
        return True

    today = dt.date(2026, 9, 17)
    s = compute_size(today.isoformat(), vdb_distance=0.50,
                     signal_strength=0.50, q_override=1.0)
    with patch("src.api.store.supabase_insert_table", _capture):
        rc = asyncio.run(log_size_meta_event(
            today=today, event_type="cell_flip",
            size_state=s, reason="Day 45: 4 cell flips in 5 days > 3 threshold",
            flips_in_window=4,
        ))
    if not rc:
        _fail("log_size_meta_event should return True")
    row = captured["rows"][0]
    if row["flips_in_window"] != 4:
        _fail(f"flips_in_window should propagate: {row['flips_in_window']}")
    _ok("log_size_meta_event: cell_flip event + flips_in_window propagate")


def test_log_size_meta_event_for_size_lookup_failure() -> None:
    """size_lookup_failure event has None size_state (table not loaded)."""
    captured = {}

    async def _capture(table, rows):
        captured["rows"] = rows
        return True

    today = dt.date(2026, 9, 18)
    with patch("src.api.store.supabase_insert_table", _capture):
        rc = asyncio.run(log_size_meta_event(
            today=today, event_type="size_lookup_failure",
            size_state=None, reason="SIZE_TABLE_2D not loaded",
        ))
    if not rc:
        _fail("log_size_meta_event should return True")
    row = captured["rows"][0]
    if row["size_final"] is not None:
        _fail(f"size_lookup_failure should have size_final=None, got {row['size_final']}")
    _ok("log_size_meta_event: size_lookup_failure → size_final=None")


def test_c3_hook_first_ship_safe_with_q_override_zero() -> None:
    """q_override=0.0 (C2 zero_zone) → size=0.0 regardless of signal strength."""
    today = dt.date(2026, 9, 19)
    s = compute_size_for_today(
        today=today, vdb_distance=0.05,                          # regime band 1
        q_override=0.0,
        r62_detector_fragility=0.95,                            # signal_band 5
        vdb_match_outcome_strength=0.95,
    )
    if s.size_final != 0.0:
        _fail(f"q_override=0.0 must dominate, got {s.size_final}")
    _ok("compute_size_for_today: q_override=0.0 dominates regardless of signal")


def main() -> int:
    tests = [
        test_c3_hook_config_default_is_safe,
        test_compute_size_for_today_default_signal,
        test_compute_size_for_today_with_r62_fragility,
        test_compute_size_for_today_with_q_override_clamps,
        test_compute_size_for_today_with_q_override_zero_zone,
        test_write_size_row_shapes_payload,
        test_write_size_row_returns_false_on_supabase_false,
        test_log_size_meta_event_for_drift_audit,
        test_log_size_meta_event_for_cell_flip,
        test_log_size_meta_event_for_size_lookup_failure,
        test_c3_hook_first_ship_safe_with_q_override_zero,
    ]
    print(f"Running {len(tests)} smoke tests for C3 size hook...")
    for t in tests:
        t()
    print(f"\n{len(tests)}/{len(tests)} smoke tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
