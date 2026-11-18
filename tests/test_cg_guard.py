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
    # S-895 阶段 0:闸门外的账也要清 —— 否则上一条用例的记账会漏进下一条。
    monkeypatch.setattr(cg_guard, "_local_unbudgeted", {})
    monkeypatch.setattr(cg_guard, "_local_unbudgeted_ep", {})
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


# ── S-895 阶段 0:闸门之外的消耗必须进账 ─────────────────────────────────────
#
# 闸门只数**它自己放行**的请求。闸门外的裸 client 打出去的调用,`used_today`
# 一概看不见 —— 于是「今天花了多少」从第一天起就是残缺的。这组测试钉住
# 「闸门外也进账」,以及**闸门内的调用不会重复进账**。

def test_闸门外的调用进账_并按端点分组():
    """记账的形状:总数 + 分端点明细。分端点是为了能回答「哪条路径在烧钱」。"""
    cg_guard.note_unbudgeted_call("coingecko", "/coins/markets")
    cg_guard.note_unbudgeted_call("coingecko", "/coins/markets")
    cg_guard.note_unbudgeted_call("coingecko", "/global")

    async def scenario():
        return await cg_guard.unbudgeted_today(), await cg_guard.unbudgeted_endpoints()

    total, eps = asyncio.run(scenario())
    assert total == 3
    assert eps["coingecko:/coins/markets"] == 2
    assert eps["coingecko:/global"] == 1


def test_同步调用点也进账():
    """两个 `requests` 调用点(`exchange_data.py` / `mmi_index_v3.py`)没有事件
    循环 ⇒ 记账必须**同步**落,不能因为「没有 loop」就静默丢掉。"""
    cg_guard.note_unbudgeted_call("coingecko", "/simple/price")

    async def scenario():
        return await cg_guard.unbudgeted_today()

    assert asyncio.run(scenario()) == 1


def test_闸门内的调用不进闸外的账():
    """**不双计**。闸门已经在数了 —— 闸外的账簿只该收闸门管不到的调用。"""
    async def scenario():
        async with _client(lambda req: httpx.Response(200, json={})) as c:
            await c.get("https://pro-api.coingecko.com/api/v3/global")
        return await cg_guard.used_today(), await cg_guard.unbudgeted_today()

    used, unbudgeted = asyncio.run(scenario())
    assert used == 1
    assert unbudgeted == 0


def test_报告里的今天真实总量_闸门内加闸门外():
    """`total_calls_today` 才是**今天的真实总量**。

    之前只有 `used_today`,它只数闸门内的 11 个文件 ⇒ 报出来的是「我们希望
    花掉的钱」,不是「我们花掉的钱」。
    """
    async def scenario():
        async with _client(lambda req: httpx.Response(200, json={})) as c:
            await c.get("https://pro-api.coingecko.com/api/v3/global")
            await c.get("https://pro-api.coingecko.com/api/v3/global")
        cg_guard.note_unbudgeted_call("coingecko", "/coins/markets")
        cg_guard.note_unbudgeted_call("coingecko", "/coins/markets")
        cg_guard.note_unbudgeted_call("coingecko", "/global")
        return await cg_guard.report()

    rep = asyncio.run(scenario())
    assert rep["used_today"] == 2
    assert rep["unbudgeted_today"] == 3
    assert rep["total_calls_today"] == 5
    assert rep["unbudgeted_total"] == 3
    assert rep["unbudgeted_endpoints"]["coingecko:/coins/markets"] == 2


def test_跨进程口径_取较大者_宁可报多不报少():
    """Redis 与进程内两份账,取**较大**者。

    少报 = 因错误理由变绿(「今天才花了 300 次」会让人以为很安全);多报只
    会让人多查一眼。两害相权,取大。
    """
    async def scenario(remote):
        async def fake_r_get(key):
            return remote if key.startswith("cg:quota:unbudgeted:") else None

        orig = cg_guard._r_get
        cg_guard._r_get = fake_r_get
        try:
            return await cg_guard.unbudgeted_today()
        finally:
            cg_guard._r_get = orig

    # Redis 那边更多(别的进程记的)⇒ 用 Redis 的
    assert asyncio.run(scenario(9)) == 9
    # 本进程更多(Redis 写失败/没配)⇒ 用本地的,不能因为 Redis 读到了 0
    # 就把本进程已经知道的消耗报成 0
    cg_guard.note_unbudgeted_call("coingecko", "/global")
    assert asyncio.run(scenario(0)) == 1


def test_两种import路径是同一个模块对象():
    """`src.data.market.cg_guard` 与 `data.market.cg_guard` 必须是**同一个对象**。

    仓库两种写法都在用(`src/api/main.py:30-38` 的双路径说明)。两个对象 =
    两份进程内计数 ⇒ Redis 写失败时读数漏掉另一半 ⇒ **少报**。
    这个别名由 `cg_guard.py` 自己在 import 时钉死,这里只验它没被摘掉。
    """
    import importlib
    a = importlib.import_module("src.data.market.cg_guard")
    b = importlib.import_module("data.market.cg_guard")
    assert a is b, "两条 import 路径加载出了两个模块对象 —— 账会被劈成两半"


def test_端点标签把coin_id归一():
    """同一个端点的不同 coin id 必须是**同一个标签** —— 否则分端点明细会
    变成「每个币一行」,读数没法用。"""
    assert cg_guard.endpoint_label(
        "https://pro-api.coingecko.com/api/v3/coins/bitcoin/market_chart"
    ) == "/coins/{id}/market_chart"
    assert cg_guard.endpoint_label(
        "https://pro-api.coingecko.com/api/v3/coins/ethereum/market_chart"
    ) == "/coins/{id}/market_chart"
    # 子路径不能被误归一成 coin id
    assert cg_guard.endpoint_label(
        "https://pro-api.coingecko.com/api/v3/coins/markets"
    ) == "/coins/markets"
    assert cg_guard.endpoint_label(
        "https://pro-api.coingecko.com/api/v3/global"
    ) == "/global"
    # 查询参数不进标签 —— 同一端点的参数变体是同一个额度池
    assert cg_guard.endpoint_label(
        "https://pro-api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd"
    ) == "/simple/price"
    assert cg_guard.endpoint_label("") == "(unknown)"
