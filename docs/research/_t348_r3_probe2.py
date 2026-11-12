"""T-348 第三轮探针 2:ACWI / XAUUSD / BTC 资金费的最早数据日(长账本起点 2020-08-16 需要)。"""
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


def main() -> None:
    for sym in ("ACWI", "XAUUSD"):
        try:
            print(sym, q("ohlcv_daily", {"select": "trade_date", "symbol": f"eq.{sym}",
                                          "source": "eq.eodhd", "order": "trade_date.asc", "limit": 2}))
        except Exception as e:  # noqa: BLE001
            print(sym, "ERR", e)
    try:
        print("funding BTC", q("funding_history", {"select": "funding_time", "venue": "eq.binance_perp",
                                                  "symbol": "eq.BTC", "order": "funding_time.asc", "limit": 2}))
    except Exception as e:  # noqa: BLE001
        print("funding ERR", e)
    try:
        rows = q("core_variants_daily", {"select": "d,ret", "arm": "eq.cap_pit24",
                                         "d": "gte.2020-08-01", "order": "d.asc", "limit": 3})
        print("core 2020-08", rows)
        rows = q("core_variants_daily", {"select": "d,ret", "arm": "eq.cap_pit24",
                                         "order": "d.desc", "limit": 3})
        print("core 最新", rows)
    except Exception as e:  # noqa: BLE001
        print("core ERR", e)


if __name__ == "__main__":
    main()
