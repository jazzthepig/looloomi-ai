"""S-926:模拟 —— 把联合模型的分数 z 接进 ① 的仓位,过去四年会怎样。研究用,不进任何账、不动钱。

**先读检出力**(台账 11-06 方法记录):z 只有约 53 个不重叠的 30 天段,能检出的月 IC ≥ ≈ 0.34,实盘口径实测 0.131 ⇒
这里只能**描述**「照规则做会怎样」,测不出 z 有没有用。打乱分位给读者看,不是证明。

- z = `joint_forecast_daily`(ridge_v2;2026-11-04 及以前是 backfill = 用今天的数据补的历史,之后是 live);标的 = BTC 永续日收盘(`perp_bv_daily`)。
- z_d 在 d 收盘后才算得出 ⇒ 晚一天执行:w_d 作用在 d+1 → d+2 的收益;某天没有 z 就沿用上一个 w(最多 3 天),再没有就满仓。
- 规则 A「减半」:z < −1 ⇒ 0.5,否则 1.0。规则 B「线性」:clip(0.75 + 0.25 z, 0.25, 1.0)。成本 = 换手 × 10 bp。
- 对照:满仓;**同平均仓位的恒定持有**(每天按规则的平均仓位再平衡,不收成本 —— 对规则更难)。
- M = 规则减同平均仓位恒定持有的年化对数收益差;零分布 = z 整体循环平移 [90, n − 90) 天,1,000 次,种子 926。

用法(仓库根目录):
    python3 docs/research/s926_joint_z_sizing.py --selftest
    python3 docs/research/s926_joint_z_sizing.py                      # 读库(环境里有只读的 SUPABASE_URL / SUPABASE_KEY)
    python3 docs/research/s926_joint_z_sizing.py --from-json data.json  # {"z": [[YYMMDD, z, kind], ...], "c": [[YYMMDD, close], ...]}
"""
from __future__ import annotations

import datetime as dt
import json
import math
import os
import sys

import numpy as np

OUT = "docs/research/s926_results.json"
COST = 0.001
LAG = 2                      # w_d 作用在 d+2 那天的收益(d+1 收盘 → d+2 收盘)
CARRY = 3
N_SHIFT, SEED, MIN_SHIFT = 1000, 926, 90
SPLIT = dt.date(2024, 7, 1)
LIVE_FROM = dt.date(2026, 11, 5)


def rule_a(z: float) -> float:
    return 0.5 if z < -1 else 1.0


def rule_b(z: float) -> float:
    return float(min(1.0, max(0.25, 0.75 + 0.25 * z)))


RULES = {"A_halve": rule_a, "B_linear": rule_b}


def exposures(days: list, zmap: dict, rule) -> np.ndarray:
    """每个收益日 t 的仓位 = rule(z_{t − LAG});缺 z 沿用上一个(≤ CARRY 天),再缺满仓。"""
    out, last, age = [], None, 0
    for t in days:
        d = t - dt.timedelta(days=LAG)
        if d in zmap:
            last, age = rule(zmap[d]), 0
        else:
            age += 1
            if age > CARRY:
                last = None
        out.append(1.0 if last is None else last)
    return np.array(out)


def nav(r: np.ndarray, w: np.ndarray, cost: float = COST) -> np.ndarray:
    tw = np.abs(np.diff(np.r_[w[0], w]))
    return np.cumprod(1 + w * r - cost * tw)


def stats(days: list, nv: np.ndarray) -> dict:
    yrs = (days[-1] - days[0]).days / 365.25
    peak, dd, under, longest, start = 1.0, 0.0, 0, 0, None
    for i, v in enumerate(nv):
        if v >= peak:
            if start is not None:
                longest = max(longest, (days[i] - start).days)
            peak, start = v, None
        else:
            if start is None:
                start = days[i - 1] if i else days[0]
            dd = max(dd, 1 - v / peak)
    if start is not None:
        longest = max(longest, (days[-1] - start).days)
        under = (days[-1] - start).days
    return {"total": round(float(nv[-1] - 1), 4), "cagr": round(float(nv[-1] ** (1 / yrs) - 1), 4), "max_dd": round(dd, 4),
            "longest_underwater_d": longest, "underwater_now_d": under}


def m_stat(days: list, r: np.ndarray, w: np.ndarray, mask=None) -> float:
    """规则减同平均仓位恒定持有的年化对数收益差(mask = 只看这段)。"""
    m = np.ones(len(r), bool) if mask is None else mask
    wb = float(w[m].mean())
    tw = np.abs(np.diff(np.r_[w[0], w]))
    lr_rule = np.log1p(w * r - COST * tw)[m].sum()
    lr_stat = np.log1p(wb * r)[m].sum()
    yrs = m.sum() / 365.25
    return float((lr_rule - lr_stat) / yrs)


def run(days: list, r: np.ndarray, zdays: list, zvals: list) -> dict:
    zmap = dict(zip(zdays, zvals))
    rng = np.random.default_rng(SEED)
    halves = {"first": np.array([t < SPLIT for t in days]), "second": np.array([t >= SPLIT for t in days])}
    hold = nav(r, np.ones(len(r)), 0.0)
    out = {"window": [str(days[0]), str(days[-1])], "n_days": len(days), "hold": stats(days, hold), "rules": {}}
    for name, f in RULES.items():
        w = exposures(days, zmap, f)
        wb = float(w.mean())
        nv, st = nav(r, w), nav(r, np.full(len(r), wb), 0.0)
        m_all = m_stat(days, r, w)
        null = []
        n = len(zvals)
        for _ in range(N_SHIFT):
            o = int(rng.integers(MIN_SHIFT, n - MIN_SHIFT))
            zs = dict(zip(zdays, np.roll(np.array(zvals), o)))
            null.append(m_stat(days, r, exposures(days, zs, f)))
        null = np.array(null)
        out["rules"][name] = {
            "avg_w": round(wb, 3), "share_days_cut": round(float((w < 1).mean()), 3), "turnover_per_yr": round(float(np.abs(np.diff(w)).sum() / (len(w) / 365.25)), 2),
            "rule": stats(days, nv), "static_same_avg": stats(days, st),
            "M_all": round(m_all, 4), "M_first": round(m_stat(days, r, w, halves["first"]), 4), "M_second": round(m_stat(days, r, w, halves["second"]), 4),
            "null_median": round(float(np.median(null)), 4), "null_q95": round(float(np.quantile(null, 0.95)), 4), "pct": round(float((null < m_all).mean()), 3)}
        rr = out["rules"][name]
        rr["criteria"] = {"M_both_halves_gt_0": bool(rr["M_first"] > 0 and rr["M_second"] > 0), "pct_ge_0.95": bool(rr["pct"] >= 0.95),
                          "dd_lt_static": bool(rr["rule"]["max_dd"] < rr["static_same_avg"]["max_dd"])}
        rr["recommend_wire_in"] = bool(all(rr["criteria"].values()))
    return out


def load(path: str | None) -> tuple:
    if path:
        j = json.load(open(path))
        zr = [(dt.datetime.strptime(a, "%y%m%d").date(), float(b), k) for a, b, k in j["z"]]
        cr = [(dt.datetime.strptime(a, "%y%m%d").date(), float(b)) for a, b in j["c"]]
    else:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import importlib.util
        sp = importlib.util.spec_from_file_location("s851", os.path.join(os.path.dirname(os.path.abspath(__file__)), "s851_watch_base_rate.py"))
        S = importlib.util.module_from_spec(sp)
        sp.loader.exec_module(S)
        zr = [(S.D(x["d"]), float(x["z"]), x["kind"][0]) for x in S.get("joint_forecast_daily", {"select": "d,z,kind", "model": "eq.ridge_v2", "z": "not.is.null", "order": "d.asc"})]
        cr = [(S.D(x["d"]), float(x["c"])) for x in S.get("perp_bv_daily", {"select": "d,c", "symbol": "eq.BTC", "d": "gte.2022-06-01", "order": "d.asc"})]
    return zr, cr


def prepare(zr: list, cr: list) -> tuple:
    zdays, zvals = [d for d, _, _ in zr], [v for _, v, _ in zr]
    cmap = dict(cr)
    cd = sorted(cmap)
    first, last = zdays[0] + dt.timedelta(days=LAG), min(cd[-1], zdays[-1] + dt.timedelta(days=LAG))
    days, r = [], []
    for i in range(1, len(cd)):
        t = cd[i]
        if first <= t <= last and (t - cd[i - 1]).days == 1:
            days.append(t)
            r.append(cmap[t] / cmap[cd[i - 1]] - 1)
    return days, np.array(r), zdays, zvals


def synthetic() -> tuple:
    rng = np.random.default_rng(1)
    d0 = dt.date(2022, 6, 1)
    n = 1500
    z = rng.normal(size=n)
    # 让 z 低的日子之后两天收益偏低一点 —— 规则 A 应当有正 M
    r = rng.normal(0.0005, 0.03, n + 5)
    for i in range(n):
        if z[i] < -1:
            r[i + LAG] -= 0.01
    zr = [(d0 + dt.timedelta(days=i), float(z[i]), "b") for i in range(n)]
    px, cr = 100.0, [(d0 - dt.timedelta(days=1), 100.0)]
    for i in range(n + 5):
        px *= 1 + r[i]
        cr.append((d0 + dt.timedelta(days=i), px))
    return zr, cr


if __name__ == "__main__":
    selftest = "--selftest" in sys.argv
    if selftest:
        N_SHIFT = 60
        zr, cr = synthetic()
    else:
        p = sys.argv[sys.argv.index("--from-json") + 1] if "--from-json" in sys.argv else None
        zr, cr = load(p)
    days, r, zdays, zvals = prepare(zr, cr)
    print("loaded", json.dumps({"z_days": len(zdays), "live_z_days": sum(1 for _, _, k in zr if k == "l"), "ret_days": len(days),
                                "window": [str(days[0]), str(days[-1])]}), flush=True)
    out = run(days, r, zdays, zvals)
    print("HOLD", json.dumps(out["hold"]), flush=True)
    for k, v in out["rules"].items():
        print("RULE", k, json.dumps({q: v[q] for q in ("avg_w", "share_days_cut", "turnover_per_yr", "M_all", "M_first", "M_second", "null_median", "null_q95", "pct")}),
              "| rule", json.dumps(v["rule"]), "| static", json.dumps(v["static_same_avg"]), "| crit", json.dumps(v["criteria"]),
              "| WIRE_IN" if v["recommend_wire_in"] else "", flush=True)
    if selftest:
        # 晚一天执行:第 t 天的仓位只看 t − LAG 那天的 z
        zm = {zdays[0]: -2.0}
        assert list(exposures([zdays[0] + dt.timedelta(days=LAG)], zm, rule_a)) == [0.5]
        assert list(exposures([zdays[0] + dt.timedelta(days=LAG - 1)], zm, rule_a)) == [1.0]          # 前一天还看不到这个 z
        assert list(exposures([zdays[0] + dt.timedelta(days=LAG + k) for k in range(5)], zm, rule_a)) == [0.5] * 4 + [1.0]   # 沿用 ≤ 3 天
        assert rule_b(-5) == 0.25 and rule_b(5) == 1.0 and abs(rule_b(-1) - 0.5) < 1e-12
        # 恒定满仓、零成本 ⇒ M = 0
        assert abs(m_stat(days, r, np.ones(len(r)))) < 1e-12
        assert out["rules"]["A_halve"]["M_all"] > 0, "合成数据里 z 低之后收益偏低,规则 A 应当正"
        print("SELFTEST OK")
    else:
        json.dump(out, open(OUT, "w"), ensure_ascii=False, indent=1, default=str)
        print("WROTE", OUT)
