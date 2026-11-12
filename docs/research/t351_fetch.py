"""T-351 / S-827 探针:摸清 ohlcv_daily(source='binance_hist') 的覆盖度与体量。

用法:python3 docs/research/t351_fetch.py probe
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

U = os.environ["SUPABASE_URL"]
K = os.environ["SUPABASE_KEY"]
H = {"apikey": K, "Authorization": "Bearer " + K}


def rest(path, lo=0, hi=999, extra_headers=None):
    h = dict(H)
    if extra_headers:
        h.update(extra_headers)
    h["Range"] = f"{lo}-{hi}"
    r = urllib.request.Request(U + "/rest/v1/" + path, headers=h)
    try:
        resp = urllib.request.urlopen(r, timeout=180)
        body = resp.read()
        cr = resp.headers.get("Content-Range")
        return json.loads(body), cr
    except urllib.error.HTTPError as e:
        if e.code == 416:
            return [], None
        raise


def count_only(path):
    """用 Prefer: count=exact + Range 0-0,只取 Content-Range 里的总行数,不落数据。"""
    t0 = time.time()
    _, cr = rest(path, 0, 0, {"Prefer": "count=exact"})
    return cr, time.time() - t0


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "probe"

    if mode == "probe":
        for label, path in [
            ("all binance_hist", "ohlcv_daily?select=symbol&source=eq.binance_hist&order=symbol.asc,trade_date.asc"),
            ("2017-09..2020-07", "ohlcv_daily?select=symbol&source=eq.binance_hist"
                                "&trade_date=gte.2017-09-01&trade_date=lte.2020-07-31&order=symbol.asc,trade_date.asc"),
            ("2020-08..2026-09", "ohlcv_daily?select=symbol&source=eq.binance_hist"
                                "&trade_date=gte.2020-08-01&trade_date=lte.2026-09-30&order=symbol.asc,trade_date.asc"),
            ("all rows no date", "ohlcv_daily?select=symbol,trade_date&source=eq.binance_hist&order=symbol.asc,trade_date.asc"),
        ]:
            cr, dt = count_only(path)
            print(f"{label:24s} Content-Range={cr}  ({dt:.1f}s)", flush=True)

        # 前 3 页样本:看 symbol 命名与最早/最晚日期
        for path, tag in [
            ("ohlcv_daily?select=symbol,trade_date,open,high,low,close,volume&source=eq.binance_hist"
             "&trade_date=gte.2017-09-01&trade_date=lte.2020-07-31&order=symbol.asc,trade_date.asc", "early"),
            ("ohlcv_daily?select=symbol,trade_date,open,high,low,close,volume&source=eq.binance_hist"
             "&trade_date=lte.2017-09-01&order=symbol.asc,trade_date.asc", "pre"),
        ]:
            rows, cr = rest(path, 0, 999)
            print(f"\n== {tag} n={len(rows)} cr={cr}")
            for r in rows[:3]:
                print("  ", r)
            if rows:
                print("   ...last:", rows[-1])

    elif mode == "full":
        # 一次性把 source='binance_hist' 的全部行按 (symbol, trade_date) 落本地,后面所有跑都用这个缓存。
        out_dir = "/Volumes/CometCloudAI/cometcloud-local/research/t351/"
        os.makedirs(out_dir, exist_ok=True)
        dst = f"{out_dir}_bars_binance_hist.jsonl"
        path = ("ohlcv_daily?select=symbol,trade_date,open,high,low,close,volume&source=eq.binance_hist"
                "&order=symbol.asc,trade_date.asc")
        off, n, t0 = 0, 0, time.time()
        with open(dst, "w") as f:
            while True:
                rows, cr = rest(path, off, off + 999)
                if not rows:
                    break
                for r in rows:
                    f.write(json.dumps(r) + "\n")
                n += len(rows)
                off += 1000
                if len(rows) < 1000:
                    break
                if off % 100000 == 0:
                    print(f"  {n} rows  {time.time()-t0:.0f}s", flush=True)
        print(f"DONE rows={n} -> {dst}  ({time.time()-t0:.0f}s)", flush=True)

    elif mode == "syms":
        # 早期窗口的 symbol 名单(带每 symbol 的行数与首末日期)
        lo, hi = sys.argv[2], sys.argv[3]
        path = ("ohlcv_daily?select=symbol,trade_date&source=eq.binance_hist"
                f"&trade_date=gte.{lo}&trade_date=lte.{hi}&order=symbol.asc,trade_date.asc")
        out, off = [], 0
        while True:
            rows, cr = rest(path, off, off + 999)
            if not rows:
                break
            out += rows
            off += 1000
            if len(rows) < 1000:
                break
        by = {}
        for r in out:
            s = r["symbol"]
            d = r["trade_date"]
            if s not in by:
                by[s] = [0, d, d]
            by[s][0] += 1
            by[s][2] = d
        json.dump({s: dict(n=v[0], first=v[1], last=v[2]) for s, v in by.items()},
                  open(f"/Volumes/CometCloudAI/cometcloud-local/research/t351_syms_{lo}_{hi}.json", "w"), indent=1)
        print(f"symbols={len(by)} rows={len(out)}")


if __name__ == "__main__":
    main()
