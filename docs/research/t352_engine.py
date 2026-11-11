#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T-352 / S-828 —— 修 `t251_gross_cap.simulate` 的「幽灵仓」(进场当天就被止损的票永不出场)。

**错在哪(S-828)。** 旧引擎每天的顺序是:① 开盘出场(stop / 破 SMA20)② 当天进场 ③ 收盘出场(到期 / 停更)。
`exit_d == entry_d` 的票(进场当根就被止损打掉)的出场事件落在 ①,而它 ② 才进场 ⇒ 出场指令在它
进场**之前**就执行了、落空 ⇒ 这张票**永远不出场**:永久占一个名额、永久占着那个币(挡同币新票)、
永久按市价计入净值与名义。14 个名额被这种仓位塞住之后,后面的票大多因「满仓」进不来
(成交 208 张;修掉之后 358 张 —— Seth 的 S-828 预览)。

**修法(S-828 登记的修法)。** 同日出场(`exit_d == entry_d`)挪到当天进场**之后**处理;票与规则
一字不动,仓位、名义、取整、跳过规则全部照旧。

**不变量(脚本内断言,跑不过就 abort)。**
  ① 没有一张票在 `exit_d` 之后还在 book 里;
  ② 窗口末 book 里只剩 t197 标记 still 的票;
  ③ 成交票的已实现盈亏之和 = Σ(r × 该票进场时的每票风险额),差 < 1e-6 × 净值。

**旧引擎当对照跑一遍**(不修的版本必然被 ① / ② / ③ 拦下)—— 这是「断言真的能抓到这个 bug」的证据。

只读、不入库。数据:`docs/research/t197_results.json`(票源)+ Mac 数据根
`research/s681/_um_daily.jsonl`(K 线)+ `research/t156/_style.json`(闸门)。
"""
from __future__ import annotations

import bisect
import datetime as dt
import json
import math
import os
import sys
import time
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import t251_gross_cap as T251          # noqa: E402 —— 引擎原件(不改一字)
import t251_gross_cap_t197 as DRV      # noqa: E402 —— 票源/数据/闸门的取数层(不改一字)

EQ0 = 630.0                # 起始净值(与 T-251 / T-310 同)
F = 0.005                  # 每票风险占净值 0.5%(卡)
MIN_NOTIONAL = 10.0        # HL 最小名义额
STOP_ATR = 2.5             # 与 T-159 逐字一致
CAP_N_INF = 999            # ∞ 的代理(引擎只做 len(book) >= cap_n 比较)

OUT_JSON = os.path.join(HERE, "t352_results.json")
REPORT_MD = os.path.join(HERE, "T-352_engine_fix.md")


# ── 引擎(修版 + 不变量所需的逐票记账)──────────────────────────────────────────────
def simulate(tickets, bars, gate, cap_frac, equity0=EQ0, risk_frac=F,
             cap_n=10, min_notional=MIN_NOTIONAL, exact_qty=False, fix=True):
    """`t251_gross_cap.simulate` 的修版。

    fix=False ⇒ 与原件**逐位相同**(本脚本用 T251.simulate 对表验证);
    fix=True  ⇒ 同日出场(exit_d == entry_d)挪到当天进场之后处理。

    多出来的记账(只为跑不变量,不影响任何数值):per_tid(逐票已实现盈亏)、
    qty_by_tid(逐票下单数量)、pop_day(逐票出场处理日)、final_book(窗口末的 book)。
    """
    om, cm, dates = {}, {}, {}
    for s, rws in bars.items():
        om[s] = {r[0]: r[1] for r in rws}
        cm[s] = {r[0]: r[4] for r in rws}
        dates[s] = [r[0] for r in rws]

    def mark(sym, day, use_open):
        m = om if use_open else cm
        dk = day.isoformat() if isinstance(day, dt.date) else day
        px = m.get(sym, {}).get(dk)
        if px is not None:
            return px
        ds = dates.get(sym) or []
        i = bisect.bisect_right(ds, dk) - 1
        return cm[sym][ds[i]] if i >= 0 else None

    entries = defaultdict(list)
    for t in tickets:
        if t.get("filled") and t["entry_d"] and t["entry_px"]:
            entries[t["entry_d"]].append(t)
    for d in entries:
        entries[d].sort(key=lambda t: (t["signal_d"], t["symbol"]))

    exits_open = defaultdict(list)    # 止损 / 破 SMA20:当天开盘平
    exits_close = defaultdict(list)   # 120 根到期 / 停更:当天收盘平
    exits_same = defaultdict(list)    # ★ 修版新增:同日出场(进场当根就被打掉)
    for t in tickets:
        if not t["exit_d"] or t["exit_px"] is None:
            continue
        if fix and t["exit_d"] == t["entry_d"]:
            exits_same[t["exit_d"]].append(t)
            continue
        (exits_open if t["exit_reason"] in ("stop", "sma20") else exits_close)[t["exit_d"]].append(t)

    days = []
    d = dt.date.fromisoformat(min(entries)) if entries else dt.date(2020, 7, 1)
    ex = [dt.date.fromisoformat(t["exit_d"]) for t in tickets if t["exit_d"]]
    last = max(ex + [d])
    while d <= last:
        days.append(d)
        d += dt.timedelta(days=1)

    book = {}
    realized = 0.0
    curve = []
    taken, blocked_gross, blocked_cap, blocked_min, blocked_coin = set(), [], [], [], []
    gross_hist, gross_ratio_hist = [], []
    held = set()
    per_tid = {}          # tid -> 已实现盈亏(只读记账)
    qty_by_tid = {}       # tid -> 下单数量
    pop_day = {}          # tid -> 出场处理日
    viol_late = []        # ① 的逐日现场证据

    def equity(day, use_open):
        e = equity0 + realized
        for p in book.values():
            px = mark(p["symbol"], day, use_open)
            if px is None:
                continue
            e += p["qty"] * (px - p["entry_px"]) - p["qty"] * 0.002 * p["entry_px"]
        return e

    def close_pos(t, p, ds):
        """结掉一个仓位:原件的算式一字不改。"""
        nonlocal realized
        amt = p["qty"] * (p["exit_px"] - p["entry_px"] - 0.004 * p["entry_px"])
        realized += amt
        per_tid[t["tid"]] = per_tid.get(t["tid"], 0.0) + amt
        pop_day[t["tid"]] = ds
        held.discard(p["symbol"])

    for day in days:
        ds = day.isoformat()
        # 1) 开盘出场
        for t in exits_open.get(ds, []):
            p = book.pop(t["tid"], None)
            if not p:
                continue
            close_pos(t, p, ds)
        # 2) 进场(主机的跳过规则)
        eq_open = equity(day, True)
        alloc = eq_open
        gross_limit = alloc * cap_frac
        gross = 0.0
        for p in book.values():
            px = mark(p["symbol"], day, True)
            gross += p["qty"] * (px if px is not None else p["entry_px"])
        for t in entries.get(ds, []):
            if len(book) >= cap_n:
                blocked_cap.append(t)
                continue
            if t["symbol"] in held:
                blocked_coin.append(t)
                continue
            # 主机计划里的 stop_frac = STOP_ATR × ATR(信号日) ÷ 收盘(信号日)
            if t.get("ref_close"):
                stop_frac = STOP_ATR * t["atr14"] / t["ref_close"]
            else:
                stop_frac = (t["entry_px"] - t["stop_px"]) / t["entry_px"]
            mid = mark(t["symbol"], day, True)
            if not mid or mid <= 0 or not (0 < stop_frac < 0.9):
                blocked_min.append(t)
                continue
            target = min(alloc * risk_frac / stop_frac, alloc * 0.5)
            if exact_qty:                     # 归一化敏感性:不按 HL 的 szDecimals 取整
                qty = target / mid
            else:
                qty = math.floor(target / mid * (10 ** T251._szd(mid)) + 1e-9) / (10 ** T251._szd(mid))
            n = round(qty * mid, 2)          # 主机 size_entry 的 notional = round(qty × mid, 2)
            if n < min_notional:
                blocked_min.append(t)
                continue
            if gross + n > gross_limit:
                blocked_gross.append({**t, "notional": n, "gross_before": gross,
                                      "gross_limit": gross_limit, "alloc": alloc})
                continue
            gross += n
            book[t["tid"]] = dict(tid=t["tid"], symbol=t["symbol"], entry_px=t["entry_px"],
                                   stop_px=t["stop_px"], qty=qty, exit_d=t["exit_d"],
                                   exit_px=t["exit_px"], exit_reason=t["exit_reason"], r=t["r"])
            qty_by_tid[t["tid"]] = qty
            held.add(t["symbol"])
            taken.add(t["tid"])
        gross_hist.append(gross)          # 当日进场后的名义合计
        if eq_open > 0:
            gross_ratio_hist.append(gross / eq_open)
        # 2b) ★ 修版:同日出场(进场当根就被止损打掉的票)—— 放在进场之后
        for t in exits_same.get(ds, []):
            p = book.pop(t["tid"], None)
            if not p:
                continue
            close_pos(t, p, ds)
        # 3) 收盘出场
        for t in exits_close.get(ds, []):
            p = book.pop(t["tid"], None)
            if not p:
                continue
            close_pos(t, p, ds)
        # 4) 收盘净值
        eq = equity(day, False)
        curve.append((ds, eq, len(book), gross))
        # ① 的逐日现场检查:book 里不该有 exit_d 已经过去的票
        for tid, p in book.items():
            ed = p["exit_d"]
            if ed is not None and ed <= ds and len(viol_late) < 20:
                viol_late.append(dict(day=ds, tid=tid, exit_d=ed, symbol=p["symbol"]))

    return dict(curve=curve, taken=taken, blocked_gross=blocked_gross, blocked_cap=blocked_cap,
                blocked_min=blocked_min, blocked_coin=blocked_coin,
                gross_hist=gross_hist, gross_ratio_hist=gross_ratio_hist,
                realized=realized, per_tid=per_tid, qty_by_tid=qty_by_tid, pop_day=pop_day,
                final_book=dict(book), viol_late=viol_late)


# ── 不变量 ──────────────────────────────────────────────────────────────────────────
def check_invariants(res, tickets, equity0, label):
    """跑三条不变量;返回 (violations, detail)。violations 非空 ⇒ 这台引擎有 bug。"""
    by_tid = {t["tid"]: t for t in tickets}
    v, det = [], {}

    # ① 没有一张票在 exit_d 之后还在 book 里
    v1 = []
    for vv in res["viol_late"]:
        v1.append(f"{vv['tid']}({vv['symbol']}) exit_d={vv['exit_d']} 在 {vv['day']} 仍在 book 里")
    for tid, p in res["final_book"].items():
        ed = p["exit_d"]
        if ed is not None:
            v1.append(f"{tid}({p['symbol']}) exit_d={ed} 到窗口末还在 book 里")
    for tid, t in by_tid.items():
        if tid in res["taken"] and t["exit_d"]:
            pd = res["pop_day"].get(tid)
            if pd is None:
                v1.append(f"{tid} 有出场事件 exit_d={t['exit_d']} 但从未出场(幽灵仓)")
            elif pd > t["exit_d"]:
                v1.append(f"{tid} 出场日 {pd} 晚于 exit_d {t['exit_d']}")
    det["1_book_over_exit"] = dict(n=len(v1), sample=v1[:8])
    v += [f"① {x}" for x in v1]

    # ② 窗口末 book 里只剩 t197 标记 still 的票
    still_tids = {t["tid"] for t in tickets if not t["exit_d"]}
    book_tids = set(res["final_book"])
    v2 = []
    for tid in sorted(book_tids - still_tids):
        v2.append(f"{tid} 不是 still 票却留在 book 里")
    for tid in sorted(still_tids - book_tids):
        if tid in res["taken"]:
            v2.append(f"{tid} 是 still 票且已成交,却不在窗口末的 book 里")
    det["2_final_book"] = dict(n=len(v2), sample=v2[:8], n_book=len(book_tids),
                                n_still=len(still_tids),
                                n_still_taken=len([t for t in still_tids if t in res["taken"]]))
    v += [f"② {x}" for x in v2]

    # ③ 成交票的已实现盈亏之和 = Σ(r × 该票进场时的每票风险额)
    closed_taken = [t for t in tickets if t["tid"] in res["taken"] and t["exit_d"]]
    sum_real = 0.0
    sum_exp = 0.0
    v3 = []
    for t in closed_taken:
        qty = res["qty_by_tid"].get(t["tid"])
        if qty is None:
            continue
        risk_amt = qty * (t["entry_px"] - t["stop_px"])
        exp = t["r"] * risk_amt
        got = res["per_tid"].get(t["tid"], 0.0)
        sum_real += got
        sum_exp += exp
        if abs(got - exp) > 1e-9 * max(1.0, abs(exp)):
            v3.append(f"{t['tid']} 已实现 {got:.10f} ≠ r×风险额 {exp:.10f}")
    diff = sum_real - sum_exp
    det["3_realized_identity"] = dict(
        n=len(closed_taken), sum_realized=sum_real, sum_r_times_risk=sum_exp, diff=diff,
        tol=1e-6 * equity0, ok=abs(diff) < 1e-6 * equity0,
        n_ticket_mismatch=len(v3), sample=v3[:8])
    v += [f"③ {x}" for x in v3]
    if abs(diff) >= 1e-6 * equity0:
        v.append(f"③ 合计差 {diff:.10f} ≥ 1e-6 × 净值 {1e-6 * equity0:.10f}")
    det["label"] = label
    det["n_violations"] = len(v)
    det["violations"] = v[:40]
    return v, det


# ── 指标 ────────────────────────────────────────────────────────────────────────────
def underwater_days(curve, equity0):
    """最长水下(净值低于前高多少天连着)。"""
    peak, cur, worst = equity0, 0, 0
    for (_ds, v, *_r) in curve:
        if v > peak:
            peak, cur = v, 0
        else:
            cur += 1
            worst = max(worst, cur)
    return worst


def summarize(res, cap_frac, cap_n, by_tid, equity0=EQ0):
    st = T251.curve_stats(res["curve"], equity0)
    taken_r = [by_tid[t]["r"] for t in res["taken"] if by_tid[t].get("r") is not None]
    gr = res["gross_ratio_hist"]
    return dict(
        cap_frac=cap_frac, cap_n=cap_n,
        total_return=st["total_return"], cagr=st["cagr"], max_dd=st["max_dd"],
        calmar=st["calmar"], end_equity=st["end_equity"], n_days=st["n_days"],
        worst_month=st["worst_month"], worst_month_ret=st["worst_month_ret"],
        longest_underwater=underwater_days(res["curve"], equity0),
        max_concurrent=max((c[2] for c in res["curve"]), default=0),
        filled=len(res["taken"]),
        sum_r_taken=round(sum(taken_r), 6),
        blocked_gross=len(res["blocked_gross"]),
        blocked_gross_r=round(sum((t.get("r") or 0.0) for t in res["blocked_gross"]), 6),
        blocked_cap=len(res["blocked_cap"]), blocked_min=len(res["blocked_min"]),
        blocked_coin=len(res["blocked_coin"]),
        days_above_cap=sum(1 for x in gr if x > cap_frac + 1e-12),
        gross_ratio_median=T251.q(gr, 0.5), gross_ratio_p95=T251.q(gr, 0.95),
        gross_ratio_max=max(gr) if gr else None,
        gross_abs_median=T251.q(res["gross_hist"], 0.5),
        gross_abs_p95=T251.q(res["gross_hist"], 0.95),
        gross_abs_max=max(res["gross_hist"]) if res["gross_hist"] else None,
        realized=res["realized"],
    )


def run_pair(tickets, bars, gate, cap_frac, cap_n, by_tid, equity0=EQ0):
    """同一份数据、同一个函数,fix=False(旧)与 fix=True(新)各跑一遍。"""
    old = simulate(tickets, bars, gate, cap_frac, equity0=equity0, risk_frac=F,
                   cap_n=cap_n, fix=False)
    new = simulate(tickets, bars, gate, cap_frac, equity0=equity0, risk_frac=F,
                   cap_n=cap_n, fix=True)
    return (summarize(old, cap_frac, cap_n, by_tid, equity0),
            summarize(new, cap_frac, cap_n, by_tid, equity0),
            old, new)


# ── 主流程 ──────────────────────────────────────────────────────────────────────────
def main():
    t0 = time.time()
    raw, t197 = DRV.load_tickets()
    need = {t["symbol"] for t in raw}
    bars = DRV.load_bars(need)
    print(f"[load] tickets {len(raw)} symbols {len(need)} bars {len(bars)} "
          f"({time.time() - t0:.1f}s)", flush=True)

    exits, bad = DRV.classify_exits(raw, bars)
    print(f"[exit-reason] 重算 {len(exits)} 张,与 t197 不一致 {len(bad)} 张", flush=True)
    for b in bad[:10]:
        print("   ", b, flush=True)

    tk = DRV.to_engine_tickets(raw, exits)
    by_tid = {x["tid"]: x for x in tk}
    gate, lvl_by_d, gdiag = DRV.load_gate()
    print(f"[gate] {gdiag}", flush=True)

    same_day = [t for t in tk if t["exit_d"] and t["exit_d"] == t["entry_d"]]
    still = [t for t in tk if not t["exit_d"]]
    print(f"[tickets] 同日出场(exit_d==entry_d) {len(same_day)} 张;still {len(still)} 张", flush=True)

    out = dict(meta=dict(
        card="T-352", lane="lane-b", ran_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
        engine_old="docs/research/t251_gross_cap.py :: simulate(一字未改)",
        engine_new="docs/research/t352_engine.py :: simulate(fix=True)",
        ticket_source="docs/research/t197_results.json → tickets.A",
        n_tickets=len(tk), n_symbols=len(need),
        bars_source=DRV.UM, gate_source=DRV.STYLE,
        exit_reason_mismatch=len(bad),
        n_same_day_exit=len(same_day), n_still=len(still),
        equity0=EQ0, risk_frac=F, min_notional=MIN_NOTIONAL,
        note=("本脚本只读、不入库;引擎改版只动『同日出场的处理顺序』,票与规则一字未改。"),
    ))

    # ── 0) 忠实性:fix=False 必须与原件 T251.simulate 逐位相同 ────────────────────
    ref = T251.simulate(tk, bars, gate, 0.40, equity0=EQ0, risk_frac=F, cap_n=14)
    mine_old = simulate(tk, bars, gate, 0.40, equity0=EQ0, risk_frac=F, cap_n=14, fix=False)
    same_curve = len(ref["curve"]) == len(mine_old["curve"]) and all(
        a[0] == b[0] and a[1] == b[1] and a[2] == b[2] and a[3] == b[3]
        for a, b in zip(ref["curve"], mine_old["curve"]))
    faithful = dict(curve_identical=bool(same_curve),
                    end_equity_identical=bool(ref["curve"][-1][1] == mine_old["curve"][-1][1]),
                    taken_identical=bool(ref["taken"] == mine_old["taken"]), n_curve=len(ref["curve"]))
    print(f"[faithful] {faithful}", flush=True)
    out["faithful_copy"] = faithful
    assert faithful["curve_identical"] and faithful["taken_identical"] and faithful["end_equity_identical"], \
        "fix=False 必须与原件逐位相同"

    # ── 1) 旧引擎(对照):不变量必须被拦下 ────────────────────────────────────────
    v_old, det_old = check_invariants(mine_old, tk, EQ0, "旧引擎(对照,fix=False)")
    print(f"[invariants] 旧引擎违规 {len(v_old)} 条(预期 > 0)", flush=True)
    for x in v_old[:6]:
        print("   ", x, flush=True)
    out["invariants_old"] = det_old

    # ── 2) T-251 名义上限表(旧/新并排)────────────────────────────────────────────
    CAPS = [0.20, 0.30, 0.40, 0.80, 1.00, 99.0]
    t251 = {}
    for cap in CAPS:
        so, sn, _ro, _rn = run_pair(tk, bars, gate, cap, 10, by_tid)
        key = "inf" if cap >= 99 else f"{cap:.2f}"
        t251[key] = dict(cap_frac=cap, old=so, new=sn)
        print(f"[cap {key}] old: {so['total_return']:+.4%} cagr {so['cagr']:+.4%} "
              f"mdd {so['max_dd']:+.4%} filled {so['filled']} | new: {sn['total_return']:+.4%} "
              f"cagr {sn['cagr']:+.4%} mdd {sn['max_dd']:+.4%} filled {sn['filled']}", flush=True)
    out["t251_gross_cap_table"] = t251

    # ── 3) T-310 名额表(旧/新并排)────────────────────────────────────────────────
    SLOTS = [10, 14, CAP_N_INF]
    t310 = {}
    for cn in SLOTS:
        so, sn, _ro, _rn = run_pair(tk, bars, gate, 0.40, cn, by_tid)
        key = {10: "10", 14: "14", CAP_N_INF: "inf"}[cn]
        t310[key] = dict(cap_n=cn, old=so, new=sn)
        print(f"[slot {key}] old: {so['total_return']:+.4%} cagr {so['cagr']:+.4%} "
              f"mdd {so['max_dd']:+.4%} filled {so['filled']} | new: {sn['total_return']:+.4%} "
              f"cagr {sn['cagr']:+.4%} mdd {sn['max_dd']:+.4%} filled {sn['filled']}", flush=True)
    out["t310_slots_table"] = t310

    # ── 4) C0:f 0.5%、名义上限 0.40、cap_n 14 ─────────────────────────────────────
    c0_old, c0_new, raw_old, raw_new = run_pair(tk, bars, gate, 0.40, 14, by_tid)
    v_new, det_new = check_invariants(raw_new, tk, EQ0, "新引擎(fix=True)")
    print(f"[invariants] 新引擎违规 {len(v_new)} 条(预期 0)", flush=True)
    for x in v_new[:10]:
        print("   ", x, flush=True)
    out["invariants_new"] = det_new

    # 去掉 ZEC(Seth 的 S-828 预览里有这一行)
    zec_tk = [t for t in tk if t["symbol"] != "ZEC"]
    zec_old, zec_new, _a, _b = run_pair(zec_tk, bars, gate, 0.40, 14, by_tid)

    out["c0"] = dict(
        config=dict(risk_frac=F, gross_cap=0.40, cap_n=14, equity0=EQ0),
        old=c0_old, new=c0_new,
        old_no_zec=zec_old, new_no_zec=zec_new,
        seth_preview=dict(filled=358, cagr=0.2643, longest_underwater=762, max_dd=-0.280,
                          no_zec_cagr=0.1759, source="REFUTATION_LEDGER S-828(Seth 的预览,未复核)"),
    )
    print(f"[C0] old filled {c0_old['filled']} cagr {c0_old['cagr']:+.4%} | "
          f"new filled {c0_new['filled']} cagr {c0_new['cagr']:+.4%} "
          f"total {c0_new['total_return']:+.4%} uw {c0_new['longest_underwater']}d "
          f"mdd {c0_new['max_dd']:+.4%}", flush=True)

    # R-v2「自己」的几个候选口径(Seth 的预览说 +97.1%)
    realized_sum = sum(raw_new["per_tid"].values())
    out["c0"]["rv2_own"] = dict(
        realized_sum_usd=realized_sum,
        realized_sum_pct_of_equity0=realized_sum / EQ0,
        filled=c0_new["filled"], sum_r_taken=c0_new["sum_r_taken"],
        sleeve_pnl_per_ticket_usd=realized_sum / max(1, c0_new["filled"]),
    )

    # ── 5) 复现锚:旧引擎必须复现已发布的 T-251 / T-310 数字 ──────────────────────
    anchors = {}
    try:
        pub251 = json.load(open(os.path.join(HERE, "t251_results_t197.json")))
        for key, mine in (("0.30", t251["0.30"]["old"]), ("0.40", t251["0.40"]["old"]),
                          ("1.00", t251["1.00"]["old"])):
            p = (pub251.get("caps") or {}).get(key, {}).get("stats", {})
            anchors[f"t251_cap_{key}"] = dict(
                published_total=p.get("total_return"), published_cagr=p.get("cagr"),
                published_mdd=p.get("max_dd"), published_taken=(pub251.get("caps") or {}).get(key, {}).get("taken"),
                mine_total=mine["total_return"], mine_cagr=mine["cagr"],
                mine_mdd=mine["max_dd"], mine_filled=mine["filled"],
                match_total=bool(p.get("total_return") is not None
                                 and abs(p["total_return"] - mine["total_return"]) < 1e-12),
                match_filled=bool((pub251.get("caps") or {}).get(key, {}).get("taken") == mine["filled"]),
            )
        pub310 = json.load(open(os.path.join(HERE, "t310_results.json")))
        for key, mine in (("10", t310["10"]["old"]), ("14", t310["14"]["old"]), ("inf", t310["inf"]["old"])):
            cell = ((pub310.get("slots") or {}).get(key) or {}).get("0.40", {})
            p = cell.get("stats", {})
            anchors[f"t310_slot_{key}"] = dict(
                published_total=p.get("total_return"), published_cagr=p.get("cagr"),
                published_mdd=p.get("max_dd"), published_taken=cell.get("taken"),
                mine_total=mine["total_return"], mine_cagr=mine["cagr"],
                mine_mdd=mine["max_dd"], mine_filled=mine["filled"],
                match_total=bool(p.get("total_return") is not None
                                 and abs(p["total_return"] - mine["total_return"]) < 1e-12),
                match_filled=bool(cell.get("taken") == mine["filled"]),
            )
    except Exception as e:  # noqa
        anchors["error"] = repr(e)
    out["reproduction_anchors"] = anchors
    print(f"[anchors] {json.dumps(anchors, ensure_ascii=False)[:600]}", flush=True)

    # ── 6) 曲线(供画图/复核)──────────────────────────────────────────────────────
    out["curve_c0"] = dict(old=[c[0] for c in raw_old["curve"]],
                           old_eq=[round(c[1], 6) for c in raw_old["curve"]],
                           new_eq=[round(c[1], 6) for c in raw_new["curve"]],
                           new_n=[c[2] for c in raw_new["curve"]])
    out["same_day_tickets"] = [dict(tid=t["tid"], symbol=t["symbol"], signal_d=t["signal_d"],
                                     entry_d=t["entry_d"], exit_d=t["exit_d"], r=t["r"])
                                for t in same_day]

    with open(OUT_JSON, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"[write] {OUT_JSON} ({time.time() - t0:.1f}s)", flush=True)

    # ── 7) 断言:新引擎三条不变量必须全过(不过就 abort)────────────────────────────
    assert len(v_new) == 0, ("新引擎不变量未通过:\n" + "\n".join(v_new[:20]))
    assert len(v_old) > 0, "对照失效:旧引擎竟然没被不变量拦下 —— 断言本身没抓到 bug"
    print("[ASSERT] 新引擎三条不变量全过;旧引擎被拦下(对照成立)", flush=True)
    print(f"[done] {time.time() - t0:.1f}s", flush=True)


if __name__ == "__main__":
    main()
