#!/usr/bin/env python3
"""
test_cis_history_provider.py — T27 validation
=============================================
Validates that CISHistoryProvider can fetch historical CIS scores from Supabase
and that all gate logic works correctly.

Run from repo root:
    python3 scripts/test_cis_history_provider.py

Requires SUPABASE_URL + SUPABASE_SERVICE_KEY (or SUPABASE_KEY) in environment,
or a .env file at repo root.
"""

import os
import sys
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Load .env if present
_env = Path(__file__).parent.parent / ".env"
if _env.exists():
    for line in _env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

# Allow running from repo root without install
sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(level=logging.WARNING)

from src.data.cis.cis_history_provider import CISHistoryProvider, get_provider

# ── Test symbols ──────────────────────────────────────────────────────────────
# Use assets that were in the 365-day reconstruction (T26)
TEST_SYMBOLS = ["BTC", "ETH", "SOL"]

REGIME_THRESHOLDS = {
    "RISK_ON":     45.0,
    "GOLDILOCKS":  45.0,
    "EASING":      48.0,
    "TIGHTENING":  52.0,
    "RISK_OFF":    60.0,
    "STAGFLATION": 58.0,
}


def _check(label: str, condition: bool, detail: str = ""):
    if condition:
        print(f"  ✓ {label}")
    else:
        print(f"  ✗ FAIL: {label}" + (f" — {detail}" if detail else ""))
    return condition


def test_provider_init():
    print("\n[1] Provider initialisation")
    p = CISHistoryProvider()
    _check("CISHistoryProvider instantiated", p is not None)
    singleton = get_provider()
    _check("get_provider() returns singleton", singleton is not None)
    return p


def test_score_retrieval(p: CISHistoryProvider):
    print("\n[2] Score retrieval from Supabase")
    now = datetime.now(tz=timezone.utc)
    results = {}

    for sym in TEST_SYMBOLS:
        score  = p.get_cis_at(sym, now, max_age_hours=48)
        grade  = p.get_grade_at(sym, now)
        signal = p.get_signal_at(sym, now)
        regime = p.get_regime_at(sym, now)

        ok = score is not None
        results[sym] = ok
        detail = f"score={score} grade={grade} signal={signal} regime={regime}" if ok else "None returned — no history in Supabase?"
        _check(f"{sym}: score retrieved", ok, detail)

    at_least_one = any(results.values())
    _check("At least one symbol returned data", at_least_one,
           "Supabase unreachable or T26 reconstruction not run yet")
    return at_least_one


def test_pillar_retrieval(p: CISHistoryProvider):
    print("\n[3] Pillar vector retrieval")
    now = datetime.now(tz=timezone.utc)

    pillars = p.get_pillar_at("BTC", now)
    if pillars is None:
        print("  ⚠  No pillar data for BTC (skipping pillar checks)")
        return

    for key in ("F", "M", "O", "S", "A"):
        _check(f"pillar {key} present", key in pillars)

    _check("regime present in pillar dict", "regime" in pillars)


def test_window_and_velocity(p: CISHistoryProvider):
    print("\n[4] Score window + velocity")
    now = datetime.now(tz=timezone.utc)

    window = p.get_cis_window("BTC", now, n=10)
    _check("get_cis_window returns list", isinstance(window, list))
    if window:
        _check("window values are floats", all(isinstance(s, float) or isinstance(s, int) for s in window))

    vel = p.get_score_velocity("BTC", now, window=7)
    if vel is not None:
        _check("velocity is numeric", isinstance(vel, (int, float)),
               f"vel={vel}")
    else:
        print("  ⚠  velocity=None (insufficient history rows)")


def test_gate_logic(p: CISHistoryProvider):
    print("\n[5] passes_cis_gate logic")
    now = datetime.now(tz=timezone.utc)

    # Gate with floor=0 should always pass if data is present
    score = p.get_cis_at("BTC", now, max_age_hours=48)
    if score is None:
        print("  ⚠  No BTC score — skipping gate tests")
        return

    passes_low  = p.passes_cis_gate("BTC", now, min_score=0.0)
    passes_high = p.passes_cis_gate("BTC", now, min_score=100.0)
    passes_reg  = p.passes_cis_gate("BTC", now, min_score=52.0,
                                    regime_thresholds=REGIME_THRESHOLDS)

    _check("gate(0) = True when data present", passes_low)
    _check("gate(100) = False (no perfect score)", not passes_high)
    _check("gate with regime_thresholds runs without error", passes_reg is not None)
    print(f"     BTC score={score:.1f}  gate(52, regime-aware)={passes_reg}")


def test_dataframe(p: CISHistoryProvider):
    print("\n[6] DataFrame export")
    try:
        import pandas as pd
    except ImportError:
        print("  ⚠  pandas not installed — skipping DataFrame test")
        return

    df = p.get_cis_dataframe("BTC")
    if df.empty:
        print("  ⚠  DataFrame empty — no BTC history in Supabase")
        return

    _check("DataFrame has rows", len(df) > 0, f"{len(df)} rows")
    _check("recorded_at column present", "recorded_at" in df.columns)
    _check("score column present", "score" in df.columns)
    print(f"     date range: {df['recorded_at'].min()} → {df['recorded_at'].max()}")


def test_stale_score_blocked(p: CISHistoryProvider):
    print("\n[7] Stale score correctly blocked")
    # A datetime far in the future — no score should exist at/before this time
    # with max_age_hours=1 from a date 1 year ahead
    far_future = datetime.now(tz=timezone.utc) + timedelta(days=365)
    score = p.get_cis_at("BTC", far_future, max_age_hours=1)
    _check("Score for t+1yr with 1h window is None (stale blocked)", score is None,
           f"got score={score}")


def test_unknown_symbol(p: CISHistoryProvider):
    print("\n[8] Unknown symbol handled gracefully")
    now = datetime.now(tz=timezone.utc)
    score  = p.get_cis_at("FAKECOIN_XYZ", now)
    passes = p.passes_cis_gate("FAKECOIN_XYZ", now, min_score=50)
    _check("Unknown symbol returns None score", score is None)
    _check("Unknown symbol fails gate (fail-closed)", not passes)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("CISHistoryProvider — T27 validation")
    print("=" * 60)

    supabase_url = os.getenv("SUPABASE_URL", "")
    if not supabase_url:
        print("\n⚠  SUPABASE_URL not set — will test Railway fallback only")
    else:
        print(f"\nSupabase: {supabase_url[:40]}...")

    p = test_provider_init()
    has_data = test_score_retrieval(p)
    test_pillar_retrieval(p)
    test_window_and_velocity(p)
    test_gate_logic(p)
    test_dataframe(p)
    test_stale_score_blocked(p)
    test_unknown_symbol(p)

    print("\n" + "=" * 60)
    if has_data:
        print("✓ CISHistoryProvider is operational — T27 wiring ready")
    else:
        print("⚠  No Supabase data returned. Check credentials or run T26 reconstruction.")
    print("=" * 60)


if __name__ == "__main__":
    main()
