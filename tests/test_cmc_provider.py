"""CoinMarketCap 兜底层(11-17):自带日预算 + 撞到额度就停 + 来源必须标。

**为什么有这个测试。** CMC 是 CoinGecko 闸门关上之后的**唯一**第二个数据源。
它有三件事必须是对的,不然兜底本身会变成新的窟窿:

① **没有 key ⇒ 一条都不发** —— 没 key 还去打,得到的是 401 和一次无效请求。
② **预算用完 ⇒ 不发**;**撞到额度错误码 ⇒ 今天停用** —— 免费档的额度比
   Analyst 档小得多,拿它当「无限兜底」就是在挖第二个坑。
③ **拿不到就返回空,不编 0** —— 「没有数据」塌成「0」会让面板显示一个
   看起来合理、其实不存在的数字(S-262/S-396 家族)。

还有一条口径纪律:**换源必须标来源**。CMC 的市值口径和 CoinGecko 不一样,
混着用却不标,数字看着一样、其实不是一回事。
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

from src.data.market import cmc_provider                          # noqa: E402


@pytest.fixture(autouse=True)
def _no_redis(monkeypatch):
    monkeypatch.setattr(cmc_provider, "_UPSTASH_URL", "")
    monkeypatch.setattr(cmc_provider, "_local_used", {})
    monkeypatch.setattr(cmc_provider, "_local_blocked_until", 0.0)
    monkeypatch.setenv("CMC_API_KEY", "test-cmc-key")
    monkeypatch.setenv("CMC_DAILY_BUDGET", "3")
    yield


def _mock(monkeypatch, handler):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(cmc_provider, "_get_http", lambda: client)
    return client


def _clear_every_cmc_key(monkeypatch):
    """清掉**所有**可能被认出来的 CMC key 变量(含按规则扫到的)。

    只删三个显式名是不够的 —— 扫描层会从环境里捡到别的名字,测试就会
    变成「看这台机器碰巧配了什么」。规则直接取生产代码里的那个函数,
    不在这里抄一份(抄一份 = 规则改了测试不知道)。
    """
    import os
    for name in list(os.environ):
        if cmc_provider._looks_like_cmc_key_name(name):
            monkeypatch.delenv(name, raising=False)


def test_没有key_一条都不发(monkeypatch):
    """没 key 还去打 = 无效请求 + 白白消耗时间。"""
    _clear_every_cmc_key(monkeypatch)
    sent: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(str(request.url))
        return httpx.Response(200, json={"data": {}})

    _mock(monkeypatch, handler)

    async def scenario():
        allowed, why = await cmc_provider.admit()
        q = await cmc_provider.cmc_quotes(["BTC"])
        g = await cmc_provider.cmc_global_metrics()
        return allowed, why, q, g

    allowed, why, q, g = asyncio.run(scenario())
    assert allowed is False
    assert why == "no_cmc_key"
    assert sent == [], "没有 key 还发了请求"
    assert q == {} and g == {}


def test_三个环境变量名都认(monkeypatch):
    """Jazz 补 key 时用的名字没人记录过 —— 三个都收,不用为了一个变量名再发一版。"""
    for name in ("CMC_API_KEY", "COINMARKETCAP_API_KEY", "CMC_PRO_API_KEY"):
        _clear_every_cmc_key(monkeypatch)
        monkeypatch.setenv(name, "k-" + name)
        assert cmc_provider._api_key() == "k-" + name


def test_名字不在名单里_按规则扫出来(monkeypatch):
    """实测:三个显式名一个都没命中(Jazz 配的是别的名字)⇒ 兜底哑掉。

    所以除了名单,还要**按规则找**:`CMC_*_KEY` / `CMC_*_TOKEN` /
    `COINMARKETCAP_*_KEY` / `COINMARKETCAP_*_TOKEN` 这四种形状。
    `CMC_ENABLED` 这类不是凭据 ⇒ 排除。
    """
    _clear_every_cmc_key(monkeypatch)
    monkeypatch.setenv("CMC_ENABLED", "true")          # 不该被认成 key
    monkeypatch.setenv("CMC_BENCHMARK_SYMBOL", "BTC")  # 同上
    monkeypatch.setenv("CMC_PRO_KEY", "scanned-key")    # 该被认出来

    assert cmc_provider._api_key() == "scanned-key"
    assert cmc_provider._key_and_source()[1] == "CMC_PRO_KEY"


def test_规则的边界_只看我们自己的命名空间(monkeypatch):
    """规则的边界要钉死,不然「扫环境变量」会变成「捡到什么都用」。

    **只在我们自己的命名空间里找**(`CMC_` / `COINMARKETCAP_` 开头),
    **且必须是凭据**(以 KEY / TOKEN 结尾)。别家的 key 一个都不看。
    """
    _clear_every_cmc_key(monkeypatch)
    # 不是凭据(开关 / 用途变量)⇒ 排除
    assert cmc_provider._looks_like_cmc_key_name("CMC_ENABLED") is False
    assert cmc_provider._looks_like_cmc_key_name("CMC_BENCHMARK_SYMBOL") is False
    # 不是我们家的命名空间 ⇒ 排除(别家的 key 一个都不看)
    assert cmc_provider._looks_like_cmc_key_name("COINGECKO_API_KEY") is False
    assert cmc_provider._looks_like_cmc_key_name("MORALIS_API_KEY") is False
    assert cmc_provider._looks_like_cmc_key_name("ETHERSCAN_API_KEY") is False
    assert cmc_provider._looks_like_cmc_key_name("INTERNAL_TOKEN") is False
    # 我们家的命名空间 + 凭据形状 ⇒ 是
    for name in ("CMC_API_KEY", "CMC_PRO_KEY", "CMC_APIKEY", "CMC_TOKEN",
                 "COINMARKETCAP_API_KEY", "COINMARKETCAP_PRO_API_KEY",
                 "COINMARKETCAP_TOKEN"):
        assert cmc_provider._looks_like_cmc_key_name(name) is True, name
    # 大小写不敏感
    assert cmc_provider._looks_like_cmc_key_name("cmc_api_key") is True
    assert cmc_provider._looks_like_cmc_key_name("coinmarketcap_api_key") is True


def test_扫到的是我们家的key_别家的key不会被误用(monkeypatch):
    """环境里同时有 CoinGecko 的 key ⇒ 绝不能把它当成 CMC 的 key 用掉。"""
    _clear_every_cmc_key(monkeypatch)
    monkeypatch.setenv("COINGECKO_API_KEY", "cg-key")
    monkeypatch.setenv("MORALIS_API_KEY", "moralis-key")
    assert cmc_provider._api_key() == ""


def test_扫描命中哪个变量名_要能报出来(monkeypatch):
    """兜底哑掉的时候,一眼要能看出是「没配」还是「配在了一个我没认的名字下」。"""
    _clear_every_cmc_key(monkeypatch)
    monkeypatch.setenv("COINMARKETCAP_PRO_API_KEY", "k")

    rep = asyncio.run(cmc_provider.report())
    assert rep["key_present"] is True
    assert rep["key_env"] == "COINMARKETCAP_PRO_API_KEY"
    assert "k" not in str(rep["key_env"])       # 报的是名字,不是值


def test_预算用完_不再发(monkeypatch):
    """免费档额度很小,预算用完就是停 —— 不是「还剩一点就再打一发」。"""
    sent: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(str(request.url))
        return httpx.Response(200, json={"data": {}})

    _mock(monkeypatch, handler)

    async def scenario():
        for _ in range(3):
            await cmc_provider.cmc_quotes(["BTC"])
        allowed, why = await cmc_provider.admit()
        return allowed, why

    allowed, why = asyncio.run(scenario())
    assert len(sent) == 3, "预算没有拦住"
    assert allowed is False
    assert "budget_exhausted" in why


def test_撞到额度错误码_今天停用(monkeypatch):
    """CMC 的额度错误码族(1001/1002/1008/1009/1010/1011)⇒ 撞一次就今天别试了。"""
    sent: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(str(request.url))
        return httpx.Response(429, json={"status": {"error_code": 1001,
                                                    "error_message": "limit"}})

    _mock(monkeypatch, handler)

    async def scenario():
        await cmc_provider.cmc_quotes(["BTC"])
        blocked = await cmc_provider.blocked_today()
        allowed, why = await cmc_provider.admit()
        return blocked, allowed, why

    blocked, allowed, why = asyncio.run(scenario())
    assert blocked is True, "撞到额度错误码后没有停用 —— 下一轮还要再撞一次"
    assert allowed is False
    assert why == "cmc_quota_blocked_today"


def test_quotes按symbol解析_并标来源(monkeypatch):
    body = {
        "data": {
            "BTC": {
                "id": 1, "name": "Bitcoin", "symbol": "BTC",
                "last_updated": "2026-11-17T00:00:00.000Z",
                "quote": {"USD": {"price": 95000.0, "market_cap": 1.9e12,
                                  "volume_24h": 4.0e10,
                                  "percent_change_24h": 1.5,
                                  "percent_change_7d": -2.0}},
            }
        }
    }
    seen: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((str(request.url), dict(request.headers), str(request.url)))
        return httpx.Response(200, json=body)

    _mock(monkeypatch, handler)

    async def scenario():
        return await cmc_provider.cmc_quotes(["btc"])

    out = asyncio.run(scenario())
    assert out["BTC"]["price"] == 95000.0
    assert out["BTC"]["percent_change_24h"] == 1.5
    assert out["BTC"]["source"] == "coinmarketcap"
    # 按 symbol 请求 —— id / slug 映射要另一次调用,而 symbol 我们本来就有
    assert "symbol=BTC" in seen[0][0]
    # CMC 的 header 名就是下划线(`X-CMC_PRO_API_KEY`);httpx 规范成小写
    hdrs = {k.lower(): v for k, v in seen[0][1].items()}
    assert hdrs.get("x-cmc_pro_api_key") == "test-cmc-key"


def test_global_metrics用CMC自己的字段名(monkeypatch):
    """不给 CMC 套一个「看起来一样」的适配器 —— 那会把两家的口径差藏起来。"""
    # 假回包用对方的**真实键名**(官方文档 + 2026-11-23 实际回包)。S-908:原来这里放的是照 CoinGecko 叫法猜的
    # `total_volume` / `total_market_cap_change_percentage_24h_usd`,代码读的也是这两个 ⇒ 测试自己跟自己对上,
    # 线上这两个值从上线起一直是 None。所以下面两个值必须断言,不能只断言市值和占比。
    body = {"data": {"btc_dominance": 61.2, "eth_dominance": 10.1, "active_cryptocurrencies": 17000,
                     "btc_dominance_24h_percentage_change": 0.09,
                     "quote": {"USD": {"total_market_cap": 3.8e12,
                                       "total_volume_24h": 1.2e11,
                                       "total_market_cap_yesterday_percentage_change": -0.8}}}}
    _mock(monkeypatch, lambda req: httpx.Response(200, json=body))

    async def scenario():
        return await cmc_provider.cmc_global_metrics()

    m = asyncio.run(scenario())
    assert m["btc_dominance_pct"] == 61.2
    assert m["total_market_cap_usd"] == 3.8e12
    assert m["total_volume_24h_usd"] == 1.2e11, "量读不到 = 键名又猜错了"
    assert m["total_market_cap_change_24h_pct"] == -0.8, "24h 变化读不到 = 键名又猜错了"
    assert m["btc_dominance_change_24h_pp"] == 0.09
    assert m["source"] == "coinmarketcap"


def test_拿不到就返回空_不编0(monkeypatch):
    """普通失败(不是额度)⇒ 空字典。不编 0 —— 0 是个看起来合理的假数字。"""
    _mock(monkeypatch, lambda req: httpx.Response(401, json={"status": {"error_code": 100}}))

    async def scenario():
        return (await cmc_provider.cmc_quotes(["BTC"]),
                await cmc_provider.cmc_global_metrics())

    q, g = asyncio.run(scenario())
    assert q == {}
    assert g == {}


# ── 接进生产路径:CG 拿不到时,CMC 顶上,而且必须标来源 ────────────────────────

def test_get_cg_global_CG失败时CMC兜底_并且标来源(monkeypatch):
    """兜底不是「换个数字继续骗人」—— 结果带 `source`,缺的数据是 None。"""
    import src.data.market.data_layer as dl

    class _Boom:
        async def get(self, *a, **k):
            raise RuntimeError("budget_exhausted")

    async def fake_cmc_global():
        return {"btc_dominance_pct": 61.2, "total_market_cap_usd": 3.8e12,
                "total_volume_24h_usd": 1.2e11,
                "total_market_cap_change_24h_pct": -0.8,
                "active_cryptocurrencies": 17000, "markets": 1200,
                "source": "coinmarketcap"}

    async def fake_redis_get(k):
        return None

    async def fake_redis_set(k, v, ttl=None):
        return True

    monkeypatch.setattr(dl, "_get_cg_client", lambda: _Boom())
    monkeypatch.setattr(dl, "CG_API_KEY", "test-key")
    monkeypatch.setattr(dl, "_cache", {})
    monkeypatch.setattr(dl, "_redis_get", fake_redis_get)
    monkeypatch.setattr(dl, "_redis_set", fake_redis_set)
    monkeypatch.setattr(cmc_provider, "cmc_global_metrics", fake_cmc_global)

    out = asyncio.run(dl.get_cg_global())
    assert out["source"] == "coinmarketcap"
    assert out["btc_dominance"] == 61.2
    assert out["total_market_cap_usd"] == 3.8e12
    # CMC 没有 ETH 占比 / DeFi 市值 ⇒ None,**不是 0**(S-262/S-396 家族)
    assert out["eth_dominance"] is None
    assert out["defi_market_cap"] is None


def test_macro_pulse_CG失败时CMC顶上_并且标来源(monkeypatch):
    """宏观脉冲是**活的面** —— CG 闸门一关,它必须有东西可显示,而且要说清是谁给的。"""
    import src.data.market.data_layer as dl

    class _Boom:
        async def get(self, *a, **k):
            raise RuntimeError("breaker_open")

    class _Fng:
        async def get(self, *a, **k):
            return httpx.Response(200, json={"data": [{"value": "55",
                                                        "value_classification": "Neutral"}]})

    async def fake_defi():
        return {"total_tvl_usd": 1.2e11}

    async def fake_cmc_global():
        return {"btc_dominance_pct": 61.2, "total_market_cap_usd": 3.8e12,
                "total_market_cap_change_24h_pct": -0.8,
                "source": "coinmarketcap"}

    async def fake_cmc_quotes(symbols):
        assert symbols == ["BTC"]
        return {"BTC": {"price": 95000.0, "percent_change_24h": 1.5,
                        "percent_change_7d": -2.0, "source": "coinmarketcap"}}

    async def fake_redis_get(k):
        return None

    async def fake_redis_set(k, v, ttl=None):
        return True

    monkeypatch.setattr(dl, "_get_cg_client", lambda: _Boom())
    monkeypatch.setattr(dl, "_get_misc_client", lambda: _Fng())
    monkeypatch.setattr(dl, "get_defi_overview", fake_defi)
    monkeypatch.setattr(dl, "_cache", {})
    monkeypatch.setattr(dl, "_redis_get", fake_redis_get)
    monkeypatch.setattr(dl, "_redis_set", fake_redis_set)
    monkeypatch.setattr(cmc_provider, "cmc_global_metrics", fake_cmc_global)
    monkeypatch.setattr(cmc_provider, "cmc_quotes", fake_cmc_quotes)

    out = asyncio.run(dl.get_macro_pulse())
    assert out["data_source"] == "coinmarketcap"
    assert out["btc"]["usd"] == 95000.0
    assert out["btc"]["usd_24h_change"] == 1.5
    assert out["btc_dominance"] == 61.2
    assert out["data"]["market_cap_percentage"]["btc"] == 61.2
    assert out["total_market_cap_usd"] == 3.8e12


def test_宏观脉冲读行情行_不再另打simple_price(monkeypatch):
    """官网首页一次 `/coins/markets` 带出价格和涨跌。行情行还在 300s 内时,
    宏观脉冲读这一行,不再为比特币发请求。"""
    import src.data.market.data_layer as dl

    class _Boom:
        async def get(self, *a, **k):
            raise AssertionError("cached markets row must not hit the network")

    async def fake_global():
        return {"market_cap_percentage": {"btc": 58.0},
                "total_market_cap": {"usd": 3.1e12},
                "market_cap_change_percentage_24h_usd": 0.4}

    async def fake_defi():
        return {"total_tvl_usd": 1.0e11}

    async def fake_markets(_ids):
        raise AssertionError("a fresh markets row is already cached")

    async def fake_redis_get(k):
        return None

    async def fake_redis_set(k, v, ttl=None):
        return True

    class _Fng:
        async def get(self, *a, **k):
            return httpx.Response(200, json={"data": [{"value": "11",
                                                        "value_classification": "Extreme Fear"}]})

    monkeypatch.setattr(dl, "_cache", {})
    monkeypatch.setattr(dl, "_get_cg_client", lambda: _Boom())
    monkeypatch.setattr(dl, "_get_misc_client", lambda: _Fng())
    monkeypatch.setattr(dl, "get_cg_global_raw", fake_global)
    monkeypatch.setattr(dl, "get_defi_overview", fake_defi)
    monkeypatch.setattr(dl, "get_cg_markets", fake_markets)
    monkeypatch.setattr(dl, "_redis_get", fake_redis_get)
    monkeypatch.setattr(dl, "_redis_set", fake_redis_set)
    dl._cache_set("cg_market_row:bitcoin", {
        "id": "bitcoin",
        "current_price": 64947.0,
        "price_change_percentage_24h": -1.1,
        "price_change_percentage_7d_in_currency": None,
    })

    out = asyncio.run(dl.get_macro_pulse())
    assert out["data_source"] == "coingecko"
    assert out["btc"]["usd"] == 64947.0
    assert out["btc"]["usd_24h_change"] == -1.1
    assert out["btc"]["usd_7d_change"] is None
    assert out["btc_price"] == 64947.0


def test_没有行情行时用一次markets_缺价不写成0():
    import src.data.market.data_layer as dl

    assert dl.btc_quote_from_market_row({"id": "bitcoin", "current_price": 0}) is None
    assert dl.btc_quote_from_market_row({"id": "ethereum", "current_price": 1800}) is None
    quote = dl.btc_quote_from_market_row({
        "id": "bitcoin",
        "current_price": "64000.5",
        "price_change_percentage_24h": "nope",
        "price_change_percentage_7d_in_currency": -2.5,
    })
    assert quote == {"usd": 64000.5, "usd_24h_change": None, "usd_7d_change": -2.5}


def test_这些测试不读线上的行情快照(monkeypatch):
    """S-908:机器人那台机器带着库凭证跑预检。上面两条「CG 失败 → CMC 兜底」的测试曾经读到线上 `market_snapshot`
    的真实行(BTC 占比 58.8,不是假回包的 61.2)而红。`tests/conftest.py` 默认把快照读关掉 —— 这里钉住它确实关着:
    就算读库的函数能读到行,这个文件里拿到的也必须是空。"""
    import src.data.market.market_snapshot as ms
    import src.data.vector.market_state_writer as msw

    class _R:
        ok, rows, reason = True, [{"ts": "2099-01-01T00:00:00+00:00"}], "ok"

    async def live_table(*a, **k):
        return _R()

    monkeypatch.setattr(msw, "_sb_get", live_table)
    assert asyncio.run(ms.latest()) is None
    assert asyncio.run(ms.cmc_latest_shaped()) == {"global": {}, "quotes": {}, "as_of": None}
