"""
CIS Drift Detector — detection logic tests
============================================

The CLI requires live Supabase; these tests cover the pure detection logic so the
gate catches regressions without a DB. The HYPE case (40.9 C → 27.3 D, 23d) is the
canonical fixture and must trigger CRITICAL.

Run:  python3 -m tests.test_cis_drift_detector
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from scripts.cis_drift_detector import (  # noqa: E402
    detect_drift, grade_for, signal_class,
)


class Args:
    """Namespace stub matching argparse output."""
    def __init__(self, drop_7d=5.0, drop_30d=10.0, sustain_days=7):
        self.drop_7d = drop_7d
        self.drop_30d = drop_30d
        self.sustain_days = sustain_days


# ── grade_for + signal_class ─────────────────────────────────────────────────
def test_grade_for_uses_cis_v4_thresholds():
    assert grade_for(90) == "A+"
    assert grade_for(85) == "A+"
    assert grade_for(84.9) == "A"
    assert grade_for(75) == "A"
    assert grade_for(65) == "B+"
    assert grade_for(55) == "B"
    assert grade_for(45) == "C+"
    assert grade_for(35) == "C"
    assert grade_for(25) == "D"
    assert grade_for(0) == "F"


def test_signal_class_buckets():
    assert signal_class("STRONG OUTPERFORM") == "OUTPERFORM"
    assert signal_class("OUTPERFORM") == "OUTPERFORM"
    assert signal_class("NEUTRAL") == "NEUTRAL"
    assert signal_class("UNDERPERFORM") == "UNDERPERFORM"
    assert signal_class("UNDERWEIGHT") == "UNDERPERFORM"
    assert signal_class(None) == "UNKNOWN"
    assert signal_class("") == "UNKNOWN"


# ── HYPE case (the canonical fixture) ────────────────────────────────────────
HYPE_HISTORY = [
    # 23 days ago: C, NEUTRAL
    {"symbol": "HYPE", "as_of_date": "2026-07-08", "cis_score": 40.9,
     "grade": "C", "signal": "NEUTRAL"},
    {"symbol": "HYPE", "as_of_date": "2026-07-16", "cis_score": 35.5,
     "grade": "C", "signal": "UNDERPERFORM"},
    # tier drop C → D
    {"symbol": "HYPE", "as_of_date": "2026-07-23", "cis_score": 33.2,
     "grade": "D", "signal": "UNDERPERFORM"},
    {"symbol": "HYPE", "as_of_date": "2026-07-31", "cis_score": 27.3,
     "grade": "D", "signal": "UNDERWEIGHT"},
]


def test_hype_case_triggers_critical():
    """HYPE: 40.9→27.3 over 23d, C→D tier drop, NEUTRAL→UNDERWEIGHT flip.
    Should fire ≥2 signals → CRITICAL."""
    findings = detect_drift(HYPE_HISTORY, Args())
    hype = [f for f in findings if f["symbol"] == "HYPE"]
    assert len(hype) == 1, f"HYPE must be flagged, got {[f['symbol'] for f in findings]}"
    f = hype[0]
    assert f["severity"] == "CRITICAL", f"HYPE must be CRITICAL, got {f['severity']}"
    assert f["drop_30d"] >= 10, f"HYPE 30d drop should be ≥10, got {f['drop_30d']}"
    assert f["tier_drops_30d"] >= 1, "HYPE had a C→D tier drop"
    assert f["signal_flip_7d"] is True, "HYPE flipped to UNDERWEIGHT class"
    assert f["consecutive_underweight_days"] >= 1
    assert any("30d_drop" in s for s in f["signals_fired"])
    assert any("tier_drop" in s for s in f["signals_fired"])


def test_stable_asset_not_flagged():
    """An asset holding steady → no findings."""
    history = [
        {"symbol": "STABLE", "as_of_date": "2026-07-01", "cis_score": 78.0,
         "grade": "A", "signal": "STRONG OUTPERFORM"},
        {"symbol": "STABLE", "as_of_date": "2026-07-31", "cis_score": 77.5,
         "grade": "A", "signal": "STRONG OUTPERFORM"},
    ]
    findings = detect_drift(history, Args())
    assert findings == [], f"STABLE must not be flagged, got {findings}"


def test_small_drop_below_threshold_not_flagged():
    """3-point drop over 30d is below the 10-point default threshold."""
    history = [
        {"symbol": "SOFT", "as_of_date": "2026-07-01", "cis_score": 70.0,
         "grade": "B+", "signal": "OUTPERFORM"},
        {"symbol": "SOFT", "as_of_date": "2026-07-31", "cis_score": 67.0,
         "grade": "B+", "signal": "OUTPERFORM"},
    ]
    findings = detect_drift(history, Args())
    assert findings == [], f"3-pt drop must NOT be flagged, got {findings}"


def test_severe_drop_single_signal_is_high_not_critical():
    """One big 30d drop, no tier drop, no flip → HIGH (not CRITICAL)."""
    history = [
        {"symbol": "PLUNGE", "as_of_date": "2026-07-01", "cis_score": 80.0,
         "grade": "A", "signal": "OUTPERFORM"},
        # score collapsed by 25 but stayed in same tier; no flip (still OUTPERFORM-class)
        {"symbol": "PLUNGE", "as_of_date": "2026-07-31", "cis_score": 55.0,
         "grade": "B", "signal": "OUTPERFORM"},
    ]
    findings = detect_drift(history, Args())
    f = [x for x in findings if x["symbol"] == "PLUNGE"][0]
    # 25-point drop alone → CRITICAL via the 30d>=20 rule
    assert f["severity"] == "CRITICAL", f"25-pt drop should trip CRITICAL, got {f['severity']}"


def test_sustained_underweight_alone_is_high():
    """10 days of UNDERWEIGHT with no score drop → single signal → HIGH."""
    history = [
        {"symbol": "SUSTAIN", "as_of_date": f"2026-07-{i:02d}",
         "cis_score": 30.0, "grade": "D", "signal": "UNDERWEIGHT"}
        for i in range(1, 11)
    ]
    findings = detect_drift(history, Args(sustain_days=7))
    f = [x for x in findings if x["symbol"] == "SUSTAIN"][0]
    assert f["severity"] == "HIGH"
    assert any("sustained_underweight" in s for s in f["signals_fired"])


def test_tier_drop_only_is_high():
    """C → D across 30d, signal class unchanged (NEUTRAL → NEUTRAL), score drop
    below threshold → only tier_drop fires → HIGH (single signal)."""
    history = [
        {"symbol": "TIER", "as_of_date": "2026-07-01", "cis_score": 36.0,
         "grade": "C", "signal": "NEUTRAL"},
        {"symbol": "TIER", "as_of_date": "2026-07-31", "cis_score": 33.0,
         "grade": "D", "signal": "NEUTRAL"},  # signal class unchanged
    ]
    findings = detect_drift(history, Args())
    f = [x for x in findings if x["symbol"] == "TIER"][0]
    assert f["tier_drops_30d"] == 1
    # single signal (tier_drop only) → HIGH
    assert f["severity"] == "HIGH"


def test_findings_sorted_critical_first():
    """Severity sort: CRITICAL before HIGH, ties broken by 30d drop desc."""
    history = HYPE_HISTORY + [
        # minor stuff → HIGH
        {"symbol": "MINOR", "as_of_date": "2026-07-25", "cis_score": 60.0,
         "grade": "B", "signal": "OUTPERFORM"},
        {"symbol": "MINOR", "as_of_date": "2026-07-31", "cis_score": 50.0,
         "grade": "C+", "signal": "NEUTRAL"},
    ]
    findings = detect_drift(history, Args())
    sevs = [f["severity"] for f in findings]
    # HYPE first (CRITICAL), MINOR second (HIGH)
    assert sevs[0] == "CRITICAL"


def test_multi_symbol_isolation():
    """Detector doesn't bleed state across symbols."""
    history = HYPE_HISTORY + [
        {"symbol": "QUIET", "as_of_date": "2026-07-01", "cis_score": 78.0,
         "grade": "A", "signal": "STRONG OUTPERFORM"},
        {"symbol": "QUIET", "as_of_date": "2026-07-31", "cis_score": 78.5,
         "grade": "A", "signal": "STRONG OUTPERFORM"},
    ]
    findings = detect_drift(history, Args())
    quiet = [f for f in findings if f["symbol"] == "QUIET"]
    assert quiet == [], "QUIET must not be flagged alongside HYPE"


def test_short_history_skipped():
    """A single-row history per symbol can't be analyzed (no anchor)."""
    history = [
        {"symbol": "NEW", "as_of_date": "2026-07-31", "cis_score": 50.0,
         "grade": "C+", "signal": "NEUTRAL"},
    ]
    findings = detect_drift(history, Args())
    assert findings == [], "Single-row symbols must be skipped (no anchor)"


# ── Driver ───────────────────────────────────────────────────────────────────
TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    p = 0
    for t in TESTS:
        t(); print(f"  ✓ {t.__name__}"); p += 1
    print(f"\n✅ {p}/{len(TESTS)} cis-drift-detector checks passed")
