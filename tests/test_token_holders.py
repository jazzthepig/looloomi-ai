"""代币持有人数历史(11-06):只取本链(平台字典第一个键)、不支持的网络跳过、同日取最后一个点、回填按日轮换、日频只补落后的。"""
from __future__ import annotations

import asyncio
import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.market import token_holders as th  # noqa: E402

TODAY = dt.date(2026, 11, 6)


def test_home_chain_is_the_first_platform_only():
    assert th.home_chain({"arbitrum-one": "0x912", "ethereum": "0xb50"}) == ("arbitrum", "0x912")
    assert th.home_chain({"hyperevm": "0xabc", "ethereum": "0xdef"}) is None, "本链不支持就跳过,不拿桥过去的副本"
    assert th.home_chain({"": ""}) is None and th.home_chain({}) is None and th.home_chain(None) is None
    assert th.home_chain({"solana": "DezX"}) == ("solana", "DezX")


def test_parse():
    pay = {"data": {"attributes": {"token_holders_list": [["2026-04-28T00:00:00.000Z", 52790], ["2026-04-28T12:00:00.000Z", 52800],
                                                          ["2026-04-29T00:00:00.000Z", 0], ["bad", 1]]}}}
    rows = th.parse(pay, "pippin", "solana", "Dfh5", "weekly", "t")
    assert rows == [{"d": "2026-04-28", "coin_id": "pippin", "network": "solana", "address": "Dfh5", "holders": 52800,
                     "granularity": "weekly", "fetched_at": "t"}]
    assert th.parse({"errors": []}, "x", "eth", "0x", "daily", "t") == []


def test_choose():
    uni = [{"coin_id": "a", "last_mcap": 3}, {"coin_id": "b", "last_mcap": 2}, {"coin_id": "c", "last_mcap": 1}, {"coin_id": "native", "last_mcap": 9}]
    homes = {"a": ("eth", "0xa"), "b": ("eth", "0xb"), "c": ("solana", "C")}
    cov = {"a": {"max_d": "2026-11-06", "n_weekly": 50}, "b": {"max_d": "2026-11-01", "n_weekly": 40}}
    back, daily = th.choose(uni, homes, cov, TODAY)
    assert back == ["c"] and daily == ["b"]


def test_run_once():
    async def fetch(path, params):
        if path == "/coins/list":
            return [{"id": "c", "platforms": {"solana": "C"}}, {"id": "bitcoin", "platforms": {}}]
        return {"data": {"attributes": {"token_holders_list": [["2026-11-01T00:00:00Z", 10], ["2026-11-02T00:00:00Z", 11]]}}}

    async def read(view, params):
        return [{"coin_id": "c", "last_mcap": 1}, {"coin_id": "bitcoin", "last_mcap": 9}] if view == th.UNIVERSE_VIEW else []

    out = []

    async def upsert(t, rows, on_conflict=None):
        out.extend(rows)
        return True

    r = asyncio.run(th.run_once(now=dt.datetime(2026, 11, 6, tzinfo=dt.timezone.utc), fetch=fetch, read=read, upsert=upsert))
    assert r["ok"] and r["in_scope"] == 1 and r["written"] == 2 and set(out[0]) == set(th.WRITES_COLUMNS[th.TABLE])


def test_wiring():
    assert "async def _token_holders_loop" in (ROOT / "src/api/main.py").read_text(encoding="utf-8")
    mig = (ROOT / "migrations/2026-11-06_token_holders_daily.sql").read_text(encoding="utf-8")
    assert all(c in mig for c in th.WRITES_COLUMNS[th.TABLE]) and th.UNIVERSE_VIEW in mig and th.COVERAGE_VIEW in mig
