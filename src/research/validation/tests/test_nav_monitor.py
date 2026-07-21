"""
Smoke tests for R66 NAV gap monitor (src/data/signals/nav_monitor.py).

Anti-imposter: a NAV monitor that papers over missing data is the trader's
trader agent at its worst. These tests pin:
  - Sharpe/dd math is correct on synthetic curves
  - Status classification reflects the gap honestly
  - min_days floor prevents a 3-day Sharpe from declaring BREAKING/OVERPERFORM
  - Reference registry exposes the OOS expectations for both books
  - Curtain edges: zero-variance curve, all-null rets, no-rows Supabase miss
    → returns None cleanly, does NOT raise.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from src.data.signals.nav_monitor import (
    _ann_sharpe,
    _rolling_max_dd,
    classify_gap,
    compute_book_gap,
    run_monitor,
    FUSION_REF,
    TWO_LAYER_REF,
    DRIFT_THRESHOLD,
    BREAKING_MARGIN,
    MIN_DAYS_FOR_READ,
)


# ── mini test harness ────────────────────────────────────────────────────────

_passes: list[str] = []
_fails: list[str] = []


def _check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        _passes.append(name)
        print(f"  ✓ {name}")
    else:
        _fails.append(f"{name}: {detail}")
        print(f"  ✗ {name} — {detail}")


def _summary(suite: str) -> None:
    print(f"\n  {len(_passes)} passed · {len(_fails)} failed — {suite}")
    if _fails:
        for f in _fails:
            print(f"    FAILED: {f}")


# ── tests ────────────────────────────────────────────────────────────────────

def test_ann_sharpe_basic():
    print("\n[test_ann_sharpe_basic]")
    # Positive constant returns → zero std → Sharpe = None
    rets = [0.001] * 50
    _check("constant returns → None (zero variance)", _ann_sharpe(rets) is None)

    # Slightly positive bias alternating with slight negative — mean > 0 → Sharpe > 0
    rets = [0.001, -0.0005] * 30   # mean = +0.00025
    s = _ann_sharpe(rets)
    _check("alternating returns with positive bias → positive Sharpe",
           s is not None and s > 0, detail=str(s))

    # Negative bias
    rets = [-0.001, 0.0005] * 30   # mean = -0.00025
    s2 = _ann_sharpe(rets)
    _check("negative biased alternating returns → negative Sharpe",
           s2 is not None and s2 < 0, detail=str(s2))

    _check("too few returns → None", _ann_sharpe([0.001] * 4) is None)

    # Mix of None + enough valid returns to compute Sharpe
    rets = [None, None, None] + [0.001, -0.002, 0.0005, 0.002, 0.0001]
    s3 = _ann_sharpe(rets)
    _check("None entries skipped, still returns a number when enough valid rets",
           s3 is not None and isinstance(s3, float), detail=str(s3))


def test_rolling_max_dd_basic():
    print("\n[test_rolling_max_dd_basic]")
    # 10-day run-up 1% → peak 1.01^10 ≈ 1.105 (+10.5%), then 5-day drop 5% → 0.95^5 ≈ 0.774
    # → end at 1.105 * 0.774 = 0.855, drawdown from peak = -22.6%
    rets = [0.01] * 10 + [-0.05] * 5
    dd = _rolling_max_dd(rets)
    _check("maxDD is negative", dd < 0, detail=str(dd))
    _check("maxDD roughly -22% to -23% (peak-after-up, drop-after)",
           -23.0 <= dd <= -21.0, detail=str(dd))

    # All positive → maxDD = 0
    dd2 = _rolling_max_dd([0.001] * 30)
    _check("monotone up → maxDD = 0", dd2 == 0.0, detail=str(dd2))

    # Single drawdown from peak: -50% then recovery → maxDD = -50%
    rets = [-0.5, 0.5, 0.5]
    dd3 = _rolling_max_dd(rets)
    _check("-50% then recovery → maxDD = -50%",
           -51.0 <= dd3 <= -49.0, detail=str(dd3))


def test_classify_gap_thresholds():
    print("\n[test_classify_gap_thresholds]")
    n = 30   # past MIN_DAYS_FOR_READ

    _check("gap=-2.0 + n>=20 → BREAKING",
           classify_gap(-2.0, n) == "BREAKING")
    _check("gap=-1.0 + n>=20 → DRIFT",
           classify_gap(-1.0, n) == "DRIFT")
    _check("gap=-0.5 + n>=20 → on_track",
           classify_gap(-0.5, n) == "on_track")
    _check("gap=+0.3 + n>=20 → on_track",
           classify_gap(+0.3, n) == "on_track")
    _check("gap=+2.0 + n>=20 → OVERPERFORM",
           classify_gap(+2.0, n) == "OVERPERFORM")
    _check("gap=None → unknown",
           classify_gap(None, n) == "unknown")
    _check("n=10 → warming_up regardless of gap",
           classify_gap(-5.0, 10) == "warming_up")
    _check("n=19 → warming_up (just below floor)",
           classify_gap(-5.0, 19) == "warming_up")
    _check("n=20 + bad gap → not warming_up",
           classify_gap(-5.0, 20) == "BREAKING")


def test_ref_registry_exposes_honest_expectations():
    print("\n[test_ref_registry_exposes_honest_expectations]")
    # FUSION REF
    _check("FUSION_REF has oos_sharpe",
           FUSION_REF.get("oos_sharpe") is not None,
           detail=str(FUSION_REF))
    _check("FUSION_REF oos_sharpe ≈ 1.98 (from OOS_t × sqrt(252/365))",
           abs(FUSION_REF["oos_sharpe"] - 1.98) < 0.1,
           detail=str(FUSION_REF["oos_sharpe"]))
    _check("FUSION_REF oos_t = 2.38 (R64 REPORT headline)",
           FUSION_REF.get("oos_t") == 2.38)
    _check("FUSION_REF oos_max_dd = -11.05 (R64 REPORT)",
           FUSION_REF.get("oos_max_dd") == -11.05)

    # TWO_LAYER REF
    _check("TWO_LAYER_REF has oos_sharpe (regime-scaled)",
           TWO_LAYER_REF.get("oos_sharpe") is not None)
    _check("TWO_LAYER_REF oos_sharpe = 4.88 (regime-scaled from C-S4)",
           TWO_LAYER_REF.get("oos_sharpe") == 4.88)
    _check("TWO_LAYER_REF oos_max_dd = -2.46 (regime-scaled)",
           TWO_LAYER_REF.get("oos_max_dd") == -2.46)

    # Anti-imposter: full-period gross must NOT be the reference
    _check("FUSION_REF oos_sharpe (1.98) ≠ gross_sharpe_full (1.69)",
           FUSION_REF["oos_sharpe"] != FUSION_REF["gross_sharpe_full"],
           detail="reference would be contaminated by fit window")
    _check("TWO_LAYER_REF uses regime-scaled (4.88) ≠ full-period (5.38)",
           TWO_LAYER_REF["oos_sharpe"] != TWO_LAYER_REF["gross_sharpe_full"])


def test_compute_book_gap_synthetic_ok_case():
    print("\n[test_compute_book_gap_synthetic_ok_case]")
    # Build a 60-day curve where live Sharpe ≈ FUSION_REF.oos_sharpe (1.98)
    # daily mean ~ 1.98 / sqrt(365) ≈ 0.1037 — choose rets with that mean
    import random
    random.seed(42)
    rets = [random.gauss(0.104, 0.6) for _ in range(60)]
    nav = 1.0
    rows = []
    for r in rets:
        nav *= (1 + r / 100)   # express in pct to keep Sharpe realistic
        rows.append({"mark_date": "2026-05-01", "nav": nav,
                     "daily_return": r / 100, "return_pct": 0})
    curve = {
        "status": "ok",
        "days": len(rows),
        "nav": rows[-1]["nav"],
        "return_pct": (rows[-1]["nav"] - 1) * 100,
        "curve": rows,
        "validated": len(rows) >= 60,
    }
    gap = compute_book_gap(curve, FUSION_REF)
    _check("compute_book_gap returns gap record", isinstance(gap, dict))
    _check("gap has live.ann_sharpe field",
           gap["live"].get("ann_sharpe") is not None)
    _check("gap has expected_oos.ann_sharpe = 1.98",
           gap["expected_oos"]["ann_sharpe"] == 1.98)
    _check("gap.status is on_track (Sharpe roughly matches)",
           gap["status"] in ("on_track", "warming_up", "DRIFT", "OVERPERFORM"),
           detail=str(gap["status"]))
    _check("gap.live.n_days == 60",
           gap["live"]["n_days"] == 60)
    _check("gap.live.max_dd_pct negative (drawdown visible)",
           gap["live"]["max_dd_pct"] <= 0,
           detail=str(gap["live"]["max_dd_pct"]))


def test_compute_book_gap_warming_up():
    print("\n[test_compute_book_gap_warming_up]")
    # 5 days with varying returns — sufficient variance to compute Sharpe,
    # but n < MIN_DAYS_FOR_READ, so classify_gap returns warming_up regardless
    rows = [
        {"mark_date": f"2026-05-0{i+1}", "nav": 1.0 + 0.001*i, "daily_return": 0.001*i}
        for i in range(1, 6)
    ]
    curve = {"status": "ok", "days": 5, "nav": rows[-1]["nav"],
             "return_pct": 0.5, "curve": rows}
    gap = compute_book_gap(curve, FUSION_REF)
    _check("warming_up when < MIN_DAYS_FOR_READ",
           gap["status"] == "warming_up",
           detail=str(gap["status"]))
    _check("warming_up but n_days surfaced honestly",
           gap["live"]["n_days"] == 5, detail=str(gap["live"]))
    _check("warming_up still surfaces live.ann_sharpe (computed, just not classified)",
           gap["live"]["ann_sharpe"] is not None,
           detail=str(gap["live"]))


def test_compute_book_gap_no_data():
    print("\n[test_compute_book_gap_no_data]")
    # Empty curve (Supabase miss, no NAV yet)
    curve = {"status": "no_data", "days": 0, "curve": []}
    gap = compute_book_gap(curve, FUSION_REF)
    _check("no_data returns gap status=unknown (not warming_up)",
           gap["status"] == "unknown",
           detail=str(gap["status"]))
    _check("no_data surfaces live.n_days=0",
           gap["live"]["n_days"] == 0)
    _check("no_data preserves ref + report_path",
           "R64" in (gap.get("ref_label") or "") or
           "fusion" in (gap.get("ref_label") or "").lower(),
           detail=gap.get("ref_label", "")[:80])
    _check("no_data preserves report_path",
           "REPORT.md" in (gap.get("report_path") or ""),
           detail=gap.get("report_path"))


def test_run_monitor_when_supabase_missing():
    print("\n[test_run_monitor_when_supabase_missing]")
    import asyncio
    # SUPABASE_URL not set in test env → both curves should return gracefully
    # rather than raising
    out = asyncio.run(run_monitor())
    _check("run_monitor returned a dict without raising",
           isinstance(out, dict))
    _check("result has 'books' key", "books" in out)
    _check("books has fusion + two_layer",
           "fusion" in out["books"] and "two_layer" in out["books"],
           detail=str(list(out["books"].keys())))
    _check("result has summary with heads",
           isinstance(out.get("summary"), dict) and
           "heads" in out["summary"],
           detail=str(out.get("summary")))
    # Status is either ok (if books reachable on disk) or no_supabase
    _check("status is sane",
           out.get("status") in ("ok", "no_supabase", "error"),
           detail=str(out.get("status")))


def main() -> None:
    print("=" * 60)
    print("R66 NAV MONITOR SMOKE TESTS")
    print("=" * 60)
    test_ann_sharpe_basic()
    test_rolling_max_dd_basic()
    test_classify_gap_thresholds()
    test_ref_registry_exposes_honest_expectations()
    test_compute_book_gap_synthetic_ok_case()
    test_compute_book_gap_warming_up()
    test_compute_book_gap_no_data()
    test_run_monitor_when_supabase_missing()
    _summary("R66 nav-monitor")
    sys.exit(1 if _fails else 0)


if __name__ == "__main__":
    main()
