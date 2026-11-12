#!/usr/bin/env python3
"""Binance 公开归档(data.binance.vision)的现货日线,**含已下架的交易对** —— 研究用的一次性取数(T-354,S-827)。

为什么:`ohlcv_daily`(binance_hist)只有今天还在交易的 262 个符号,2017–2020 下架的币一个都不在 ⇒ 任何「早年周期」的检验都带幸存者偏差
(S-827 因此量不了)。交易所的实时接口不提供已下架的交易对,归档里有。

只写研究目录,不进库、不碰任何生产表(与 s681/_um_daily.jsonl 同一种东西:研究缓存)。只用标准库;可断点续跑(每个符号一个文件,已有的跳过)。

用法(Mac 上,仓库根目录):
  nohup python3 scripts/research/fetch_binance_vision_spot.py > /Volumes/CometCloudAI/cometcloud-local/research/binance_vision/run.log 2>&1 &
产物(--out-dir 下):
  _sym/<SYMBOL>.json   每个符号一份(断点续跑用)
  spot_1d.jsonl        一行一个符号:{"symbol","pair","quote","last_month_in_archive","bars":[[d,o,h,l,c,quote_volume],…]}(形状同 s681/_um_daily.jsonl)
  manifest.json        判活:符号数、bar 数、逐年在交易的符号数、其中归档已停更(= 下架)的符号数、失败清单
"""
import argparse
import csv
import datetime as dt
import io
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor

S3 = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
DL = "https://data.binance.vision/"
ROOT = "data/spot/monthly/klines/"
UA = {"User-Agent": "cometcloud-research/1.0"}


def get(url, tries=4):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
                return r.read()
        except Exception as e:                      # noqa: BLE001 —— 重试后仍失败由调用方记进 manifest
            if i == tries - 1:
                raise
            time.sleep(1.5 * (i + 1))


def s3_list(prefix):
    """→ (子目录列表, 文件 key 列表);翻页到 IsTruncated = false。"""
    dirs, keys, marker = [], [], ""
    while True:
        q = {"delimiter": "/", "prefix": prefix}
        if marker:
            q["marker"] = marker
        x = get(S3 + "?" + urllib.parse.urlencode(q)).decode("utf-8", "replace")
        dirs += re.findall(r"<CommonPrefixes><Prefix>([^<]+)</Prefix>", x)
        ks = re.findall(r"<Key>([^<]+)</Key>", x)
        keys += ks
        if "<IsTruncated>true</IsTruncated>" not in x:
            return dirs, keys
        m = re.search(r"<NextMarker>([^<]+)</NextMarker>", x)
        marker = m.group(1) if m else (ks[-1] if ks else (dirs[-1] if dirs else ""))
        if not marker:
            return dirs, keys


def parse_zip(blob):
    rows = []
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        for name in z.namelist():
            for r in csv.reader(io.TextIOWrapper(z.open(name), "utf-8")):
                if not r or not r[0].strip().lstrip("-").isdigit():
                    continue                         # 表头(个别新文件有)
                t = int(r[0])
                t = t / 1e6 if t > 1e14 else t / 1e3  # 2025 起现货归档的时间戳是微秒
                d = dt.datetime.fromtimestamp(t, dt.timezone.utc).date().isoformat()
                o, h, l, c, qv = float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[7])
                if c > 0:
                    rows.append([d, o, h, l, c, qv])
    return rows


def fetch_symbol(sym, quote, m_from, m_until, out_sym):
    path = os.path.join(out_sym, sym + ".json")
    if os.path.exists(path):
        return json.load(open(path))
    _, keys = s3_list(f"{ROOT}{sym}/1d/")
    months = sorted(set(re.findall(rf"{re.escape(sym)}-1d-(\d{{4}}-\d{{2}})\.zip$", "\n".join(keys), re.M)))
    want = [m for m in months if m_from <= m <= m_until]
    rec = {"symbol": sym[: -len(quote)], "pair": sym, "quote": quote, "last_month_in_archive": months[-1] if months else None, "bars": [], "errors": []}
    for m in want:
        try:
            rec["bars"] += parse_zip(get(f"{DL}{ROOT}{sym}/1d/{sym}-1d-{m}.zip"))
        except Exception as e:                      # noqa: BLE001
            rec["errors"].append(f"{m}: {type(e).__name__}: {str(e)[:80]}")
    rec["bars"] = sorted({b[0]: b for b in rec["bars"]}.values())
    tmp = path + ".tmp"
    json.dump(rec, open(tmp, "w"))
    os.replace(tmp, path)
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default="/Volumes/CometCloudAI/cometcloud-local/research/binance_vision")
    ap.add_argument("--quotes", default="USDT,BTC")
    ap.add_argument("--from-month", default="2017-08")
    ap.add_argument("--until-month", default="2020-12")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit", type=int, default=0, help="只取前 N 个符号(试跑)")
    ap.add_argument("--only", default="", help="逗号分隔的交易对(试跑)")
    a = ap.parse_args()
    out_sym = os.path.join(a.out_dir, "_sym")
    os.makedirs(out_sym, exist_ok=True)
    quotes = [q for q in a.quotes.split(",") if q]
    if a.only:
        pairs = [p for p in a.only.split(",") if p]
    else:
        dirs, _ = s3_list(ROOT)
        pairs = sorted(d[len(ROOT):].strip("/") for d in dirs)
    todo = []
    for p in pairs:
        q = next((q for q in quotes if p.endswith(q) and len(p) > len(q)), None)
        if q:
            todo.append((p, q))
    if a.limit:
        todo = todo[: a.limit]
    print(f"{dt.datetime.now(dt.timezone.utc).isoformat()} 归档里 {len(pairs)} 个交易对,按计价币 {quotes} 取 {len(todo)} 个", flush=True)
    recs, failed = [], []

    def one(pq):
        try:
            return fetch_symbol(pq[0], pq[1], a.from_month, a.until_month, out_sym)
        except Exception as e:                      # noqa: BLE001
            return {"pair": pq[0], "fatal": f"{type(e).__name__}: {str(e)[:120]}"}
    with ThreadPoolExecutor(a.workers) as ex:
        for i, r in enumerate(ex.map(one, todo), 1):
            (failed if r.get("fatal") else recs).append(r)
            if i % 100 == 0:
                print(f"  {i}/{len(todo)}", flush=True)
    recs = [r for r in recs if r["bars"]]
    with open(os.path.join(a.out_dir, "spot_1d.jsonl"), "w") as f:
        for r in sorted(recs, key=lambda r: r["pair"]):
            f.write(json.dumps({k: r[k] for k in ("symbol", "pair", "quote", "last_month_in_archive", "bars")}) + "\n")
    this_month = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m")
    stale = lambda r: (r["last_month_in_archive"] or "") < f"{int(this_month[:4]) - 1}-{this_month[5:]}"   # 归档停更超过一年 ⇒ 下架
    by_year = {}
    for r in recs:
        for y in sorted({b[0][:4] for b in r["bars"]}):
            e = by_year.setdefault(y, {"pairs": 0, "delisted_since": 0})
            e["pairs"] += 1
            e["delisted_since"] += int(stale(r))
    man = {"written_at": dt.datetime.now(dt.timezone.utc).isoformat(), "from_month": a.from_month, "until_month": a.until_month, "quotes": quotes,
           "pairs_with_bars": len(recs), "bars": sum(len(r["bars"]) for r in recs), "delisted_pairs": sum(int(stale(r)) for r in recs),
           "by_year": by_year, "month_errors": {r["pair"]: r["errors"] for r in recs if r.get("errors")}, "fatal": failed}
    json.dump(man, open(os.path.join(a.out_dir, "manifest.json"), "w"), indent=1)
    print(json.dumps({k: man[k] for k in ("pairs_with_bars", "bars", "delisted_pairs", "by_year")}, ensure_ascii=False), flush=True)
    print(f"失败 {len(failed)} 个符号,月份级错误 {len(man['month_errors'])} 个符号", flush=True)
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
