"""S-593 —— 「只拿龙头」这道门在全市场上有没有用(预注册见 REFUTATION_LEDGER §S-593)。

用法:python3 docs/research/s593_gate_full_market.py <crypto_daily 目录> [输出 json]
A = 非 BTC 市值前 15 等权;B = A 里 vol13 ≤ 宇宙中位数 × 1.5 且 13 周流通量增幅 ≤ 10% 的等权(宇宙 = 非 BTC 市值前 50、v26 ≥ 15%);
C = 含 BTC 市值前 24 市值加权(S-588 的 A);D = 只持 BTC;E = 从 A 里随机去掉与 B 同样个数,1,000 条路径。每 4 周调仓,20 bp × 换手。
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any, Optional

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.data.evaluation.apparatus import ab_test, null_distribution, percentile_of  # noqa: E402
from s588_quality_tilt import build, stats  # noqa: E402

EVERY, COST, TOP, UNI, VOL_MULT, SUP_MAX = 4, 20 / 1e4, 15, 50, 1.5, 0.10
START, END = "2019-06-07", "2026-09-25"
SEGS = (("2019-06 → 2020", "2019-06-01", "2020-12-31"), ("2021", "2021-01-01", "2021-12-31"), ("2022", "2022-01-01", "2022-12-31"),
        ("2023", "2023-01-01", "2023-12-31"), ("2024", "2024-01-01", "2024-12-31"), ("2025 → 2026-09", "2025-01-01", "2026-12-31"))


def pick(t: int, syms, P, C, v13, v26, sup, bi: int) -> tuple[list[int], list[int]]:
    """当周的 A(前 15)与 B(门内)。纯函数。"""
    m = C[:, t]
    ok = np.isfinite(m) & np.isfinite(P[:, t])
    ok[bi] = False
    idx = np.where(ok)[0]
    idx = idx[np.argsort(-m[idx])]
    a = [int(i) for i in idx[:TOP]]
    uni = [int(i) for i in idx[:UNI] if np.isfinite(v26[i, t]) and v26[i, t] >= 0.15 and np.isfinite(v13[i, t])]
    if len(uni) < 10:
        return a, []
    med = float(np.median(v13[uni, t]))
    b = [i for i in a if np.isfinite(v13[i, t]) and np.isfinite(sup[i, t]) and v13[i, t] <= VOL_MULT * med and sup[i, t] <= SUP_MAX]
    return a, b


def run(data, arm: str, rng: Optional[np.random.Generator] = None):
    grid, syms, P, C, v13, v26, sup, wret = data
    bi = syms.index("BTC")
    t0 = next(i for i, g in enumerate(grid) if g >= START)
    w: dict[int, float] = {}
    out, weeks, kept = [], [], []
    since = EVERY
    for t in range(t0, len(grid)):
        if grid[t] > END:
            break
        if t > t0:
            avail = {i: wret[i, t] for i in w if np.isfinite(wret[i, t])}
            tot = sum(w[i] for i in avail)
            r = sum(w[i] * avail[i] for i in avail) / tot if tot > 0 else 0.0
            out.append(r)
            weeks.append(grid[t])
            grown = {i: w[i] * (1 + avail.get(i, 0.0)) for i in w}
            s = sum(grown.values())
            w = {i: v / s for i, v in grown.items()} if s > 0 else w
            since += 1
        if since < EVERY:
            continue
        if arm == "D":
            new = {bi: 1.0}
        elif arm == "C":
            m = C[:, t]
            ok = np.isfinite(m) & np.isfinite(P[:, t]) & (v26[:, t] >= 0.15)
            idx = np.where(ok)[0]
            idx = idx[np.argsort(-m[idx])][:24]
            new = {int(i): float(m[i] / m[idx].sum()) for i in idx}
        else:
            a, b = pick(t, syms, P, C, v13, v26, sup, bi)
            if arm == "A":
                names = a
            elif arm == "B":
                names = b or a
            else:                                   # E:同样个数随机去掉
                k = len(b) if b else len(a)
                names = [int(x) for x in rng.choice(a, size=k, replace=False)] if a else []
            kept.append(len(names))
            new = {i: 1 / len(names) for i in names} if names else w
        keys = set(new) | set(w)
        tv = sum(abs(new.get(i, 0.0) - w.get(i, 0.0)) for i in keys)
        if out:
            out[-1] = (1 + out[-1]) * (1 - tv * COST) - 1
        w = new
        since = 0
    return weeks, out, (float(np.mean(kept)) if kept else None)


def seg_stats(weeks, r, lo, hi):
    x = [v for d, v in zip(weeks, r) if lo <= d <= hi]
    if len(x) < 8:
        return None
    a = np.asarray(x)
    nav = np.cumprod(1 + a)
    return {"total": float(nav[-1] - 1), "max_dd": float((nav / np.maximum.accumulate(nav) - 1).min()), "weeks": len(x)}


def four_week(weeks, r):
    """周收益 → 4 周复利块(从第一周起不重叠)。"""
    a = np.asarray(r)
    n = len(a) // 4
    return list(np.prod(1 + a[: n * 4].reshape(n, 4), axis=1) - 1)


def main(dir_: str, out_path: Optional[str] = None) -> dict[str, Any]:
    data = build(dir_)
    res: dict[str, Any] = {"arms": {}}
    runs = {k: run(data, k) for k in "ABCD"}
    wk = runs["A"][0]
    assert all(runs[k][0] == wk for k in "BCD")
    for k, (w, r, kept) in runs.items():
        res["arms"][k] = {**stats(r), "kept_avg": kept, "segments": {nm: seg_stats(w, r, lo, hi) for nm, lo, hi in SEGS}}
    a4, b4 = four_week(wk, runs["A"][1]), four_week(wk, runs["B"][1])
    res["ab_B_vs_A"] = ab_test(a4, b4, mean_block=3, days_per_year=13)
    res["ab_B_vs_C"] = ab_test(four_week(wk, runs["C"][1]), b4, mean_block=3, days_per_year=13)
    res["ab_B_vs_D"] = ab_test(four_week(wk, runs["D"][1]), b4, mean_block=3, days_per_year=13)
    actual = float(np.log1p(np.asarray(runs["B"][1])).sum())
    null = null_distribution(lambda rng: float(np.log1p(np.asarray(run(data, "E", rng)[1])).sum()), 1000, seed=593, actual=actual)
    res["random_gate_pct"] = percentile_of(actual, null)
    res["passes"] = res["ab_B_vs_A"]["verdict"] == "B > A" and (res["random_gate_pct"] or 0) >= 0.95
    res["weeks"] = [wk[0], wk[-1], len(wk)]
    if out_path:
        Path(out_path).write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float))
    return res


if __name__ == "__main__":
    r = main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
    print("weeks", r["weeks"])
    for k, v in r["arms"].items():
        print(k, f"CAGR {v['cagr']*100:6.1f}%  total {v['total_x']:.2f}x  MDD {v['max_dd']*100:6.1f}%  kept {v['kept_avg']}")
        for nm, s in v["segments"].items():
            if s:
                print(f"    {nm:16s} {s['total']*100:8.1f}%  dd {s['max_dd']*100:6.1f}%")
    for k in ("ab_B_vs_A", "ab_B_vs_C", "ab_B_vs_D"):
        v = r[k]
        print(k, v["verdict"], round(v["ratio_b_over_a"], 3), "p", round(v["p_b_le_a"], 3))
    print("random gate pct", r["random_gate_pct"], "PASSES", r["passes"])
