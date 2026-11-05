"""S-719(11-05):R-v2 读永续序列 perp_bv_daily。迁移与代码说同一件事:两个函数只读 perp_bv_daily、函数体与 10-20 / 10-21 版本只差读表;
采集器存 tbqv、从 2019-09 回补、死币也补;main 里不再有 ohlcv_daily 的桥。"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_norm = lambda s: re.sub(r"\s+", " ", re.sub(r"--[^\n]*", "", s)).strip()   # noqa: E731


def _body(path: str) -> str:
    sql = (ROOT / path).read_text(encoding="utf-8")
    return sql[sql.find("create or replace function"):]


def test_functions_read_only_perp_bv_daily_and_differ_from_the_old_version_only_in_the_source():
    body = _body("migrations/2026-11-05_r_tickets_perp_source.sql")
    assert body.count("perp_bv_daily") == 3 and "ohlcv_daily" not in body and "binance_hist" not in body
    old = (ROOT / "migrations/2026-10-20_r_tickets_paper.sql").read_text(encoding="utf-8")
    old_scan = old[old.find("create or replace function public.r_tickets_scan"):old.find("revoke all on function public.r_tickets_scan")]
    new_scan = body[:body.find("create or replace function public.r_tickets_nav(")]
    # 把旧版的读表段换成新版的读表段后,其余逐字相同
    i, j = old_scan.find("  with pre as ("), old_scan.find("  ), f as (")
    k, m = new_scan.find("  with uni as ("), new_scan.find("  ), f as (")
    assert 0 < i < j and 0 < k < m
    assert _norm(old_scan[:i] + old_scan[j:]) == _norm(new_scan[:k] + new_scan[m:])
    assert "kind = 'coin' or (kind is null and dead_from is not null)" in new_scan      # 宇宙 = 加密合约 + 分类前就死的


def test_collector_keeps_taker_flow_and_backfills_the_whole_perp_history():
    from src.data.market import perp_bv_daily as bv
    assert bv.BACKFILL_FROM == "2019-09-01"
    assert bv.bar_rows("XUSDT", [("2026-01-01", 1.0, 2.0, 0.5, 1.5, 15.0, 7.5)])[0]["tbqv"] == 7.5
    src = (ROOT / "src/data/market/perp_bv_daily.py").read_text(encoding="utf-8")
    assert "float(r[10])" in src, "klines 第 11 列 = taker_buy_quote_volume"


def test_no_bridge_into_ohlcv_daily_remains():
    main = (ROOT / "src/api/main.py").read_text(encoding="utf-8")
    assert "um_bridge_fill" not in main and "_um_bridge" not in main
    mig = (ROOT / "migrations/2026-11-05_um_bridge_fill.sql").read_text(encoding="utf-8")
    assert mig.startswith("-- ⚠️ 同日作废")
