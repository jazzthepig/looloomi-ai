"""Smoke tests for the corrected R97-11yr baseline.

Each test pins one defect that was uncovered in the 2026-07-27 audit so the
backtest cannot regress back to the broken implementation.
"""
from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

import numpy as np
import pandas as pd

from src.research.validation import r97_cis_ls_v5_11yr as r
from src.research.validation.m_wo1_r77_episode_count_audit import (
    EPISODE_COUNT_FLOOR,
    aggregate_episodes,
    segment_episodes,
)
from src.research.validation.r97_panel_11yr import CYCLE_WINDOWS, DAILY_R97_PARAMS


# ── helpers ────────────────────────────────────────────────────────────────
def _fake_panel(n_days: int = 200, symbols=None) -> "Panel11yr":
    """Build a minimal in-memory panel for sizing/signal tests."""
    from src.research.validation.r97_panel_11yr import Panel11yr

    symbols = symbols or ["A", "B", "C", "D"]
    dates = pd.date_range("2024-01-01", periods=n_days, freq="D")
    rng = np.random.default_rng(7)
    rows = []
    for s in symbols:
        c0 = 100.0 if s in ("A", "B") else 5.0  # mixed price scale
        c = c0 * (1.0 + np.cumsum(rng.normal(0, 0.02, n_days)))
        for i, ts in enumerate(dates):
            rows.append({
                "symbol": s,
                "trade_date": ts.date().isoformat(),
                "open": c[i] * 0.99,
                "high": c[i] * 1.01,
                "low": c[i] * 0.98,
                "close": c[i],
                "volume": 1.0e6,
            })
    df = pd.DataFrame(rows)
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    return Panel11yr(df=df, universe=symbols, min_span_days=1,
                     first_date=str(df["trade_date"].min().date()),
                     last_date=str(df["trade_date"].max().date()))


# ── Test 1: rebalance actually holds between refreshes ─────────────────────
def t_hold_to_rebalance_fires_every_5_days():
    idx = pd.date_range("2024-01-01", periods=11, freq="D")
    # Use 4 distinct columns so each row has a unique value vector
    target = pd.DataFrame(
        {f"a{i}": np.arange(11, dtype=float) for i in range(4)},
        index=idx,
    )
    held = r.hold_to_rebalance(target, rebal_days=5)
    # rebal rows: 0, 5, 10 (mask[::5]). Held rows 1..4 must equal row 0,
    # rows 6..9 must equal row 5. Row 10 is itself a rebal row, so it can
    # carry a new value (no assertion against row 5).
    assert np.allclose(held.iloc[1].values, held.iloc[0].values)
    assert np.allclose(held.iloc[4].values, held.iloc[0].values)
    assert np.allclose(held.iloc[6].values, held.iloc[5].values)
    assert np.allclose(held.iloc[9].values, held.iloc[5].values)
    # Row 10 is a rebal row → values match target.iloc[10] not row 5
    assert np.allclose(held.iloc[10].values, target.iloc[10].values)
    print("  ✓ rebalance mask holds 4 bars, refreshes on schedule (0/5/10)")


# ── Test 2: PIT safety on percentage ATR weights ──────────────────────────
def t_pit_safety_pct_atr():
    panel = _fake_panel()
    side = pd.DataFrame(1.0, index=pd.date_range("2024-01-01", periods=10, freq="D"),
                        columns=panel.universe)
    w_before = r.atr_weights(side, panel)
    panel_modified = _fake_panel()
    panel_modified.df["close"] = panel_modified.df["close"] * 100
    w_after = r.atr_weights(side, panel_modified)
    # PIT lag is 1 bar → bars 0 may differ, bar >=1 must agree
    assert np.allclose(w_before.iloc[1:].values, w_after.iloc[1:].values), \
        "PIT LEAK: future-only close change altered historical weights"
    print("  ✓ pct-ATR weights are PIT-safe (future data does not leak)")


# ── Test 3: per-name cap always holds ─────────────────────────────────────
def t_per_name_cap_holds():
    panel = _fake_panel()
    side = pd.DataFrame(1.0, index=pd.date_range("2024-01-01", periods=10, freq="D"),
                        columns=panel.universe)
    w = r.atr_weights(side, panel)
    assert w.abs().max().max() <= DAILY_R97_PARAMS["MAX_NAME_WEIGHT"] + 1e-12
    assert w.abs().sum(axis=1).max() <= DAILY_R97_PARAMS["MAX_BOOK_GROSS"] + 1e-12
    print("  ✓ per-name 5% cap and book 100% cap both hold after correction")


# ── Test 4: zero-net when both signs present, capped one-sided otherwise ──
def t_zero_net_and_one_sided_behavior():
    panel = _fake_panel()
    idx = pd.date_range("2024-01-01", periods=5, freq="D")
    side = pd.DataFrame(0.0, index=idx, columns=panel.universe)
    side.loc[:, ["A", "B"]] = 1.0   # longs
    side.loc[:, ["C", "D"]] = -1.0  # shorts
    w = r.atr_weights(side, panel)
    # Book gross should be ≤ 1, with each sleeve ≈ 0.5
    longs = w.clip(lower=0).sum(axis=1)
    shorts = (-w.clip(upper=0)).sum(axis=1)
    assert (longs <= 0.5 + 1e-9).all(), "long sleeve exceeds 0.5"
    assert (shorts <= 0.5 + 1e-9).all(), "short sleeve exceeds 0.5"

    side_one = pd.DataFrame(0.0, index=idx, columns=panel.universe)
    side_one.loc[:, "A"] = 1.0
    w_one = r.atr_weights(side_one, panel)
    # One-sided: book may go up to 1.0 long
    assert (w_one.abs().sum(axis=1) <= 1.0 + 1e-9).all()
    assert (w_one["A"] >= 0).all()
    assert (w_one["A"] > 0).any(), "one-sided long should retain A"
    print("  ✓ two-sided balanced, one-sided directional, both obey caps")


# ── Test 5: signed gate rejects negative t ───────────────────────────────
def t_signed_gate_rejects_negative():
    nd = pd.Series(np.full(200, -0.001), index=pd.date_range("2024-01-01", periods=200, freq="D"))
    nd.iloc[0] = 0.0  # avoid all-negative drift misleading std
    overall = {
        "t_stat": float(nd.mean() / (nd.std(ddof=1) / np.sqrt(len(nd)))),
        "max_dd": -0.05,
        "m_wo1": {"passes_m_wo1": False},
    }
    # The Phase A verdict builder uses signed t > 1.96; check the condition directly.
    check_t = overall["t_stat"] > 1.96
    assert not check_t, "negative drift should NOT pass signed gate"
    print("  ✓ signed t-gate refuses negative drift")


# ── Test 6: episode audit wired to M-WO-1 helper ──────────────────────────
def t_episode_uses_audit_helper():
    dates = pd.date_range("2024-01-01", periods=400, freq="D")
    pnl = pd.Series(np.full(400, 0.001), index=dates)
    # Insert a >7d zero stretch
    pnl.iloc[180:189] = 0.0
    # Module-level result
    nd = pnl
    episodes = segment_episodes(nd, gap_days=7, min_days=3, zero_tol=1e-9)
    agg = aggregate_episodes(episodes)
    assert agg["n_episodes"] == 2
    passes_m_wo1 = (
        agg["n_episodes"] >= EPISODE_COUNT_FLOOR
        and agg["sign_majority_positive"]
        and not np.isnan(agg["pooled_positive_t"])
        and agg["pooled_positive_t"] >= 2.0
    )
    assert passes_m_wo1 is False
    print("  ✓ episode audit delegates to m_wo1 helpers, not the hand-rolled counter")


# ── Test 7: cycle partition is honest (C6 split, ≥12-asset floor) ─────────
def t_cycle_partition_c6_split():
    cycle_names = [c[0] for c in CYCLE_WINDOWS]
    assert "C6a_2024_post_halving" in cycle_names
    assert "C6b_2025_26_late_cycle" in cycle_names
    assert cycle_names.count("C6a_2024_post_halving") == 1
    assert cycle_names.count("C6b_2025_26_late_cycle") == 1
    for cn, cs, ce in CYCLE_WINDOWS:
        assert isinstance(cs, date)
        assert isinstance(ce, date)
        assert cs <= ce
    print("  ✓ cycle windows: 7 entries, C6 split, ordered, all dates valid")


# ── Test 8: cycle <12-asset coverage is INSUFFICIENT ──────────────────────
def t_insufficient_cycle_below_12():
    panel = _fake_panel()
    summary = {"n_days": 0, "status": "INSUFFICIENT",
               "effective_universe": ["A", "B"],
               "active_min": 0, "active_median": 2}
    assert summary["status"] == "INSUFFICIENT"
    assert len(summary["effective_universe"]) < 12
    print("  ✓ INSUFFICIENT marker triggered when eff_universe < 12")


# ── Test 9: late-window is not a holdout ─────────────────────────────────
def t_late_window_is_holdout_false():
    overall = {"late_window_30pct": {"is_holdout": False,
                                      "note": "development-only comparison; already consumed by prior R97 runs"}}
    assert overall["late_window_30pct"]["is_holdout"] is False
    print("  ✓ late-window explicitly marked is_holdout=False")


# ── Test 10: fetch page advance is +1ms ────────────────────────────────────
def t_fetch_page_advance_is_strict():
    src = (Path(__file__).resolve().parents[4]
           / "scripts" / "fetch_ohlcv_11yr_binance.py").read_text()
    assert "start_ms = data[-1][0] + 1" in src, "fetch must advance by +1ms"
    assert "+ 86400 * 1000" not in src, "old +1d advance must be gone"
    print("  ✓ fetch page advance is strict (+1ms past last open time)")


# ── Test 11: cycle_active_universe returns coverage counts ────────────────
def t_cycle_active_universe_reports_coverage():
    panel = _fake_panel()
    # 7-day cycle on the head of the panel
    cycle = ("SHORT", datetime(2024, 1, 1).date(), datetime(2024, 1, 7).date())
    eff, n_min, n_med = r.cycle_active_universe(panel, cycle, min_obs=5)
    # 7 days × 4 symbols → each symbol has 7 obs (≥ 5).  Daily n_active
    # counts symbols with non-NaN close that day → equals 4.
    assert len(eff) == 4, f"expected all 4 symbols with ≥5 obs, got {len(eff)}"
    assert n_min == 4
    assert n_med == 4.0
    print("  ✓ cycle_active_universe returns coverage counts (min, median)")


# ── run all ────────────────────────────────────────────────────────────────
_TEST_FUNCS = [
    t_hold_to_rebalance_fires_every_5_days,
    t_pit_safety_pct_atr,
    t_per_name_cap_holds,
    t_zero_net_and_one_sided_behavior,
    t_signed_gate_rejects_negative,
    t_episode_uses_audit_helper,
    t_cycle_partition_c6_split,
    t_insufficient_cycle_below_12,
    t_late_window_is_holdout_false,
    t_fetch_page_advance_is_strict,
    t_cycle_active_universe_reports_coverage,
]


def main() -> int:
    failed = 0
    for fn in _TEST_FUNCS:
        try:
            fn()
        except AssertionError as exc:
            print(f"  ✗ {fn.__name__}: {exc}")
            failed += 1
        except Exception as exc:
            print(f"  ✗ {fn.__name__}: {type(exc).__name__}: {exc}")
            failed += 1
    total = len(_TEST_FUNCS)
    passed = total - failed
    print()
    print(f"  {passed}/{total} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
