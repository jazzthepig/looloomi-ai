"""CoinGecko 闸门(11-17):预算 + 熔断 + 计数。

**为什么有这个测试。** 2026-11-17 起 CoinGecko 的**超额调用要钱**。闸门
(`src/data/market/cg_guard.py`)是唯一的收口点,它必须在三件事上是对的:

① **预算没��完 ⇒ 请求照发** —— 闸门不能把正常业务掐死(那是另一种事故)。
② **预算用完 ⇒ 一条外部请求都不许发** —— 这是钱的闸门,发不出去才是对的。
③ **上游 429 ⇒ 开闸** —— 限额用尽之后每一次重试都是一次付费调用。

而且拒绝时返回的是**带 `request` 的合成 503**:既有代码的 `raise_for_status()` /
`except` 分支一个字都不用改 —— 闸门不能逼着全仓库改一遍降级逻辑。

另外钉一条**形状守卫**:线上每一个 CoinGecko 客户端都必须是 `GuardedCGClient`。
新写一个裸 `httpx.AsyncClient` 就是把闸门拆了 —— 这个 bug 静默、无异常、
只在账单上现形。
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.market import cg_guard                              # noqa: E402
from src.data.market.cg_guard import GuardedCGClient              # noqa: E402


@pytest.fixture(autouse=True)
def _no_redis(monkeypatch):
    """测试里不碰真 Redis:计数走进程内兜底,预算从环境变量读。"""
    monkeypatch.setattr(cg_guard, "_UPSTASH_URL", "")
    monkeypatch.setattr(cg_guard, "_local_used", {})
    monkeypatch.setattr(cg_guard, "_local_breaker_until", 0.0)
    monkeypatch.setattr(cg_guard, "_local_tripped", 0)
    monkeypatch.setenv("CG_DAILY_BUDGET", "5")
    monkeypatch.setenv("CG_BREAKER_COOLDOWN_S", "300")
    yield


def _client(handler) -> GuardedCGClient:
    return GuardedCGClient(transport=httpx.MockTransport(handler))


def test_预算没用完_请求照发():
    """闸门的第一职责:**不许误伤**。预算充足时请求必须真的发出去。"""
    seen: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json={"ok": True})

    async def scenario():
        async with _client(handler) as c:
            r = await c.get("https://pro-api.coingecko.com/api/v3/global")
            return r

    r = asyncio.run(scenario())
    assert r.status_code == 200
    assert seen, "请求没有发出去 —— 闸门误伤了正常流量"


def test_每次请求都被计数():
    async def scenario():
        async with _client(lambda req: httpx.Response(200, json={})) as c:
            await c.get("https://pro-api.coingecko.com/api/v3/global")
            await c.get("https://pro-api.coingecko.com/api/v3/simple/price")
        return await cg_guard.used_today()

    assert asyncio.run(scenario()) == 2


def test_预算用完_一条外部请求都不许发():
    """**钱的闸门**。预算 = 5,先用掉 5 次,第 6 次不许发出去。"""
    sent: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(str(request.url))
        return httpx.Response(200, json={"ok": True})

    async def scenario():
        async with _client(handler) as c:
            for _ in range(5):
                r = await c.get("https://pro-api.coingecko.com/api/v3/global")
                assert r.status_code == 200
            r = await c.get("https://pro-api.coingecko.com/api/v3/global")
            return r

    r = asyncio.run(scenario())
    assert len(sent) == 5, f"闸门没拦住 —— 多发了 {len(sent) - 5} 次付费请求"
    assert r.status_code == 503
    body = r.json()
    assert body["error"] == "coingecko_guard"
    assert "budget_exhausted" in body["reason"]


def test_拒绝时返回的是合成503_带request_能照常raise_for_status():
    """既有调用点的降级分支(`raise_for_status()` + `except`)一个字都不用改。"""
    sent: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(str(request.url))
        return httpx.Response(200, json={"ok": True})

    async def scenario():
        async with _client(handler) as c:
            for _ in range(5):
                await c.get("https://pro-api.coingecko.com/api/v3/global")
            return await c.get("https://pro-api.coingecko.com/api/v3/global")

    r = asyncio.run(scenario())
    assert len(sent) == 5, "闸门没拦住 —— 多发了一次付费请求"
    assert r.status_code == 503
    assert r.request is not None
    with pytest.raises(httpx.HTTPStatusError):
        r.raise_for_status()


def test_上游429_开闸_之后一条都不发():
    """限额用尽之后每一次重试都是一次付费调用 ⇒ 429 必须开闸。"""
    sent: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(str(request.url))
        return httpx.Response(429, json={"error": "rate limit"})

    async def scenario():
        async with _client(handler) as c:
            r1 = await c.get("https://pro-api.coingecko.com/api/v3/global")
            r2 = await c.get("https://pro-api.coingecko.com/api/v3/global")
            return r1, r2

    r1, r2 = asyncio.run(scenario())
    assert r1.status_code == 429
    assert len(sent) == 1, "429 之后还发了请求 —— 每次重试都是一次付费调用"
    assert r2.status_code == 503
    assert "breaker_open" in r2.json()["reason"]


def test_5xx也算熔断():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "upstream"})

    async def scenario():
        async with _client(handler) as c:
            await c.get("https://pro-api.coingecko.com/api/v3/global")
            return await cg_guard.breaker_state()

    open_, why = asyncio.run(scenario())
    assert open_ is True, why


def test_熔断期间_admit直接拒绝():
    async def scenario():
        await cg_guard.trip_breaker("HTTP 429")
        return await cg_guard.admit()

    allowed, why = asyncio.run(scenario())
    assert allowed is False
    assert "breaker_open" in why


def test_线上每个CG客户端都必须是GuardedCGClient():
    """**形状守卫**:新写一个裸 `httpx.AsyncClient` 就把闸门拆了。

    这个 bug 静默、无异常、只在账单上现形 —— 所以用静态扫描钉死。
    """
    import src.data.market.data_layer as dl

    async def scenario():
        c = dl._get_cg_client()
        try:
            return isinstance(c, GuardedCGClient)
        finally:
            await c.aclose()

    assert asyncio.run(scenario()), "data_layer 的 CG client 不是受闸门约束的"

    for rel in ("src/data/narrative/social_collector.py", "src/api/main.py"):
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert "GuardedCGClient" in src, f"{rel} 没有接闸门"
        assert "async with _httpx.AsyncClient(headers=_cg_headers()" not in src, \
            f"{rel} 还在用裸 httpx client 打 CoinGecko"


def test_额度报告把今天花了多少说出来():
    """看不见花销,就只能等账单 —— 那时候已经晚了。"""

    async def scenario():
        async with _client(lambda req: httpx.Response(200, json={})) as c:
            await c.get("https://pro-api.coingecko.com/api/v3/global")
        return await cg_guard.report()

    rep = asyncio.run(scenario())
    assert rep["used_today"] == 1
    assert rep["daily_budget"] == 5
    assert rep["remaining"] == 4
    assert rep["breaker_open"] is False
