#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T-347 第一步:发现段(2012-01-01 → 2020-12-31)算 R1–R8 + 持有,选一条规则。

硬纪律:本脚本**只取 d ≤ 2020-12-31 的价格**(服务端过滤),只算发现段,
选中的规则写进 t347_discovery.json 之后,第二步才允许碰 2021 起的数据。
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import t347_lib as L  # noqa: E402

OUT = os.path.join(HERE, "t347_discovery.json")

# 逐段(空头腿分报用)
SEGMENTS = [
    ("2012-2013", "2012-01-01", "2013-12-31"),
    ("2014-2015", "2014-01-01", "2015-12-31"),
    ("2016-2017", "2016-01-01", "2017-12-31"),
    ("2018-2019", "2018-01-01", "2019-12-31"),
    ("2020", "2020-01-01", "2020-12-31"),
]


def main() -> None:
    print("[1] 取价格(d ≤ 2020-12-31,服务端过滤)…", flush=True)
    raw = L.fetch_btc_price(d_to=L.DISCOVERY_END, cache_name="price_to_2020.json")
    print(f"    行数 {len(raw)}  区间 {raw[0][0]} → {raw[-1][0]}", flush=True)

    dates_all = [d for d, _ in raw]
    closes_all = [v for _, v in raw]
    idx = [i for i, d in enumerate(dates_all) if d >= L.DISCOVERY_START]
    dates = [dates_all[i] for i in idx]
    closes = [closes_all[i] for i in idx]
    print(f"    发现段样本 {len(dates)} 天 {dates[0]} → {dates[-1]}", flush=True)

    print("[2] 取资金费(BTC)…", flush=True)
    funding = L.load_btc_funding()
    if funding:
        ks = sorted(funding)
        print(f"    资金费 {len(funding)} 天 {ks[0]} → {ks[-1]}", flush=True)
    else:
        print("    资金费读不到 ⇒ 记 0", flush=True)

    # 部件在**全序列**(含 2011 热身)上算,再切到样本窗 —— 与留出段口径一致
    ind_full = L.indicators(dates_all, closes_all)
    exps_full = L.exposures(ind_full)
    ind = {k: v[idx] for k, v in ind_full.items()}
    exps = {k: v[idx] for k, v in exps_full.items()}
    warm = int(np.sum(np.isnan(ind["M200"])))

    print("[3] 逐规则回测…", flush=True)
    res: dict = {}
    for name, e in exps.items():
        m = L.metrics(dates, closes, e, funding)
        leg = L.short_leg(dates, closes, e, funding)
        leg_segs = {}
        for sname, a, b in SEGMENTS:
            leg_segs[sname] = L.short_leg(dates, closes, e, funding, a, b)
        m.pop("_sim")
        res[name] = {"metrics": m, "leg": {k: v for k, v in leg.items() if k != "leg_series"},
                     "leg_segments": leg_segs}

    r8 = res["R8"]["metrics"]
    eligible = []
    for name in ["R1", "R2", "R3", "R4", "R5", "R6", "R7"]:
        m = res[name]["metrics"]
        if m["longest_underwater_days"] <= r8["longest_underwater_days"]:
            eligible.append((name, m["cagr"] - r8["cagr"], m["longest_underwater_days"]))

    if eligible:
        eligible.sort(key=lambda x: (-x[1], x[0]))
        selected = eligible[0][0]
        why = (f"最长水下 ≤ R8 的候选 {len(eligible)} 条:{[e[0] for e in eligible]};"
               f"取 CAGR − R8 CAGR 最大者 = {eligible[0][0]}"
               f"(ΔCAGR {eligible[0][1]:+.4f})")
    else:
        selected = None
        why = ("R1–R7 里没有一条的最长水下不长于 R8 ⇒ 到此为止:"
               "结论「在这族里做空不比空仓好」,不做留出段判定")

    # 资金费覆盖说明(2019-09 之前没有永续)
    short_days_no_fund = 0
    for name, e in exps.items():
        if name in ("HOLD", "R8"):
            continue
        for i in range(1, len(dates)):
            if e[i - 1] < 0 and dates[i] not in funding:
                short_days_no_fund += 1

    out = {
        "task": "T-347",
        "ledger": "S-823",
        "stage": "discovery",
        "window": [dates[0], dates[-1]],
        "window_spec": [L.DISCOVERY_START, L.DISCOVERY_END],
        "price_rows_fetched": len(raw),
        "price_rows_in_sample": len(dates),
        "warmup_days_M200_undefined": warm,
        "funding": {
            "file": L.FUNDING_FILE,
            "days": len(funding),
            "first": min(funding) if funding else None,
            "last": max(funding) if funding else None,
            "note": "2019-09 之前没有永续 ⇒ 记 0;本文件 BTC 实际覆盖见 first/last",
            "short_return_days_without_funding": short_days_no_fund,
        },
        "selection": {"selected": selected, "why": why,
                      "eligible": [{"rule": a, "cagr_minus_r8": b,
                                    "longest_underwater_days": c} for a, b, c in eligible]},
        "rules": res,
    }
    with open(OUT, "w") as fh:
        json.dump(out, fh, indent=1, ensure_ascii=False, default=float)
    print(f"[4] 落盘 {OUT}", flush=True)

    print("\n== 发现段 ==", flush=True)
    print(f"{'rule':5} {'CAGR':>9} {'最长水下':>9} {'最大回撤':>9} {'总收益':>10} "
          f"{'换手':>5} {'向下':>6} {'空仓':>6} {'不明确':>7} {'向上':>6}", flush=True)
    for name in ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "HOLD"]:
        m = res[name]["metrics"]
        print(f"{name:5} {m['cagr']*100:8.2f}% {m['longest_underwater_days']:9d} "
              f"{m['max_drawdown']*100:8.2f}% {m['total_return']*100:9.1f}% "
              f"{m['turnover_events']:5d} {m['down_days']:6d} {m['flat_days']:6d} "
              f"{m['unclear_days']:7d} {m['up_days']:6d}", flush=True)
    print(f"\n选中:{selected}", flush=True)
    print(why, flush=True)


if __name__ == "__main__":
    main()
