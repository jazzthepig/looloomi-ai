"""S-698:binance_hist 统一成现货 —— 逐日判定、先存档后覆盖、只写收集器之前的月份、同名不同币拒绝。"""
import io
import zipfile

import pytest

from src.data.market import binance_hist_repair as br


def _row(o, c, v, h=None, l=None):
    return {"open": o, "high": h or max(o, c), "low": l or min(o, c), "close": c, "volume": v, "asset_class": "Crypto"}


def _days(month, n=28):
    return [f"{month}-{d:02d}" for d in range(1, n + 1)]


def test_parse_month_keys_and_spot_zip_handle_checksums_and_microseconds():
    xml = (b"<Key>data/spot/monthly/klines/TRXUSDT/1d/TRXUSDT-1d-2018-07.zip</Key>"
           b"<Key>data/spot/monthly/klines/TRXUSDT/1d/TRXUSDT-1d-2018-07.zip.CHECKSUM</Key>"
           b"<Key>data/spot/monthly/klines/TRXUSDT/1d/TRXUSDT-1d-2018-06.zip</Key>")
    assert br.parse_month_keys(xml) == ["2018-06", "2018-07"]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("x.csv", "1530403200000,0.0376,0.03784,0.03601,0.03665,323005581.9,1530489599999,1,1,1,1,0\n"
                            "1735689600000000,1,2,0.5,1.5,10,1735775999999999,1,1,1,1,0\n")
    bars = br.parse_spot_zip(buf.getvalue())
    assert bars["2018-07-01"] == (0.0376, 0.03784, 0.03601, 0.03665, 323005581.9)
    assert bars["2025-01-01"][3] == 1.5, "2025 起的微秒时间戳"


def test_plan_overwrites_perp_rows_inserts_depth_and_archives_before_writing():
    spot = {d: (1.0, 1.1, 0.9, 1.0, 100.0) for d in _days("2019-06") + _days("2020-01") + _days("2026-09")}
    table = {d: _row(1.0005, 1.0004, 900.0) for d in _days("2020-01")}               # 永续:价差几个 bp、量 9 倍
    table.update({d: _row(1.0, 1.0, 100.0, h=1.1, l=0.9) for d in _days("2026-09")})  # 收集器时代:现货
    p = br.plan_symbol("TRX", table, spot)
    assert p["verdict"] == "ok" and p["n_overwrite"] == 28 and p["n_insert"] == 28, "2019-06 是补的深度"
    assert {r["source"] for r in p["archive"]} == {br.ARCHIVE} and len(p["archive"]) == 28
    assert all(r["source"] == br.SOURCE for r in p["write"])
    assert not any(r["trade_date"].startswith("2026-09") for r in p["write"]), "收集器时代只核不写"
    assert p["first_after"] == "2019-06-01" and p["first_before"] == "2020-01-01"


def test_already_spot_rows_are_left_alone():
    spot = {d: (1.0, 1.1, 0.9, 1.0, 100.0) for d in _days("2023-06") + _days("2026-09")}
    table = {d: _row(1.0, 1.0, 100.00004, h=1.1, l=0.9) for d in spot}             # float4 舍入
    p = br.plan_symbol("ADA", table, spot)
    assert p["verdict"] == "ok" and p["n_overwrite"] == 0 and p["n_insert"] == 0 and not p["archive"]


def test_refuses_a_different_asset_with_the_same_ticker_and_a_collector_era_mismatch():
    spot = {d: (1.0, 1.0, 1.0, 1.0, 1.0) for d in _days("2022-03")}
    other = {d: _row(1.6, 1.6, 1.0) for d in _days("2022-03")}
    assert br.plan_symbol("LUNA", other, spot)["verdict"] == "not_same_asset"
    spot2 = {d: (1.0, 1.0, 1.0, 1.0, 1.0) for d in _days("2026-09")}
    perp_now = {d: _row(1.0003, 1.0003, 7.0) for d in _days("2026-09")}
    assert br.plan_symbol("X", perp_now, spot2)["verdict"] == "collector_era_mismatch", "收集器之后还对不上 ⇒ 对错了对,不写"
    assert br.plan_symbol("Y", {"2020-01-01": _row(1, 1, 1)}, {"2020-01-01": (1, 1, 1, 1, 1)})["verdict"] == "too_little_overlap"


def test_rows_with_no_spot_bar_are_archived_but_not_removed():
    spot = {d: (1.0, 1.0, 1.0, 1.0, 1.0) for d in _days("2021-02")}
    table = {d: _row(1.0, 1.0, 1.0) for d in _days("2021-02")}
    table.update({d: _row(1.0, 1.0, 5.0) for d in _days("2021-01")})                # 永续早于现货上市
    p = br.plan_symbol("Z", table, spot)
    assert p["n_nonspot_extra"] == 28 and len(p["archive"]) == 28 and p["n_overwrite"] == 0
    assert not any(r["trade_date"].startswith("2021-01") for r in p["write"])


def test_done_set_is_per_version_and_errors_are_retried():
    rows = [{"detail": {"v": br.VERSION, "done": {"TRX": "ok", "AAA": "error"}}},
            {"detail": {"v": br.VERSION - 1, "done": {"ETC": "ok"}}}]
    d = br.done_from(rows)
    assert d == {"TRX": "ok", "AAA": "error"}, "旧版本做过的不算"
