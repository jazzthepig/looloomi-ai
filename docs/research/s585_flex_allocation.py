"""S-585 —— 灵活配置组合 v1(预注册见 REFUTATION_LEDGER §S-585):加密 10–70%、World50 10–80%、总仓位 ≥ 30%,引擎按风格配。

用法:python3 docs/research/s585_flex_allocation.py <w50_daily 目录> [输出 json] [--w50-arm EW_B|FAST_B]
判据:规则对「同平均权重的恒定组合」apparatus.ab_test 为 B > A,且状态序列 13 周块打乱 1,000 次后规则的对数总收益 ≥ 95 分位。
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

from src.data.evaluation.apparatus import ab_test, block_permute, null_distribution, percentile_of  # noqa: E402
from s584_world50_weekly_mom import load, per_year, run_arm, stats  # noqa: E402

CRYPTO = ("BTC", "ETH", "XRP", "BNB", "SOL")
MA_WEEKS, RM_WEEKS = 40, 13
COST = {"c": 20 / 1e4, "w": 10 / 1e4}
#: 状态 → (加密, World50);TC↑TW↑ 的加密份额由 RM 定
TABLE = {("up", "down"): (0.55, 0.15), ("down", "up"): (0.10, 0.80), ("down", "down"): (0.10, 0.20)}


def crypto_leg(grid: list[str], wc: dict, wr: dict, snaps: dict) -> list[Optional[float]]:
    """五个大币按上一周五的市值加权,每周再平衡;第 i 项 = 第 i 周的收益。"""
    out: list[Optional[float]] = [None]
    for i in range(1, len(grid)):
        snap = snaps.get(grid[i - 1], {})
        caps = {k: snap[k] for k in CRYPTO if k in snap and k in wr and wr[k][i] is not None}
        tot = sum(caps.values())
        out.append(sum(caps[k] / tot * wr[k][i] for k in caps) if tot > 0 else None)
    return out


def index_from(rets: list[Optional[float]]) -> list[Optional[float]]:
    lvl, out = None, []
    for r in rets:
        if r is None:
            out.append(lvl)
            continue
        lvl = (lvl or 1.0) * (1 + r)
        out.append(lvl)
    return out


def states(idx_c: list[Optional[float]], idx_w: list[Optional[float]]) -> list[Optional[tuple[str, str, float]]]:
    """第 i 周收盘的状态(用到第 i 周为止的数据):(TC, TW, RM)。不够 40 周 ⇒ None。"""
    out: list[Optional[tuple[str, str, float]]] = []
    for i in range(len(idx_c)):
        if i < MA_WEEKS or any(x is None for x in idx_c[i - MA_WEEKS + 1: i + 1] + idx_w[i - MA_WEEKS + 1: i + 1]) \
                or idx_c[i - RM_WEEKS] is None or idx_w[i - RM_WEEKS] is None:
            out.append(None)
            continue
        ma_c = float(np.mean(idx_c[i - MA_WEEKS + 1: i + 1]))
        ma_w = float(np.mean(idx_w[i - MA_WEEKS + 1: i + 1]))
        rm = (idx_c[i] / idx_c[i - RM_WEEKS]) - (idx_w[i] / idx_w[i - RM_WEEKS])
        out.append(("up" if idx_c[i] > ma_c else "down", "up" if idx_w[i] > ma_w else "down", rm))
    return out


def target(st: tuple[str, str, float]) -> tuple[float, float]:
    tc, tw, rm = st
    if (tc, tw) == ("up", "up"):
        c = 0.55 if rm > 0 else 0.35
        return c, min(0.80, 1.0 - c)
    return TABLE[(tc, tw)]


def simulate(rc: list[float], rw: list[float], tgt: list[tuple[float, float]], cash_yield: float = 0.0) -> list[float]:
    """每周初按目标权重持有(上一周末定的),周内不漂;换手按目标的变化计成本。"""
    rf = (1 + cash_yield) ** (1 / 52) - 1
    out, prev = [], None
    for (c, w), a, b in zip(tgt, rc, rw):
        cash = 1 - c - w
        r = c * a + w * b + cash * rf
        if prev is not None:
            r -= abs(c - prev[0]) * COST["c"] + abs(w - prev[1]) * COST["w"]
        out.append(r)
        prev = (c, w)
    return out


def main(dir_: str, out_path: Optional[str] = None, w50_arm: str = "EW_B") -> dict[str, Any]:
    grid, wc, wr, snaps, cls = load(dir_)
    arm, every = w50_arm.split("_")
    wl = run_arm(arm, 2 if every == "B" else 1, grid, wc, wr, snaps, cls)
    pos = {g: i for i, g in enumerate(grid)}
    rw_full: list[Optional[float]] = [None] * len(grid)
    for g, r in zip(wl["weeks"], wl["ret"]):
        rw_full[pos[g]] = r
    rc_full = crypto_leg(grid, wc, wr, snaps)
    st = states(index_from(rc_full), index_from(rw_full))
    # 第 i 周的收益用第 i − 1 周收盘的状态
    rows = [(grid[i], rc_full[i], rw_full[i], st[i - 1]) for i in range(1, len(grid))
            if rc_full[i] is not None and rw_full[i] is not None and st[i - 1] is not None]
    weeks = [r[0] for r in rows]
    rc = [r[1] for r in rows]
    rw = [r[2] for r in rows]
    sts = [r[3] for r in rows]
    tgt = [target(s) for s in sts]
    rule = simulate(rc, rw, tgt)
    avg_c = float(np.mean([t[0] for t in tgt]))
    avg_w = float(np.mean([t[1] for t in tgt]))
    const = simulate(rc, rw, [(avg_c, avg_w)] * len(rc))
    res: dict[str, Any] = {"weeks": [weeks[0], weeks[-1], len(weeks)], "w50_arm": w50_arm,
                           "avg_weights": {"crypto": avg_c, "world50": avg_w, "cash": 1 - avg_c - avg_w}}
    series = {"rule": rule, "constant_same_avg": const,
              "static_30_50": simulate(rc, rw, [(0.30, 0.50)] * len(rc)),
              "crypto_only": rc, "world50_only": rw}
    if "BTC" in wr:
        series["btc_only"] = [wr["BTC"][pos[g]] or 0.0 for g in weeks]
    res["stats"] = {k: {**stats(v), "per_year": per_year(weeks, v)} for k, v in series.items()}
    res["primary_ab"] = ab_test(const, rule, mean_block=4, days_per_year=52)
    actual = float(np.log1p(np.asarray(rule)).sum())

    def shuffled(rng):
        perm = block_permute(list(range(len(sts))), 13, rng)
        return float(np.log1p(np.asarray(simulate(rc, rw, [tgt[int(j)] for j in perm]))).sum())
    null = null_distribution(shuffled, 1000, seed=20261016, actual=actual)
    res["primary_random_pct"] = percentile_of(actual, null)
    res["passes"] = res["primary_ab"]["verdict"] == "B > A" and (res["primary_random_pct"] or 0) >= 0.95
    res["cash4"] = {"rule": stats(simulate(rc, rw, tgt, 0.04)), "const": stats(simulate(rc, rw, [(avg_c, avg_w)] * len(rc), 0.04))}
    occ: dict[str, dict] = {}
    for s, a, b in zip(sts, rc, rw):
        key = f"C{s[0]}_W{s[1]}"
        o = occ.setdefault(key, {"weeks": 0, "c": [], "w": []})
        o["weeks"] += 1
        o["c"].append(a)
        o["w"].append(b)
    res["by_state"] = {k: {"weeks": v["weeks"], "crypto_ann": float(np.mean(v["c"]) * 52), "world50_ann": float(np.mean(v["w"]) * 52)}
                       for k, v in occ.items()}
    if out_path:
        Path(out_path).write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float))
    return res


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    arm = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--w50-arm=")), "EW_B")
    r = main(args[0], args[1] if len(args) > 1 else None, arm)
    print("weeks", r["weeks"], "avg", {k: round(v, 3) for k, v in r["avg_weights"].items()})
    for k, v in r["stats"].items():
        print(f"{k:18s} CAGR {v['cagr']*100:6.2f}%  vol {v['vol']*100:5.1f}%  MDD {v['max_dd']*100:6.1f}%  calmar {v['calmar'] or 0:.2f}")
    p = r["primary_ab"]
    print("AB rule vs const:", p["verdict"], "ratio", round(p["ratio_b_over_a"], 3), "MDE/yr", round(p["mde_log_diff_per_year"], 4),
          "| random pct", round(r["primary_random_pct"], 3), "| passes", r["passes"])
    print("by_state", r["by_state"])
