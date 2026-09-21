"""Unit + integration tests for `compare_three_arms.py` and `report_three_arms.py`.

Tests split into two halves:
  1. Pure-function unit tests: `_build_daily_returns`, `_sharpe_daily`,
     `_sortino_daily`, `_max_dd_pct`. These don't touch disk.
  2. End-to-end on a synthetic run dir built in `tmp_path`: write 3 synthetic
     JSONLs + _meta.json, call `compare()`, then `render()` the markdown.

Per CLAUDE.md rule 9 (no mock data in production paths): tests are allowed
synthetic data; production replay requires real Supabase.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


# ── 1. Pure-function unit tests ─────────────────────────────────────────────

def test_sharpe_daily_known_input():
    """Steady +1%/day → Sharpe should be very high (large positive mean, low vol)."""
    from paper_trading.compare_three_arms import _sharpe_daily
    daily = [0.01] * 100
    sr = _sharpe_daily(daily, ann=365)
    # mean = 0.01, std ≈ 0, so (mean/std) → infinity; we cap at 0.0
    # Actually if std == 0, returns 0.0 by the no-variance branch.
    assert sr == 0.0, f"constant return → std=0 → SR=0; got {sr}"


def test_sharpe_daily_random_walk():
    """Random walk with mean=0.001, std=0.01 → SR ≈ 0.001/0.01 × √365 ≈ 1.91."""
    from paper_trading.compare_three_arms import _sharpe_daily
    import random
    random.seed(42)
    daily = [random.gauss(0.001, 0.01) for _ in range(1000)]
    sr = _sharpe_daily(daily, ann=365)
    # Expected: 0.1 * sqrt(365) ≈ 1.91
    assert 1.0 < sr < 3.0, f"random walk with mean=0.001, std=0.01 → SR ≈ 1.9; got {sr}"


def test_sharpe_daily_short_series():
    """< 2 days → returns 0.0 (no variance to compute)."""
    from paper_trading.compare_three_arms import _sharpe_daily
    assert _sharpe_daily([0.01]) == 0.0
    assert _sharpe_daily([]) == 0.0


def test_sortino_no_downside_caps_at_10():
    """All positive returns → Sortino capped at 10.0 (avoids inf)."""
    from paper_trading.compare_three_arms import _sortino_daily
    daily = [0.01] * 100
    sr = _sortino_daily(daily, ann=365)
    assert sr == 10.0, f"all positive → Sortino cap 10; got {sr}"


def test_max_dd_pct_simple():
    """Equity curve 100 → 80 → 90 → 70 → peak=100, valley=70 → MaxDD=30%."""
    from paper_trading.compare_three_arms import _max_dd_pct
    eq = [100, 80, 90, 70]
    dd = _max_dd_pct(eq)
    assert abs(dd - 30.0) < 0.01, f"expected 30% MaxDD, got {dd}"


def test_max_dd_pct_no_drawdown():
    """Monotonic increase → MaxDD = 0%."""
    from paper_trading.compare_three_arms import _max_dd_pct
    eq = [100, 110, 120, 130]
    assert _max_dd_pct(eq) == 0.0


def test_max_dd_pct_short_curve():
    """Equity with < 2 points → MaxDD = 0."""
    from paper_trading.compare_three_arms import _max_dd_pct
    assert _max_dd_pct([100.0]) == 0.0
    assert _max_dd_pct([]) == 0.0


def test_build_daily_returns_single_period():
    """Single ENTERED then window end → no period return computed (0s)."""
    from paper_trading.compare_three_arms import _build_daily_returns
    decisions = [
        {"date": "2026-07-01", "verdict": "ENTERED", "legs": [
            {"symbol": "BTC", "weight": 0.5, "price": 100.0},
            {"symbol": "ETH", "weight": 0.5, "price": 100.0},
        ]},
    ]
    start = dt.date(2026, 7, 1)
    end = dt.date(2026, 7, 10)
    daily = _build_daily_returns(decisions, start, end)
    assert len(daily) == 10
    # 1 ENTERED at d, no subsequent ENTERED → no period return
    assert all(r == 0.0 for r in daily), f"single ENTERED → no period return; got {daily}"


def test_build_daily_returns_two_periods():
    """Two ENTERED events → 1 period return flattened across the gap.

    Semantic: daily_r is applied to days [d_a, d_b) (exclusive of d_b) —
    because d_b's close IS the exit mark for the next ENTERED, and the period
    return already reflects the price jump. Including d_b in the loop would
    double-count (and the "final period" tail branch would overwrite it).
    """
    from paper_trading.compare_three_arms import _build_daily_returns
    decisions = [
        {"date": "2026-07-01", "verdict": "ENTERED", "legs": [
            {"symbol": "BTC", "weight": 1.0, "price": 100.0},
        ]},
        {"date": "2026-07-08", "verdict": "ENTERED", "legs": [
            {"symbol": "BTC", "weight": 1.0, "price": 110.0},  # +10% in 7 days
        ]},
    ]
    start = dt.date(2026, 7, 1)
    end = dt.date(2026, 7, 14)
    daily = _build_daily_returns(decisions, start, end)
    # period_return = 0.10 (from 100 to 110), flattened across 7-day hold
    # daily_r = (1.10)^(1/7) - 1 ≈ 0.0137
    expected_daily_r = (1.10) ** (1.0 / 7) - 1.0
    # Days 0..6 are the holding period; day 7 is the EXIT mark of period 1
    # AND the entry of period 2 — exclusive end means we don't double-count.
    for i in range(7):
        assert abs(daily[i] - expected_daily_r) < 1e-9, (
            f"day {i}: expected {expected_daily_r}, got {daily[i]}"
        )
    # Days 7..13: post-second-ENTERED, no further ENTERED → final-period tail = 0
    for i in range(7, 14):
        assert daily[i] == 0.0, f"day {i}: expected 0, got {daily[i]}"


def test_build_daily_returns_negative_period():
    """Losing period: BTC drops from 100 to 90 → daily_r < 0."""
    from paper_trading.compare_three_arms import _build_daily_returns
    decisions = [
        {"date": "2026-07-01", "verdict": "ENTERED", "legs": [
            {"symbol": "BTC", "weight": 1.0, "price": 100.0},
        ]},
        {"date": "2026-07-08", "verdict": "ENTERED", "legs": [
            {"symbol": "BTC", "weight": 1.0, "price": 90.0},    # -10%
        ]},
    ]
    daily = _build_daily_returns(decisions, dt.date(2026, 7, 1), dt.date(2026, 7, 8))
    assert all(r < 0 for r in daily[:7]), f"all days should be negative; got {daily[:7]}"


# ── 2. Agreement helper ─────────────────────────────────────────────────────

def test_agreement_perfect_match():
    from paper_trading.compare_three_arms import _agreement
    assert _agreement(["ENTERED", "SKIPPED"], ["ENTERED", "SKIPPED"]) == 100.0


def test_agreement_partial_match():
    from paper_trading.compare_three_arms import _agreement
    assert _agreement(["ENTERED", "ENTERED"], ["ENTERED", "SKIPPED"]) == 50.0


def test_agreement_empty():
    from paper_trading.compare_three_arms import _agreement
    assert _agreement([], []) == 0.0


# ── 3. End-to-end on a synthetic run dir ───────────────────────────────────

@pytest.fixture
def synthetic_run_dir(tmp_path) -> Path:
    """Build 3 synthetic JSONLs + _meta.json for hypothesis testing.

    Construction:
      - 14 days, daily decisions
      - arm A and B always ENTER on day 0 and day 7 (cadence 7d)
      - arm C ENTERS on day 0 (all 5 pass) and SKIPS day 7 (factor rejects)
      - BTC +20% over 14d, ETH +5%, SOL flat, BNB -10%, XRP +2%
    """
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    rows_meta = {
        "start": "2026-07-01", "end": "2026-07-14",
        "source": "binance_hist", "panel_n_symbols": 5,
        "panel_last_bar": "2026-07-14",
        "panel_age_at_start_days": 0, "n_rows": 70,
        "universe": ["BTC", "ETH", "SOL", "BNB", "XRP"],
        "cadence_days": 7,
        "n_entered_arm_a_jev": 2, "n_entered_arm_b_baseline": 2,
        "n_entered_arm_c_simple_factor": 1,
        "n_dates_total": 14,
        "spec_a_path": "spec_a.json", "spec_b_path": "spec_b.json",
        "spec_c_path": "spec_c.json", "ts": "2026-09-21T00:00:00Z",
    }
    (run_dir / "_meta.json").write_text(json.dumps(rows_meta))

    # arm A and B: ENTERED on day 0 + 7, cadence SKIPPED otherwise
    a_b_days = []
    for i in range(14):
        d = f"2026-07-{1 + i:02d}"
        if i in (0, 7):
            a_b_days.append({
                "date": d, "spec": "A17_PANEL_LONG_ONLY",
                "spec_family": "panel_long_only",
                "verdict": "ENTERED", "verdict_kind": "entered",
                "panel_source": "binance_hist", "panel_last_bar": "2026-07-14",
                "legs": [
                    {"symbol": "BTC", "side": "long", "weight": 0.20, "price": 100 + i * 1.4},
                    {"symbol": "ETH", "side": "long", "weight": 0.20, "price": 100 + i * 0.35},
                    {"symbol": "SOL", "side": "long", "weight": 0.20, "price": 100.0},
                    {"symbol": "BNB", "side": "long", "weight": 0.20, "price": 100 - i * 0.7},
                    {"symbol": "XRP", "side": "long", "weight": 0.20, "price": 100 + i * 0.14},
                ],
                "reason": f"rebalance {d}", "_meta": {"arm": "B-baseline", "cadence": 7},
            })
        else:
            a_b_days.append({
                "date": d, "spec": "A17_PANEL_LONG_ONLY",
                "spec_family": "panel_long_only",
                "verdict": "SKIPPED", "verdict_kind": "skipped",
                "panel_source": "binance_hist", "panel_last_bar": "2026-07-14",
                "reason": f"cadence skip — last rebalance 2026-07-{1 + (i - i % 7):02d}",
                "_meta": {"arm": "B-baseline", "cadence": 7},
            })
    (run_dir / "a_jev_decisions.jsonl").write_text(
        "\n".join(json.dumps(r) for r in a_b_days))
    (run_dir / "b_baseline_decisions.jsonl").write_text(
        "\n".join(json.dumps(r) for r in a_b_days))

    # arm C: ENTER on day 0, SKIP day 7 (factor rejects), cadence SKIP otherwise
    c_days = []
    for i in range(14):
        d = f"2026-07-{1 + i:02d}"
        if i == 0:
            c_days.append({
                "date": d, "spec": "A17_PANEL_LONG_ONLY_SIMPLE_FACTOR",
                "spec_family": "panel_long_only_simple_factor",
                "verdict": "ENTERED", "verdict_kind": "entered",
                "panel_source": "binance_hist", "panel_last_bar": "2026-07-14",
                "legs": [
                    {"symbol": "BTC", "side": "long", "weight": 0.20, "price": 100},
                    {"symbol": "ETH", "side": "long", "weight": 0.20, "price": 100},
                    {"symbol": "SOL", "side": "long", "weight": 0.20, "price": 100},
                    {"symbol": "BNB", "side": "long", "weight": 0.20, "price": 100},
                    {"symbol": "XRP", "side": "long", "weight": 0.20, "price": 100},
                ],
                "reason": "rebalance, n_legs=5/5 passed factor gate",
                "_meta": {"arm": "C", "cadence": 7},
            })
        elif i == 7:
            c_days.append({
                "date": d, "spec": "A17_PANEL_LONG_ONLY_SIMPLE_FACTOR",
                "spec_family": "panel_long_only_simple_factor",
                "verdict": "SKIPPED", "verdict_kind": "skipped",
                "panel_source": "binance_hist", "panel_last_bar": "2026-07-14",
                "reason": "0/5 通过 factor gate (sma=2/5, mom=3/5, vol=4/5) — factor model 当天空仓",
                "_meta": {"arm": "C", "cadence": 7},
            })
        else:
            c_days.append({
                "date": d, "spec": "A17_PANEL_LONG_ONLY_SIMPLE_FACTOR",
                "spec_family": "panel_long_only_simple_factor",
                "verdict": "SKIPPED", "verdict_kind": "skipped",
                "panel_source": "binance_hist", "panel_last_bar": "2026-07-14",
                "reason": f"cadence skip — last rebalance 2026-07-{(1 if i < 7 else 8):02d}",
                "_meta": {"arm": "C", "cadence": 7},
            })
    (run_dir / "c_simple_factor_decisions.jsonl").write_text(
        "\n".join(json.dumps(r) for r in c_days))
    return run_dir


def test_compare_end_to_end(synthetic_run_dir):
    from paper_trading.compare_three_arms import compare
    diff = compare(synthetic_run_dir)
    assert diff["summary"]["windows_match_under_always_ok"] >= 99.99, (
        f"A and B should match 100% under always_ok; got "
        f"{diff['summary']['windows_match_under_always_ok']}"
    )
    assert diff["summary"]["factor_skip_days"] == 1, (
        f"arm B ENTERS on day 7, arm C SKIPS (factor) → factor_skip_days=1; "
        f"got {diff['summary']['factor_skip_days']}"
    )


def test_report_renders_to_markdown(synthetic_run_dir):
    """End-to-end: compare() → render() → markdown file."""
    from paper_trading.compare_three_arms import compare
    from paper_trading.report_three_arms import render
    diff = compare(synthetic_run_dir)
    md = render(diff)
    assert "S-393" in md
    assert "Arm C vs Arm B" in md
    assert "Per-arm metrics" in md
    assert "Jev wire sanity" in md
    assert "Promote criteria" in md
    # The factor_skip_days=1 should appear in the report
    assert "factor_skip_days" in md.lower() or "factor skip" in md.lower()


def test_full_pipeline_subprocess(synthetic_run_dir):
    """Subprocess: run compare_three_arms.py → _diff.json, then report → .md."""
    compare_cp = subprocess.run(
        [sys.executable, "-m", "paper_trading.compare_three_arms",
         "--in-dir", str(synthetic_run_dir)],
        cwd=str(ROOT), capture_output=True, text=True, timeout=30,
    )
    assert compare_cp.returncode == 0, f"compare failed: {compare_cp.stderr!r}"
    diff_path = synthetic_run_dir / "_diff.json"
    assert diff_path.exists()
    report_path = synthetic_run_dir / "report.md"
    report_cp = subprocess.run(
        [sys.executable, "-m", "paper_trading.report_three_arms",
         "--diff", str(diff_path), "--out", str(report_path)],
        cwd=str(ROOT), capture_output=True, text=True, timeout=30,
    )
    assert report_cp.returncode == 0, f"report failed: {report_cp.stderr!r}"
    md = report_path.read_text()
    assert "S-393" in md
    assert "Promote criteria" in md
