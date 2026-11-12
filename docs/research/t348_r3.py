"""T-348 第三轮 ①(lane-c,2026-11-12):前两轮各族叠到**新 C0** 上的差值重出(只要表,不重写报告)。

口径(§Seth-1112e):
- R-v2 账户曲线 = `docs/research/t353_engine.simulate`(A 道从零写的那台):f 0.005、gross_cap 0.40、
  cap_n 14、exits_first=True、gross_basis="marked"、票源 t197 tickets.A;
- C0 = RBv2 三腿 + 现金计息 + R-v2 叠加,喂 `src.data.universe.flex_alloc.dynamic_mix_nav`
  (rb_weights,reb 21、cost 20bp);窗口 2021-10-11 → 2026-10-30;
- 预期:C0 年化 +26.4%、最长水下 762 天、最大回撤 −28.0%(S-829 的 E2 格)。

同时修 §Seth-1111l 的记账错:`fam_return_series` 先填 1.0 再 ffill ⇒ ffill 不生效,
族曲线没值的日子净值跳回 1.0(族收尾后整条叠加臂被打回原点)。改成:先留 NaN → ffill →
开头补 1.0;族收尾后净值持平、收益 0。

用法: python3 t348_r3.py
产物: t348_r3_results.json + _t348_r3_tables.md + t348_r3_families.csv(族曲线缓存)
"""
from __future__ import annotations

import importlib.util
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

WIN_START = "2021-10-11"
WIN_END = "2026-10-30"
UM_FILE = "/Volumes/CometCloudAI/cometcloud-local/research/s681/_um_daily.jsonl"
T197 = os.path.join(HERE, "t197_results.json")
OUT_JSON = os.path.join(HERE, "t348_r3_results.json")
OUT_MD = os.path.join(HERE, "_t348_r3_tables.md")
FAM_CACHE = os.path.join(HERE, "t348_r3_families.csv")
RV2_CACHE = os.path.join(HERE, "t348_r3_rv2_curve.csv")

# §Seth-1112e 的新基准(预期值,用来对账)
EXPECT_CAGR = 0.264
EXPECT_UW = 762
EXPECT_MDD = -0.280


def log(msg: str) -> None:
    print(str(msg), flush=True)


def load_module(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── R-v2 曲线(t353_engine;新口径)──────────────────────────────────────────────
def rv2_curve() -> pd.Series:
    if os.path.exists(RV2_CACHE):
        s = pd.read_csv(RV2_CACHE, parse_dates=["d"]).set_index("d")["nav"].astype(float)
        log(f"  R-v2 曲线(缓存):{len(s)} 天 {s.index[0].date()} → {s.index[-1].date()}")
        return s
    E = load_module("t353_engine", os.path.join(HERE, "t353_engine.py"))
    bars = E.load_um(UM_FILE)
    tickets, _meta = E.load_tickets(T197)
    log(f"  R-v2:票 {len(tickets)} 张 · bar {len(bars)} 符号 · t353_engine.simulate"
        f"(f 0.005 / cap 0.40 / 名额 14 / exits_first / gross_basis=marked)")
    r = E.simulate(tickets, bars, f=0.005, gross_cap=0.40, cap_n=14,
                   nav_to="2026-09-30", strict=True, exits_first=True, gross_basis="marked")
    s = pd.Series({pd.Timestamp(x[0]): float(x[1]) for x in r["curve"]}).sort_index()
    pg = max((x[2] / x[1] if x[1] > 0 else 0.0) for x in r["curve"])
    log(f"  R-v2 曲线:{len(s)} 天 {s.index[0].date()} → {s.index[-1].date()}"
        f" · 终值 {float(s.iloc[-1]):.4f} · 峰值名义 {pg:.4f}")
    s.to_frame("nav").rename_axis("d").to_csv(RV2_CACHE)
    return s


# ── 基准 C0(RBv2 + 现金 + R-v2)────────────────────────────────────────────────
def build_base() -> dict:
    d = pd.read_csv(os.path.join(HERE, "t342_daily.csv"), parse_dates=["date"]).set_index("date")
    legs = {"crypto": d["crypto_leg_nav_x1v"].astype(float),
            "equity": d["equity_close_acwi"].astype(float),
            "gold": d["gold_close_xauusd"].astype(float)}
    cal = pd.date_range(d.index[0], d.index[-1], freq="D")
    cash = d["cash_daily_rate"].astype(float).reindex(cal).ffill().fillna(0.0)
    rv2 = rv2_curve().pct_change().dropna()
    nav, lg = fa.dynamic_mix_nav(legs, lambda h, x: fa.rb_weights(h),
                                 start=pd.Timestamp(WIN_START), overlay_ret=rv2, cash_ret=cash)
    nav = nav[nav.index <= pd.Timestamp(WIN_END)]
    log(f"  C0:{len(nav)} 天 {nav.index[0].date()} → {nav.index[-1].date()}"
        f" · 终值 {float(nav.iloc[-1]):.4f} · 调仓 {len(lg)} 次")
    return {"legs": legs, "cash": cash, "rv2": rv2, "nav": nav, "cal_idx": cal,
            "log": lg, "start": WIN_START, "end": WIN_END}


# ── S-829 口径的水下 / 回撤(用来跟 Seth 给的 762 天 / −28.0% 对账)─────────────
def recovery_s829(nav: pd.Series) -> dict:
    peak = nav.cummax()
    uw = nav < peak
    longest, cur_start, open_end = 0, None, False
    spells = []
    for t, u in uw.items():
        if u and cur_start is None:
            cur_start = nav[:t][nav[:t] >= peak[t]].index[-1]
        if not u and cur_start is not None:
            spells.append((cur_start, t, (t - cur_start).days, False))
            cur_start = None
    if cur_start is not None:
        spells.append((cur_start, nav.index[-1], (nav.index[-1] - cur_start).days, True))
    lg = max(spells, key=lambda s: s[2]) if spells else None
    dd = nav / peak - 1
    tr = dd.idxmin()
    pk = nav[:tr][nav[:tr] >= peak[tr]].index[-1]
    after = nav[tr:][nav[tr:] >= peak[tr]]
    rec = after.index[0] if len(after) else None
    return {"mdd": float(dd.min()), "longest_uw_d": lg[2] if lg else 0,
            "longest_uw": (str(lg[0].date()), str(lg[1].date()), "open" if lg[3] else "closed") if lg else None,
            "mdd_peak": str(pk.date()), "mdd_trough": str(tr.date()),
            "down_d": (tr - pk).days, "up_d": (rec - tr).days if rec is not None else None}


def cagr_of(nav: pd.Series) -> float:
    yrs = max((nav.index[-1] - nav.index[0]).days / 365.25, 1e-9)
    return float(nav.iloc[-1] ** (1.0 / yrs) - 1.0)


# ── 族 → 叠加序列(修 §Seth-1111l)──────────────────────────────────────────
def fam_return_series(fam_nav: pd.Series, cal_idx: pd.DatetimeIndex) -> pd.Series:
    """族净值 → 日历日收益序列。

    修:先留 NaN(不是 1.0)再 ffill —— 原来先填 1.0,ffill 完全不生效,
    族曲线没值的日子(收尾后、中间缺口)净值跳回 1.0,整条叠加臂被打回原点。
    现在:族开始前 = 1.0;族有值的日子 = 族净值;族收尾后 = 持平(收益 0)。
    """
    e = pd.Series(np.nan, index=cal_idx, dtype=float)
    common = cal_idx.intersection(fam_nav.index)
    e.loc[common] = fam_nav.loc[common].astype(float)
    e = e.ffill().fillna(1.0)
    return e.pct_change().fillna(0.0)


def selfcheck_family(fam_nav: pd.Series, fam_ret: pd.Series, start: str, end: str) -> dict:
    """自检②:喂给内核的族序列在窗口内 Π(1+r) = 族曲线同区间收益(差 < 1e-9)。

    族曲线收益**直接从族自己的净值端点算**(asof),不重建 e 序列 ⇒ 与被检的构造无关。
    """
    s, e = pd.Timestamp(start), pd.Timestamp(end)
    win = fam_ret[(fam_ret.index > s) & (fam_ret.index <= e)]
    prod = float((1.0 + win).prod() - 1.0)
    nav = fam_nav.dropna().sort_index()
    base_v = float(nav.asof(s)) if len(nav) and s >= nav.index[0] else 1.0
    end_v = float(nav.asof(e)) if len(nav) else 1.0
    curve_ret = end_v / base_v - 1.0 if base_v else float("nan")
    return {"window": [str(s.date()), str(e.date())], "n_days": int(len(win)),
            "fed_prod_return": prod, "curve_return": curve_ret,
            "abs_diff": abs(prod - curve_ret),
            "note": "族曲线收益直接取族净值端点(asof),不重建被检序列"}


def arm_with_family(base: dict, fam_ret: pd.Series | None) -> pd.Series:
    rv2 = base["rv2"]
    if fam_ret is None:
        ov = rv2
    else:
        fam = fam_ret.reindex(base["cal_idx"]).fillna(0.0)
        ov = (1.0 + rv2.reindex(base["cal_idx"]).fillna(0.0)) * (1.0 + fam) - 1.0
    nav, _ = fa.dynamic_mix_nav(base["legs"], lambda h, x: fa.rb_weights(h),
                                 start=pd.Timestamp(base["start"]), overlay_ret=ov, cash_ret=base["cash"])
    return nav[nav.index <= pd.Timestamp(base["end"])]


def slice_win(nav: pd.Series, start: str, end: str = WIN_END) -> pd.Series:
    s = nav[(nav.index >= pd.Timestamp(start)) & (nav.index <= pd.Timestamp(end))]
    return s / float(s.iloc[0])


def evaluate(base: dict, fam: dict, label: str) -> dict:
    fam_ret = fam_return_series(fam["nav"], base["cal_idx"])
    arm = arm_with_family(base, fam_ret)
    w_a = max(fam["first_entry"], base["start"])
    windows = {"A_earliest": w_a, "B_2021-10-11": base["start"]}
    out = {"meta": {k: v for k, v in fam.items() if k not in ("nav", "variant")},
           "family_standalone": G.metrics(fam["nav"]),
           "family_standalone_yearly": G.yearly(fam["nav"]),
           "windows": {}}
    fs = out["family_standalone"]
    log(f"  {label} 族自身(f 0.5%/票):总收益 {fs['total_return']:+.4%}"
        f" 年化 {fs['cagr']:+.4%} 最大回撤 {fs['max_dd']:+.4%}")
    for wname, wstart in windows.items():
        c0 = slice_win(base["nav"], wstart)
        c0f = slice_win(arm, wstart)
        m0, mf = G.metrics(c0), G.metrics(c0f)
        u0, uf = G.underwater(c0), G.underwater(c0f)
        sc = selfcheck_family(fam["nav"], fam_ret, wstart, base["end"])
        log(f"  [{label}/{wname}] {wstart} → {base['end']}:C0 CAGR {m0['cagr']:+.4%}"
            f" / +族 {mf['cagr']:+.4%}(Δ {100*(mf['cagr']-m0['cagr']):+.3f}pp)"
            f" | 最长水下 {u0.get('length_d')} → {uf.get('length_d')} 日"
            f" | 最大回撤 {m0['max_dd']:+.4%} → {mf['max_dd']:+.4%}"
            f" | 自检② {sc['abs_diff']:.2e}")
        out["windows"][wname] = {
            "start": wstart, "end": base["end"],
            "C0": {"metrics": m0, "underwater": u0, "yearly": G.yearly(c0)},
            "C0_plus_family": {"metrics": mf, "underwater": uf, "yearly": G.yearly(c0f)},
            "diff": {"cagr_pp": 100.0 * (mf["cagr"] - m0["cagr"]),
                     "max_dd_pp": 100.0 * (mf["max_dd"] - m0["max_dd"]),
                     "total_return_pp": 100.0 * (mf["total_return"] - m0["total_return"]),
                     "underwater_days": (uf.get("length_d") or 0) - (u0.get("length_d") or 0),
                     "cagr_not_lower": bool(mf["cagr"] >= m0["cagr"]),
                     "underwater_shorter": bool((uf.get("length_d") or 0) < (u0.get("length_d") or 0))},
            "selfcheck_family": sc,
        }
    wins = out["windows"]
    a = wins.get("A_earliest", {}).get("diff", {})
    b = wins.get("B_2021-10-11", {}).get("diff", {})
    a_pass = bool(a.get("underwater_shorter") and a.get("cagr_not_lower"))
    b_pass = bool(b.get("underwater_shorter") and b.get("cagr_not_lower"))
    cls = ("两个窗口都让最长水下变短且年化不降" if (a_pass and b_pass)
           else ("只在一个窗口" if (a_pass or b_pass) else "都不"))
    out["conclusion"] = {"class": cls, "window_A_pass": a_pass, "window_B_pass": b_pass,
                         "window_dependent": bool(a_pass != b_pass)}
    log(f"  {label} 结论:{cls}(A {a_pass} / B {b_pass})"
        + ("—— 窗口依赖" if a_pass != b_pass else ""))
    return out


# ── 各族(票与规则一字不动,各自已有脚本 / 结果文件)────────────────────────
def build_families() -> dict:
    fams: dict[str, dict] = {}
    log("=== S-642(T-159 空头臂)===")
    fams["S642"] = G.family_s642()
    log("=== S-736(T-256 战术空单)===")
    f736 = G.family_s736()
    fams["S736_published"] = {k: v for k, v in f736.items() if k != "variant"}
    fams["S736_fixed"] = {**fams["S736_published"], **f736["variant"]}
    log("=== S-808 / S-810(T-332 / T-334)===")
    import t348_families as F  # noqa: PLC0415
    T332, ev_rows, events, panels = F.t332_env()
    import t334_squeeze_fail as T334  # noqa: PLC0415
    fams["S808"] = F.fam_s808(T332, events, panels)
    fams["S810"] = F.fam_s810(T332, T334, ev_rows, panels)
    log("=== S-681 H2 / H3 / H4 ===")
    import t348_s681 as S681  # noqa: PLC0415
    h2 = json.load(open(os.path.join(HERE, "s681_h2_pump_fade_results.json")))
    h3 = json.load(open(os.path.join(HERE, "s681_h3_funding_crowd_results.json")))
    h4 = json.load(open(os.path.join(HERE, "s681_h4_bear_rally_fail_results.json")))
    tk_h2 = h2["tickets"]
    tk_h3 = list(h3["tickets"]["discovery"]) + list(h3["tickets"]["holdout"])
    tk_h4 = h4["tickets"]
    syms = {t["symbol"] for t in tk_h2 + tk_h3 + tk_h4}
    closes = S681.load_bars(syms)
    log(f"  bar 重建:{len(syms)} 个标的 → 命中 {sum(1 for s in syms if closes.get(s))}")
    fams["S681_H2"] = S681.family("S-681 H2(pump fade)", tk_h2, closes,
                                  "照 short_lab_common.money 的尺(t159.nav:f 0.5%/票、cap 10、逐日盯市)")
    fams["S681_H3"] = S681.family("S-681 H3(资金费拥挤)", tk_h3, closes, "同上;票 = 发现段 + 留出段合并")
    fams["S681_H4"] = S681.family("S-681 H4(熊市反弹失败)", tk_h4, closes, "同上")
    # 缓存族曲线(第二阶段复用)
    rows = []
    for k, f in fams.items():
        for d, v in f["nav"].items():
            rows.append({"family": k, "d": str(d.date()), "nav": float(v)})
    pd.DataFrame(rows).to_csv(FAM_CACHE, index=False)
    return fams


def load_families_from_cache() -> dict:
    df = pd.read_csv(FAM_CACHE, parse_dates=["d"])
    out: dict[str, dict] = {}
    meta_path = os.path.join(HERE, "t348_r3_families_meta.json")
    meta = json.load(open(meta_path))
    for k, m in meta.items():
        nav = df[df["family"] == k].set_index("d")["nav"].astype(float)
        out[k] = {"nav": nav, **m}
    return out


def main() -> None:
    log("=== R-v2 曲线(t353_engine,新口径)===")
    base = build_base()
    m = G.metrics(base["nav"])
    rec = recovery_s829(base["nav"])
    uw_g = G.underwater(base["nav"])
    log(f"  C0 账户口径:年化 {m['cagr']:+.4%} · 总收益 {m['total_return']:+.4%}"
        f" · 最长水下 {rec['longest_uw_d']} 日(S-829 口径)/ {uw_g.get('length_d')} 日(G.underwater)"
        f" · 最大回撤 {rec['mdd']:+.4%}")
    ok_cagr = abs(m["cagr"] - EXPECT_CAGR) < 0.005
    ok_uw = rec["longest_uw_d"] == EXPECT_UW
    ok_mdd = abs(rec["mdd"] - EXPECT_MDD) < 0.005
    log(f"  对账 §Seth-1112e(预期 +26.4% / 762 天 / −28.0%):"
        f"年化 {'✅' if ok_cagr else '❌'} · 水下 {'✅' if ok_uw else '❌'} · 回撤 {'✅' if ok_mdd else '❌'}")

    res = {"card": "T-348", "part": "第三轮 ①:新 C0(R-v2 用 t353_engine)上各族差值重出",
           "generated": "lane-c 2026-11-12",
           "spec": {"engine": "docs/research/t353_engine.py", "f": 0.005, "gross_cap": 0.40,
                    "cap_n": 14, "exits_first": True, "gross_basis": "marked",
                    "account_window": [WIN_START, WIN_END],
                    "expected": {"cagr": EXPECT_CAGR, "longest_uw_d": EXPECT_UW, "max_dd": EXPECT_MDD}},
           "base": {"C0_cagr": m["cagr"], "C0_total_return": m["total_return"],
                    "C0_max_dd_G": m["max_dd"], "C0_uw_G": uw_g,
                    "C0_recovery_S829": rec,
                    "check_cagr": ok_cagr, "check_uw": ok_uw, "check_mdd": ok_mdd,
                    "cal_start": str(base["cal_idx"][0].date()),
                    "cal_end": str(base["cal_idx"][-1].date())},
           "families": {}}

    cache = os.path.join(HERE, "t348_r3_families_meta.json")
    if os.path.exists(FAM_CACHE) and os.path.exists(cache):
        log("=== 各族(用缓存曲线)===")
        fams = load_families_from_cache()
    else:
        log("=== 各族(重建)===")
        fams = build_families()
        meta = {k: {kk: vv for kk, vv in f.items() if kk != "nav"} for k, f in fams.items()}
        json.dump(meta, open(cache, "w"), ensure_ascii=False, indent=1, default=str)

    for key, fam in fams.items():
        label = {"S642": "S-642", "S736_published": "S-736 已发布", "S736_fixed": "S-736 诊断变体",
                 "S808": "S-808", "S810": "S-810", "S681_H2": "S-681 H2",
                 "S681_H3": "S-681 H3", "S681_H4": "S-681 H4"}.get(key, key)
        res["families"][key] = evaluate(base, fam, label)
        json.dump(res, open(OUT_JSON, "w"), ensure_ascii=False, indent=2, default=str)
        log(f"  → {key} 写完")
    write_md(res)
    log(f"  → 已写 {OUT_JSON} / {OUT_MD}")


def write_md(res: dict) -> None:
    b = res["base"]
    L: list[str] = []
    A = L.append
    A("## T-348 第三轮 ①:各族叠到新 C0 上的差值(只表,不重写报告)\n")
    A(f"新 C0(RBv2 + 现金 + R-v2,t353_engine 口径 f 0.005 / cap 0.40 / 名额 14 / exits_first / marked)"
      f",窗口 {res['spec']['account_window'][0]} → {res['spec']['account_window'][1]}:"
      f"年化 **{b['C0_cagr']:+.4%}** · 最长水下 **{b['C0_recovery_S829']['longest_uw_d']} 日**"
      f"(S-829 口径)/ {b['C0_uw_G'].get('length_d')} 日(本卡 G.underwater)·"
      f"最大回撤 **{b['C0_max_dd_G']:+.4%}**。")
    A(f"对账 §Seth-1112e 预期(+26.4% / 762 天 / −28.0%):"
      f"年化 {'✅' if b['check_cagr'] else '❌'} · 水下 {'✅' if b['check_uw'] else '❌'} ·"
      f" 回撤 {'✅' if b['check_mdd'] else '❌'}(旧的 +21.56% / 824 天作废)。\n")
    A("| 族 | 窗口 | C0 CAGR | +族 CAGR | Δ(pp) | C0 最长水下 | +族 最长水下 | C0 最大回撤 | +族 最大回撤 | 自检② 差 |")
    A("|---|---|---|---|---|---|---|---|---|---|")
    for key, r in res["families"].items():
        for wn, w in r["windows"].items():
            A(f"| {key} | {wn}({w['start']} →) | {w['C0']['metrics']['cagr']:+.4%} | "
              f"{w['C0_plus_family']['metrics']['cagr']:+.4%} | {w['diff']['cagr_pp']:+.3f} | "
              f"{w['C0']['underwater'].get('length_d')} 日 | {w['C0_plus_family']['underwater'].get('length_d')} 日 | "
              f"{w['C0']['metrics']['max_dd']:+.4%} | {w['C0_plus_family']['metrics']['max_dd']:+.4%} | "
              f"{w['selfcheck_family']['abs_diff']:.1e} |")
    A("")
    A("| 族 | 结论 | A 通过 | B 通过 | 窗口依赖 |")
    A("|---|---|---|---|---|")
    for key, r in res["families"].items():
        c = r["conclusion"]
        A(f"| {key} | {c['class']} | {c['window_A_pass']} | {c['window_B_pass']} | {c['window_dependent']} |")
    A("")
    with open(OUT_MD, "w") as f:
        f.write("\n".join(L))


if __name__ == "__main__":
    main()
