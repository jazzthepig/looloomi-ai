"""T-082 B(11-02):HL 盘口深度 —— ±1% / ±2% 两边、原始档不够用聚合档、覆盖不到写下限不外推、一批一个时点、容量取 min 边 ÷ 5%。"""
import asyncio
import datetime as dt

from src.data.market import venue_depth as vd


def _book(bids, asks):
    return {"levels": [[{"px": str(p), "sz": str(s), "n": 1} for p, s in bids], [{"px": str(p), "sz": str(s), "n": 1} for p, s in asks]]}


def test_band_depth_counts_only_levels_inside_the_band():
    fine = _book([(99.9, 10), (99.5, 10), (98.9, 10), (97.5, 10)], [(100.1, 10), (100.6, 10), (101.5, 10), (102.5, 10)])
    m = vd.measure(fine)
    assert m["mid"] == 100.0 and m["spread_bps"] == 20.0 and m["granularity"] == "raw"
    assert m["depth_1pct_bid_usd"] == round(99.9 * 10 + 99.5 * 10, 2)
    assert m["depth_2pct_ask_usd"] == round((100.1 + 100.6 + 101.5) * 10, 2), "102.5 在 +2% 之外"
    assert m["covered_bid_pct"] == 2.5 and m["covered_ask_pct"] == 2.5


def test_coarse_book_is_used_only_for_the_side_the_raw_book_cannot_reach():
    fine = _book([(99.99, 1), (99.98, 1)], [(100.01, 1), (102.5, 1)])           # 买盘原始档只到 0.02%
    coarse = _book([(99.9, 50), (99.0, 50), (97.0, 50)], [(100.0, 9), (103.0, 9)])
    m = vd.measure(fine, coarse)
    assert m["granularity"] == "nSigFigs=3" and m["covered_bid_pct"] == 3.0
    assert m["depth_1pct_bid_usd"] == round(99.9 * 50 + 99.0 * 50, 2), "买盘换成聚合档"
    assert m["depth_2pct_ask_usd"] == 100.01, "卖盘原始档已覆盖到 2.5%,不换"
    assert vd.measure(_book([], [(1, 1)])) is None, "一边空 ⇒ 不写 0"


def test_thin_book_is_a_lower_bound_not_extrapolated():
    m = vd.measure(_book([(99.95, 1)], [(100.05, 1)]), _book([(99.9, 2)], [(100.1, 2)]))
    assert m["covered_bid_pct"] < 2 and m["depth_2pct_bid_usd"] == round(99.9 * 2, 2)
    cap = vd.venue_capacity([{"venue": "hyperliquid_spot", "symbol": "X", **m}], 0.05)
    assert cap["X"]["lower_bound"] is True


def test_slots_and_capacity_prefers_spot():
    assert vd.slot_for(dt.datetime(2026, 11, 2, 7, 59, tzinfo=dt.timezone.utc)).hour == 0
    assert vd.slot_for(dt.datetime(2026, 11, 2, 16, 0, tzinfo=dt.timezone.utc)).hour == 16
    rows = [{"venue": "hyperliquid_perp", "symbol": "BTC", "depth_1pct_bid_usd": 9e7, "depth_1pct_ask_usd": 8e7,
             "depth_2pct_bid_usd": 2e8, "depth_2pct_ask_usd": 1.5e8, "spread_bps": 0.1, "covered_bid_pct": 2.5, "covered_ask_pct": 2.5},
            {"venue": "hyperliquid_spot", "symbol": "BTC", "depth_1pct_bid_usd": 3e6, "depth_1pct_ask_usd": 2e6,
             "depth_2pct_bid_usd": 4e6, "depth_2pct_ask_usd": 3.5e6, "spread_bps": 0.1, "covered_bid_pct": 2.5, "covered_ask_pct": 2.5}]
    cap = vd.venue_capacity(rows, 0.05)["BTC"]
    assert cap["venue"] == "hyperliquid_spot" and cap["venue_capacity_aum_usd"] == 70_000_000, "① 只持现货:容量按现货"
    assert cap["other"]["venue"] == "hyperliquid_perp"


def test_run_once_samples_once_per_slot(monkeypatch):
    import src.api.store as store
    import src.data.style.header as hdr
    written = []

    class R:
        ok, why = True, None

    async def read_all(t, params):
        return [{"fetched_utc": "x"}] if written else []

    async def ins(t, rows):
        written.extend(rows)
        return R()

    async def coins():
        return ["BTC"]
    monkeypatch.setattr(hdr, "_read_all", read_all)
    monkeypatch.setattr(store, "supabase_insert_table", ins)
    monkeypatch.setattr(vd, "perp_coins", coins)
    monkeypatch.setattr(vd, "sample_sync", lambda c, cs, at: ([{"venue": "hyperliquid_perp", "symbol": "BTC"}], []))
    now = dt.datetime(2026, 11, 2, 8, 30, tzinfo=dt.timezone.utc)
    r = asyncio.run(vd.run_once(now))
    assert r["ok"] and r["written"] == 1 and r["slot"].startswith("2026-11-02T08:00")
    assert asyncio.run(vd.run_once(now))["status"] == "skipped"


def test_book_venue_capacity_is_the_thinnest_holding_over_its_weight():
    from src.data.accounting.capacity import book_venue
    vcap = {"BTC": {"depth_2pct_min_usd": 4e6, "venue": "hyperliquid_spot"},
            "ETH": {"depth_2pct_min_usd": 8e5, "venue": "hyperliquid_spot"}}
    r = book_venue({"BTC": 0.6, "ETH": 0.3, "DOGE": 0.1}, vcap)
    assert r["venue_binding"]["symbol"] == "ETH" and r["venue_capacity_aum_usd"] == round(8e5 / 0.3)
    assert r["missing_depth"] == ["DOGE"], "没有深度数据的持仓单列,不当成无限深"
    assert r["venue_ok_at_target"] is False
    assert book_venue({}, vcap)["venue_capacity_aum_usd"] is None
