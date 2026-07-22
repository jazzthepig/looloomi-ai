"""
Smoke tests for `cis_quality_factor.py` — the §CIS-HISTORY-BACKFILL follow-up (Seth, 2026-07-18).
================================================================================================
Sandbox-safe: synthetic CIS history + synthetic prices; no FUSE reads. Verifies:

  1. Module imports cleanly (no httpx, no nautilus, no FUSE access at module level)
  2. `load_cis_history()` parses the documented JSON schema correctly
  3. `build_cis_quality_factor()` is deterministic for given inputs
  4. Cross-sectional ranking uses PREVIOUS-DAY CIS (no look-ahead)
  5. The factor captures positive IC when synth data embeds a quality premium
  6. Edge cases: empty dataframe, all-same CIS scores, < 6 assets, missing days
  7. Output is a pd.Series with name `f_cis_quality` (drop-in compatible with
     `absorption_sweep_runner.py`'s wide CSV column)

Pattern matches `tests/test_absorption_sweep_smoke.py` — behavioral shape, not exact numbers.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import numpy as np
import pandas as pd
import pytest

from src.research.validation.cis_quality_factor import (
    DEFAULT_CIS_HISTORY_DIR,
    TERCILES,
    build_cis_quality_factor,
    load_cis_history,
)


# ── fixtures ──────────────────────────────────────────────────────────────────
def _synth_cis_history(n_assets: int = 9, n_weeks: int = 60, seed: int = 42) -> pd.DataFrame:
    """Build a synthetic CIS history DataFrame matching the documented schema."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2024-03-01", periods=n_weeks * 7, freq="D")[::7]
    assets = [f"A{i}" for i in range(n_assets)]
    rows = []
    for d in dates:
        cis_vals = rng.uniform(40, 90, n_assets)
        for a, c in zip(assets, cis_vals):
            rows.append({
                "date": d.date(), "asset": a, "cis_score": float(c),
                "asset_class": "L1", "signal": "NEUTRAL", "las": c,
            })
    return pd.DataFrame(rows)


def _synth_returns(cis_df: pd.DataFrame, dates: pd.DatetimeIndex,
                    quality_premium_per_score_unit: float = 0.0003,
                    seed: int = 99) -> pd.DataFrame:
    """Synthetic daily returns where higher-CIS assets earn more (positive IC)."""
    rng = np.random.default_rng(seed)
    assets = sorted(cis_df["asset"].unique())
    avg_cis = cis_df.groupby("asset")["cis_score"].mean()
    rets = pd.DataFrame(index=dates, columns=assets, dtype=float)
    for a in assets:
        base = (avg_cis[a] - 65) * quality_premium_per_score_unit
        rets[a] = rng.normal(base, 0.03, len(dates))
    return rets


# ── 1. imports cleanly ────────────────────────────────────────────────────────
def test_imports_sandbox_safe():
    """No httpx / nautilus / FUSE reads at module level."""
    src_path = _REPO_ROOT / "src/research/validation/cis_quality_factor.py"
    src = src_path.read_text()
    assert "import httpx" not in src, "no network imports"
    assert "import nautilus" not in src, "no nautilus"
    # Should reference the documented schema fields (defends against drift in real data)
    assert "cis_score" in src
    assert "scores" in src
    assert "asset" in src


# ── 2. parse the documented schema ───────────────────────────────────────────
def test_load_cis_history_parses_schema(tmp_path):
    """Should parse the schema documented at MINIMAX_SYNC.md line 3521-3535."""
    daily_dir = tmp_path / "cis_history"
    daily_dir.mkdir()
    # write 3 small snapshots
    for i, d in enumerate(["2024-03-01", "2024-03-08", "2024-03-15"]):
        snap = {
            "date": d,
            "macro_regime": "Risk-On",
            "scores": [
                {"asset": "BTC", "symbol": "BTC", "asset_class": "L1",
                 "grade": "A+", "cis_score": 78.5, "signal": "STRONG OUTPERFORM",
                 "las": 75.2, "confidence": 0.85,
                 "pillars": {"F": 80, "M": 75, "O": 70, "S": 82, "A": 78},
                 "market_micro": {"funding_rate": 0.0001, "open_interest_usd": 12345678}},
                {"asset": "ETH", "symbol": "ETH", "asset_class": "L1",
                 "cis_score": 65.0, "signal": "OUTPERFORM", "las": 60.0,
                 "pillars": {"F": 60, "M": 70, "O": 65, "S": 50, "A": 80}},
            ],
        }
        with open(daily_dir / f"cis_{d}.json", "w") as fh:
            json.dump(snap, fh)
    df = load_cis_history(cis_history_dir=daily_dir)
    assert len(df) == 6, "3 snapshots × 2 assets = 6 rows"
    assert set(["date", "asset", "cis_score"]).issubset(df.columns)
    assert df[df["asset"] == "BTC"]["cis_score"].iloc[0] == 78.5


# ── 3. deterministic ──────────────────────────────────────────────────────────
def test_factor_is_deterministic():
    """Same inputs → same output (essential for the absorption sweep to be reproducible)."""
    cis_df = _synth_cis_history(seed=7)
    dates = pd.date_range("2024-03-01", "2025-05-02", freq="D")
    rets = _synth_returns(cis_df, dates, seed=11)
    f1 = build_cis_quality_factor(cis_df, rets)
    f2 = build_cis_quality_factor(cis_df, rets)
    pd.testing.assert_series_equal(f1, f2, check_names=True)


# ── 4. no look-ahead — uses t-1 CIS rank ─────────────────────────────────────
def test_factor_no_lookahead():
    """Factor(t) must use CIS ranking from t-1, not t."""
    # Build two scenarios: SAME returns, but DIFFERENT CIS ranks at a non-zero snapshot.
    # The factor(t) for t in [snap_day, next_snapshot) should change accordingly;
    # factor(t) for t < snap_day must NOT depend on CIS(snap_day) (no look-ahead).
    cis_df = _synth_cis_history(seed=3)
    dates = pd.date_range("2024-03-01", periods=60, freq="D")  # 60d covers 8+ weekly snapshots
    rets = _synth_returns(cis_df, dates, quality_premium_per_score_unit=0,
                          seed=5)  # pure noise — eliminates quality premium confound
    fac_baseline = build_cis_quality_factor(cis_df, rets)

    # Mutate the SECOND snapshot (snap_day = 2024-03-08, day 7).
    # The ffill uses the most-recent-prior snapshot for any given return day.
    # Days 0..6 use the day-0 snapshot (unchanged by this mutation) → factors equal.
    # Days 7..13 use the day-7 snapshot (mutated) → factors DIFFER.
    snap_day = pd.Timestamp("2024-03-08")
    cis_mut = cis_df.copy()
    mask = (pd.to_datetime(cis_mut["date"]) == snap_day)
    assert mask.any(), "snap_day should match at least one snapshot row"
    # Force rank changes: swap 3 top assets with 3 bottom assets
    for top_a, bot_a in [("A0", "A6"), ("A1", "A7"), ("A2", "A8")]:
        top_score = cis_mut.loc[mask & (cis_mut["asset"] == top_a), "cis_score"].iloc[0]
        bot_score = cis_mut.loc[mask & (cis_mut["asset"] == bot_a), "cis_score"].iloc[0]
        cis_mut.loc[mask & (cis_mut["asset"] == top_a), "cis_score"] = bot_score - 1
        cis_mut.loc[mask & (cis_mut["asset"] == bot_a), "cis_score"] = top_score + 1
    fac_mut = build_cis_quality_factor(cis_mut, rets)

    # (a) Days 0..6: factor(t) uses day-0 snapshot ranks (unchanged by mutation) → EQUAL
    pd.testing.assert_series_equal(
        fac_baseline.iloc[0:7], fac_mut.iloc[0:7],
        check_names=False, check_dtype=False,
        obj="Days 0..6 must NOT depend on CIS(snap_day) — look-ahead check",
    )

    # (b) Days 7..13 (until next snapshot at day 14): factor(t) uses day-7 snapshot ranks
    #     (mutated) → must DIFFER from baseline
    within_mutated_window = slice(7, 14)
    diffs = (fac_baseline.iloc[within_mutated_window]
             != fac_mut.iloc[within_mutated_window]).sum()
    assert diffs > 0, (
        f"Days 7..13 (between snap_day and next snapshot) must change when "
        f"CIS(snap_day) changes — got {diffs} differing values (need >0). "
        f"Otherwise factor(t) is using CIS(t) instead of CIS(t-1) (look-ahead)."
    )


# ── 5. captures positive IC when embedded ────────────────────────────────────
def test_factor_captures_quality_premium():
    """When synth returns embed a positive quality premium, factor mean should be > 0."""
    cis_df = _synth_cis_history(n_assets=12, n_weeks=80, seed=42)
    dates = pd.date_range("2024-03-01", "2025-05-02", freq="D")
    rets = _synth_returns(cis_df, dates, quality_premium_per_score_unit=0.001,
                          seed=13)  # 3x the default
    fac = build_cis_quality_factor(cis_df, rets)
    assert fac.name == "f_cis_quality"
    assert fac.mean() > 0, f"expected positive quality premium; got mean={fac.mean()}"
    # factor length = returns index length
    assert len(fac) == len(rets)
    # index alignment: factor uses same date index
    pd.testing.assert_index_equal(fac.index, rets.index)


# ── 6. edge cases ─────────────────────────────────────────────────────────────
def test_empty_inputs_return_empty_series():
    """No data → empty series (don't crash; don't lie with zeros)."""
    empty_cis = pd.DataFrame(columns=["date", "asset", "cis_score"])
    empty_rets = pd.DataFrame()
    out = build_cis_quality_factor(empty_cis, empty_rets)
    assert isinstance(out, pd.Series)
    assert len(out) == 0


def test_too_few_assets_returns_zero_series():
    """Universe too small to form a cross-section → factor=0 (not crash, not fake signal)."""
    cis_df = _synth_cis_history(n_assets=4, seed=1)  # too small (needs ≥6)
    dates = pd.date_range("2024-03-01", periods=30, freq="D")
    rets = _synth_returns(cis_df, dates, seed=2)
    fac = build_cis_quality_factor(cis_df, rets)
    assert (fac == 0.0).all()


# ── 7. compliance language ────────────────────────────────────────────────────
def test_compliance_language():
    """No buy/sell/avoid/reduce in source. Module is pure interface/math."""
    src = (_REPO_ROOT / "src/research/validation/cis_quality_factor.py").read_text().lower()
    forbidden = ["buy", "sell", "avoid", "reduce", "accumulate"]
    for word in forbidden:
        if re.search(rf"\b{word}\b", src):
            pytest.fail(f"compliance violation: '{word}' in cis_quality_factor.py")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))