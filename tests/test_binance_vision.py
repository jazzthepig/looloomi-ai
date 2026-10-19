"""T-133 Binance 公开历史档 → 持仓结构日度特征:按列名解析、缺列明说、只收当天的点、缺档记 0 不重取、
最近两天的缺档不落(可能只是还没上传)、回补计划先新后旧并按名字轮转。"""
import asyncio
import datetime as dt
import io
import zipfile

import pytest

from src.data.market import binance_vision as bv

HEADER = ("create_time,symbol,sum_open_interest,sum_open_interest_value,count_toptrader_long_short_ratio,"
          "sum_toptrader_long_short_ratio,count_long_short_ratio,sum_taker_long_short_vol_ratio")


def _zip(lines, header=HEADER):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("BTCUSDT-metrics-2026-10-15.csv", "\n".join([header, *lines]))
    return buf.getvalue()


def test_features_come_from_named_columns_and_only_that_utc_day():
    blob = _zip(["2026-10-14 23:55:00,BTCUSDT,1,1,9,9,9,9",
                 "2026-10-15 00:00:00,BTCUSDT,100,8000000,1.8,1.5,1.7,0.6",
                 "2026-10-15 21:00:00,BTCUSDT,110,8800000,1.9,1.3,1.6,1.4",
                 "2026-10-15 23:55:00,BTCUSDT,120,9600000,2.0,1.1,1.5,1.0"])
    f = bv.daily_features("BTC", "2026-10-15", bv.parse_metrics_zip(blob))
    assert f["n_points"] == 3, "前一天 23:55 那一行不算"
    assert f["oi_close"] == 120 and f["oi_value_close"] == 9_600_000
    assert f["top_pos_ratio_close"] == 1.1 and abs(f["top_pos_ratio_mean"] - (1.5 + 1.3 + 1.1) / 3) < 1e-9
    assert f["top_acct_ratio_close"] == 2.0 and f["global_acct_ratio_close"] == 1.5
    assert abs(f["taker_ratio_mean"] - 1.0) < 1e-9 and abs(f["taker_ratio_last4h"] - 1.2) < 1e-9


def test_a_renamed_column_is_an_error_that_names_it():
    with pytest.raises(ValueError, match="sum_taker_long_short_vol_ratio"):
        bv.parse_metrics_zip(_zip([], header=HEADER.replace("sum_taker_long_short_vol_ratio", "taker_ratio")))


def test_plan_fills_recent_gaps_first_then_backfills_round_robin():
    today = dt.date(2026, 10, 19)
    cov = [{"symbol": "BTC", "target_start": "2020-09-01", "last_d": "2026-10-19", "min_d": "2026-10-10", "max_d": "2026-10-16"},
           {"symbol": "ARB", "target_start": "2023-03-23", "last_d": "2026-10-19", "min_d": None, "max_d": None},
           {"symbol": "OLD", "target_start": "2020-09-01", "last_d": "2021-01-05", "min_d": "2020-09-01", "max_d": "2021-01-05"}]
    p = bv.plan(cov, today, budget=50, chunk=5)
    assert p[:2] == [("BTC", "2026-10-18"), ("BTC", "2026-10-17")], "先补最近缺的,今天(未收完)不取"
    assert ("ARB", "2026-10-18") in p and ("BTC", "2026-10-09") in p, "两名都在往回补"
    assert not any(s == "OLD" for s, _ in p), "已下架且补齐的名字不再取"
    assert len(p) == 50
    full = bv.plan(cov, today, budget=10_000, chunk=5)
    assert ("ARB", "2023-03-23") in full and ("ARB", "2023-03-22") not in full, "不早于上市日"


def test_missing_files_are_recorded_only_when_final(monkeypatch):
    import src.data.market.data_layer as dl

    async def none(kind, pair, day):
        return None
    monkeypatch.setattr(dl, "get_binance_vision_um_daily", none)
    today = dt.date(2026, 10, 19)
    sem = asyncio.Semaphore(1)
    old, _ = asyncio.run(bv._fetch_one("ARB", "2023-03-01", today, sem))
    recent, _ = asyncio.run(bv._fetch_one("BTC", "2026-10-18", today, sem))
    assert old["n_points"] == 0 and old["oi_close"] is None, "早就该有的日子没有文件 ⇒ 记下来,不再重取"
    assert recent is None, "最近两天可能只是还没上传 ⇒ 不落行,下一轮重试"

    async def boom(kind, pair, day):
        raise RuntimeError("HTTP 451")
    monkeypatch.setattr(dl, "get_binance_vision_um_daily", boom)
    row, err = asyncio.run(bv._fetch_one("BTC", "2024-01-01", today, sem))
    assert row is None and "451" in err, "读不到 ≠ 没有"
