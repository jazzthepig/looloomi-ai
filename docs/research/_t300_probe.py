#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T-300 探针:写情景文件要用的两个自动结算量的当前读数。同一个文件反复改。"""
import json
import os
import urllib.request

URL = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1/"
KEY = os.environ["SUPABASE_KEY"]
H = {"apikey": KEY, "Authorization": "Bearer " + KEY}


def get(p):
    r = urllib.request.Request(URL + p, headers=H)
    with urllib.request.urlopen(r, timeout=120) as f:
        return json.loads(f.read().decode())


rows = get("ohlcv_daily?select=symbol,trade_date,close&source=eq.binance_hist&symbol=eq.BTC"
           "&order=trade_date.desc&limit=3")
print("BTC 最近 3 个收盘:", [(r["trade_date"], r["close"]) for r in rows])
rows = get("state_daily?select=d,feature,value&entity=eq.panel&feature=eq.breadth_above_ma50"
           "&order=d.desc&limit=3")
print("breadth_above_ma50 最近 3 日:", [(r["d"], r["value"]) for r in rows])
