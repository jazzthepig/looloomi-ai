#!/usr/bin/env python3
"""
T-189 敏感性测试 —— 规则「读法」层面的分歧,逐个变体重跑,看票表变不变。

起因:SQL 的 frame 写法与卡 T-189 的中文复述在两处差一根:
  (a) dd 的分母   SQL `max(c) over (rows between 365 preceding and current row)` = 含当天 366 根
                  卡的复述「前 365 根含当天」 = 365 根
  (b) mindd120    SQL `min(dd) over (rows between 120 preceding and current row)` = 含当天 121 个
                  卡的复述「120 根含当天」 = 120 个
另外 (c) 同币不叠票:SQL `t.ei > rec.xi`(进场根严格晚于出场根)vs 允许进场根 = 出场根。
这三处都是「同一句话两种读法」,正是逐张对票时最容易出分歧的地方 —— 先自己跑一遍,
把「读法一变票就变」的读法挑出来,剩下不会变票的读法就不是分歧来源。

跑法:  python3 docs/research/t189_s677_sensitivity.py
"""
import importlib
import json
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys_path = HERE
import sys

sys.path.insert(0, sys_path)
import t189_s677_replicate as R  # noqa: E402

DATA_ROOT = R.DATA_ROOT


def tickets(dd_window, mindd_window, overlap_strict, force_gate_open=False):
    R.DD_WINDOW = dd_window
    R.MINDD_WINDOW = mindd_window
    R.OVERLAP_STRICT = overlap_strict
    orig_gate = R.gate_open
    if force_gate_open:
        R.gate_open = lambda runs, d: True
    try:
        runs = R.load_gate()
        with open(R.BARS_PATH) as fh:
            rows = [json.loads(line) for line in fh]
        out = []
        for row in rows:
            out.extend(R.tickets_for_symbol(row["symbol"], row["bars"], runs))
        out.sort(key=lambda t: (t["signal_d"], t["symbol"]))
        return out
    finally:
        R.gate_open = orig_gate


def key(t):
    return (t["symbol"], t["signal_d"], t["entry_d"], t["exit_d"], int(t["still"]))


def stats(ts):
    if not ts:
        return "0 张"
    v = np.array([t["r"] for t in ts], dtype=float)
    return "%d 张, 平均 R %+.4f, 合计 R %+.4f" % (len(ts), v.mean(), v.sum())


def main():
    variants = [
        ("A SQL 原样 (dd366 / mindd121 / 严格不叠票)", 366, 121, True),
        ("B 卡的字面 (dd365 / mindd120 / 严格不叠票)", 365, 120, True),
        ("C SQL + 允许进场根=出场根", 366, 121, False),
        ("D 卡的字面 + 允许进场根=出场根", 365, 120, False),
    ]
    results = {}
    for name, ddw, mw, ov in variants:
        results[name] = tickets(ddw, mw, ov)

    base_name = variants[0][0]
    base = results[base_name]
    base_keys = [key(t) for t in base]

    for name, _, _, _ in variants:
        ts = results[name]
        ks = [key(t) for t in ts]
        only_base = [k for k in base_keys if k not in set(ks)]
        only_var = [k for k in ks if k not in set(base_keys)]
        print("== %s: %s" % (name, stats(ts)))
        if only_base or only_var:
            print("   与 A 的差异 —— A 独有 %d 张, 本变体独有 %d 张" % (len(only_base), len(only_var)))
            for k in only_base:
                print("     A 独有:", k)
            for k in only_var:
                print("     本变体独有:", k)
        else:
            print("   与 A 逐张一致")

    # 判据余量:最小 margin 排序,给对票时定位边界票用
    print()
    print("判据余量最小的 8 张(相对差 = 余量 / 判据阈值量级):")
    ms = sorted(base, key=lambda t: min(
        t["m_c_gt_hh40"] / max(t["hh40"], 1e-12),
        t["m_c_gt_sma200"] / max(t["sma200_at_signal"], 1e-12),
        t["m_dv_ge_2adv40p"] / max(2 * t["adv30"], 1e-12),
    ))
    for t in ms[:8]:
        print("   %-6s %s  c-hh40 %+.6f  c-sma200 %+.6f  dv-2adv40p %+.1f  atr %.6f" % (
            t["symbol"], t["signal_d"], t["m_c_gt_hh40"], t["m_c_gt_sma200"],
            t["m_dv_ge_2adv40p"], t["atr14"]))

    # 闸门处理的对账:把闸门强制打开(=台账 S-677「只报:不设闸门」那一行)
    nogate = tickets(366, 121, True, force_gate_open=True)
    print()
    print("闸门强制打开(=台账「只报:不设闸门」那一行):", stats(nogate))
    by_year_ng = {}
    for t in nogate:
        by_year_ng.setdefault(t["signal_d"][:4], []).append(t)
    for y in sorted(by_year_ng):
        print("   %s: %s" % (y, stats(by_year_ng[y])))
    gate_blocked = [t for t in nogate if key(t) not in set(base_keys)]
    print("   闸门挡掉的票 %d 张:" % len(gate_blocked))
    for t in gate_blocked:
        print("     %-6s %s  R %+.3f" % (t["symbol"], t["signal_d"], t["r"]))

    # 诊断:为什么 2018 一张票都没有 —— 各币 rn>=220 最早成立的日子
    print()
    print("各币 rn>=220 最早成立的日子(前 12 个):")
    with open(R.BARS_PATH) as fh:
        rows = [json.loads(line) for line in fh]
    firsts = []
    for row in rows:
        bars = row["bars"]
        if len(bars) >= 220:
            firsts.append((bars[219][0], row["symbol"], len(bars)))
    firsts.sort()
    for d, sym, nb in firsts[:12]:
        print("   %s %-8s (共 %d 根)" % (d, sym, nb))
    print("   共 %d 个币在窗口内能到 220 根" % len(firsts))
    pre = [f for f in firsts if f[0] < "2018-03-14"]
    print("   其中在闸门 2018-03-14 关闭之前就到 220 根的:%d 个 %s" % (len(pre), [f[1] for f in pre]))

    # 诊断:2018 年闸门开着、且已有 220 根的日子,各条件差在哪
    print()
    print("2018 年闸门开着且 rn>=220 的日子 —— 条件差在哪:")
    runs = R.load_gate()
    diag_rows = []
    with open(R.BARS_PATH) as fh:
        rows2 = [json.loads(line) for line in fh]
    for row in rows2:
        bars = row["bars"]
        d = [b[0] for b in bars]
        o = np.array([b[1] for b in bars], float)
        h = np.array([b[2] for b in bars], float)
        l = np.array([b[3] for b in bars], float)
        c = np.array([b[4] for b in bars], float)
        dv = np.array([b[5] for b in bars], float)
        n = len(bars)
        pc = np.concatenate(([c[0]], c[:-1]))
        tr = np.maximum.reduce([h - l, np.abs(h - pc), np.abs(l - pc)])
        sma200 = R.roll_mean(c, 200)
        atr14 = R.roll_mean(tr, 14)
        adv30 = R.roll_mean(dv, 30)
        adv40p = R.roll_prev(dv, 40)
        hh40 = R.roll_max_prev(h, 40)
        ll40 = R.roll_min_prev(l, 40)
        dd = c / R.roll_max(c, R.DD_WINDOW)
        mindd120 = R.roll_min(dd, R.MINDD_WINDOW)
        for i in range(n):
            if i + 1 < 220 or i + 1 > n - 1:
                continue
            if not (d[i].startswith("2018")):
                continue
            if not R.gate_open(runs, d[i]):
                continue
            miss = []
            if not adv30[i] >= R.ADV30_MIN:
                miss.append("adv30=%.3g" % adv30[i])
            if not mindd120[i] <= R.MINDD120_MAX:
                miss.append("mindd120=%.3f" % mindd120[i])
            if not (hh40[i] - ll40[i]) / hh40[i] <= R.RANGE40_MAX:
                miss.append("range40=%.3f" % ((hh40[i] - ll40[i]) / hh40[i]))
            if not c[i] > hh40[i]:
                miss.append("c<=hh40(c=%.6g hh40=%.6g)" % (c[i], hh40[i]))
            if not c[i] > sma200[i]:
                miss.append("c<=sma200(c=%.6g sma=%.6g)" % (c[i], sma200[i]))
            if not dv[i] >= R.DV_MULT * adv40p[i]:
                miss.append("dv<2*adv40p(dv=%.4g need=%.4g)" % (dv[i], R.DV_MULT * adv40p[i]))
            diag_rows.append((row["symbol"], d[i], miss))
    print("   这样的 (币, 日) 共 %d 个" % len(diag_rows))
    for sym, day, miss in diag_rows:
        print("   %-6s %s  差: %s" % (sym, day, "; ".join(miss) if miss else "(全部通过!)"))


if __name__ == "__main__":
    main()
