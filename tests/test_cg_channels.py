"""上游通道序列:分类按关键词发现、加总不补缺、时间戳语义。"""
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from src.data.channels import cg_channels as c


def test_discover_routes_category_ids_by_keyword_once():
    ids = {"stablecoins", "usd-stablecoin", "tokenized-gold", "tokenized-treasury-bills",
           "real-world-assets-rwa", "layer-1", "meme-token"}
    f = c.discover(ids)
    assert f["stablecoin"] == ["stablecoins", "usd-stablecoin"]
    assert f["tokenized"] == ["tokenized-gold", "tokenized-treasury-bills"]
    assert f["rwa"] == ["real-world-assets-rwa"]
    assert sum(len(v) for v in f.values()) == 5


def test_aggregate_sums_members_counts_once_and_never_fills():
    idx = pd.date_range("2026-01-01", periods=3, freq="D")
    mc = pd.DataFrame({"usdt": [100.0, 110.0, np.nan], "usdc": [50.0, np.nan, np.nan]}, index=idx)
    rows = c.aggregate(mc, {"stablecoin/*": ["usdt", "usdc", "usdt"]})
    assert [(r["d"], r["mcap"], r["n_members"]) for r in rows] == [
        ("2026-01-01", 150.0, 2), ("2026-01-02", 110.0, 1)]          # 第三天全缺 ⇒ 不出行,不是 0


def test_global_points_near_midnight_map_to_the_previous_day():
    ms = lambda y, m, d, hh=0, mm=0: int(datetime(y, m, d, hh, mm, tzinfo=timezone.utc).timestamp() * 1000)
    pts = [[ms(2026, 9, 29, 0, 5), 1.0], [ms(2026, 9, 29, 0, 30), 2.0], [ms(2026, 9, 29, 13), 3.0]]
    assert c.daily_points(pts) == {"2026-09-28": 1.0}


def test_run_once_end_to_end_with_fakes(monkeypatch):
    import asyncio
    import src.api.store as store
    import src.data.market.data_layer as dl
    import src.data.style.header as sh
    import src.data.vector.market_state_writer as msw
    ms = lambda d: int(datetime(2026, 9, d, tzinfo=timezone.utc).timestamp() * 1000)

    async def cat_ids():
        return {"stablecoins", "tokenized-treasury-bills", "layer-1"}
    async def cat_markets(cid, n):
        return [{"id": "tether"}, {"id": "usd-coin"}] if cid == "stablecoins" else [{"id": "buidl"}]
    async def chart(coin, a, b, interval=None):
        return {"available": True, "prices": [[ms(1), 1.0], [ms(2), 1.0]], "market_caps": [[ms(1), 10.0], [ms(2), 11.0]]}
    async def gchart(days):
        return {"market_cap": [[ms(1), 3e12], [ms(2), 3.1e12]], "volume": [[ms(1), 1e11]]}
    store_rows = {}
    async def upsert(table, rows, on_conflict=None):
        store_rows.setdefault(table, []).extend(rows)
        class R: ok = True; why = None
        return R()
    class SB:
        def __init__(self, rows): self.ok, self.rows, self.reason = True, rows, None
    async def sb_get(table, params):
        return SB([])
    async def read_all(table, params):
        return [r for r in store_rows.get("cg_coin_mcap_daily", [])]
    monkeypatch.setattr(dl, "get_cg_category_ids", cat_ids)
    monkeypatch.setattr(dl, "get_cg_category_markets", cat_markets)
    monkeypatch.setattr(dl, "get_cg_market_chart_range", chart)
    monkeypatch.setattr(dl, "get_cg_global_market_cap_chart", gchart)
    monkeypatch.setattr(store, "supabase_upsert_table", upsert)
    monkeypatch.setattr(msw, "_sb_get", sb_get)
    monkeypatch.setattr(sh, "_read_all", read_all)
    async def no_sleep(*a, **k):
        return None
    monkeypatch.setattr(c.asyncio, "sleep", no_sleep)
    r = asyncio.run(c.run_once())
    assert r["ok"], r
    ser = store_rows["channel_series_daily"]
    st = [x for x in ser if x["channel"] == "stablecoin" and x["category_id"] == "*"]
    assert {x["d"]: x["mcap"] for x in st} == {"2026-08-31": 20.0, "2026-09-01": 22.0}
    assert any(x["channel"] == "global" and x["category_id"] == "market_cap" for x in ser)

