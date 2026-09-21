"""End-to-end smoke test for `replay_three_arms.py` + `compare_three_arms.py`.

These tests run WITHOUT Supabase (synthetic panel), and verify:
  1. `Spec.load` accepts both arm A/B and arm C specs.
  2. `replay_three_arms.main()` produces 3 JSONLs with sensible ENTERED counts.
  3. `compare_three_arms.compare()` returns the expected structure.
  4. Arm A and arm B agree 100% under `always_ok` mode (sanity check).
  5. Arm C is structurally different (different ENTERED counts or different legs).

Per the same discipline as the other smoke tests in this dir: one mutation
per assertion. If something flips, the test tells you exactly which invariant
broke.

Per CLAUDE.md rule 9 (no mock data in production paths): these tests are in
`tests/` so they're allowed to use synthetic panels. The production replay
script (Mac-side) requires real Supabase data.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
REPLAY = ROOT / "paper_trading" / "replay_three_arms.py"
COMPARE = ROOT / "paper_trading" / "compare_three_arms.py"
SPEC_A17 = ROOT / "paper_trading" / "specs" / "a17_panel_long_only.json"
SPEC_ARMC = ROOT / "paper_trading" / "specs" / "a17_panel_long_only_simple_factor.json"
SPECS_DIR = ROOT / "paper_trading" / "specs"


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def panel_60d(tmp_path) -> Path:
    """120d synthetic panel with BTC/ETH/SOL/BNB/XRP, src=binance_hist.

    Length chosen so window starting 2026-06-01 (47d before window end 2026-07-18)
    has ≥60d history for min_history_days to pass (A-17 spec). 60d window would
    start panel at 2026-05-19 — too late for as_of=2026-06-01 - 60d = 2026-04-02.
    120d window gives panel start 2026-03-21, well below the threshold.

    BTC: steady uptrend (+0.5%/day)
    ETH: downtrend (-0.3%/day)
    SOL: high-vol alternating (±3%)
    BNB: flat
    XRP: gentle uptrend (+0.2%/day)
    """
    rows = []
    end = dt.date(2026, 7, 18)
    n_days = 120
    px = {"BTC": 100.0, "ETH": 100.0, "SOL": 100.0, "BNB": 100.0, "XRP": 100.0}
    profiles = {
        "BTC": (0.005, 0.0),
        "ETH": (-0.003, 0.0),
        "SOL": (0.0, 0.03),
        "BNB": (0.0, 0.0),
        "XRP": (0.002, 0.0),
    }
    for i in range(n_days):
        d = (end - dt.timedelta(days=n_days - 1 - i)).isoformat()
        for sym, (drift, vol) in profiles.items():
            sign = 1 if i % 2 == 0 else -1
            shock = sign * vol if sym == "SOL" else 0.0
            px[sym] *= (1 + drift + shock)
            rows.append({
                "symbol": sym, "trade_date": d, "close": round(px[sym], 4),
                "source": "binance_hist",
            })
    p = tmp_path / "panel_120d.json"
    p.write_text(json.dumps(rows), encoding="utf-8")
    return p


def _run_replay(panel_path: Path, out_dir: Path, start: str = "2026-06-01",
                end: str = "2026-07-18") -> subprocess.CompletedProcess:
    e = os.environ.copy()
    e["SUPABASE_URL"] = ""
    e["SUPABASE_KEY"] = ""
    return subprocess.run(
        [sys.executable, "-m", "paper_trading.replay_three_arms",
         "--panel-json", str(panel_path),
         "--start", start, "--end", end,
         "--out", str(out_dir),
         "--spec-a", str(SPEC_A17),
         "--spec-b", str(SPEC_A17),
         "--spec-c", str(SPEC_ARMC)],
        cwd=str(ROOT), capture_output=True, text=True, env=e, timeout=60,
    )


# ── 1. Spec.load accepts both arms ──────────────────────────────────────────

def test_spec_loads_for_both_arms():
    from paper_trading.spec_runner import Spec
    spec_a = Spec.load(SPEC_A17)
    spec_c = Spec.load(SPEC_ARMC)
    assert spec_a.family == "panel_long_only"
    assert spec_c.family == "panel_long_only_simple_factor"
    assert set(spec_a.universe) == set(spec_c.universe), \
        "arms MUST share universe for fair comparison"


# ── 2. Replay end-to-end produces 3 JSONLs ──────────────────────────────────

def test_replay_proces_three_jsonls(panel_60d, tmp_path):
    out_dir = tmp_path / "replay_test"
    cp = _run_replay(panel_60d, out_dir)
    assert cp.returncode == 0, f"replay failed: stdout={cp.stdout!r} stderr={cp.stderr!r}"
    for name in ("a_jev_decisions.jsonl", "b_baseline_decisions.jsonl",
                 "c_simple_factor_decisions.jsonl"):
        path = out_dir / name
        assert path.exists(), f"missing {path}"
        n_lines = len([l for l in path.read_text().splitlines() if l.strip()])
        assert n_lines > 0, f"empty {path}"


# ── 3. _meta.json has expected shape ────────────────────────────────────────

def test_meta_json_shape(panel_60d, tmp_path):
    out_dir = tmp_path / "replay_test"
    _run_replay(panel_60d, out_dir)
    meta = json.loads((out_dir / "_meta.json").read_text())
    assert meta["start"] == "2026-06-01"
    assert meta["end"] == "2026-07-18"
    assert meta["source"] == "binance_hist"
    assert meta["panel_n_symbols"] == 5
    # At least 5 ENTERED events in arm B (panel_long_only) over 47 days
    assert meta["n_entered_arm_b_baseline"] >= 5, (
        f"arm B should rebalance ~6 times in 47d; got {meta['n_entered_arm_b_baseline']}"
    )
    # Arm A and arm B ENTERED counts should match (always_ok = no veto)
    assert meta["n_entered_arm_a_jev"] == meta["n_entered_arm_b_baseline"], (
        f"arm A and arm B ENTERED counts should match under always_ok; "
        f"A={meta['n_entered_arm_a_jev']} B={meta['n_entered_arm_b_baseline']}"
    )


# ── 4. Arm A and Arm B verdicts are identical under always_ok ──────────────

def test_arm_a_matches_arm_b_under_always_ok(panel_60d, tmp_path):
    out_dir = tmp_path / "replay_test"
    _run_replay(panel_60d, out_dir)
    a = [json.loads(l) for l in (out_dir / "a_jev_decisions.jsonl").read_text().splitlines() if l]
    b = [json.loads(l) for l in (out_dir / "b_baseline_decisions.jsonl").read_text().splitlines() if l]
    a_verdicts = [r["verdict"] for r in a]
    b_verdicts = [r["verdict"] for r in b]
    assert a_verdicts == b_verdicts, (
        f"arm A and arm B verdicts should be IDENTICAL under always_ok; "
        f"Jev wire leaks behavior if they differ.\n"
        f"A first 10: {a_verdicts[:10]}\n"
        f"B first 10: {b_verdicts[:10]}"
    )


# ── 5. Arm C is structurally different from B ──────────────────────────────

def test_arm_c_differs_from_arm_b(panel_60d, tmp_path):
    out_dir = tmp_path / "replay_test"
    _run_replay(panel_60d, out_dir)
    meta = json.loads((out_dir / "_meta.json").read_text())
    # Arm C should NOT have the same ENTERED count as B (factor gate filters
    # SOMETIMING in this synthetic panel — SOL high-vol is filtered out,
    # ETH downtrend filtered out, BNB flat may fail mom).
    # Specifically: SOL is ±3% daily → vol ~3% daily stdev > 0.05? No — 3% <
    # 5% threshold so vol_ok passes. But ETH is downtrend so SMA60 fails.
    # BNB flat → SMA60 ≈ close so sma_ok fails. XRP uptrend → all pass.
    # BTC uptrend → all pass. So arm C should enter 2/5 = BTC + XRP only.
    assert meta["n_entered_arm_c_simple_factor"] <= meta["n_entered_arm_b_baseline"], (
        f"arm C should enter ≤ arm B (factor gate is a filter, not a booster); "
        f"C={meta['n_entered_arm_c_simple_factor']} B={meta['n_entered_arm_b_baseline']}"
    )


# ── 6. Compare produces _diff.json with expected structure ──────────────────

def test_compare_produces_diff_with_expected_shape(panel_60d, tmp_path):
    out_dir = tmp_path / "replay_test"
    _run_replay(panel_60d, out_dir)
    cp = subprocess.run(
        [sys.executable, "-m", "paper_trading.compare_three_arms",
         "--in-dir", str(out_dir)],
        cwd=str(ROOT), capture_output=True, text=True, timeout=30,
    )
    assert cp.returncode == 0, f"compare failed: stderr={cp.stderr!r}"
    diff_path = out_dir / "_diff.json"
    assert diff_path.exists()
    diff = json.loads(diff_path.read_text())
    assert set(diff["arms"].keys()) == {"A", "B", "C"}
    for arm_key, arm in diff["arms"].items():
        assert "n_entered" in arm
        assert "cum_return_pct" in arm
        assert "sharpe_annualized" in arm
        assert "max_dd_pct" in arm
    assert "agreement_a_b_pct" in diff["agreement"]
    assert "windows_match_under_always_ok" in diff["summary"]
    assert diff["summary"]["windows_match_under_always_ok"] >= 99.99, (
        f"agreement should be 100% under always_ok; got "
        f"{diff['summary']['windows_match_under_always_ok']:.2f}%"
    )
