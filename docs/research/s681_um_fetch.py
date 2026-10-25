"""S-681 数据:Binance Vision USDT 本位永续**全部**合约(含已下架)的日线与资金费月档。只读公开数据,不需要 key。

写到数据根 `research/s681/`:
    _um_daily.jsonl     每行 {"symbol": 基础币, "pair": "XXXUSDT", "bars": [[d, o, h, l, c, quote_volume], ...]}
    _um_funding.jsonl   每行 {"symbol": ..., "pair": ..., "rates": [[iso_ts, rate], ...]}
    _manifest_um.json
可分段续抓:每个(对, 月)缓存在 _cache_um_klines / _cache_um_funding,--budget 秒到点就停,再跑一次接着抓。
用法:python3 docs/research/s681_um_fetch.py --root <数据根> --kind klines|funding [--budget 140] [--workers 32]
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import os
import re
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from s677_bv_fetch import DL, _get, list_prefix  # noqa: E402  同一套 S3 列表与重试

M_FROM, M_TO = "2019-09", "2026-09"
EXCLUDE_BASE = {"BTCDOM", "DEFI", "USDC", "FDUSD", "TUSD", "BUSD", "USDP", "DAI", "FOOTBALL", "BLUEBIRD"}
DEADLINE = [float("inf")]


def keep(pair: str) -> bool:
    if not (pair.isascii() and pair.isalnum() and pair.endswith("USDT")):
        return False                      # 交割合约带「_」、USDC 本位不以 USDT 结尾
    return pair[:-4] not in EXCLUDE_BASE and len(pair) > 4


def cached(cache: str, name: str, fn):
    path = os.path.join(cache, name + ".json")
    if os.path.exists(path):
        return json.load(open(path))
    if time.time() > DEADLINE[0]:
        return None
    val = fn()
    tmp = path + ".tmp"
    json.dump(val, open(tmp, "w"))
    os.replace(tmp, path)
    return val


def months(kind: str, pair: str) -> list[str]:
    sub = "klines/{p}/1d".format(p=pair) if kind == "klines" else f"fundingRate/{pair}"
    pat = rf"{pair}-1d-(\d{{4}}-\d{{2}})\.zip</Key>" if kind == "klines" else rf"{pair}-fundingRate-(\d{{4}}-\d{{2}})\.zip</Key>"
    ms = list_prefix(f"data/futures/um/monthly/{sub}/", pat)
    return sorted({m for m in ms if M_FROM <= m <= M_TO})


def _ts(x: str) -> int:
    t = int(x)
    return t // 1000 if t > 10 ** 14 else t


def fetch(kind: str, pair: str, m: str) -> list[list]:
    if kind == "klines":
        url = f"{DL}data/futures/um/monthly/klines/{pair}/1d/{pair}-1d-{m}.zip"
    else:
        url = f"{DL}data/futures/um/monthly/fundingRate/{pair}/{pair}-fundingRate-{m}.zip"
    b = _get(url)
    if b is None:
        return []
    z = zipfile.ZipFile(io.BytesIO(b))
    rows = []
    for name in z.namelist():
        for r in csv.reader(io.TextIOWrapper(z.open(name))):
            if not r or not r[0].strip().isdigit():
                continue
            iso = dt.datetime.fromtimestamp(_ts(r[0]) / 1000, dt.timezone.utc)
            if kind == "klines":
                o, h, l, c = (float(x) for x in r[1:5])
                qv = float(r[7]) if len(r) > 7 and r[7] else float(r[5]) * c
                rows.append([iso.date().isoformat(), o, h, l, c, qv])
            else:
                rate = float(r[2]) if len(r) > 2 else float(r[1])
                rows.append([iso.isoformat(), rate])
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="/Volumes/CometCloudAI/cometcloud-local")
    ap.add_argument("--kind", choices=["klines", "funding"], default="klines")
    ap.add_argument("--workers", type=int, default=32)
    ap.add_argument("--budget", type=float, default=0)
    a = ap.parse_args()
    out = os.path.join(a.root, "research", "s681")
    cache = os.path.join(out, f"_cache_um_{a.kind}")
    os.makedirs(cache, exist_ok=True)
    if a.budget:
        DEADLINE[0] = time.time() + a.budget
    top = "klines" if a.kind == "klines" else "fundingRate"
    allp = cached(cache, "_pairs", lambda: list_prefix(f"data/futures/um/monthly/{top}/",
                                                         rf"<Prefix>data/futures/um/monthly/{top}/([^<]+)/</Prefix>"))
    if allp is None:
        print("budget hit listing pairs — run again", file=sys.stderr)
        return
    pairs = sorted(p for p in allp if keep(p))
    print(f"{a.kind}: listed {len(allp)}, kept {len(pairs)}", file=sys.stderr)
    with ThreadPoolExecutor(a.workers) as ex:
        ms = dict(zip(pairs, ex.map(lambda p: cached(cache, f"months_{p}", lambda: months(a.kind, p)), pairs)))
    if any(v is None for v in ms.values()):
        print(f"budget hit listing months ({sum(v is None for v in ms.values())} left) — run again", file=sys.stderr)
        return
    jobs = [(p, m) for p in pairs for m in ms[p]]
    with ThreadPoolExecutor(a.workers) as ex:
        got = list(ex.map(lambda pm: (pm[0], cached(cache, f"{pm[0]}_{pm[1]}", lambda: fetch(a.kind, *pm))), jobs))
    left = sum(1 for _, r in got if r is None)
    if left:
        print(f"budget hit: {left} of {len(jobs)} month files left — run again", file=sys.stderr)
        return
    by: dict[str, dict] = {}
    for p, rows in got:
        for r in rows:
            by.setdefault(p, {})[r[0]] = r
    fn = "_um_daily.jsonl" if a.kind == "klines" else "_um_funding.jsonl"
    key = "bars" if a.kind == "klines" else "rates"
    n = 0
    with open(os.path.join(out, fn), "w") as f:
        for p in sorted(by):
            rs = [by[p][k] for k in sorted(by[p])]
            n += len(rs)
            f.write(json.dumps({"symbol": p[:-4], "pair": p, key: rs}) + "\n")
    man_path = os.path.join(out, "_manifest_um.json")
    man = json.load(open(man_path)) if os.path.exists(man_path) else {}
    man[a.kind] = {"fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(), "months": [M_FROM, M_TO],
                   "pairs_listed": len(allp), "kept": len(pairs), "pairs_with_data": len(by), "rows": n,
                   "excluded_bases": sorted(EXCLUDE_BASE), "source": DL + f"data/futures/um/monthly/{top}/"}
    json.dump(man, open(man_path, "w"), indent=1)
    print(f"wrote {len(by)} pairs, {n} rows -> {fn}", file=sys.stderr)


if __name__ == "__main__":
    main()
