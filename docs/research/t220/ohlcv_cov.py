#!/usr/bin/env python3
"""T-220 ④:预注册要用的价格侧数据(o_hlcv_daily / asset_mcap_daily)对 CIS 25 名的覆盖。"""
import json
import os
import urllib.parse
import urllib.request
from collections import defaultdict

URL = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_KEY"]
HERE = os.path.dirname(os.path.abspath(__file__))
CIS = ["AAVE", "ADA", "APT", "ARB", "AVAX", "BNB", "BTC", "DOT", "ETH", "HYPE", "INJ", "LDO",
       "LINK", "NEAR", "ONDO", "OP", "PENDLE", "POL", "SKY", "SOL", "STRK", "SUI", "TIA", "UNI", "XRP"]


def page(path, params, rng):
    url = f"{URL}/rest/v1/{path}?" + urllib.parse.urlencode(params, doseq=True)
    req = urllib.request.Request(url, headers={"apikey": KEY, "Authorization": "Bearer " + KEY,
                                              "Accept": "application/json", "Range": rng})
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read().decode() or "null")


def fetch_all(path, params, tag):
    fp = os.path.join(HERE, "_cache", tag + ".json")
    if os.path.exists(fp):
        return json.load(open(fp))
    out, off = [], 0
    while True:
        body = page(path, params, f"{off}-{off+999}")
        if not isinstance(body, list) or not body:
            break
        out.extend(body)
        if len(body) < 1000:
            break
        off += 1000
    json.dump(out, open(fp, "w"))
    return out


sym_in = "(" + ",".join(CIS) + ")"
oh = fetch_all("ohlcv_daily", {"select": "symbol,source,trade_date,close,asset_class",
                               "symbol": f"in.{sym_in}", "order": "symbol.asc,source.asc,trade_date.asc"},
               "ohlcv_cis25")
per = defaultdict(list)
for r in oh:
    per[(r.get("symbol"), r.get("source"))].append(str(r.get("trade_date"))[:10])
print("ohlcv_daily rows:", len(oh), flush=True)
srcs = sorted({r.get("source") for r in oh})
print("sources:", srcs, flush=True)
for s in CIS:
    line = []
    for (sym, src), ds in sorted(per.items()):
        if sym == s:
            line.append(f"{src}:{len(ds)}d {min(ds)}..{max(ds)}")
    print(f"{s:6s} " + " | ".join(line), flush=True)
