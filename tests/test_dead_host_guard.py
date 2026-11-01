"""主机死了的那一段(11-02):现货越线 + 主机沉默 ⇒ 报;永续裸仓 ⇒ 主机沉默立刻报、主机在要连续两轮;同一天同一件事只报一次;不下单。"""
import asyncio
import datetime as dt
from pathlib import Path

from src.data.execution import dead_host_guard as g

TOK = {"BTC": "UBTC", "ETH": "UETH"}


def test_spot_breach_is_the_same_rule_as_the_host():
    b = g.spot_breaches({"BTC": 60000.0, "ETH": 2000.0}, {"UBTC": 0.002, "UETH": 0.001, "USDC": 300.0},
                        {"BTC": 59000.0, "ETH": 1900.0}, TOK)
    assert [x["symbol"] for x in b] == ["BTC"], "ETH 持仓 $1.9 不到最小名义额"
    assert b[0]["usd"] == 118.0 and b[0]["below_pct"] == -1.67
    assert g.spot_breaches({"BTC": None}, {"UBTC": 1.0}, {"BTC": 1.0}, TOK) == [], "没有线不猜"
    assert g.spot_breaches({"BTC": 60000.0}, {"UBTC": 1.0}, {}, TOK) == [], "没有现价不猜"


def test_naked_perp_means_no_reduce_only_trigger_on_that_coin():
    ch = {"assetPositions": [{"position": {"coin": "SOL", "szi": "2.0", "entryPx": "150", "positionValue": "300"}},
                             {"position": {"coin": "AVAX", "szi": "-3", "entryPx": "20", "positionValue": "60"}},
                             {"position": {"coin": "DOGE", "szi": "0"}}]}
    oo = [{"coin": "SOL", "isTrigger": True, "reduceOnly": True},
          {"coin": "AVAX", "isTrigger": False, "reduceOnly": True}]                 # 限价减仓单不是止损
    assert [n["coin"] for n in g.naked_perps(ch, oo)] == ["AVAX"]
    assert g.naked_perps({}, []) == [] and g.naked_perps(None, None) == []


def test_decide_spot_only_when_host_silent_and_once_a_day():
    br = [{"symbol": "BTC", "token": "UBTC", "qty": 0.002, "mid": 59000.0, "line": 60000.0, "usd": 118.0, "below_pct": -1.67}]
    assert g.decide(0.5, br, [], set(), set(), False) == [], "主机在 ⇒ 主机自己会止"
    a = g.decide(3.2, br, [], set(), set(), True)
    assert [x["key"] for x in a] == ["spot:BTC"] and "3.2 小时" in a[0]["text"] and "一键停开着" in a[0]["text"]
    assert "不会下单" in a[0]["text"]
    assert g.decide(3.2, br, [], set(), {"spot:BTC"}, False) == [], "同一天只报一次"
    assert g.decide(None, br, [], set(), set(), False)[0]["text"].count("从没回报过") == 1


def test_decide_naked_perp_needs_two_passes_when_host_is_alive():
    n = [{"coin": "SOL", "szi": 2.0, "entry_px": 150.0, "value_usd": 300.0, "upnl": 0.0, "liq_px": 80.0}]
    assert g.decide(0.3, [], n, set(), set(), False) == [], "第一轮:进场到挂触发单之间的正常空档"
    a = g.decide(0.3, [], n, {"SOL"}, set(), False)
    assert [x["key"] for x in a] == ["perp:SOL"] and "连续两轮" in a[0]["text"]
    assert [x["key"] for x in g.decide(5.0, [], n, set(), set(), False)] == ["perp:SOL"], "主机沉默 ⇒ 立刻"


def test_run_once_reads_public_state_and_alerts(monkeypatch):
    import src.api.notify as notify
    import src.api.store as store
    import src.data.accounting.live_account as la
    import src.data.execution.dry_run as dry
    import src.data.execution.host_plan as hp
    import src.data.style.header as hdr
    now = dt.datetime(2026, 11, 2, 12, 0, tzinfo=dt.timezone.utc)
    redis, sent = {}, []

    async def read_all(t, params):
        assert t == "loop_attempt"
        return [{"at": "2026-11-02T08:00:00+00:00", "detail": {"kind": "heartbeat", "trade_account": "0xabc"}}]

    async def hl(body):
        return {"spotClearinghouseState": {"balances": [{"coin": "UBTC", "total": "0.002"}, {"coin": "USDC", "total": "300"}]},
                "clearinghouseState": {"assetPositions": []}, "frontendOpenOrders": []}[body["type"]]

    async def core(asof):
        return {"ok": True, "asof": asof, "stop_px": {"BTC": 60000.0, "ETH": 2000.0}}

    async def halt():
        return False, "miss"

    async def get(k):
        return redis.get(k), "hit" if k in redis else "miss"

    async def put(k, v, ttl=0):
        redis[k] = v
        return True

    async def tg(text):
        sent.append(text)
        return True
    monkeypatch.setattr(hdr, "_read_all", read_all)
    monkeypatch.setattr(la, "hl_info", hl)
    monkeypatch.setattr(hp, "plan_core", core)
    monkeypatch.setattr(hp, "read_halt", halt)
    monkeypatch.setattr(dry, "_spot_quotes_sync", lambda c, t: {"BTC": {"mid": 59000.0}, "ETH": {"mid": 2100.0}})
    monkeypatch.setattr(store, "redis_get_key_status", get)
    monkeypatch.setattr(store, "redis_set_key", put)
    monkeypatch.setattr(notify, "notify_telegram", tg)
    r = asyncio.run(g.run_once(now))
    assert r["ok"] and r["host_age_h"] == 4.0 and r["delivered"] == ["spot:BTC"] and len(sent) == 1
    r2 = asyncio.run(g.run_once(now))
    assert r2["delivered"] == [] and len(sent) == 1, "同一天第二轮不重复报"


def test_the_guard_never_trades():
    src = Path(g.__file__).read_text(encoding="utf-8")
    for w in ("exchange", "order(", "cancel(", "private_key", "SECRET"):
        assert w not in src.replace("不下单、不撤单", ""), w
