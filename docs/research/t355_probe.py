#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T-355 探针(第八版,终版):ohlcv_daily 用 trade_date 列 —— BTC 波动带 + LOOM 末行。"""
from __future__ import annotations
import json, os, urllib.request
import numpy as np

URL = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_KEY"]
H = {"apikey": KEY, "Authorization": "Bearer " + KEY}


def get(p):
    try:
        with urllib.request.urlopen(urllib.request.Request(URL + "/rest/v1/" + p, headers=H),
                                    timeout=60) as r:
            b = r.read().decode()
            return json.loads(b) if b else None
    except Exception as e:
        return {"err": str(e)[:160]}


for sym in ("BTC", "LOOM"):
    rows = get("ohlcv_daily?select=trade_date,close&symbol=eq.%s&order=trade_date.desc&limit=90" % sym)
    if not isinstance(rows, list) or not rows:
        print(sym, "->", json.dumps(rows, ensure_ascii=False)[:200])
        continue
    c = np.array([float(x["close"]) for x in rows if x.get("close") is not None])[::-1]
    d = [x["trade_date"] for x in rows][::-1]
    print("%s: %s -> %s last %.4f n=%d" % (sym, d[0], d[-1], c[-1], len(c)))
    if sym == "BTC" and len(c) > 31:
        rets = np.diff(c) / c[:-1]
        sd30 = float(np.std(rets[-30:]) * np.sqrt(30))
        print("   30日年化波动 %.1f%% | ±1σ %.0f..%.0f | ±1.65σ %.0f..%.0f" %
              (sd30 * 100, c[-1] * (1 - sd30), c[-1] * (1 + sd30),
               c[-1] * (1 - 1.65 * sd30), c[-1] * (1 + 1.65 * sd30)))
    if sym == "LOOM":
        print("   末几根:", [(x["trade_date"], x["close"]) for x in rows[:3]])
