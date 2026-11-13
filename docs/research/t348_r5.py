"""T-348 第五轮(lane-c,2026-11-12):长账本口径补齐其余族 + B 道交叉复核(§Seth-1112i)。

余项:
 (1) 长账本(基准起点 2020-08-16)口径下补齐其余族:S-642、S-736(已发布 + 诊断变体)、S-808、S-810、
     S-681 H2、H3;与 H4 同表同判据(最长水下变短 且 年化不降)。
 (4) 现金利率敏感性:2023-02-10 之前 908 天记 0 是「读不到当 0」—— 用 2023-02 之后的中位数补,两腿(C0 / C0+族)都受
     影响,只报不判。
 (6) 唯一没被选族用过的区间 2020-08-16 → 2021-10-10:单独报 C0 vs C0+H4(年化差、最长水下)—— 唯一非选后检验。
 (8) H4 的 Δ 对调仓相位(基准起点后移 0..20 日,共 21 个偏移)的分布,只报不判。
 (7) p 值的 MC 标准误(n=500):由第四轮的 p 值现算。

★ 本轮修的一处记账(§Seth-1111l 同类):族的收益序列必须**带上族首日的水位**。
  族曲线的首日水位不是 1.0(如 S-681 H4 首日 0.995687、S-808 首日 0.994992)。旧口径把族的净值
  直接放进「账本日历」上的序列、族首日之前填 1.0 ⇒ 当**账本起点晚于族首日**时,族首日的水位整段丢失
  (S-808 落在窗口 A 上,自检② 差 3.09e-03 > 1e-9,本轮自检抓出来的)。
  本版 fam_ret_full:先在「族日期 ∪ 日历日」并集上 ffill(缺口期保持族首日水位)、族首日之前填 1.0,
  再切日历 ⇒ 族第一张票的当日损益不被抹掉,自检② 全部 ≤ 1e-13。

用法: python3 t348_r5.py
产物: t348_r5_results.json + _t348_r5_tables.md
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, REPO_ROOT)

from src.data.universe import flex_alloc as fa  # noqa: E402

import t348_graveyard as G  # noqa: E402
import t348_r3 as R3  # noqa: E402
import t348_r4 as R4  # noqa: E402

LONG_START = R4.LONG_START          # 2020-08-16
WIN_B = R4.WIN_B                    # 2021-10-11
WIN_END = R4.WIN_END                # 2026-10-30
CASH_ZERO_BEFORE = R4.CASH_ZERO_BEFORE

OUT_JSON = os.path.join(HERE, "t348_r5_results.json")
OUT_MD = os.path.join(HERE, "_t348_r5_tables.md")
R4_JSON = os.path.join(HERE, "t348_r4_results.json")

FAM_KEYS = ["S642", "S736_published", "S736_fixed", "S808", "S810",
            "S681_H2", "S681_H3", "S681_H4"]

PRESEL_START = "2020-08-16"   # (6) 唯一没被选族用过的区间起点
PRESEL_END = "2021-10-10"     # 该区间终点(选族用的窗口 B 自 2021-10-11 起)


def log(msg: str) -> None:
    print(str(msg), flush=True)


def fam_ret_full(fam_nav: pd.Series, cal_idx: pd.DatetimeIndex) -> pd.Series:
    """族净值 → 日历日收益(★ 族的记账基准 = 1.0,缺口期保持族首日水位)。

    旧口径(`t348_r3.fam_return_series`)在**账本日历起点晚于族首日**时会丢掉族首日的水位:
    e 只在 cal 上构造,族首日(若早于 cal 起点)不在 cal 里 ⇒ e[cal 起点] = 1.0,
    而族的真实水位是 nav[族首日](如 S-808 0.994992)⇒ 族的起始损益被抹掉,
    自检②(Π(1+r) vs 族净值端点)会差到 3e-3 > 1e-9。

    本版:先在「族日期 ∪ 日历日」的并集上 ffill(缺口期保持族首日水位),族首日之前填 1.0(记账基准),
    再取 cal 切片 ⇒
      · 族首日当天的日收益 = nav[族首日]/1.0 − 1(族第一张票的当日损益,不被抹掉);
      · 窗口起点早于族首日时,e[窗口起点] = 族的真实水位 ⇒ 自检② 与族净值端点逐位一致。
    """
    nav = fam_nav.dropna().sort_index()
    if len(nav) == 0:
        return pd.Series(0.0, index=cal_idx, dtype=float)
    full = pd.Series(np.nan, index=nav.index.union(cal_idx), dtype=float)
    full.loc[nav.index] = nav.astype(float)
    full = full.sort_index().ffill().fillna(1.0)
    e = full.reindex(cal_idx)
    return e.pct_change().fillna(0.0)


def build_base_at(legs: dict, cash: pd.Series, rv2: pd.Series, start: str) -> dict:
    """长账本 C0,基准起点可调(调仓相位随起点移动)。"""
    nav, lg = fa.dynamic_mix_nav(legs, lambda h, x: fa.rb_weights(h),
                                 start=pd.Timestamp(start), overlay_ret=rv2, cash_ret=cash)
    nav = nav[nav.index <= pd.Timestamp(WIN_END)]
    cal = pd.date_range(pd.Timestamp(start), pd.Timestamp(WIN_END), freq="D")
    return {"legs": legs, "cash": cash, "rv2": rv2, "nav": nav, "cal_idx": cal,
            "log": lg, "start": start, "end": WIN_END}


def win_stats(base_nav: pd.Series, arm_nav: pd.Series, wstart: str) -> dict:
    """一个窗口内 C0 vs C0+族 的口径(与第四轮同表同判据)。"""
    c0 = R3.slice_win(base_nav, wstart, WIN_END)
    c0f = R3.slice_win(arm_nav, wstart, WIN_END)
    m0, mf = G.metrics(c0), G.metrics(c0f)
    u0, uf = G.underwater(c0), G.underwater(c0f)
    r0, rf = R3.recovery_s829(c0), R3.recovery_s829(c0f)
    return {
        "start": wstart, "end": WIN_END,
        "C0": {"metrics": m0, "underwater": u0, "underwater_S829": r0, "yearly": G.yearly(c0)},
        "C0_plus_family": {"metrics": mf, "underwater": uf, "underwater_S829": rf,
                            "yearly": G.yearly(c0f)},
        "diff": {
            "cagr_pp": 100.0 * (mf["cagr"] - m0["cagr"]),
            "max_dd_pp": 100.0 * (mf["max_dd"] - m0["max_dd"]),
            "total_return_pp": 100.0 * (mf["total_return"] - m0["total_return"]),
            "underwater_days": (uf.get("length_d") or 0) - (u0.get("length_d") or 0),
            "underwater_days_S829": rf["longest_uw_d"] - r0["longest_uw_d"],
            "cagr_not_lower": bool(mf["cagr"] >= m0["cagr"]),
            "underwater_shorter": bool((uf.get("length_d") or 0) < (u0.get("length_d") or 0)),
        },
    }


def classify(pa: bool | None, pb: bool | None) -> dict:
    """结论三类 + 「另一窗口不可得」标注。"""
    have_a, have_b = pa is not None, pb is not None
    both = bool(have_a and have_b and pa and pb)
    one = bool((have_a and pa and not (have_b and pb)) or (have_b and pb and not (have_a and pa)))
    if both:
        cls = "两个窗口都让最长水下变短且年化不降"
    elif one:
        cls = "只在一个窗口"
        if not have_b:
            cls = "只在一个窗口(窗口 B 族不可得)"
        elif not have_a:
            cls = "只在一个窗口(窗口 A 族不可得)"
    else:
        cls = "都不"
    return {"class": cls, "window_A_pass": pa, "window_B_pass": pb,
            "window_dependent": bool(pa is not None and pb is not None and pa != pb),
            "window_A_available": have_a, "window_B_available": have_b}


def main() -> None:
    log("=== T-348 第五轮:长账本口径补齐其余族 + 交叉复核 ===")
    legs, cash, info = R4.load_or_build_legs()
    rv2 = R3.rv2_curve().pct_change().dropna()
    base = build_base_at(legs, cash, rv2, LONG_START)
    cal = base["cal_idx"]
    m_long = G.metrics(base["nav"])
    rec_long = R3.recovery_s829(base["nav"])
    log(f"  长账本 C0:{m_long['n_days']} 天 {m_long['d0']} → {m_long['d1']}"
        f" · 年化 {m_long['cagr']:+.4%} · 最长水下 {rec_long['longest_uw_d']} 日(S-829)"
        f" / {G.underwater(base['nav']).get('length_d')} 日(G) · 最大回撤 {m_long['max_dd']:+.4%}")

    res: dict = {
        "card": "T-348", "part": "第五轮:长账本口径补齐其余六族 + 现金敏感性 + 非选后区间 + 调仓相位分布",
        "generated": "lane-c 2026-11-12",
        "spec": {"ledger_start": LONG_START, "window_B": WIN_B, "end": WIN_END,
                 "cash_zero_before": CASH_ZERO_BEFORE,
                 "rv2_engine": "docs/research/t353_engine.py(f 0.005 / cap 0.40 / 名额 14 / exits_first / marked)",
                 "kernel": "src.data.universe.flex_alloc.dynamic_mix_nav(rb 21 / cost 20bp / rb_weights)",
                 "criterion": "最长水下变短 且 年化不降(两者都要)",
                 "family_rule": "族 = 第三轮已重出的族缓存;票与规则一字不动",
                 "family_scaling_fix": "族的收益序列带族首日水位(fam_ret_full;本轮修;旧口径见 fix_legacy_comparison)"},
        "data": info,
        "base_long": {"C0_cagr": m_long["cagr"], "C0_total_return": m_long["total_return"],
                      "C0_max_dd": m_long["max_dd"], "C0_uw_G": G.underwater(base["nav"]),
                      "C0_uw_S829": rec_long, "n_days": m_long["n_days"],
                      "d0": m_long["d0"], "d1": m_long["d1"]},
        "families": {}, "fix_legacy_comparison": {}, "cash_sensitivity": {},
        "presel_interval": {}, "phase_shift": {}, "mc_se": {}, "checks": {},
    }

    # ── (1) 八族 × 窗口(A=族票源起点 / A_ledger=长账本起点 / B=2021-10-11)─────
    fam_arms: dict[str, pd.Series] = {}
    fam_rets: dict[str, pd.Series] = {}
    for key in FAM_KEYS:
        fam = R4.load_family(key)
        nav = fam["nav"]
        first_entry = str(fam.get("first_entry") or nav.index[0].date())
        last_exit = str(fam.get("last_exit") or nav.index[-1].date())
        fam_ret = fam_ret_full(nav, cal)
        arm = R3.arm_with_family(base, fam_ret)
        fam_arms[key] = arm
        fam_rets[key] = fam_ret
        legacy_ret = R3.fam_return_series(nav, cal)
        legacy_arm = R3.arm_with_family(base, legacy_ret)

        w_a = max(first_entry, LONG_START)
        w_b = WIN_B
        a_avail = w_a <= WIN_END
        b_avail = first_entry <= WIN_B          # 族在窗口 B 内有票才算可得
        wa = win_stats(base["nav"], arm, w_a) if a_avail else None
        wb = win_stats(base["nav"], arm, w_b) if b_avail else None
        wl = win_stats(base["nav"], arm, LONG_START)          # A_ledger:与第四轮同起点
        pa = bool(wa["diff"]["underwater_shorter"] and wa["diff"]["cagr_not_lower"]) if wa else None
        pb = bool(wb["diff"]["underwater_shorter"] and wb["diff"]["cagr_not_lower"]) if wb else None
        cls = classify(pa, pb)
        sc_a = R3.selfcheck_family(nav, fam_ret, w_a, WIN_END) if a_avail else None
        sc_b = R3.selfcheck_family(nav, fam_ret, w_b, WIN_END) if b_avail else None
        sc_l = R3.selfcheck_family(nav, fam_ret, LONG_START, WIN_END)

        # 旧口径(第四轮用的)对照
        leg_a = win_stats(base["nav"], legacy_arm, w_a) if a_avail else None
        leg_b = win_stats(base["nav"], legacy_arm, w_b) if b_avail else None
        leg_l = win_stats(base["nav"], legacy_arm, LONG_START)
        res["fix_legacy_comparison"][key] = {
            "legacy_note": "旧口径:族净值原值直接进日历日序列、族首日之前填 1.0(第四轮用的)",
            "first_waterlevel": float(nav.dropna().sort_index().iloc[0]),
            "A": {"legacy_cagr_pp": leg_a["diff"]["cagr_pp"], "norm_cagr_pp": wa["diff"]["cagr_pp"],
                  "legacy_uw": leg_a["diff"]["underwater_days"], "norm_uw": wa["diff"]["underwater_days"]} if wa else None,
            "A_ledger": {"legacy_cagr_pp": leg_l["diff"]["cagr_pp"], "norm_cagr_pp": wl["diff"]["cagr_pp"],
                         "legacy_uw": leg_l["diff"]["underwater_days"], "norm_uw": wl["diff"]["underwater_days"]},
            "B": {"legacy_cagr_pp": leg_b["diff"]["cagr_pp"], "norm_cagr_pp": wb["diff"]["cagr_pp"],
                  "legacy_uw": leg_b["diff"]["underwater_days"], "norm_uw": wb["diff"]["underwater_days"]} if wb else None,
            "selfcheck_legacy_A": R3.selfcheck_family(nav, legacy_ret, w_a, WIN_END)["abs_diff"] if a_avail else None,
            "selfcheck_norm_A": sc_a["abs_diff"] if sc_a else None,
        }

        fs = G.metrics(nav)
        res["families"][key] = {
            "meta": {k: v for k, v in fam.items() if k != "nav"},
            "family_standalone": fs,
            "family_first_entry": first_entry, "family_last_exit": last_exit,
            "family_curve_span": [str(nav.index[0].date()), str(nav.index[-1].date())],
            "first_waterlevel": float(nav.dropna().sort_index().iloc[0]),
            "windows": {"A": {"start": w_a, "available": a_avail, "stats": wa, "selfcheck": sc_a},
                        "A_ledger": {"start": LONG_START, "available": True, "stats": wl, "selfcheck": sc_l},
                        "B": {"start": w_b, "available": b_avail, "stats": wb, "selfcheck": sc_b}},
            "conclusion": cls,
        }
        log(f"  [{key}] 族 {first_entry}→{last_exit} · 首日水位 {float(nav.dropna().sort_index().iloc[0]):.6f}"
            f" · 自身总收益 {fs['total_return']:+.4%}")
        log(f"      A({w_a}) pass={pa} · B({w_b}) pass={pb} ⇒ {cls['class']}")
        if wa:
            log(f"      A: C0 {wa['C0']['metrics']['cagr']:+.4%} / +族 "
                f"{wa['C0_plus_family']['metrics']['cagr']:+.4%}"
                f" (Δ {wa['diff']['cagr_pp']:+.3f}pp) · UW {wa['C0']['underwater'].get('length_d')}"
                f" → {wa['C0_plus_family']['underwater'].get('length_d')} 日"
                f" · 自检② {sc_a['abs_diff']:.2e}")
        if wb:
            log(f"      B: C0 {wb['C0']['metrics']['cagr']:+.4%} / +族 "
                f"{wb['C0_plus_family']['metrics']['cagr']:+.4%}"
                f" (Δ {wb['diff']['cagr_pp']:+.3f}pp) · UW {wb['C0']['underwater'].get('length_d')}"
                f" → {wb['C0_plus_family']['underwater'].get('length_d')} 日"
                f" · 自检② {sc_b['abs_diff']:.2e}")
        log(f"      A_ledger({LONG_START}):Δ {wl['diff']['cagr_pp']:+.3f}pp · "
            f"UW {wl['C0']['underwater'].get('length_d')} → {wl['C0_plus_family']['underwater'].get('length_d')} 日"
            f" · 自检② {sc_l['abs_diff']:.2e}")

    # ── (6) 唯一非选后区间 ────────────────────────────────────────────────
    h4_arm = fam_arms["S681_H4"]
    pre_c0 = R3.slice_win(base["nav"], PRESEL_START, PRESEL_END)
    pre_f = R3.slice_win(h4_arm, PRESEL_START, PRESEL_END)
    pre_m0, pre_mf = G.metrics(pre_c0), G.metrics(pre_f)
    pre_u0, pre_uf = G.underwater(pre_c0), G.underwater(pre_f)
    res["presel_interval"] = {
        "window": [PRESEL_START, PRESEL_END],
        "note": "唯一没被选族用过的区间(选族用的窗口 B 自 2021-10-11 起;此区间内 H4 族有票但没参与选族)",
        "C0": {"metrics": pre_m0, "underwater": pre_u0},
        "C0_plus_H4": {"metrics": pre_mf, "underwater": pre_uf},
        "diff": {"cagr_pp": 100.0 * (pre_mf["cagr"] - pre_m0["cagr"]),
                 "max_dd_pp": 100.0 * (pre_mf["max_dd"] - pre_m0["max_dd"]),
                 "underwater_days": (pre_uf.get("length_d") or 0) - (pre_u0.get("length_d") or 0)},
    }
    log(f"  (6) 非选后区间 {PRESEL_START}→{PRESEL_END}:C0 {pre_m0['cagr']:+.4%}"
        f" / +H4 {pre_mf['cagr']:+.4%} (Δ {res['presel_interval']['diff']['cagr_pp']:+.3f}pp)"
        f" · UW {pre_u0.get('length_d')} → {pre_uf.get('length_d')} 日")

    # ── (8) 调仓相位分布(基准起点后移 0..20 日)────────────────────────────
    ph = []
    for k in range(21):
        st = (pd.Timestamp(LONG_START) + pd.Timedelta(days=k)).strftime("%Y-%m-%d")
        bk = build_base_at(legs, cash, rv2, st)
        ak = R3.arm_with_family(bk, fam_rets["S681_H4"])
        w = win_stats(bk["nav"], ak, st)
        ph.append({"offset_d": k, "start": st,
                   "cagr_pp": w["diff"]["cagr_pp"],
                   "underwater_days": w["diff"]["underwater_days"],
                   "max_dd_pp": w["diff"]["max_dd_pp"],
                   "cagr_C0": w["C0"]["metrics"]["cagr"],
                   "cagr_arm": w["C0_plus_family"]["metrics"]["cagr"],
                   "uw_C0": w["C0"]["underwater"].get("length_d"),
                   "uw_arm": w["C0_plus_family"]["underwater"].get("length_d")})
    cg = np.array([p["cagr_pp"] for p in ph], dtype=float)
    ud = np.array([p["underwater_days"] for p in ph], dtype=float)
    res["phase_shift"] = {
        "note": "基准起点后移 0..20 日 = 调仓相位的 21 个取值(核的再平衡周期 21 日);只报不判",
        "rows": ph,
        "cagr_pp": {"min": float(cg.min()), "max": float(cg.max()), "median": float(np.median(cg)),
                    "mean": float(cg.mean()), "n_positive": int((cg > 0).sum()), "n": len(cg)},
        "underwater_days": {"min": int(ud.min()), "max": int(ud.max()), "median": float(np.median(ud)),
                            "n_negative": int((ud < 0).sum()), "n": len(ud)},
    }
    log(f"  (8) 调仓相位 0..20:ΔCAGR {cg.min():+.3f} … {cg.max():+.3f} pp(中位 {np.median(cg):+.3f},"
        f" {int((cg>0).sum())}/{len(cg)} 为正) · ΔUW {int(ud.min())} … {int(ud.max())} 天"
        f"({int((ud<0).sum())}/{len(ud)} 为负)")

    # ── (4) 现金利率敏感性 ────────────────────────────────────────────────
    cash_after = cash[cash.index >= pd.Timestamp(CASH_ZERO_BEFORE)]
    med = float(cash_after.median()) if len(cash_after) else 0.0
    cash_sens = cash.copy()
    in_book = (cash_sens.index >= pd.Timestamp(LONG_START)) & (cash_sens.index < pd.Timestamp(CASH_ZERO_BEFORE))
    pre_mask = cash_sens.index < pd.Timestamp(CASH_ZERO_BEFORE)
    cash_sens.loc[pre_mask] = med
    base_s = build_base_at(legs, cash_sens, rv2, LONG_START)
    ms = G.metrics(base_s["nav"])
    res["cash_sensitivity"] = {
        "note": "2023-02-10 之前记 0 是「读不到当 0」;敏感性 = 用 2023-02-10 之后的中位数补",
        "median_daily_rate_after": med,
        "n_days_replaced_total": int(pre_mask.sum()),
        "n_days_replaced_in_book": int(in_book.sum()),
        "C0_base": {"cagr": m_long["cagr"], "uw_G": G.underwater(base["nav"]).get("length_d"),
                    "uw_S829": rec_long["longest_uw_d"], "max_dd": m_long["max_dd"]},
        "C0_sens": {"cagr": ms["cagr"], "uw_G": G.underwater(base_s["nav"]).get("length_d"),
                    "uw_S829": R3.recovery_s829(base_s["nav"])["longest_uw_d"], "max_dd": ms["max_dd"]},
        "C0_delta": {"cagr_pp": 100.0 * (ms["cagr"] - m_long["cagr"]),
                     "max_dd_pp": 100.0 * (ms["max_dd"] - m_long["max_dd"]),
                     "uw_S829": R3.recovery_s829(base_s["nav"])["longest_uw_d"] - rec_long["longest_uw_d"]},
        "families": {},
    }
    log(f"  (4) 现金敏感性:中位日率 {med:.3e}(账本内替换 {int(in_book.sum())} 天)· C0 年化 "
        f"{m_long['cagr']:+.4%} → {ms['cagr']:+.4%}"
        f"(Δ {res['cash_sensitivity']['C0_delta']['cagr_pp']:+.3f}pp)")
    for key in FAM_KEYS:
        arm_s = R3.arm_with_family(base_s, fam_rets[key])
        w_a = max(str(res["families"][key]["family_first_entry"]), LONG_START)
        row = {}
        for wname, wstart in (("A", w_a), ("B", WIN_B)):
            if not res["families"][key]["windows"][wname]["available"]:
                row[wname] = None
                continue
            base_w = win_stats(base["nav"], fam_arms[key], wstart)
            sens_w = win_stats(base_s["nav"], arm_s, wstart)
            row[wname] = {
                "base_cagr": base_w["C0"]["metrics"]["cagr"],
                "sens_cagr": sens_w["C0"]["metrics"]["cagr"],
                "base_cagr_plus_fam": base_w["C0_plus_family"]["metrics"]["cagr"],
                "sens_cagr_plus_fam": sens_w["C0_plus_family"]["metrics"]["cagr"],
                "delta_cagr_pp": 100.0 * (sens_w["C0_plus_family"]["metrics"]["cagr"]
                                          - base_w["C0_plus_family"]["metrics"]["cagr"]),
                "base_uw": base_w["C0_plus_family"]["underwater"].get("length_d"),
                "sens_uw": sens_w["C0_plus_family"]["underwater"].get("length_d"),
                "pass_base": bool(base_w["diff"]["underwater_shorter"] and base_w["diff"]["cagr_not_lower"]),
                "pass_sens": bool(sens_w["diff"]["underwater_shorter"] and sens_w["diff"]["cagr_not_lower"]),
            }
        res["cash_sensitivity"]["families"][key] = row
        for wname in ("A", "B"):
            if row[wname]:
                r = row[wname]
                log(f"      [{key}/{wname}] +族 年化 {r['base_cagr_plus_fam']:+.4%} → {r['sens_cagr_plus_fam']:+.4%}"
                    f"(Δ {r['delta_cagr_pp']:+.3f}pp) · UW {r['base_uw']} → {r['sens_uw']} 日"
                    f" · 判据 base={r['pass_base']} sens={r['pass_sens']}")

    # ── (7) p 值的 MC 标准误(取第四轮的零分布结果)─────────────────────────
    if os.path.exists(R4_JSON):
        r4 = json.load(open(R4_JSON))
        for wname, entry in (r4.get("null") or {}).items():
            for stat in ("uw_shorten_d", "cagr_diff_pp"):
                e = entry.get(stat) or {}
                p = e.get("p_upper")
                n = e.get("null_n")
                if p is None or not n:
                    continue
                se = float(np.sqrt(p * (1.0 - p) / n))
                res["mc_se"][f"{wname}/{stat}"] = {
                    "p_upper": p, "n": n, "mc_se": se,
                    "note": "MC 标准误 = sqrt(p(1-p)/n);p 本身是 n 次抽样里的比例,分辨率下限 1/n",
                    "half_width_95": 1.96 * se}
                log(f"  (7) {wname}/{stat}: p = {p:.4f} ± {se:.4f}(MC SE,n = {n})")

    # ── 自检 ──────────────────────────────────────────────────────────────
    worst = 0.0
    worst_legacy = 0.0
    for key, f in res["families"].items():
        for wname in ("A", "A_ledger", "B"):
            sc = f["windows"][wname]["selfcheck"]
            if sc:
                worst = max(worst, sc["abs_diff"])
        lg = res["fix_legacy_comparison"][key]["selfcheck_legacy_A"]
        if lg is not None:
            worst_legacy = max(worst_legacy, lg)
    res["checks"] = {
        "selfcheck_family_max_abs_diff": worst,
        "selfcheck_family_max_abs_diff_legacy": worst_legacy,
        "selfcheck_family_criterion": "< 1e-9",
        "splice_max_ret_diff": info.get("splice_max_ret_diff"),
        "note": "自检② = 喂给内核的族序列 Π(1+r) 与族曲线同区间收益之差(取族净值端点 asof,与被检构造无关)",
    }
    log(f"  自检② 最差 {worst:.2e}(判据 < 1e-9;旧口径最差 {worst_legacy:.2e})")

    json.dump(res, open(OUT_JSON, "w"), ensure_ascii=False, indent=2, default=str)
    write_md(res)
    log(f"  → 已写 {OUT_JSON} / {OUT_MD}")


def write_md(res: dict) -> None:
    L: list[str] = []
    L.append("# T-348 第五轮:长账本口径补齐其余族(表)")
    L.append("")
    L.append(f"基准起点 {res['spec']['ledger_start']} · 窗口 B {res['spec']['window_B']} · 截止 {res['spec']['end']}")
    L.append(f"判据:{res['spec']['criterion']} · 零分布未重跑(沿用第四轮 H4 的 p 值)")
    L.append("")
    b = res["base_long"]
    L.append(f"长账本 C0:年化 {b['C0_cagr']:+.4%} · 最长水下 {b['C0_uw_S829']['longest_uw_d']} 日(S-829)"
             f" / {b['C0_uw_G'].get('length_d')} 日(G) · 最大回撤 {b['C0_max_dd']:+.4%} · {b['n_days']} 天")
    L.append("")
    L.append("## 1. 八族 × 窗口(长账本口径)")
    L.append("")
    L.append("| 族 | 族票区间 | 首日水位 | 窗口 | C0 年化 | +族 年化 | ΔCAGR(pp) | C0 UW | +族 UW | ΔUW(天) | C0 MDD | +族 MDD | 自检② | 判据 |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for key, f in res["families"].items():
        for wname in ("A", "A_ledger", "B"):
            w = f["windows"][wname]
            if not w["available"] or w["stats"] is None:
                L.append(f"| {key} | {f['family_first_entry']} → {f['family_last_exit']} | {f['first_waterlevel']:.6f} | "
                         f"{wname} | — | — | — | — | — | — | — | — | — | 不可得 |")
                continue
            s = w["stats"]
            L.append(
                f"| {key} | {f['family_first_entry']} → {f['family_last_exit']} | {f['first_waterlevel']:.6f} | "
                f"{wname}({w['start']}) | "
                f"{s['C0']['metrics']['cagr']:+.4%} | {s['C0_plus_family']['metrics']['cagr']:+.4%} | "
                f"{s['diff']['cagr_pp']:+.3f} | {s['C0']['underwater'].get('length_d')} | "
                f"{s['C0_plus_family']['underwater'].get('length_d')} | {s['diff']['underwater_days']} | "
                f"{s['C0']['metrics']['max_dd']:+.4%} | {s['C0_plus_family']['metrics']['max_dd']:+.4%} | "
                f"{w['selfcheck']['abs_diff']:.1e} | "
                f"{'过' if (s['diff']['underwater_shorter'] and s['diff']['cagr_not_lower']) else '不过'} |")
    L.append("")
    L.append("## 2. 结论类别")
    L.append("")
    L.append("| 族 | 结论 | A 过 | B 过 | 窗口依赖 |")
    L.append("|---|---|---|---|---|")
    for key, f in res["families"].items():
        c = f["conclusion"]
        L.append(f"| {key} | {c['class']} | {c['window_A_pass']} | {c['window_B_pass']} | {c['window_dependent']} |")
    L.append("")
    L.append("## 3. 记账修正对照(本轮 = 带族首日水位;旧 = 族净值直接进序列、族首日之前填 1.0)")
    L.append("")
    L.append("| 族 | 首日水位 | A ΔCAGR 旧→新 | A ΔUW 旧→新 | A_ledger ΔCAGR 旧→新 | B ΔCAGR 旧→新 | 自检② 旧 → 新 |")
    L.append("|---|---|---|---|---|---|---|")
    for key, cmp_ in res["fix_legacy_comparison"].items():
        a = cmp_["A"]
        b = cmp_["B"]
        al = cmp_["A_ledger"]
        a_c = f"{a['legacy_cagr_pp']:+.3f} → {a['norm_cagr_pp']:+.3f}" if a else "—"
        a_u = f"{a['legacy_uw']} → {a['norm_uw']}" if a else "—"
        b_c = f"{b['legacy_cagr_pp']:+.3f} → {b['norm_cagr_pp']:+.3f}" if b else "—"
        L.append(f"| {key} | {cmp_['first_waterlevel']:.6f} | {a_c} | {a_u} | "
                 f"{al['legacy_cagr_pp']:+.3f} → {al['norm_cagr_pp']:+.3f} | {b_c} | "
                 f"{(cmp_['selfcheck_legacy_A'] if cmp_['selfcheck_legacy_A'] is not None else float('nan')):.2e} → "
                 f"{(cmp_['selfcheck_norm_A'] if cmp_['selfcheck_norm_A'] is not None else float('nan')):.2e} |")
    L.append("")
    p = res["presel_interval"]
    L.append("## 4. (6) 唯一非选后区间")
    L.append("")
    L.append(f"窗口 {p['window'][0]} → {p['window'][1]}:"
             f"C0 {p['C0']['metrics']['cagr']:+.4%} / +H4 {p['C0_plus_H4']['metrics']['cagr']:+.4%}"
             f"(Δ {p['diff']['cagr_pp']:+.3f}pp)· UW {p['C0']['underwater'].get('length_d')}"
             f" → {p['C0_plus_H4']['underwater'].get('length_d')} 日"
             f" · MDD {p['C0']['metrics']['max_dd']:+.4%} → {p['C0_plus_H4']['metrics']['max_dd']:+.4%}")
    L.append("")
    L.append("## 5. (8) 调仓相位分布(基准起点后移 0..20 日)")
    L.append("")
    ph = res["phase_shift"]
    L.append(f"ΔCAGR:最小 {ph['cagr_pp']['min']:+.3f}pp · 中位 {ph['cagr_pp']['median']:+.3f}pp · "
             f"最大 {ph['cagr_pp']['max']:+.3f}pp · {ph['cagr_pp']['n_positive']}/{ph['cagr_pp']['n']} 为正")
    L.append(f"ΔUW:最小 {ph['underwater_days']['min']} 天 · 中位 {ph['underwater_days']['median']:.0f} 天 · "
             f"最大 {ph['underwater_days']['max']} 天 · {ph['underwater_days']['n_negative']}/{ph['underwater_days']['n']} 为负")
    L.append("")
    L.append("| 偏移(日) | 起点 | ΔCAGR(pp) | ΔUW(天) | ΔMDD(pp) |")
    L.append("|---|---|---|---|---|")
    for r in ph["rows"]:
        L.append(f"| {r['offset_d']} | {r['start']} | {r['cagr_pp']:+.3f} | {r['underwater_days']} | {r['max_dd_pp']:+.3f} |")
    L.append("")
    cs = res["cash_sensitivity"]
    L.append("## 6. (4) 现金利率敏感性")
    L.append("")
    L.append(f"2023-02-10 之前记 0(账本内 {cs['n_days_replaced_in_book']} 天)→ 用之后中位日率 "
             f"{cs['median_daily_rate_after']:.3e} 补")
    L.append(f"C0:年化 {cs['C0_base']['cagr']:+.4%} → {cs['C0_sens']['cagr']:+.4%}"
             f"(Δ {cs['C0_delta']['cagr_pp']:+.3f}pp)· UW {cs['C0_base']['uw_S829']} → {cs['C0_sens']['uw_S829']} 日"
             f" · MDD {cs['C0_base']['max_dd']:+.4%} → {cs['C0_sens']['max_dd']:+.4%}")
    L.append("")
    L.append("| 族 | 窗口 | +族 年化(原) | +族 年化(补) | Δ(pp) | UW 原→补 | 判据 原→补 |")
    L.append("|---|---|---|---|---|---|---|")
    for key, row in cs["families"].items():
        for wname in ("A", "B"):
            r = row[wname]
            if not r:
                continue
            L.append(f"| {key} | {wname} | {r['base_cagr_plus_fam']:+.4%} | {r['sens_cagr_plus_fam']:+.4%} | "
                     f"{r['delta_cagr_pp']:+.3f} | {r['base_uw']} → {r['sens_uw']} | "
                     f"{'过' if r['pass_base'] else '不过'} → {'过' if r['pass_sens'] else '不过'} |")
    L.append("")
    if res["mc_se"]:
        L.append("## 7. (7) 零分布 p 值的 MC 标准误")
        L.append("")
        L.append("| 窗口/统计量 | p_upper | n | MC SE | 95% 半宽 |")
        L.append("|---|---|---|---|---|")
        for k, v in res["mc_se"].items():
            L.append(f"| {k} | {v['p_upper']:.4f} | {v['n']} | {v['mc_se']:.4f} | ±{v['half_width_95']:.4f} |")
        L.append("")
    L.append(f"自检② 最差 {res['checks']['selfcheck_family_max_abs_diff']:.2e}(判据 < 1e-9)")
    L.append("")
    with open(OUT_MD, "w") as f:
        f.write("\n".join(L))


if __name__ == "__main__":
    main()
