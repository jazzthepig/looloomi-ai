"""S-638 后续:资金费率月档 → funding_history。按列名解析、取最近整点、404 记缺档不重取、读失败不写、半数失败整轮拒写、
新月优先;取数只经 data_layer 的同一个入口(monthly=True),不新开取数函数。"""
import asyncio
import io
import zipfile

import pytest

from src.data.market import binance_vision_funding as vf

HEAD = "calc_time,funding_interval_hours,last_funding_rate"


def _zip(lines, header=HEAD):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("CRVUSDT-fundingRate-2024-01.csv", "\n".join(([header] if header else []) + lines))
    return buf.getvalue()


def test_parse_by_column_name_and_round_to_the_nearest_hour():
    blob = _zip(["1704067200000,8,0.0001", "1704095999998,8,-0.00025", "bad,8,x"])
    items = vf.parse_funding_zip(blob)
    assert items == [(1704067200000, 0.0001), (1704095999998, -0.00025)], "读不出的行跳过,不补 0"
    rows = vf.funding_rows("CRV", items)
    assert rows[0]["funding_time"].startswith("2024-01-01T00:00:00")
    assert rows[1]["funding_time"].startswith("2024-01-01T08:00:00"), "整点前 2 毫秒 ⇒ 归到那个整点,不是前一小时"
    assert all(r["venue"] == "binance_perp" and r["mark_price"] is None and r["asset_id"] == "CRV" for r in rows)


def test_headerless_file_reads_first_and_last_column_and_unknown_header_is_named():
    assert vf.parse_funding_zip(_zip(["1704067200000,8,0.0003"], header=None)) == [(1704067200000, 0.0003)]
    with pytest.raises(ValueError, match="last_funding_rate"):
        vf.parse_funding_zip(_zip(["1,2"], header="when,rate_x"))


def test_plan_newest_month_first_then_by_symbol():
    rows = [{"symbol": "ZRX", "month": "2021-03-01"}, {"symbol": "CRV", "month": "2026-09-01"},
            {"symbol": "AAVE", "month": "2026-09-01"}, {"symbol": "CRV", "month": "2026-09-01"}]
    assert vf.plan(rows, budget=10) == [("AAVE", "2026-09"), ("CRV", "2026-09"), ("ZRX", "2021-03")]
    assert vf.plan(rows, budget=1) == [("AAVE", "2026-09")]


def test_missing_file_is_absent_failed_fetch_is_an_error(monkeypatch):
    import src.data.market.data_layer as dl
    calls = []

    async def none(kind, pair, day, *, monthly=False):
        calls.append((kind, pair, day, monthly))
        return None
    monkeypatch.setattr(dl, "get_binance_vision_um_daily", none)
    sem = asyncio.Semaphore(1)
    got, absent, err = asyncio.run(vf._fetch_one("ZRX", "2020-01", sem))
    assert got is None and err is None and absent == {"symbol": "ZRX", "month": "2020-01-01"}
    assert calls == [("fundingRate", "ZRXUSDT", "2020-01", True)], "同一个取数入口,月档参数"

    async def boom(kind, pair, day, *, monthly=False):
        raise RuntimeError("HTTP 451")
    monkeypatch.setattr(dl, "get_binance_vision_um_daily", boom)
    got, absent, err = asyncio.run(vf._fetch_one("CRV", "2024-01", sem))
    assert got is None and absent is None and "451" in err, "读不到 ≠ 没有:不记缺档,下一轮重试"


def test_half_failed_round_writes_nothing(monkeypatch):
    import src.api.store as store
    import src.data.market.data_layer as dl
    import src.data.style.header as header
    writes = []

    async def read_all(view, params):
        return [{"symbol": s, "month": "2026-09-01"} for s in ("A", "B", "C", "D")]

    async def flaky(kind, pair, day, *, monthly=False):
        if pair in ("AUSDT", "BUSDT", "CUSDT"):
            raise RuntimeError("HTTP 503")
        return _zip(["1788220800000,8,0.0001"])

    async def upsert(table, rows, on_conflict=None):
        writes.append(table)
        from src.api.store_result import StoreResult
        return StoreResult.ok_(value=None)
    monkeypatch.setattr(header, "_read_all", read_all)
    monkeypatch.setattr(dl, "get_binance_vision_um_daily", flaky)
    monkeypatch.setattr(store, "supabase_upsert_table", upsert)
    out = asyncio.run(vf.run_once(budget=10))
    assert out["refused"] and not out["ok"] and writes == [], "3/4 读不到 ⇒ 整轮拒写"


def test_data_layer_keeps_one_entry_point_and_whitelists_the_monthly_kind():
    import src.data.market.data_layer as dl
    assert "fundingRate" in dl.BINANCE_VISION_MONTHLY_KINDS and "fundingRate" not in dl.BINANCE_VISION_KINDS
    assert not hasattr(dl, "get_binance_vision_um_monthly"), "取数入口只减不增:月档走同一个函数的 monthly 参数"
    with pytest.raises(ValueError):                 # S-683 起 klines 进了白名单;白名单本身照样拦别的
        asyncio.run(dl.get_binance_vision_um_daily("aggTrades", "BTCUSDT", "2024-01", monthly=True))


def test_main_runs_it_inside_the_vision_loop_with_its_own_attempt_name():
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "src/api/main.py").read_text(encoding="utf-8")
    body = src.split("async def _binance_vision_loop", 1)[1].split("\nasync def ", 1)[0]
    assert "binance_vision_funding import run_once" in body
    assert body.count('"_binance_vision_funding"') >= 2, "成功与异常两条路都要记 loop_attempt"
