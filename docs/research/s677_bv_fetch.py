"""S-677 数据:Binance Vision 公开月档里全部 USDT 现货对(含已下架)的日线,2017-08 → 2020-08。

只读公开数据(data.binance.vision,无 key)。写到数据根 `research/s677/`:
    _bv_daily.jsonl   每行一个币 {"symbol": 基础币, "pair": "XXXUSDT", "bars": [[d, o, h, l, c, dv], ...]}
                      dv = close × volume(与 binance_hist 同口径,只算 USDT 对)
    _manifest.json    抓取时刻、对数、月份范围、排除表、每个对的月数
排除:稳定币 / 法币基、杠杆代币(UP / DOWN / BULL / BEAR 结尾)、BTCDOM / DEFI —— 与台账 S-677 同一张表。
用法:python3 docs/research/s677_bv_fetch.py [--root /Volumes/CometCloudAI/cometcloud-local] [--workers 16]
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
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor

S3 = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
DL = "https://data.binance.vision/"
M_FROM, M_TO = "2017-08", "2020-08"
STABLE_FIAT = {"USDC", "TUSD", "PAX", "USDP", "BUSD", "USDS", "USDSB", "DAI", "FDUSD", "USDJ", "SUSD", "UST", "EUR",
               "GBP", "AUD", "TRY", "RUB", "BIDR", "IDRT", "BKRW", "NGN", "UAH", "ZAR", "BRL", "BVND"}
LEVERAGED = re.compile(r"(.*)(UP|DOWN|BULL|BEAR)$")   # 杠杆代币:BULL / BEAR 本身,或「另一个 USDT 对的基础币 + 后缀」(JUP / SYRUP 不算)
EXCL_EXTRA = {"BTCDOM", "DEFI"}


def _get(url: str, tries: int = 4) -> bytes | None:
    for k in range(tries):
        try:
            return urllib.request.urlopen(url, timeout=60).read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(1.5 * (k + 1))
        except (urllib.error.URLError, TimeoutError, OSError):
            time.sleep(1.5 * (k + 1))
    raise RuntimeError(f"failed: {url}")


def list_prefix(prefix: str, pat: str) -> list[str]:
    """S3 列表(带 marker 翻页),返回匹配 pat 的捕获组。"""
    out, marker = [], ""
    while True:
        u = f"{S3}?delimiter=/&prefix={prefix}" + (f"&marker={marker}" if marker else "")
        x = _get(u).decode()
        got = re.findall(pat, x)
        keys = re.findall(r"<Key>([^<]+)</Key>", x) + re.findall(r"<Prefix>([^<]+)</Prefix>", x)
        out += got
        if "<IsTruncated>true</IsTruncated>" in x and keys:
            marker = keys[-1]
        else:
            return out


QUOTE = "USDT"                     # S-678 起也抓 BTC 计价对(--quote BTC)


def base_of(pair: str) -> str:
    return pair[:-len(QUOTE)]


def is_leveraged(base: str, pairs: set[str]) -> bool:
    m = LEVERAGED.match(base)
    return bool(m) and (m.group(1) == "" or m.group(1) + QUOTE in pairs or m.group(1) + "USDT" in pairs)


def keep(pair: str, pairs: set[str]) -> bool:
    b = base_of(pair)
    if not (pair.isascii() and pair.isalnum()):          # 2025 起有中文名的对;2017–2020 没有
        return False
    return bool(b) and b not in STABLE_FIAT and b not in EXCL_EXTRA and not is_leveraged(b, pairs)


CACHE = ""                          # 数据根 research/s677/_cache_<quote>/ —— 每个(对, 月)一份,断了可以续
DEADLINE = [float("inf")]


def _cached(name: str, fn):
    path = os.path.join(CACHE, name + ".json")
    if os.path.exists(path):
        return json.load(open(path))
    if time.time() > DEADLINE[0]:
        return None
    val = fn()
    tmp = path + ".tmp"
    json.dump(val, open(tmp, "w"))
    os.replace(tmp, path)
    return val


def months_of(pair: str) -> list[str]:
    ms = list_prefix(f"data/spot/monthly/klines/{pair}/1d/", rf"{pair}-1d-(\d{{4}}-\d{{2}})\.zip</Key>")
    lo = "2017-07" if QUOTE == "BTC" else M_FROM
    return sorted({m for m in ms if lo <= m <= M_TO})


def fetch_month(pair: str, m: str) -> list[list]:
    b = _get(f"{DL}data/spot/monthly/klines/{pair}/1d/{pair}-1d-{m}.zip")
    if b is None:
        return []
    z = zipfile.ZipFile(io.BytesIO(b))
    rows = []
    for name in z.namelist():
        for r in csv.reader(io.TextIOWrapper(z.open(name))):
            if not r or not r[0].isdigit():
                continue
            t = int(r[0])
            t = t // 1000 if t > 10 ** 14 else t          # 2025 起有微秒档;这段应该都是毫秒
            d = dt.datetime.fromtimestamp(t / 1000, dt.timezone.utc).date().isoformat()
            o, h, l, c, v = (float(x) for x in r[1:6])
            # USDT 对存 dv = 收盘 × 成交量(与 binance_hist 同口径);BTC 对存原始成交量(基础币数量),折美元在 S-678 里做
            rows.append([d, o, h, l, c, c * v] if QUOTE == "USDT" else [d, o, h, l, c, v])
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="/Volumes/CometCloudAI/cometcloud-local")
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--quote", choices=["USDT", "BTC"], default="USDT")
    ap.add_argument("--budget", type=float, default=0, help="秒;到点就停,已抓的留在缓存里,再跑一次接着抓")
    a = ap.parse_args()
    global QUOTE
    QUOTE = a.quote
    out_dir = os.path.join(a.root, "research", "s677")
    os.makedirs(out_dir, exist_ok=True)
    every = list_prefix("data/spot/monthly/klines/", r"<Prefix>data/spot/monthly/klines/([^<]+)/</Prefix>")
    pairs = [p for p in every if p.endswith(QUOTE)]
    kept = sorted(p for p in pairs if keep(p, set(every)))
    print(f"{QUOTE} pairs {len(pairs)}, kept {len(kept)}", file=sys.stderr)
    global CACHE
    CACHE = os.path.join(out_dir, f"_cache_{QUOTE.lower()}")
    os.makedirs(CACHE, exist_ok=True)
    if a.budget:
        DEADLINE[0] = time.time() + a.budget
    with ThreadPoolExecutor(a.workers) as ex:
        months = dict(zip(kept, ex.map(lambda p: _cached(f"months_{p}", lambda: months_of(p)), kept)))
    if any(v is None for v in months.values()):
        print(f"budget hit while listing months ({sum(v is None for v in months.values())} left) — run again", file=sys.stderr)
        return
    jobs = [(p, m) for p in kept for m in months[p]]
    print(f"pairs with months in range: {sum(1 for p in kept if months[p])}; month files {len(jobs)}", file=sys.stderr)
    with ThreadPoolExecutor(a.workers) as ex:
        got = list(ex.map(lambda pm: (pm[0], _cached(f"{pm[0]}_{pm[1]}", lambda: fetch_month(*pm))), jobs))
    left = sum(1 for _, rows in got if rows is None)
    if left:
        print(f"budget hit: {left} of {len(jobs)} month files left — run again", file=sys.stderr)
        return
    bars: dict[str, dict[str, list]] = {}
    for p, rows in got:
        for r in rows:
            bars.setdefault(p, {})[r[0]] = r
    n_bars = 0
    suffix = "" if QUOTE == "USDT" else "_" + QUOTE.lower()
    with open(os.path.join(out_dir, f"_bv_daily{suffix}.jsonl"), "w") as f:
        for p in sorted(bars):
            rs = [bars[p][d] for d in sorted(bars[p])]
            n_bars += len(rs)
            f.write(json.dumps({"symbol": base_of(p), "pair": p, "bars": rs}) + "\n")
    json.dump({"fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(), "source": DL + "data/spot/monthly/klines/",
               "quote": QUOTE, "months": ["2017-07" if QUOTE == "BTC" else M_FROM, M_TO], "pairs_listed": len(pairs), "kept": len(kept),
               "pairs_with_data": len(bars), "bars": n_bars, "excluded_stable_fiat": sorted(STABLE_FIAT),
               "excluded_other": sorted(EXCL_EXTRA), "leveraged_rule": LEVERAGED.pattern,
               "months_per_pair": {p: len(months[p]) for p in kept if months[p]}},
              open(os.path.join(out_dir, f"_manifest{suffix}.json"), "w"), indent=1)
    print(f"wrote {len(bars)} pairs, {n_bars} bars -> {out_dir}", file=sys.stderr)


if __name__ == "__main__":
    main()
