"""watchlist 行情:一次请求取全部 + 每个 key 独立缓存(11-16)。

**为什么有这个测试。** 原来 `/api/v1/agent/universe-watchlist?include_live_data=true` 给 9 个标的
**各发一次** `/coins/markets`,而且缓存的时间戳是全局的 —— 九个标的轮流 miss、轮流把全局时钟拨到当下,
一个 60 秒的缓存几乎从不命中。CG 的 `ids` 本来就支持一次取多个(上限 250),所以这九次调用从头到尾
没必要发生过。

这个测试钉死三件事:
  ① 一轮只发**一次**请求,`ids` 一次带齐;
  ② 缓存命中时**一次都不发**;
  ③ 某一个 key 过期,只补那一个 —— 不把别人的 TTL 一起拨回零(这正是原来那个 bug)。
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.api.routers import cis  # noqa: E402

SYMS = {"VIRTUAL": "virtuals-protocol", "FTM": "fantom", "ICP": "internet-computer"}


class _FakeResp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, payload):
        self._payload = payload
        self.calls: list = []

    async def get(self, url, **kw):
        self.calls.append((url, kw))
        return _FakeResp(self._payload)


def _rows(ids):
    return [{"id": i, "current_price": 1.0, "market_cap": 2.0, "market_cap_rank": 3,
             "price_change_percentage_30d_in_currency": 4.0} for i in ids]


def _setup(monkeypatch, client):
    import src.data.market.data_layer as dl
    cis._watchlist_cache.clear()
    monkeypatch.setattr(dl, "_get_cg_client", lambda: client)
    return client


def test_一轮只发一次请求_而且带齐所有ids(monkeypatch):
    client = _setup(monkeypatch, _FakeClient(_rows(SYMS.values())))
    out = asyncio.run(cis._get_cg_markets_batch(SYMS))
    assert len(client.calls) == 1, f"9 个标的发了 {len(client.calls)} 次 —— 应该是一轮一次"
    ids = client.calls[0][1]["params"]["ids"].split(",")
    assert sorted(ids) == sorted(SYMS.values())
    assert set(out) == set(SYMS)
    assert out["VIRTUAL"]["price"] == 1.0
    assert out["VIRTUAL"]["mcap_rank"] == 3


def test_缓存命中时一次都不发(monkeypatch):
    client = _setup(monkeypatch, _FakeClient(_rows(SYMS.values())))
    asyncio.run(cis._get_cg_markets_batch(SYMS))
    assert len(client.calls) == 1
    out = asyncio.run(cis._get_cg_markets_batch(SYMS))
    assert len(client.calls) == 1, "全部命中缓存,不该再发请求"
    assert set(out) == set(SYMS)


def test_一个key过期只补那一个_不把别人的TTL拨回零(monkeypatch):
    """原来那个 bug:时间戳是全局的,任何一个 miss 都把所有人的 TTL 重来一遍。"""
    client = _setup(monkeypatch, _FakeClient(_rows(SYMS.values())))
    asyncio.run(cis._get_cg_markets_batch(SYMS))
    assert len(client.calls) == 1
    # 只让 VIRTUAL 过期
    cis._watchlist_cache["VIRTUAL"] = ({}, time.time() - (cis._WATCHLIST_CACHE_TTL + 1))
    out = asyncio.run(cis._get_cg_markets_batch(SYMS))
    assert len(client.calls) == 2, "只该补 VIRTUAL 这一次"
    assert client.calls[1][1]["params"]["ids"] == "virtuals-protocol"
    assert set(out) == set(SYMS)


def test_有key时走Pro端点(monkeypatch):
    import src.data.cis.cis_provider as cp
    client = _setup(monkeypatch, _FakeClient(_rows(SYMS.values())))
    monkeypatch.setattr(cp, "CG_API_KEY", "test-key")
    asyncio.run(cis._get_cg_markets_batch(SYMS))
    url = client.calls[0][0]
    assert url.startswith("https://pro-api.coingecko.com/api/v3/coins/markets"), url
    assert client.calls[0][1]["headers"] == {"x-cg-pro-api-key": "test-key"}


def test_取不到就当没数据_不编造(monkeypatch):
    client = _setup(monkeypatch, _FakeClient([]))
    out = asyncio.run(cis._get_cg_markets_batch(SYMS))
    assert out == {s: {} for s in SYMS}
    assert len(client.calls) == 1
