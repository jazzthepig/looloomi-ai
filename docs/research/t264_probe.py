"""T-264 探针(单文件,反复改同一个文件跑;不产生最终产物)。

取情景文件要用的参照量:BTC 现货收盘、state_daily 的 taker_buy_share_30d、macro_daily 的序列。

只读。
"""
from __future__ import annotations

import json
import os
import urllib.request


def _conn():
    url = os.environ["SUPABASE_URL"].rstrip("/")
    key = os.environ["SUPABASE_KEY"]
    return url, {"apikey": key, "Authorization": "Bearer " + key}


def get(table: str, params: str):
    url, h = _conn()
    req = urllib.request.Request(f"{url}/rest/v1/{table}?{params}",
                                 headers={**h, "Prefer": "count=exact"})
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            body = json.load(resp)
            hdrs = {k.lower(): v for k, v in resp.headers.items()}
            return body, hdrs.get("content-range")
    except urllib.error.HTTPError as e:
        return {"http_error": e.code, "msg": e.read().decode()[:200]}, "ERR"


def main():
    print("=== BTC 现货收盘(binance_hist)最近 3 天 ===")
    b, cr = get("ohlcv_daily", "select=symbol,trade_date,close&symbol=eq.BTC&source=eq.binance_hist&order=trade_date.desc&limit=3")
    print(" ", cr, json.dumps(b, ensure_ascii=False))

    print("\n=== state_daily:panel 的 taker_buy_share_30d 最近 3 天 ===")
    b, cr = get("state_daily", "select=d,entity,feature,value&entity=eq.panel&feature=eq.taker_buy_share_30d&order=d.desc&limit=3")
    print(" ", cr, json.dumps(b, ensure_ascii=False)[:400])

    print("\n=== macro_daily 形状与最新值 ===")
    b, cr = get("macro_daily", "select=*&limit=2")
    print(" ", cr, json.dumps(b, ensure_ascii=False)[:400])
    if isinstance(b, list) and b:
        cols = sorted(b[0].keys())
        for col in cols:
            if col in ("d", "date", "recorded_at", "id"):
                continue
            b2, _ = get("macro_daily", f"select={col}&order=d.desc&limit=1")
            print(f"   {col}: {json.dumps(b2, ensure_ascii=False)[:120]}")


if __name__ == "__main__":
    main()
