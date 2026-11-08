#!/usr/bin/env python3
"""T-304 / S-787 拉数:kimchi_premium_daily、ohlcv_daily(binance_hist) BTC + 24 名面板。
纪律:每页 ≤1000 行、每页带 order=、抓完核总数(Prefer: count=exact)、并行 8 线程。
"""
import json
import os
import threading
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path

URL = os.environ["SUPABASE_URL"]
KEY = os.environ["SUPABASE_KEY"]
OUT = Path("/Volumes/CometCloudAI/cometcloud-local/research/_cache/t304")
OUT.mkdir(parents=True, exist_ok=True)

# ① 面板 = 项目标准「① 面板 24 名」(docs/research/s694_avoid_tilt.sql 第 34 行;台账 L24085)
PANEL24 = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK", "DOT",
           "LTC", "TRX", "ATOM", "NEAR", "APT", "ARB", "OP", "SUI", "UNI", "AAVE",
           "INJ", "FIL", "ETC", "BCH"]


def fetch(path, params, count=False):
    q = dict(params)
    u = f"{URL}/rest/v1/{path}?" + urllib.parse.urlencode(q)
    hdr = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}
    if count:
        hdr["Prefer"] = "count=exact"
    req = urllib.request.Request(u, headers=hdr)
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode()), r.headers.get("Content-Range")


def total_of(cr):
    return int(cr.split("/")[-1]) if cr and "/" in cr else None


def pull_symbol(sym):
    """取一个 symbol 在 ohlcv_daily(source=binance_hist)的全部 (trade_date, close)。"""
    rows, cr = fetch("ohlcv_daily", {"select": "trade_date,close", "symbol": f"eq.{sym}",
                                    "source": "eq.binance_hist", "order": "trade_date.asc", "limit": 1}, count=True)
    total = total_of(cr)
    out, off = [], 0
    while True:
        r, cr2 = fetch("ohlcv_daily", {"select": "trade_date,close", "symbol": f"eq.{sym}",
                                       "source": "eq.binance_hist", "order": "trade_date.asc",
                                       "limit": 1000, "offset": off})
        if not r:
            break
        out.extend(r)
        off += len(r)
        if off >= total or len(r) < 1000:
            break
    return sym, out, total, off


def pull_simple(path, order_col, sel, extra=None, tag=""):
    rows, cr = fetch(path, dict({"select": sel, "order": f"{order_col}.asc", "limit": 1},
                                **(extra or {})), count=True)
    total = total_of(cr)
    out, off = [], 0
    while True:
        r, _ = fetch(path, dict({"select": sel, "order": f"{order_col}.asc", "limit": 1000, "offset": off},
                                 **(extra or {})))
        if not r:
            break
        out.extend(r)
        off += len(r)
        if off >= total or len(r) < 1000:
            break
    (OUT / f"{tag}.json").write_text(json.dumps(out))
    return tag, len(out), total


summary = {}
lock = threading.Lock()

# 1) kimchi
try:
    t, n, total = pull_simple("kimchi_premium_daily", "d", "d,prem,usdkrw,btc_krw,btc_usdt,fx_d", tag="kimchi")
    summary["kimchi"] = {"rows": n, "total": total}
except Exception as e:
    summary["kimchi"] = {"err": repr(e)}

# 2) 面板 24 名 + BTC 并行
results = {}


def work(sym):
    try:
        s, out, total, off = pull_symbol(sym)
        (OUT / f"px_{sym}.json").write_text(json.dumps(out))
        with lock:
            results[s] = {"rows": len(out), "total": total, "first": out[0]["trade_date"] if out else None,
                          "last": out[-1]["trade_date"] if out else None}
    except Exception as e:
        with lock:
            results[s] = {"err": repr(e)}


syms = sorted(set(PANEL24) | {"BTC"})
threads = []
for s in syms:
    t = threading.Thread(target=work, args=(s,))
    t.start()
    threads.append(t)
for t in threads:
    t.join()
summary["panel"] = results

(OUT / "pull_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1))
print(json.dumps(summary, ensure_ascii=False, indent=1)[:5000])
