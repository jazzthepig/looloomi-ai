"""
ⓠ REGIME OVERRIDE Enforcer — unit tests
=========================================

First cut (2026-08-06). Per architecture audit finding #2: ⓠ spec was complete
but enforcer was not built. These tests pin the production-shape behavior so
the gate catches regressions as the enforcer is wired into the live book.

Run:  python3 -m tests.test_regime_override_enforcer
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import numpy as np
import pandas as pd

from src.research.beta_core.regime_override_enforcer import (  # noqa: E402
    DEFAULT_PIT_LAG,
    ALLOWED_CAPS,
    BAND_NAMES,
    EXPOSURE_BANDS_V1,
    RegimeOverride,
    apply_regime_override,
    apply_regime_override_series,
    band_for_cap,
    validate_cap,
)


# ── Spec sanity ──────────────────────────────────────────────────────────────
def test_allowed_caps_match_exposure_bands_v1():
    """The allowed cap set is the spec's v1 set, sorted ascending."""
    assert ALLOWED_CAPS == (0.0, 0.5, 1.0, 1.3)


def test_default_pit_lag_is_one_bar():
    """Spec §4: cap applied at day t uses signal from day t-1."""
    assert DEFAULT_PIT_LAG == 1


def test_v1_disables_naked_short():
    """v1 EXPOSURE_BANDS_V1 has CRISIS=0.0 (shelter), NOT -0.3 (naked short).
    Naked-short is a v2 feature requiring borrow-cost model (per m_wo_q docstring)."""
    assert EXPOSURE_BANDS_V1["CRISIS"] == 0.0, (
        "v1 CRISIS must be shelter (0.0), not naked-short (-0.3). "
        "Naked-short requires borrow-cost model — deferred to v2."
    )


# ── RegimeOverride dataclass ─────────────────────────────────────────────────
def test_regime_override_validates_band_and_cap():
    ro = RegimeOverride(as_of_date=pd.Timestamp("2026-08-06"),
                         band="HOT", exposure_cap=1.3, raw_signal=0.12)
    assert ro.band == "HOT"
    assert ro.exposure_cap == 1.3


def test_regime_override_rejects_unknown_band():
    try:
        RegimeOverride(as_of_date=pd.Timestamp("2026-08-06"),
                        band="SUPERNOVA", exposure_cap=1.0, raw_signal=0.0)
    except ValueError as e:
        assert "SUPERNOVA" in str(e)
    else:
        raise AssertionError("unknown band must raise ValueError")


def test_regime_override_rejects_cap_outside_allowed_set():
    try:
        RegimeOverride(as_of_date=pd.Timestamp("2026-08-06"),
                        band="HOT", exposure_cap=2.0, raw_signal=0.12)
    except ValueError as e:
        assert "2.0" in str(e)
    else:
        raise AssertionError("exposure_cap=2.0 must raise (not in v1 allowed set)")


# ── validate_cap ─────────────────────────────────────────────────────────────
def test_validate_cap_accepts_each_allowed_value():
    for c in ALLOWED_CAPS:
        validate_cap(c)  # must not raise


def test_validate_cap_rejects_disallowed():
    for c in (0.1, 0.7, 0.99, 1.1, 1.5, -0.5):
        try:
            validate_cap(c)
        except ValueError:
            pass
        else:
            raise AssertionError(f"validate_cap({c}) must raise ValueError")


# ── band_for_cap ─────────────────────────────────────────────────────────────
def test_band_for_cap_round_trip():
    """Each ALLOWED_CAP maps to ONE of the bands that exposes it (the first in
    EXPOSURE_BANDS_V1 iteration order). For 1.0, both NEUTRAL and EXPANSION
    expose the same cap — round-trip picks whichever comes first."""
    seen_caps: set[float] = set()
    for band, cap in EXPOSURE_BANDS_V1.items():
        if cap in seen_caps:
            continue  # 1.0 is exposed by NEUTRAL first; EXPANSION is a sibling
        seen_caps.add(cap)
        assert band_for_cap(cap) == band, (
            f"band_for_cap({cap}) must return '{band}' (first band that exposes "
            f"this cap in EXPOSURE_BANDS_V1 iteration order)"
        )


def test_band_for_cap_unknown_returns_none():
    assert band_for_cap(0.7) is None
    assert band_for_cap(2.0) is None


# ── apply_regime_override (single day) ───────────────────────────────────────
def _baseline(n_syms: int = 5) -> pd.Series:
    """Equal-weight baseline summing to 1.0 (long-only ① layer shape)."""
    return pd.Series(1.0 / n_syms, index=[f"S{i}" for i in range(n_syms)])


def test_neutral_cap_is_identity():
    """cap=1.0 must pass-through exactly (NEUTRAL band)."""
    w = _baseline(5)
    out = apply_regime_override(w, exposure_cap=1.0)
    np.testing.assert_allclose(out.values, w.values, atol=1e-12)


def test_contraction_halves_book_gross():
    """cap=0.5: total |w| must equal exactly 0.5."""
    w = _baseline(5)
    out = apply_regime_override(w, exposure_cap=0.5)
    assert abs(out.abs().sum() - 0.5) < 1e-9, (
        f"contraction cap=0.5 must produce gross=0.5, got {out.abs().sum()}"
    )


def test_hot_increases_book_gross():
    """cap=1.3: total |w| must equal exactly 1.3 (HOT band)."""
    w = _baseline(5)
    out = apply_regime_override(w, exposure_cap=1.3)
    assert abs(out.abs().sum() - 1.3) < 1e-9


def test_crisis_zeros_the_book():
    """cap=0.0: every weight must be 0 (CRISIS shelter)."""
    w = _baseline(5)
    out = apply_regime_override(w, exposure_cap=0.0)
    np.testing.assert_array_equal(out.values, np.zeros(len(w)))


def test_unequal_baseline_preserves_relative_weights():
    """Scaled+renormalized output must preserve the BASELINE's relative weights."""
    w = pd.Series([0.50, 0.30, 0.15, 0.05], index=["A", "B", "C", "D"])
    for cap in (0.5, 1.0, 1.3):
        out = apply_regime_override(w, exposure_cap=cap)
        # The proportions A:B:C:D must be preserved (0.5:0.3:0.15:0.05)
        ratios_out = out.values / out.sum()
        ratios_in = w.values / w.sum()
        np.testing.assert_allclose(ratios_out, ratios_in, atol=1e-9,
                                    err_msg=f"relative weights must be preserved at cap={cap}")


def test_rejects_non_series_baseline():
    try:
        apply_regime_override([0.5, 0.5], exposure_cap=1.0)
    except TypeError as e:
        assert "pd.Series" in str(e)
    else:
        raise AssertionError("non-Series baseline must raise TypeError")


def test_empty_baseline_returns_empty():
    w = pd.Series(dtype=float)
    out = apply_regime_override(w, exposure_cap=1.0)
    assert len(out) == 0


def test_rejects_disallowed_cap_in_apply():
    try:
        apply_regime_override(_baseline(), exposure_cap=0.7)
    except ValueError as e:
        assert "0.7" in str(e)
    else:
        raise AssertionError("disallowed cap must raise")


# ── apply_regime_override_series (multi-day with PIT) ───────────────────────
def test_pit_lag_uses_prior_day_cap():
    """At day t, the cap used must come from day t-1, not day t.

    Concretely: with pit_lag=1, the output at day t equals
    apply_regime_override(baseline_t, cap_(t-1)).
    """
    dates = pd.date_range("2026-08-01", periods=5, freq="D")
    baseline = pd.DataFrame(
        {f"S{i}": [1.0 / 5] * 5 for i in range(5)},
        index=dates,
    )
    # Cap series: NEUTRAL, NEUTRAL, HOT, NEUTRAL, NEUTRAL.
    # With pit_lag=1, day-2 (index 2) should see cap[1]=1.0 (NEUTRAL), not cap[2]=1.3.
    caps = pd.Series([1.0, 1.0, 1.3, 1.0, 1.0], index=dates, name="cap")

    out = apply_regime_override_series(baseline, caps, pit_lag_bars=1)

    # day-2 (HOT in caps but lagged to day-3 in output)
    assert abs(out.iloc[2].abs().sum() - 1.0) < 1e-9, (
        f"day-2 should use cap[1]=1.0 (NEUTRAL), got gross {out.iloc[2].abs().sum()}"
    )
    # day-3 (HOT cap was at index 2, applied with 1-day lag → index 3)
    assert abs(out.iloc[3].abs().sum() - 1.3) < 1e-9, (
        f"day-3 should use cap[2]=1.3 (HOT, lagged), got gross {out.iloc[3].abs().sum()}"
    )


def test_pit_lag_zero_passes_cap_immediately():
    """pit_lag=0 means cap at day t is used at day t (no lag)."""
    dates = pd.date_range("2026-08-01", periods=3, freq="D")
    baseline = pd.DataFrame(
        {f"S{i}": [1.0 / 5] * 3 for i in range(5)},
        index=dates,
    )
    caps = pd.Series([1.0, 1.3, 0.5], index=dates)

    out = apply_regime_override_series(baseline, caps, pit_lag_bars=0)
    assert abs(out.iloc[0].abs().sum() - 1.0) < 1e-9
    assert abs(out.iloc[1].abs().sum() - 1.3) < 1e-9
    assert abs(out.iloc[2].abs().sum() - 0.5) < 1e-9


def test_nan_cap_passes_baseline_through():
    """If exposure_cap_series is NaN at day t, baseline passes through unchanged."""
    dates = pd.date_range("2026-08-01", periods=3, freq="D")
    baseline = pd.DataFrame(
        {f"S{i}": [1.0 / 5] * 3 for i in range(5)},
        index=dates,
    )
    # NaN at day-2 (signal hasn't started yet) — should pass through unchanged
    caps = pd.Series([1.0, np.nan, 1.3], index=dates)

    out = apply_regime_override_series(baseline, caps, pit_lag_bars=1)
    np.testing.assert_allclose(out.iloc[0].values, baseline.iloc[0].values, atol=1e-12)
    # day-2 cap is NaN → pass-through (baseline sum=1.0)
    np.testing.assert_allclose(out.iloc[1].values, baseline.iloc[1].values, atol=1e-12)


def test_pit_lag_negative_rejected():
    try:
        apply_regime_override_series(
            pd.DataFrame({"A": [1.0]}, index=pd.date_range("2026-08-01", periods=1)),
            pd.Series([1.0], index=pd.date_range("2026-08-01", periods=1)),
            pit_lag_bars=-1,
        )
    except ValueError:
        pass
    else:
        raise AssertionError("pit_lag_bars=-1 must raise")


def test_hysteresis_pattern_matches_m_wo_q():
    """End-to-end: feed a signal through m_wo_q's assign_band_hysteresis, then
    through the enforcer. The cap values in the output must equal the spec's
    EXPOSURE_BANDS_V1 by state."""
    from src.research.validation.m_wo_q_o1_stablecoin_gate import (
        ENTER_HOT, ENTER_CRISIS, EXPOSURE_BANDS_V1,
    )

    # Signal that flips NEUTRAL → CRISIS → NEUTRAL → HOT → NEUTRAL.
    # Each value is a 28-day pct change decimal.
    dates = pd.date_range("2026-08-01", periods=20, freq="D")
    sig = pd.Series([0.0] * 20, index=dates)
    sig.iloc[5] = -0.10   # CRISIS
    sig.iloc[10] = +0.15  # HOT
    sig.iloc[15] = 0.0    # back to NEUTRAL

    _, states = __import__(
        "src.research.validation.m_wo_q_o1_stablecoin_gate",
        fromlist=["assign_band_hysteresis"],
    ).assign_band_hysteresis(sig)

    # CRISIS at index 5 → cap = EXPOSURE_BANDS_V1["CRISIS"] = 0.0
    assert states.iloc[5] == "CRISIS"
    # HOT at index 10 → cap = EXPOSURE_BANDS_V1["HOT"] = 1.3
    assert states.iloc[10] == "HOT"


# ── Driver ───────────────────────────────────────────────────────────────────
TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    p = 0
    for t in TESTS:
        t(); print(f"  ✓ {t.__name__}"); p += 1
    print(f"\n✅ {p}/{len(TESTS)} regime-override-enforcer checks passed")
