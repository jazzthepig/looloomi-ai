"""Smoke test for Liveness SLO (A-13 / M-119 prevention).

The structural fix for "loops go dark and nobody notices for 42 days":
every loop must have a max-age budget, and the verdict (live / stale / dead)
must surface in the same place as the existing data-freshness read.

Tests:

  T1: RECENT_OK — last_ok_at < budget, last_run_at < budget → live
  T2: STALE — age > budget but < 4× budget → stale
  T3: DEAD_4X — age > 4× budget → dead
  T4: NEVER_RAN — verdict=never_ran → dead
  T5: NO_RECORD — last_run_at=None → dead
  T6: ZERO_AGE_OK — age_s=0 → live
  T7: MARKER_DEAD_OVERALL — any marker loop dead → overall=critical
  T8: NON_MARKER_DEAD_OVERALL — only non-marker dead → overall=degraded
  T9: STALE_OVERALL — only stale → overall=degraded
  T10: ALL_LIVE — all live → overall=healthy
  T11: SUMMARY_COUNTS — counts match dead_loops + stale_loops + n_live
  T12: LOOP_WITH_NO_SLO_REGISTERED — falls back to DEFAULT_MAX_AGE_H=48

Synthetic data only — no DB / no secrets / no network.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, "/Users/sbb/Projects/looloomi-ai")

from src.api.liveness import (
    LIVENESS_SLOS, DEFAULT_MAX_AGE_H,
    compute_liveness_for_loop, compute_liveness_summary,
    LivenessVerdict,
)


def _row(loop, last_ok_at=None, last_run_at=None, age_s=None, verdict="failing"):
    return {"loop": loop, "last_ok_at": last_ok_at, "last_run_at": last_run_at,
            "age_s": age_s, "verdict": verdict}


# === Per-loop tests ==========================================================
def test_t1_recent_ok_live():
    v = compute_liveness_for_loop(
        "_beta_core_loop",
        last_ok_at=1000, last_run_at=1000, age_s=3600,  # 1h old
        verdict="ok",
    )
    print(f"  T1 verdict={v.verdict} age_s={v.age_s} remaining={v.budget_remaining_h:.1f}h")
    assert v.verdict == "live", f"expected live, got {v.verdict}"
    assert v.budget_remaining_h > 0
    print("✓ T1: 1h-old successful run → live")


def test_t2_stale_age_over_budget():
    v = compute_liveness_for_loop(
        "_beta_core_loop",
        last_ok_at=9000, last_run_at=9500, age_s=60 * 3600,  # 60h old (budget 48h)
        verdict="failing",
    )
    print(f"  T2 verdict={v.verdict} age_s={v.age_s}h remaining={v.budget_remaining_h:.1f}h")
    assert v.verdict == "stale", f"expected stale, got {v.verdict}"
    print("✓ T2: 60h-old run (budget 48h) → stale")


def test_t3_dead_age_over_4x_budget():
    v = compute_liveness_for_loop(
        "_beta_core_loop",
        last_ok_at=0, last_run_at=100, age_s=200 * 3600,  # 200h old (4× = 192h)
        verdict="failing",
    )
    print(f"  T3 verdict={v.verdict} age_s={v.age_s}h")
    assert v.verdict == "dead", f"expected dead, got {v.verdict}"
    assert "4×" in v.reason
    print("✓ T3: 200h-old run (4× budget 192h) → dead")


def test_t4_never_ran_dead():
    v = compute_liveness_for_loop(
        "_beta_core_loop", None, None, None, verdict="never_ran",
    )
    print(f"  T4 verdict={v.verdict} reason={v.reason}")
    assert v.verdict == "dead"
    assert "never_ran" in v.reason
    print("✓ T4: verdict=never_ran → dead")


def test_t5_no_record_dead():
    v = compute_liveness_for_loop(
        "_beta_core_loop", None, None, None, verdict="ok",  # verdict=ok but no record
    )
    print(f"  T5 verdict={v.verdict}")
    assert v.verdict == "dead"
    print("✓ T5: no last_run_at / no age_s → dead (verdict lied)")


def test_t6_zero_age_ok():
    v = compute_liveness_for_loop(
        "_beta_core_loop", 100, 100, age_s=0, verdict="ok",
    )
    print(f"  T6 verdict={v.verdict}")
    assert v.verdict == "live"
    print("✓ T6: age_s=0 → live")


def test_t12_loop_without_slo_entry_uses_default():
    v = compute_liveness_for_loop(
        "_some_unknown_loop",
        last_ok_at=100, last_run_at=200, age_s=24 * 3600,  # 24h old
        verdict="ok",
    )
    print(f"  T12 verdict={v.verdict} reason={v.reason}")
    # Default budget is 48h; 24h is within budget → live
    assert v.verdict == "live"
    assert "unknown" in v.reason, f"reason should mention 'unknown' kind: {v.reason}"
    print("✓ T12: unknown loop falls back to DEFAULT_MAX_AGE_H=48h")


# === Summary tests ===========================================================
def test_t7_marker_dead_overall_critical():
    rows = [
        _row("_beta_core_loop", last_ok_at=0, last_run_at=100,
             age_s=200 * 3600, verdict="failing"),
        _row("_causal_paper_loop", last_ok_at=100, last_run_at=100,
             age_s=3600, verdict="ok"),
    ]
    s = compute_liveness_summary(rows)
    print(f"  T7 overall={s['overall']} dead={s['dead_loops']} marker_problem={s['marker_loops_problem']}")
    assert s["overall"] == "critical"
    assert "_beta_core_loop" in s["marker_loops_problem"]
    print("✓ T7: marker loop dead → overall=critical")


def test_t8_non_marker_dead_overall_degraded():
    rows = [
        _row("_hyperliquid_loop", last_ok_at=0, last_run_at=100,
             age_s=200 * 3600, verdict="failing"),  # non-marker
        _row("_beta_core_loop", last_ok_at=100, last_run_at=100,
             age_s=3600, verdict="ok"),
    ]
    s = compute_liveness_summary(rows)
    print(f"  T8 overall={s['overall']} dead={s['dead_loops']} marker_problem={s['marker_loops_problem']}")
    assert s["overall"] == "degraded"
    assert "_hyperliquid_loop" in s["dead_loops"]
    assert s["marker_loops_problem"] == []   # not a marker
    print("✓ T8: only non-marker dead → overall=degraded")


def test_t9_stale_overall_degraded():
    rows = [
        _row("_cg_panel_loop", last_ok_at=100, last_run_at=100,
             age_s=200 * 3600, verdict="refusing"),  # 200h, fanout budget 168h → stale
        _row("_beta_core_loop", last_ok_at=100, last_run_at=100,
             age_s=3600, verdict="ok"),
    ]
    s = compute_liveness_summary(rows)
    print(f"  T9 overall={s['overall']} stale={s['stale_loops']}")
    assert s["overall"] == "degraded"
    assert "_cg_panel_loop" in s["stale_loops"]
    print("✓ T9: only stale → overall=degraded")


def test_t10_all_live_overall_healthy():
    rows = [
        _row("_beta_core_loop", last_ok_at=100, last_run_at=100, age_s=3600, verdict="ok"),
        _row("_forward_record_loop", last_ok_at=100, last_run_at=100, age_s=1800, verdict="ok"),
        _row("_cg_panel_loop", last_ok_at=100, last_run_at=100, age_s=24*3600, verdict="ok"),
    ]
    s = compute_liveness_summary(rows)
    print(f"  T10 overall={s['overall']} n_live={s['n_live']}/{s['n_total']}")
    assert s["overall"] == "healthy"
    assert s["n_dead"] == 0 and s["n_stale"] == 0
    print("✓ T10: all live → overall=healthy")


def test_t11_summary_counts_consistent():
    rows = [
        _row("_beta_core_loop", 0, 100, 200*3600, "failing"),     # dead (marker)
        _row("_causal_paper_loop", 0, 100, 200*3600, "failing"),  # dead (marker)
        _row("_cg_panel_loop", 100, 100, 60*3600, "refusing"),    # stale
        _row("_forward_record_loop", 100, 100, 3600, "ok"),       # live
    ]
    s = compute_liveness_summary(rows)
    print(f"  T11 n_live={s['n_live']} n_stale={s['n_stale']} n_dead={s['n_dead']} total={s['n_total']}")
    assert s["n_live"] + s["n_stale"] + s["n_dead"] == s["n_total"]
    assert len(s["dead_loops"]) == s["n_dead"]
    assert len(s["stale_loops"]) == s["n_stale"]
    assert s["overall"] == "critical"
    print("✓ T11: counts match")


# === Real-world replay: what we saw on 09-14 ================================
def test_replay_09_14_production_state():
    """The 09-14 估值点 4 判据 state, replayed against this SLO.

    These are the loop rows I pulled from /internal/data-freshness at
    checkpoint. With the SLO applied, the picture is:
      - 4 marker loops DEAD (last_ok_at = 09-09 or 09-12, S-323 era)
      - 1 refused-non-marker dead/stale per its kind
      - overall = critical (marker dead)

    That's the headline that should have been on /health when this started,
    instead of the human spotting it from a curl.
    """
    # 09-14 ~21:00 UTC, breaker just reset, but loop.last_ok_at still old
    rows = [
        _row("_beta_core_loop", last_ok_at=1788825943, last_run_at=1789354500,
             age_s=10428, verdict="failing"),   # 09-09 last ok
        _row("_causal_paper_loop", last_ok_at=1789171553, last_run_at=1789354498,
             age_s=10432, verdict="failing"),
        _row("_combined_book_loop", last_ok_at=1789171549, last_run_at=1789354494,
             age_s=10436, verdict="failing"),
        _row("_scalable_book_loop", last_ok_at=1789171549, last_run_at=1789354494,
             age_s=10436, verdict="failing"),
        _row("_forward_record_loop", last_ok_at=1788967467, last_run_at=1789355331,
             age_s=763, verdict="failing"),   # 13 minutes ago, freshly failed
        _row("_deep_panel_loop", last_ok_at=1788846643, last_run_at=1789289112,
             age_s=67376, verdict="refusing"),  # 18.7h old, fanout budget 168h → live
        _row("_hyperliquid_loop", last_ok_at=None, last_run_at=1789354047,
             age_s=165, verdict="failing"),
    ]
    s = compute_liveness_summary(rows)
    print(f"  REPLAY overall={s['overall']}")
    print(f"    dead:   {s['dead_loops']}")
    print(f"    stale:  {s['stale_loops']}")
    print(f"    marker_problem: {s['marker_loops_problem']}")
    assert s["overall"] == "critical", f"expected critical, got {s['overall']}"
    assert "_beta_core_loop" in s["marker_loops_problem"]
    print("✓ REPLAY 09-14: marker problem → overall=critical (the headline we needed)")


if __name__ == "__main__":
    print("=== Liveness SLO smoke (A-13) ===\n")
    test_t1_recent_ok_live()
    test_t2_stale_age_over_budget()
    test_t3_dead_age_over_4x_budget()
    test_t4_never_ran_dead()
    test_t5_no_record_dead()
    test_t6_zero_age_ok()
    test_t12_loop_without_slo_entry_uses_default()
    print()
    test_t7_marker_dead_overall_critical()
    test_t8_non_marker_dead_overall_degraded()
    test_t9_stale_overall_degraded()
    test_t10_all_live_overall_healthy()
    test_t11_summary_counts_consistent()
    test_replay_09_14_production_state()
    print(f"\n=== All Liveness SLO tests passed (12/12) ===")
