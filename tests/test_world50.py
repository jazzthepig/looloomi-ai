"""World50(T-098 / S-577 / S-578):候选池、动量分、等权 × 有界分数、缓冲选成分、整段复权重取。"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.universe.world50 import (CANDIDATES, eodhd_candidates, equal_weights, momentum_scores,  # noqa: E402
                                       momentum_values, select_members, tilt_weights)


def test_candidate_pool_is_assets_not_funds():
    keys = [c.key for c in CANDIDATES]
    assert len(keys) == len(set(keys)), "symbol 必须唯一"
    assert {c.cls for c in CANDIDATES} == {"equity", "metal", "crypto"}
    for etf in ("SPY", "VOO", "IVV", "QQQ", "VTI", "VUG", "VEA", "GLD", "SLV"):
        assert etf not in keys, f"{etf} 是一篮子,会重复计算 —— World50 不收基金"
    for c in CANDIDATES:
        assert c.onchain is None, "链上形式还没量,不能先写死(T-098 的映射表填)"
    assert all("." in c.code for c in eodhd_candidates()), "EODHD 代码要带交易所后缀"
    assert len(eodhd_candidates()) >= 90 and sum(c.cls == "crypto" for c in CANDIDATES) == 5
    assert any("曾经的龙头" in c.note for c in CANDIDATES), "按时点回放要有今天掉出去的公司"


def test_momentum_values_skip_and_none_not_zero():
    up = [100 * 1.02 ** i for i in range(14)]
    m6, m12 = momentum_values(up)
    assert m6 > 0 and m12 > m6
    assert momentum_values(up[:6]) == (None, None), "不到 7 个月末:不可算"
    m6s, m12s = momentum_values(up[:9])
    assert m6s is not None and m12s is None, "不到 13 个:只有 6 个月"
    flat = [100.0] * 14
    assert momentum_values(flat) == (None, None), "零波动不能除"


def test_scores_are_bounded_and_ordered():
    vals = {f"a{i}": (float(i), float(i)) for i in range(20)}
    vals["huge"] = (1e6, 1e6)
    vals["no6"] = (None, 1.0)
    s = momentum_scores(vals)
    assert "no6" not in s, "没有 6 个月动量不出分"
    assert all(0.25 - 1e-9 <= v <= 4.0 + 1e-9 for v in s.values()), "截 ±3 ⇒ 分数在 [0.25, 4]"
    assert s["huge"] == max(s.values()) and s["a0"] == min(s.values())
    only6 = momentum_scores({"x": (1.0, None), "y": (-1.0, None)})
    assert only6["x"] > 1 > only6["y"]


def test_tilt_without_caps_stays_diversified_at_fifty():
    members = [f"m{i}" for i in range(50)]
    extreme = {m: 0.25 for m in members}
    extreme["m0"] = 4.0
    w = tilt_weights(members, extreme)
    assert abs(sum(w.values()) - 1) < 1e-12
    assert w["m0"] < 0.25, "一个最强、其余最弱也到不了 25%"
    typical = momentum_scores({m: (float(i % 7 - 3), float(i % 5 - 2)) for i, m in enumerate(members)})
    wt = tilt_weights(members, typical)
    assert max(wt.values()) <= 0.08 + 1e-9, "50 个成分、2% 为底:单一权重天然 ≤ 约 8%"
    assert equal_weights(members)["m7"] == pytest.approx(0.02)
    with pytest.raises(ValueError):
        tilt_weights(members + ["unscored"], typical)


def test_select_members_buffer():
    ranked = [f"r{i}" for i in range(1, 101)]
    assert select_members(ranked) == ranked[:50]
    prev = ranked[:50]
    shifted = ranked[5:] + ranked[:5]          # 前 5 名掉到 96–100
    got = select_members(shifted, previous=prev)
    assert len(got) == 50
    assert "r6" in got and "r1" not in got, "掉出 60 名以外的不保留"
    holder = [f"x{i}" for i in range(1, 46)] + ["r50"] + [f"y{i}" for i in range(1, 55)]
    kept = select_members(holder, previous=["r50"])
    assert "r50" in kept, "老成分在 41–60 名内保留"
    newcomer = select_members(holder, previous=[])
    assert len(newcomer) == 50
    with pytest.raises(ValueError):
        select_members(ranked, add_rank=60, n=50, retain_rank=60)


def test_history_rows_and_split():
    from src.data.market.tradfi_history import rows_for, split_code
    assert split_code("AAPL.US") == ("AAPL", "US") and split_code("XAUUSD.FOREX") == ("XAUUSD", "FOREX")
    assert split_code("SIE.XETRA") == ("SIE", "XETRA") and split_code("BRK-B.US") == ("BRK-B", "US")
    with pytest.raises(ValueError):
        split_code("AAPL")
    from src.api.routers.ohlcv import eodhd_adjusted_rows
    adj = eodhd_adjusted_rows([{"date": "2020-01-02", "open": 10, "high": 11, "low": 9, "close": 10, "adjusted_close": 8, "volume": 5},
                               {"date": "2020-01-03", "close": None}])
    rows = rows_for("AAPL", "Equity", adj)
    assert rows == [{"symbol": "AAPL", "asset_class": "Equity", "source": "eodhd", "trade_date": "2020-01-02",
                     "open": 8.0, "high": 8.8, "low": 7.2, "close": 8.0, "volume": 5.0}]


def test_failed_ticker_writes_nothing_and_is_reported(monkeypatch):
    from src.data.market import tradfi_history as th
    from src.data.universe.world50 import Candidate

    async def boom(ticker, ex, frm):
        raise RuntimeError("EODHD eod NOPE.US HTTP 404")

    written = []

    async def fake_upsert(client, rows):
        written.extend(rows)
        return len(rows)

    import src.api.routers.ohlcv as ohlcv
    import src.data.market.data_layer as dl
    monkeypatch.setattr(dl, "get_eodhd_eod_range", boom)
    monkeypatch.setattr(ohlcv, "_upsert_ohlcv", fake_upsert)
    c = Candidate("NOPE", "Nope", "equity", "eodhd", "NOPE.US", "US")
    out = asyncio.run(th.run_once(candidates=[c]))
    assert out["ok"] is False and out["refused"] is True and written == []
    assert out["failed"][0]["symbol"] == "NOPE" and "404" in out["failed"][0]["why"]
