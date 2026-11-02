"""S-469:映射表读不到时,本轮不解析、不覆盖;人工确认的映射不被自动解析覆盖。"""
import asyncio

from src.data.market import cg_panel_sync as ps
from src.data.market import cg_pro_backfill as bf


def _run(rows_or_none, panel, monkeypatch, resolved=None):
    upserts, gets = [], []

    async def q(table, cols):
        if isinstance(rows_or_none, Exception):
            raise rows_or_none
        return rows_or_none

    async def up(table, rows, on_conflict):
        upserts.append(rows)
        return True

    class Client:
        async def get(self, *a, **k):
            gets.append(a)
            raise AssertionError("映射读不到时不该去 CoinGecko 重新解析")

    class Res:
        rows_written, ok, per_symbol, reason = 1, True, (), ""

    async def fake_backfill(*a, **k):
        return Res()
    monkeypatch.setattr(bf, "backfill", fake_backfill)
    out = asyncio.run(ps.run_once(client=Client(), supabase_query=q, supabase_upsert=up,
                                  panel_symbols=panel, today="2026-10-03"))
    return out, upserts, gets


def test_unreadable_map_refuses_the_round(monkeypatch):
    for bad in (None, [], RuntimeError("timeout")):
        out, upserts, gets = _run(bad, ["ONE", "AI", "BTC"], monkeypatch)
        assert out["status"] == "error" and "读不到" in out["error"]
        assert upserts == [] and gets == []


def test_readable_map_leaves_manual_rows_alone(monkeypatch):
    rows = [{"symbol": "ONE", "coin_id": "harmony", "resolved_from": "manual_verified"},
            {"symbol": "BTC", "coin_id": "bitcoin", "resolved_from": "list_unique"}]
    out, upserts, gets = _run(rows, ["ONE", "BTC"], monkeypatch)
    assert upserts == [] and gets == []
    assert out["n_missing"] == 0


def test_mcap_resolved_known_symbols_are_refreshed_but_must_pass_the_check(monkeypatch):
    """S-471:BTC/ETH/SOL 在映射表里是 mcap_tiebreak —— 原来整批不进日更回填,① 面板 24 个里 18 个没有日更写入端。
    现在它们进回填,但不在 vendor_paired 里(查不到对照就拒写,不放行)。"""
    rows = [{"symbol": "BTC", "coin_id": "bitcoin", "resolved_from": "mcap_tiebreak"},
            {"symbol": "AAVE", "coin_id": "aave", "resolved_from": "list_unique"},
            {"symbol": "ONE", "coin_id": "harmony", "resolved_from": "manual_verified"}]
    seen = {}

    async def q(table, cols):
        return rows

    async def up(table, r, on_conflict):
        return True

    class Client:
        async def get(self, *a, **k):
            raise AssertionError("没有缺失的标的,不该去解析")

    class Res:
        rows_written, ok, per_symbol, reason = 3, True, (), ""

    async def fake_backfill(pairs, **k):
        seen["pairs"], seen["vendor"] = list(pairs), set(k["vendor_paired"])
        return Res()
    monkeypatch.setattr(bf, "backfill", fake_backfill)
    out = asyncio.run(ps.run_once(client=Client(), supabase_query=q, supabase_upsert=up,
                                  panel_symbols=["BTC", "AAVE", "ONE"], today="2026-10-03"))
    assert ("BTC", "bitcoin") in seen["pairs"]
    assert "BTC" not in seen["vendor"] and {"AAVE", "ONE"} <= seen["vendor"]
    assert out["n_mcap_required_check"] == 1 and out["status"] == "ok"


def test_cis_crypto_names_are_always_in_the_panel_with_their_verified_ids():
    """11-02(T-220「SKY 撞名」根因):面板只覆盖 Binance 永续宇宙,CIS 的 25 个加密名字不一定在里面 —— SKY 在 ohlcv_daily
    只有 15 行 HL 永续。ensure_cis_names 把 CIS 名字并进面板,缺映射的按 cis_provider 的 coingecko id 写成 manual_verified。"""
    written = []

    async def q(table, cols):
        return [{"symbol": "BTC", "coin_id": "bitcoin", "resolved_from": "list_unique"},
                {"symbol": "MKR", "coin_id": "maker", "resolved_from": "list_unique"}]

    async def up(table, rows, on_conflict):
        written.append((table, rows, on_conflict))
        return True
    panel, added = asyncio.run(ps.ensure_cis_names(q, up, ["BTC", "MKR", "DOGE"]))
    assert "SKY" in panel and "HYPE" in panel and "DOGE" in panel and panel == sorted(set(panel))
    assert "SKY" in added and "BTC" not in added
    t, rows, oc = written[0]
    sky = next(r for r in rows if r["symbol"] == "SKY")
    assert t == "cg_coin_map" and oc == "symbol" and sky["coin_id"] == "sky" and sky["resolved_from"] == "manual_verified"

    async def q_none(table, cols):
        return None
    panel2, added2 = asyncio.run(ps.ensure_cis_names(q_none, up, ["BTC"]))
    assert "SKY" in panel2 and added2 == [], "映射表读不到 ⇒ 不写、只并面板"
