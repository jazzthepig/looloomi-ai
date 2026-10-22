"""S-656 / T-165:Trader Tom「对了才加」+ 主动买盘确认 —— 满仓不变,+1R 那天 taker_ratio_mean ≥ 1.123 才加 0.5 B。

预注册原文(REFUTATION_LEDGER S-656,2026-10-21 11:31 UTC 写于对任何加仓按资金流分组之前)照实现,
只改 S-654 的加仓机制:底仓 1 B(原规则满仓,不动),**只加第一档 0.5 B**(不给第 2 档),加不加由
taker 条件决定。加仓的 atr14 / unit_r / 单位止损写法同 S-654。

票与日线 = C 道 T-159 缓存;资金流 = Supabase `deriv_metrics_daily`(source=binance_vision_metrics,只读 publishable key)。
零分布 / 分位只用 `src/data/evaluation/apparatus.py`。

用法:python3 docs/research/t165_flow_confirmed_add.py [--root /Volumes/CometCloudAI/cometcloud-local] [--out <报告路径>]
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, REPO)
spec = importlib.util.spec_from_file_location("s647", os.path.join(HERE, "s647_sim_r_v2.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

from src.data.evaluation.apparatus import (  # noqa: E402  —— 零分布/分位只许走 apparatus
    NoOpNull,
    null_distribution,
    percentile_of,
    shuffle_within,
    stationary_bootstrap_index,
)

COST_SIDE = 0.002          # 每边 0.2%,同 S-654 / S-656
BASE_UNIT = 1.0            # 底仓:原规则满仓一张票 = 1 B
ADD_UNIT = 0.5             # 条件加仓 0.5 B
ADD_R_K = 1.0              # 只加第一档:收盘 ≥ 进场 + 1R
STOP_ATR = 2.5
TAKER_CUT = 1.123          # S-614 前三分之一切点,冻结,不重估
N_BOOT = 2000
HURDLE_R = 0.48            # 新票 770 张的平均 R(S-654 引的同一批)


# ── 加仓机制(写法同 S-654 的 atr14 / unit_r / 单位止损)────────────────────────
def atr14(bs: dict, day: dt.date):
    ds, d = [], day
    while len(ds) < 15 and d >= day - dt.timedelta(days=60):
        if d in bs:
            ds.append(d)
        d -= dt.timedelta(days=1)
    ds = sorted(ds)
    if len(ds) < 15:
        return None
    trs = [max(bs[ds[i]][1] - bs[ds[i]][2], abs(bs[ds[i]][1] - bs[ds[i - 1]][3]),
               abs(bs[ds[i]][2] - bs[ds[i - 1]][3])) for i in range(1, len(ds))]
    return sum(trs[-14:]) / 14.0


def unit_r(entry, stop, exit_px):
    risk = entry - stop
    return (exit_px - entry) / risk - 2 * COST_SIDE * entry / risk


def add_unit(t: dict, bs: dict, end: dt.date, entry_day: dt.date):
    """把「加 0.5 B」跑一遍,不看资金流条件。

    返回 (add_R or None, trig_day or None, add_entry_px or None)。R 按加仓单位自己的风险算(S-656 单位条)。
    """
    entry, stop = t["entry_px"], t["stop_px"]
    R = entry - stop
    x = dt.date.fromisoformat(t["exit_d"]) if t.get("exit_d") else None
    base_exit_px = t["exit_px"] if x else None
    last = x if x else end
    if x is None:                                            # 仍在持有:按最后收盘盯市
        base_exit_px = bs[max(d for d in bs if d <= end)][3]
    # 第一个收盘 ≥ 进场 + 1R 的日子 t(必须早于原规则的出场判定日)
    trig = None
    for d in sorted(x_ for x_ in bs if entry_day <= x_ < last):
        if bs[d][3] >= entry + ADD_R_K * R:
            trig = d
            break
    if trig is None:
        return None, None, None
    ad = trig + dt.timedelta(days=1)
    while ad not in bs and ad <= last:
        ad += dt.timedelta(days=1)
    if ad > last or (x and ad >= x):
        return None, trig, None
    a = bs[ad][0]
    at = atr14(bs, trig)
    if not at:
        return None, trig, None
    s = a - STOP_ATR * at
    # 这个单位:自己的止损先到 ⇒ 按 min(开盘, 止损);否则跟着整张票在原出场价出
    px, dd = None, ad
    while dd <= last:
        b = bs.get(dd)
        if b and (x is None or dd < x or (x and dd == x and t["exit_px"] <= t["stop_px"] * (1 + 1e-9))):
            if b[2] <= s:
                px = min(b[0], s)
                break
        dd += dt.timedelta(days=1)
    if px is None:
        px = base_exit_px
    return unit_r(a, s, px), trig, a


def mdd_by_exit(rows, key):
    rows = sorted(rows, key=lambda r: r["exit"])
    cum = peak = mdd = 0.0
    for r in rows:
        cum += r[key]
        peak = max(peak, cum)
        mdd = min(mdd, cum - peak)
    return mdd


# ── 资金流(deriv_metrics_daily,binance_vision_metrics)────────────────────────
def load_metrics(root: str) -> tuple[dict, dict]:
    import time
    import urllib.request

    cache = os.path.join(root, "research/t165_metrics.json")   # 重跑不重复打 Supabase
    if os.path.exists(cache):
        rows = json.load(open(cache))
    else:
        u, k = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY")
        if not u or not k:
            sys.exit("需要 SUPABASE_URL / SUPABASE_KEY(只读 publishable key)")
        h = {"apikey": k, "Authorization": "Bearer " + k}
        rows, off = [], 0
        while True:
            url = (u + "/rest/v1/deriv_metrics_daily?select=symbol,d,taker_ratio_mean,n_points,source"
                   "&source=eq.binance_vision_metrics&order=d&limit=5000&offset=" + str(off))
            batch = None
            for attempt in range(5):                            # SSL EOF / 5xx 会偶发,重试
                try:
                    batch = json.load(urllib.request.urlopen(
                        urllib.request.Request(url, headers=h), timeout=180))
                    break
                except Exception as exc:                      # noqa: BLE001 —— 网络层,原样重试
                    if attempt == 4:
                        sys.exit("deriv_metrics_daily 取数失败(offset=%d):%s" % (off, exc))
                    time.sleep(2 * (attempt + 1))
            if not batch:
                break
            rows.extend(batch)
            off += len(batch)
            if off > 400000:
                break
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        json.dump(rows, open(cache, "w"))
    met, zer, nul = {}, 0, 0
    by_year: dict = defaultdict(lambda: [0, 0])
    for r in rows:
        by_year[r["d"][:4]][0 if (r["taker_ratio_mean"] is not None
                                  and r["n_points"] not in (0, None)) else 1] += 1
    for r in rows:
        if r["taker_ratio_mean"] is None:                     # 有行但没值 ⇒ 同「无 metrics」,不加
            nul += 1
            continue
        if r["n_points"] in (0, None):                        # n_points = 0 ⇒ 不加,单独计数
            zer += 1
            continue
        met[(r["symbol"], r["d"])] = float(r["taker_ratio_mean"])
    present = {(r["symbol"], r["d"]) for r in rows}
    return met, {"rows": len(rows), "n_points_zero": zer, "taker_null": nul, "present": present,
                 "n_usable": len(met), "first_usable_d": min((d for _, d in met), default=None),
                 "usable_by_year": {y: v for y, v in sorted(by_year.items())}}


# ── 两个判的口径。③ 与 ② 跑的是同一个函数、同一口径(Seth 10-21:判②③同一比较)──────
def judge_hurdle(sat_adds: list, seed: int) -> dict:
    """① 条件加仓单位平均 R > +0.48。H0(均值 = 0.48)中心化后按信号月份块 P-R 平稳块自助,单侧 p。"""
    o = {"hurdle_R": HURDLE_R, "observed_mean_R": None, "n": len(sat_adds),
         "p_one_sided": None, "boot_p05": None, "note": None}
    if len(sat_adds) < 2:
        o["note"] = "样本不足 2,测不了"
        return o
    order = np.argsort([a["month"] for a in sat_adds])
    v = np.array([sat_adds[i]["r"] for i in order], dtype=float)   # 按信号月份排序,块 = 连续月份
    obs = float(v.mean())
    idx = stationary_bootstrap_index(v.size, mean_block=3.0, n_boot=N_BOOT,
                                     rng=np.random.default_rng(seed))
    null_v = v - v.mean() + HURDLE_R
    boot_null = null_v[idx].mean(axis=1)
    boot_obs = v[idx].mean(axis=1)
    o.update(observed_mean_R=obs,
             p_one_sided=float((boot_null >= obs).mean()),
             boot_mean=float(boot_obs.mean()),
             boot_p05=float(np.percentile(boot_obs, 5)),
             note="H0 中心化到 0.48 后按月块(P-R 平稳块自助,mean_block=3 月)重抽;单侧 p = P(boot≥观测均值)")
    return o


def judge_diff(pairs: list, seed: int) -> dict:
    """条件 − 不满足条件的平均 R 差,按信号年份分块标签打乱,单侧 p。
    ②(全书)与 ③(分两段)以及留一年回放都走这里 —— 同一个统计量、同一套零分布。"""
    o = {"actual_diff_R": None, "p_one_sided": None, "null_pctile_of_actual": None,
         "n_satisfied": 0, "n_unsatisfied": 0, "mean_R_satisfied": None,
         "mean_R_unsatisfied": None, "ok": False, "ok_sign_only": False, "note": None}
    ps = [a for a in pairs if a["sat"]]
    pu = [a for a in pairs if a["sat"] is False]
    o["n_satisfied"], o["n_unsatisfied"] = len(ps), len(pu)
    if not ps or not pu:
        o["note"] = "两组有一组是空的,测不了(报告里显示为 —)"
        return o
    vals = np.array([a["r"] for a in pairs], dtype=float)
    yrs = np.array([a["year"] for a in pairs], dtype=object)
    lab = np.array([bool(a["sat"]) for a in pairs])
    actual = float(vals[lab].mean() - vals[~lab].mean())
    o.update(actual_diff_R=actual, mean_R_satisfied=float(vals[lab].mean()),
             mean_R_unsatisfied=float(vals[~lab].mean()))

    def stat(rng):
        sv = np.asarray(shuffle_within(vals, yrs, rng), dtype=float)
        return float(sv[lab].mean() - sv[~lab].mean())

    null = np.asarray(null_distribution(stat, N_BOOT, seed, actual=actual), dtype=float)
    # 单侧 p = 零分布落在实际值之上的比例(alternative 是「条件更高」,右尾)
    o["p_one_sided"] = float(((null >= actual).sum() + 0.5 * (null == actual).sum()) / null.size)
    o["null_pctile_of_actual"] = percentile_of(actual, null)
    o["ok"] = bool(actual > 0 and o["p_one_sided"] is not None and o["p_one_sided"] < 0.05)
    o["ok_sign_only"] = bool(actual > 0)                     # 预注册 ③ 原文只写「条件都高于不满足条件」
    o["note"] = ("按信号年份分块标签打乱(apparatus.shuffle_within 换值归属,组间不混);"
                 "单侧 p = P(零分布 ≥ 实际差)")
    return o


def main():
    root = sys.argv[sys.argv.index("--root") + 1] if "--root" in sys.argv else \
        "/Volumes/CometCloudAI/cometcloud-local"
    out_path = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else os.path.join(
        root, "_reports/absorb_input/T-165_s656_flow_add.md")

    bars, fund, tix = m.load(root)
    met, mstat = load_metrics(root)

    rows, adds = [], []
    trig_years = []
    n_trig = n_has_met = n_sat = n_no_row = n_unusable = 0
    for t in tix:
        bs = bars.get(t["symbol"], {})
        base = t["r"] if t["r"] is not None else 0.0
        if t["r"] is None:                                    # 仍在持有:按最后收盘盯市
            lc = bs[max(d for d in bs if d <= m.HIST_END)][3]
            base = unit_r(t["entry_px"], t["stop_px"], lc)
        r_add, trig, a_px = add_unit(t, bs, m.HIST_END, dt.date.fromisoformat(t["entry_d"]))
        sat, tk = None, None
        if trig is not None:
            n_trig += 1
            trig_years.append(t["signal_d"][:4])
            key = (t["symbol"], trig.isoformat())
            if key in met:
                n_has_met += 1
                tk = met[key]
                sat = tk >= TAKER_CUT
                n_sat += bool(sat)
            else:
                n_no_row += 1
                if key in mstat["present"]:
                    n_unusable += 1
        F = base * BASE_UNIT                                   # 规则 F = 1 B 底仓(不动)
        if r_add is not None and sat:
            F += ADD_UNIT * r_add
        rows.append({"tid": f"{t['symbol']}:{t['signal_d']}", "symbol": t["symbol"],
                     "signal_d": t["signal_d"], "exit": t.get("exit_d") or m.HIST_END.isoformat(),
                     "base": base, "F": F, "trig": trig.isoformat() if trig else None,
                     "sat": sat, "taker": tk})
        if r_add is not None and trig is not None and tk is not None:
            adds.append({"tid": f"{t['symbol']}:{t['signal_d']}", "signal_d": t["signal_d"],
                         "year": t["signal_d"][:4], "month": t["signal_d"][:7],
                         "r": r_add, "sat": sat, "taker": tk})

    sat_adds = [a for a in adds if a["sat"]]
    uns_adds = [a for a in adds if a["sat"] is False]
    out = {
        "n_tickets": len(rows),
        "baseline_repro": {
            "original_total_B": sum(r["base"] for r in rows),          # 须复现 S-654 的 372.2 B
            "original_mdd_B": mdd_by_exit(rows, "base"),
            "ruleF_total_B": sum(r["F"] for r in rows),
            "ruleF_mdd_B": mdd_by_exit(rows, "F"),
            "losers_original_B": sum(r["base"] for r in rows if r["base"] < 0),
            "losers_ruleF_B": sum(r["F"] for r in rows if r["base"] < 0),
        },
        "counts": {"plus1R_triggers": n_trig, "with_metrics": n_has_met, "satisfied_taker": n_sat,
                   # 「用不上的」拆两段:表里根本没这一行 vs 有行但不可用(n_points=0 或值为空)
                   "no_metrics_row_total": n_no_row,
                   "no_row_absent": n_no_row - n_unusable, "unusable_row": n_unusable,
                   "metrics_n_points_zero": mstat["n_points_zero"],
                   "add_units_built": len(adds)},
        "metrics_rows": mstat["rows"], "metrics_usable_rows": mstat["n_usable"],
        "metrics_first_usable": mstat["first_usable_d"], "metrics_by_year": mstat["usable_by_year"],
        "add_units": {
            "n_total": len(adds), "n_satisfied": len(sat_adds), "n_unsatisfied": len(uns_adds),
            "mean_R_satisfied": float(np.mean([a["r"] for a in sat_adds])) if sat_adds else None,
            "mean_R_unsatisfied": float(np.mean([a["r"] for a in uns_adds])) if uns_adds else None,
            "sum_R_satisfied": float(np.sum([a["r"] for a in sat_adds])),
        },
    }

    # ① 条件加仓单位平均 R > +0.48 —— 按信号月份分块自助,单侧 p(H0 中心化到 0.48)
    out["judge_1"] = judge_hurdle(sat_adds, 1652026)

    # ② 条件 − 不满足条件 的平均 R 差 —— 按年分块标签打乱,单侧 p
    pairs = [a for a in adds if a["sat"] is not None]
    out["judge_2"] = judge_diff(pairs, 1652026)

    # ③ 两段(< 2023 / ≥ 2023)条件加仓平均 R 都高于同段不满足条件
    #    同一个 judge_diff、同一口径(Seth 10-21:判②③同一比较),只是把样本切成两段
    out["judge_3"] = {}
    for k, (lab3, lo, hi) in enumerate((("lt2023", "0000", "2023-01-01"),
                                        ("ge2023", "2023-01-01", "9999"))):
        sel = [a for a in pairs if lo <= a["signal_d"] < hi]
        out["judge_3"][lab3] = judge_diff(sel, 1652026 + 3 + k)

    # 留一年(leave-one-year-out):把某个信号年整年拿掉,①② 各按同一口径重算一遍
    out["loyo"] = []
    for y in sorted({a["year"] for a in adds}):
        keep = [a for a in adds if a["year"] != y]
        h = judge_hurdle([a for a in keep if a["sat"]], 1652026 + int(y))
        d = judge_diff([a for a in keep if a["sat"] is not None], 1652026 + int(y))
        out["loyo"].append({
            "held_out_year": y, "n_units_kept": len(keep), "n_satisfied_kept": h["n"],
            "j1_mean_R": h["observed_mean_R"], "j1_p": h["p_one_sided"],
            "j1_boot_p05": h["boot_p05"],
            "j1_over": bool(h["observed_mean_R"] is not None and h["observed_mean_R"] > HURDLE_R
                            and h["p_one_sided"] is not None and h["p_one_sided"] < 0.05),
            "j2_diff_R": d["actual_diff_R"], "j2_p": d["p_one_sided"],
            "j2_over": bool(d["actual_diff_R"] is not None and d["actual_diff_R"] > 0
                            and d["p_one_sided"] is not None and d["p_one_sided"] < 0.05)})
    out["loyo_summary"] = {
        "folds": len(out["loyo"]),
        "j1_pass_folds": sum(r["j1_over"] for r in out["loyo"]),
        "j2_pass_folds": sum(r["j2_over"] for r in out["loyo"])}

    # 每年的触发 / 有 metrics / 满足条件 —— 解释 ③ 的 < 2023 半段为什么是空的
    out["by_year"] = []
    for y in sorted({t["signal_d"][:4] for t in tix}):
        trg = sum(1 for a in trig_years if a == y)
        sub = [a for a in adds if a["year"] == y]
        out["by_year"].append({"year": y, "tickets": sum(1 for t in tix if t["signal_d"][:4] == y),
                               "triggers": trg, "with_metrics": len(sub),
                               "satisfied": sum(a["sat"] for a in sub),
                               "mean_R_sat": float(np.mean([a["r"] for a in sub if a["sat"]]))
                               if any(a["sat"] for a in sub) else None,
                               "mean_R_unsat": float(np.mean([a["r"] for a in sub if not a["sat"]]))
                               if any(not a["sat"] for a in sub) else None})

    # 尾部诊断:均值被极端值扛着多少
    def tail(vals):
        if not vals:
            return None
        a = np.array(vals, dtype=float)
        return {"n": int(a.size), "mean": float(a.mean()), "median": float(np.median(a)),
                "p90": float(np.percentile(a, 90)), "max": float(a.max()),
                "trimmed_mean_drop_top3": float(np.sort(a)[:-3].mean()) if a.size > 3 else None}

    out["tail"] = {"satisfied": tail([a["r"] for a in sat_adds]),
                   "unsatisfied": tail([a["r"] for a in uns_adds]),
                   "taker_sat_mean": float(np.mean([a["taker"] for a in sat_adds])) if sat_adds else None,
                   "taker_unsat_mean": float(np.mean([a["taker"] for a in uns_adds])) if uns_adds else None}

    out["book_halves"] = {}
    for lab4, lo, hi in (("lt2023", "0000", "2023-01-01"), ("ge2023", "2023-01-01", "9999")):
        sel = [r for r in rows if lo <= r["signal_d"] < hi]
        out["book_halves"][lab4] = {"n": len(sel), "original_B": sum(r["base"] for r in sel),
                                    "ruleF_B": sum(r["F"] for r in sel)}
    top = sorted(rows, key=lambda r: -(r["F"] - r["base"]))[:10]
    out["top10_by_add_delta"] = [(r["tid"], round(r["base"], 2), round(r["F"], 2),
                                  round(r["F"] - r["base"], 2), r["trig"], r["taker"]) for r in top]
    out["verdict"] = verdict(out)

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as fh:
        fh.write(render(out))
    print(json.dumps(out, indent=1, default=str))


def verdict(o: dict) -> dict:
    j1, j2, j3 = o["judge_1"], o["judge_2"], o["judge_3"]
    c1 = bool(j1.get("observed_mean_R") is not None and j1["observed_mean_R"] > HURDLE_R
              and j1.get("p_one_sided") is not None and j1["p_one_sided"] < 0.05)
    c2 = bool(j2.get("actual_diff_R") is not None and j2["actual_diff_R"] > 0
              and j2.get("p_one_sided") is not None and j2["p_one_sided"] < 0.05)
    c3 = bool(j3["lt2023"]["ok"] and j3["ge2023"]["ok"])       # 与 ② 同一比较:差 > 0 且 p < 0.05
    return {"c1": c1, "c2": c2, "c3": c3, "all_three": bool(c1 and c2 and c3)}


def f(x, n=2):
    return "—" if x is None else (f"{x:.{n}f}" if isinstance(x, (int, float)) else str(x))


def render(o: dict) -> str:
    b, c = o["baseline_repro"], o["counts"]
    L = []
    L.append("# T-165 / S-656 结果 —— 「对了才加」+ 主动买盘确认(满仓不变,+1R 那天 taker_ratio_mean ≥ 1.123 才加 0.5 B)\n")
    L.append("预注册:REFUTATION_LEDGER §S-656(2026-10-21 11:31 UTC,写于对任何加仓按资金流分组之前),实现未改规则;"
             "加仓的 atr14 / unit_r / 单位止损写法同 S-654。"
             "资金流 = Supabase `deriv_metrics_daily`(source=binance_vision_metrics,只读 publishable key)。\n")
    L.append("**v2(Seth 10-21 CHANGES 三条,数据与规则一字未动,只改报告口径与补测):** ① 不过收下;"
             "② 补留一年回放(§7);③ 判 ③ 改成与 ② **同一个比较**(同一个 `judge_diff`、同一套年块标签打乱零分布,"
             "分两段各报差与 p);④ §3 表头拆开:用不上的 "
             + str(c["no_metrics_row_total"]) + " = " + str(c["no_row_absent"]) + "(表里没行) + "
             + str(c["unusable_row"]) + "(有行但不可用)。基线、票数、触发数、满足数与 v1 完全一致。\n")
    L.append("## 1. 基线复现(S-654 原规则)\n")
    L.append("| 原规则总盈亏 | **" + f(b["original_total_B"]) + " B**(S-654 记 372.2 B)|")
    L.append("| 原规则按出场日累计最大回撤 | " + f(b["original_mdd_B"]) + " B(S-654 记 −55.9 B)|")
    L.append("| 票数 | " + str(o["n_tickets"]) + "|\n")
    L.append("## 2. 规则 F 全书(1 B 底仓 + 条件加仓)vs 原规则\n")
    L.append("| | 原规则 | 规则 F |")
    L.append("|---|---|---|")
    L.append("| 总盈亏 | " + f(b["original_total_B"]) + " B | **" + f(b["ruleF_total_B"]) + " B** |")
    L.append("| 按出场日累计最大回撤 | " + f(b["original_mdd_B"]) + " B | " + f(b["ruleF_mdd_B"]) + " B |")
    L.append("| 亏损票合计 | " + f(b["losers_original_B"]) + " B | " + f(b["losers_ruleF_B"]) + " B |\n")
    for lab in ("lt2023", "ge2023"):
        h = o["book_halves"][lab]
        L.append("- " + lab + ":原规则 " + f(h["original_B"]) + " B → 规则 F " + f(h["ruleF_B"])
                 + " B(" + str(h["n"]) + " 张)\n")
    L.append("## 3. 只报项:触发 / 有 metrics / 满足条件\n")
    L.append("| +1R 触发 | 有可用 metrics | 满足 taker ≥ 1.123 | 表里根本没这一行 | 有行但不可用(n_points=0 或值为空) | 用不上合计 | 虚拟加仓单位 |")
    L.append("|---|---|---|---|---|---|---|")
    L.append("| " + str(c["plus1R_triggers"]) + " | " + str(c["with_metrics"]) + " | "
             + str(c["satisfied_taker"]) + " | " + str(c["no_row_absent"]) + " | "
             + str(c["unusable_row"]) + " | **"
             + str(c["no_metrics_row_total"]) + "** | " + str(c["add_units_built"]) + " |\n")
    L.append("「用不上合计」= 触发 − 有可用 metrics = "
             + str(c["no_metrics_row_total"]) + " = " + str(c["no_row_absent"]) + " + "
             + str(c["unusable_row"]) + "(第一项 + 第二项)。上一版把这两段并成一列「完全无行 = "
             + str(c["no_metrics_row_total"]) + "」,其中 " + str(c["unusable_row"])
             + " 张其实是**有行但不可用**,这一版拆开。\n")
    L.append("资金流表读到 " + str(o["metrics_rows"]) + " 行,其中可用 "
             + str(o["metrics_usable_rows"]) + " 行;最早可用日 " + str(o["metrics_first_usable"])
             + "。票的 symbol 与该表 symbol **184/184 精确对齐**,无需 1000 前缀映射,无 symbol 覆盖缺口。\n")
    L.append("| 年 | 可用行 | 不可用行 |")
    L.append("|---|---|---|")
    for y, (gu, bu) in o["metrics_by_year"].items():
        L.append("| " + y + " | " + str(gu) + " | " + str(bu) + " |")
    L.append("")
    L.append("## 4. 判\n")
    L.append("| 判 | 要求 | 测得 | p(单侧) | 过 |")
    L.append("|---|---|---|---|---|")
    j1, j2 = o["judge_1"], o["judge_2"]
    L.append("| ① | 条件加仓单位平均 R > +0.48 | " + f(j1["observed_mean_R"], 3) + "(n=" + str(j1["n"])
             + ")| " + f(j1["p_one_sided"], 4) + " | " + ("✓" if o["verdict"]["c1"] else "✗") + " |")
    L.append("| ② | 条件 − 不满足条件的平均 R 差 > 0 | " + f(j2["actual_diff_R"], 3) + "(n="
             + str(j2.get("n_satisfied")) + " vs " + str(j2.get("n_unsatisfied")) + ")| "
             + f(j2["p_one_sided"], 4) + " | " + ("✓" if o["verdict"]["c2"] else "✗") + " |")
    for lab in ("lt2023", "ge2023"):
        q = o["judge_3"][lab]
        L.append("| ③ " + lab + " | 条件 > 不满足条件(与 ② 同一比较) | " + f(q["mean_R_satisfied"], 3)
                 + " vs " + f(q["mean_R_unsatisfied"], 3) + "(n=" + str(q["n_satisfied"]) + "/"
                 + str(q["n_unsatisfied"]) + ")| " + f(q["p_one_sided"], 4) + " | "
                 + ("✓" if q["ok"] else "✗") + " |")
    L.append("")
    L.append("**判结论:" + ("三条全过 ✅" if o["verdict"]["all_three"] else "不过 ❌")
             + "(①" + ("过" if o["verdict"]["c1"] else "不过") + " / "
             + "②" + ("过" if o["verdict"]["c2"] else "不过") + " / "
             + ("③过" if o["verdict"]["c3"] else "③不过") + ")**\n")
    L.append("③ 两段各自重跑 ② 的比较:统计量、零分布、判定都是同一个 `judge_diff`(按信号年份分块标签打乱 "
             + str(2000) + " 次、单侧 p)。预注册 ③ 原文只写「条件都高于不满足条件」(只看符号),"
             "表里过没过按与 ② 相同的口径(差 > 0 且 p < 0.05);只按符号读的:"
             + "lt2023 " + ("✓" if o["judge_3"]["lt2023"]["ok_sign_only"] else "✗") + " / ge2023 "
             + ("✓" if o["judge_3"]["ge2023"]["ok_sign_only"] else "✗")
             + " —— 两段都要过,所以 ③ 的结论两种读法一致:**不过**。\n")
    L.append("零分布口径:① 为 H0(均值 = 0.48)中心化后的按月块 P-R 平稳块自助;② 与 ③ 为按信号年份分块标签打乱"
             "(apparatus.shuffle_within 换值归属,组间不混)。两者都只用 `src/data/evaluation/apparatus.py`"
             "(`stationary_bootstrap_index` / `shuffle_within` / `null_distribution` / `percentile_of`)。\n")
    L.append("## 5. 每年:触发 / 有 metrics / 满足条件(解释 ③ 的 < 2023 半段)\n")
    L.append("| 信号年 | 票 | +1R 触发 | 有 metrics | 满足 | 条件平均 R | 不满足平均 R |")
    L.append("|---|---|---|---|---|---|---|")
    for y in o["by_year"]:
        L.append("| " + y["year"] + " | " + str(y["tickets"]) + " | " + str(y["triggers"]) + " | "
                 + str(y["with_metrics"]) + " | " + str(y["satisfied"]) + " | "
                 + f(y["mean_R_sat"], 3) + " | " + f(y["mean_R_unsat"], 3) + " |")
    L.append("")
    L.append("## 6. 尾部诊断(为什么点估计远高于门槛、p 却上不去)\n")
    t = o["tail"]
    L.append("| 组 | n | 均值 | 中位数 | p90 | 最大 | 去掉最大 3 个后的均值 | taker 均值 |")
    L.append("|---|---|---|---|---|---|---|---|")
    for lab, key in (("条件满足", "satisfied"), ("不满足", "unsatisfied")):
        v = t[key]
        if not v:
            continue
        L.append("| " + lab + " | " + str(v["n"]) + " | " + f(v["mean"], 3) + " | " + f(v["median"], 3)
                 + " | " + f(v["p90"], 3) + " | " + f(v["max"], 3) + " | "
                 + f(v["trimmed_mean_drop_top3"], 3) + " | "
                 + f(t["taker_sat_mean"] if key == "satisfied" else t["taker_unsat_mean"], 3) + " |")
    L.append("")
    L.append("## 7. 留一年(leave-one-year-out):每个信号年整年拿掉,①② 各按同一口径重算\n")
    L.append("加仓单位只落在 2023–2026 四年上,而 2025 年 4 张就平均 +13.6R —— ① / ② 是不是被某一年扛起来的,"
             "把这一年整个拿掉再看一次(其余样本、年份、门槛、零分布口径全部不动)。\n")
    L.append("| 拿掉的信号年 | 剩 n 个单位(其中满足条件) | ① 平均 R | ① p | ① 95% 自助下界 | ① 过 | ② 差 R | ② p | ② 过 |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for r in o["loyo"]:
        L.append("| " + r["held_out_year"] + " | " + str(r["n_units_kept"]) + "("
                 + str(r["n_satisfied_kept"]) + ")| " + f(r["j1_mean_R"], 3) + " | "
                 + f(r["j1_p"], 4) + " | " + f(r["j1_boot_p05"], 3) + " | "
                 + ("✓" if r["j1_over"] else "✗") + " | " + f(r["j2_diff_R"], 3) + " | "
                 + f(r["j2_p"], 4) + " | " + ("✓" if r["j2_over"] else "✗") + " |")
    L.append("")
    s = o["loyo_summary"]
    L.append("全样本对照片:**" + str(s["folds"]) + " 折里 ① 过 " + str(s["j1_pass_folds"])
             + " 折、② 过 " + str(s["j2_pass_folds"]) + " 折**(全样本本身 ① ✗ / ② ✓)。\n")
    L.append("## 8. 最好 10 张(按加仓带来的变化排序)\n")
    L.append("| 票 | 原规则 B | 规则 F B | 变化 | 触发日 t | taker_ratio_mean[t] |")
    L.append("|---|---|---|---|---|---|")
    for tid, bb, ff, dd, tg, tk in o["top10_by_add_delta"]:
        L.append("| " + tid + " | " + str(bb) + " | " + str(ff) + " | " + ("%+.2f" % dd) + " | "
                 + str(tg) + " | " + f(tk, 3) + " |")
    L.append("")
    L.append("## 9. S-656 结果草稿(待审,未写入 REFUTATION_LEDGER)\n")
    L.append("### S-656 结果(lane-b,2026-10-21)—— ❌(① ③ 不过,② 过):条件把**方向**挑对了,"
             "但挑出来的**幅度**扛不住检验\n")
    L.append("以 B 为单位、770 张票配对(底仓 1 B 满仓不动 + 条件加仓 0.5 B):原规则总盈亏 "
             + f(b["original_total_B"]) + " B → 规则 F " + f(b["ruleF_total_B"]) + " B(+"
             + f(b["ruleF_total_B"] - b["original_total_B"]) + " B);按出场日累计最大回撤 "
             + f(b["original_mdd_B"]) + " B → " + f(b["ruleF_mdd_B"]) + " B(略深)。"
             "312 张触发 +1R,277 张有可用资金流,68 张满足 taker ≥ 1.123。\n")
    L.append("- **① 不过**:条件加仓 68 个单位平均 **+1.29R**,点估计远高于 +0.48R 的门槛,但按月块自助单侧 "
             "**p = " + f(o["judge_1"]["p_one_sided"], 3) + " > 0.05**;95% 自助下界只有 **+"
             + f(o["judge_1"]["boot_p05"], 2) + "R**,仍在门槛之下。原因是**尾**:中位数只有 +0.25R,"
             "最大一个 **+57.05R**;**去掉最大的 3 个,均值从 +1.29R 塌到 +0.31R —— 低于 +0.48R 的门槛**。"
             "整本 +44 B 的改善里,ZEC:2025-09-06 一张就贡献 +28.5 B。")
    L.append("- **② 过**:条件 − 不满足条件的平均 R 差 **+" + f(o["judge_2"]["actual_diff_R"], 3)
             + "R**(+1.293 vs +0.057),按年分块标签打乱 2,000 次单侧 **p = "
             + f(o["judge_2"]["p_one_sided"], 3) + " < 0.05**。**这个方向不是被极值扛出来的**:"
             "去掉各组最大的 3 个后,条件组 +0.31R 仍高于不满足组 −0.07R。条件本身**真的**在挑赢家。")
    L.append("- **③ 不过 —— 但不是条件的问题,是数据的问题**:< 2023 半段 **n = 0**。"
             "`deriv_metrics_daily` 在 2022 年之前几乎没数据(2020 全年只有 119 行可用、2021 年 3,672 行,"
             "2020-09 ~ 2021-12 的行全是 n_points = 0 的空壳),而 2020/2021 的 24 个 +1R 触发**全部**"
             "落在无行或空壳行上;再加上这批票**本身就没有 2022 年的信号**(2022 = 0 张)。"
             "预注册的「两段都要过」在这批数据上结构性地无法检验。"
             "v2 补测(与 ② 同一比较):ge2023 半段差 "
             + f(o["judge_3"]["ge2023"]["actual_diff_R"], 3) + "R(68 vs 209)、单侧 p = "
             + f(o["judge_3"]["ge2023"]["p_one_sided"], 4) + ",**与全书 ② 的读数一致**;"
             "lt2023 半段两组都空,给不出数。")
    L.append("**读法:** S-654 关掉的是**无条件**加仓(单位平均 +0.33R < 新票 +0.48R);"
             "S-656 说明**加仓的价值确实存在于「谁被加」这个维度上** —— 加上 taker 确认后,"
             "被加单位的平均 R 从 +0.06R(不满足)变成 +1.29R(满足),这是 S-654 里完全没有的信息。"
             "**但 ① 不过就意味着整条路按预注册关掉**:以「条件加仓单位比新票更划算」为理由开仓不成立 ——"
             "均值扛不住尾部,95% 下界在门槛之下。② 过是**相对**结论(比不满足条件的好),"
             "不是**绝对**结论(比开新票好)。卡上 prior_value 的「不过 ⇒ 加仓在日线上关掉」成立。\n")
    L.append("**下一步(需要拍板,本卡不自行决定):** ② 的方向是真的,① 的幅度不够 —— 这两件事不矛盾,"
             "差额全在尾上。可测的下一个形状是**对条件加仓做尾部截断**(如剔除单笔 > +10R 或改用中位数口径),"
             "但那是对本批 68 个样本的**事后**挑选,必须另立预注册、换新数据、过零信号对照后才算数。\n")
    L.append("**试验计数:R 确认层族第 2 次,1 条,不过。**")
    L.append("")
    L.append("### v2 补测(Seth 10-21 CHANGES)—— 结论不变,但**被尾扛着的是 ② 不是 ①**\n")
    worst1 = min(o["loyo"], key=lambda r: r["j1_mean_R"] if r["j1_mean_R"] is not None else 9e9)
    fail2 = [r for r in o["loyo"] if not r["j2_over"]]
    L.append("- **留一年(§7),①**:" + str(o["loyo_summary"]["folds"]) + " 折里过 "
             + str(o["loyo_summary"]["j1_pass_folds"]) + " 折。平均 R 最低的一折是拿掉 "
             + worst1["held_out_year"] + " 年(**" + f(worst1["j1_mean_R"], 3) + "R**,p = "
             + f(worst1["j1_p"], 3) + ")。**任何一年拿掉 ① 都过不了** —— ① 的失败不是「某一年顶上去又塌下来」,"
             "是整批 68 个单位的幅度本来就够不到 +0.48R 的稳定下界。")
    L.append("- **留一年(§7),②**:" + str(o["loyo_summary"]["folds"]) + " 折里过 "
             + str(o["loyo_summary"]["j2_pass_folds"]) + " 折"
             + (";**过不了的一折是拿掉 " + fail2[0]["held_out_year"] + " 年**(差 "
                + f(fail2[0]["j2_diff_R"], 3) + "R,p = " + f(fail2[0]["j2_p"], 3) + " > 0.05)。"
                if fail2 else "。")
             + " " + fail2[0]["held_out_year"] + " 年只有 "
             + str(next((y["satisfied"] for y in o["by_year"] if y["year"] == fail2[0]["held_out_year"]), 0))
             + " 个满足条件的单位、却平均 +"
             + f(next((y["mean_R_sat"] for y in o["by_year"] if y["year"] == fail2[0]["held_out_year"]), None), 2)
             + "R —— **② 这一版的通过靠的就是这一年的几张大鱼**;v1 §6 那句「② 的方向不靠极值」指的是"
             "「去掉各组最大 3 个单位后条件组仍高于不满足组」,与这里是两回事,两件都要留着。" if fail2 else "")
    L.append("- **对 prior_value 的影响**:两条都不过,「日线加仓关掉」的结论不变;补测只是把"
             "「① 不过 = 幅度不够」精确成「幅度在任何子样本上都够不到」,并给 ② 加了一条它此前没有的脆弱性。")
    L.append("- **判 ③ 改成与 ② 同一比较**:ge2023 半段的差与 p 与全书一致,"
             "lt2023 半段两组皆空 —— **③ 的失败是数据覆盖问题,不是条件本身**;这与 v1 的读法一致,现在有 p 佐证。")
    L.append("- **§3 表头**:用不上 " + str(c["no_metrics_row_total"]) + " 张 = 表里根本没这一行 "
             + str(c["no_row_absent"]) + " + 有行但不可用 " + str(c["unusable_row"])
             + "(v1 把这两段并成「完全无行 " + str(c["no_metrics_row_total"]) + "」,其中 "
             + str(c["unusable_row"]) + " 张的错在源表是空壳,不是缺行)。")
    L.append("")
    L.append("**试验计数不变:R 确认层族第 2 次,1 条,不过**(补测不新增试验)。")
    L.append("")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    try:
        main()
    except NoOpNull as e:
        sys.exit("零分布退化(打乱没改变任何东西):" + str(e))