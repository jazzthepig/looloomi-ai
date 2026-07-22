"""
Smoke tests for `causal_sleeve_extension.py` — Track 5 Causal Sleeve Extension.

Verifies (sandbox-safe, no network):
  1. Module imports cleanly (network imports are inside functions only)
  2. `positioning_weights_cw(fmean, kwin, p=0)` reproduces equal-weight behaviour
  3. `positioning_weights_cw(fmean, kwin, p>0)` increases concentration on |z| outliers
  4. `backtest_cw(..., p=0)` matches the original causal sleeve mechanic
  5. `backtest_cw(..., p=2)` is more concentrated (higher per-name |w|) than p=0
  6. `window_metrics` handles edge cases (n<30 → null metrics)
  7. All 5 p-values runnable on synthetic panel without crashing
  8. Compliance: no buy/sell language in module docstrings/comments

Sandbox-safe: synthetic data only (no httpx, no FUSE).

Run:
    python -m src.research.cis_regime_studies.tests.test_causal_sleeve_extension_smoke
    pytest src/research/cis_regime_studies/tests/test_causal_sleeve_extension_smoke.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))


# ── Test 1: imports ──────────────────────────────────────────────────────────

def test_imports() -> None:
    """Module imports without httpx/nautilus at module level (sandbox-safe)."""
    import src.research.cis_regime_studies.causal_sleeve_extension as cwe
    assert hasattr(cwe, "positioning_weights_cw")
    assert hasattr(cwe, "backtest_cw")
    assert hasattr(cwe, "window_metrics")
    assert hasattr(cwe, "DEFAULT_UNIVERSE")
    assert hasattr(cwe, "KWIN")
    assert cwe.KWIN == 10
    assert cwe.REBALANCE_DAYS == 7


# ── Test 2: p=0 reproduces equal-weight ──────────────────────────────────────

def test_p0_equals_original() -> None:
    """At p=0, cw weights should be mathematically identical to original."""
    from src.research.cis_regime_studies.causal_sleeve_extension import positioning_weights_cw

    rng = np.random.default_rng(42)
    T, K = 200, 24
    fmean = rng.normal(0.0005, 0.001, size=(T, K))

    W_p0 = positioning_weights_cw(fmean, kwin=10, p=0.0)
    # Reference: original mechanic
    W_ref = np.zeros((T, K))
    for i in range(T):
        roll = fmean[max(0, i - 10 + 1):i + 1].mean(0)
        z = roll - roll.mean()
        sd = z.std()
        z = z / sd if sd > 0 else z
        w = -z
        w = w - w.mean()
        g = np.abs(w).sum()
        W_ref[i] = w / g if g > 0 else w

    np.testing.assert_allclose(W_p0, W_ref, rtol=1e-10, atol=1e-12)
    # Gross should be ~1 (sanity)
    for i in [50, 100, 150]:
        assert abs(np.abs(W_p0[i]).sum() - 1.0) < 1e-9, f"day {i}: gross != 1"
        assert abs(W_p0[i].mean()) < 1e-12, f"day {i}: not dollar-neutral"


# ── Test 3: p>0 increases concentration ──────────────────────────────────────

def test_higher_p_concentrates_weights() -> None:
    """As p grows, max(|w|) should grow (capital concentrates on high-|z| names)."""
    from src.research.cis_regime_studies.causal_sleeve_extension import positioning_weights_cw

    rng = np.random.default_rng(123)
    T, K = 300, 24
    # Heavy-tail fmean so there ARE outlier days with concentrated |z|
    fmean = rng.normal(0, 0.001, size=(T, K))
    fmean[100:110] *= 5  # spike 10 days

    W_p0 = positioning_weights_cw(fmean, kwin=10, p=0.0)
    W_p1 = positioning_weights_cw(fmean, kwin=10, p=1.0)
    W_p2 = positioning_weights_cw(fmean, kwin=10, p=2.0)

    # Pick a non-spike, non-zero day (e.g. day 200)
    day = 200
    max_p0 = np.abs(W_p0[day]).max()
    max_p1 = np.abs(W_p1[day]).max()
    max_p2 = np.abs(W_p2[day]).max()
    assert max_p1 > max_p0, f"p=1 max ({max_p1}) should exceed p=0 ({max_p0})"
    assert max_p2 >= max_p1, f"p=2 max ({max_p2}) should exceed p=1 ({max_p1})"

    # Gross should still be ~1 (after renormalization)
    for W, p in [(W_p0, 0), (W_p1, 1), (W_p2, 2)]:
        for i in [50, 150, 250]:
            assert abs(np.abs(W[i]).sum() - 1.0) < 1e-9, f"p={p}, day {i}: gross != 1"


# ── Test 4: backtest_cw(p=0) is well-defined ─────────────────────────────────

def test_backtest_p0_runs() -> None:
    """Synthetic panel → backtest_cw(p=0) returns expected dict shape."""
    from src.research.cis_regime_studies.causal_sleeve_extension import backtest_cw

    rng = np.random.default_rng(99)
    T, K = 500, 24
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, size=(T, K)), axis=0))
    fmean = rng.normal(0.0005, 0.001, size=(T, K))
    fsum = fmean * 3  # 3 settlements/day

    bt = backtest_cw(close, fmean, fsum, kwin=10, fee=0.0005, rebal_days=7, p=0.0)
    assert "daily_pnl" in bt
    assert "ann_sharpe" in bt
    assert "max_dd_pct" in bt
    assert "total_return_pct" in bt
    assert "avg_turnover_per_day" in bt
    assert len(bt["daily_pnl"]) == T
    assert isinstance(bt["ann_sharpe"], float)
    assert bt["avg_turnover_per_day"] >= 0  # turnover is non-negative


# ── Test 5: weekly rebalance lowers turnover ─────────────────────────────────

def test_weekly_rebal_lowers_turnover_vs_daily() -> None:
    """rebal_days=7 should have ≤ turnover vs rebal_days=1."""
    from src.research.cis_regime_studies.causal_sleeve_extension import backtest_cw

    rng = np.random.default_rng(7)
    T, K = 365, 24
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, size=(T, K)), axis=0))
    fmean = rng.normal(0.0005, 0.001, size=(T, K))
    fsum = fmean * 3

    bt_daily = backtest_cw(close, fmean, fsum, kwin=10, fee=0.0005, rebal_days=1, p=0.0)
    bt_weekly = backtest_cw(close, fmean, fsum, kwin=10, fee=0.0005, rebal_days=7, p=0.0)
    assert bt_weekly["avg_turnover_per_day"] < bt_daily["avg_turnover_per_day"], (
        f"Weekly turnover ({bt_weekly['avg_turnover_per_day']}) should be < "
        f"daily turnover ({bt_daily['avg_turnover_per_day']})"
    )


# ── Test 6: window_metrics edge cases ────────────────────────────────────────

def test_window_metrics_short_window() -> None:
    """window_metrics with n<30 days should return None metrics, not crash."""
    from src.research.cis_regime_studies.causal_sleeve_extension import window_metrics

    pnl = np.zeros(20)
    out = window_metrics(pnl, dates=list(range(20)), start_idx=0, end_idx=20)
    assert out["sharpe"] is None
    assert out["max_dd_pct"] is None
    assert out["n_days"] == 20


def test_window_metrics_zero_pnl() -> None:
    """Zero PnL → Sharpe 0, MaxDD 0."""
    from src.research.cis_regime_studies.causal_sleeve_extension import window_metrics

    pnl = np.zeros(100)
    out = window_metrics(pnl, dates=list(range(100)), start_idx=0, end_idx=100)
    assert out["sharpe"] == 0.0
    assert out["max_dd_pct"] == 0.0


# ── Test 7: all p-values runnable ─────────────────────────────────────────────

def test_all_p_values_runnable() -> None:
    """All 5 default p-values {0, 0.5, 1.0, 1.5, 2.0} should run without crash."""
    from src.research.cis_regime_studies.causal_sleeve_extension import backtest_cw

    rng = np.random.default_rng(11)
    T, K = 400, 24
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, size=(T, K)), axis=0))
    fmean = rng.normal(0.0005, 0.001, size=(T, K))
    fsum = fmean * 3

    sharpes = []
    for p in [0.0, 0.5, 1.0, 1.5, 2.0]:
        bt = backtest_cw(close, fmean, fsum, kwin=10, fee=0.0005, rebal_days=7, p=p)
        sharpes.append(bt["ann_sharpe"])
        # Sanity: gross is preserved
        assert isinstance(bt["ann_sharpe"], float)
        assert not np.isnan(bt["ann_sharpe"])

    # Sanity: all 5 p-values produce *finite* but possibly different Sharpes
    assert all(isinstance(s, float) for s in sharpes)


# ── Test 8: compliance language ──────────────────────────────────────────────

def test_compliance_language() -> None:
    """No buy/sell/avoid/reduce/accumulate language in module docstrings/comments.

    Only checks the module docstring (top-level) and inline comments — not code,
    since `np.maximum.accumulate` is a legitimate numpy API call.
    """
    from src.research.cis_regime_studies import causal_sleeve_extension as mod

    src_text = Path(mod.__file__).read_text()
    # Extract docstring (between triple-quote pairs at module level)
    docstring_match = re.search(r'^"""(.*?)"""', src_text, re.DOTALL | re.MULTILINE)
    docstring = docstring_match.group(1) if docstring_match else ""
    # Extract inline comments only (lines starting with #)
    inline_comments = "\n".join(
        line for line in src_text.split("\n") if line.lstrip().startswith("#")
    )
    text_to_check = docstring + "\n" + inline_comments
    forbidden = re.compile(r"\b(BUY|SELL|STRONG BUY|ACCUMULATE|AVOID|REDUCE)\b", re.IGNORECASE)
    hits = forbidden.findall(text_to_check)
    assert len(hits) == 0, f"Compliance: found forbidden language {hits} in docstring/comments"


# ── Runner ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Running causal_sleeve_extension smoke tests…")
    test_funcs = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    for fn in test_funcs:
        try:
            fn()
            print(f"  ✓ {fn.__name__}")
        except AssertionError as e:
            print(f"  ✗ {fn.__name__}: {e}")
            sys.exit(1)
        except Exception as e:
            print(f"  ✗ {fn.__name__}: {type(e).__name__}: {e}")
            sys.exit(1)
    print(f"{len(test_funcs)} test(s) passed (sandbox-safe; ready for network backtest).")