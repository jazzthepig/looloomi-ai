#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T-348(S-821 / S-822 新尺子):坟场里的做空 / 对冲票族按**账户口径**重判。

**这是重判,不是新检验。** 每一族的票、规则、复现都用它们自己已有的脚本与结果文件:
- S-642(T-159)→ `t159_bear_short.py` 的空头臂(`_tickets_2020-03-01_2026-06-20.json` 的 `short`);
- S-736(T-256)→ `t256_tactical_short.py` 的袖套(tickets + perp BTC 永续 bar + Binance 资金费)。
不重新选票、不改规则、不动判据;只加一层「族票按每票 0.5% 净值风险叠到 C0 上」。

**装配(与 T-342 v2 一套,核一字不改)**:`flex_alloc.dynamic_mix_nav`(reb 21、cost 20bp、
RBv2 权重、现金计息、R-v2 叠加 f 0.5%),**日历日**序列直喂。
C0 = RBv2 + R-v2 f 0.5% + 现金(= T-342 的 L3 臂;自检①:本脚本重算的 C0 与 T-342 的 L3 对上)。
族票叠加:同一个 overlay 槽,两条日历日收益**相乘**合成
`z_d = (1 + rv2_d)(1 + fam_d) − 1` ⇒ 窗口内 `Π(1+z) = Π(1+rv2)·Π(1+fam)`;
族曲线那一段单独核(自检②:喂给内核的族序列在窗口内 `Π(1+r)` = 该族曲线同区间收益,差 < 1e-9)。

**窗口**:两个都报 —— (A) 该族票源能覆盖的最早日期起;(B) 2021-10-11 起(与 T-342 同窗)。
**判据(只三类)**:两个窗口都让最长水下变短且年化不降 / 只在一个窗口 / 都不。
两个窗口结论相反的明写「窗口依赖」。「去掉最好一张」只报不判。不入库;长计算 nohup。
"""
from __future__ import annotations

import importlib.util
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
MAIN_ROOT = "/Users/sbb/Projects/looloomi-ai"
DATA_ROOT = "/Volumes/CometCloudAI/cometcloud-local"
T159_DIR = os.path.join(DATA_ROOT, "research", "t159")
T156_DIR = os.path.join(DATA_ROOT, "research", "t156")
T256_DIR = os.path.join(DATA_ROOT, "research", "t256")

WIN_START = "2021-10-11"     # 记 NAV 起点(T-342 同窗)
WIN_END = "2026-10-30"       # 记 NAV 终点(T-342 同窗)
REB = 21
COST = 20 / 1e4
DAYS_PER_YEAR = 365.0

F_FAM = 0.005                # 每票风险 0.5% 净值(与 R-v2 / T-256 / T-332 的 RISK_PCT 同)
CAP_FAM = 10                 # 同时在场上限(S-642 原文:at most 10 at once)
COST_BPS = 7.5              # T-256:每次开 / 关 7.5bp
MAX_NOTIONAL = 0.50         # T-256:名义 ≤ 净值 50%
DVOL_START = "2021-03-24"   # T-256 的 DVOL 起点(袖套 NAV 的起点)
DVOL_END = "2026-10-31"     # T-256 的 DVOL 最后一天(袖套 NAV 的终点)

BASE_LEGS_CSV = os.path.join(HERE, "t348_base_legs.csv")
BASE_CAL_CSV = os.path.join(HERE, "t348_base_overlay_calendar.csv")
BASE_T342_JSON = os.path.join(HERE, "t348_base_t342_results.json")
KERNEL_PY = os.path.join(HERE, "t348_kernel.py")
OUT_JSON = os.path.join(HERE, "t348_results.json")
OUT_MD = os.path.join(HERE, "T-348_graveyard_rejudged.md")
OUT_SCEN = os.path.join(HERE, "scenarios", "lane-c-T-348.json")

LOG: list[str] = []


def log(msg: str) -> None:
    line = str(msg)
    LOG.append(line)
    print(line, flush=True)


# ── 核 ───────────────────────────────────────────────────────────────────────────
def load_kernel():
    spec = importlib.util.spec_from_file_location("t348_kernel", KERNEL_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── 指标(照 T-342 的口径)────────────────────────────────────────────────────────
def metrics(nav: pd.Series) -> dict:
    nav = nav.dropna()
    if len(nav) < 2:
        return {"n_days": int(len(nav))}
    final = float(nav.iloc[-1] / nav.iloc[0])
    days = (nav.index[-1] - nav.index[0]).days
    years = max(days / 365.25, 1e-9)
    rets = nav.pct_change().dropna()
    vol = float(rets.std(ddof=1) * math.sqrt(DAYS_PER_YEAR)) if len(rets) > 1 else None
    dd = nav / nav.cummax() - 1.0
    trough = dd.idxmin()
    peak = nav.loc[:trough].idxmax()
    maxdd = float(dd.min())
    cagr = final ** (1.0 / years) - 1.0
    try:
        m = nav.resample("ME").last().pct_change().dropna()
    except ValueError:
        m = nav.resample("M").last().pct_change().dropna()
    return {
        "n_days": int(len(nav)),
        "d0": str(nav.index[0].date()), "d1": str(nav.index[-1].date()),
        "total_return": final - 1.0,
        "cagr": cagr,
        "vol_ann": vol,
        "max_dd": maxdd,
        "dd_peak": str(peak.date()), "dd_trough": str(trough.date()),
        "calmar": (cagr / abs(maxdd)) if maxdd < 0 else None,
        "worst_month": float(m.min()) if len(m) else None,
        "worst_month_end": str(m.idxmin().date()) if len(m) else None,
        "best_month": float(m.max()) if len(m) else None,
        "n_months": int(len(m)),
    }


def yearly(nav: pd.Series) -> dict:
    nav = nav.dropna()
    out: dict[int, float] = {}
    if len(nav) < 2:
        return out
    prev = float(nav.iloc[0])
    for y, grp in nav.groupby(nav.index.year):
        last = float(grp.iloc[-1])
        out[int(y)] = last / prev - 1.0
        prev = last
    return out


def underwater(nav: pd.Series) -> dict:
    """最长水下:NAV 跌在前高之下最长的一段(自然日)。

    返回:长度(日)、前高日、谷日、收复日(未收复则 None)、该段最大回撤、
    以及「水下最久的那一段是第几段」。
    """
    nav = nav.dropna()
    idx = list(nav.index)
    if len(idx) < 3:
        return {"length_d": None}
    peak = nav.cummax()
    uw = (nav < peak).values
    episodes = []
    a = None
    for i in range(len(idx)):
        if uw[i]:
            if a is None:
                a = i - 1 if i > 0 else 0
        elif a is not None:
            episodes.append((a, i))
            a = None
    if a is not None:
        episodes.append((a, len(idx) - 1))
    best = None
    for (x, y) in episodes:
        seg = nav.iloc[x:y + 1]
        pk = float(seg.iloc[0])
        tr_i = seg.iloc[1:].idxmin() if len(seg) > 1 else seg.index[0]
        rec = None
        for j in range(y + 1, len(idx)):
            if float(nav.iloc[j]) >= pk:
                rec = idx[j]
                break
        end = rec if rec is not None else idx[-1]
        length = int((end - idx[x]).days)
        rec_flag = rec is not None
        dd = float(seg.min() / pk - 1.0)
        item = {"length_d": length, "peak_d": str(idx[x].date()), "trough_d": str(tr_i.date()),
                "recover_d": str(rec.date()) if rec is not None else None,
                "recovered": rec_flag, "depth": dd,
                "peak_value": pk, "trough_value": float(seg.min()),
                "end_if_open": str(idx[-1].date())}
        if best is None or length > best["length_d"]:
            best = item
    best["n_episodes"] = len(episodes)
    return best


def slice_win(nav: pd.Series, start: str, end: str = WIN_END) -> pd.Series:
    s = nav[(nav.index >= pd.Timestamp(start)) & (nav.index <= pd.Timestamp(end))]
    return s / float(s.iloc[0])


# ── 基准(C0)────────────────────────────────────────────────────────────────────
def build_base(kernel) -> dict:
    cdf = pd.read_csv(BASE_LEGS_CSV, parse_dates=["date"]).set_index("date").sort_index()
    legs = {"crypto": cdf["crypto_leg_nav_x1v"].astype(float),
            "equity": cdf["equity_close_acwi"].astype(float),
            "gold": cdf["gold_close_xauusd"].astype(float)}
    cal = pd.read_csv(BASE_CAL_CSV, parse_dates=["date"]).set_index("date").sort_index()
    cash_ret = cal["cash_daily_rate"].astype(float)
    rv2 = cal["rv2_daily_ret_f05"].astype(float)
    cal_idx = cal.index
    def fn_rb(hist, d):          # 与 T-342 的 fn_rb 一字同义:rb_weights 只吃历史
        return kernel.rb_weights(hist)

    nav, lg = kernel.dynamic_mix_nav(legs, fn_rb, reb=REB, cost=COST,
                                      start=pd.Timestamp(WIN_START), cash_ret=cash_ret,
                                      overlay_ret=rv2)
    nav = nav[nav.index <= pd.Timestamp(WIN_END)]
    log(f"  C0(L3 臂): {len(nav)} 天 {nav.index[0].date()} → {nav.index[-1].date()}"
        f" 终值 {float(nav.iloc[-1]):.4f} 调仓 {len(lg)} 次")
    # 自检①:与 T-342 的 L3 对上
    t342 = json.load(open(BASE_T342_JSON))
    ref = ((t342.get("arms") or {}).get("L3") or {}).get("metrics") or {}
    mine = metrics(nav)
    d = abs(mine["total_return"] - float(ref.get("total_return", float("nan"))))
    log(f"  自检①: 本脚本 C0 总收益 {mine['total_return']:+.10%} vs T-342 L3 "
        f"{float(ref.get('total_return')):+.10%}(差 {d:.3e})→ {'✅' if d < 1e-9 else '❌'}")
    return {"legs": legs, "cash_ret": cash_ret, "rv2": rv2, "cal_idx": cal_idx,
            "C0": nav, "selfcheck_C0_diff": d,
            "C0_total_return": mine["total_return"], "C0_cagr": mine["cagr"]}


def arm_with_overlay(base: dict, kernel, fam_ret: pd.Series | None) -> pd.Series:
    """把族票序列与 R-v2 序列相乘合成一个 overlay 槽,喂内核。"""
    rv2 = base["rv2"].fillna(0.0)
    if fam_ret is None:
        ov = rv2
    else:
        fam = fam_ret.reindex(base["cal_idx"]).fillna(0.0)
        ov = (1.0 + rv2.reindex(base["cal_idx"]).fillna(0.0)) * (1.0 + fam) - 1.0
    def fn_rb(hist, d):
        return kernel.rb_weights(hist)

    nav, _ = kernel.dynamic_mix_nav(base["legs"], fn_rb, reb=REB, cost=COST,
                                     start=pd.Timestamp(WIN_START), cash_ret=base["cash_ret"],
                                     overlay_ret=ov)
    return nav[nav.index <= pd.Timestamp(WIN_END)]


# ── 族曲线 ─────────────────────────────────────────────────────────────────────
def family_s642() -> dict:
    """S-642 / T-159:空头臂。票本与 bar 用他们自己缓存;曲线用他们自己的 `nav()`
    (f = 0.5%、同时最多 10 张、逐日盯市、复利)—— 不重新选票、不改规则。
    注:他们的 nav() 不含资金费(资金费按 S-642 原文单列在 R 里),这里照他们的口径,
    并把「资金费未计」写进报告。"""
    sys.path.insert(0, HERE)
    import t159_bear_short as T159  # noqa: PLC0415
    T159.ENV = T159_DIR if T159_DIR.endswith("/") else T159_DIR + "/"
    bars = T159.load_bars()
    nbars = sum(len(v) for v in bars.values())
    tb = json.load(open(os.path.join(T159_DIR, "_tickets_2020-03-01_2026-06-20.json")))
    short = tb["short"]
    log(f"  S-642: bar {nbars} 行 / {len(bars)} 符号;空头票 {len(short)} 张")
    curve = list(T159.nav(short, bars, f=F_FAM, cap=CAP_FAM, d_to=T159.CURVE_TO, compound=True))
    nav = pd.Series({pd.Timestamp(r["d"]): float(r["equity"]) for r in curve}).sort_index()
    first = min(t["entry_d"] for t in short if t.get("entry_d"))
    last = max((t.get("exit_d") or T159.CURVE_TO) for t in short)
    n_still = sum(1 for t in short if not t.get("exit_d"))
    log(f"  S-642 族曲线: {len(nav)} 天 {nav.index[0].date()} → {nav.index[-1].date()}"
        f" 终值 {float(nav.iloc[-1]):.4f};首票进场 {first} 末票出场 {last}(未平 {n_still} 张)")
    best = max(short, key=lambda t: (t.get("r") if t.get("r") is not None else -9e9))
    return {"nav": nav, "first_entry": first, "last_exit": last, "n_tickets": len(short),
            "n_open_end": n_still, "risk_frac": F_FAM, "cap": CAP_FAM,
            "best_ticket": {"symbol": best.get("symbol"), "signal_d": best.get("signal_d"),
                            "entry_d": best.get("entry_d"), "r": best.get("r"),
                            "why": "贡献最大的一张(只报不判)"},
            "note": "资金费未计(照 T-159 自己的 nav() 口径:资金费单列在 R 里)"}


def family_s736() -> dict:
    """S-736 / T-256:战术空单。票用他们自己 results 的 tickets;曲线复刻他们脚本里的
    `sleeve_nav`(逐日盯市、每票风险 0.5% 净值、名义 ≤ 50%、成本 7.5bp、资金费实计)。"""
    res = json.load(open(os.path.join(HERE, "t256_results.json")))
    tickets = res["tickets"]
    bars = json.load(open(os.path.join(T256_DIR, "perp_btc.json")))
    vf = json.load(open(os.path.join(T256_DIR, "v_funding_btc.json")))
    dates = [b["d"] for b in bars]
    close = {b["d"]: float(b["c"]) for b in bars}
    idx = {d: i for i, d in enumerate(dates)}
    fund = {}
    for r in vf:
        dd = str(r["d"])[:10]
        n = int(r.get("n") or 1)
        fund[dd] = fund.get(dd, 0.0) + float(r["funding_rate"]) * n
    for t in tickets:
        t["_fund_day"] = {dd: fund.get(dd, 0.0) for dd in dates[idx[t["entry_d"]]:idx[t["exit_d"]] + 1]}
    # ── 复刻 sleeve_nav(T-256 第 501–540 行)──────────────────────────────────
    day_end = max(DVOL_END, max(t["exit_d"] for t in tickets))
    days = [d for d in dates if DVOL_START <= d <= day_end]

    def sleeve(fix_same_day_exit: bool):
        cash, open_t, nav = 1.0, None, []
        taken: list = []
        for t in tickets:          # 清掉上一轮的名义标记(每次跑都重算)
            t.pop("_notional_rebuilt", None)
            t.pop("_equity_rebuilt", None)
        for d in days:
            i = idx[d]
            if open_t is not None and (d >= open_t["exit_d"] if fix_same_day_exit
                                       else idx[open_t["exit_d"]] == i):
                t = open_t
                pnl = t["_notional_rebuilt"] * (t["entry"] - t["exit"]) / t["entry"]
                fund_cash = t["_notional_rebuilt"] * sum(t["_fund_day"].get(dd, 0.0)
                                                for dd in dates[idx[t["entry_d"]]:i + 1])
                cash += pnl + fund_cash - t["_notional_rebuilt"] * (COST_BPS / 1e4)
                open_t = None
            if open_t is None:
                for t in tickets:
                    if t["entry_d"] == d:
                        notional = min(F_FAM * cash / (t["r_unit"] / t["entry"]), MAX_NOTIONAL * cash)
                        t["_notional_rebuilt"] = notional
                        t["_equity_rebuilt"] = cash
                        cash -= notional * (COST_BPS / 1e4)
                        open_t = t
                        taken.append(t)
                        break
            if fix_same_day_exit and open_t is not None and open_t["exit_d"] <= d:
                t = open_t
                pnl = t["_notional_rebuilt"] * (t["entry"] - t["exit"]) / t["entry"]
                fund_cash = t["_notional_rebuilt"] * sum(t["_fund_day"].get(dd, 0.0)
                                                for dd in dates[idx[t["entry_d"]]:i + 1])
                cash += pnl + fund_cash - t["_notional_rebuilt"] * (COST_BPS / 1e4)
                open_t = None
            unreal = 0.0
            if open_t is not None:
                t = open_t
                unreal += t["_notional_rebuilt"] * (t["entry"] - close[d]) / t["entry"]
                unreal += t["_notional_rebuilt"] * sum(t["_fund_day"].get(dd, 0.0)
                                              for dd in dates[idx[t["entry_d"]]:i + 1])
            nav.append(cash + unreal)
        return nav, taken

    nav, taken = sleeve(False)
    # 自检:复刻出来的名义 / 进场净值 与他们自己跑出来的对得上(只对实际成交的票)
    taken = list(taken)
    dnot = max((abs(float(t.get("notional") or 0.0) - float(t["_notional_rebuilt"])) for t in taken),
               default=None)
    deq = max((abs(float(t.get("equity_at_entry") or 0.0) - float(t["_equity_rebuilt"])) for t in taken),
               default=None)
    dsum = max(abs(float(t.get("funding_sum") or 0.0) - sum(t["_fund_day"].values())) for t in tickets)
    log(f"  S-736 自检:成交 {len(taken)}/{len(tickets)} 张;名义最大差 {dnot} / "
        f"进场净值最大差 {deq} / 资金费合计最大差 {dsum:.3e}")
    navs = pd.Series(nav, index=pd.to_datetime(days))
    first = min(t["entry_d"] for t in tickets)
    m_pub = metrics(navs)
    log(f"  S-736 族曲线(照他们已发布口径): {len(navs)} 天 {navs.index[0].date()} → "
        f"{navs.index[-1].date()} 终值 {float(navs.iloc[-1]):.4f};票 {len(tickets)} 张"
        f"(实际成交 {len(taken)}),首票进场 {first}")
    log(f"  S-736 忠实性核:本复刻 袖套总回报 {m_pub['total_return']:+.4%} / 最大回撤 "
        f"{m_pub['max_dd']:+.4%} vs T-256 报告第 81 行 −10.62% / −22.15%"
        f"(回撤差 {100*(m_pub['max_dd']+0.2215):+.4f}pp)")
    # 诊断变体:他们的 sleeve_nav 里「同日出场」的票(出场日 == 进场日)永不平仓
    # (出场判断在开场判断之前,进场当天开的票当天不会走到出场分支)⇒ 那张票一直占位,
    # 后面的票全被跳过 —— 18 张票只成交 2 张。这是**记账次序**问题,不是选票或规则问题;
    # 诊断变体只把出场判断改成「出场日 ≤ 当天就平」,票与规则一字不动。
    nav_f, taken_fix = sleeve(True)
    nav_fix = pd.Series(nav_f, index=pd.to_datetime(days))
    m_fix = metrics(nav_fix)
    n_taken_fix = len(taken_fix)
    pub_ids = {id(t) for t in taken}
    fix_ids = {id(t) for t in taken_fix}
    tickets_detail = []
    for t in tickets:
        tickets_detail.append({
            "symbol": t.get("symbol") or "BTC", "signal_d": t.get("signal_d"),
            "entry_d": t.get("entry_d"), "exit_d": t.get("exit_d"),
            "hold_days": t.get("hold_days"), "reason": t.get("reason"),
            "r_price": t.get("r_price"), "r_fund": t.get("r_fund"), "r_cost": t.get("r_cost"),
            "r_net": t.get("r_net"),
            "taken_published": id(t) in pub_ids, "taken_fixed": id(t) in fix_ids,
            "notional_published": t.get("_notional_rebuilt") if id(t) in pub_ids else None,
        })
    log(f"  S-736 诊断变体(修正同日出场):成交 {n_taken_fix} 张,袖套总回报 "
        f"{m_fix['total_return']:+.4%} / 最大回撤 {m_fix['max_dd']:+.4%}")
    best = max(tickets, key=lambda t: (t.get("r_net") if t.get("r_net") is not None else -9e9))
    return {"nav": navs, "first_entry": first, "last_exit": max(t["exit_d"] for t in tickets),
            "n_tickets": len(tickets), "n_open_end": 0, "risk_frac": F_FAM, "cap": 1,
            "n_taken": len(taken),
            "tickets_detail": tickets_detail,
            "ticket_level_avg_r_net": float(sum(float(t.get("r_net") or 0.0) for t in tickets)
                                            / max(len(tickets), 1)),
            "ticket_level_total_r_net": float(sum(float(t.get("r_net") or 0.0) for t in tickets)),
            "published_faithful": {"total_return": m_pub["total_return"], "max_dd": m_pub["max_dd"],
                                   "t342_ref_total_return": -0.1062, "t342_ref_max_dd": -0.2215,
                                   "ref": "T-256_tactical_short.md 第 81 行"},
            "best_ticket": {"symbol": best.get("symbol") or "BTC(单一标的)", "signal_d": best.get("signal_d"),
                            "entry_d": best.get("entry_d"), "r": best.get("r_net"),
                            "why": "贡献最大的一张(只报不判)"},
            "selfcheck": {"notional_max_abs_diff": dnot, "equity_at_entry_max_abs_diff": deq,
                          "funding_sum_max_abs_diff": dsum},
            "note": "资金费实计(照 T-256 自己的 sleeve_nav 口径)",
            "variant": {"nav": nav_fix, "first_entry": first,
                        "last_exit": max(t["exit_d"] for t in tickets),
                        "n_tickets": len(tickets), "n_taken": n_taken_fix, "risk_frac": F_FAM,
                        "cap": 1, "best_ticket": best,
                        "note": "诊断:修正「同日出场不平仓」的记账次序;票与规则一字不动"}}


# ── 族 → 叠加序列 ──────────────────────────────────────────────────────────────
def fam_return_series(fam_nav: pd.Series, cal_idx: pd.DatetimeIndex) -> pd.Series:
    """族净值 → 日历日收益序列(族不在场的日子记 0;族曲线开始前净值 1.0、结束后持平)。"""
    e = pd.Series(1.0, index=cal_idx)
    common = cal_idx.intersection(fam_nav.index)
    e.loc[common] = fam_nav.loc[common]
    e = e.ffill().fillna(1.0)
    return e.pct_change().fillna(0.0)


def selfcheck_family(fam_nav: pd.Series, fam_ret: pd.Series, start: str, end: str) -> dict:
    """自检②:喂给内核的族序列在窗口内 Π(1+r) = 该族曲线同区间收益(差 < 1e-9)。"""
    s, e = pd.Timestamp(start), pd.Timestamp(end)
    win = fam_ret[(fam_ret.index > s) & (fam_ret.index <= e)]
    prod = float((1.0 + win).prod() - 1.0)
    # 族曲线同区间收益(用曲线端点值,不用逐日收益累乘)
    eq = pd.Series(1.0, index=fam_ret.index)
    common = fam_ret.index.intersection(fam_nav.index)
    eq.loc[common] = fam_nav.loc[common]
    eq = eq.ffill().fillna(1.0)
    base_v = float(eq.asof(s)) if s in eq.index else 1.0
    end_v = float(eq.asof(e)) if e in eq.index else float(eq.iloc[-1])
    curve_ret = end_v / base_v - 1.0
    return {"window": [str(s.date()), str(e.date())], "n_days": int(len(win)),
            "fed_prod_return": prod, "curve_return": curve_ret,
            "abs_diff": abs(prod - curve_ret)}


# ── 主流程 ─────────────────────────────────────────────────────────────────────
def evaluate(base: dict, kernel, fam: dict, label: str) -> dict:
    """一族票 → 叠加臂 → 两个窗口的账户口径指标 + 结论三类。"""
    fam_ret = fam_return_series(fam["nav"], base["cal_idx"])
    arm = arm_with_overlay(base, kernel, fam_ret)
    w_a_start = max(fam["first_entry"], WIN_START)
    windows = {"A_earliest": w_a_start, "B_2021-10-11": WIN_START}
    out = {"meta": {k: v for k, v in fam.items() if k not in ("nav", "variant")},
           "family_standalone": metrics(fam["nav"]),
           "family_standalone_yearly": yearly(fam["nav"]),
           "windows": {}}
    fs = out["family_standalone"]
    log(f"  {label} 族自身(f 0.5%/票):总收益 {fs['total_return']:+.4%}"
        f" 年化 {fs['cagr']:+.4%} 最大回撤 {fs['max_dd']:+.4%}")
    for wname, wstart in windows.items():
        c0 = slice_win(base["C0"], wstart)
        c0f = slice_win(arm, wstart)
        m0, mf = metrics(c0), metrics(c0f)
        u0, uf = underwater(c0), underwater(c0f)
        y0, yf = yearly(c0), yearly(c0f)
        sc = selfcheck_family(fam["nav"], fam_ret, wstart, WIN_END)
        log(f"  [{label}/{wname}] {wstart} → {WIN_END}:C0 CAGR {m0['cagr']:+.4%}"
            f" / +族 {mf['cagr']:+.4%}(Δ {100*(mf['cagr']-m0['cagr']):+.3f}pp)"
            f" | 最长水下 {u0.get('length_d')} 日 → {uf.get('length_d')} 日"
            f" | 最大回撤 {m0['max_dd']:+.4%} → {mf['max_dd']:+.4%}")
        log(f"      自检②:族序列 Π(1+r) {sc['fed_prod_return']:+.12f} vs 族曲线 "
            f"{sc['curve_return']:+.12f}(差 {sc['abs_diff']:.3e})"
            f" → {'✅' if sc['abs_diff'] < 1e-9 else '❌'}")
        out["windows"][wname] = {
            "start": wstart, "end": WIN_END,
            "C0": {"metrics": m0, "underwater": u0, "yearly": y0},
            "C0_plus_family": {"metrics": mf, "underwater": uf, "yearly": yf},
            "diff": {"cagr_pp": 100.0 * (mf["cagr"] - m0["cagr"]),
                     "max_dd_pp": 100.0 * (mf["max_dd"] - m0["max_dd"]),
                     "total_return_pp": 100.0 * (mf["total_return"] - m0["total_return"]),
                     "underwater_days": (uf.get("length_d") or 0) - (u0.get("length_d") or 0),
                     "cagr_not_lower": bool(mf["cagr"] >= m0["cagr"]),
                     "underwater_shorter": bool((uf.get("length_d") or 0) < (u0.get("length_d") or 0))},
            "selfcheck_family": sc,
        }
    wins = out["windows"]
    a_ok = wins.get("A_earliest", {}).get("diff", {})
    b_ok = wins.get("B_2021-10-11", {}).get("diff", {})
    a_pass = bool(a_ok.get("underwater_shorter") and a_ok.get("cagr_not_lower"))
    b_pass = bool(b_ok.get("underwater_shorter") and b_ok.get("cagr_not_lower"))
    if a_pass and b_pass:
        cls = "两个窗口都让最长水下变短且年化不降"
    elif a_pass or b_pass:
        cls = "只在一个窗口"
    else:
        cls = "都不"
    out["conclusion"] = {"class": cls, "window_A_pass": a_pass, "window_B_pass": b_pass,
                         "window_dependent": bool(a_pass != b_pass)}
    log(f"  {label} 结论:{cls}(A 通过 {a_pass} / B 通过 {b_pass})"
        + ("—— 窗口依赖" if a_pass != b_pass else ""))
    out["arm_curve"] = {str(d.date()): float(v) for d, v in arm.items()}
    return out


def main() -> None:
    kernel = load_kernel()
    log("=== 基准(C0 = RBv2 + R-v2 f0.5% + 现金) ===")
    base = build_base(kernel)
    fam_fns = {"S-642": family_s642, "S-736": family_s736}
    only = sys.argv[1:] if len(sys.argv) > 1 else None

    results = {"card": "T-348", "generated": pd.Timestamp.utcnow().isoformat(),
               "base": {"win_start": WIN_START, "win_end": WIN_END,
                        "C0_total_return": base["C0_total_return"], "C0_cagr": base["C0_cagr"],
                        "selfcheck_C0_diff": base["selfcheck_C0_diff"]},
               "families": {}}

    for name, fn in fam_fns.items():
        if only and name not in only:
            continue
        log(f"=== 族 {name} ===")
        fam = fn()
        out = evaluate(base, kernel, fam, name)
        if fam.get("variant"):
            log(f"  --- {name} 诊断变体 ---")
            v = evaluate(base, kernel, fam["variant"], name + "-variant")
            out["diagnostic"] = {"note": fam["variant"]["note"], "result": v}
        results["families"][name] = out

    with open(OUT_JSON, "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=1, default=str)
    log(f"落 {OUT_JSON}")
    write_report(results)
    log(f"落 {OUT_MD}")


# ── 报告 ───────────────────────────────────────────────────────────────────────
def _pct(x, nd=2):
    return "—" if x is None else f"{100.0 * float(x):+.{nd}f}%"


def write_report(res: dict) -> None:
    A = []
    A.append("# T-348 坟场按新尺子重判(S-821 / S-822)")
    A.append("")
    A.append("**重判,不是新检验。** 各族的票与规则用它们自己已有的脚本与结果文件;"
             "只加一层「族票按每票 0.5% 净值风险叠到 C0 上」,按**账户口径**看"
             "(CAGR、最长水下、最大回撤、逐年)。")
    A.append("")
    A.append(f"- 基准 C0 = RBv2 + R-v2 f 0.5% + 现金(= T-342 的 L3 臂),核 `flex_alloc.dynamic_mix_nav`"
             f"(reb 21、cost 20bp),日历日序列直喂。")
    A.append(f"- 自检①:C0 总收益 {res['base']['C0_total_return']:+.6%} 与 T-342 的 L3 对上"
             f"(差 {res['base']['selfcheck_C0_diff']:.3e})。")
    A.append("- 族票叠加:族序列与 R-v2 序列相乘合成一个 overlay 槽 ⇒ 窗口内 "
             "Π(1+z) = Π(1+rv2)·Π(1+fam);自检②:族序列 Π(1+r) 与族曲线同区间收益差 < 1e-9。")
    A.append("")
    for name, fam in (res.get("families") or {}).items():
        m = fam["meta"]
        fs = fam["family_standalone"]
        A.append(f"## {name}")
        A.append("")
        A.append(f"- 族自身(f {m['risk_frac']:.1%}/票):总收益 {_pct(fs['total_return'])}、"
                 f"年化 {_pct(fs['cagr'])}、最大回撤 {_pct(fs['max_dd'])};票 {m['n_tickets']} 张,"
                 f"首票进场 {m['first_entry']},末票出场 {m['last_exit']}。")
        A.append(f"- 口径备注:{m['note']}。")
        if m.get("published_faithful"):
            pf = m["published_faithful"]
            A.append(f"- 忠实性核(照他们已发布的数字):袖套总回报 {pf['total_return']:+.4%} / 最大回撤 "
                     f"{pf['max_dd']:+.4%},对 {pf['ref']} 的 {pf['t342_ref_total_return']:+.2%} / "
                     f"{pf['t342_ref_max_dd']:+.2%}。")
        if m.get("n_taken") is not None and m.get("n_tickets"):
            A.append(f"- 票 {m['n_tickets']} 张里实际成交 **{m['n_taken']}** 张(见下)。")
        A.append(f"- 「去掉最好一张」(**只报不判**):{m['best_ticket']['symbol']} "
                 f"{m['best_ticket']['entry_d']} 进,r = {m['best_ticket']['r']}。")
        A.append("")
        for wname, w in fam["windows"].items():
            c0, c0f = w["C0"], w["C0_plus_family"]
            d = w["diff"]
            sc = w["selfcheck_family"]
            A.append(f"### 窗口 {wname}({w['start']} → {w['end']})")
            A.append("")
            A.append("| 量 | C0 | C0 + 族 | 差 |")
            A.append("|---|---|---|---|")
            A.append(f"| 总收益 | {_pct(c0['metrics']['total_return'])} | "
                     f"{_pct(c0f['metrics']['total_return'])} | {d['total_return_pp']:+.2f}pp |")
            A.append(f"| 年化 CAGR | {_pct(c0['metrics']['cagr'])} | "
                     f"{_pct(c0f['metrics']['cagr'])} | {d['cagr_pp']:+.3f}pp |")
            A.append(f"| 最大回撤 | {_pct(c0['metrics']['max_dd'])} | "
                     f"{_pct(c0f['metrics']['max_dd'])} | {d['max_dd_pp']:+.2f}pp |")
            A.append(f"| 最长水下 | {c0['underwater'].get('length_d')} 日 | "
                     f"{c0f['underwater'].get('length_d')} 日 | {d['underwater_days']:+d} 日 |")
            A.append(f"| 最长水下的前高 → 谷 | {c0['underwater'].get('peak_d')} → "
                     f"{c0['underwater'].get('trough_d')} | {c0f['underwater'].get('peak_d')} → "
                     f"{c0f['underwater'].get('trough_d')} | |")
            A.append(f"| 最长水下收复日 | {c0['underwater'].get('recover_d') or '未收复'} | "
                     f"{c0f['underwater'].get('recover_d') or '未收复'} | |")
            A.append("")
            y0, yf = c0["yearly"], c0f["yearly"]
            ys = sorted(set(y0) | set(yf))
            A.append("| 年 | " + " | ".join(str(y) for y in ys) + " |")
            A.append("|---|" + "---|" * len(ys))
            A.append("| C0 | " + " | ".join(_pct(y0.get(y)) for y in ys) + " |")
            A.append("| C0 + 族 | " + " | ".join(_pct(yf.get(y)) for y in ys) + " |")
            A.append("")
            A.append(f"自检②:族序列 Π(1+r) = {sc['fed_prod_return']:+.12f},族曲线同区间 "
                     f"{sc['curve_return']:+.12f},差 {sc['abs_diff']:.3e}"
                     f"({'✅' if sc['abs_diff'] < 1e-9 else '❌'})。")
            A.append("")
        c = fam["conclusion"]
        A.append(f"**结论:{c['class']}**(窗口 A 通过 {c['window_A_pass']} / "
                 f"窗口 B 通过 {c['window_B_pass']})"
                 + ("—— **窗口依赖**" if c["window_dependent"] else ""))
        A.append("")
        if fam.get("diagnostic"):
            dg = fam["diagnostic"]
            r = dg["result"]
            A.append(f"**诊断变体**({dg['note']}):")
            A.append("")
            for wname, w in r["windows"].items():
                d = w["diff"]
                A.append(f"- 窗口 {wname}:CAGR {_pct(w['C0']['metrics']['cagr'])} → "
                         f"{_pct(w['C0_plus_family']['metrics']['cagr'])}"
                         f"(Δ {d['cagr_pp']:+.3f}pp);最长水下 "
                         f"{w['C0']['underwater'].get('length_d')} → "
                         f"{w['C0_plus_family']['underwater'].get('length_d')} 日;"
                         f"最大回撤 {_pct(w['C0']['metrics']['max_dd'])} → "
                         f"{_pct(w['C0_plus_family']['metrics']['max_dd'])}。")
            A.append(f"- 变体结论:{r['conclusion']['class']}。"
                     "**探索性 —— 需另立预注册、在新数据上过零信号对照。**")
            A.append("")
    with open(OUT_MD, "w") as f:
        f.write("\n".join(A) + "\n")


if __name__ == "__main__":
    main()
