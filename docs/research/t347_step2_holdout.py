#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T-347 第二步:留出段(2021-01-01 → 2026-10-30)判一次。

硬纪律:本脚本**先读 t347_discovery.json**(发现段已经落盘、规则已经选定),
之后才允许取 2021 起的数据。留出段只判一次,不回头改选择。
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import t347_lib as L  # noqa: E402

DISCOVERY = os.path.join(HERE, "t347_discovery.json")
OUT = os.path.join(HERE, "t347_results.json")

SEGMENTS = [
    ("2021", "2021-01-01", "2021-12-31"),
    ("2022", "2022-01-01", "2022-12-31"),
    ("2023", "2023-01-01", "2023-12-31"),
    ("2024", "2024-01-01", "2024-12-31"),
    ("2025", "2025-01-01", "2025-12-31"),
    ("2026ytd", "2026-01-01", "2026-10-30"),
    ("2025-11→2026-08", "2025-11-01", "2026-08-31"),
    ("2021-05→2021-09", "2021-05-01", "2021-09-30"),
]


def leg_from_flag(dates, closes, flag, funding, e=None) -> dict:
    """按给定的「是否做空」列重算空头腿(1 倍名义,价格口径 = apparatus.short_return)。"""
    p = np.asarray(closes, dtype=float)
    rets = []
    f_tot = 0.0
    for i in range(1, len(dates)):
        if flag[i] != 1:
            continue
        sr = L.apparatus.short_return(p[i - 1], p[i])
        if sr is None:
            continue
        rets.append(float(sr))
        if e is not None:
            f_tot += (-e[i - 1]) * funding.get(dates[i], 0.0)
    if not rets:
        return {"days": 0, "total_return": None}
    arr = np.asarray(rets)
    return {"days": len(rets), "total_return": float(np.prod(1.0 + arr) - 1.0),
            "funding": float(f_tot)}


def main() -> None:
    print("[1] 读发现段结果…", flush=True)
    with open(DISCOVERY) as fh:
        disc = json.load(fh)
    selected = disc["selection"]["selected"]
    print(f"    发现段选中:{selected}", flush=True)

    print("[2] 取留出段价格(d ≥ 2021-01-01,服务端过滤)+ 发现段热身…", flush=True)
    hold = L.fetch_btc_price(d_from=L.HOLDOUT_START, cache_name="price_from_2021.json")
    warm = L.fetch_btc_price(d_to=L.DISCOVERY_END, cache_name="price_to_2020.json")
    series = sorted(dict(warm + hold).items())
    dates_all = [d for d, _ in series]
    closes_all = [v for _, v in series]
    idx = [i for i, d in enumerate(dates_all) if L.HOLDOUT_START <= d <= L.HOLDOUT_END]
    dates = [dates_all[i] for i in idx]
    closes = [closes_all[i] for i in idx]
    print(f"    留出段样本 {len(dates)} 天 {dates[0]} → {dates[-1]}", flush=True)

    funding = L.load_btc_funding()
    ind = L.indicators(dates_all, closes_all)
    exps_full = L.exposures(ind)
    # 切成留出段
    exps = {k: v[idx] for k, v in exps_full.items()}
    warm_m200 = int(np.sum(np.isnan(ind["M200"][:idx[0]])))

    print("[3] 逐规则回测(留出段)…", flush=True)
    res: dict = {}
    names = [selected, "R8", "HOLD", "R1"] if selected else ["R8", "HOLD", "R1"]
    for name in names:
        if name is None:
            continue
        e = exps[name]
        m = L.metrics(dates, closes, e, funding)
        leg = L.short_leg(dates, closes, e, funding)
        leg_segs = {}
        for sname, a, b in SEGMENTS:
            leg_segs[sname] = L.short_leg(dates, closes, e, funding, a, b)
        m.pop("_sim")
        res[name] = {"metrics": m,
                     "leg": {k: v for k, v in leg.items() if k != "leg_series"},
                     "leg_segments": leg_segs}

    r8 = res["R8"]["metrics"]
    verdict: dict = {}

    if selected:
        m = res[selected]["metrics"]
        # (i) CAGR > R8
        verdict["i_cagr_gt_r8"] = {
            "rule": selected, "cagr": m["cagr"], "r8_cagr": r8["cagr"],
            "delta": m["cagr"] - r8["cagr"], "pass": bool(m["cagr"] > r8["cagr"])}
        # (ii) 最长水下 ≤ R8
        verdict["ii_underwater_le_r8"] = {
            "rule": selected, "longest_underwater_days": m["longest_underwater_days"],
            "r8_longest_underwater_days": r8["longest_underwater_days"],
            "pass": bool(m["longest_underwater_days"] <= r8["longest_underwater_days"])}
        # (iii) 空头腿 2022 与 2025-11→2026-08 两段都为正;报 2021-05→2021-09 亏多少
        segs = res[selected]["leg_segments"]
        v2022 = segs["2022"]["total_return"]
        vlate = segs["2025-11→2026-08"]["total_return"]
        v2021 = segs["2021-05→2021-09"]["total_return"]
        verdict["iii_short_leg_segments"] = {
            "rule": selected,
            "leg_2022": v2022, "leg_2025-11_to_2026-08": vlate,
            "leg_2021-05_to_2021-09": v2021,
            "days_2022": segs["2022"]["days"],
            "days_2025-11_to_2026-08": segs["2025-11→2026-08"]["days"],
            "days_2021-05_to_2021-09": segs["2021-05→2021-09"]["days"],
            "pass": bool(v2022 is not None and late_ok(vlate) and v2022 > 0 and vlate > 0)}
        # (iv) circular_shift 零分布
        e = exps[selected]
        flag = L.short_flag(dates, e)
        actual = res[selected]["leg"]["total_return"]

        def fn(rng):
            shifted = L.apparatus.circular_shift(flag, rng, block=1)
            return leg_from_flag(dates, closes, shifted, funding)["total_return"]

        try:
            null = L.apparatus.null_distribution(fn, 500, 823, actual=actual)
            p = L.apparatus.p_upper(actual, null)
            null_info = {"n": int(len(null)), "seed": 823, "block": 1,
                         "null_mean": float(np.mean(null)),
                         "null_p05": float(np.percentile(null, 5)),
                         "null_p50": float(np.percentile(null, 50)),
                         "null_p95": float(np.percentile(null, 95)),
                         "actual": actual, "p_upper": p,
                         "null_error": None}
        except L.apparatus.NoOpNull as exc:
            p = None
            null_info = {"n": 500, "seed": 823, "block": 1, "actual": actual,
                         "p_upper": None, "null_error": str(exc)}
        verdict["iv_circular_shift"] = {**null_info, "pass": bool(p is not None and p < 0.10)}

        all_pass = all(verdict[k]["pass"] for k in
                       ["i_cagr_gt_r8", "ii_underwater_le_r8", "iii_short_leg_segments",
                        "iv_circular_shift"])
        verdict["all_pass"] = bool(all_pass)
        verdict["failed"] = [k for k in ["i_cagr_gt_r8", "ii_underwater_le_r8",
                                        "iii_short_leg_segments", "iv_circular_shift"]
                               if not verdict[k]["pass"]]
    else:
        verdict["all_pass"] = False
        verdict["note"] = "发现段没有选出规则 ⇒ 不做留出段判定"

    # 自检:R1 在 2020-07-01 之后的空头腿(1 倍折算)应与 T-252 定义 C 同号(负)
    r1 = res.get("R1")
    self_check = None
    if r1 is not None:
        # 需要 2020-07-01 起的价格 → 用全序列(含热身)算
        sc_idx = [i for i, d in enumerate(dates_all)
                  if "2020-07-01" <= d <= L.HOLDOUT_END]
        d_sc = [dates_all[i] for i in sc_idx]
        c_sc = [closes_all[i] for i in sc_idx]
        e_sc = exps_full["R1"][sc_idx]
        leg_sc = L.short_leg(d_sc, c_sc, e_sc, funding)
        self_check = {
            "rule": "R1", "window": [d_sc[0], d_sc[-1]],
            "leg_1x_total_return": leg_sc["total_return"],
            "leg_days": leg_sc["days"],
            "sign": "neg" if (leg_sc["total_return"] or 0) < 0 else "pos",
            "t252_def_C_expected": "neg",
            "consistent": bool((leg_sc["total_return"] or 0) < 0),
        }

    # 「去掉最好一段 / 最好一笔」—— 只报不判(Jazz 10-20)
    drop_best = {}
    if selected:
        e_sel = exps[selected]
        leg_h = L.short_leg(dates, closes, e_sel, funding)
        drop_best["holdout"] = L.leg_without_best(
            leg_h["leg_dates"], leg_h["leg_series"],
            {s[0]: (s[1], s[2]) for s in SEGMENTS})
        # 发现段的腿(用发现段缓存 + 全序列敞口,重算)
        d_idx = [i for i, d in enumerate(dates_all)
                 if L.DISCOVERY_START <= d <= L.DISCOVERY_END]
        d_sc = [dates_all[i] for i in d_idx]
        c_sc = [closes_all[i] for i in d_idx]
        leg_d = L.short_leg(d_sc, c_sc, exps_full[selected][d_idx], funding)
        drop_best["discovery"] = L.leg_without_best(
            leg_d["leg_dates"], leg_d["leg_series"],
            {"2012-2013": ("2012-01-01", "2013-12-31"),
             "2014-2015": ("2014-01-01", "2015-12-31"),
             "2016-2017": ("2016-01-01", "2017-12-31"),
             "2018-2019": ("2018-01-01", "2019-12-31"),
             "2020": ("2020-01-01", "2020-12-31")})

    out = {
        "task": "T-347", "ledger": "S-823", "stage": "holdout",
        "window": [dates[0], dates[-1]],
        "window_spec": [L.HOLDOUT_START, L.HOLDOUT_END],
        "price_rows_holdout_fetched": len(hold),
        "sample_days": len(dates),
        "warmup_M200_undefined_days": warm_m200,
        "selected_from_discovery": selected,
        "discovery_selection_why": disc["selection"]["why"],
        "funding": {
            "days": len(funding),
            "first": min(funding) if funding else None,
            "last": max(funding) if funding else None,
            "holdout_days_without_funding": int(sum(
                1 for d in dates if d >= "2026-10-01" and d not in funding)),
            "note": "文件 BTC 覆盖到 2026-09-30;2026-10 记 0",
        },
        "rules": res,
        "drop_best_report_only": drop_best,
        "verdict": verdict,
        "self_check_R1_vs_T252_C": self_check,
    }
    with open(OUT, "w") as fh:
        json.dump(out, fh, indent=1, ensure_ascii=False, default=float)
    print(f"[4] 落盘 {OUT}", flush=True)

    print("\n== 留出段 ==", flush=True)
    for name in [n for n in ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "HOLD"] if n in res]:
        m = res[name]["metrics"]
        print(f"{name:5} CAGR {m['cagr']*100:8.2f}%  最长水下 {m['longest_underwater_days']:5d}d  "
              f"最大回撤 {m['max_drawdown']*100:8.2f}%  总收益 {m['total_return']*100:9.1f}%  "
              f"换手 {m['turnover_events']:4d}  向下 {m['down_days']:5d}  空仓 {m['flat_days']:5d}  "
              f"不明确 {m['unclear_days']:5d}  向上 {m['up_days']:5d}", flush=True)
    print("\n== 判定 ==", flush=True)
    for k in ["i_cagr_gt_r8", "ii_underwater_le_r8", "iii_short_leg_segments",
              "iv_circular_shift"]:
        if k in verdict:
            print(f"  {k}: {'PASS' if verdict[k]['pass'] else 'FAIL'}  {verdict[k]}", flush=True)
    print(f"  全过:{verdict.get('all_pass')}", flush=True)
    if self_check:
        print(f"  自检 R1(2020-07-01 起)空头腿 1 倍: {self_check['leg_1x_total_return']:.4f} "
              f"({self_check['sign']}) 与 T-252 定义 C 一致:{self_check['consistent']}", flush=True)


def late_ok(x) -> bool:
    return x is not None and x > 0


if __name__ == "__main__":
    main()
