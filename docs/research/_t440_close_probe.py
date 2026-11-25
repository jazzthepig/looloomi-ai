"""T-440 情景文件的前向阈值来源:读 ohlcv_daily 最近收盘(BTC/ETH/SOL)。只读,不改库。

用法:python3 docs/research/_t440_close_probe.py
本卡用到:BTC 59832 / ETH 1680.11(2026-11-24 收盘,写入 scenarios/lane-a-T-440.json)。
"""
import json
import os
import urllib.request

BASE = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1/"
KEY = os.environ["SUPABASE_KEY"]
HDR = {"apikey": KEY, "Authorization": "Bearer " + KEY}


def get(path, params):
    req = urllib.request.Request(BASE + path + "?" + params, headers=HDR)
    return json.load(urllib.request.urlopen(req))


rows = get("ohlcv_daily", "select=symbol,trade_date,close&symbol=in.(BTC,ETH,SOL)"
                   "&order=trade_date.desc,symbol.asc&limit=60")
last = {}
for r in rows:
    last.setdefault(r["symbol"], (r["trade_date"], r["close"]))
print(json.dumps(last, ensure_ascii=False, indent=1))
