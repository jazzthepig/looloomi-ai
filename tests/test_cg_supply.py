"""供给拆分 + 新币(11-06):缺总量不编、锁仓钱包数与异常、新币时间戳、宇宙只取最近还有市值的、404 记住不再问、第一次看见的时间不被覆盖。"""
from __future__ import annotations

import asyncio
import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.market import cg_supply as cs  # noqa: E402

UNI = {"id": "uniswap", "supply_data": {"total_supply": 894.0, "circulating_supply": 622.0, "non_circulating_supply": 272.0,
                                        "last_updated": "2026-06-15T04:23:07Z"},
       "non_circulating_wallets": [{"address": "0x1", "balance": 272.0, "anomaly": False}, {"address": "0x2", "anomaly": True}]}


def test_supply_row():
    r = cs.supply_row(UNI, "2026-11-06", "t")
    assert r["n_wallets"] == 2 and r["anomaly"] is True and r["non_circulating_supply"] == 272.0 and set(r) == set(cs.WRITES_COLUMNS[cs.SUPPLY_TABLE])
    assert cs.supply_row({"id": "x", "supply_data": {}}, "d", "t") is None and cs.supply_row(None, "d", "t") is None


def test_new_coin_rows():
    rows = cs.new_coin_rows([{"id": "cat", "symbol": "c", "name": "Cat", "activated_at": 1778737128}, {"id": "bad", "activated_at": "x"}], "t")
    assert len(rows) == 1 and rows[0]["activated_at"].startswith("2026-05-14") and set(rows[0]) == set(cs.WRITES_COLUMNS[cs.NEW_TABLE])


def test_pick_and_run_once(monkeypatch):
    today = dt.date(2026, 11, 6)
    uni = [{"coin_id": "uniswap", "last_d": "2026-11-05", "last_mcap": 5}, {"coin_id": "dead", "last_d": "2026-01-01", "last_mcap": 9},
           {"coin_id": "nob", "last_d": "2026-11-05", "last_mcap": 1}]
    cs._NO_BREAKDOWN.clear()
    assert cs.pick(uni, today) == ["uniswap", "nob"]

    async def fetch(path, params=None):
        if path == "/coins/list/new":
            return [{"id": "cat", "symbol": "c", "name": "Cat", "activated_at": 1778737128}, {"id": "old", "activated_at": 1778737000}]
        return UNI if "uniswap" in path else None

    async def read(t, params):
        return uni if t == cs.UNIVERSE_VIEW else [{"coin_id": "old"}]

    out: dict = {}

    async def upsert(t, rows, on_conflict=None):
        out.setdefault(t, []).extend(rows)
        return True

    r = asyncio.run(cs.run_once(now=dt.datetime(2026, 11, 6, tzinfo=dt.timezone.utc), fetch=fetch, read=read, upsert=upsert))
    assert r["ok"] and r["supply_rows"] == 1 and r["no_breakdown"] == 1
    assert [x["coin_id"] for x in out[cs.NEW_TABLE]] == ["cat"], "已见过的新币不重写 first_seen_at"
    assert "nob" in cs._NO_BREAKDOWN and cs.pick(uni, today) == ["uniswap"]


def test_wiring():
    assert "async def _cg_supply_loop" in (ROOT / "src/api/main.py").read_text(encoding="utf-8")
    mig = (ROOT / "migrations/2026-11-06_cg_supply.sql").read_text(encoding="utf-8")
    assert all(c in mig for t in cs.WRITES_TABLES for c in cs.WRITES_COLUMNS[t])


def test_categories_snapshot():
    from src.data.market import cg_categories as cc
    rows = cc.rows_from([{"id": "layer-1", "name": "Layer 1 (L1)", "market_cap": 2.1e12, "market_cap_change_24h": -0.5, "volume_24h": 4e10,
                          "top_3_coins_id": ["bitcoin", "ethereum", "binancecoin"]},
                         {"id": "tiny", "market_cap": 10}, {"id": None, "market_cap": 1e9}], "2026-11-06", "t")
    assert len(rows) == 1 and rows[0]["top3"] == ["bitcoin", "ethereum", "binancecoin"] and set(rows[0]) == set(cc.WRITES_COLUMNS[cc.TABLE])
    mig = (ROOT / "migrations/2026-11-06_cg_supply.sql").read_text(encoding="utf-8")
    assert all(c in mig for c in cc.WRITES_COLUMNS[cc.TABLE])
