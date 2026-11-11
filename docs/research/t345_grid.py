"""T-345 —— S-817 盲复算:R-v2 的名义上限 × 每票风险,12 格。

口径只读 REFUTATION_LEDGER `## S-817 —` 登记那一节(不读「S-817 结果」那一节,
不读 docs/research/s817_*)。装配用我自己的 T-343 装配(t343_blind.py):
核 = src/data/universe/flex_alloc.dynamic_mix_nav(RBv2 权重 / reb 21 / cost 20bp /
cash_ret / overlay_ret);腿 = CORE_X1V 作用于 ① + eodhd ACWI + eodhd XAUUSD;
窗口 2021-10-11 → 2026-10-30;叠加引擎 = docs/research/t251_gross_cap.py 的 simulate(一字不改),
票源 = docs/research/t197_results.json 的 tickets.A。

本卡只做一件事:把 (每票风险 f, 名义上限 cap) 这两个开关扫成 12 格,每格报
成交票数 / CAGR / 最大回撤 / 最长水下(日历日)/ 逐年;再对每格做「去掉成交票里
实现 R 最大的一张重跑」(S-796:一张票不许决定结论),报是哪张、CAGR 变成多少;
然后按 S-817 的 (i)–(iv) 逐格对 C0 = (0.5%, 0.40) 判。

只读库、不入库、不改 src/、不改任何被跟踪的代码。
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import t343_blind as T343          # noqa: E402  我自己的 T-343 装配(口径写死在里面)
import t251_gross_cap as T251      # noqa: E402  叠加引擎(simulate / curve_stats,一字不改)

FA = T343.FA

# ── 网格(写死)───────────────────────────────────────────────────────────────
F_GRID = [0.005, 0.010, 0.020]                    # 每票风险
CAP_GRID = [0.40, 0.80, 1.20, 2.00]                # 名义上限(占净值)
C0 = (0.005, 0.40)                               # 基准:真钱现在的配置

# ── 判据(S-817 登记原文)─────────────────────────────────────────────────────
UW_TOL_DAYS = 30       # (i) 最长水下 ≤ C0 + 30 天
CAGR_GAIN_PP = 3.0     # (ii) CAGR ≥ C0 + 3pp / 年
MDD_FLOOR = -0.50      # (iv) 账户最大回撤不深于 −50%

OUT_JSON = HERE / "t345_results.json"


def cell_key(f: float, cap: float) -> str:
    return f"f{int(round(f * 1000))}pc_cap{cap:.2f}"


# ── 指标 ────────────────────────────────────────────────────────────────────
def underwater(nav: pd.Series) -> dict:
    """最长水下:从高点到净值第一次回到它,日历日数;窗口末没回的写明。

    口径:净值跌破当时最高点 ⇒ 水下开始(起点 = 那个高点的日期);净值回到该高点 ⇒ 结束。
    """
    nav = nav.dropna()
    best = dict(days=0, peak_date=None, recovered_date=None, recovered=False,
                depth_pct=None)
    if len(nav) < 2:
        return best
    peak_val = float(nav.iloc[0])
    peak_d = nav.index[0]
    uw_start = None
    for d, v in nav.items():
        v = float(v)
        if v >= peak_val:
            if uw_start is not None:
                days = (d - uw_start).days
                if days > best["days"]:
                    seg = nav.loc[(nav.index >= uw_start) & (nav.index <= d)]
                    best = dict(days=int(days), peak_date=uw_start.date().isoformat(),
                                recovered_date=d.date().isoformat(), recovered=True,
                                depth_pct=round(float((seg / seg.cummax() - 1.0).min()) * 100, 4))
            peak_val = v
            peak_d = d
            uw_start = None
        elif uw_start is None:
            uw_start = peak_d
    if uw_start is not None:                      # 窗口末还没回到高点
        days = (nav.index[-1] - uw_start).days
        if days > best["days"]:
            seg = nav.loc[nav.index >= uw_start]
            best = dict(days=int(days), peak_date=uw_start.date().isoformat(),
                        recovered_date=None, recovered=False,
                        depth_pct=round(float((seg / seg.cummax() - 1.0).min()) * 100, 4))
    return best


def run_overlay(engine_tickets: list[dict], bars: dict, f: float, cap: float,
                cap_n: int = T343.OVERLAY_CAP_N, eq0: float = T343.OVERLAY_EQ0):
    """跑 t251 的 simulate,取净值曲线的逐日收益 + 成交票集合。"""
    res = T251.simulate(engine_tickets, bars, {}, cap, equity0=eq0,
                         risk_frac=f, cap_n=cap_n)
    curve = res["curve"]
    if not curve:
        raise SystemExit(f"overlay 空曲线:f={f} cap={cap}")
    ds = [c[0] for c in curve]
    eq = [float(c[1]) for c in curve]
    idx = pd.to_datetime(pd.Series(ds))
    s = pd.Series(eq, index=idx).sort_index()
    ret = s.pct_change()
    ret.iloc[0] = s.iloc[0] / eq0 - 1.0
    st = T251.curve_stats(curve, eq0)
    return ret, st, res


def account_nav(ov_ret: pd.Series, legs: dict, nav_start, cash_daily):
    def fn_rb(hist, d):
        return FA.rb_weights(hist)

    return FA.dynamic_mix_nav(legs, fn_rb, reb=T343.REB, cost=T343.COST, start=nav_start,
                              cash_ret=cash_daily, overlay_ret=ov_ret)


def main() -> int:
    t0 = datetime.now(timezone.utc)
    print("[load] 腿 / ① / 现金 …", flush=True)
    data = T343.load_legs()
    apy, apy_diag = T343.load_cash()
    tickets, t197 = T343.load_tickets()
    need = {t["symbol"] for t in tickets}
    bars = T343.load_um_bars(need)
    exits, bad = T343.classify_exits(tickets, bars)
    engine_tickets = T343.to_engine_tickets(tickets, exits)
    by_tid = {t["tid"]: t for t in engine_tickets}
    print(f"[tickets] {len(tickets)} 张 / {len(need)} 个币;出场原因不一致 {len(bad)} 张", flush=True)

    # ── 腿与窗口(与 T-343 逐字相同)─────────────────────────────────────────
    cnav_all = data["core_nav"]
    cnav = cnav_all[cnav_all.index >= pd.Timestamp(T343.LEG_FROM)]
    cleg_x1v, gpath = T343.crypto_leg(cnav, data["funding"])
    end = pd.Timestamp(T343.WINDOW_END)

    def cut(d):
        return {k: v[v.index <= end] for k, v in d.items()}

    legs_x1v = cut({"crypto": cleg_x1v, "equity": data["equity"], "gold": data["gold"]})
    df = pd.concat(legs_x1v, axis=1).dropna().sort_index()
    common = df.index
    nav_start = common[T343.WARM]
    cal = pd.date_range(common[0], end, freq="D")
    apy_cal = apy.reindex(cal).ffill()
    apy_cal = apy_cal.where(apy_cal.index >= pd.Timestamp(T343.CASH_FIRST), 0.0)
    cash_daily = (apy_cal / 100.0 / 365.0)
    cash_daily.name = "cash_ret"
    print(f"[window] 共同日 {len(common)}  记账起点 {nav_start.date()}", flush=True)

    out = {
        "meta": dict(card="T-345", lane="lane-b", ran_utc=t0.isoformat(),
                     spec_source="REFUTATION_LEDGER.md ## S-817(只读登记节)",
                     blind_note=("本文件不读「S-817 结果」那一节,不读 docs/research/s817_*;"
                                 "装配 = 我自己的 T-343(t343_blind.py);"
                                 "叠加引擎 = docs/research/t251_gross_cap.py:simulate(未改一字);"
                                 "票源 = docs/research/t197_results.json 的 tickets.A。"),
                     window=[nav_start.date().isoformat(), T343.WINDOW_END],
                     grid=dict(f=F_GRID, cap=CAP_GRID, c0=list(C0)),
                     criteria=dict(uw_tol_days=UW_TOL_DAYS, cagr_gain_pp=CAGR_GAIN_PP,
                                   mdd_floor=MDD_FLOOR,
                                   i="最长水下 ≤ C0 + 30 天", ii="CAGR ≥ C0 + 3pp/年",
                                   iii="去掉实现 R 最大的一张重跑后 CAGR ≥ C0 的全样本 CAGR",
                                   iv="账户最大回撤不深于 −50%"),
                     overlay=dict(ticket_source="docs/research/t197_results.json → tickets.A",
                                  engine="docs/research/t251_gross_cap.py:simulate(未改一字)",
                                  cap_n=T343.OVERLAY_CAP_N, equity0=T343.OVERLAY_EQ0)),
        "validation": {},
        "cells": {},
        "judgement": {},
        "f_star": {},
    }

    # ── 12 格 ────────────────────────────────────────────────────────────────
    for f in F_GRID:
        for cap in CAP_GRID:
            key = cell_key(f, cap)
            print(f"[cell] {key} …", flush=True)
            ov_ret, ov_st, res = run_overlay(engine_tickets, bars, f, cap)
            taken = sorted(res["taken"])
            nav, log = account_nav(ov_ret, legs_x1v, nav_start, cash_daily)
            m = T343.metrics(nav)
            uw = underwater(nav)
            y = T343.yearly(nav)

            # 去掉成交票里实现 R 最大的一张(S-796)
            cands = [by_tid[t] for t in taken if by_tid.get(t) and by_tid[t].get("r") is not None]
            drop = max(cands, key=lambda t: (t["r"], t["signal_d"], t["symbol"])) if cands else None
            drop_info = None
            if drop is not None:
                kept = [t for t in engine_tickets if t["tid"] != drop["tid"]]
                ov2, ov2_st, res2 = run_overlay(kept, bars, f, cap)
                nav2, _ = account_nav(ov2, legs_x1v, nav_start, cash_daily)
                m2 = T343.metrics(nav2)
                uw2 = underwater(nav2)
                drop_info = dict(
                    tid=drop["tid"], symbol=drop["symbol"], signal_d=drop["signal_d"],
                    entry_d=drop["entry_d"], exit_d=drop["exit_d"], r=round(float(drop["r"]), 6),
                    n_taken_after=len(res2["taken"]),
                    total_return=round(float(m2["total_return"]), 6),
                    cagr=round(float(m2["cagr"]), 6) if m2["cagr"] is not None else None,
                    max_drawdown=round(float(m2["max_drawdown"]), 6),
                    underwater=uw2,
                    yearly=T343.yearly(nav2),
                    overlay_total_return=round(float(ov2_st["total_return"]), 6),
                    overlay_cagr=round(float(ov2_st["cagr"]), 6) if ov2_st["cagr"] is not None else None,
                )

            cell = dict(
                f=f, cap=cap,
                n_tickets_taken=len(taken),
                n_tickets_source=len(engine_tickets),
                overlay=dict(total_return=round(float(ov_st["total_return"]), 6),
                             cagr=round(float(ov_st["cagr"]), 6) if ov_st["cagr"] is not None else None,
                             max_dd=round(float(ov_st["max_dd"]), 6),
                             worst_month=ov_st["worst_month"],
                             worst_month_ret=round(float(ov_st["worst_month_ret"]), 6),
                             n_days=ov_st["n_days"],
                             blocked_gross=len(res["blocked_gross"]),
                             blocked_cap=len(res["blocked_cap"]),
                             blocked_min=len(res["blocked_min"]),
                             blocked_coin=len(res["blocked_coin"]),
                             gross_ratio_max=round(float(max(res["gross_ratio_hist"])), 6) if res["gross_ratio_hist"] else None,
                             days_above_cap=sum(1 for x in res["gross_ratio_hist"] if x > cap + 1e-12)),
                account=dict(total_return=round(float(m["total_return"]), 6),
                             cagr=round(float(m["cagr"]), 6) if m["cagr"] is not None else None,
                             max_drawdown=round(float(m["max_drawdown"]), 6),
                             calmar=m["calmar"], vol_ann=m["vol_ann"],
                             worst_month=m["worst_month"], worst_month_key=m["worst_month_key"],
                             n_days=m["n_days"], first=m["first"], last=m["last"],
                             years=m["years"], underwater=uw),
                yearly=y,
                drop_max_r=drop_info,
                n_rebalances=int(len(log)),
            )
            out["cells"][key] = cell
            print(f"  [{key}] n={len(taken)} total {m['total_return']:+.4%} cagr {m['cagr']:+.4%} "
                  f"mdd {m['max_drawdown']:+.4%} uw {uw['days']}d "
                  f"drop->cagr {None if not drop_info else drop_info['cagr']}", flush=True)

    # ── 自检:C0 那格 = T-343 的 L3 ───────────────────────────────────────────
    c0 = out["cells"][cell_key(*C0)]
    l3_expect = dict(total_return=1.680953, max_drawdown=-0.347264)
    out["validation"] = dict(
        nav_start=nav_start.date().isoformat(),
        n_common_days=int(len(common)),
        exit_reason_mismatch=len(bad),
        exit_reason_mismatch_sample=bad[:5],
        c0_total_return=c0["account"]["total_return"],
        c0_max_drawdown=c0["account"]["max_drawdown"],
        t343_L3_total_return=l3_expect["total_return"],
        t343_L3_max_drawdown=l3_expect["max_drawdown"],
        c0_matches_t343_L3=bool(abs(c0["account"]["total_return"] - l3_expect["total_return"]) < 5e-5
                                and abs(c0["account"]["max_drawdown"] - l3_expect["max_drawdown"]) < 5e-5),
        c0_cagr=c0["account"]["cagr"],
        s817_register_c0_cagr=0.2156,          # 登记原文:(0.5%,0.40) → +21.56% / 年
        s817_register_c0_uw_days=824,           # 登记原文:最长水下 824 天
        c0_uw_days=c0["account"]["underwater"]["days"],
        c0_uw_matches_register=bool(abs(c0["account"]["underwater"]["days"] - 824) <= 3),
    )
    print(f"[self-check] C0 vs T-343 L3: {out['validation']['c0_matches_t343_L3']}  "
          f"uw {c0['account']['underwater']['days']}d(登记 824)", flush=True)

    # ── 判据(i)–(iv):每格对 C0 ──────────────────────────────────────────────
    c0_cagr = c0["account"]["cagr"]
    c0_uw = c0["account"]["underwater"]["days"]
    for key, c in out["cells"].items():
        acct = c["account"]
        j = {}
        j["i"] = dict(value=acct["underwater"]["days"], limit=c0_uw + UW_TOL_DAYS,
                      ok=bool(acct["underwater"]["days"] <= c0_uw + UW_TOL_DAYS),
                      text="最长水下 ≤ C0 + 30 天")
        j["ii"] = dict(value=acct["cagr"], limit=round(c0_cagr + CAGR_GAIN_PP / 100.0, 6),
                       ok=bool(acct["cagr"] is not None and c0_cagr is not None
                               and acct["cagr"] >= c0_cagr + CAGR_GAIN_PP / 100.0),
                       text="CAGR ≥ C0 + 3pp/年")
        dr = c["drop_max_r"]
        j["iii"] = dict(value=dr["cagr"] if dr else None, limit=c0_cagr,
                        ok=bool(dr is not None and dr["cagr"] is not None and dr["cagr"] >= c0_cagr),
                        text="去掉实现 R 最大的一张重跑后 CAGR ≥ C0 的全样本 CAGR")
        j["iv"] = dict(value=acct["max_drawdown"], limit=MDD_FLOOR,
                       ok=bool(acct["max_drawdown"] >= MDD_FLOOR),
                       text="账户最大回撤不深于 −50%")
        j["pass_all"] = bool(j["i"]["ok"] and j["ii"]["ok"] and j["iii"]["ok"] and j["iv"]["ok"])
        c["judgement"] = j
        print(f"[judge] {key} i={j['i']['ok']} ii={j['ii']['ok']} iii={j['iii']['ok']} iv={j['iv']['ok']} "
              f"=> {j['pass_all']}", flush=True)

    # ── f★:过的格里 CAGR 最高的,且网格上至少有一个相邻格也过 (i)(iii) ─────────
    passing = [k for k, c in out["cells"].items() if c["judgement"]["pass_all"]]
    best_key = None
    if passing:
        best_key = max(passing, key=lambda k: out["cells"][k]["account"]["cagr"])
    neigh_ok = False
    neigh = []
    if best_key is not None:
        f0 = out["cells"][best_key]["f"]
        cap0 = out["cells"][best_key]["cap"]
        for k, c in out["cells"].items():
            if k == best_key:
                continue
            df_ = abs(c["f"] - f0) <= 1e-9
            dc = abs(c["cap"] - cap0) <= 1e-9
            adjacent = (df_ and any(abs(x - cap0) < 1e-9 for x in CAP_GRID)) or \
                       (dc and any(abs(x - f0) < 1e-9 for x in F_GRID))
            if adjacent:
                ok = bool(c["judgement"]["i"]["ok"] and c["judgement"]["iii"]["ok"])
                neigh.append(dict(key=k, i=c["judgement"]["i"]["ok"], iii=c["judgement"]["iii"]["ok"]))
                neigh_ok = neigh_ok or ok
    out["f_star"] = dict(passing_cells=passing, best_cell=best_key,
                          best_cagr=(out["cells"][best_key]["account"]["cagr"] if best_key else None),
                          adjacent_check=neigh, adjacent_ok=bool(neigh_ok),
                          rule="CAGR 最高的过格,且网格上至少有一个相邻格也过 (i)(iii)")

    json.dump(out, open(OUT_JSON, "w"), indent=1, default=str)
    print("[out]", OUT_JSON)
    print("[f*]", json.dumps(out["f_star"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
