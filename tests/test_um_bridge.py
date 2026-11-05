"""S-718(11-05):R-v2 读永续序列。两份迁移文件与代码说同一件事:函数只读 binance_um_hist;续写函数只插不改;循环紧跟 _perp_bv_daily。"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_r_tickets_functions_read_only_the_perp_series():
    sql = (ROOT / "migrations/2026-11-05_r_tickets_um_source.sql").read_text(encoding="utf-8")
    body = sql[sql.find("create or replace function"):]
    assert body.count("source = 'binance_um_hist'") == 3 and "source = 'binance_hist'" not in body
    assert "r_tickets_scan" in body and "r_tickets_nav(" in body
    # 函数体与 10-20 / 10-21 的版本只差源标签
    old = (ROOT / "migrations/2026-10-20_r_tickets_paper.sql").read_text(encoding="utf-8")
    old_scan = old[old.find("create or replace function public.r_tickets_scan"):old.find("revoke all on function public.r_tickets_scan")]
    new_scan = body[:body.find("create or replace function public.r_tickets_nav(")]
    norm = lambda s: re.sub(r"\s+", " ", re.sub(r"--[^\n]*", "", s)).strip()
    assert norm(old_scan.replace("'binance_hist'", "'binance_um_hist'")) == norm(new_scan)


def test_bridge_function_only_inserts_and_keeps_dollar_volume():
    sql = (ROOT / "migrations/2026-11-05_um_bridge_fill.sql").read_text(encoding="utf-8")
    assert "on conflict (symbol, trade_date, source) do nothing" in sql and "update ohlcv_daily" not in sql.lower().replace("on conflict (symbol, trade_date, source) do nothing", "")
    assert "p.qv / p.c" in sql and "'binance_um_hist'" in sql and "from perp_bv_daily p join sym s" in sql


def test_loop_runs_bridge_right_after_perp_bars():
    main = (ROOT / "src/api/main.py").read_text(encoding="utf-8")
    i, j = main.find('"_perp_bv_daily", "src.data.market.perp_bv_daily"'), main.find('supabase_rpc_write("um_bridge_fill"')
    assert 0 < i < j and '_record_loop_attempt("_um_bridge"' in main
