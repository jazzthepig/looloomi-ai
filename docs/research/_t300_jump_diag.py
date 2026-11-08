#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T-300 诊断 2:链式剔币日(比对「上一个存活日」)会剔多少、会不会把某个币的历史剔光。
只读本地缓存。同一个文件反复改。"""
import collections
import json
import os
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
rows = json.load(open(os.path.join(HERE, "t291_cache", "asset_mcap_daily.json")))
per = collections.defaultdict(list)
for r in rows:
    if r.get("price") is None:
        continue
    per[r["symbol"]].append((r["d"], float(r["price"])))
for s in per:
    per[s].sort()

LO, HI = 0.01, 100.0
drop = collections.defaultdict(list)
chain_len = collections.Counter()
for s, lst in per.items():
    last = None
    for d, p in lst:
        if last is not None and p > 0 and last > 0:
            ratio = p / last
            if ratio > HI or ratio < LO:
                drop[s].append((d, ratio))
                chain_len[s] += 1
                continue          # 剔掉,last 不动(继续比对上一个存活日)
        last = p

tot_rows = sum(len(v) for v in per.values())
tot_drop = sum(len(v) for v in drop.values())
print(f"总行数 {tot_rows};链式剔掉 {tot_drop} 币日;涉及 {len(drop)} 个代号")

print("\n每个代号:原行数 / 剔掉 / 占比 / 剔掉日期(前 6)")
for s in sorted(drop, key=lambda x: -len(drop[x])):
    n = len(per[s])
    print(f"   {s:<16} {n:>5} / {len(drop[s]):>4} = {len(drop[s]) / n:6.1%}  "
          + " ".join(d for d, _ in drop[s][:6]))

# 「永久换算」的迹象:剔完之后,剩下的价格量级是否一致
print("\n== 剔完后是否还有量级断层(相邻存活日比值仍 > 10 或 < 0.1)===")
bad = 0
examples = []
for s, lst in per.items():
    ds = set(d for d, _ in drop[s])
    kept = [(d, p) for d, p in lst if d not in ds]
    for i in range(1, len(kept)):
        p0, p1 = kept[i - 1][1], kept[i][1]
        if p0 <= 0 or p1 <= 0:
            continue
        r = p1 / p0
        if r > 10 or r < 0.1:
            bad += 1
            if len(examples) < 12:
                examples.append((s, kept[i][0], r))
print("剩余断层条数 =", bad)
for e in examples:
    print("   ", e)
