"""positioning 读库优先(11-16):同一份数据、两条路、口径必须逐位相同。

**为什么有这个测试。** `src/data/cis/positioning.py` 原来每 30 分钟直接打 CoinGecko 的**公开**
`/derivatives`,而 `derivatives_market.py` 每 6 小时把**同一份数据**落进 `derivatives_market_daily`
—— 一个端点,两个额度池。改成读库优先之后,最怕的不是「读不到」(读不到会回落 API),
而是**两条路算出不同的数**:库里那份是「分子分母两列」,API 那份是「现场求和」,两者一旦口径分叉,
positioning 的历史序列会在某天悄悄换算法 —— 那种 bug 在图上看不出来。

所以这里钉死三件事:
  ① API 路径的口径没被改坏(永续才收、没 funding_rate 的行不参与加权);
  ② 库路径和 API 路径喂同样数据 ⇒ 算出来的 map **完全相等**;
  ③ 库里有新鲜数据时,一条 API 都不许发(发不出去 = 测试失败)。
"""
from __future__ import annotations

import asyncio
import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.cis import positioning as pos                      # noqa: E402
from src.data.vector.market_state_writer import SbRead          # noqa: E402

#: 三行:一个永续(有资金费)、一个永续(资金费 0)、一个非永续(有资金费 ⇒ 不该被收)。
TICKERS = [
    {"index_id": "BTC", "contract_type": "perpetual", "open_interest": 3e9, "funding_rate": 0.01},
    {"index_id": "BTC", "contract_type": "perpetual", "open_interest": 1e9, "funding_rate": 0.03},
    {"index_id": "BTC", "contract_type": "futures", "open_interest": 9e9, "funding_rate": 0.50},
    {"index_id": "ETH", "contract_type": "perpetual", "open_interest": 2e9, "funding_rate": -0.02},
    {"index_id": "ETH", "contract_type": "perpetual", "open_interest": 5e8, "funding_rate": None},
    {"index_id": "SOL", "contract_type": "perpetual", "open_interest": 1e5, "funding_rate": 0.01},
]
KNOWN = {"BTC", "ETH", "SOL"}


def _patch_universe(monkeypatch):
    import src.data.cis.cis_provider as cp
    monkeypatch.setattr(cp, "CRYPTO_ASSETS", {s: {"symbol": s} for s in KNOWN})


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, payload):
        self._payload = payload
        self.calls: list = []

    async def get(self, url, **kw):
        self.calls.append((url, kw))
        return _FakeResp(self._payload)


def test_api_path_口径_只收永续且只收有资金费的行():
    agg = pos._agg_from_tickers(TICKERS, KNOWN)
    # BTC:非永续那一行(oi 9e9)不参与;分母只算两行永续的 4e9。
    assert agg["BTC"]["oi"] == 4e9
    assert abs(agg["BTC"]["oi_wsum"] - (0.01 * 3e9 + 0.03 * 1e9)) < 1e-6
    # ETH:funding_rate 为 None 的那一行不参与(分母只有 2e9,不是 2.5e9)。
    assert agg["ETH"]["oi"] == 2e9
    assert abs(agg["ETH"]["oi_wsum"] - (-0.02 * 2e9)) < 1e-6
    # SOL:oi 太小 —— 进了 agg,但过不了 _MIN_OI_USD,在 _compute 里被剔掉(不进分位数)。
    assert agg["SOL"]["oi"] == 1e5
    assert "SOL" not in pos._compute(agg)
    assert set(pos._compute(agg)) == {"BTC", "ETH"}


def test_库路径和API路径_喂同样的数据_算出来必须完全一样():
    """库里那两列(分子分母)就是 API 路径那两个和 —— 这是「口径统一」的全部含义。"""
    api_agg = pos._agg_from_tickers(TICKERS, KNOWN)
    db_rows = []
    for sym, a in api_agg.items():
        db_rows.append({"symbol": sym, "oi_funding_usd": a["oi"], "funding_oiw_sum": a["oi_wsum"],
                        "d": "2026-11-16", "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat()})
    db_agg = {r["symbol"]: {"oi_wsum": r["funding_oiw_sum"], "oi": r["oi_funding_usd"]} for r in db_rows}
    assert pos._compute(db_agg) == pos._compute(api_agg)


def test_库里新鲜时_一条API都不许发(monkeypatch):
    import src.data.market.data_layer as dl
    import src.data.vector.market_state_writer as msw

    _patch_universe(monkeypatch)
    now = dt.datetime.now(dt.timezone.utc)
    rows = [{"symbol": "BTC", "oi_funding_usd": 4e9, "funding_oiw_sum": 0.06e9,
             "d": now.date().isoformat(), "fetched_at": now.isoformat()},
            {"symbol": "ETH", "oi_funding_usd": 2e9, "funding_oiw_sum": -0.04e9,
             "d": now.date().isoformat(), "fetched_at": now.isoformat()}]

    async def fake_sb_get(path, params):
        assert path == pos.TABLE
        return SbRead(rows)

    class Boom:
        def get(self, *a, **k):
            raise AssertionError("库里明明有,为什么还去打 API")

    monkeypatch.setattr(msw, "_sb_get", fake_sb_get)
    monkeypatch.setattr(dl, "_get_cg_client", lambda: Boom())
    saved = {}

    async def fake_redis_set(key, val, ttl=None):
        saved[key] = val
        return True

    monkeypatch.setattr(dl, "_redis_set", fake_redis_set)
    m = asyncio.run(pos.refresh_positioning())
    assert set(m) == {"BTC", "ETH"}
    assert saved["cis:positioning"] == m
    # 两个标的的 OI 都过 5M 门槛;funding 的符号相反 ⇒ pressure 符号也相反。
    assert m["BTC"]["funding"] > 0 and m["BTC"]["positioning_pressure"] < 0
    assert m["ETH"]["funding"] < 0 and m["ETH"]["positioning_pressure"] > 0


def test_库里旧了或没有_回落API_并且走Pro端点(monkeypatch):
    import src.data.market.data_layer as dl
    import src.data.vector.market_state_writer as msw

    _patch_universe(monkeypatch)
    old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=30)).isoformat()

    async def fake_sb_get(path, params):
        # 列还没上线(PGRST204)= 读不到 ⇒ 必须回落。
        return SbRead(None, "HTTP 400: PGRST204")

    client = _FakeClient(TICKERS)
    monkeypatch.setattr(msw, "_sb_get", fake_sb_get)
    monkeypatch.setattr(dl, "_get_cg_client", lambda: client)
    monkeypatch.setattr(dl, "CG_API_KEY", "test-key")

    async def fake_redis_set(key, val, ttl=None):
        return True

    monkeypatch.setattr(dl, "_redis_set", fake_redis_set)
    m = asyncio.run(pos.refresh_positioning())
    assert set(m) == {"BTC", "ETH"}, m
    assert client.calls, "读不到就必须回落 API"
    url = client.calls[0][0]
    assert url.startswith("https://pro-api.coingecko.com/api/v3/derivatives"), url
    assert client.calls[0][1]["headers"] == {"x-cg-pro-api-key": "test-key"}
    assert old  # 只是提醒:这条路径不看旧行,列缺失时直接回落


def test_公开端点不再被写死():
    """原来的 bug:URL 里写死 `https://api.coingecko.com/api/v3/derivatives`。
    有 key 的时候必须走 Pro —— 公开端点每分钟十几次,429 是家常便饭。"""
    src = (ROOT / "src/data/cis/positioning.py").read_text(encoding="utf-8")
    assert '"https://api.coingecko.com/api/v3/derivatives"' not in src
    assert "CG_PRO_BASE" in src
