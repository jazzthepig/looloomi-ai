#!/usr/bin/env python3
"""T-262 探针 4:binance_hist 覆盖(符号数 / 起止日 / 每符号天数)。改同一个文件再跑。"""
import json
import os
import sys
from collections import Counter

import requests

URL = os.environ.get("SUPABASE_URL")
KEY = os.environ.get("SUPABASE_KEY")
if not URL or not KEY:
    sys.exit("缺 SUPABASE_URL / SUPABASE_KEY")
H = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}


def pull(table, query, step=1000):
    rows, off, total = [], 0, -1
    while True:
        r = requests.get(f"{URL}/rest/v1/{table}?{query}", headers={**H, "Prefer": "count=exact"},
                         params={"limit": step, "offset": off}, timeout=300)
        if r.status_code not in (200, 206):
            raise RuntimeError(f"{table}: HTTP {r.status_code} {r.text[:300]}")
        body = r.json()
        rows.extend(body)
        cr = r.headers.get("content-range", "")
        if "/" in cr:
            total = int(cr.split("/")[-1])
        off += len(body)
        if not body or total < 0 or off >= total:
            break
    return rows


# 全表 symbol + 起止日(按 symbol 排序翻页)
rows = pull("ohlcv_daily", "source=eq.binance_hist&select=symbol,trade_date&order=symbol.asc,trade_date.asc")
print("binance_hist rows:", len(rows), flush=True)
per = {}
for r in rows:
    s = r["symbol"]
    d = r["trade_date"]
    if s not in per:
        per[s] = [d, d, 1]
    else:
        per[s][1] = d
        per[s][2] += 1
print("distinct symbols:", len(per), flush=True)
print("global min/max:", min(v[0] for v in per.values()), max(v[1] for v in per.values()), flush=True)
starts = Counter(v[0][:7] for v in per.values())
print("start month dist:", sorted(starts.items())[:12], flush=True)
ends = Counter(v[1][:7] for v in per.values())
print("end month dist:", sorted(ends.items())[-6:], flush=True)
days = Counter(v[2] for v in per.values())
print("days-per-symbol dist (top):", sorted(days.items())[-8:], flush=True)
for s in ("BTC", "ETH", "SOL", "ADA", "DOGE", "XRP", "PEPE", "WIF"):
    print("  ", s, per.get(s), flush=True)
print("symbols with < 100 days:", sum(1 for v in per.values() if v[2] < 100), flush=True)
print("symbols with >= 365 days:", sum(1 for v in per.values() if v[2] >= 365), flush=True)
json.dump({k: v for k, v in per.items()}, open("/Volumes/CometCloudAI/cometcloud-local/research/t262_bhs_coverage.json", "w"))
