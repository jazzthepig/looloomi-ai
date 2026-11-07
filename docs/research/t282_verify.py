"""T-282 核对:直接从库里取原始行,手工核 3 张票(不复用缓存、不复用 t282_short 的计算)。

用法:python3 docs/research/t282_verify.py
"""
from __future__ import annotations

import json
import os
import sys

import requests

URL = os.environ.get("SUPABASE_URL")
KEY = os.environ.get("SUPABASE_KEY")
if not URL or not KEY:
    sys.exit("缺 SUPABASE_URL / SUPABASE_KEY")
H = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}
S = requests.Session()


def rows(table: str, q: str) -> list[dict]:
    out, off = [], 0
    while True:
        r = S.get(f"{URL}/rest/v1/{table}?{q}", headers={**H, "Prefer": "count=exact"},
                  params={"limit": 1000, "offset": off}, timeout=300)
        if r.status_code not in (200, 206):
            raise RuntimeError(f"{table}: {r.status_code} {r.text[:200]}")
        b = r.json()
        out.extend(b)
        cr = r.headers.get("content-range", "")
        total = int(cr.split("/")[-1]) if "/" in cr else -1
        off += len(b)
        if not b or total < 0 or off >= total:
            break
    return out


res = json.load(open("/Users/sbb/Projects/looloomi-ai-lane-b/docs/research/t282_results.json"))
by = {(t["sym"], t["d"]): t for t in res["tickets"]}

for sym, d in (("XRP", "2020-01-06"), ("ONE", "2021-03-17"), ("FUN", "2025-03-31")):
    t = by[(sym, d)]
    print("=" * 70)
    print(f"{sym} d={d} entry={t['entry_date']} exit={t['exit_date']} kind={t['exit_kind']}")
    px = rows("perp_bv_daily",
              f"select=d,o,h,l,c&symbol=eq.{sym}&d=gte.{t['entry_date']}&d=lte.{t['exit_date']}"
              "&order=d.asc")
    for p in px:
        print("   ", p)
    fb = rows("funding_history",
              f"select=funding_time,funding_rate,venue&symbol=eq.{sym}"
              f"&venue=eq.binance_perp&funding_time=gte.{t['entry_date']}"
              f"&funding_time=lte.{t['exit_date']}&order=funding_time.asc")
    print("   funding 期数:", len(fb), "合计 %.6f" % sum(x["funding_rate"] for x in fb),
          "venues:", {x["venue"] for x in fb})
    print("   台账: entry_px=%s exit_px=%s tok=%.4f%% btc=%.4f%% fund_tok=%.4f%% "
          "fund_btc=%.4f%% cost=%.4f%% net=%.4f%%"
          % (t["entry_px"], t["exit_px"], t["tok_ret_pct"], t["btc_ret_pct"],
             t["funding_tok_pct"], t["funding_btc_pct"], t["cost_pct"], t["net_pct"]))
    print("   max_high=%.2f%% min_low=%.2f%% atr_at_exit=%s" %
          (t["max_high_pct"], t["min_low_pct"], t.get("atr_at_exit")))
