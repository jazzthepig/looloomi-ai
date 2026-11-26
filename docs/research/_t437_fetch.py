"""T-437 探针(抓取):把 ohlcv_hourly(source=binance_hist)按 UTC 00/04/…/20 聚成 4 小时线,缓存到 Mac 数据根。

只读库,不写库。产物:/Volumes/CometCloudAI/cometcloud-local/research/t437/bars4h.json
    {"meta": {...}, "symbols": {SYM: [[ts_epoch, open, high, low, close], ...]}}
    ts_epoch = 4h 桶起点的 UTC epoch 秒
    桶内四根小时线不齐的桶直接丢掉。
用法: python3 docs/research/_t437_fetch.py
"""
from __future__ import annotations

import datetime as dt
import json
import os
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

URL = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_KEY"]
HDR = {"apikey": KEY, "Authorization": f"Bearer {KEY}", "Accept": "application/json"}
SYMS = ["BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "AVAX", "DOGE", "LINK", "NEAR", "SUI"]
OUT = "/Volumes/CometCloudAI/cometcloud-local/research/t437/bars4h.json"
CACHE = "/Volumes/CometCloudAI/cometcloud-local/research/t437"
LOCK = threading.Lock()


def q(path, params, tries=4):
    url = f"{URL}/rest/v1/{path}?" + urllib.parse.urlencode(params)
    last = None
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers=HDR)
            with urllib.request.urlopen(req, timeout=300) as r:
                return json.loads(r.read() or b"[]")
        except Exception as e:  # 网络抖一下重试,别把一次 DNS 抖动当成数据问题
            last = e
            time.sleep(2 * (k + 1))
    raise RuntimeError(f"{path}: {last}")


def fetch_symbol(sym: str) -> tuple[str, list, int]:
    rows, cursor, pages = [], None, 0
    while True:
        p = {"source": "eq.binance_hist", "symbol": f"eq.{sym}", "select": "ts,open,high,low,close",
             "order": "ts.asc", "limit": 1000}
        if cursor:
            p["ts"] = f"gt.{cursor}"
        page = q("ohlcv_hourly", p)
        pages += 1
        if not page:
            break
        rows.extend(page)
        cursor = page[-1]["ts"]
        if len(page) < 1000:
            break
        if pages > 200:
            raise RuntimeError(f"{sym} 分页超限")
    return sym, rows, pages


def to_4h(rows: list) -> list:
    """按 UTC 00/04/…/20 聚合;四根小时线齐了才算。"""
    buckets: dict[int, dict] = {}
    for r in rows:
        ts = dt.datetime.fromisoformat(r["ts"])
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=dt.timezone.utc)
        ts = ts.astimezone(dt.timezone.utc)
        b = ts.replace(hour=(ts.hour // 4) * 4, minute=0, second=0, microsecond=0)
        key = int(b.timestamp())
        e = buckets.get(key)
        if e is None:
            buckets[key] = {"hours": {ts.hour: r}, "open": r["open"], "high": r["high"],
                            "low": r["low"], "close": r["close"], "last_h": ts.hour}
        else:
            e["hours"][ts.hour] = r
            e["high"] = max(e["high"], r["high"])
            e["low"] = min(e["low"], r["low"])
            if ts.hour > e["last_h"]:
                e["last_h"] = ts.hour
                e["close"] = r["close"]
    out = []
    for key in sorted(buckets):
        e = buckets[key]
        if len(e["hours"]) != 4:
            continue
        out.append([key, e["open"], e["high"], e["low"], e["close"]])
    return out


def main():
    os.makedirs(CACHE, exist_ok=True)
    result = {}
    for sym in SYMS:
        cf = os.path.join(CACHE, f"bars4h_{sym}.json")
        if os.path.exists(cf):
            bars = json.load(open(cf))
            result[sym] = bars
            print(f"{sym:5s} cached bars4h={len(bars)}", flush=True)
            continue
        sym_, rows, pages = fetch_symbol(sym)
        bars = to_4h(rows)
        json.dump(bars, open(cf, "w"), separators=(",", ":"))
        result[sym] = bars
        print(f"{sym:5s} hourly={len(rows)} pages={pages} bars4h={len(bars)} "
              f"first={dt.datetime.fromtimestamp(bars[0][0], dt.timezone.utc).isoformat() if bars else None} "
              f"last={dt.datetime.fromtimestamp(bars[-1][0], dt.timezone.utc).isoformat() if bars else None}",
              flush=True)
    meta = {"built_at": dt.datetime.now(dt.timezone.utc).isoformat(), "source": "binance_hist",
            "bucket": "UTC 00/04/08/12/16/20, 四根齐", "symbols": SYMS}
    with open(OUT, "w") as f:
        json.dump({"meta": meta, "symbols": result}, f, separators=(",", ":"))
    print("WROTE", OUT, os.path.getsize(OUT), "bytes")


if __name__ == "__main__":
    main()
