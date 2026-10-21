"""S-665:R-v2 的票开在「正在稀释」的币上是不是更差 —— 预注册见台账(写于把流通量与票的 R 放在一起之前)。

票 = t159_bear_short.run_long 复现的 770 张(仍持有的盯市,同 s657_s658);流通量 = asset_mcap_daily 的 市值 ÷ 价格,
按 symbol 接(同 symbol 取当日市值最大的 coin_id)。抓取:--fetch(publishable key,os.environ,不打印)。
用法:set -a; source .env; set +a; python3 docs/research/s665_dilution_rv2.py --fetch [--root …];然后不带 --fetch 再跑一次
"""
from __future__ import annotations

import bisect
import datetime as dt
import importlib.util
import json
import math
import os
import random
import sys
import urllib.request
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = sys.argv[sys.argv.index("--root") + 1] if "--root" in sys.argv else "/Volumes/CometCloudAI/cometcloud-local"
OUT = os.path.join(ROOT, "research", "s665")
_spec = importlib.util.spec_from_file_location("s657", os.path.join(HERE, "s657_s658_breadth_second_leg.py"))
s657 = importlib.util.module_from_spec(_spec)
sys.modules["s657"] = s657
_spec.loader.exec_module(s657)
t159 = s657.t159
SEED = 665


def rest(path: str, lo: int, hi: int) -> list:
    u, k = os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"]
    req = urllib.request.Request(u + "/rest/v1/" + path, headers={"apikey": k, "Authorization": "Bearer " + k,
                                                                    "Range": f"{lo}-{hi}"})
    return json.loads(urllib.request.urlopen(req, timeout=120).read())


def fetch(symbols: list[str], max_s: float = 90.0):
    """按 30 个 symbol 一块抓,每块一个文件,可断点续跑;全部块都在才合并成 _supply.json。"""
    import time
    os.makedirs(OUT, exist_ok=True)
    t0, chunks = time.time(), [symbols[k:k + 30] for k in range(0, len(symbols), 30)]
    for i, ch in enumerate(chunks):
        fn = os.path.join(OUT, f"_part{i:02d}.json")
        if os.path.exists(fn):
            continue
        if time.time() - t0 > max_s:
            break
        q = (f"asset_mcap_daily?select=symbol,coin_id,d,price,mcap&symbol=in.({','.join(ch)})&d=gte.2019-09-01"
             f"&price=not.is.null&mcap=not.is.null&order=symbol.asc,coin_id.asc,d.asc")
        got, off = [], 0
        while True:
            b = rest(q, off, off + 999)
            got += b
            if len(b) < 1000:
                break
            off += 1000
        json.dump(got, open(fn, "w"))
    parts = [os.path.join(OUT, f"_part{i:02d}.json") for i in range(len(chunks))]
    done = [p for p in parts if os.path.exists(p)]
    if len(done) == len(parts):
        allrows = [x for p in parts for x in json.load(open(p))]
        json.dump(allrows, open(os.path.join(OUT, "_supply.json"), "w"))
    print(json.dumps({"symbols": len(symbols), "chunks": len(parts), "done": len(done)}))


def supply_series() -> dict[str, list[tuple[dt.date, float]]]:
    by: dict[tuple[str, str], list] = defaultdict(list)
    for x in json.load(open(os.path.join(OUT, "_supply.json"))):
        if x["price"] and x["mcap"] and float(x["price"]) > 0:
            by[(x["symbol"].upper(), x["coin_id"])].append((dt.date.fromisoformat(x["d"][:10]), float(x["mcap"]),
                                                            float(x["mcap"]) / float(x["price"])))
    # 同 symbol 多个 coin_id:取最近一天市值最大的那个
    best: dict[str, tuple[float, list]] = {}
    for (sym, _cid), ser in by.items():
        ser.sort()
        if sym not in best or ser[-1][1] > best[sym][0]:
            best[sym] = (ser[-1][1], ser)
    return {s: [(d, sup) for d, _m, sup in v[1]] for s, v in best.items()}


def at(ser, d, tol=7):
    i = bisect.bisect_right(ser, (d, float("inf"))) - 1
    return ser[i][1] if i >= 0 and (d - ser[i][0]).days <= tol else None


def main():
    panel = t159.load_bars()
    gate = t159.load_gate()
    tickets = s657.mtm(t159.run_long(panel, gate, "2020-03-01", "2026-10-19"), panel)
    assert len(tickets) == 770, len(tickets)
    if "--fetch" in sys.argv:
        fetch(sorted({t["symbol"].upper().replace("1000", "") for t in tickets} | {t["symbol"].upper() for t in tickets}))
        return
    sup = supply_series()
    rows, nodata = [], []
    for t in tickets:
        sym = t["symbol"].upper()
        ser = sup.get(sym) or sup.get(sym.replace("1000", ""))
        d = dt.date.fromisoformat(t["signal_d"])
        a, b = (at(ser, d), at(ser, d - dt.timedelta(days=90))) if ser else (None, None)
        if not a or not b:
            nodata.append(t)
            continue
        rows.append({**t, "dil": math.log(a / b)})
    # 年内中位数切两半
    by_y = defaultdict(list)
    for r in rows:
        by_y[r["signal_d"][:4]].append(r)
    for y, rs in by_y.items():
        med = sorted(r["dil"] for r in rs)[len(rs) // 2]
        for r in rs:
            r["low"] = r["dil"] < med
    def diff(rs):
        lo = [r["r"] for r in rs if r["low"]]
        hi = [r["r"] for r in rs if not r["low"]]
        return (sum(lo) / len(lo) - sum(hi) / len(hi)) if lo and hi else None
    obs = diff(rows)
    rng = random.Random(SEED)
    null = []
    for _ in range(2000):
        sh = []
        for y, rs in by_y.items():
            labels = [r["low"] for r in rs]
            rng.shuffle(labels)
            sh += [{**r, "low": lab} for r, lab in zip(rs, labels)]
        null.append(diff(sh))
    p = sum(1 for x in null if x >= obs) / len(null)
    halves = {h: diff([r for r in rows if (r["signal_d"] < "2023-01-01") == (h == "lt2023")]) for h in ("lt2023", "ge2023")}
    tot = sum(r["r"] for r in rows)
    tot_low = sum(r["r"] for r in rows if r["low"])
    ok = obs > 0 and p < 0.05 and all(v is not None and v > 0 for v in halves.values()) and tot_low >= 0.5 * tot
    srt = sorted(rows, key=lambda r: r["dil"])
    k = len(srt) // 3
    terc = {name: seg for name, seg in (("low", srt[:k]), ("mid", srt[k:2 * k]), ("high", srt[2 * k:]))}
    top10 = sorted(rows, key=lambda r: -r["r"])[:10]
    res = {"n_with_data": len(rows), "n_nodata": len(nodata),
           "nodata_mean_r": sum(t["r"] for t in nodata) / len(nodata) if nodata else None,
           "diff_low_minus_high": obs, "p_perm_within_year": p, "halves": halves,
           "total_r": tot, "total_r_low_half": tot_low,
           "terciles": {n: {"n": len(s), "mean_r": sum(r["r"] for r in s) / len(s),
                            "win": sum(r["r"] > 0 for r in s) / len(s),
                            "dil_range": (round(s[0]["dil"], 3), round(s[-1]["dil"], 3))} for n, s in terc.items()},
           "top10": [(r["symbol"], r["signal_d"], round(r["r"], 1), round(r["dil"], 3),
                      "low" if r["dil"] <= srt[k - 1]["dil"] else "high" if r["dil"] >= srt[2 * k]["dil"] else "mid")
                     for r in top10],
           "verdict": "过" if ok else "不过"}
    json.dump(res, open(os.path.join(HERE, "s665_results.json"), "w"), indent=1, default=str)
    print(json.dumps(res, indent=1, default=str))


if __name__ == "__main__":
    main()
