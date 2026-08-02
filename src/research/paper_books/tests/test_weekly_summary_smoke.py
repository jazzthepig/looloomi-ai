"""Smoke tests for weekly_summary.py — 60d paper phase monitoring module.

Per project discipline (§REFUTATION_LEDGER + CLAUDE.md "every sleeve has a smoke"):
verify that the weekly aggregation module imports cleanly, generates the expected
markdown report, handles insufficient data correctly without fabricating metrics,
and that the Pearson helper is mathematically correct.

Run:
  python3 src/research/paper_books/tests/test_weekly_summary_smoke.py
"""
from __future__ import annotations

import csv
import os
import sys
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "src" / "research" / "paper_books"))

import weekly_summary as ws  # noqa: E402
from ledger import LEDGER_DIR, append_paper_position, PaperPosition  # noqa: E402


def _test_module_imports():
    """ws module is importable; key functions exist."""
    assert hasattr(ws, "main"), "main() missing"
    assert hasattr(ws, "_read_daily_summary"), "_read_daily_summary() missing"
    assert hasattr(ws, "_pearson"), "_pearson() missing"
    assert hasattr(ws, "_signal_trajectories"), "_signal_trajectories() missing"
    assert hasattr(ws, "_try_fetch_r77_nav"), "_try_fetch_r77_nav() missing"
    print("  ✓ module imports + key functions present")


def _test_pearson_correct():
    """Pearson correlation matches known values on synthetic data."""
    # Perfect positive
    xs = [1.0, 2.0, 3.0, 4.0, 5.0]
    ys = [2.0, 4.0, 6.0, 8.0, 10.0]
    r = ws._pearson(xs, ys)
    assert r is not None and abs(r - 1.0) < 1e-9, f"perfect positive failed: {r}"
    # Perfect negative
    r = ws._pearson(xs, [-2.0, -4.0, -6.0, -8.0, -10.0])
    assert r is not None and abs(r - (-1.0)) < 1e-9, f"perfect negative failed: {r}"
    # Uncorrelated (orthogonal — [1,1,-1,-1] and [1,-1,1,-1] have zero correlation)
    r = ws._pearson([1.0, 1.0, -1.0, -1.0], [1.0, -1.0, 1.0, -1.0])
    assert r is not None and abs(r) < 1e-9, f"uncorrelated should be 0: {r}"
    # None handling — ignores None pairs
    r = ws._pearson([1.0, 2.0, None, 4.0], [2.0, 4.0, None, 8.0])
    assert r is not None and abs(r - 1.0) < 1e-9, f"None-pair skipping failed: {r}"
    # Insufficient (n<3)
    r = ws._pearson([1.0, 2.0], [3.0, 4.0])
    assert r is None, f"n<3 should return None, got {r}"
    # Zero variance
    r = ws._pearson([1.0, 2.0, 3.0, 4.0], [5.0, 5.0, 5.0, 5.0])
    assert r is None, f"zero variance should return None, got {r}"
    print("  ✓ _pearson matches known values (positive/negative/orthogonal/None/zero-variance)")


def _test_signal_trajectories_empty():
    """Empty input → all trajectories empty, no crash."""
    out = ws._signal_trajectories([])
    assert len(out) == 4, f"expected 4 trajectories, got {len(out)}"
    for k, v in out.items():
        assert v == [], f"{k} should be empty, got {v}"
    print("  ✓ _signal_trajectories on empty input")


def _test_signal_trajectories_macro_imbalance():
    """macro_overlay_imbalance = (long - short) / (long + short) computed correctly."""
    rows = [
        {"date_utc": "2026-07-28", "vol_carry_term_premium": "6.0", "vol_carry_action": "ENTER_SELL",
         "vol_carry_iv": "37.8", "vol_carry_rv": "31.7",
         "regime_nowcast_p": "0.5", "regime_nowcast_tilt": "1.0",
         "regime_nowcast_btc_30d": "+6.0", "regime_nowcast_tvl_7d": "-2.0",
         "regime_nowcast_usdt_7d": "+0.0",
         "macro_overlay_long_count": "4", "macro_overlay_short_count": "3"},
        {"date_utc": "2026-07-29", "vol_carry_term_premium": "7.0", "vol_carry_action": "ENTER_SELL",
         "vol_carry_iv": "38.0", "vol_carry_rv": "31.0",
         "regime_nowcast_p": "0.6", "regime_nowcast_tilt": "1.5",
         "regime_nowcast_btc_30d": "+7.0", "regime_nowcast_tvl_7d": "+1.0",
         "regime_nowcast_usdt_7d": "+1.0",
         "macro_overlay_long_count": "5", "macro_overlay_short_count": "2"},
    ]
    out = ws._signal_trajectories(rows)
    imb = [v for _, v in out["macro_overlay_imbalance"]]
    assert abs(imb[0] - (4 - 3) / (4 + 3)) < 1e-9, f"day 1 imbalance: {imb[0]}"
    assert abs(imb[1] - (5 - 2) / (5 + 2)) < 1e-9, f"day 2 imbalance: {imb[1]}"
    assert out["regime_nowcast_p"][0][1] == 0.5
    assert out["regime_nowcast_tilt"][1][1] == 1.5
    print("  ✓ macro_overlay_imbalance computed correctly (4/3→+0.143, 5/2→+0.429)")


def _test_safe_float():
    """_safe_float handles malformed strings."""
    assert ws._safe_float("1.5") == 1.5
    assert ws._safe_float("-2.5") == -2.5
    assert ws._safe_float("not_a_number") is None
    assert ws._safe_float("") is None
    assert ws._safe_float(None) is None
    print("  ✓ _safe_float handles valid/invalid/empty/None")


def _test_std():
    """_std handles n<2 and standard cases (sample std, n-1 denominator)."""
    assert ws._std([1.0]) is None
    # [1.0, 2.0]: sample variance = ((1-1.5)^2 + (2-1.5)^2) / (2-1) = 0.5, std = sqrt(0.5) ≈ 0.7071
    s = ws._std([1.0, 2.0])
    assert s is not None and abs(s - 0.7071) < 0.001, f"std of [1,2]: {s}"
    xs = [1.0, 2.0, 3.0, 4.0, 5.0]
    s = ws._std(xs)
    # Sample std of 1..5: sqrt(((−2)^2 + (−1)^2 + 0^2 + 1^2 + 2^2) / 4) = sqrt(2.5) ≈ 1.5811
    assert s is not None and abs(s - 1.5811) < 0.01, f"std mismatch: {s}"
    print("  ✓ _std correct (n<2 returns None; sample std on [1..5] ≈ 1.5811)")


def _test_diffs():
    """_diffs returns first differences, skipping pairs where EITHER is None."""
    assert ws._diffs([1.0, 2.0, 3.0, 4.0]) == [1.0, 1.0, 1.0]
    # [1.0, None, 3.0, 4.0]: only (3.0, 4.0) is a valid adjacent pair → [1.0]
    assert ws._diffs([1.0, None, 3.0, 4.0]) == [1.0]
    assert ws._diffs([]) == []
    # [None, None, 3.0] → no valid pair
    assert ws._diffs([None, None, 3.0]) == []
    print("  ✓ _diffs correct (consecutive differences, skipping any pair where either is None)")


def _test_main_empty_summary(tmp_path: Path):
    """main() on an empty daily_summary.csv returns 0 without crashing."""
    # Override LEDGER_DIR temporarily
    original = ws.LEDGER_DIR if hasattr(ws, "LEDGER_DIR") else LEDGER_DIR
    original_summary = ws.DAILY_SUMMARY_PATH
    original_md = ws.WEEKLY_SUMMARY_PATH
    try:
        # Use tmp dir for daily_summary
        fake_summary = tmp_path / "daily_summary.csv"
        fake_summary.touch()  # empty file
        ws.DAILY_SUMMARY_PATH = fake_summary
        ws.WEEKLY_SUMMARY_PATH = tmp_path / "weekly_summary.md"
        rc = ws.main()
        assert rc == 0, f"main() should return 0, got {rc}"
        print("  ✓ main() on empty summary returns 0 cleanly")
    finally:
        ws.DAILY_SUMMARY_PATH = original_summary
        ws.WEEKLY_SUMMARY_PATH = original_md


def _test_main_synthetic(tmp_path: Path):
    """main() with a 5-row synthetic daily_summary writes weekly_summary.md and exits 0."""
    fake_summary = tmp_path / "daily_summary.csv"
    rows = []
    for i in range(5):
        rows.append({
            "date_utc": f"2026-07-{28 + i:02d}",
            "vol_carry_iv": "37.0", "vol_carry_rv": "31.0",
            "vol_carry_term_premium": f"{6.0 + i * 0.1:.3f}",
            "vol_carry_action": "ENTER_SELL",
            "regime_nowcast_btc_30d": "+6.0", "regime_nowcast_tvl_7d": "-2.0",
            "regime_nowcast_usdt_7d": "+0.0",
            "regime_nowcast_p": f"{0.5 + i * 0.02:.4f}",
            "regime_nowcast_tilt": "1.0",
            "macro_overlay_long_count": "4", "macro_overlay_short_count": "3",
        })
    with open(fake_summary, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    original_summary = ws.DAILY_SUMMARY_PATH
    original_md = ws.WEEKLY_SUMMARY_PATH
    try:
        ws.DAILY_SUMMARY_PATH = fake_summary
        ws.WEEKLY_SUMMARY_PATH = tmp_path / "weekly_summary.md"
        rc = ws.main()
        assert rc == 0, f"main() should return 0, got {rc}"
        assert ws.WEEKLY_SUMMARY_PATH.exists(), "weekly_summary.md not written"
        body = ws.WEEKLY_SUMMARY_PATH.read_text()
        assert "Weekly summary" in body
        assert "vol_carry_term_premium" in body
        assert "5 day(s)" in body
        # Still n=5 < 7 threshold → should report IN-FLIGHT
        assert "IN-FLIGHT" in body, "should report IN-FLIGHT with 5 days"
        print("  ✓ main() on 5-row synthetic writes valid weekly_summary.md (IN-FLIGHT status)")
    finally:
        ws.DAILY_SUMMARY_PATH = original_summary
        ws.WEEKLY_SUMMARY_PATH = original_md


def _test_r77_nav_no_creds():
    """_try_fetch_r77_nav returns None when SUPABASE_URL/KEY are unset (no crash)."""
    # Save and unset creds
    saved_url = ws.SUPABASE_URL
    saved_key = ws.SUPABASE_KEY
    try:
        ws.SUPABASE_URL = ""
        ws.SUPABASE_KEY = ""
        out = ws._try_fetch_r77_nav()
        assert out is None, f"expected None, got {out}"
        print("  ✓ _try_fetch_r77_nav returns None without creds (no crash)")
    finally:
        ws.SUPABASE_URL = saved_url
        ws.SUPABASE_KEY = saved_key


def _test_sharpe_annualized():
    """Sharpe annualized: known values."""
    # All-zero P&L → std=0 → None
    assert ws._sharpe_annualized([0.0, 0.0, 0.0]) is None
    # Constant positive P&L → std=0 → None
    assert ws._sharpe_annualized([1.0, 1.0, 1.0, 1.0]) is None
    # Insufficient (n<3)
    assert ws._sharpe_annualized([1.0, 2.0]) is None
    # Known: [+1, -1] → mean=0, std undefined (n-1=1, sqrt(1)=1, 0/1=0) → Sharpe=0
    s = ws._sharpe_annualized([1.0, -1.0, 1.0, -1.0])
    assert s is not None and abs(s) < 1e-9, f"symmetric P&L should be ~0 Sharpe: {s}"
    # Constant +2 → sharpe = inf (positive) — but std=0 → None
    print("  ✓ _sharpe_annualized handles zero-std/insufficient/symmetric cases")


def _test_max_drawdown():
    """maxDD: known values."""
    # Monotonic up → 0
    assert ws._max_drawdown([100.0, 110.0, 120.0, 130.0]) == 0.0
    # Single drawdown
    dd = ws._max_drawdown([100.0, 90.0, 110.0])
    assert abs(dd - (-0.10)) < 1e-9, f"maxDD should be -10%: {dd}"
    # Multiple drawdowns — take the deepest
    dd = ws._max_drawdown([100.0, 90.0, 110.0, 80.0, 120.0])
    # Peak 110 at idx2, drop to 80 → drawdown = (80 - 110) / 110 = -30/110 ≈ -0.2727
    assert abs(dd - (-30.0 / 110.0)) < 1e-9, f"maxDD should be ≈ -27.27%: {dd}"
    # Insufficient (n<2)
    assert ws._max_drawdown([100.0]) is None
    print("  ✓ _max_drawdown handles monotonic/drawdown/multiple/insufficient")


def _test_read_sleeve_nav_empty(tmp_path: Path):
    """_read_sleeve_nav returns [] when NAV CSV doesn't exist."""
    saved_paths = dict(ws.SLEEVE_NAV_PATHS)
    try:
        ws.SLEEVE_NAV_PATHS = {
            "vol_carry": tmp_path / "missing1.csv",
            "regime_nowcast": tmp_path / "missing2.csv",
            "macro_overlay": tmp_path / "missing3.csv",
        }
        for sleeve_id in ["vol_carry", "regime_nowcast", "macro_overlay"]:
            assert ws._read_sleeve_nav(sleeve_id) == [], f"missing file should return []: {sleeve_id}"
        print("  ✓ _read_sleeve_nav returns [] when CSV missing")
    finally:
        ws.SLEEVE_NAV_PATHS = saved_paths


def _test_read_sleeve_nav_round_trip(tmp_path: Path):
    """_read_sleeve_nav reads correctly a CSV with 3 NAV rows."""
    saved_paths = dict(ws.SLEEVE_NAV_PATHS)
    try:
        nav_path = tmp_path / "macro_overlay_nav.csv"
        with open(nav_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["date_utc", "daily_pnl_usd", "cumulative_nav_usd", "n_positions", "sleeve_note"])
            w.writeheader()
            w.writerow({"date_utc": "2026-07-27", "daily_pnl_usd": "120.0", "cumulative_nav_usd": "400120.0", "n_positions": "2", "sleeve_note": "test1"})
            w.writerow({"date_utc": "2026-07-28", "daily_pnl_usd": "-50.0", "cumulative_nav_usd": "400070.0", "n_positions": "2", "sleeve_note": "test2"})
            w.writerow({"date_utc": "2026-07-29", "daily_pnl_usd": "200.0", "cumulative_nav_usd": "400270.0", "n_positions": "2", "sleeve_note": "test3"})
        ws.SLEEVE_NAV_PATHS = {"macro_overlay": nav_path}
        rows = ws._read_sleeve_nav("macro_overlay")
        assert len(rows) == 3, f"expected 3 rows: {len(rows)}"
        assert rows[0]["date_utc"] == "2026-07-27"
        # Sharpe on daily_pnls [120, -50, 200]: mean=90, std=sqrt(((120-90)^2 + (-50-90)^2 + (200-90)^2)/2)=sqrt(13300)≈115.3, Sharpe(ann)≈90/115.3×sqrt(365)≈14.78
        sharpe = ws._sharpe_annualized([120.0, -50.0, 200.0])
        assert sharpe is not None and sharpe > 10.0, f"expected high Sharpe: {sharpe}"
        # maxDD on cumulative_navs [400120, 400070, 400270]: peak=400270, drop to 400070 → -0.05%
        max_dd = ws._max_drawdown([400120.0, 400070.0, 400270.0])
        assert max_dd is not None and abs(max_dd - (-50.0 / 400120.0)) < 1e-9
        print("  ✓ _read_sleeve_nav round-trip + Sharpe/maxDD computation correct")
    finally:
        ws.SLEEVE_NAV_PATHS = saved_paths


def main() -> int:
    print("=" * 72)
    print("weekly_summary.py smoke tests")
    print("=" * 72)
    _test_module_imports()
    _test_safe_float()
    _test_pearson_correct()
    _test_std()
    _test_diffs()
    _test_sharpe_annualized()
    _test_max_drawdown()
    _test_signal_trajectories_empty()
    _test_signal_trajectories_macro_imbalance()
    _test_r77_nav_no_creds()
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        _test_main_empty_summary(tmp_path)
        _test_main_synthetic(tmp_path)
        _test_read_sleeve_nav_empty(tmp_path)
        _test_read_sleeve_nav_round_trip(tmp_path)
    print()
    print(f"{'='*72}")
    print(f"  ALL SMOKE TESTS PASSED")
    print(f"{'='*72}")
    return 0


if __name__ == "__main__":
    sys.exit(main())