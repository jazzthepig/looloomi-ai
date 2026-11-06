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
    import src.data.market.hyperliquid_collector as hc
    seen = {}

    async def snap():
        return {"ok": True, "assets": {"BTC": {"day_notional_volume": 4e9}}}
    monkeypatch.setattr(hc, "venue_snapshot", snap)

    def sample(c, cs, at, pa=None):
        seen["pa"] = pa
        return [{"venue": "hyperliquid_perp", "symbol": "BTC", "day_ntl_vlm_usd": 4e9}], []
    monkeypatch.setattr(vd, "sample_sync", sample)
    now = dt.datetime(2026, 11, 2, 8, 30, tzinfo=dt.timezone.utc)
    r = asyncio.run(vd.run_once(now))
    assert r["ok"] and r["written"] == 1 and r["slot"].startswith("2026-11-02T08:00") and r["with_volume"] == 1
    assert seen["pa"] == {"BTC": {"day_notional_volume": 4e9}}, "永续成交来自同一时点的一次 metaAndAssetCtxs"
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


def test_every_weighted_book_is_in_the_capacity_report():
    """11-02:cis_tilt 被同一行的行尾注释吞掉,容量报告少了一本账、没有任何报错。"""
    from src.data.accounting.capacity import WEIGHTED_BOOKS
    assert set(WEIGHTED_BOOKS) == {"core_cap", "cis_tilt", "beta_plus_w", "beta_plus_m", "tokenization_tilt"}


def test_perp_flow_reads_the_one_request_snapshot_and_never_writes_zero_for_missing():
    assets = {"BTC": {"day_notional_volume": 4.0e9, "open_interest": 30_000.0, "mark": 100_000.0},
              "KPEPE": {"day_notional_volume": None, "open_interest": None, "mark": 0.01}}
    assert vd.perp_flow(assets, "BTC") == (4.0e9, 3.0e9)
    assert vd.perp_flow(assets, "kPEPE") == (None, None), "HL 名字大小写不一致(kPEPE)⇒ 按大写找;缺值不写 0"
    assert vd.perp_flow(None, "BTC") == (None, None)


def test_sample_rows_carry_venue_volume_spot_from_ctx_perp_from_snapshot():
    class P:
        name, day_ntl_vlm = "@142", 7.2e7

    class Fx:
        def __init__(self, *a):
            pass

        def find_pair_by_token(self, tok):
            return P() if tok == "UBTC" else None

    class C:
        def spot_meta(self):
            return {}

        def spot_meta_and_asset_ctxs(self):
            return []

        def l2_book(self, ex, n_sig_figs=None):
            return _book([(99.0, 100)], [(101.0, 100)])

    import src.data.venues.hl_spot as hs
    orig = hs.HlSpotFixture
    hs.HlSpotFixture = Fx
    try:
        rows, failed = vd.sample_sync(C(), ["ETH"], "t", {"ETH": {"day_notional_volume": 1.1e9, "open_interest": 1000.0, "mark": 3000.0}})
    finally:
        hs.HlSpotFixture = orig
    by = {(r["venue"], r["symbol"]): r for r in rows}
    assert by[("hyperliquid_spot", "BTC")]["day_ntl_vlm_usd"] == 7.2e7 and by[("hyperliquid_spot", "BTC")]["open_interest_usd"] is None
    assert by[("hyperliquid_perp", "ETH")]["day_ntl_vlm_usd"] == 1.1e9 and by[("hyperliquid_perp", "ETH")]["open_interest_usd"] == 3.0e6
    assert all(set(r) <= set(vd.WRITES_COLUMNS[vd.TABLE]) for r in rows), "写的列都在 WRITES_COLUMNS 里"


def test_venue_flow_capacity_is_the_market_formula_with_venue_volume():
    from src.api.contracts.fund import BUILD_DAYS, PARTICIPATION_RATE
    from src.data.accounting.capacity import book_venue, market_to_venue
    rows = [{"venue": "hyperliquid_spot", "symbol": "BTC", "depth_2pct_bid_usd": 4e6, "depth_2pct_ask_usd": 3e6,
             "depth_1pct_bid_usd": 2e6, "depth_1pct_ask_usd": 2e6, "spread_bps": 1, "covered_bid_pct": 3, "covered_ask_pct": 3,
             "day_ntl_vlm_usd": v} for v in (6e7, 7e7, 8e7, None)]
    cap = vd.venue_capacity(rows, 0.05)["BTC"]
    assert cap["venue_adv_usd"] == 7e7 and cap["n_volume_snapshots"] == 3, "中位数只用有成交的快照"
    assert cap["venue_flow_capacity_aum_usd"] == round(7e7 * PARTICIPATION_RATE * BUILD_DAYS / 0.05)
    r = book_venue({"BTC": 0.7, "ETH": 0.3}, {"BTC": cap, "ETH": {"depth_2pct_min_usd": 1e6, "venue": "hyperliquid_spot"}})
    assert r["venue_flow_binding"]["symbol"] == "BTC" and r["missing_venue_volume"] == ["ETH"], "缺场所成交的持仓单列,不当成无限"
    assert r["venue_flow_capacity_aum_usd"] == round(7e7 * PARTICIPATION_RATE * BUILD_DAYS / 0.7)
    assert market_to_venue(3.5e10, cap) == 500.0 and market_to_venue(None, cap) is None and market_to_venue(1e9, {}) is None


def test_volume_columns_are_in_a_migration():
    from pathlib import Path
    mig = (Path(__file__).resolve().parents[1] / "migrations/2026-11-06_venue_depth_volume.sql").read_text(encoding="utf-8")
    assert "day_ntl_vlm_usd" in mig and "open_interest_usd" in mig
