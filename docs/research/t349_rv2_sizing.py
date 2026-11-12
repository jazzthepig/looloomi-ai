#!/usr/bin/env python3
"""T-349 — S-825 盲复算(lane-a):R-v2 每票风险 f × 名义上限,8 格。

口径来源:**只读** `REFUTATION_LEDGER.md` 的 `## S-825 —` 登记那一节(唯一口径来源)。
**禁读** `## S-825 结果` 与 `docs/research/s825_*`。

装配(全部复用 B 道的 `docs/research/t343_blind.py`,不改它一字):
  腿/①/现金   t343_blind.load_legs / load_cash / crypto_leg(核 = `src/data/universe/flex_alloc`)
  票源        `docs/research/t197_results.json` → `tickets.A`(t343_blind.load_tickets)
  出场原因    t343_blind.classify_exits(按 T-159 规则重算,逐张对表 t197)
  叠加引擎    `docs/research/t251_gross_cap.py:simulate`(未改一字)—— cap_frac = 名义上限
  C0 臂       t343 的 **L3**(RBv2 权重 + 现金计息 + R-v2 叠加 f 0.5% / 上限 0.40)

网格(S-825 写死):f ∈ {0.75%, 1.0%, 1.25%, 1.5%} × 名义上限 ∈ {1.20, 2.00}。

判(S-825 写死,对 C0):一格站住 =
  (i)   最长水下 ≤ C0 + 30 天
  (ii)  CAGR ≥ C0 + 3pp / 年
  (iii) 上限不咬合:同一 f 在上限 1.20 与 2.00 下 CAGR 差 < 1pp
f★ = 最大的、自己站住且所有更小的 f 也都站住的 f(要一段连续的区间,不要孤点)。

只读、不入库。用法:`python3 docs/research/t349_rv2_sizing.py` → 写 `t349_results.json`
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

import t343_blind as T343                                    # noqa: E402  B 道 C0 装配(不改一字)
import t251_gross_cap as T251                                # noqa: E402  叠加引擎(不改一字)

FA = T343.FA

OUT_JSON = HERE / "t349_results.json"
OUT_MD = HERE / "t349_summary.md"

# ── S-825 写死的网格与判据 ────────────────────────────────────────────────────
F_GRID = [0.0075, 0.0100, 0.0125, 0.0150]
CAP_GRID = [1.20, 2.00]
C0_F, C0_CAP = 0.005, 0.40
UW_TOL_DAYS = 30          # (i) 最长水下 ≤ C0 + 30 天
CAGR_TOL_PP = 3.0         # (ii) CAGR ≥ C0 + 3pp / 年
BITE_TOL_PP = 1.0         # (iii) 同一 f 在 1.20 / 2.00 下 CAGR 差 < 1pp
C0_TOTAL_EXPECT = 1.6810  # +168.10%(卡上写死的自检值;metrics 的 total_return 是「净值倍数 − 1」)
C0_UW_EXPECT = 824        # 最长水下 824 天(卡上写死的自检值)


# ── 最长水下(两种口径都算,C0 自检时看哪个对上 824)────────────────────────────
def underwater(nav: pd.Series) -> dict:
    """最长水下:① 日历天(峰值日 → 收复日,没收复就到最后一天)② 交易日数(连续低于前高的天数)。"""
    nav = nav.dropna()
    if len(nav) < 2:
        return {"uw_cal_days": None, "uw_trading_days": None}
    vals = nav.to_numpy()
    dates = nav.index
    peak_v = vals[0]
    peak_d = dates[0]
    best_cal = 0
    for i in range(len(vals)):
        v = vals[i]
        if v >= peak_v:
            best_cal = max(best_cal, (dates[i] - peak_d).days)
            peak_v = v
            peak_d = dates[i]
        else:
            best_cal = max(best_cal, (dates[i] - peak_d).days)
    best_cal = max(best_cal, (dates[-1] - peak_d).days)

    # 连续低于前高的交易日数
    run = best_tr = 0
    for i in range(len(vals)):
        if i > 0 and vals[i] >= vals[:i].max():
            run = 0
        else:
            run += 1
            best_tr = max(best_tr, run)
    return {"uw_cal_days": int(best_cal), "uw_trading_days": int(best_tr),
            "uw_peak_date": peak_d.date().isoformat(), "uw_end_date": dates[-1].date().isoformat()}


def run_overlay(engine_tickets: list[dict], bars: dict, risk_frac: float, cap_frac: float) -> tuple[pd.Series, dict]:
    """跑 t251 的 simulate,取净值曲线的逐日收益 + 名义占用(gross_ratio_hist)的统计。"""
    res = T251.simulate(engine_tickets, bars, {}, cap_frac,
                         equity0=T343.OVERLAY_EQ0, risk_frac=risk_frac, cap_n=T343.OVERLAY_CAP_N)
    curve = res["curve"]
    if not curve:
        return pd.Series(dtype=float), {"error": "empty curve"}
    ds = [c[0] for c in curve]
    eq = [float(c[1]) for c in curve]
    s = pd.Series(eq, index=pd.to_datetime(pd.Series(ds))).sort_index()
    ret = s.pct_change()
    ret.iloc[0] = s.iloc[0] / T343.OVERLAY_EQ0 - 1.0
    gr = res.get("gross_ratio_hist") or []
    st = T343.T251.curve_stats(curve, T343.OVERLAY_EQ0)
    diag = dict(
        risk_frac=risk_frac, gross_cap=cap_frac, cap_n=T343.OVERLAY_CAP_N,
        equity0=T343.OVERLAY_EQ0,
        n_days=len(curve), curve_first=ds[0], curve_last=ds[-1],
        taken=len(res["taken"]),
        blocked_gross=len(res["blocked_gross"]),
        blocked_cap=len(res["blocked_cap"]),
        blocked_min=len(res["blocked_min"]),
        blocked_coin=len(res["blocked_coin"]),
        overlay_total_return=round(st["total_return"], 6),
        overlay_cagr=round(st["cagr"], 6) if st["cagr"] is not None else None,
        overlay_max_dd=round(st["max_dd"], 6),
        gross_ratio_peak=round(float(max(gr)), 6) if gr else None,
        gross_ratio_days_over_1=int(sum(1 for x in gr if x > 1.0)),
        gross_ratio_median=round(float(sorted(gr)[len(gr) // 2]), 6) if gr else None,
    )
    return ret, diag


def build_nav(legs: dict, cash_daily: pd.Series, overlay_ret: pd.Series, start: pd.Timestamp, end: pd.Timestamp):
    """L3 臂:RBv2 权重 + 现金计息 + R-v2 叠加。核 = `src/data/universe/flex_alloc.dynamic_mix_nav`。"""

    def fn_rb(hist, d):
        return FA.rb_weights(hist)

    nav, log = FA.dynamic_mix_nav(legs, fn_rb, reb=T343.REB, cost=T343.COST, start=start,
                                  cash_ret=cash_daily, overlay_ret=overlay_ret)
    return nav, log


def house_metrics(nav: pd.Series) -> dict:
    m = T343.metrics(nav)
    m.update(underwater(nav))
    m["yearly"] = T343.yearly(nav)
    return m


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
    print(f"[tickets] {len(tickets)} 张 / {len(need)} 个币 / bars {len(bars)};"
          f"出场原因不一致 {len(bad)} 张", flush=True)

    # ── 腿与窗口(照 t343 的 L3 装配)─────────────────────────────────────────
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
    nav_start_ok = nav_start.date().isoformat() == T343.NAV_START_EXPECT

    cal = pd.date_range(common[0], end, freq="D")
    apy_cal = apy.reindex(cal).ffill()
    apy_cal = apy_cal.where(apy_cal.index >= pd.Timestamp(T343.CASH_FIRST), 0.0)
    cash_daily = (apy_cal / 100.0 / 365.0)
    cash_daily.name = "cash_ret"
    print(f"[window] 共同日 {len(common)}  记账起点 {nav_start.date()}"
          f" (期望 {T343.NAV_START_EXPECT})", flush=True)

    out = {
        "meta": dict(card="T-349", lane="lane-a", ran_utc=t0.isoformat(),
                     spec_source="REFUTATION_LEDGER.md ## S-825 —(只读登记那一节)",
                     blind_note=("本文件不读 `## S-825 结果` 那一节、不读 docs/research/s825_*;"
                                 "C0 装配直接 import B 道的 docs/research/t343_blind.py,"
                                 "叠加引擎用 docs/research/t251_gross_cap.py:simulate(未改一字),"
                                 "票源 docs/research/t197_results.json → tickets.A。"),
                     window=[T343.NAV_START_EXPECT, T343.WINDOW_END],
                     reb=T343.REB, cost_bps=20,
                     overlay=dict(ticket_source="docs/research/t197_results.json → tickets.A",
                                  engine="docs/research/t251_gross_cap.py:simulate",
                                  cap_n=T343.OVERLAY_CAP_N, equity0=T343.OVERLAY_EQ0,
                                  c0=dict(f=C0_F, gross_cap=C0_CAP),
                                  grid=dict(f=F_GRID, gross_cap=CAP_GRID)),
                     criteria=dict(uw_tol_days=UW_TOL_DAYS, cagr_tol_pp=CAGR_TOL_PP,
                                   bite_tol_pp=BITE_TOL_PP),
                     c0_expect=dict(total_return=C0_TOTAL_EXPECT, uw_days=C0_UW_EXPECT)),
        "validation": {"nav_start_computed": nav_start.date().isoformat(),
                       "nav_start_expected": T343.NAV_START_EXPECT,
                       "nav_start_matches": bool(nav_start_ok),
                       "n_common_days": int(len(common)),
                       "common_first": common[0].date().isoformat(),
                       "common_last": common[-1].date().isoformat(),
                       "exit_reason_mismatch": len(bad),
                       "exit_reason_mismatch_sample": bad[:10],
                       "n_tickets": len(tickets)},
        "cells": {}, "c0": {}, "judgement": {},
    }

    def run_cell(key: str, risk_frac: float, cap_frac: float, tk: list[dict]) -> dict:
        ret, diag = run_overlay(tk, bars, risk_frac, cap_frac)
        nav, log = build_nav(legs_x1v, cash_daily, ret, nav_start, end)
        m = house_metrics(nav)
        w = pd.DataFrame([{c: r[c] for c in ("crypto", "equity", "gold")} for r in log])
        m["weights_mean"] = {c: round(float(w[c].mean()), 4) for c in w.columns}
        m["weights_max"] = {c: round(float(w[c].max()), 4) for c in w.columns}
        m["n_rebalances"] = int(len(log))
        cell = dict(key=key, risk_frac=risk_frac, gross_cap=cap_frac,
                    overlay=diag, metrics=m)
        out["cells"][key] = cell
        print(f"[{key}] f={risk_frac:.2%} cap={cap_frac:.2f} | 成交票 {diag['taken']} "
              f"(挡住:上限 {diag['blocked_gross']} 张) | total {m['total_return']:+.4%} "
              f"cagr {m['cagr']:+.4%} | uw_cal {m['uw_cal_days']} uw_tr {m['uw_trading_days']} "
              f"| mdd {m['max_drawdown']:+.4%} | 名义峰值 {diag['gross_ratio_peak']} "
              f"超1倍 {diag['gross_ratio_days_over_1']}天", flush=True)
        return cell

    # ── C0 自检(f 0.5% / 上限 0.40)───────────────────────────────────────────
    print("[C0] f=0.50% cap=0.40 …", flush=True)
    c0 = run_cell("C0", C0_F, C0_CAP, engine_tickets)
    c0m = c0["metrics"]
    c0["selfcheck"] = dict(
        total_return=round(c0m["total_return"], 6),
        total_expect=C0_TOTAL_EXPECT,
        total_ok=bool(abs(c0m["total_return"] - C0_TOTAL_EXPECT) < 0.0005),
        uw_cal_days=c0m["uw_cal_days"], uw_trading_days=c0m["uw_trading_days"],
        uw_expect=C0_UW_EXPECT,
        uw_ok_cal=bool(c0m["uw_cal_days"] == C0_UW_EXPECT),
        uw_ok_trading=bool(c0m["uw_trading_days"] == C0_UW_EXPECT),
    )
    print("[C0 selfcheck]", json.dumps(c0["selfcheck"], ensure_ascii=False), flush=True)
    out["c0"] = c0

    # ── 8 格 ─────────────────────────────────────────────────────────────────
    for f in F_GRID:
        for cap in CAP_GRID:
            run_cell(f"f{f*100:g}_cap{cap:g}", f, cap, engine_tickets)

    # ── 只报:去掉成交票里 r 最大的一张(每格各自找)────────────────────────────
    drop_cagr = {}
    for f in F_GRID:
        for cap in CAP_GRID:
            key = f"f{f*100:g}_cap{cap:g}"
            cell = out["cells"][key]
            taken = set()  # 重跑一次拿到 taken 的票 —— simulate 的 taken 是 tid 集合
            # 用该格自己的 taken(从 overlay 诊断里只有计数,这里从引擎重取)
            res = T251.simulate(engine_tickets, bars, {}, cap, equity0=T343.OVERLAY_EQ0,
                                risk_frac=f, cap_n=T343.OVERLAY_CAP_N)
            for t in engine_tickets:
                if t["tid"] in res["taken"] and t.get("r") is not None:
                    taken.add(t["tid"])
            if not taken:
                drop_cagr[key] = dict(error="no taken ticket with r")
                continue
            worst = max((t for t in engine_tickets if t["tid"] in taken),
                        key=lambda t: t["r"])
            tk2 = [t for t in engine_tickets if t["tid"] != worst["tid"]]
            ret2, diag2 = run_overlay(tk2, bars, f, cap)
            nav2, _ = build_nav(legs_x1v, cash_daily, ret2, nav_start, end)
            m2 = house_metrics(nav2)
            drop_cagr[key] = dict(dropped=dict(symbol=worst["symbol"], signal_d=worst["signal_d"],
                                               tid=worst["tid"], r=worst["r"]),
                                  cagr=m2["cagr"], total_return=m2["total_return"],
                                  uw_cal_days=m2["uw_cal_days"], uw_trading_days=m2["uw_trading_days"],
                                  max_drawdown=m2["max_drawdown"],
                                  worst_month=m2["worst_month"], worst_month_key=m2["worst_month_key"],
                                  taken_after=diag2["taken"], blocked_gross_after=diag2["blocked_gross"],
                                  gross_ratio_peak_after=diag2["gross_ratio_peak"])
            print(f"[drop-r] {key} 去掉 {worst['symbol']}@{worst['signal_d']} (r={worst['r']:.3f}) "
                  f"→ cagr {m2['cagr']:+.4%} (原 {cell['metrics']['cagr']:+.4%})", flush=True)

    # C0 自己的「去掉 r 最大一张」(同样只报)—— 给 Jazz 并排看
    res0 = T251.simulate(engine_tickets, bars, {}, C0_CAP, equity0=T343.OVERLAY_EQ0,
                         risk_frac=C0_F, cap_n=T343.OVERLAY_CAP_N)
    tk0 = [t for t in engine_tickets if t["tid"] in res0["taken"] and t.get("r") is not None]
    if tk0:
        w0 = max(tk0, key=lambda t: t["r"])
        tk2 = [t for t in engine_tickets if t["tid"] != w0["tid"]]
        ret2, diag2 = run_overlay(tk2, bars, C0_F, C0_CAP)
        nav2, _ = build_nav(legs_x1v, cash_daily, ret2, nav_start, end)
        m2 = house_metrics(nav2)
        drop_cagr["C0"] = dict(dropped=dict(symbol=w0["symbol"], signal_d=w0["signal_d"],
                                            tid=w0["tid"], r=w0["r"]),
                               cagr=m2["cagr"], total_return=m2["total_return"],
                               uw_cal_days=m2["uw_cal_days"], uw_trading_days=m2["uw_trading_days"],
                               max_drawdown=m2["max_drawdown"],
                               worst_month=m2["worst_month"], worst_month_key=m2["worst_month_key"],
                               taken_after=diag2["taken"], blocked_gross_after=diag2["blocked_gross"],
                               gross_ratio_peak_after=diag2["gross_ratio_peak"])
        print(f"[drop-r] C0 去掉 {w0['symbol']}@{w0['signal_d']} (r={w0['r']:.3f}) "
              f"→ cagr {m2['cagr']:+.4%} (原 {c0m['cagr']:+.4%})", flush=True)
    out["drop_max_r"] = drop_cagr

    # ── 判据 ────────────────────────────────────────────────────────────────
    c0_cagr = c0m["cagr"]
    uw_ref = c0m["uw_cal_days"] if c0["selfcheck"]["uw_ok_cal"] else c0m["uw_trading_days"]
    uw_ref_kind = "cal" if c0["selfcheck"]["uw_ok_cal"] else "trading"
    cagr_thr = c0_cagr + CAGR_TOL_PP / 100.0
    uw_thr = uw_ref + UW_TOL_DAYS

    per_f = {}
    for f in F_GRID:
        a = out["cells"][f"f{f*100:g}_cap1.2"]["metrics"]
        b = out["cells"][f"f{f*100:g}_cap2"]["metrics"]
        bite_pp = abs(a["cagr"] - b["cagr"]) * 100.0
        cells = {}
        for cap, m in ((1.20, a), (2.00, b)):
            i_ok = m["uw_cal_days"] <= uw_thr
            ii_ok = m["cagr"] >= cagr_thr
            cells[f"{cap:g}"] = dict(cagr=m["cagr"], uw_cal_days=m["uw_cal_days"],
                                     uw_trading_days=m["uw_trading_days"],
                                     max_drawdown=m["max_drawdown"],
                                     worst_month=m["worst_month"], worst_month_key=m["worst_month_key"],
                                     i_uw=dict(value=m["uw_cal_days"], thr=uw_thr, ok=bool(i_ok),
                                               text=f"最长水下 ≤ C0+{UW_TOL_DAYS} 天"),
                                     ii_cagr=dict(value=m["cagr"], thr=cagr_thr, ok=bool(ii_ok),
                                                  text=f"CAGR ≥ C0+{CAGR_TOL_PP}pp/年"),
                                     stand=bool(i_ok and ii_ok))
        f_ok = all(v["stand"] for v in cells.values()) and bite_pp < BITE_TOL_PP
        per_f[f"{f*100:g}"] = dict(risk_frac=f, cells=cells,
                                   bite_cagr_diff_pp=round(bite_pp, 4),
                                   iii_bite=dict(value_pp=round(bite_pp, 4), thr_pp=BITE_TOL_PP,
                                                 ok=bool(bite_pp < BITE_TOL_PP),
                                                 text="同一 f 在上限 1.20 与 2.00 下 CAGR 差 < 1pp"),
                                   stand=bool(f_ok))
        print(f"[judge] f={f*100:g}%  bite Δcagr {bite_pp:.3f}pp  cells "
              f"1.20:{cells['1.2']['stand']} 2.00:{cells['2']['stand']}  → 站住 {f_ok}", flush=True)

    # f★ = 最大的、自己站住且所有更小的 f 也都站住的 f
    fstar = None
    for f in sorted(F_GRID):
        if per_f[f"{f*100:g}"]["stand"]:
            fstar = f
        else:
            break
    out["judgement"] = dict(
        c0=dict(cagr=c0_cagr, total_return=c0m["total_return"],
                uw_cal_days=c0m["uw_cal_days"], uw_trading_days=c0m["uw_trading_days"],
                uw_ref_used=uw_ref, uw_ref_kind=uw_ref_kind,
                max_drawdown=c0m["max_drawdown"], worst_month=c0m["worst_month"],
                worst_month_key=c0m["worst_month_key"], yearly=c0m["yearly"]),
        thresholds=dict(cagr_thr=round(cagr_thr, 6), uw_thr=uw_thr),
        per_f=per_f, f_star=fstar,
        f_star_rule="最大的、自己站住且所有更小的 f 也都站住的 f(连续区间,不要孤点)",
    )
    print(f"[judge] f★ = {fstar}", flush=True)

    json.dump(out, open(OUT_JSON, "w"), indent=1, default=str)
    print("[out]", OUT_JSON)

    # ── 摘要表(md)───────────────────────────────────────────────────────────
    lines = ["# T-349 摘要(S-825 盲复算 · lane-a)", "",
             f"跑于 {t0.isoformat()} · 窗口 {out['meta']['window'][0]} → {out['meta']['window'][1]}",
             "",
             "## C0 自检", "",
             f"- 起点 {out['validation']['nav_start_computed']}(期望 {T343.NAV_START_EXPECT})"
             f"· 出场原因不一致 {out['validation']['exit_reason_mismatch']} 张",
             f"- total {c0m['total_return']:+.4%}(期望 {C0_TOTAL_EXPECT:+.4%})· "
             f"CAGR {c0_cagr:+.4%}· 最长水下 cal {c0m['uw_cal_days']} / trading {c0m['uw_trading_days']}"
             f"(期望 {C0_UW_EXPECT})· 回撤 {c0m['max_drawdown']:+.4%}",
             "",
             "## 8 格", "",
             "| f | 上限 | 成交票 | 挡住(上限/张数/同币) | CAGR | 最长水下 | 回撤 | 最差月 | 去掉 r 最大一张后 CAGR | 名义峰值 | 超 1 倍天数 | 站住 |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for f in F_GRID:
        for cap in CAP_GRID:
            key = f"f{f*100:g}_cap{cap:g}"
            c = out["cells"][key]
            m = c["metrics"]
            o = c["overlay"]
            d = drop_cagr.get(key, {})
            st = per_f[f"{f*100:g}"]["cells"][f"{cap:g}"]
            lines.append(
                f"| {f*100:g}% | {cap:g} | {o['taken']} | {o['blocked_gross']} / {o['blocked_cap']} / {o['blocked_coin']} | "
                f"{m['cagr']:+.2%} | "
                f"{m['uw_cal_days']} | {m['max_drawdown']:+.1%} | {m['worst_month']:+.1%}"
                f"({m['worst_month_key']}) | {d.get('cagr')} | {o['gross_ratio_peak']} | "
                f"{o['gross_ratio_days_over_1']} | {'✅' if st['stand'] else '❌'} |")
    c0d = drop_cagr.get("C0", {})
    lines.append(
        f"| **C0 0.50%** | **0.40** | {c0['overlay']['taken']} | "
        f"{c0['overlay']['blocked_gross']} / {c0['overlay']['blocked_cap']} / {c0['overlay']['blocked_coin']} | "
        f"**{c0m['cagr']:+.2%}** | {c0m['uw_cal_days']} | {c0m['max_drawdown']:+.1%} | "
        f"{c0m['worst_month']:+.1%}({c0m['worst_month_key']}) | {c0d.get('cagr')} | "
        f"{c0['overlay']['gross_ratio_peak']} | {c0['overlay']['gross_ratio_days_over_1']} | (基准) |")
    lines += ["", "## 逐年", ""]
    for f in F_GRID:
        for cap in CAP_GRID:
            key = f"f{f*100:g}_cap{cap:g}"
            y = out["cells"][key]["metrics"]["yearly"]
            lines.append(f"- {key}: " + " / ".join(f"{k} {v:+.1%}" for k, v in y.items()))
    lines += ["", "## 判", "",
              f"阈值:CAGR ≥ {cagr_thr:+.4%} · 最长水下 ≤ {uw_thr} 天(以 {uw_ref_kind} 口径)· "
              f"咬合 < {BITE_TOL_PP}pp", "",
              "| f | 1.20 站住 | 2.00 站住 | 咬合 Δcagr | 站住 |", "|---|---|---|---|---|"]
    for f in F_GRID:
        p = per_f[f"{f*100:g}"]
        lines.append(f"| {f*100:g}% | {'✅' if p['cells']['1.2']['stand'] else '❌'} | "
                     f"{'✅' if p['cells']['2']['stand'] else '❌'} | {p['bite_cagr_diff_pp']:.3f}pp | "
                     f"{'✅' if p['stand'] else '❌'} |")
    lines += ["", f"**f★ = {fstar}**", ""]
    open(OUT_MD, "w").write("\n".join(lines))
    print("[out]", OUT_MD)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
