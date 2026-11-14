"""S-864:今天这一格在历史上长什么样 —— 「状态 + 历史相似状态」的最低配(T-369 ⑫ / 高维回看 11-14)。

为什么:11-12、11-13 两次回看都把最大的权重给了「磨 / 收回」,用的锚是闸门基率与 ③ 的基率臂 —— 都不分利率与流动性状态。
三天后 BTC −11%。这份脚本把每一天按四个轴分格,报每一格之后 30 / 56 天 BTC 的分布,**连同独立段数与循环平移对照** ——
没有后两样,一张「同格历史」的表就是事后拟合的入口。

只描述。不进规则、不动敞口。预期与后果写在台账 S-864(先登记,后计算)。

四个轴(每一天只用当天及以前的数据):
  R 利率      2 年期收益率 − 91 天前的读数 > 0 ⇒ 升,否则 降
  L 边际流动性 稳定币 30 日供应变化 < 0 ⇒ 抽,否则 注
  W 周线结构   s851.weekly_down_days(周日收盘 < 10 周均线且 < 4 周前;下周一起生效)⇒ 坏 / 没坏
  T 趋势      面板离 200 日线 < 0 ⇒ 线下,否则 线上

用法(仓库根目录;取数与 s851 同一个 get(),环境变量 SUPABASE_URL / SUPABASE_KEY):
    python3 docs/research/s864_same_cell.py --selftest     # 合成数据,不连库
    python3 docs/research/s864_same_cell.py                # 写 docs/research/s864_results.json
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import sys

import numpy as np

_sp = importlib.util.spec_from_file_location("s851", os.path.join(os.path.dirname(os.path.abspath(__file__)), "s851_watch_base_rate.py"))
S = importlib.util.module_from_spec(_sp)
_sp.loader.exec_module(S)

OUT = "docs/research/s864_results.json"
HORIZONS = (30, 56)
BIG = 0.10                      # 「大动」= 30 天里 ±10%
GAP_MERGE_D = 5                 # 同一格里断开不超过 5 天算同一段
N_SHIFT = 2000
MIN_SHIFT_D = 180
SEED = 864
AXES = ("R", "L", "W", "T")
NAMES = {"R": ("升", "降"), "L": ("抽", "注"), "W": ("坏", "没坏"), "T": ("线下", "线上")}


def cells(days, close, dist200, stable, y2_d, y2_v) -> dict:
    """每一天 → 'R升|L抽|W坏|T线下' 这样的格子名;任何一轴读不到 ⇒ 这一天没有格子。"""
    wdown = S.weekly_down_days(days, close)
    out = {}
    for d in days:
        y_now, y_ago = S.asof(y2_d, y2_v, d, 7), S.asof(y2_d, y2_v, d - dt.timedelta(days=91), 7)
        st, di, wd = stable.get(d), dist200.get(d), wdown.get(d)
        if None in (y_now, y_ago, st, di, wd):
            continue
        flags = {"R": y_now > y_ago, "L": st < 0, "W": bool(wd), "T": di < 0}
        out[d] = "|".join(a + NAMES[a][0 if flags[a] else 1] for a in AXES)
    return out


def forward(days, close, h: int) -> dict:
    idx = {d: i for i, d in enumerate(days)}
    return {d: close[days[idx[d] + h]] / close[d] - 1 for d in days if idx[d] + h < len(days)}


def episodes(days_in: list) -> list[list]:
    eps, cur = [], []
    for d in days_in:
        if cur and (d - cur[-1]).days > GAP_MERGE_D:
            eps.append(cur)
            cur = []
        cur.append(d)
    return eps + ([cur] if cur else [])


def describe(days_in: list, fwd: dict) -> dict:
    r = np.array([fwd[d] for d in days_in if d in fwd])
    if not len(r):
        return {"n_days": 0}
    return {"n_days": int(len(r)), "median": round(float(np.median(r)), 4), "mean": round(float(r.mean()), 4),
            "p_down_big": round(float((r < -BIG).mean()), 3), "p_up_big": round(float((r > BIG).mean()), 3)}


def shift_p(labels: list, rets: np.ndarray, target: str, stat) -> dict:
    """循环平移对照:把格子标签整条平移 k 天(k ≥ 180),收益序列不动;看「这一格的统计量」落在平移分布的哪里。"""
    rng = np.random.default_rng(SEED)
    lab = np.array([x == target for x in labels])
    if lab.sum() < 5:
        return {"p_two_sided": None, "why": "这一格不足 5 天"}
    obs = stat(rets[lab])
    n = len(lab)
    sims = np.array([stat(rets[np.roll(lab, int(k))]) for k in rng.integers(MIN_SHIFT_D, n - MIN_SHIFT_D, N_SHIFT)])
    return {"obs": round(float(obs), 4), "null_mean": round(float(sims.mean()), 4),
            "p_two_sided": round(float((np.abs(sims - sims.mean()) >= abs(obs - sims.mean())).mean()), 4), "n_shift": N_SHIFT}


def run(days, close, dist200, taker, stable, y2_d, y2_v) -> dict:
    cell = cells(days, close, dist200, stable, y2_d, y2_v)
    labelled = [d for d in days if d in cell]
    today = labelled[-1]
    fw = {h: forward(days, close, h) for h in HORIZONS}
    usable = [d for d in labelled if d in fw[max(HORIZONS)]]          # 留出最后 56 天:它们的结果还没发生
    table = {}
    for name in sorted(set(cell.values())):
        in_cell = [d for d in usable if cell[d] == name]
        eps = episodes(in_cell)
        row = {"n_episodes": len(eps), "episode_starts": [e[0].isoformat() for e in eps][-12:]}
        for h in HORIZONS:
            row[f"d{h}"] = describe(in_cell, fw[h])
            row[f"d{h}_by_episode_start"] = describe([e[0] for e in eps], fw[h])
        table[name] = row
    lab_seq = [cell[d] for d in usable]
    r30 = np.array([fw[30][d] for d in usable])
    target = cell[today]
    control = {"mean_30d": shift_p(lab_seq, r30, target, lambda x: float(x.mean())),
               "p_down_big_30d": shift_p(lab_seq, r30, target, lambda x: float((x < -BIG).mean()))}
    uncond = {f"d{h}": describe(usable, fw[h]) for h in HORIZONS}
    t = table.get(target, {})
    d30 = t.get("d30", {})
    expectations = {
        "E1_today_cell_median_30d_negative": (d30.get("median") is not None and d30["median"] < 0),
        "E1_today_cell_p_down_at_least_5pp_above_uncond": (d30.get("p_down_big") is not None
                                                           and d30["p_down_big"] >= uncond["d30"]["p_down_big"] + 0.05),
        "E2_today_cell_fewer_than_8_episodes": t.get("n_episodes", 0) < 8,
        "E3_shift_p_mean_above_0.10": (control["mean_30d"].get("p_two_sided") or 1.0) > 0.10,
    }
    cut = usable[len(usable) // 2]
    half = cells([d for d in days if d <= cut], {d: v for d, v in close.items() if d <= cut}, dist200, stable, y2_d, y2_v)
    self_checks = {"cells_before_cut_ignore_the_future": all(half[d] == cell[d] for d in half),
                   "days_with_cell": len(labelled), "usable_days": len(usable), "n_cells": len(table)}
    return {"asof": today.isoformat(), "today_cell": target, "today_cell_row": t, "unconditional": uncond, "control_today_cell": control,
            "expectations": expectations, "table": table, "self_checks": self_checks,
            "coverage": {"first": labelled[0].isoformat(), "last_usable": usable[-1].isoformat()}}


if __name__ == "__main__":
    selftest = "--selftest" in sys.argv
    out = run(*(S.synthetic() if selftest else S.load_live()))
    for k in ("asof", "today_cell", "coverage", "today_cell_row", "unconditional", "control_today_cell", "expectations", "self_checks"):
        print(k.upper(), json.dumps(out[k], ensure_ascii=False), flush=True)
    print("TABLE")
    for name, row in out["table"].items():
        print(" ", name, "段", row["n_episodes"], "| 30天", json.dumps(row["d30"], ensure_ascii=False), "| 56天", json.dumps(row["d56"], ensure_ascii=False), flush=True)
    if selftest:
        assert out["self_checks"]["cells_before_cut_ignore_the_future"] and out["self_checks"]["n_cells"] >= 8
        assert sum(r["d30"].get("n_days", 0) for r in out["table"].values()) == out["self_checks"]["usable_days"]
        print("SELFTEST OK")
    else:
        json.dump(out, open(OUT, "w"), ensure_ascii=False, indent=1)
        print("WROTE", OUT)
