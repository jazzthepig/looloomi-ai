"""11-11 BTC 周期指标:MVRV / 发行美元价值 / 算力按天落 macro_daily;Puell 读时现算,只用 ≤ d。"""
import asyncio
import datetime as dt
from types import SimpleNamespace

from src.data.market import btc_cycle as bc


def test_rows_drop_missing_and_non_positive_never_write_zero():
    raw = [{"time": "2026-11-10T00:00:00.000000000Z", "CapMVRVCur": "1.3666", "IssTotUSD": "31075736.4", "HashRate": "995657714.6"},
           {"time": "2026-11-11T00:00:00.000000000Z", "CapMVRVCur": "", "IssTotUSD": "0", "HashRate": "nan"},
           {"time": "bad", "CapMVRVCur": "2"}]
    rows = bc.to_rows(raw)
    assert {(r["series"], r["d"]) for r in rows} == {("btc_mvrv", "2026-11-10"), ("btc_issuance_usd", "2026-11-10"), ("btc_hashrate", "2026-11-10")}, \
        "PriceUSD 这两行没给 ⇒ 没有 btc_price_usd 行"
    assert all(r["value"] > 0 and r["source"] == bc.SOURCE for r in rows)


def test_puell_uses_only_data_up_to_d():
    iss = {(dt.date(2025, 1, 1) + dt.timedelta(days=i)).isoformat(): 100.0 for i in range(400)}
    d = "2025-12-31"
    iss[d] = 200.0
    future = (dt.date.fromisoformat(d) + dt.timedelta(days=1)).isoformat()
    p = bc.puell(iss, d)
    iss[future] = 10_000.0
    assert p == bc.puell(iss, d), "加了未来的值,d 的 Puell 不变"
    assert abs(p - 200.0 / ((364 * 100.0 + 200.0) / 365)) < 1e-9
    assert bc.puell(iss, "2025-02-01") is None, "不足 365 天 ⇒ None"


def test_first_run_backfills_full_history_then_only_recent(monkeypatch):
    import src.api.store as store
    import src.data.market.data_layer as dl
    import src.data.vector.market_state_writer as msw
    calls, written = [], []

    async def fetch(metrics, start):
        calls.append(start)
        return [{"time": "2026-11-10T00:00:00Z", "CapMVRVCur": "1.4", "IssTotUSD": "3e7", "HashRate": "9e8"}]

    async def sb_get(table, params):
        return SimpleNamespace(ok=True, rows=list(have), why=None)

    async def upsert(table, rows, on_conflict):
        written.extend(rows)
        return True

    async def kget(k):
        return None, None

    async def kset(*a, **k):
        return True
    have = []
    monkeypatch.setattr(dl, "get_coinmetrics_btc", fetch)
    monkeypatch.setattr(msw, "_sb_get", sb_get)
    monkeypatch.setattr(store, "supabase_upsert_table", upsert)
    monkeypatch.setattr(store, "redis_get_key_status", kget)
    monkeypatch.setattr(store, "redis_set_key", kset)
    now = dt.datetime(2026, 11, 11, 1, 0, tzinfo=dt.timezone.utc)
    r = asyncio.run(bc.run_once(now))
    assert r["ok"] and calls[-1] == bc.HISTORY_FROM and len(written) == 3
    have.append({"d": "2026-11-10"})
    asyncio.run(bc.run_once(now))
    assert calls[-1] == "2025-09-17", "派生序列已有 ⇒ 只取 420 天(够重算最近 14 天的 Puell)"


def test_derived_series_are_puell_and_hashrate_change_from_the_same_functions():
    """11-11:派生序列(Puell / 算力 30 天变化)落库后自动成为融合特征表的维;写入端与读的人同一个纯函数。"""
    import math
    days = [(dt.date(2025, 1, 1) + dt.timedelta(days=i)).isoformat() for i in range(400)]
    base = [{"series": "btc_issuance_usd", "d": d, "value": 100.0, "source": "x"} for d in days] + \
           [{"series": "btc_hashrate", "d": d, "value": 1000.0 * (2.0 if d >= days[380] else 1.0), "source": "x"} for d in days]
    out = bc.derived_rows(base, days[395])
    by = {(r["series"], r["d"]): r["value"] for r in out}
    assert by[("btc_puell", days[399])] == 1.0
    assert abs(by[("btc_hash_30d", days[399])] - math.log(2.0)) < 1e-12, "近 7 天都在翻倍之后、30 天前的 7 天都在之前"
    assert all(r["d"] >= days[395] for r in out)
    assert bc.hash_30d({days[0]: 1.0}, days[0]) is None and bc.derived_rows(base[:300], days[0]) == [], "不满窗口的那天不写(300 天发行不够 365)"
