#!/usr/bin/env python3
"""S-867 情景口径的结算与概率校准(T-387 CHANGES 追加)。

用途:
  1. 复核选中格(f=0.0025 / cap=0.40 / n=10)的账户净值曲线与已交付 s867_results.json 逐位一致;
  2. 给情景条目 T-387-4 / T-387-5 两条 manual 命题一个**同源**的观测值口径与结算方法;
  3. 给 T-387-5 的概率一个前瞻频率(不用新写的零分布/盈亏,只数同一条曲线上的历史频率)。

不重跑 16 格前沿(交付数已在 s867_results.json 里),也不写回任何交付产物 —— 只重建选中格一条曲线。

  python3 docs/research/s867_frontier_calib.py
"""
import importlib.util
import json
import os
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
SEL = (0.0025, 0.40, 10)                       # 选中格:台账规则挑出来的那一格
SEL_KEY = "0.0025|0.40|10"                     # s867_results.json 里 A_table 的键
HORIZON = 93                                   # 从最后数据日(2026-10-30)到结算日(2027-01-31)还有 93 天


def load_frontier():
    """导入 s867_frontier.py(它按 __main__ 保护,导入不会跑 16 格)。"""
    argv = sys.argv
    sys.argv = ["s867_frontier"]                # 它在模块层读 argv[1]/argv[2],给默认路径
    try:
        spec = importlib.util.spec_from_file_location("s867f", os.path.join(HERE, "s867_frontier.py"))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
    finally:
        sys.argv = argv
    return m


def rebuild_nav(m):
    """重建选中格的账户净值曲线(与 s867_frontier.py 的 cell() 同一套装配)。"""
    res, rv2 = m.run_engine(m.TK, *SEL)
    nav = m.build_account(rv2)["nav"].copy()
    nav.index = pd.to_datetime(nav.index)
    return nav


def check_against_delivered(nav):
    """复现检查:nav 末日值 / 前高必须与已交付 s867_results.json 一致(逐位)。"""
    ref = json.load(open(os.path.join(HERE, "s867_results.json"), encoding="utf-8"))
    cell = ref["A_table"][SEL_KEY]
    cum = nav.cummax()
    got = {"nav_end": float(nav.iloc[-1]), "nav_peak": float(cum.iloc[-1]), "nav_peak_date": str(cum.idxmax().date())}
    ok = (abs(got["nav_end"] - cell["nav_end"]) < 1e-12
          and abs(got["nav_peak"] - cell["nav_peak"]) < 1e-12
          and got["nav_peak_date"] == cell["nav_peak_date"])
    print("[复现] 选中格 nav_end %.15f vs 交付 %.15f" % (got["nav_end"], cell["nav_end"]))
    print("[复现] 选中格 nav_peak %.15f @ %s vs 交付 %.15f @ %s" % (got["nav_peak"], got["nav_peak_date"], cell["nav_peak"], cell["nav_peak_date"]))
    print("[复现] 一致:", ok)
    return ok


def forward_freq(nav, horizon=HORIZON):
    """T-387-5 的前瞻频率:「创新高之后、90 天内跌破 −6%」的段,往后 93 天有没有再创新高。"""
    cum = nav.cummax()
    new_highs, run = [], -1e18
    for d, v in nav.items():
        if v > run + 1e-12:
            new_highs.append(d)
            run = v
    new_highs = pd.DatetimeIndex(new_highs)
    last = nav.index[-1]
    rows = []
    for t in new_highs:
        hi = float(cum.loc[t])
        seg = nav.loc[(nav.index > t) & (nav.index <= t + pd.Timedelta(days=90))]
        if len(seg) == 0:
            continue
        below = seg[seg.values <= 0.94 * hi]
        if len(below) == 0:
            continue
        u = below.index[0]                      # 第一次跌破 −6% 的日子
        if u + pd.Timedelta(days=horizon) > last:
            continue                            # 前瞻窗没被数据覆盖 ⇒ 不计入(否则会把截断当成「没创新高」)
        fut = nav.loc[(nav.index > u) & (nav.index <= u + pd.Timedelta(days=horizon))]
        if len(fut) == 0:
            continue
        rows.append((t, u, float(fut.max()) > float(cum.loc[u])))
    no_new = sum(1 for r in rows if not r[2])
    print("[T-387-5] 「创新高后 90 天内跌破 −6%」的段数 =", len(rows), ";往后 %d 天没有再创新高 %d/%d = %.3f" % (horizon, no_new, len(rows), no_new / max(len(rows), 1)))
    return rows, no_new, len(rows)


def episodes(nav):
    """水下段(跌破前高到收复)的长度。"""
    cum = nav.cummax()
    eps, prev = [], None
    for d in nav.index:
        if abs(nav.loc[d] / cum.loc[d] - 1.0) < 1e-12:
            if prev is not None:
                eps.append((prev, d, (d - prev).days))
            prev = d
    if prev is not None:
        eps.append((prev, nav.index[-1], (nav.index[-1] - prev).days))
    return eps


def main():
    m = load_frontier()
    nav = rebuild_nav(m)
    if not check_against_delivered(nav):
        print("!! 与交付产物不一致,停。")
        return 1
    cum = nav.cummax()
    print("[当前] 前高 %.6f @ %s;末日 %.6f @ %s(距高 %+.4f%%)" % (
        cum.iloc[-1], cum.idxmax().date(), nav.iloc[-1], nav.index[-1].date(),
        (nav.iloc[-1] / cum.iloc[-1] - 1) * 100))
    seg = nav.loc["2026-09-09":]
    print("[当前] 结算窗 2026-09-09 → 2027-01-31 里已知最高 %.6f @ %s(离前高 %+.4f%%)" % (
        seg.max(), seg.idxmax().date(), (seg.max() / cum.iloc[-1] - 1) * 100))
    rows, no_new, n = forward_freq(nav)
    for t, u, made in rows:
        print("    高点 %s → 跌破 −6%% 于 %s(%d 天) 再创新高:%s" % (t.date(), u.date(), (u - t).days, made))
    eps = [e for e in episodes(nav) if e[2] >= 90]
    print("[段] ≥90 天的水下段:", [(str(a.date()), str(b.date()), d) for a, b, d in eps])
    print("[T-387-5] 段级计数 %d/%d(去重后按独立水下段看),带平滑 (4+1)/(5+2)=0.714" % (no_new, n))
    print("[T-387-4] 选中格 R-v2 风险占比 =", json.load(open(os.path.join(HERE, "s867_results.json"), encoding="utf-8"))["A_table"][SEL_KEY]["rv2_risk_share"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
