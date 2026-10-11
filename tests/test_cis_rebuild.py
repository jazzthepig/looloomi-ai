"""T-079 / S-531:CIS 按时点重建 —— 滞回、只用 ≤ d 的数据、不能复原的维度记进 missing、与实盘同一个函数。"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.cis.rebuild import (LEVELS, build, crypto_market_data, hysteresis, level_of,  # noqa: E402
                                  score_day, tradfi_market_data)


def test_level_of_matches_signal_cuts() -> None:
    from src.data.cis.cis_provider import get_grade, get_signal
    for s in np.arange(0, 100.01, 0.25):
        assert LEVELS[level_of(float(s))] == get_signal(float(s), get_grade(float(s))), s


def test_hysteresis_needs_two_points_beyond_the_cut() -> None:
    lv = hysteresis([60.0, 65.5, 66.9, 67.1, 64.0, 63.1, 62.9, None, 70.0])
    names = [LEVELS[x] if x is not None else None for x, _ in lv]
    assert names == ["NEUTRAL", "NEUTRAL", "NEUTRAL", "OUTPERFORM", "OUTPERFORM", "OUTPERFORM", "NEUTRAL", "NEUTRAL", "OUTPERFORM"]
    assert [w for _, w in lv][:3] == [None, "up", "up"], "缓冲带内保持原档,标 watch"
    assert lv[4][1] == "down"


def _days(n=500):
    return pd.date_range("2022-01-01", periods=n, freq="D")


def _crypto(seed=0, n=500):
    rng = np.random.default_rng(seed)
    idx = _days(n)
    px = pd.Series(100 * np.cumprod(1 + rng.normal(0, 0.03, n)), index=idx)
    return (px, px * 1e7, px * 1e5, px * 1.02, px * 0.98)


def test_crypto_market_data_uses_only_past_and_flags_missing() -> None:
    px, mc, vol, hi, lo = _crypto()
    d = px.index[400]
    md, miss = crypto_market_data(px, mc, vol, hi, lo, d, {"total_supply": 2e7, "max_supply": None})
    assert abs(md["change_30d"] - (px[d] / px[d - pd.Timedelta(days=30)] - 1) * 100) < 1e-9
    assert abs(md["ath_change_percentage"] - (px[d] / px.loc[:d].max() - 1) * 100) < 1e-9
    assert miss == []
    px2 = px.copy()
    px2.iloc[401:] *= 10                                         # 改 d 之后的数据
    md2, _ = crypto_market_data(px2, mc, vol, hi, lo, d, {"total_supply": 2e7})
    assert md2["ath_change_percentage"] == md["ath_change_percentage"], "不能看到 d 之后"
    _, miss3 = crypto_market_data(px, mc, vol.where(vol.index != d), hi, lo, d, {})
    assert "volume" in miss3 and "total_supply" in miss3


def test_tradfi_uses_last_trading_day_within_four_days() -> None:
    idx = pd.bdate_range("2023-01-02", periods=300)
    cl = pd.Series(np.linspace(100, 130, 300), index=idx)
    sat = idx[200] + pd.Timedelta(days=(5 - idx[200].weekday()) % 7)
    md, _ = tradfi_market_data(cl, cl, cl, cl * 0 + 1000, sat)
    assert md["price"] == cl.loc[:sat].iloc[-1]
    assert tradfi_market_data(cl, cl, cl, cl, idx[-1] + pd.Timedelta(days=10))[0] is None, "停太久 ⇒ 不出分"
    md2, miss2 = tradfi_market_data(cl, cl, cl, cl * 0 + 1000, idx[100], {"market_cap": 1e12, "price": float(cl.iloc[-1])})
    assert abs(md2["market_cap"] - 1e12 * cl.iloc[100] / cl.iloc[-1]) < 1 and miss2 == ["tradfi_market_cap_static"]


def test_score_day_records_non_reconstructable_and_uses_live_function() -> None:
    idx = _days()
    btc = _crypto(1)
    eth = _crypto(2)
    spy_idx = pd.bdate_range(idx[0], idx[-1])
    spy = pd.Series(np.linspace(400, 450, len(spy_idx)), index=spy_idx)
    assets = {"BTC": {"class": "L1"}, "ETH": {"class": "L1"}, "SPY": {"class": "US Equity"}}
    data = {"crypto": {"BTC": btc, "ETH": eth}, "tradfi": {"SPY": (spy, spy, spy, spy * 0 + 1e6)},
            "tvl": {}, "macro": {"fng": {idx[450]: 55.0}, "vix": {}, "total_mcap": {}},
            "funding": {}, "static": {}}
    rows = score_day(idx[450], assets, data)
    assert {r["symbol"] for r in rows} == {"BTC", "ETH", "SPY"}
    eth_row = [r for r in rows if r["symbol"] == "ETH"][0]
    assert "funding" in eth_row["missing"] and "total_supply" in eth_row["missing"]
    assert "vix" in [r for r in rows if r["symbol"] == "SPY"][0]["missing"]
    out = build(assets, data, idx[455], start=idx[440])
    assert {r["signal"] for r in out} <= set(LEVELS) and all("watch" in r for r in out)
    from src.data.cis.rebuild import CODE_REF
    assert all(r["code_ref"] == CODE_REF for r in out)


def test_pct_signal_candidate_ranks_within_group_with_band() -> None:
    from src.data.cis.rebuild import group_pct, pct_hysteresis, pct_level
    assert [pct_level(p) for p in (0.0, 0.1, 0.5, 0.75, 0.95)] == [0, 1, 2, 3, 4]
    rows = [{"d": "2026-01-01", "asset_class": "L1", "score": float(s)} for s in range(10)] + \
           [{"d": "2026-01-01", "asset_class": "US Bond", "score": 40.0}]
    group_pct(rows)
    assert rows[0]["pct"] == 0.05 and rows[9]["pct"] == 0.95, "加密 10 个名字内排"
    assert rows[10]["pct"] is None, "传统资产当天不足 5 个名字不排"
    lv = pct_hysteresis([0.68, 0.72, 0.74, 0.76, 0.66, 0.64], band=0.05)
    assert [x for x, _ in lv] == [2, 2, 2, 3, 3, 2]
    lv10 = pct_hysteresis([0.68, 0.76, 0.79, 0.81, 0.62, 0.59])
    assert [x for x, _ in lv10] == [2, 2, 2, 3, 3, 2], "正式口径 ±10:越过 0.70 要到 0.80,跌回要到 0.60"


def test_pit_fundamentals_only_quarters_already_published() -> None:
    from src.data.cis.rebuild import pit_fundamentals
    q = [{"period_end": f"2023-{m:02d}-28", "available_d": f"2023-{m + 1:02d}-15", "eps": 1.0, "revenue": 100.0} for m in (2, 5, 8, 11) if m < 11] + \
        [{"period_end": "2023-11-28", "available_d": "2024-01-20", "eps": 1.0, "revenue": 100.0}] + \
        [{"period_end": f"2024-{m:02d}-28", "available_d": f"2024-{m + 1:02d}-15", "eps": 2.0, "revenue": 150.0} for m in (2, 5, 8)] + \
        [{"period_end": "2024-11-28", "available_d": "2025-01-20", "eps": 2.0, "revenue": 150.0}]
    f = pit_fundamentals(q, 80.0, pd.Timestamp("2025-01-19"))
    assert abs(f["pe_ratio"] - 80.0 / 7.0) < 1e-9, "2024-11 季还没公布:近四季 = 1 + 2 + 2 + 2"
    assert "revenue_growth_yoy" not in f, "营收同比要 8 个已公布的季度,当时只有 7 个"
    g = pit_fundamentals(q, 80.0, pd.Timestamp("2025-01-20"))
    assert abs(g["pe_ratio"] - 10.0) < 1e-9 and abs(g["revenue_growth_yoy"] - 50.0) < 1e-9
    assert pit_fundamentals(q[:3], 80.0, pd.Timestamp("2025-01-20")) is None


def test_commits_4w_complete_weeks_before_d() -> None:
    from src.data.cis.rebuild import commits_4w
    weeks = {"2026-09-13": 1, "2026-09-20": 2, "2026-09-27": 3, "2026-10-04": 4, "2026-10-11": 100}
    assert commits_4w(weeks, pd.Timestamp("2026-10-14")) == 10, "10-11 那周没走完,不算"
    assert commits_4w(weeks, pd.Timestamp("2026-10-06")) is None, "不满 4 个已知完整周 ⇒ None,不补 0"


def test_churn_counts_changes_and_quick_flip_backs() -> None:
    from src.data.cis.rebuild import churn, label_stats
    days = [f"2026-01-{i:02d}" for i in range(1, 11)]
    assert churn([2, 3, 2, 2, 2, 2, 3, 3, 3, 3], days) == (3, 1), "第 2 天升、第 3 天又回 = 1 次来回跳;第 7 天再升不回"
    rows = [{"symbol": "A", "d": d, "asset_class": "L1", "score": s, "pct": p}
            for d, s, p in zip(days, [60, 66, 60, 60, 60, 60, 70, 70, 70, 70], [0.5, 0.75, 0.5, 0.5, 0.5, 0.5, 0.8, 0.8, 0.8, 0.8])]
    st = label_stats(rows)
    assert set(st["crypto"]) == {"abs_2pt", "pct_5", "pct_10", "pct_15"}
