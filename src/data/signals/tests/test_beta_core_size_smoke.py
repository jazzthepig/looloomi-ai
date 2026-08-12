"""
test_beta_core_size_smoke.py — Smoke tests for C3 conviction-size 2D table.

Per §C3-SHIP-SPEC 2026-08-12: pure-function helpers, no live Supabase.
Tests are offline-runnable.

Coverage: 12 checks (per C-series preflight convention).
"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent.parent))
from src.data.signals.beta_core_size import (
    SCHEMA_VERSION,
    INCEPTION_ID,
    DAY_60,
    N_BANDS,
    SIZE_CLIP_MIN,
    SIZE_CLIP_MAX,
    NEUTRAL_SIZE_TABLE,
    active_size_table,
    regime_band,
    signal_band,
    lookup_size,
    compute_size,
    compute_signal_strength,
    drift_from_baseline,
    cell_flip_audit,
    Size2DState,
)


# ── Reference table for MECHANISM tests (S-151) ──────────────────────────────
# The live table is external now (it is the mined edge) and the in-code
# fallback is deliberately uniform, so arithmetic tests — does q_override
# multiply, does the clip engage — have no numbers to bite on. They inject
# this instead.
#
# It is the repo's 2026-08-12 table with BOTH AXES REVERSED: same 25 values,
# correct orientation. Using it here is deliberate — if the un-transposition
# is ever disputed, these tests fail loudly rather than quietly agreeing with
# whatever shape happens to be live.
_REF_TABLE = [
    # signal=1  2     3     4     5
    [0.50, 0.85, 1.05, 1.20, 1.30],   # regime=1 (in-distribution)
    [0.40, 0.75, 0.95, 1.10, 1.25],   # regime=2
    [0.30, 0.65, 0.85, 1.00, 1.20],   # regime=3 (mid-tail)
    [0.20, 0.50, 0.70, 0.95, 1.10],   # regime=4
    [0.10, 0.30, 0.50, 0.80, 1.00],   # regime=5 (out-of-distribution)
]


def _ref():
    from src.data.signals.strategy_params import ParamSet, NS_C3_SIZE
    return ParamSet(NS_C3_SIZE, {
        "size_table_2d": _REF_TABLE, "size_clip_min": 0.0,
        "size_clip_max": 1.3, "nan_regime_band": 3, "nan_signal_band": 1,
    }, version=-1, source="code_fallback")


def _cell(r: int, s: int) -> float:
    return _REF_TABLE[r - 1][s - 1]


def _ok(msg: str) -> None:
    print(f"  ✓ {msg}")


def _fail(msg: str) -> None:
    print(f"  ✗ {msg}")
    sys.exit(1)


# ─────────────────────────────────────────────────────────────────────────────
def test_frozen_consts_and_table_match_spec() -> None:
    """Frozen constants and 5×5 table match §C3 §1 verbatim."""
    if INCEPTION_ID != "c3_size_v1":
        _fail(f"INCEPTION_ID drift: {INCEPTION_ID}")
    if DAY_60 != "2026-11-09":
        _fail(f"DAY_60 drift: {DAY_60}")
    if N_BANDS != 5:
        _fail(f"N_BANDS drift: {N_BANDS}")
    if SIZE_CLIP_MIN != 0.0 or SIZE_CLIP_MAX != 1.3:
        _fail(f"clip range drift: [{SIZE_CLIP_MIN}, {SIZE_CLIP_MAX}]")
    # S-151: the 25 values are NO LONGER ASSERTED HERE, for two reasons.
    #
    # 1. They left the repo — they are the mined edge and now live in
    #    `strategy_params` (Jazz, 2026-08-12).
    # 2. The values this block used to assert were TRANSPOSED ON BOTH AXES,
    #    and asserting them is how the inversion survived: the table and this
    #    test agreed with each other, so every consistency check passed while
    #    both disagreed with the module's stated design.
    #
    # A frozen-value check cannot catch a table that was wrong before it was
    # frozen — freezing preserves it. So this now asserts the PROPERTY:
    # whatever table is active must be correctly oriented.
    from src.data.signals.strategy_params import NS_C3_SIZE, validate
    tbl = active_size_table()
    problems = validate(NS_C3_SIZE, {
        "size_table_2d": [list(r) for r in tbl],
        "size_clip_min": SIZE_CLIP_MIN, "size_clip_max": SIZE_CLIP_MAX,
        "nan_regime_band": 3, "nan_signal_band": 1,
    })
    if problems:
        _fail(f"active size table violates its invariants: {problems}")
    _ok("frozen constants OK; active 5×5 table is correctly oriented")


def test_regime_band_quantizes_correctly() -> None:
    """regime_band(distance) → 1..5 by 0.20 quantile."""
    cases = [
        (0.00, 1), (0.10, 1), (0.19, 1),
        (0.20, 2), (0.30, 2), (0.39, 2),
        (0.40, 3), (0.50, 3), (0.59, 3),
        (0.60, 4), (0.70, 4), (0.79, 4),
        (0.80, 5), (0.90, 5), (1.00, 5),
    ]
    for d, expected in cases:
        if regime_band(d) != expected:
            _fail(f"regime_band({d}) = {regime_band(d)}, expected {expected}")
    # Out-of-bounds handled
    if regime_band(-0.5) != 1:
        _fail("negative distance should clamp to band 1")
    if regime_band(1.5) != 5:
        _fail("distance > 1.0 should clamp to band 5")
    _ok("regime_band: 5 quantiles by 0.20, clamps negative / > 1.0")


def test_regime_band_handles_missing_data_conservatively() -> None:
    """Per I1: None/NaN → mid-tail band 3 (NOT band 1 strong-claim)."""
    if regime_band(None) != 3:
        _fail("None should default to band 3 (conservative)")
    if regime_band(float("nan")) != 3:
        _fail("NaN should default to band 3 (conservative)")
    if regime_band("not-a-number") != 3:
        _fail("non-numeric should default to band 3 (conservative)")
    _ok("regime_band: missing data → band 3 (I1: no silent strong-claim)")


def test_signal_band_quantizes_correctly() -> None:
    """signal_band(strength) → 1..5 by 0.20 quantile."""
    cases = [
        (0.00, 1), (0.10, 1), (0.19, 1),
        (0.20, 2), (0.30, 2), (0.39, 2),
        (0.40, 3), (0.50, 3), (0.59, 3),
        (0.60, 4), (0.70, 4), (0.79, 4),
        (0.80, 5), (0.90, 5), (1.00, 5),
    ]
    for s, expected in cases:
        if signal_band(s) != expected:
            _fail(f"signal_band({s}) = {signal_band(s)}, expected {expected}")
    _ok("signal_band: 5 quantiles by 0.20")


def test_signal_band_handles_missing_data_conservatively() -> None:
    """Per I1: None/NaN → band 1 (very weak signal)."""
    if signal_band(None) != 1:
        _fail("None should default to band 1 (weak, conservative)")
    if signal_band(float("nan")) != 1:
        _fail("NaN should default to band 1")
    if signal_band("nope") != 1:
        _fail("non-numeric should default to band 1")
    _ok("signal_band: missing data → band 1 (no silent strong-claim)")


def test_lookup_size_returns_table_values() -> None:
    """Corner ORDERING, not corner values (S-151).

    This function used to read:

        if lookup_size(1, 5) != 0.10:
            _fail("regime=1, signal=5 (in-dist, strong) should be 0.10")


    i.e. it asserted that the most familiar regime with the strongest signal
    gets the SMALLEST position and the least familiar regime with the weakest
    signal gets the LARGEST. That is the inversion, written down as a
    requirement — and once a wrong value is in a test, it stops being a bug and
    starts being the spec.
    """
    t = active_size_table()
    if lookup_size(1, 5, table=t) < lookup_size(5, 1, table=t):
        _fail("in-distribution + strongest signal sizes SMALLER than "
              "out-of-distribution + weakest — the table is transposed")
    if lookup_size(1, 5, table=t) < lookup_size(1, 1, table=t):
        _fail("stronger signal must never size smaller (regime 1)")
    if lookup_size(5, 5, table=t) > lookup_size(1, 5, table=t):
        _fail("less familiar regime must never size larger (signal 5)")
    _ok("lookup_size: corners ordered correctly (no transpose)")


def test_lookup_size_rejects_out_of_bounds() -> None:
    """Out-of-bounds raises (not silent default)."""
    try:
        lookup_size(0, 3)
        _fail("regime=0 should raise")
    except ValueError:
        pass
    try:
        lookup_size(3, 6)
        _fail("signal=6 should raise")
    except ValueError:
        pass
    _ok("lookup_size: out-of-bounds raises ValueError (no silent default)")


def test_compute_size_with_q_override_default() -> None:
    """q_override=1.0 (C2 offline) → size = table lookup (no clip)."""
    s = compute_size(
        mark_date="2026-09-15",
        vdb_distance=0.50,                                       # regime band 3
        signal_strength=0.50,                                    # signal band 3
        q_override=1.0,
        params=_ref(),
    )
    exp = _cell(3, 3)
    if s.regime_band != 3 or s.signal_band != 3:
        _fail(f"bands should be 3,3: {s.regime_band},{s.signal_band}")
    if s.raw_table_size != exp:
        _fail(f"raw should be {exp}, got {s.raw_table_size}")
    if s.size_final != exp:
        _fail(f"size_final should be {exp}, got {s.size_final}")
    if s.clipped:
        _fail("no clip should be engaged")
    _ok("compute_size: q_override=1.0 → size = table lookup (0.85 center)")


def test_compute_size_with_q_override_zero_zone_no_clip() -> None:
    """q_override=1.3 × low corner (0.10) = 0.13 → no clip."""
    s = compute_size(
        mark_date="2026-09-16",
        vdb_distance=0.10,                                      # regime band 1
        signal_strength=0.90,                                    # signal band 5
        q_override=1.3,
        params=_ref(),
    )
    # (1,5) x 1.3 clips, so exercise the NO-CLIP path on the smallest cell:
    # weakest signal in the least familiar regime, in a correct orientation.
    s2 = compute_size(mark_date="2026-09-16", vdb_distance=0.90,
                      signal_strength=0.10, q_override=1.3, params=_ref())
    exp2 = round(_cell(5, 1) * 1.3, 6)
    if s2.size_final != exp2:
        _fail(f"expected {exp2}, got {s2.size_final}")
    if s2.clipped:
        _fail("clip should NOT be engaged")
    _ok(f"compute_size: q_override=1.3 x smallest cell -> {exp2} (no clip needed)")


def test_compute_size_with_q_override_clamps_to_max() -> None:
    """q_override=1.3 × table 1.30 = 1.69 → clip to 1.30."""
    s = compute_size(
        mark_date="2026-09-17",
        vdb_distance=0.10,                                      # regime band 1 (in-dist)
        signal_strength=0.90,                                    # signal band 5 (strong)
        q_override=1.3,
        params=_ref(),
    )
    raw = round(_cell(1, 5) * 1.3, 6)                            # 1.30 x 1.3 = 1.69
    if s.size_final != 1.3:
        _fail(f"expected clip to 1.3, got {s.size_final}")
    if not s.clipped:
        _fail("clip flag should be True")
    if s.raw_table_size != raw:
        _fail(f"raw should be {raw}, got {s.raw_table_size}")
    _ok(f"compute_size: q_override=1.3 x largest cell -> {raw} -> clip to 1.30")


def test_compute_signal_strength_handles_missing_halves() -> None:
    """Per §C3 §1: signal_strength = 0.5 × R62 + 0.5 × VDB."""
    if compute_signal_strength(0.8, 0.6) != 0.7:
        _fail("0.5×0.8 + 0.5×0.6 should = 0.7")
    if compute_signal_strength(None, 0.6) != 0.6:
        _fail("None + 0.6 should = 0.6 (VDB only)")
    if compute_signal_strength(0.8, None) != 0.8:
        _fail("0.8 + None should = 0.8 (R62 only)")
    if compute_signal_strength(None, None) is not None:
        _fail("None + None should = None")
    if compute_signal_strength(1.5, 0.5) != 0.75:                # unit-clamp
        _fail("values > 1.0 should be clamped to 1.0")
    _ok("compute_signal_strength: handles missing halves + unit-clamp")


def test_drift_audit_fires_above_threshold() -> None:
    """Day 30 guard: drift > 0.30 → tighten range."""
    drift_high = drift_from_baseline([0.5, 0.5, 0.5])           # mean=0.5, drift=0.5
    if drift_high <= 0.30:
        _fail(f"drift should be > 0.30, got {drift_high}")
    drift_low = drift_from_baseline([0.95, 1.05, 1.00])         # mean=1.0, drift=0.0
    if drift_low != 0.0:
        _fail(f"drift should be 0.0, got {drift_low}")
    drift_empty = drift_from_baseline([])
    if drift_empty != 0.0:
        _fail(f"empty distribution → 0.0, got {drift_empty}")
    _ok("drift_audit: fires at >0.30, zero on degenerate inputs")


def test_cell_flip_audit_counts_daily_changes() -> None:
    """Day 45 guard: > 3 flips in 5 days → tighten cells."""
    if cell_flip_audit([1.0]) != 0:
        _fail("single element → 0 flips")
    if cell_flip_audit([1.0, 1.0, 1.0, 1.0]) != 0:
        _fail("same value daily → 0 flips")
    if cell_flip_audit([1.0, 0.85, 1.0, 0.85, 1.0]) != 4:
        _fail("alternating → 4 flips")
    if cell_flip_audit([1.0, 0.85, 0.85, 0.85, 0.85]) != 1:
        _fail("single transition → 1 flip")
    _ok("cell_flip_audit: counts daily transitions, 0 on identical")


# ─────────────────────────────────────────────────────────────────────────────
def main() -> int:
    tests = [
        test_frozen_consts_and_table_match_spec,
        test_regime_band_quantizes_correctly,
        test_regime_band_handles_missing_data_conservatively,
        test_signal_band_quantizes_correctly,
        test_signal_band_handles_missing_data_conservatively,
        test_lookup_size_returns_table_values,
        test_lookup_size_rejects_out_of_bounds,
        test_compute_size_with_q_override_default,
        test_compute_size_with_q_override_zero_zone_no_clip,
        test_compute_size_with_q_override_clamps_to_max,
        test_compute_signal_strength_handles_missing_halves,
        test_drift_audit_fires_above_threshold,
        test_cell_flip_audit_counts_daily_changes,
    ]
    print(f"Running {len(tests)} smoke tests for C3 conviction-size 2D table...")
    for t in tests:
        t()
    print(f"\n{len(tests)}/{len(tests)} smoke tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
