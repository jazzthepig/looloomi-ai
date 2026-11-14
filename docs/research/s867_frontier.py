"""S-867(T-387):R-v2 三参数(每票风险 f / 名义上限 cap / 名额 n)的前沿 + 被动腿移出实盘在历史上值多少。

装配、数据、引擎与 `s834_diversification_audit.py` **完全相同**(t310_slots / t352_engine / flex_alloc.rb_weights /
docs/research/t342_daily.csv / cometcloud-local/research/ 下的 s681 与 t156);**不改 s834**,这里只是把它的装配
包成可以按参数重跑的函数。窗口 2021-10-11 → t342_daily.csv 的末日。

用法(任意目录均可):
  python3 docs/research/s867_frontier.py [<t342_daily.csv>] [<cometcloud-local/research/>]
  S867_CELLS="0.0075:0.80:10,0.0025:0.40:10"   # 只跑这几格(冒烟用);默认跑满 16 格
产物: docs/research/s867_results.json · docs/research/s867_run.txt
"""
import bisect
import importlib.util
import json
import math
import os
import sys
import time
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, REPO)

import t310_slots as T310                                   # noqa: E402
from src.data.universe import flex_alloc as fa              # noqa: E402

_sp = importlib.util.spec_from_file_location("t352_engine", os.path.join(HERE, "t352_engine.py"))
E1 = importlib.util.module_from_spec(_sp)
_sp.loader.exec_module(E1)

CSV = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "t342_daily.csv")
R = sys.argv[2] if len(sys.argv) > 2 else "/Volumes/CometCloudAI/cometcloud-local/research/"
T310.UM = R + "s681/_um_daily.jsonl"
T310.STYLE = R + "t156/_style.json"

START = pd.Timestamp("2021-10-11")
EQ0 = 630.0
SRC = ["crypto", "equity", "gold", "rv2", "cash"]
FS = [0.0025, 0.00375, 0.005, 0.0075]
CAPS = [0.40, 0.80]
NS = [10, 14]
BASE_CELL = (0.0075, 0.80, 10)          # 真钱现配置(S-831 / S-834 的那一点)

LOG = []


def log(msg=""):
    print(msg, flush=True)
    LOG.append(str(msg))


# ── 装配(与 s834 同一套)────────────────────────────────────────────────────────────────────────
d = pd.read_csv(CSV, parse_dates=["date"]).set_index("date")
legs_px = {"crypto": d.crypto_leg_nav_x1v, "equity": d.equity_close_acwi, "gold": d.gold_close_xauusd}
cal = pd.date_range(d.index[0], d.index[-1], freq="D")
cash_rate = d.cash_daily_rate.reindex(cal).ffill().fillna(0.0)

_t0 = time.time()
raw, _ = T310.load_tickets()
bars = T310.load_bars({t["symbol"] for t in raw})
exits, _ = T310.classify_exits(raw, bars)
TK = T310.to_engine_tickets(raw, exits)
gate_d, _, _ = T310.load_gate()
log(f"[装配] 票 {len(TK)} 张 / 标的 {len(bars)} 个 / 闸门 {len(gate_d)} 天,用时 {time.time() - _t0:.1f}s")

CLOSE = {s: {r[0]: r[4] for r in rows} for s, rows in bars.items()}
DATES = {s: [r[0] for r in rows] for s, rows in bars.items()}


def close_mark(sym, day_iso):
    m = CLOSE.get(sym)
    if not m:
        return None
    px = m.get(day_iso)
    if px is not None:
        return px
    ds = DATES.get(sym) or []
    i = bisect.bisect_right(ds, day_iso) - 1
    return m[ds[i]] if i >= 0 else None


# ── 引擎跑一次(给定参数)─────────────────────────────────────────────────────────────────────
def run_engine(tickets, f, cap, n):
    res = E1.simulate(tickets, bars, gate_d, cap, equity0=EQ0, risk_frac=f, cap_n=n, fix=True)
    rv2 = pd.Series({pd.Timestamp(r[0]): float(r[1]) for r in res["curve"]}).sort_index().pct_change().dropna()
    return res, rv2


def ticket_contrib(res):
    """每张票对净值的贡献(美元):已实现(per_tid)+ 窗口末仍未平仓的浮盈。合计 = 末净值 − 起始净值。"""
    out = dict(res["per_tid"])
    last = res["curve"][-1][0]
    for tid, p in res["final_book"].items():
        px = close_mark(p["symbol"], last)
        if px is None:
            continue
        out[tid] = out.get(tid, 0.0) + p["qty"] * (px - p["entry_px"]) - p["qty"] * 0.002 * p["entry_px"]
    return out


# ── 账户记账(s834 第 37–53 行逐字搬过来,加 zero_legs 开关)─────────────────────────────────
DF = pd.concat(legs_px, axis=1).dropna().sort_index()
RETS = DF.pct_change()
IDX = [x for x in DF.index if x >= START]
BETWEEN = fa._between


def build_account(rv2, zero_legs=()):
    """zero_legs 非空 ⇒ 把这些腿的目标权重改成 0,空出来的那部分按 (1 − Σ权重) 记现金利息。"""
    zl = list(zero_legs)

    def target(day):
        w = pd.Series(fa.rb_weights(RETS.loc[:day].iloc[1:])).reindex(list(fa.LEGS)).fillna(0.0)
        if zl:
            w = w.copy()
            w[zl] = 0.0
        return w

    tgt = target(IDX[0])
    hold = tgt.copy()
    rows, nav = [], 1.0
    for i, day in enumerate(IDX[1:], start=1):
        row = RETS.loc[day, list(fa.LEGS)]
        prev = IDX[i - 1]
        c = {k: float(hold[k] * row[k]) for k in fa.LEGS}
        w_cash = 1.0 - float(hold.sum())
        c["cash"] = w_cash * BETWEEN(cash_rate, prev, day)
        c["rv2"] = BETWEEN(rv2, prev, day)
        g = sum(c.values())
        nav *= 1 + g
        hold = hold * (1 + row) / (1 + g)
        if i % 21 == 0:
            new = target(day)
            cost = float((hold - new).abs().sum()) * 20 / 1e4
            nav *= 1 - cost
            c["cost"] = -cost
            hold = new.copy()
        rows.append({"d": day, **c, "acct": g + c.get("cost", 0.0), "nav": nav, "cashw": w_cash})
    return pd.DataFrame(rows).set_index("d").fillna(0.0)


# ── 指标 ───────────────────────────────────────────────────────────────────────────────────
def underwater_days(nav):
    """最长水下:净值低于前高、到窗口末也没收复的最长自然日数。"""
    peak_v, peak_d = float(nav.iloc[0]), nav.index[0]
    worst = 0
    for day, v in nav.items():
        if float(v) > peak_v:
            worst = max(worst, (day - peak_d).days)
            peak_v, peak_d = float(v), day
    worst = max(worst, (nav.index[-1] - peak_d).days)
    return int(worst)


def underwater_open_from(nav):
    """当前仍未收复的那一段水下,起点是最后一次创新高的那天。"""
    peak_v, peak_d = float(nav.iloc[0]), nav.index[0]
    for day, v in nav.items():
        if float(v) > peak_v:
            peak_v, peak_d = float(v), day
    return peak_d


def cagr_seg(nav, d0, d1, base):
    """一段窗口的年化(按自然日折年 365.25)。base = d0 之前的净值。"""
    sub = nav.loc[(nav.index >= d0) & (nav.index <= d1)]
    days = (d1 - d0).days
    if len(sub) == 0 or days <= 0:
        return None
    return float((float(sub.iloc[-1]) / base) ** (365.25 / days) - 1)


def metrics(C):
    nav = C["nav"]
    Am = (1 + C["acct"]).resample("M").prod() - 1
    Cm = pd.DataFrame({k: C[k].resample("M").sum() for k in SRC})
    rc = {k: float(np.cov(Cm[k], Am)[0, 1] / Am.var()) for k in SRC}
    w = np.clip(list(rc.values()), 1e-9, None)
    w = w / w.sum()
    ent = float(np.exp(-sum(float(x) * math.log(float(x)) for x in w)))
    dd = nav / nav.cummax() - 1.0
    pk_i = int(nav.values.argmax())
    pk_d = nav.index[pk_i]
    pk_v = float(nav.iloc[pk_i])
    tr_i = int(dd.values.argmin())
    # 当前仍未收复的那一段水下:从最后一次创新高到窗口末
    r20 = (1 + C["acct"]).rolling(20).apply(np.prod) - 1
    e20 = r20.idxmin()
    s20 = C.index[max(0, C.index.get_loc(e20) - 19)]
    m = len(IDX) // 2
    h1_end = IDX[m - 1]
    h1_base = 1.0
    nav_h1 = float(nav.loc[nav.index <= h1_end].iloc[-1])
    return {
        "cagr": float(nav.iloc[-1] ** (365.25 / (IDX[-1] - IDX[0]).days) - 1),
        "vol_ann_monthly": float(Am.std() * np.sqrt(12)),
        "worst_month": [str(Am.idxmin().date()), float(Am.min())],
        "underwater_days": underwater_days(nav),
        "nav_peak": pk_v,
        "nav_peak_date": str(pk_d.date()),
        "nav_trough": float(nav.iloc[tr_i]),
        "nav_trough_date": str(nav.index[tr_i].date()),
        "nav_end": float(nav.iloc[-1]),
        "nav_vs_peak_pct": float(nav.iloc[-1] / pk_v - 1.0),
        "underwater_open_from": str(underwater_open_from(nav).date()),
        "max_dd": float(dd.min()),
        "worst_20d": float(r20.min()),
        "worst_20d_window": f"{s20.date()}→{e20.date()}",
        "rv2_risk_share": rc["rv2"],
        "risk_contribution": {k: round(v, 3) for k, v in rc.items()},
        "eff_sources": ent,
        "cagr_1st_half": cagr_seg(nav, IDX[0], h1_end, h1_base),
        "cagr_2nd_half": cagr_seg(nav, h1_end, IDX[-1], nav_h1),
        "cash_share_mean": float(C["cashw"].mean()),
        "months": int(len(Am)),
        "end_nav": float(nav.iloc[-1]),
    }


# ── 一格(参数 + 是否去掉最大一张票)────────────────────────────────────────────────────────────
def cell(f, cap, n, drop_tid=None, zero_legs=()):
    tickets = TK if drop_tid is None else [t for t in TK if t["tid"] != drop_tid]
    res, rv2 = run_engine(tickets, f, cap, n)
    C = build_account(rv2, zero_legs=zero_legs)
    m = metrics(C)
    m["n_taken"] = len(res["taken"])
    m["end_equity"] = float(res["curve"][-1][1])
    return res, m


def top_ticket(res):
    contrib = ticket_contrib(res)
    total = sum(contrib.values())
    if not contrib:
        return None, 0.0, 0.0
    tid, amt = max(contrib.items(), key=lambda kv: kv[1])
    return tid, amt, total


# ── 跑 ───────────────────────────────────────────────────────────────────────────────────
def main():
    t0 = time.time()
    ref = json.load(open(os.path.join(HERE, "s834_results.json")))
    log(f"# S-867 / T-387 · R-v2 三参数前沿 · 窗口 {IDX[0].date()} → {IDX[-1].date()} · {len(IDX)} 个交易日")
    log(f"# 产物: docs/research/s867_results.json · docs/research/s867_run.txt")

    cells = [(f, c, n) for f in FS for c in CAPS for n in NS]
    env_cells = os.environ.get("S867_CELLS")
    if env_cells:
        cells = [tuple(float(x) if i < 2 else int(x) for i, x in enumerate(c.split(":"))) for c in env_cells.split(",")]
        log(f"[冒烟] 只跑 {cells}")

    # ① 复现:先跑现配置那一格,与 s834_results.json 对表
    res_b, m_b = cell(*BASE_CELL)
    checks = [
        ("年化 cagr", m_b["cagr"], ref["acct"]["cagr"], 0.001),
        ("月度波动折年", m_b["vol_ann_monthly"], ref["acct"]["vol_ann_monthly"], 0.001),
        ("R-v2 风险占比", m_b["rv2_risk_share"], ref["risk_contribution"]["full"]["rv2"], 0.01),
        ("有效来源数(熵)", m_b["eff_sources"], ref["effective_sources"]["entropy_full"], 0.01),
    ]
    log("\n## 复现(f=0.0075 / cap=0.80 / n=10)vs docs/research/s834_results.json")
    ok = True
    for name, got, want, tol in checks:
        d = abs(float(got) - float(want))
        flag = "OK" if d <= tol else "不一致"
        if d > tol:
            ok = False
        log(f"  {name}: 本脚本 {float(got):.6g} vs s834 {float(want):.6g} | 差 {d:.6g} (容差 {tol}) → {flag}")
    if not ok:
        log("\n!! 复现不一致 —— 按卡上要求停下,贴两边的数,不往下做。")
        json.dump({"repro_ok": False, "checks": [{"name": n, "got": float(g), "ref": float(w), "diff": abs(float(g) - float(w))} for n, g, w, _ in checks]},
                  open(os.path.join(HERE, "s867_results.json"), "w"), indent=1, ensure_ascii=False)
        open(os.path.join(HERE, "s867_run.txt"), "w").write("\n".join(LOG) + "\n")
        return 1
    log("  → 复现通过")

    # ② A 表 16 格
    A = {}
    for (f, c, n) in cells:
        t1 = time.time()
        res, m = cell(f, c, n)
        tid, amt, tot = top_ticket(res)
        if tid is not None:
            _, m2 = cell(f, c, n, drop_tid=tid)
            m["cagr_no_top"] = m2["cagr"]
            m["no_top"] = {"tid": tid, "contrib_usd": amt, "contrib_pct_eq0": amt / EQ0,
                           "cagr": m2["cagr"], "max_dd": m2["max_dd"], "underwater_days": m2["underwater_days"],
                           "rv2_risk_share": m2["rv2_risk_share"], "eff_sources": m2["eff_sources"]}
        else:
            m["cagr_no_top"] = None
            m["no_top"] = None
        m["f"], m["cap"], m["n"] = f, c, n
        m["contrib_sum_check"] = tot
        m["equity_check"] = m["end_equity"] - EQ0
        A[f"{f:.4f}|{c:.2f}|{n}"] = m
        log(f"[A] f={f} cap={c} n={n} 年化 {m['cagr']*100:.1f}% 波动 {m['vol_ann_monthly']*100:.1f}% "
            f"水下 {m['underwater_days']}d 回撤 {m['max_dd']*100:.1f}% rv2风险 {m['rv2_risk_share']:.3f} "
            f"熵 {m['eff_sources']:.2f} 去最大票后 {m['cagr_no_top']*100:.1f}% "
            f"[{m['no_top']['tid'] if m['no_top'] else '-'}] 用时 {time.time()-t1:.1f}s")

    # ③ 判(A 表,事前写死的规则)
    cand = [m for m in A.values() if m["rv2_risk_share"] <= 0.40 and m["eff_sources"] >= 3.0]
    sel = None
    if cand:
        best = min(m["underwater_days"] for m in cand)
        near = [m for m in cand if m["underwater_days"] - best < 30]
        sel = max(near, key=lambda m: m["cagr_no_top"])
        rule = f"候选 {len(cand)} 格;最短水下 {best} 天;差 <30 天的有 {len(near)} 格 → 取「去最大票后年化」最高"
    else:
        rule = "这张网格里没有满足 40% 线的点"

    # ④ B 表:同参数,被动腿移出实盘
    resB, mB = cell(*BASE_CELL)
    tidB, amtB, _ = top_ticket(resB)
    if tidB is not None:
        _, mB2 = cell(*BASE_CELL, drop_tid=tidB)
    else:
        mB2 = None
    _, mB_nolegs = cell(*BASE_CELL, zero_legs=("equity", "gold"))
    if tidB is not None:
        _, mB_nolegs2 = cell(*BASE_CELL, drop_tid=tidB, zero_legs=("equity", "gold"))
    else:
        mB_nolegs2 = None
    B = [
        {"row": "现状(带股、金两条腿)", **{k: v for k, v in mB.items() if k != "no_top"},
         "cagr_no_top": (mB2 or {}).get("cagr"), "no_top_tid": tidB},
        {"row": "股、金权重改 0、那部分记现金利息",
         **{k: v for k, v in mB_nolegs.items() if k != "no_top"},
         "cagr_no_top": (mB_nolegs2 or {}).get("cagr"), "no_top_tid": tidB},
    ]

    # ⑤ 打印
    def row_str(m):
        return (f"f={m['f']:.4f} cap={m['cap']:.2f} n={m['n']:2d} | 年化 {m['cagr']*100:6.1f}% | 波动 {m['vol_ann_monthly']*100:5.1f}% | "
                f"水下 {m['underwater_days']:4d}d | 回撤 {m['max_dd']*100:6.1f}% | 最差20日 {m['worst_20d']*100:6.1f}% | "
                f"rv2风险 {m['rv2_risk_share']:.3f} | 熵 {m['eff_sources']:.2f} | 去最大票后年化 "
                f"{(m['cagr_no_top']*100 if m['cagr_no_top'] is not None else float('nan')):6.1f}% | "
                f"前半 {(m['cagr_1st_half']*100 if m['cagr_1st_half'] is not None else float('nan')):6.1f}% | "
                f"后半 {(m['cagr_2nd_half']*100 if m['cagr_2nd_half'] is not None else float('nan')):6.1f}% | "
                f"最大票 {(m['no_top']['tid'] if m['no_top'] else '-')}")

    log("\n## A 表(16 格)")
    for k in sorted(A, key=lambda k: (A[k]["f"], A[k]["cap"], A[k]["n"])):
        log("  " + row_str(A[k]))
    log(f"\n## 判:候选 = 风险占比 ≤ 0.40 且 有效来源数 ≥ 3.0;取最长水下最短的;相差 <30 天取「去最大票后年化」更高")
    log(f"  {rule}")
    if sel:
        log(f"  选中格: {row_str(sel)}")
        log(f"    最大票 {sel['no_top']['tid']} 贡献 {sel['no_top']['contrib_usd']:.2f} 美元"
            f"({sel['no_top']['contrib_pct_eq0']*100:.2f}% 起始净值);去掉后 年化 {sel['no_top']['cagr']*100:.1f}%、"
            f"回撤 {sel['no_top']['max_dd']*100:.1f}%、水下 {sel['no_top']['underwater_days']} 天、"
            f"rv2 风险 {sel['no_top']['rv2_risk_share']:.3f}、熵 {sel['no_top']['eff_sources']:.2f}")
    log("\n## B 表(f=0.0075 / cap=0.80 / n=10)")
    for b in B:
        log(f"  {b['row']}: 年化 {b['cagr']*100:.1f}% | 波动 {b['vol_ann_monthly']*100:.1f}% | 水下 {b['underwater_days']}d | "
            f"回撤 {b['max_dd']*100:.1f}% | 最差20日 {b['worst_20d']*100:.1f}% | rv2风险 {b['rv2_risk_share']:.3f} | "
            f"熵 {b['eff_sources']:.2f} | 去最大票后年化 {(b['cagr_no_top']*100 if b['cagr_no_top'] is not None else float('nan')):.1f}% | "
            f"前半 {(b['cagr_1st_half']*100):.1f}% | 后半 {(b['cagr_2nd_half']*100):.1f}% | 现金权重均值 {b['cash_share_mean']*100:.1f}%")
    if B[1]["cagr_no_top"] is not None:
        log(f"  差额(移出被动腿): 年化 {(B[1]['cagr']-B[0]['cagr'])*100:+.1f} pp | "
            f"水下 {B[1]['underwater_days']-B[0]['underwater_days']:+d} 天 | "
            f"回撤 {(B[1]['max_dd']-B[0]['max_dd'])*100:+.1f} pp | "
            f"去最大票后年化 {(B[1]['cagr_no_top']-B[0]['cagr_no_top'])*100:+.1f} pp")

    out = {
        "task": "T-387", "ledger": "S-867",
        "window": [str(IDX[0].date()), str(IDX[-1].date())], "n_trading_days": len(IDX),
        "repro_ok": True,
        "repro_checks": [{"name": n, "got": float(g), "ref": float(w), "diff": abs(float(g) - float(w)), "tol": t} for n, g, w, t in checks],
        "A_table": A, "A_selection": {"rule": rule, "selected": ({k: v for k, v in sel.items()} if sel else None),
                                      "n_candidates": len(cand)},
        "B_table": B,
        "run_seconds": round(time.time() - t0, 1),
    }
    json.dump(out, open(os.path.join(HERE, "s867_results.json"), "w"), indent=1, ensure_ascii=False, default=str)
    open(os.path.join(HERE, "s867_run.txt"), "w").write("\n".join(LOG) + "\n")
    log(f"\n[完成] 用时 {time.time()-t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
