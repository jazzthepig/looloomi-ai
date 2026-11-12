"""T-348 第三轮探针:长账本(2020-08-16 起)需要的三条腿 / 现金利率能否回溯到 2020。

只读:PostgREST,每页 ≤ 1000 行,每条查询带 order=。
用法: python3 _t348_r3_probe.py
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request

URL = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_KEY"]


def q(table: str, params: dict) -> list:
    url = f"{URL}/rest/v1/{table}?" + urllib.parse.urlencode(params, doseq=True)
    req = urllib.request.Request(url, headers={"apikey": KEY, "Authorization": f"Bearer {KEY}"})
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read().decode())


def head(table: str, params: dict, label: str, order_col: str) -> None:
    p = dict(params)
    p.update({"select": p.get("select", "d"), "order": f"{order_col}.asc", "limit": 3})
    try:
        rows = q(table, p)
        print(f"{label}: {rows}", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"{label}: ERR {e}", flush=True)


def main() -> None:
    # ① core_variants_daily 的 cap_pit24 单臂:最早一行到哪
    head("core_variants_daily", {"arm": "eq.cap_pit24"}, "core cap_pit24 最早", "d")
    # 其他臂也看一眼(也许有更早的臂能替)
    head("core_variants_daily", {}, "core 任意臂最早", "d")
    # ② 股 / 金(eodhd)
    for sym in ("ACWI", "XAUUSD"):
        head("ohlcv_daily", {"symbol": f"eq.{sym}", "source": "eq.eodhd"},
             f"{sym} eodhd 最早", "trade_date")
    # ③ 现金利率
    head("feature_matrix_daily", {}, "feature_matrix_daily 最早", "d")
    # ④ BTC/ETH 日线(若要自己拼 crypto 腿)
    for sym in ("BTC", "ETH"):
        head("ohlcv_daily", {"symbol": f"eq.{sym}"}, f"{sym} 最早(任意源)", "trade_date")


if __name__ == "__main__":
    main()
