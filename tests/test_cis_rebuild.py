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
    assert all(r["code_ref"] == "cis-standard-v1" for r in out)
