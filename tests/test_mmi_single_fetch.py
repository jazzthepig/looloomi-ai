"""MMI v3:`/market_chart` 一轮只取一次(11-16)。

**为什么有这个测试。** `get_historical_score()`(价格/市值)和 `get_onchain_score()`(成交量)要的是
**同一份** `/market_chart?vs_currency=usd&days=30` —— 同一个 URL、同一个参数。原来两个方法各取一次,
一次 `calculate()` 就是两次 CoinGecko 调用外加两次 1.5 秒的空等。而这条路径打的是**公开**端点
(每分钟十几次),Pro key 在公开 host 上还会被忽略。

这个测试钉死:一轮 `calculate()` ⇒ market_chart **一次**、fear&greed 一次;并且有 key 时走 Pro 端点。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.analytics.mmi import mmi_index_v3 as mmi_mod  # noqa: E402


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _chart():
    return {
        "prices": [[1700000000000, 100.0], [1700086400000, 110.0]],
        "market_caps": [[1700000000000, 1e9], [1700086400000, 1.1e9]],
        "total_volumes": [[1700000000000, 1e8], [1700086400000, 2e8]],
    }


def test_一轮只取一次market_chart(monkeypatch):
    calls = []

    def fake_get(url, params=None, headers=None, timeout=None):
        calls.append((url, params))
        if "market_chart" in url:
            return _FakeResp(_chart())
        return _FakeResp({"data": [{"value": "60", "value_classification": "Greed"}]})

    monkeypatch.setattr(mmi_mod.requests, "get", fake_get)
    m = mmi_mod.LooloomiMMI("bitcoin")
    m.api_delay = 0
    score = m.calculate()
    chart_calls = [c for c in calls if "market_chart" in c[0]]
    assert len(chart_calls) == 1, f"market_chart 被取了 {len(chart_calls)} 次 —— 应该一次"
    assert len(calls) == 2, "一轮 = 1 次 market_chart + 1 次 fear&greed"
    assert 0 <= score <= 100


def test_有key时走Pro端点(monkeypatch):
    calls = []

    def fake_get(url, params=None, headers=None, timeout=None):
        calls.append((url, headers))
        if "market_chart" in url:
            return _FakeResp(_chart())
        return _FakeResp({"data": [{"value": "50", "value_classification": "Neutral"}]})

    monkeypatch.setattr(mmi_mod.requests, "get", fake_get)
    monkeypatch.setattr(mmi_mod, "CG_API_KEY", "test-key")
    m = mmi_mod.LooloomiMMI("bitcoin")
    m.api_delay = 0
    m.calculate()
    chart = [c for c in calls if "market_chart" in c[0]][0]
    assert chart[0].startswith("https://pro-api.coingecko.com/api/v3/coins/"), chart[0]
    assert chart[1] == {"x-cg-pro-api-key": "test-key"}


def test_分数没变_只是少取一次(monkeypatch):
    """口径不能因为合并调用而变。"""
    def fake_get(url, params=None, headers=None, timeout=None):
        if "market_chart" in url:
            return _FakeResp(_chart())
        return _FakeResp({"data": [{"value": "60", "value_classification": "Greed"}]})

    monkeypatch.setattr(mmi_mod.requests, "get", fake_get)
    m = mmi_mod.LooloomiMMI("bitcoin")
    m.api_delay = 0
    m.calculate()
    h = m.components["historical"]
    o = m.components["onchain"]
    assert h["price_change_30d"] == 10.0
    assert h["mcap_change_30d"] == 10.0
    # 口径照旧:vol_7d = sum(最近 7 个点)/7(点不够也照除 7 —— 这是原口径,没动)
    assert o["vol_7d_avg"] == round(3e8 / 7, 0) and o["vol_30d_avg"] == 1.5e8
    assert o["vol_ratio"] == round((3e8 / 7) / 1.5e8, 2)
