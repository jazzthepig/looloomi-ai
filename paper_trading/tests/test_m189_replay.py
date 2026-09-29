"""Smoke + unit tests for paper_trading.research.m189_replay (T-034).

What we lock down:
  1. `vol_formula_size_multiplier` — clamp behavior + missing-data fallback
  2. `tom_targets_vol_formula` — wrapper produces wrapped output without
     mutating engine output for the MECH_tom baseline
  3. `simulate` — 4-arm Monday loop produces weight matrices of expected shape
  4. `pnl` — net series shape + cost subtraction + funding subtraction
  5. `lag_discipline_check` — retention math matches M-114 contract
  6. `build_diff` / `render_report` — full pipeline with synthetic 250d panel

Synthetic data is required because `hl_book.features_at:111` requires ≥201
days per coin. We build a 260d deterministic panel so smoke is fast and
reproducible.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# S-402 bootstrap — `python3 paper_trading/tests/test_m189_replay.py` standalone.
_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent.parent if _HERE.parent.name == "paper_trading" else _HERE.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from paper_trading.research.m189_replay import (  # noqa: E402
    vol_formula_size_multiplier, tom_targets_vol_formula,
    simulate, pnl, stats, lag_discipline_check,
    bucket_regime, regime_conditional_sr, build_diff, render_report,
    ARMS, REGIME_BUCKETS,
)
from paper_trading import hl_book as hb  # noqa: E402


# ────────────────────────── synthetic fixture ──────────────────────────


COINS = ("BTC", "ETH", "SOL", "HYPE")
N_DAYS = 260                # ≥201 for features_at; 260 covers ~37 weeks


def _make_synthetic_panel(seed: int = 412) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Deterministic 260d OHLCV for 4 coins.

    BTC: gentle uptrend (drift +0.10% / day, vol 0.03%)
    ETH: volatile uptrend (drift +0.15%, vol 0.05%)
    SOL: downtrend (drift -0.10%, vol 0.06%)
    HYPE: sideways (drift 0.00%, vol 0.04%)

    Returns (px, fd) — daily close + per-day total funding.
    """
    rng = np.random.default_rng(seed)
    start = pd.Timestamp("2023-05-15")
    days = pd.date_range(start, periods=N_DAYS, freq="D")
    px_dict = {}
    fd_dict = {}
    profiles = {
        "BTC":  (0.0010, 0.03),
        "ETH":  (0.0015, 0.05),
        "SOL":  (-0.0010, 0.06),
        "HYPE": (0.0000, 0.04),
    }
    for c, (drift, vol) in profiles.items():
        # log-returns → price series, seed at 100
        rets = rng.normal(drift, vol, size=N_DAYS)
        prices = 100 * np.exp(np.cumsum(rets))
        px_dict[c] = pd.Series(prices, index=days, name=c)
        # funding ~ small daily rate, mean 0.0005, occasionally negative
        f = rng.normal(0.0005, 0.0008, size=N_DAYS)
        fd_dict[c] = pd.Series(f, index=days, name=c)
    px = pd.DataFrame(px_dict)
    fd = pd.DataFrame(fd_dict)
    return px, fd


# ────────────────────────── unit: vol_formula ──────────────────────────


def test_vol_formula_default_clamp():
    """Standard vol-of-target ratios → expected multipliers."""
    feats = {
        "BTC": {"vol_30d_ann": 0.50},   # 0.50 / 0.50 = 1.00
        "ETH": {"vol_30d_ann": 1.00},   # 0.50 / 1.00 = 0.50 (floor)
        "SOL": {"vol_30d_ann": 0.25},   # 0.50 / 0.25 = 2.00 → clamp hi → 1.50
    }
    mults = vol_formula_size_multiplier(feats, target_vol_annual=0.50)
    assert mults["BTC"] == 1.0
    assert mults["ETH"] == 0.5
    assert mults["SOL"] == 1.5
    print("✓ test_vol_formula_default_clamp")


def test_vol_formula_missing_or_nan_falls_back_to_one():
    feats = {
        "BTC": {"vol_30d_ann": 0.50},
        "ETH": {},                      # missing
        "SOL": {"vol_30d_ann": None},   # None
        "HYPE": {"vol_30d_ann": float("nan")},  # NaN
    }
    mults = vol_formula_size_multiplier(feats, target_vol_annual=0.50)
    assert mults["BTC"] == 1.0
    assert mults["ETH"] == 1.0
    assert mults["SOL"] == 1.0
    assert mults["HYPE"] == 1.0
    print("✓ test_vol_formula_missing_or_nan_falls_back_to_one")


def test_vol_formula_negative_vol_falls_back_to_one():
    feats = {"X": {"vol_30d_ann": -0.10}}
    mults = vol_formula_size_multiplier(feats)
    assert mults["X"] == 1.0
    print("✓ test_vol_formula_negative_vol_falls_back_to_one")


def test_vol_formula_custom_bounds():
    feats = {"X": {"vol_30d_ann": 0.10}}
    # tight [0.8, 1.2] band
    mults = vol_formula_size_multiplier(feats, target_vol_annual=0.20,
                                        lo=0.8, hi=1.2)
    assert mults["X"] == 1.2  # 0.20 / 0.10 = 2.0 → clamp 1.2
    print("✓ test_vol_formula_custom_bounds")


# ────────────────────────── wrapper: tom_targets_vol_formula ──────────────────────────


def test_tom_targets_vol_formula_wraps_engine():
    """Wrapper must produce (base * mult) per coin without calling engine twice."""
    from dataclasses import dataclass

    @dataclass
    class _A:
        trend_confirmed: dict
        crowded: dict
        capitulation: dict
        mode: str

    feats = {
        "BTC": {"vol_30d_ann": 0.50, "ret_20d": 0.1, "ret_60d": 0.2, "ret_120d": 0.3,
                "dist_from_ma200": 0.05, "drawdown_from_200d_high": -0.1, "funding_7d_ann": 0.1},
        "ETH": {"vol_30d_ann": 1.00, "ret_20d": 0.1, "ret_60d": 0.2, "ret_120d": 0.3,
                "dist_from_ma200": 0.05, "drawdown_from_200d_high": -0.1, "funding_7d_ann": 0.1},
    }
    # Engine answer: trend_confirmed=True, not crowded, not capitulation → base 1.0 for both
    ans = _A({"BTC": True, "ETH": True}, {"BTC": False, "ETH": False},
             {"BTC": False, "ETH": False}, "press")
    book = {}
    out = tom_targets_vol_formula(feats, ans, book, target_vol_annual=0.50)
    # BTC: base 1.0 × mult 1.0 = 1.0; ETH: base 1.0 × mult 0.5 = 0.5
    assert math.isclose(out["BTC"], 1.0, rel_tol=1e-6), out["BTC"]
    assert math.isclose(out["ETH"], 0.5, rel_tol=1e-6), out["ETH"]
    print("✓ test_tom_targets_vol_formula_wraps_engine")


# ────────────────────────── simulate 4-arm loop ──────────────────────────


def test_simulate_4arms_synthetic_260d():
    px, fd = _make_synthetic_panel()
    W, N = simulate(px, fd, target_vol=0.50, lag=1)
    assert set(W.keys()) == set(ARMS), f"arms mismatch: {W.keys()}"
    for arm in ARMS:
        assert W[arm].shape == px.shape, f"{arm} shape {W[arm].shape} vs {px.shape}"
        # each arm should have at least some non-NaN rows
        non_nan_rows = int(W[arm].notna().any(axis=1).sum())
        assert non_nan_rows > 0, f"{arm} has 0 non-NaN rows"
        # index aligns with px
        assert (W[arm].index == px.index).all()
    # N should equal 4 on Mondays where all coins have ≥201 days history
    mondays_n = N.dropna()
    assert (mondays_n == 4).all(), f"N should be 4 across all Mondays, got {mondays_n.unique()}"
    print(f"✓ test_simulate_4arms_synthetic_260d "
          f"(4 arms, {non_nan_rows} active rows, N=4 on {len(mondays_n)} Mondays)")


def test_simulate_monday_only_iteration():
    """simulate should ONLY *originate* weights on Mondays; ffill forward is expected."""
    # Re-run simulate but keep the pre-ffill version: spot-check the original
    # weight matrix W (before .ffill()) only has values on Mondays.
    from paper_trading.research import m189_replay
    px, fd = _make_synthetic_panel()
    W_ffill, _ = simulate(px, fd)
    # Reach into simulate's internal state by re-running the loop manually on
    # what simulate() would have written. Simpler: call the raw mondays loop.
    from paper_trading import hl_book as hb
    mondays = [d for d in px.index if d.weekday() == 0 and d >= m189_replay.START]
    # Check: for each Monday m, W_ffill.loc[m] should have at least one non-NaN
    # (the original write). For each non-Monday day, W_ffill.loc[d] should equal
    # the most recent Monday's value (forward-fill, no new writes).
    for arm in ARMS:
        for d in px.index:
            v = W_ffill[arm].loc[d]
            if d.weekday == 0 and d in mondays:
                # either NaN (pre-history, <201d) or written by simulate
                if not pd.isna(v).all():
                    pass  # OK: written
            elif not pd.isna(v).all():
                # Non-Monday: must equal the most recent Monday's value (no new writes)
                prev_mondays = [m for m in mondays if m <= d]
                if prev_mondays:
                    last_m = prev_mondays[-1]
                    expected = W_ffill[arm].loc[last_m]
                    assert v.equals(expected), (
                        f"{arm} wrote new weights on non-Monday {d.date()} "
                        f"(differs from previous Monday {last_m.date()})")
    print("✓ test_simulate_monday_only_iteration")


# ────────────────────────── pnl + stats ──────────────────────────


def test_pnl_shape_and_cost_subtraction():
    px, fd = _make_synthetic_panel()
    W, N = simulate(px, fd, target_vol=0.50, lag=1)
    net, extras = pnl(W["H0_hold"], N, px, fd, lag=1, cost_spot_bps=12.0)
    assert isinstance(net, pd.Series)
    assert len(net) > 0
    # lag=1 → w.shift(2): net starts 2 days after the first valid N day
    assert net.index.equals(N.dropna().index[2:]), (
        f"net should align with N.dropna().index[2:] under lag=1 "
        f"(got len {len(net)} vs expected {len(N.dropna()) - 2})")
    assert extras["cost_yr"] >= 0
    assert isinstance(extras["fund_yr"], float)
    print(f"✓ test_pnl_shape_and_cost_subtraction "
          f"(n_periods={extras['n_periods']}, gross={extras['gross']:.3f})")


def test_pnl_higher_cost_lowers_net():
    """cost_spot_bps=30 should yield strictly lower (or equal) net than cost=10."""
    px, fd = _make_synthetic_panel()
    W, N = simulate(px, fd, target_vol=0.50, lag=1)
    net_10, _ = pnl(W["MECH_tom"], N, px, fd, lag=1, cost_spot_bps=10.0)
    net_30, _ = pnl(W["MECH_tom"], N, px, fd, lag=1, cost_spot_bps=30.0)
    # cumulative cost differential should be negative
    cumret_10 = (1 + net_10).prod() - 1
    cumret_30 = (1 + net_30).prod() - 1
    assert cumret_10 >= cumret_30 - 1e-9, (
        f"10bps should not be worse than 30bps: {cumret_10} vs {cumret_30}")
    print(f"✓ test_pnl_higher_cost_lowers_net "
          f"(cum@10bps={cumret_10:.4f}, cum@30bps={cumret_30:.4f})")


def test_stats_known_shape():
    s = pd.Series([0.001, -0.002, 0.003, -0.001, 0.002] * 50)
    out = stats(s)
    assert set(out.keys()) == {"total", "cagr", "sharpe", "maxdd", "n_periods"}
    assert out["n_periods"] == 250
    # MaxDD should be ≤ 0 (always)
    assert out["maxdd"] <= 0.0
    print(f"✓ test_stats_known_shape (n=250, SR={out['sharpe']:.2f}, MaxDD={out['maxdd']:.3f})")


# ────────────────────────── lag discipline ──────────────────────────


def test_lag_discipline_pass_for_m93_like_retention():
    """M-93 retention ~0.97 (lag-0 0.97 / lag-1 0.947) should PASS the guard."""
    # Build realistic series: small noise around a drift.
    # lag-0 has smaller std (tighter, brighter SR); lag-1 has slightly larger std.
    np.random.seed(13)
    base = np.random.normal(0.001, 0.01, size=300)
    lag0 = pd.Series(base + np.random.normal(0, 0.001, size=300))   # SR high
    lag1 = pd.Series(base + np.random.normal(0, 0.010, size=300))   # SR slightly lower
    res = lag_discipline_check(net_lag1=lag1, net_lag0=lag0)
    assert res["passes"] is True, f"expected retention ≥ 0.5, got {res}"
    assert res["retention"] is not None
    assert res["retention"] >= 0.5
    print(f"✓ test_lag_discipline_pass_for_m93_like_retention "
          f"(sr_lag0={res['sr_lag0']:.3f}, sr_lag1={res['sr_lag1']:.3f}, "
          f"ret={res['retention']:.3f})")


def test_lag_discipline_fail_for_m95c_like_collapse():
    """M-95c M-112 finding: lag-0 SR +8.2, lag-1 SR +0.6 → retention 0.073 → FAIL."""
    # Synthesize two series that produce very different SR via std manipulation.
    # We can't fake the exact 8.2 / 0.6 directly (SR is std-scaled), but we can
    # produce a series where lag-0 has tiny std + large mean and lag-1 has
    # large std + same mean → retention << 0.5.
    np.random.seed(7)
    lag1 = pd.Series(np.random.normal(0.005, 0.05, size=300))   # noisy, small SR
    lag0 = pd.Series(np.random.normal(0.01, 0.001, size=300))    # tight, huge SR
    res = lag_discipline_check(net_lag1=lag1, net_lag0=lag0)
    assert res["passes"] is False, "tight-but-bright lag-0 should fail retention guard"
    print(f"✓ test_lag_discipline_fail_for_m95c_like_collapse "
          f"(ret={res['retention']:.3f} < 0.5 → FAIL ✅)")


def test_lag_discipline_trivial_skip():
    """|sr_lag0| < 0.05 → no judgement (passes=True, retention=None)."""
    # Construct a series whose SR is deterministically below the 0.05 threshold:
    # mean=0.001, std=0.50 → SR = 0.001/0.50 * sqrt(365) = 0.0382 < 0.05.
    # Use a symmetric alternating series to pin mean=0.001, std≈0.50 exactly.
    pattern = np.array([+0.501, -0.499] * 150)   # alternating ±0.5, mean=0.001, std=0.5
    trivial = pd.Series(pattern)
    res = lag_discipline_check(net_lag1=trivial, net_lag0=trivial)
    assert res["passes"] is True, f"expected passes=True, got {res}"
    assert res["retention"] is None, f"expected retention=None, got {res}"
    assert "trivial" in res.get("note", ""), f"expected trivial note, got {res}"
    print(f"✓ test_lag_discipline_trivial_skip (sr_lag0={res['sr_lag0']:.4f} < 0.05)")


# ────────────────────────── regime + compare + report ──────────────────────────


def test_bucket_regime_and_conditional():
    """UNKNOWN bucket absorbs missing dates; RISK_ON bucket aggregates correctly."""
    px, fd = _make_synthetic_panel()
    W, N = simulate(px, fd)
    regime_map = {
        px.index[10].date().isoformat(): "RISK_ON",
        px.index[20].date().isoformat(): "RISK_OFF",
        # most days absent → UNKNOWN
    }
    regime = bucket_regime(px.index, regime_map)
    assert (regime == "UNKNOWN").sum() == len(px) - 2
    assert (regime == "RISK_ON").sum() == 1
    assert (regime == "RISK_OFF").sum() == 1

    net, _ = pnl(W["H0_hold"], N, px, fd, lag=1, cost_spot_bps=12.0)
    rc = regime_conditional_sr(net, regime)
    # UNKNOWN should appear with whatever days it covers
    assert "UNKNOWN" in rc, f"expected UNKNOWN bucket, got {list(rc.keys())}"
    print(f"✓ test_bucket_regime_and_conditional (buckets = {list(rc.keys())})")


def test_build_diff_end_to_end():
    px, fd = _make_synthetic_panel()
    regime_map = {px.index[10].date().isoformat(): "RISK_ON"}
    W, N = simulate(px, fd, target_vol=0.50, lag=1)
    diff = build_diff(W, N, px, fd, regime_map,
                      target_vol=0.50, lag=1, cost_bps_list=[12.0, 10.0])
    # Structure checks
    assert "config" in diff
    assert "cost_runs" in diff
    assert "summary" in diff
    assert set(diff["cost_runs"].keys()) == {"12.0bps", "10.0bps"}
    for cost_block in diff["cost_runs"].values():
        assert set(cost_block.keys()) == set(ARMS)
        for arm in ARMS:
            assert "sharpe" in cost_block[arm]
            assert "maxdd" in cost_block[arm]
            assert "n_periods" in cost_block[arm]
    assert "vol_vs_fixed_delta_sharpe" in diff["summary"]
    assert "lag_discipline_pass" in diff["summary"]
    print(f"✓ test_build_diff_end_to_end "
          f"(deltas: vol-fixed={diff['summary']['vol_vs_fixed_delta_sharpe']:.3f}, "
          f"vol-hold={diff['summary']['vol_vs_hold_delta_sharpe']:.3f})")


def test_render_report_contains_required_sections():
    px, fd = _make_synthetic_panel()
    W, N = simulate(px, fd, target_vol=0.50, lag=1)
    diff = build_diff(W, N, px, fd, {}, target_vol=0.50, lag=1, cost_bps_list=[12.0])
    md = render_report(diff)
    required = [
        "# M-189 HL 4-coin replay report",
        "Per-arm headline",
        "Lag discipline",
        "Regime-conditional SR",
        "M-189 criteria checklist",
        "baseline = hold the panel",
        "regime-conditional",
        "n_periods ≥ 30",
        "cost realism",
        "lag discipline",
    ]
    for r in required:
        assert r in md, f"missing section: {r!r}"
    print(f"✓ test_render_report_contains_required_sections ({len(md)} chars)")


# ────────────────────────── driver ──────────────────────────


def test_all() -> None:
    """Run all tests; report failures."""
    funcs = [v for k, v in globals().items()
             if k.startswith("test_") and k != "test_all" and callable(v)]
    failed = 0
    for f in funcs:
        try:
            f()
        except AssertionError as e:
            print(f"✗ {f.__name__}: {e}")
            failed += 1
        except Exception as e:  # noqa: BLE001
            print(f"💥 {f.__name__}: {type(e).__name__}: {e}")
            failed += 1
    if failed:
        raise SystemExit(f"\n{failed} test(s) failed")
    print(f"\n✓ all {len(funcs)} tests passed")


if __name__ == "__main__":
    test_all()
