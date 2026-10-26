#!/usr/bin/env python3
"""T-203 补充(探索性,未预注册):OI/市值比 r 与规模(市值)的可分性。

背景:lane-a 交叉复核指出,S-688 诊断 B「OI/市值 r 的截面 IC 为负」这条,预注册的偏相关只控分数、
不控市值 —— r 可能只是「小市值」的代理。本脚本用**同一份缓存**(与主脚本同源)把这件事量化:
逐日截面 Spearman ρ(r, log 市值),按自然月聚合成月序列(同一套 t 公式)。
只描述,不做零分布/显著性标定 —— 零信号对照属下一轮预注册。

用法: python3 docs/research/t203_sizeconfound.py --cache <DIR> [--out FILE]
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

MIN_NAMES = 8
CRYPTO = ["AAVE", "ADA", "APT", "ARB", "AVAX", "BNB", "DOT", "ETH", "HYPE", "INJ", "LDO", "LINK",
          "NEAR", "ONDO", "OP", "PENDLE", "POL", "SKY", "SOL", "STRK", "SUI", "TIA", "UNI", "XRP",
          "BTC"]


def rank(xs: list) -> list:
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    rk = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            rk[order[k]] = avg
        i = j + 1
    return rk


def pearson(a: list, b: list) -> float:
    n = len(a)
    ma = sum(a) / n
    mb = sum(b) / n
    sa = sum((x - ma) ** 2 for x in a) ** 0.5
    sb = sum((y - mb) ** 2 for y in b) ** 0.5
    if sa == 0 or sb == 0:
        return float("nan")
    return sum((a[i] - ma) * (b[i] - mb) for i in range(n)) / (sa * sb)


def spearman(x: list, y: list) -> float:
    return pearson(rank(x), rank(y))


def monthly(daily: dict) -> dict:
    bym = defaultdict(list)
    for d, v in daily.items():
        bym[d[:7]].append(v)
    monthly_mean = {m: sum(v) / len(v) for m, v in sorted(bym.items())}
    vals = list(monthly_mean.values())
    n = len(vals)
    mean = sum(vals) / n
    sd = (sum((v - mean) ** 2 for v in vals) / (n - 1)) ** 0.5 if n > 1 else float("nan")
    t = mean / sd * math.sqrt(n) if sd else float("nan")
    h1 = [v for m, v in monthly_mean.items() if m < "2024-07"]
    h2 = [v for m, v in monthly_mean.items() if m >= "2024-07"]
    return {"monthly": {m: round(v, 6) for m, v in monthly_mean.items()},
            "n_months": n, "mean_rho": round(mean, 6), "monthly_sd": round(sd, 6), "t": round(t, 6),
            "half1_mean_rho": round(sum(h1) / len(h1), 6) if h1 else None,
            "half1_n": len(h1),
            "half2_mean_rho": round(sum(h2) / len(h2), 6) if h2 else None,
            "half2_n": len(h2)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default="/Volumes/CometCloudAI/cometcloud-local/research/t203_run2")
    ap.add_argument("--out", default="docs/research/t203_sizeconfound.json")
    a = ap.parse_args()

    rb = json.load(open(os.path.join(a.cache, "rb_v13.json")))
    dm = json.load(open(os.path.join(a.cache, "deriv_oi.json")))

    oi_by = {}
    for r in dm:
        v = r.get("oi_value_close")
        if v is not None:
            oi_by[(r["symbol"], r["d"][:10])] = float(v)

    day_rows = defaultdict(list)
    for r in rb:
        sym = r["symbol"]
        if sym not in CRYPTO or sym == "BTC":
            continue
        d = r["d"][:10]
        inp = r.get("inputs") or {}
        mc = inp.get("mcap")
        oi = oi_by.get((sym, d))
        if mc is None or float(mc) <= 0 or oi is None or oi <= 0:
            continue
        day_rows[d].append({"symbol": sym, "r": oi / float(mc), "logmcap": math.log(float(mc)),
                            "score": r.get("score")})

    daily_r_logmcap, daily_r_score, daily_med_r = {}, {}, {}
    for d, rows in sorted(day_rows.items()):
        if len(rows) < MIN_NAMES:
            continue
        rr = [x["r"] for x in rows]
        if len(set(rr)) < 2:
            continue
        daily_r_logmcap[d] = spearman(rr, [x["logmcap"] for x in rows])
        sc = [x["score"] for x in rows if x["score"] is not None]
        if len(sc) == len(rows) and len(set(sc)) > 1:
            daily_r_score[d] = spearman(rr, sc)
        daily_med_r[d] = sorted(rr)[len(rr) // 2]

    out = {
        "task": "T-203",
        "status": "探索性 —— 需另立预注册、在新数据上过零信号对照(未预注册,只描述量测)",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "question": "S-688 诊断 B「OI/市值 r 的截面 IC 为负」这条,r 是否只是「小市值」的代理?"
                    "预注册的偏相关只控分数,不控市值。",
        "statistic": "逐日截面 Spearman ρ(r, log 市值)与 ρ(r, 分数),日 ρ 按自然月平均后按月 t"
                     "(同一套公式:t = 月均 / 月标准差(ddof=1) × √月数);上半段 2023-01→2024-06,下半段 2024-07→",
        "caveats": ["只描述,无零信号/置换对照,无显著性标定(留给下一轮预注册)",
                    "样本是全部 crypto 重建行(σ≠BTC)里 mcap 与 OI 同时有值的日子,与 IC 面板(有档位)不完全相同",
                    "r 的水平随时间漂移(中位数 2023 初 ~0.012 → 2026 末 ~0.028),故只读秩相关"],
        "data": {"rebuild_rows_used": sum(len(v) for v in day_rows.values()),
                 "days_used": len(daily_r_logmcap),
                 "date_range": [min(day_rows), max(day_rows)] if day_rows else None},
        "r_vs_log_mcap": monthly(daily_r_logmcap),
        "r_vs_score": monthly(daily_r_score),
        "median_r_by_half": {
            "half1_median_of_daily_medians": round(
                sorted(v for d, v in daily_med_r.items() if d < "2024-07-01")[len(
                    [1 for d in daily_med_r if d < "2024-07-01"]) // 2], 6),
            "half2_median_of_daily_medians": round(
                sorted(v for d, v in daily_med_r.items() if d >= "2024-07-01")[len(
                    [1 for d in daily_med_r if d >= "2024-07-01"]) // 2], 6)},
    }
    with open(a.out, "w") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    m = out["r_vs_log_mcap"]
    print("days used:", out["data"]["days_used"], "| ρ(r, log mcap) 月均 %.6f t %.6f | 上半 %s 下半 %s"
          % (m["mean_rho"], m["t"], m["half1_mean_rho"], m["half2_mean_rho"]))
    print("ρ(r, score) 月均 %s t %s" % (out["r_vs_score"]["mean_rho"], out["r_vs_score"]["t"]))
    print("median r 两半:", out["median_r_by_half"])
    print("wrote", a.out)


if __name__ == "__main__":
    main()
