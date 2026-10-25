"""T-202 独立复核:另写实现、换随机种子,把 t202_rv2_killline_power_replica.py 的关键数重算一遍。

复核内容(全部只读,不改主脚本的任何数):
  1. 票的基本量:已平张数、平均 R、信号月数、每月票数(最小 / 最大 / 中位)、2024 每月开票数。
  2. ① 的 R1 通过率:换随机种子 20261026、2,000 次,独立写一遍「按信号月整块抽(末块截断)」。
  3. ③ 等多久:独立写一遍(中位 / 90 分位 / 顺序接)。
  4. 整块抽偏差:截断版 / 不截断版 / 逐票 iid 对照 / 总体均值。
  5. ② 的标记价口径:全样本 908 张与 2024-01…2025-12 的 435 张,各算「真实日期 / 平移·自洽标记价 /
     平移·字面标记价」三条曲线的最大回撤。
  6. 没边世界的出场价重算:exit_px' = entry_px·1.004 + (r − mean_r)·(entry_px − stop_px),检查是否全为正。

用法:python3 docs/research/t202_indep_check.py   → 打印汇总行 + 写 docs/research/t202_indep_check.json
"""
from __future__ import annotations

import bisect
import importlib.util
import json
import os
import sys
from collections import defaultdict
from datetime import date, timedelta

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, ROOT)
os.environ.setdefault("T156_DATA", "/Volumes/CometCloudAI/cometcloud-local/research/t156/")
os.environ.setdefault("T159_DATA", "/Volumes/CometCloudAI/cometcloud-local/research/t159/")
_spec = importlib.util.spec_from_file_location("t159", os.path.join(HERE, "t159_bear_short.py"))
t159 = importlib.util.module_from_spec(_spec)
sys.modules["t159"] = t159
_spec.loader.exec_module(t159)

UM_FILE = "/Volumes/CometCloudAI/cometcloud-local/research/s681/_um_daily.jsonl"
OUT_JSON = os.path.join(HERE, "t202_indep_check.json")
SEED = 20261026
DRAWS = 2000
F, CAP = 0.01, 10
BASE = date(2020, 1, 1)


def load():
    d = json.load(open(os.path.join(HERE, "t197_results.json")))
    A = [t for t in d["tickets"]["A"] if not t.get("still")]
    by_m = defaultdict(list)
    for t in A:
        by_m[t["signal_d"][:7]].append(t)
    return d, A, by_m


def load_bars():
    bars = {}
    for line in open(UM_FILE):
        x = json.loads(line)
        rows = sorted({tuple(b) for b in x["bars"] if len(b) >= 6 and b[4] > 0})
        if rows:
            bars[x["symbol"]] = rows
    return bars


def draw_r(rng, months, by_m, n):
    """按信号月整块抽到 n 张票,末块随机截断(独立实现)。"""
    out, tot = [], 0
    while tot < n:
        m = months[int(rng.integers(len(months)))]
        rs = [t["r"] for t in by_m[m]]
        take = min(len(rs), n - tot)
        if take < len(rs):
            sel = rng.permutation(len(rs))[:take]
            rs = [rs[i] for i in sorted(sel)]
        out.extend(rs)
        tot += take
    return out


def slot_start(base, k):
    return date(base.year + (base.month - 1 + k) // 12, (base.month - 1 + k) % 12 + 1, 1)


def shift_and_marks(tickets, bars, idx, dates):
    """按信号月整块平移到 2020-01-01 起的时间线;同时返回自洽标记价(每张票自己那段真实路径)。"""
    by_m = defaultdict(list)
    for t in tickets:
        by_m[t["signal_d"][:7]].append(t)
    months = sorted(by_m)
    out, pathmap, ser = [], {}, defaultdict(dict)
    for k, m in enumerate(months):
        sb = slot_start(BASE, k)
        for t in by_m[m]:
            s = date.fromisoformat(t["signal_d"])
            delta = sb - date(s.year, s.month, 1)
            nt = dict(t)
            nt["signal_d"] = (s + delta).isoformat()
            nt["entry_d"] = (date.fromisoformat(t["entry_d"]) + delta).isoformat()
            nt["exit_d"] = (date.fromisoformat(t["exit_d"]) + delta).isoformat()
            out.append(nt)
            ds = dates.get(t["symbol"], [])
            lo = bisect.bisect_left(ds, t["signal_d"])
            hi = bisect.bisect_left(ds, t["exit_d"])
            pathmap[id(nt)] = delta
            for i in range(lo, hi):
                ser[t["symbol"]][(date.fromisoformat(ds[i]) + delta).isoformat()] = idx[t["symbol"]][ds[i]]
    self_c = {s: [(k, 0, 0, 0, m[k], 0) for k in sorted(m)] for s, m in ser.items()}
    return out, self_c


def curve_stats(tickets, closes):
    d_to = (max(date.fromisoformat(t["exit_d"]) for t in tickets) + timedelta(days=5)).isoformat()
    st = t159.stats(list(t159.nav(tickets, closes, F, cap=CAP, d_to=d_to)))
    return dict(end=st["end"], mdd=st["mdd"], taken=st["taken"], skipped=st["skipped"], closed=st["closed"])


def main():
    d, A, by_m = load()
    months = sorted(by_m)
    mean_r = float(np.mean([t["r"] for t in A]))
    counts = np.array([len(by_m[m]) for m in months])
    out = dict(seed=SEED, draws=DRAWS, n_closed=len(A), mean_r=mean_r,
               t197_mean_r=d["A"]["mean_r"], n_months=len(months),
               tickets_per_month=dict(min=int(counts.min()), max=int(counts.max()),
                                      mean=float(counts.mean()), median=float(np.median(counts))),
               months_mean_r_le0=sum(1 for m in months
                                     if float(np.mean([t["r"] for t in by_m[m]])) <= 0))
    c24 = [len(by_m.get(f"2024-{m:02d}", [])) for m in range(1, 13)]
    out["counts_2024"] = c24
    out["total_2024"] = sum(c24)

    # ② R1 通过率(独立实现、换种子)
    r1 = {}
    for n in (10, 20, 30, 50, 100, 200):
        rng = np.random.default_rng([SEED, n])      # 每档独立流:加档位不影响其它档
        e, ne = [], []
        for _ in range(DRAWS):
            rs = draw_r(rng, months, by_m, n)
            e.append(float(np.mean(rs)))
            ne.append(float(np.mean(rs)) - mean_r)
        e, ne = np.array(e), np.array(ne)
        r1[str(n)] = dict(edge_p5=float(np.percentile(e, 5)), edge_p50=float(np.percentile(e, 50)),
                          edge_p95=float(np.percentile(e, 95)),
                          pass_r1_edge=float((e > 0).mean()), pass_r1_noedge=float((ne > 0).mean()))
    out["r1_pass"] = r1

    # ③ 等多久
    arr = np.array(c24)
    mn = {}
    for n in (30, 50, 100):
        rng = np.random.default_rng(SEED)
        need = []
        for _ in range(10000):
            tot, k = 0, 0
            while tot < n:
                tot += arr[int(rng.integers(12))]
                k += 1
            need.append(k)
        seq, tot, k = [], 0, 0
        while tot < n:
            seq.append(arr[k % 12])
            tot += seq[-1]
            k += 1
        mn[str(n)] = dict(median_months=float(np.median(need)), p90_months=float(np.percentile(need, 90)),
                          sequential_months=k)
    out["months_needed"] = mn

    # ④ 整块抽偏差
    allr = np.array([t["r"] for m in months for t in by_m[m]])
    bias = {}
    for n in (10, 30, 50, 100, 200):
        rng = np.random.default_rng(SEED)
        a, b = [], []
        for _ in range(2000):
            a.append(float(np.mean(draw_r(rng, months, by_m, n))))
            out_r, tot = [], 0
            while tot < n:
                m = months[int(rng.integers(len(months)))]
                out_r.extend(t["r"] for t in by_m[m])
                tot += len(by_m[m])
            b.append(float(np.mean(out_r)))
        c = allr[rng.integers(0, len(allr), size=(2000, n))].mean(axis=1)
        bias[str(n)] = dict(truncated=float(np.mean(a)), untruncated=float(np.mean(b)),
                            iid=float(np.mean(c)), population=mean_r)
    out["sampling_bias"] = bias

    # ⑤ 钱曲线三口径
    bars = load_bars()
    idx = {s: {r[0]: r[4] for r in v} for s, v in bars.items()}
    dates = {s: [r[0] for r in v] for s, v in bars.items()}
    sub = [t for t in A if "2024-01" <= t["signal_d"][:7] <= "2025-12"]
    curves = {}
    for label, sel in (("all_908", A), ("sub_2024_2025_12", sub)):
        sh, self_c = shift_and_marks(sel, bars, idx, dates)
        curves[label] = dict(n=len(sel),
                             real=curve_stats(sel, bars),
                             shift_self=curve_stats(sh, self_c),
                             shift_literal=curve_stats(sh, bars))
    out["curves"] = curves

    # ⑥ 没边世界的出场价重算
    ratios = []
    for t in A:
        den = t["entry_px"] - t["stop_px"]
        ratios.append((t["entry_px"] * 1.004 + (t["r"] - mean_r) * den) / t["entry_px"])
    out["noedge_exit_ratio"] = dict(min=float(min(ratios)), n_nonpos=int(sum(1 for r in ratios if r <= 0)))

    with open(OUT_JSON, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    print(f"[indep] 票 {out['n_closed']} 张 / 平均 R {mean_r:.6f}(t197 {d['A']['mean_r']:.6f}) / "
          f"{out['n_months']} 个月")
    print(f"[indep] 每月票数 min {out['tickets_per_month']['min']} max {out['tickets_per_month']['max']} "
          f"median {out['tickets_per_month']['median']:.0f};mean_r≤0 的月 {out['months_mean_r_le0']}")
    print(f"[indep] 2024 每月开票 {c24} 合计 {out['total_2024']}")
    for n in (10, 30, 50, 100, 200):
        x = r1[str(n)]
        print(f"[indep] R1 N={n:3d} 有边 {x['pass_r1_edge']:.3f} 没边 {x['pass_r1_noedge']:.3f} "
              f"(平均 R p5/p50/p95 {x['edge_p5']:+.3f}/{x['edge_p50']:+.3f}/{x['edge_p95']:+.3f})")
    for n in (30, 50, 100):
        x = mn[str(n)]
        print(f"[indep] ③ N={n:3d} 中位 {x['median_months']:.0f} 月 / p90 {x['p90_months']:.0f} 月 / "
              f"顺序 {x['sequential_months']}")
    for n in (10, 30, 50, 100, 200):
        x = bias[str(n)]
        print(f"[indep] 偏差 N={n:3d} 截断 {x['truncated']:+.4f} 不截断 {x['untruncated']:+.4f} "
              f"iid {x['iid']:+.4f} 总体 {x['population']:+.4f}")
    for label, c in curves.items():
        print(f"[indep] 钱曲线 {label}({c['n']} 张) 真实 {c['real']['mdd']:.4%} | "
              f"平移·自洽 {c['shift_self']['mdd']:.4%} | 平移·字面 {c['shift_literal']['mdd']:.4%}")
    print(f"[indep] 没边世界 exit_px'/entry_px 最小 {out['noedge_exit_ratio']['min']:.4f}"
          f"(≤0 的 {out['noedge_exit_ratio']['n_nonpos']} 张)")
    print(f"[indep] → {OUT_JSON}")


if __name__ == "__main__":
    main()
