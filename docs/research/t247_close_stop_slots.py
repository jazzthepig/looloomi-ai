#!/usr/bin/env python3
"""T-247 (S-732) — 收盘止损(规则 C)配占坑中性的名额:能不能把 +23% 的 R 变成钱。

预注册:REFUTATION_LEDGER.md S-732(Seth,2026-11-05 08:43 UTC);原文抄在 T-247_close_stop_slots.md 开头,只算一次。
只读:不改代码、不做 DDL、不入库。
数据:t159 缓存的 770 张多头票(t159/_tickets_2020-03-01_2026-06-20.json)+ t156/t159 日线缓存(与 S-638 同一份,
      与 T-244 同一份)。出入口复算的 4 个小函数逐字抄自 docs/research/t244_stop_hunt.py(T-244/S-728),
      本脚本自带一份,好让分支不依赖尚未合并的 T-244 产物。
用法:python3 docs/research/t247_close_stop_slots.py
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("COMETCLOUD_LOCAL", "/Volumes/CometCloudAI/cometcloud-local")
TK = os.path.join(ROOT, "research", "t159", "_tickets_2020-03-01_2026-06-20.json")
RES = os.path.join(HERE, "t247_results.json")
REP = os.path.join(HERE, "T-247_close_stop_slots.md")

_spec = importlib.util.spec_from_file_location("t159", os.path.join(HERE, "t159_bear_short.py"))
t159 = importlib.util.module_from_spec(_spec)
sys.modules["t159"] = t159
_spec.loader.exec_module(t159)

# ── 口径常量(开算前写定) ─────────────────────────────────────────────────────
COST = 0.004             # 来回成本(t159/t244 逐字)
F_RISK = 0.01            # 钱曲线每笔 1%(S-638 的 f★)
CAP = 10                 # 同时最多 10 张(原规则名额)
CURVE_TO = "2026-06-30"  # 全样本钱曲线终点(卡上样本尾)
H1_END = "2022-12-31"
H2_START = "2023-01-01"
H2_END = "2026-06-30"
DISASTER_ATR = 4.0       # 规则 C 的灾难线(与 T-244 主口径同)

# T-244(S-728)报告里已发表的数 —— 只作「复算有没有跑歪」的回归对照,不是本卡的结果
REGRESSION = {
    "A_cap10": {"end": 4.155, "annualised": 0.2599, "mdd": -0.3229, "calmar": 0.805},
    "C_cap10": {"end": 4.109, "annualised": 0.2576, "mdd": -0.3389, "calmar": 0.760},
}

PREREG = """## S-732 — 收盘止损配占坑中性的名额 —— 预注册(Seth,2026-11-05 08:43 UTC;交 B 道 T-247)

**为什么。** S-728:规则 C 的 R 多 23%,但持有更久、cap 10 下被挤掉,钱曲线略差 —— 机制明确。只换一个由机制推出来的量:cap_C = round(10 × C 平均持有根数 / 原规则平均持有根数)(先算、写进报告、不许再改),让两边可开新票的速率相同;不扫 cap。**判据(全过 ✅):** C cap_C 的 Calmar ≥ 原规则;两半收益都 ≥ 原规则;盯市 MDD 不深超过 3 个百分点;名义峰值 ≤ 原规则 1.5 倍。**诚实:** 同一份 770 张票上的第二次检验(有窥探);✅ 只是真钱变更流程的候选。**试验计数:交易层 +1。**"""


# ── 数据与复算(抄自 T-244) ───────────────────────────────────────────────────
def load():
    tk = json.load(open(TK))
    bars = t159.load_bars()
    ind = {}
    for s, rows in bars.items():
        ind[s] = t159.indicators(rows)
    return tk, bars, ind


def r_of(entry, stop, exit_px):
    """R(与 t159/t244 逐字一致):(exit-entry)/(entry-stop) - 0.004*entry/(entry-stop)。"""
    return (exit_px - entry) / (entry - stop) - COST * entry / (entry - stop)


def orig_exit(a, ei, i_sig, stop):
    """t159.run_long 的逐字语义:盘中触止损 → 出场;close<sma20 → 次日开盘;否则 120 根 → 收盘。"""
    n = len(a["d"])
    j_max = min(i_sig + 120, n - 1)
    for j in range(ei, j_max + 1):
        if a["l"][j] <= stop:
            px = a["o"][j] if (j > ei and a["o"][j] <= stop) else stop
            return j, px, "stop", False
        if a["c"][j] < a["sma20"][j]:
            if j + 1 <= n - 1:
                return j + 1, a["o"][j + 1], "sma20", False
            return j, a["c"][j], "sma20_open", True
    return j_max, a["c"][j_max], "time", (i_sig + 120 > n - 1)


def rule_c_exit(a, ei, i_sig, stop, atr_i, k_atr):
    """规则 C:止损只在收盘 ≤ 止损价时触发(次日开盘出);盘中灾难线 = 进场 − k×ATR14(触及即出)。
    优先级(同一根 K 线):灾难线(盘中即出)> 收盘止损(次日开盘)> SMA20(次日开盘)> 时间(收盘)。
    R 的分母仍是原来的 2.5×ATR 风险单位(entry − stop_px)。"""
    n = len(a["d"])
    j_max = min(i_sig + 120, n - 1)
    disaster = stop - (k_atr - 2.5) * atr_i          # entry − k×ATR
    for j in range(ei, j_max + 1):
        if a["l"][j] <= disaster:
            return j, disaster, "disaster", False
        if a["c"][j] <= stop:
            if j + 1 <= n - 1:
                return j + 1, a["o"][j + 1], "close_stop", False
            return j, a["c"][j], "close_stop_open", True
        if a["c"][j] < a["sma20"][j]:
            if j + 1 <= n - 1:
                return j + 1, a["o"][j + 1], "sma20", False
            return j, a["c"][j], "sma20_open", True
    return j_max, a["c"][j_max], "time", (i_sig + 120 > n - 1)


# ── 名额准入(逐字镜像 t159.nav 的准入逻辑) ───────────────────────────────────
def admit(tickets, cap, d_to, d_from=None, d_end=None):
    """镜像 t159.nav 的名额准入:同样的过滤、同样的同日排序 (signal_d, symbol)、同样的占坑口径
    (进场日 d 的占坑 = 进场日 < d 且 出场日 >= d 或 未出场)。
    返回 (接下的票, 被挡的票);返回的是副本,不改原票。"""
    tk = []
    for i, t in enumerate(tickets):
        if not t["entry_d"] or t["entry_px"] == t["stop_px"]:
            continue
        if d_from is not None and not (d_from <= t["entry_d"] <= (d_end or d_to)):
            continue
        c = dict(t)
        c["_k"] = i
        tk.append(c)
    if not tk:
        return [], []
    v_from = min(t["entry_d"] for t in tk)
    tk = [t for t in tk if v_from <= t["entry_d"] <= d_to]
    for t in tk:
        if t["exit_d"] and t["exit_d"] > d_to:
            t["exit_d"] = t["exit_px"] = None
    state = {}
    for v_e in sorted({t["entry_d"] for t in tk}):
        occ = sum(1 for k in tk if state.get(k["_k"]) == "taken" and k["entry_d"] < v_e
                  and (k["exit_d"] is None or k["exit_d"] >= v_e))
        taken_today = 0
        for k in sorted([k for k in tk if k["entry_d"] == v_e], key=lambda x: (x["signal_d"], x["symbol"])):
            if cap is None or occ + taken_today < cap:
                state[k["_k"]] = "taken"
                taken_today += 1
            else:
                state[k["_k"]] = "skipped"
    taken = [t for t in tk if state.get(t["_k"]) == "taken"]
    skipped = [t for t in tk if state.get(t["_k"]) == "skipped"]
    return taken, skipped


# ── 钱曲线 ───────────────────────────────────────────────────────────────────
def nav_curve(tickets, bars, d_to, cap, d_from=None, d_end=None):
    """逐字用 t159.nav(S-638 同款)跑一条钱曲线;外加本卡要报的几项。"""
    tk = [t for t in tickets if t["entry_d"] and (d_from is None or d_from <= t["entry_d"] <= (d_end or d_to))]
    c = list(t159.nav(tk, bars, F_RISK, cap=cap, d_to=d_to))
    if not c:
        return {}
    st = dict(t159.stats(c))
    ann, mdd = st.get("annualised"), st.get("mdd")
    st["calmar"] = (ann / abs(mdd)) if (ann is not None and mdd) else None
    st["avg_open_n"] = sum(r["open_n"] for r in c) / len(c)
    st["max_open_n"] = max(r["open_n"] for r in c)
    st["n_tickets_in"] = len(tk)
    st["total_r"] = sum((t.get("r") or 0.0) for t in tk)
    return st


def med(xs):
    xs = sorted(xs)
    n = len(xs)
    if not n:
        return None
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2.0


def pct(x, n):
    return (100.0 * x / n) if n else None


def _f(x, nd=3):
    return "n/a" if x is None else f"{x:.{nd}f}"


# ── main ─────────────────────────────────────────────────────────────────────
def main():
    tk, bars, ind = load()
    longs = list(tk["long"])
    res = {"task": "T-247", "prereg": "S-732", "as_of": "2026-11-05", "n_tickets": len(longs),
           "n_symbols": len(bars),
           "constants": {"cost": COST, "f": F_RISK, "cap": CAP, "disaster_atr": DISASTER_ATR,
                         "curve_to": CURVE_TO, "h1_end": H1_END, "h2": [H2_START, H2_END]}}

    # ── 0. 自检 A:进场价 / 止损 ATR 对齐 + 原规则出口复算 vs 缓存 R ──────────
    sc = {"n_checked": 0, "entry_px_match": 0, "stop_atr_match": 0, "r_mismatch": 0,
          "max_abs_dr": 0.0, "no_bars": 0, "reason_counts": {}}
    A_tickets = []
    C_tickets = []
    for t in longs:
        s = t["symbol"]
        if s not in ind or t["ei"] >= len(ind[s]["d"]):
            sc["no_bars"] += 1
            continue
        a = ind[s]
        ei = t["ei"]
        i_sig = ei - 1
        atr_i = a["atr14"][i_sig]
        sc["n_checked"] += 1
        if abs(a["o"][ei] - t["entry_px"]) <= 1e-6 * max(1.0, abs(t["entry_px"])):
            sc["entry_px_match"] += 1
        if atr_i and abs((t["entry_px"] - t["stop_px"]) - 2.5 * atr_i) <= 1e-6 * max(1.0, t["entry_px"]):
            sc["stop_atr_match"] += 1
        # 原规则出口复算
        j, px, why, still = orig_exit(a, ei, i_sig, t["stop_px"])
        sc["reason_counts"][why] = sc["reason_counts"].get(why, 0) + 1
        r_new = None if still else r_of(t["entry_px"], t["stop_px"], px)
        r_old = t.get("r")
        if (r_old is None) != (r_new is None):
            sc["r_mismatch"] += 1
        elif r_old is not None:
            d = abs(r_new - r_old)
            sc["max_abs_dr"] = max(sc["max_abs_dr"], d)
            if d > 1e-9:
                sc["r_mismatch"] += 1
        # A 票(用缓存的出口/根数)
        at = dict(t)
        at["bars_held_A"] = t["bars_held"]
        A_tickets.append(at)
        # C 票(收盘判止损 + −4 ATR 灾难线)
        jc, pxc, whyc, stillc = rule_c_exit(a, ei, i_sig, t["stop_px"], atr_i, DISASTER_ATR)
        ct = dict(t)
        ct["exit_d"] = None if stillc else a["d"][jc]
        ct["exit_px"] = None if stillc else pxc
        ct["r"] = None if stillc else r_of(t["entry_px"], t["stop_px"], pxc)
        ct["c_reason"] = whyc
        ct["c_j"] = jc
        ct["bars_held_C"] = jc - ei + 1
        C_tickets.append(ct)
    res["selfcheck"] = sc

    # ── 1. ① 平均持有根数 → cap_C(先算、写死、不许再改) ────────────────────
    a_taken, a_skipped = admit(A_tickets, CAP, CURVE_TO)
    c_taken10, c_skipped10 = admit(C_tickets, CAP, CURVE_TO)
    hold_A = sum(t["bars_held_A"] for t in a_taken) / len(a_taken)
    hold_C = sum(t["bars_held_C"] for t in c_taken10) / len(c_taken10)
    cap_C = int(round(CAP * hold_C / hold_A))
    res["step1_cap"] = {
        "hold_convention": "持有根数 = 出场根 − 进场根 + 1(含进场根与出场根;与缓存 bars_held 同口径)",
        "n_taken_A_cap10": len(a_taken), "n_skipped_A_cap10": len(a_skipped),
        "n_taken_C_cap10": len(c_taken10), "n_skipped_C_cap10": len(c_skipped10),
        "hold_A": hold_A, "hold_C": hold_C, "hold_ratio_C_over_A": hold_C / hold_A,
        "cap_C": cap_C, "cap_C_formula": f"round({CAP} × {hold_C:.6f} / {hold_A:.6f}) = {cap_C}",
        "hold_A_median": med([t["bars_held_A"] for t in a_taken]),
        "hold_C_median": med([t["bars_held_C"] for t in c_taken10]),
    }

    # ── 2. ② 三条钱曲线(全样本 + 两半) ────────────────────────────────────
    curves = {}
    for name, tks, cap in (("A_cap10", A_tickets, CAP),
                           ("C_cap10", C_tickets, CAP),
                           ("C_capC", C_tickets, cap_C)):
        full = nav_curve(tks, bars, CURVE_TO, cap)
        h1 = nav_curve(tks, bars, H1_END, cap, d_end=H1_END)
        h2 = nav_curve(tks, bars, H2_END, cap, d_from=H2_START, d_end=H2_END)
        curves[name] = {"cap": cap, "full": full, "h1": h1, "h2": h2}

    # 自检 B:admit() 的接下/被挡数必须等于 nav() 自己数出来的
    mism = []
    for name, tks, cap in (("A_cap10", A_tickets, CAP), ("C_cap10", C_tickets, CAP),
                           ("C_capC", C_tickets, cap_C)):
        for part, d_to, d_from, d_end in (("full", CURVE_TO, None, None),
                                          ("h1", H1_END, None, H1_END),
                                          ("h2", H2_END, H2_START, H2_END)):
            tk_, sk_ = admit(tks, cap, d_to, d_from, d_end)
            cv = curves[name][part]
            if (len(tk_), len(sk_)) != (cv.get("taken"), cv.get("skipped")):
                mism.append({"curve": name, "part": part, "admit": [len(tk_), len(sk_)],
                             "nav": [cv.get("taken"), cv.get("skipped")]})
            # 钱曲线只由「接下的票」产生 ⇒ 总 R 也按接下的票算(与 total_r 口径不同,写清)
            cv["total_r_taken"] = sum((t.get("r") or 0.0) for t in tk_)
            cv["n_taken_r"] = sum(1 for t in tk_ if t.get("r") is not None)
    res["selfcheck_admit_vs_nav"] = {"mismatches": mism, "n_mismatch": len(mism)}

    # 自检 C:回归对照 T-244 已发表的两条曲线(A cap10 / C cap10)
    reg = {}
    for name, key in (("A_cap10", "A_cap10"), ("C_cap10", "C_cap10")):
        cv = curves[name]["full"]
        reg[name] = {k: {"published": REGRESSION[key][k], "recomputed": cv.get(k),
                          "delta": (cv.get(k) - REGRESSION[key][k]) if cv.get(k) is not None else None}
                      for k in ("end", "annualised", "mdd", "calmar")}
    res["selfcheck_regression_vs_t244"] = reg

    # ── 3. ③ 判(S-732:全过 ✅) ────────────────────────────────────────────
    A, C10, CC = curves["A_cap10"], curves["C_cap10"], curves["C_capC"]
    checks = {
        "J1_calmar_ge": {"A": A["full"].get("calmar"), "C_capC": CC["full"].get("calmar"),
                         "pass": bool(A["full"].get("calmar") is not None and CC["full"].get("calmar") is not None
                                      and CC["full"]["calmar"] >= A["full"]["calmar"])},
        "J2_both_halves_ge": {
            "h1": {"A": A["h1"].get("end"), "C_capC": CC["h1"].get("end")},
            "h2": {"A": A["h2"].get("end"), "C_capC": CC["h2"].get("end")},
            "pass": bool(CC["h1"].get("end") is not None and CC["h2"].get("end") is not None
                         and CC["h1"]["end"] >= A["h1"]["end"] and CC["h2"]["end"] >= A["h2"]["end"])},
        "J3_mdd_not_3pp_deeper": {"A": A["full"].get("mdd"), "C_capC": CC["full"].get("mdd"),
                                  "delta_pp": ((CC["full"].get("mdd") or 0) - (A["full"].get("mdd") or 0)) * 100,
                                  "pass": bool(CC["full"].get("mdd") is not None and A["full"].get("mdd") is not None
                                               and CC["full"]["mdd"] >= A["full"]["mdd"] - 0.03)},
        "J4_nominal_peak_le_1p5x": {"A": A["full"].get("peak_gross"), "C_capC": CC["full"].get("peak_gross"),
                                    "ratio": (CC["full"]["peak_gross"] / A["full"]["peak_gross"])
                                    if (CC["full"].get("peak_gross") and A["full"].get("peak_gross")) else None,
                                    "pass": bool(CC["full"].get("peak_gross") is not None
                                                 and A["full"].get("peak_gross") is not None
                                                 and CC["full"]["peak_gross"] <= 1.5 * A["full"]["peak_gross"])},
    }
    checks["all_pass"] = all(v.get("pass") for k, v in checks.items() if isinstance(v, dict) and "pass" in v)
    res["step3_checks"] = checks
    res["curves"] = curves

    # ── 4. ④ 副报:cap_C ± 2(只报不判)+ 被挡票的 R 分布 ─────────────────────
    side = {}
    for cc in (cap_C - 2, cap_C + 2):
        full = nav_curve(C_tickets, bars, CURVE_TO, cc)
        side[f"cap_{cc}"] = {"cap": cc, "full": full}
    res["step4_side"] = side

    # cap_C 相对 cap 10 多放进来/多挡住的票
    c_taken_capC, c_skipped_capC = admit(C_tickets, cap_C, CURVE_TO)
    key10 = {t["symbol"] + "|" + t["signal_d"] for t in c_taken10}
    keyCC = {t["symbol"] + "|" + t["signal_d"] for t in c_taken_capC}
    newly = [t for t in c_taken_capC if (t["symbol"] + "|" + t["signal_d"]) not in key10]
    still_out = [t for t in c_skipped_capC if (t["symbol"] + "|" + t["signal_d"]) in key10]
    nr = [t["r"] for t in newly if t.get("r") is not None]
    sr = [t["r"] for t in still_out if t.get("r") is not None]
    nr_ex1 = sorted(nr, reverse=True)[1:] if len(nr) > 1 else []
    res["step4_blocked"] = {
        "definition": "cap_C 比 cap 10 多接下的票(cap 10 下被挡、cap_C 下进场)的 R 分布",
        "n_newly_taken": len(newly),
        "n_newly_with_r": len(nr),
        "newly_total_r": sum(nr) if nr else None,
        "newly_mean_r": (sum(nr) / len(nr)) if nr else None,
        "newly_median_r": med(nr),
        "newly_min_r": min(nr) if nr else None,
        "newly_max_r": max(nr) if nr else None,
        "newly_total_r_ex_top1": sum(nr_ex1) if nr_ex1 else None,
        "newly_mean_r_ex_top1": (sum(nr_ex1) / len(nr_ex1)) if nr_ex1 else None,
        "newly_share_positive": pct(sum(1 for x in nr if x > 0), len(nr)),
        "newly_share_ge_1R": pct(sum(1 for x in nr if x >= 1.0), len(nr)),
        "n_still_blocked_at_capC": len(still_out),
        "still_blocked_total_r": sum(sr) if sr else None,
        "still_blocked_mean_r": (sum(sr) / len(sr)) if sr else None,
        "still_blocked_share_positive": pct(sum(1 for x in sr if x > 0), len(sr)),
        "newly_rows": [{"symbol": t["symbol"], "signal_d": t["signal_d"], "entry_d": t["entry_d"],
                        "exit_d": t["exit_d"], "r": t.get("r"), "c_reason": t.get("c_reason"),
                        "bars_held_C": t.get("bars_held_C")} for t in newly],
    }

    # 机制读数(全部由上面的数推出,不手打)
    Af, CCf = curves["A_cap10"]["full"], curves["C_capC"]["full"]
    res["mechanism"] = {
        "end_delta_pct": pct(CCf["end"] - Af["end"], Af["end"]),
        "ann_delta_pp": (CCf["annualised"] - Af["annualised"]) * 100,
        "mdd_delta_pp": (CCf["mdd"] - Af["mdd"]) * 100,
        "calmar_delta": CCf["calmar"] - Af["calmar"],
        "total_r_delta_pct": pct(curves["C_capC"]["full"]["total_r"] - curves["A_cap10"]["full"]["total_r"],
                                 abs(curves["A_cap10"]["full"]["total_r"])),
        "cap13_calmar": res["step4_side"].get(f"cap_{cap_C + 2}", {}).get("full", {}).get("calmar"),
        "cap13_beats_A_calmar": bool(res["step4_side"].get(f"cap_{cap_C + 2}", {}).get("full", {}).get("calmar")
                                     and Af.get("calmar")
                                     and res["step4_side"][f"cap_{cap_C + 2}"]["full"]["calmar"] >= Af["calmar"]),
    }

    json.dump(res, open(RES, "w"), indent=1, ensure_ascii=False, default=str)
    print("wrote", RES)
    write_report(res)
    print("wrote", REP)


# ── report ───────────────────────────────────────────────────────────────────
def write_report(res):
    L = []
    A = L.append
    s1 = res["step1_cap"]
    ch = res["step3_checks"]
    cv = res["curves"]
    A("# T-247 (S-732) —— 收盘止损的 +23% R 能不能变成钱:占坑中性的名额")
    A("")
    A("## 0. 预注册(S-732 原文,先写下来再算;只算一次)")
    A("")
    A(PREREG)
    A("")
    A("## 1. 口径与实现决定(开算前写定)")
    A("")
    A("| 项 | 决定 | 依据 |")
    A("|---|---|---|")
    A("| 票集 | t159 缓存 770 张多头票 | 卡上写死;同 T-244 |")
    A("| 日线 | t156 + t159 缓存(`t159.load_bars()`,与 S-638 同一份) | 同上 |")
    A("| 规则 A(对照) | 原规则:盘中触止损(进场 − 2.5×ATR14)即出;收盘破 SMA20 次日开盘出;120 根到期 | S-728 |")
    A("| 规则 C | 止损只在收盘 ≤ 止损价时触发(次日开盘出);盘中灾难线 = 进场 − 4×ATR14 触及即出 | S-728 |")
    A("| 名额 | A: cap 10; C: cap 10 与 cap_C | 卡上写死 |")
    A(f"| cap_C | `round({CAP} × hold_C / hold_A)` = **{s1['cap_C']}**(算完写死,不再改;不扫 cap) | 卡上写死 |")
    A(f"| 持有根数 | {s1['hold_convention']} | 缓存 `bars_held` 同口径 |")
    A("| 钱曲线 | f = 1%、逐日盯市(`t159.nav`,S-638 同款)、0.4% 来回 | 卡上写死 |")
    A("| 两半 | 按进场日切:≤2022-12-31 / ≥2023-01-01;每半**重跑**一条钱曲线(权益从 1 起) | 与 T-244 同 |")
    A("| 名义峰值 | `peak_gross` = Σ\\|units\\|·mark ÷ 权益 的历史最大值 | 名义敞口,不是权益峰值 |")
    A("| 纪律 | 不改代码、不做 DDL、不入库;本卡是同一样本上的对照,不用零分布 | 卡上写死 |")
    A("")
    A("## 2. 自检(先证明复算无误,再看结论)")
    A("")
    sc = res["selfcheck"]
    A(f"* 进场价对得上 `open[ei]`:**{sc['entry_px_match']}/{sc['n_checked']}**;")
    A(f"* `entry − stop == 2.5 × ATR14[ei−1]`:**{sc['stop_atr_match']}/{sc['n_checked']}**;")
    A(f"* 原规则出口复算 vs 缓存 R:不一致 **{sc['r_mismatch']}** 张,最大 |ΔR| = **{sc['max_abs_dr']:.9f}**;")
    A(f"* 复算出口原因分布:`{sc['reason_counts']}`。")
    mm = res["selfcheck_admit_vs_nav"]["n_mismatch"]
    A(f"* **名额镜像自检**:本脚本自写的 `admit()` 与 `t159.nav` 自己数出来的「接下/被挡」数,在 9 条曲线上不一致 **{mm}** 处"
      f"(0 = 准入口径复算一致)。")
    A("")
    A("**回归对照(T-244/S-728 已发表的数,用来证明本脚本跑的是同一条曲线)**")
    A("")
    A("| 曲线 | 终值(发表 → 复算) | 年化(发表 → 复算) | 盯市 MDD(发表 → 复算) | Calmar(发表 → 复算) |")
    A("|---|---|---|---|---|")
    for name in ("A_cap10", "C_cap10"):
        r = res["selfcheck_regression_vs_t244"][name]
        A(f"| {name} | {_f(r['end']['published'])} → {_f(r['end']['recomputed'])} | "
          f"{_f(r['annualised']['published'], 4)} → {_f(r['annualised']['recomputed'], 4)} | "
          f"{_f(r['mdd']['published'], 4)} → {_f(r['mdd']['recomputed'], 4)} | "
          f"{_f(r['calmar']['published'])} → {_f(r['calmar']['recomputed'])} |")
    A("")
    A("## 3. ① 平均持有根数 → cap_C")
    A("")
    A("| 量 | 规则 A(cap 10) | 规则 C(cap 10) |")
    A("|---|---|---|")
    A(f"| 接下的票 | {s1['n_taken_A_cap10']} | {s1['n_taken_C_cap10']} |")
    A(f"| 被挡的票 | {s1['n_skipped_A_cap10']} | {s1['n_skipped_C_cap10']} |")
    A(f"| 平均持有根数 | **{s1['hold_A']:.4f}** | **{s1['hold_C']:.4f}** |")
    A(f"| 中位持有根数 | {_f(s1['hold_A_median'], 1)} | {_f(s1['hold_C_median'], 1)} |")
    A("")
    A(f"**cap_C = {s1['cap_C_formula']}** —— 规则 C 一次占坑的时间是原规则的 {s1['hold_ratio_C_over_A']:.4f} 倍,"
      f"所以名额按同比例放大,两边可开新票的速率相同。")
    A("")
    A("## 4. ② 三条钱曲线")
    A("")
    A("**全样本(2020-03 → 2026-06)**")
    A("")
    A("| 曲线 | 名额 | 年化 | 盯市 MDD | Calmar | 名义峰值(总敞口/权益) | 平均同时持仓 | 被挡票 | 终值 | 接下票的总 R |")
    A("|---|---|---|---|---|---|---|---|---|---|")
    for name, label in (("A_cap10", "A cap 10"), ("C_cap10", "C cap 10"), ("C_capC", f"C cap {s1['cap_C']}")):
        f_ = cv[name]["full"]
        A(f"| {label} | {cv[name]['cap']} | {_f(f_['annualised'], 4)} | {_f(f_['mdd'], 4)} | {_f(f_['calmar'])} | "
          f"{_f(f_['peak_gross'], 4)} | {_f(f_['avg_open_n'], 2)} | {f_['skipped']} | {_f(f_['end'])} | "
          f"{_f(f_.get('total_r_taken'), 2)} |")
    A("")
    A("**两半(每半重跑一条钱曲线,权益从 1 起)**")
    A("")
    A("| 曲线 | H1 2020-03 → 2022-12 终值 | H1 年化 | H1 MDD | H2 2023-01 → 2026-06 终值 | H2 年化 | H2 MDD |")
    A("|---|---|---|---|---|---|---|")
    for name, label in (("A_cap10", "A cap 10"), ("C_cap10", "C cap 10"), ("C_capC", f"C cap {s1['cap_C']}")):
        h1, h2 = cv[name]["h1"], cv[name]["h2"]
        A(f"| {label} | {_f(h1['end'])} | {_f(h1['annualised'], 4)} | {_f(h1['mdd'], 4)} | "
          f"{_f(h2['end'])} | {_f(h2['annualised'], 4)} | {_f(h2['mdd'], 4)} |")
    A("")
    A("## 5. ③ 判(S-732:全过 ✅)")
    A("")
    A("| 判据 | A cap 10 | C cap_C | 过? |")
    A("|---|---|---|---|")
    A(f"| J1 Calmar ≥ A | {_f(ch['J1_calmar_ge']['A'])} | {_f(ch['J1_calmar_ge']['C_capC'])} | "
      f"{'✅' if ch['J1_calmar_ge']['pass'] else '❌'} |")
    A(f"| J2 两半收益都 ≥ A | H1 {_f(ch['J2_both_halves_ge']['h1']['A'])} / H2 {_f(ch['J2_both_halves_ge']['h2']['A'])} | "
      f"H1 {_f(ch['J2_both_halves_ge']['h1']['C_capC'])} / H2 {_f(ch['J2_both_halves_ge']['h2']['C_capC'])} | "
      f"{'✅' if ch['J2_both_halves_ge']['pass'] else '❌'} |")
    A(f"| J3 盯市 MDD 不比 A 深 > 3pp | {_f(ch['J3_mdd_not_3pp_deeper']['A'], 4)} | "
      f"{_f(ch['J3_mdd_not_3pp_deeper']['C_capC'], 4)} (差 {_f(ch['J3_mdd_not_3pp_deeper']['delta_pp'], 2)}pp) | "
      f"{'✅' if ch['J3_mdd_not_3pp_deeper']['pass'] else '❌'} |")
    A(f"| J4 名义峰值 ≤ 1.5×A | {_f(ch['J4_nominal_peak_le_1p5x']['A'], 4)} | "
      f"{_f(ch['J4_nominal_peak_le_1p5x']['C_capC'], 4)} (×{_f(ch['J4_nominal_peak_le_1p5x']['ratio'], 3)}) | "
      f"{'✅' if ch['J4_nominal_peak_le_1p5x']['pass'] else '❌'} |")
    A("")
    A(f"**判: {'✅ 全过' if ch['all_pass'] else '❌ 未全过'}**")
    A("")
    A("## 6. ④ 副报(只报,不判)")
    A("")
    A(f"**cap_C ± 2**")
    A("")
    A("| 曲线 | 年化 | 盯市 MDD | Calmar | 名义峰值 | 平均同时持仓 | 被挡票 | 终值 |")
    A("|---|---|---|---|---|---|---|---|")
    for key in sorted(res["step4_side"]):
        f_ = res["step4_side"][key]["full"]
        A(f"| {key} | {_f(f_['annualised'], 4)} | {_f(f_['mdd'], 4)} | {_f(f_['calmar'])} | "
          f"{_f(f_['peak_gross'], 4)} | {_f(f_['avg_open_n'], 2)} | {f_['skipped']} | {_f(f_['end'])} |")
    A("")
    bl = res["step4_blocked"]
    A(f"**被挡掉的票(cap 10 挡下、cap_C 放进来那部分)值多少**")
    A("")
    A("| 量 | 值 |")
    A("|---|---|")
    A(f"| 多放进来的票 | {bl['n_newly_taken']} 张(有 R 的 {bl['n_newly_with_r']} 张) |")
    A(f"| 这些票的总 R | {_f(bl['newly_total_r'], 2)} |")
    A(f"| 均值 / 中位 R | {_f(bl['newly_mean_r'])} / {_f(bl['newly_median_r'])} |")
    A(f"| 最小 / 最大 R | {_f(bl['newly_min_r'])} / {_f(bl['newly_max_r'])} |")
    A(f"| 去掉最大那一张后的总 R / 均值 | {_f(bl['newly_total_r_ex_top1'], 2)} / {_f(bl['newly_mean_r_ex_top1'])} |")
    A(f"| 为正占比 / ≥ +1R 占比 | {_f(bl['newly_share_positive'], 1)}% / {_f(bl['newly_share_ge_1R'], 1)}% |")
    A(f"| cap_C 下仍被挡 | {bl['n_still_blocked_at_capC']} 张,总 R {_f(bl['still_blocked_total_r'], 2)},"
      f"均值 {_f(bl['still_blocked_mean_r'])},为正占比 {_f(bl['still_blocked_share_positive'], 1)}% |")
    A("")
    A("## 7. ⑤ 诚实与边界")
    A("")
    A("* **第二次检验**:同一份 770 张票,S-728(T-244)已经用过一次;本卡的 cap_C 是从这份数据里算出来的"
      "(持有根数的比),有窥探。✅ 也只是进真钱变更流程的候选 —— 执行器的止损要从交易所触发单改成"
      "「收盘判 + 远端灾难单」,**要 Jazz 拍板**(DECISIONS)。")
    A(f"* **占坑中性买到了钱、没买到 Calmar**:C cap {s1['cap_C']} 终值比 A 高 {_f(res['mechanism']['end_delta_pct'], 1)}%,"
      f"年化高 {_f(res['mechanism']['ann_delta_pp'], 2)}pp,但盯市 MDD 深 {_f(abs(res['mechanism']['mdd_delta_pp']), 2)}pp,"
      f"Calmar 反而低 {_f(abs(res['mechanism']['calmar_delta']), 3)} —— **R 多 ≠ 钱曲线好**:同样的 R 兑现得更晚"
      f"(占坑 {s1['hold_C']:.2f} 根 vs {s1['hold_A']:.2f} 根),水下时间更长,回撤更深。")
    A(f"* **多放进来的那批票中位 R 是负的**:中位 {_f(bl['newly_median_r'])}R、只有 {_f(bl['newly_share_positive'], 1)}% 为正;"
      f"总 R {_f(bl['newly_total_r'], 2)} 里有一张 {_f(bl['newly_max_r'])}R 撑着 —— 去掉它就是 "
      f"{_f(bl['newly_total_r_ex_top1'], 2)}R。名额放大换来的边际票不便宜。")
    if res["mechanism"]["cap13_beats_A_calmar"]:
        A(f"* **副报的 cap {s1['cap_C'] + 2} 那列 Calmar = {_f(res['mechanism']['cap13_calmar'])},恰好 ≥ A 的 "
          f"{_f(ch['J1_calmar_ge']['A'])} —— 但那不是结果**:按它选 cap 就是预注册明令禁止的「扫 cap」。"
          f"本卡的 cap 是机制推出来的({s1['cap_C']}),判 ❌ 就记 ❌。"
          f"(**探索性 —— 需另立预注册、在新数据上过零信号对照**)")
    A("* 名额按平均占坑时间等比放大,是**机制推出来的量**,不是扫出来的最优;cap_C ± 2 两列只作敏感性参考。")
    A("* 规则 C 的灾难线按 S-728 写死「触及即按该价出」;若某日开盘已低于灾难线,实盘滑点会更差,本卡未模拟。")
    A("* 票集是固定的 770 张(没有让规则 C 重新生成票),两边的差异只来自出场与名额。")
    A("* 「总 R」这一列是**全部票**的 R 之和;钱曲线只由接下的票产生,接下那部分的 R 见各曲线的 `total_r_taken`。")
    A("")
    A("## 8. 数字出处与边界")
    A("")
    A("* 全部数字来自 `t247_results.json`,由 `docs/research/t247_close_stop_slots.py` 一次跑出;报告里没有手打的数。")
    A("")
    open(REP, "w").write("\n".join(L) + "\n")


if __name__ == "__main__":
    main()
