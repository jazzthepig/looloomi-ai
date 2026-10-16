"""S-586 挖掘(时间序列,只看发现段)—— 什么在事前告诉我们「下一段该多拿加密还是多拿 World50」:灵活配置引擎的候选信号。

用法:python3 docs/research/s586_mine_alloc.py <w50_daily 目录> [输出 json] [--holdout]
两条腿同 S-585:加密腿 C = 五个大币市值加权(① 的近似),World50 腿 W = 双周等权。
目标:之后 h ∈ {4, 13} 周的 C 收益、W 收益、C − W。预测量(第 t 周收盘可知):
  c_r4 c_r13 c_r26、w_r4 w_r13 w_r26、c_vol13、w_vol13、btc_dom_chg13(BTC 在五大币里的市值占比 13 周变化)、
  c_dd52 / w_dd52(距 52 周高点)、gold_r13、agg_r13(美债)、qqq_minus_acwi_r13(科技领先)。
统计:Spearman(预测量_t, 之后 h 周收益),重叠窗口 ⇒ 用 apparatus 的平稳块自助(块长 = h)给 t。
发现段 2017-01 → 2021-12(加密腿要 40 周起步,样本只有约 5 年 —— 时间序列挖掘的检验力天生很低,结果只作候选)。
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

from s584_world50_weekly_mom import load, run_arm  # noqa: E402
from s585_flex_allocation import crypto_leg, index_from  # noqa: E402
from s586_mine_world50 import boot_t, spearman  # noqa: E402

DISCOVERY = ("2017-01-01", "2021-12-31")
HOLDOUT = ("2022-01-01", "2026-09-25")


def trailing(idx: list[Optional[float]], i: int, k: int) -> Optional[float]:
    if i - k < 0 or idx[i] is None or idx[i - k] is None:
        return None
    return idx[i] / idx[i - k] - 1


def vol(rets: list[Optional[float]], i: int, k: int) -> Optional[float]:
    w = [r for r in rets[max(1, i - k + 1): i + 1] if r is not None]
    return float(np.std(w, ddof=1) * math.sqrt(52)) if len(w) >= k * 0.7 else None


def dd52(idx: list[Optional[float]], i: int) -> Optional[float]:
    w = [x for x in idx[max(0, i - 51): i + 1] if x is not None]
    return idx[i] / max(w) - 1 if idx[i] and w else None


def main(dir_: str, out_path: Optional[str] = None, holdout: bool = False) -> dict[str, Any]:
    window = HOLDOUT if holdout else DISCOVERY
    grid, wc, wr, snaps, cls = load(dir_)
    wl = run_arm("EW", 2, grid, wc, wr, snaps, cls)
    pos = {g: i for i, g in enumerate(grid)}
    rw: list[Optional[float]] = [None] * len(grid)
    for g, r in zip(wl["weeks"], wl["ret"]):
        rw[pos[g]] = r
    rc = crypto_leg(grid, wc, wr, snaps)
    ic_, iw_ = index_from(rc), index_from(rw)
    bench = {k: wc.get(k) for k in ("XAUUSD", "AGG", "QQQ", "ACWI")}
    dom = []
    for g in grid:
        s = snaps.get(g, {})
        tot = sum(s.get(k, 0) for k in ("BTC", "ETH", "XRP", "BNB", "SOL"))
        dom.append(s["BTC"] / tot if tot and "BTC" in s else None)
    preds: dict[str, list[Optional[float]]] = {n: [] for n in (
        "c_r4", "c_r13", "c_r26", "w_r4", "w_r13", "w_r26", "c_vol13", "w_vol13", "btc_dom_chg13",
        "c_dd52", "w_dd52", "gold_r13", "agg_r13", "qqq_minus_acwi_r13")}
    for i in range(len(grid)):
        preds["c_r4"].append(trailing(ic_, i, 4))
        preds["c_r13"].append(trailing(ic_, i, 13))
        preds["c_r26"].append(trailing(ic_, i, 26))
        preds["w_r4"].append(trailing(iw_, i, 4))
        preds["w_r13"].append(trailing(iw_, i, 13))
        preds["w_r26"].append(trailing(iw_, i, 26))
        preds["c_vol13"].append(vol(rc, i, 13))
        preds["w_vol13"].append(vol(rw, i, 13))
        preds["btc_dom_chg13"].append(dom[i] - dom[i - 13] if i >= 13 and dom[i] is not None and dom[i - 13] is not None else None)
        preds["c_dd52"].append(dd52(ic_, i))
        preds["w_dd52"].append(dd52(iw_, i))
        g13 = trailing(bench["XAUUSD"], i, 13) if bench["XAUUSD"] else None
        preds["gold_r13"].append(g13)
        preds["agg_r13"].append(trailing(bench["AGG"], i, 13) if bench["AGG"] else None)
        q, a = (trailing(bench["QQQ"], i, 13) if bench["QQQ"] else None), (trailing(bench["ACWI"], i, 13) if bench["ACWI"] else None)
        preds["qqq_minus_acwi_r13"].append(q - a if q is not None and a is not None else None)
    res: dict[str, Any] = {"window": window, "rows": {}}
    for h in (4, 13):
        fut = {"C": [trailing(ic_, i + h, h) if i + h < len(grid) else None for i in range(len(grid))],
               "W": [trailing(iw_, i + h, h) if i + h < len(grid) else None for i in range(len(grid))]}
        fut["C-W"] = [a - b if a is not None and b is not None else None for a, b in zip(fut["C"], fut["W"])]
        sel = [i for i, g in enumerate(grid) if window[0] <= g <= window[1]
               and (holdout or (i + h < len(grid) and grid[i + h] <= window[1]))]
        for pname, pv in preds.items():
            for tname, tv in fut.items():
                xs = [(pv[i], tv[i]) for i in sel if pv[i] is not None and tv[i] is not None]
                if len(xs) < 3 * h:
                    continue
                x = np.array([a for a, _ in xs])
                y = np.array([b for _, b in xs])
                rho = spearman(x, y)
                # 块自助的 t:把 (x, y) 成对按块重抽,看 rho 的分布
                from src.data.evaluation.apparatus import stationary_bootstrap_index
                idx = stationary_bootstrap_index(len(xs), float(h), 1000, np.random.default_rng(586))
                boots = [spearman(x[j], y[j]) for j in idx]
                boots = [b for b in boots if b is not None]
                se = float(np.std(boots, ddof=1)) if boots else float("nan")
                res["rows"][f"{pname}->{tname}|h{h}"] = {"n": len(xs), "rho": rho, "t": rho / se if se and rho is not None else None}
    if out_path:
        Path(out_path).write_text(json.dumps(res, ensure_ascii=False, indent=1))
    return res


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    r = main(args[0], args[1] if len(args) > 1 else None, "--holdout" in sys.argv)
    print("window", r["window"])
    rows = sorted(r["rows"].items(), key=lambda kv: -abs(kv[1]["t"] or 0))
    for k, v in rows[:30]:
        print(f"{k:34s} n {v['n']:4d}  rho {v['rho']:+.3f}  t {v['t']:+5.2f}")
