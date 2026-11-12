#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T-353 — 第二台 R-v2 账户引擎(从零独立实现)

规则**全部**来自任务卡 T-353 的 acceptance,本文件不 import t251_gross_cap / t352_* /
s825_* / s828_*,也不复用任何既有 simulate:

  每票名义 = 每票风险 f × 当日开盘净值 ÷ 止损距离占比
  同时在场 ≤ 名额(cap_n)
  同币不重复
  名义合计 ≤ 上限 × 净值(超了就不进)
  进场 = entry_d 开盘(= 票里的 entry_px,已逐张核对 956/956 相等)
  出场 = exit_d 的 exit_px(同日进场同日出场也要出)
  来回成本 0.4%(名义口径)
  逐日按收盘盯市

三条不变量(与 T-352 卡相同),跑不过就 abort:
  ① 没有一张票在 exit_d 之后还在 book 里
  ② 窗口末 book 里只剩 t197 标记 still 的票
  ③ 成交票的已实现盈亏之和 = Σ(r × 该票进场时的每票风险额),差 < 1e-6 × 净值

票 = docs/research/t197_results.json 的 tickets.A;日线 = Mac 数据根 s681/_um_daily.jsonl(只读)。
"""
from __future__ import annotations

import argparse
import bisect
import datetime as dt
import json
import os
from collections import defaultdict

UM_FILE = "/Volumes/CometCloudAI/cometcloud-local/research/s681/_um_daily.jsonl"
T197_FILE = "/Users/sbb/Projects/looloomi-ai/docs/research/t197_results.json"
COST = 0.004  # 来回成本(名义口径)


# --------------------------------------------------------------------------- 数据

def load_um(path: str = UM_FILE) -> dict:
    """{symbol: [(d, o, h, l, c), ...]},按日期升序。"""
    bars = {}
    with open(path) as f:
        for line in f:
            o = json.loads(line)
            rows = o.get("bars") or []
            if not rows:
                continue
            bars[o["symbol"]] = sorted(
                [(r[0], float(r[1]), float(r[2]), float(r[3]), float(r[4])) for r in rows],
                key=lambda r: r[0],
            )
    return bars


def load_tickets(path: str = T197_FILE) -> list:
    """t197 的 A 组票,原样保留顺序(同日多个候选按文件顺序处理)。"""
    with open(path) as f:
        T = json.load(f)
    A = T["tickets"]["A"]
    for i, t in enumerate(A):
        t["tid"] = i
    return A, T["meta"]


class PriceLookup:
    """收盘价/开盘价查表:日期缺失时向前carry(最后一个已知价)。"""

    def __init__(self, bars: dict):
        self._dates = {}
        self._rows = {}
        for s, rows in bars.items():
            self._rows[s] = rows
            self._dates[s] = [r[0] for r in rows]

    def _row_on_or_before(self, sym: str, d: str):
        ds = self._dates.get(sym)
        if not ds:
            return None
        i = bisect.bisect_right(ds, d)
        return self._rows[sym][i - 1] if i > 0 else None

    def close_on(self, sym: str, d: str):
        r = self._row_on_or_before(sym, d)
        return r[4] if r else None

    def open_on(self, sym: str, d: str):
        r = self._row_on_or_before(sym, d)
        return r[1] if r else None


# --------------------------------------------------------------------------- 引擎

def simulate(tickets, bars, f, gross_cap, cap_n, open_mark=False,
             cost_at_entry=True, nav_to=None, d0=None,
             same_day_exit=True, strict=True, skip_same_day=False,
             exits_first=False, eq_open_after_exits=False, gross_basis="entry",
             nav0=1.0, qty_mode="none"):
    """跑一台 R-v2 账户。

    f          每票风险(占净值),0.005 = 0.5%
    gross_cap  名义上限(占净值);None = 不限
    cap_n      同时在场的名额
    open_mark  True = 「当日开盘净值」按当日开盘价重估;False = 沿用前一日收盘净值
    cost_at_entry  True = 一半成本在进场时扣;False = 全部 0.4% 在出场时扣
    same_day_exit  False = 关掉「同日出场」(复现 T-352 说的幽灵仓,用来对账老结果)
    skip_same_day  True = 同日进同日出的票根本不进
    exits_first    True = 当天先出场后进场;False = 先进场后出场
    eq_open_after_exits  True = 进场用的「当日开盘净值」含当天已出场票的已实现盈亏
    gross_basis  「名义合计」怎么算:"entry" = 各仓进场名义之和;"marked" = 各仓按现价盯市后的名义
    nav0      初始净值(1.0 = 净值口径;630 = 美元口径)
    qty_mode  名义取整:"none" 不取整 / "usd_round" 整数美元 / "qty_floor" 枚数向下取整 / "qty_round" 枚数四舍五入
    strict    True = 跑三条不变量,不过就 abort
    """
    pl = PriceLookup(bars)
    by_entry = defaultdict(list)
    by_exit = defaultdict(list)
    for t in tickets:
        by_entry[t["entry_d"]].append(t)
        if t.get("exit_d"):
            by_exit[t["exit_d"]].append(t)

    if d0 is None:
        d0 = min(t["entry_d"] for t in tickets)
    if nav_to is None:
        nav_to = max(t["exit_d"] for t in tickets if t.get("exit_d"))

    d0d = dt.date.fromisoformat(d0)
    d1d = dt.date.fromisoformat(nav_to)
    days = [(d0d + dt.timedelta(days=i)).isoformat() for i in range((d1d - d0d).days + 1)]

    book = []           # 在场仓位
    cash = nav0         # 现金(净值口径):进场付名义、出场收回名义 × 成交价/进场价
    eq = nav0           # 净值 = cash + 在场市值(收盘口径)
    gross_now = 0.0     # 在场名义合计
    curve = []          # (日期, 净值, 在场名义合计, 在场张数)
    trades = []         # 成交明细
    taken = 0
    skipped = 0
    skip_reasons = defaultdict(int)   # 被谁挡:slot_full / dup_symbol / notional_cap / ...

    def skip(reason):
        nonlocal skipped
        skipped += 1
        skip_reasons[reason] += 1
    closed_count = 0
    sum_realized_cash = 0.0   # 不变量③左:按现金流的已实现盈亏合计
    sum_r_risk = 0.0          # 不变量③右:Σ(r × 进场时每票风险额)

    def mark(prices):
        """positions 按 prices(sym→价)估值后的净值。"""
        v = cash
        for p in book:
            px = prices.get(p["symbol"])
            if px is None:
                px = p["entry_px"]
            v += p["notional"] * (px / p["entry_px"])
        return v

    def open_equity(day):
        """当日开盘净值:open_mark 时按当日开盘价重估,否则沿用上一收盘价。"""
        if open_mark:
            prices = {}
            for p in book:
                o = pl.open_on(p["symbol"], day)
                if o:
                    prices[p["symbol"]] = o
            return mark(prices)
        prices = {p["symbol"]: p.get("last_close") for p in book}
        return mark(prices)

    def gross_marked(prices):
        """在场名义合计(按 prices 盯市)。prices 缺的用上一收盘价/进场价兜底。"""
        tot = 0.0
        for p in book:
            px = prices.get(p["symbol"])
            if px is None:
                px = p.get("last_close") or p["entry_px"]
            tot += p["notional"] * px / p["entry_px"]
        return tot

    for d in days:
        # ---- 当日开盘净值(入场与出场的计价基准)----
        def _exit(t, pos):
            nonlocal cash, gross_now, sum_realized_cash, sum_r_risk, closed_count
            exit_cost = (COST / 2 if cost_at_entry else COST) * pos["notional"]
            proceeds = pos["notional"] * (t["exit_px"] / pos["entry_px"])
            cash += proceeds - exit_cost
            gross_now -= pos["notional"]
            # 不变量③的左端:这张票的全部盈亏(含全部 0.4% 成本),与成本记账时点无关
            sum_realized_cash += pos["notional"] * (t["exit_px"] / pos["entry_px"] - 1.0) - COST * pos["notional"]
            sum_r_risk += t["r"] * pos["risk"]
            pos["exit_realized"] = proceeds - pos["notional"] - exit_cost
            pos["exit_d_actual"] = d
            book.remove(pos)
            closed_count += 1

        def _exit_pass(same_day):
            for t in by_exit.get(d, []):
                pos = next((p for p in book if p["tid"] == t["tid"]), None)
                if pos is None:
                    continue
                if (pos["entry_d"] == d) != same_day:
                    continue
                _exit(t, pos)

        eq_open_pre = open_equity(d)   # 当天任何成交之前的开盘净值
        # 「名义合计」盯市价:om=1 用当日开盘价,om=0 用上一收盘价(缺失回落到进场价)
        check_prices = {}
        if gross_basis == "marked":
            for p in book:
                px = (pl.open_on(p["symbol"], d) if open_mark else p.get("last_close"))
                if px:
                    check_prices[p["symbol"]] = px
        if exits_first:
            _exit_pass(same_day=False)  # 释放名额与名义
        eq_open = open_equity(d) if eq_open_after_exits else eq_open_pre

        # ---- 进场 ----
        for t in by_entry.get(d, []):
            if skip_same_day and t.get("exit_d") == d:
                skip("same_day_skipped")
                continue
            sd = (t["entry_px"] - t["stop_px"]) / t["entry_px"]
            if not (sd > 0):
                skip("bad_stop")
                continue
            if len(book) >= cap_n:
                skip("slot_full")
                continue
            if any(p["symbol"] == t["symbol"] for p in book):
                skip("dup_symbol")
                continue
            notional = f * eq_open / sd
            if qty_mode != "none":
                if qty_mode == "usd_round":
                    notional = float(round(notional))
                else:
                    units = (notional / t["entry_px"])
                    units = int(units) if qty_mode == "qty_floor" else float(round(units))
                    notional = units * t["entry_px"]
                if notional <= 0:
                    skip("qty_zero")
                    continue
            if gross_cap is not None:
                gchk = gross_now if gross_basis == "entry" else gross_marked(check_prices)
                if (gchk + notional) > gross_cap * eq_open:
                    skip("notional_cap")
                    continue
            cash -= notional
            entry_cost_charged = 0.0
            if cost_at_entry:
                entry_cost_charged = (COST / 2) * notional
                cash -= entry_cost_charged
            gross_now += notional
            taken += 1
            pos = {
                "tid": t["tid"], "symbol": t["symbol"], "entry_d": d,
                "entry_px": t["entry_px"], "notional": notional,
                "risk": notional * sd, "sd": sd,
                "exit_d": t.get("exit_d"), "exit_px": t.get("exit_px"),
                "r": t["r"], "still": bool(t.get("still")),
                "exit_realized": None, "exit_d_actual": None,
                "entry_cost_charged": entry_cost_charged,
            }
            book.append(pos)
            trades.append(pos)

        # ---- 出场(第二遍):同日进场的票当天必须出(T-352 的幽灵仓就在这里) ----
        if same_day_exit:
            _exit_pass(same_day=True)
        if not exits_first:
            _exit_pass(same_day=False)

        # ---- 收盘盯市 ----
        closes = {}
        for p in book:
            c = pl.close_on(p["symbol"], d)
            closes[p["symbol"]] = c
            p["last_close"] = c
            p["last_unreal"] = (p["notional"] * (c / p["entry_px"] - 1.0)
                                 if c is not None else 0.0)
        eq = mark(closes)
        curve.append((d, eq, gross_marked(closes), len(book)))

        # ---- 不变量①:任何票都不该在自己的 exit_d 之后还留在 book 里 ----
        if strict:
            for p in book:
                assert p["exit_d"] is None or p["exit_d"] > d, f"票在 exit_d 之后仍在 book:{p}"

    # ---- 不变量②:窗口末 book 里只剩 t197 标记 still 的票 ----
    if strict:
        for p in book:
            assert p["still"], f"窗口末 book 里有非 still 的票:{p}"
    # ---- 不变量③:已实现盈亏合计 = Σ(r × 进场时每票风险额) ----
    diff = sum_realized_cash - sum_r_risk
    if strict:
        assert abs(diff) < 1e-6 * eq, f"不变量③不成立:diff={diff}"

    closed = sum(1 for p in trades if p.get("exit_realized") is not None)
    return {
        "f": f, "gross_cap": gross_cap, "cap_n": cap_n,
        "open_mark": open_mark, "cost_at_entry": cost_at_entry,
        "exits_first": exits_first, "eq_open_after_exits": eq_open_after_exits,
        "gross_basis": gross_basis, "nav0": nav0, "qty_mode": qty_mode,
        "same_day_exit": same_day_exit, "skip_same_day": skip_same_day,
        "d0": d0, "d1": nav_to, "days": len(days),
        "end_equity": eq,
        "total_return": eq / nav0 - 1.0,
        "taken": taken, "skipped": skipped,
        "skip_reasons": dict(skip_reasons),
        "closed": closed,
        "open_at_end": len(book),
        "book_at_end": [{"symbol": p["symbol"], "entry_d": p["entry_d"], "r": p["r"]} for p in book],
        "invariant3_diff": diff,
        "curve": curve,
        "trades": trades,
    }


# --------------------------------------------------------------------------- 统计

def mdd(curve):
    peak = -1e18
    worst = 0.0
    peak_d = trough_d = None
    pk = None
    for d, eq, _g, _n in curve:
        if eq > peak:
            peak, pk = eq, d
        dd = eq / peak - 1.0
        if dd < worst:
            worst, peak_d, trough_d = dd, pk, d
    return worst, peak_d, trough_d


def by_year(curve):
    out = {}
    prev = 1.0
    for d, eq, _g, _n in curve:
        y = d[:4]
        out.setdefault(y, eq)
        out[y] = eq
    res = {}
    for y in sorted(out):
        res[y] = {"end_equity": out[y], "ret": out[y] / prev - 1.0}
        prev = out[y]
    return res


def summarize(res):
    curve = res["curve"]
    yr = by_year(curve)
    peak_gross = max((g / e if e > 0 else 0.0) for _d, e, g, _n in curve)
    m, pk, tr = mdd(curve)
    return {
        "f": res["f"], "gross_cap": res["gross_cap"], "cap_n": res["cap_n"],
        "end_equity": res["end_equity"], "total_return": res["total_return"],
        "taken": res["taken"], "skipped": res["skipped"], "closed": res["closed"],
        "open_at_end": res["open_at_end"],
        "peak_gross": peak_gross, "mdd": m, "mdd_peak": pk, "mdd_trough": tr,
        "by_year": {y: v["ret"] for y, v in yr.items()},
        "year_end_equity": {y: v["end_equity"] for y, v in yr.items()},
        "invariant3_diff": res["invariant3_diff"],
    }


def run_cell(bars, tickets, nav_to, f, gross_cap, cap_n, curve=False, **kw):
    """跑一格并只留摘要(curve=True 时带上逐日曲线)。"""
    r = simulate(tickets, bars, f=f, gross_cap=gross_cap, cap_n=cap_n,
                 nav_to=nav_to, strict=True, **kw)
    s = summarize(r)
    s["skip_reasons"] = r["skip_reasons"]
    s["open_at_end"] = r["open_at_end"]
    if curve:
        s["curve"] = r["curve"]
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--validate", action="store_true", help="跑 t197 已发布的 nav 作为对照")
    ap.add_argument("--cells", action="store_true", help="跑 T-353 交付格")
    ap.add_argument("--sweep", action="store_true", help="扫记账口径,定位与 T-352 的分歧")
    ap.add_argument("--round", action="store_true", help="扫初始净值与取整规则")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    bars = load_um()
    tickets, meta = load_tickets()
    print(f"票 {len(tickets)} 张 | um 符号 {len(bars)} 个 | nav_to {meta['nav_to']}", flush=True)

    out = {"meta": meta, "runs": {}, "validation": {}}

    if args.validate:
        # 对账 t197 自己发布的那条 nav(f=1%、名额 10、无名义上限):
        # 把「当日开盘净值 / 出场先后 / 同日出场 / 成本时点」这四个语义开关全排列一遍,
        # 看哪一组能逐字复现 t197 已发布的数字 —— 复现不了的地方就是两台引擎的分歧点。
        ref = json.load(open(T197_FILE))["nav"]["A"]
        print("t197 已发布 nav.A:", json.dumps(ref, ensure_ascii=False), flush=True)
        grid = []
        for om in (False, True):
            for ce in (False, True):
                for sde in (True, False):
                    for ssd in (False, True):
                        for ef in (True, False):
                            for eoae in (True, False):
                                r = simulate(tickets, bars, f=0.01, gross_cap=None, cap_n=10,
                                             open_mark=om, cost_at_entry=ce, nav_to=meta["nav_to"],
                                             same_day_exit=sde, strict=False, skip_same_day=ssd,
                                             exits_first=ef, eq_open_after_exits=eoae)
                                s = summarize(r)
                                key = (f"om{int(om)}_ce{int(ce)}_sde{int(sde)}_ssd{int(ssd)}"
                                       f"_ef{int(ef)}_eo{int(eoae)}")
                                d_end = abs(s["end_equity"] - ref["end"])
                                d_tk = abs(s["taken"] - ref["taken"])
                                grid.append((d_end + d_tk, d_end, d_tk, key, s))
        grid.sort(key=lambda x: x[0])
        for _sc, d_end, d_tk, key, s in grid[:8]:
            print(key, "| end", round(s["end_equity"], 6), "(Δ", round(d_end, 4), ")",
                  "taken", s["taken"], "(Δ", d_tk, ")", "closed", s["closed"],
                  "open_end", s["open_at_end"], "peak_gross", round(s["peak_gross"], 6),
                  "mdd", round(s["mdd"], 6), flush=True)
        out["validation_grid_top"] = [{"key": g[3], **{k: v for k, v in g[4].items() if k != "curve"}}
                                       for g in grid[:8]]
        out["validation_ref"] = ref
        print("t197 已发布 nav.A:", json.dumps(
            json.load(open(T197_FILE))["nav"]["A"], ensure_ascii=False), flush=True)
        print("t197 已发布:", json.dumps(
            {k: meta.get(k) for k in ("f", "cap")}, ensure_ascii=False),
            json.dumps(json.load(open(T197_FILE))["nav"]["A"], ensure_ascii=False)[:400], flush=True)

    if args.cells:
        # T-353 交付格:
        #   (a) C0 = f 0.5% × 名义上限 0.40 × 名额 14,出逐日曲线(成交票数/总收益/逐年)
        #   (b) cap_n {10, 14, ∞} @ f 0.5% × 上限 0.40 —— 谁挡下了多少张
        #   (c) f {0.5,0.75,1.0,1.25}% × 名义上限 1.20 四格
        # 两种「出场/进场同日先后」都跑:ef0 = 当天先进场后出场(逐位复现 t197 已发布 nav.A),
        # ef1 = 当天先出场后进场(T-352 修后引擎的顺序)。数字不同就都摆出来,不替别人选。
        # (主) T-352 对齐口径:ef1(当天先出场后进场)+ 名义按现价盯市 —— 成交张数与 T-352 逐张对上
        # (副) t197 逐位复现口径:ef0(当天先进场后出场)+ 名义按进场额 —— 逐位复现 t197 已发布 nav.A
        CONV = [("main_ef1_gbmarked", True, "marked"),
                ("alt_ef0_gbentry", False, "entry")]
        grid_out = {}
        for tag, ef, gb in CONV:
            sweep = {}
            for cn in (10, 14, 10 ** 9):
                sweep[f"cap_n={cn if cn < 10 ** 8 else 'inf'}"] = run_cell(
                    bars, tickets, meta["nav_to"], f=0.005, gross_cap=0.40,
                    cap_n=cn, exits_first=ef, gross_basis=gb, curve=(cn == 14))
            g4 = {}
            for fv in (0.005, 0.0075, 0.01, 0.0125):
                g4[f"f={fv}"] = run_cell(
                    bars, tickets, meta["nav_to"], f=fv, gross_cap=1.20,
                    cap_n=14, exits_first=ef, gross_basis=gb)
            g4inf = {}
            for fv in (0.005, 0.0075, 0.01, 0.0125):
                g4inf[f"f={fv}"] = run_cell(
                    bars, tickets, meta["nav_to"], f=fv, gross_cap=1.20,
                    cap_n=10 ** 9, exits_first=ef, gross_basis=gb)
            grid_out[tag] = {"capn_sweep_f0.5_cap0.40": sweep,
                             "grid_f_x_cap1.20_capn14": g4,
                             "grid_f_x_cap1.20_capninf": g4inf}
            print(f"--- {tag} ---", flush=True)
            for k, v in sweep.items():
                print(f"  C0 {k}: taken {v['taken']} 收 {v['total_return']*100:+.2f}% "
                      f"MDD {v['mdd']*100:+.2f}% 挡 {v['skip_reasons']}", flush=True)
            for k, v in g4.items():
                print(f"  四格 {k}: taken {v['taken']} 收 {v['total_return']*100:+.2f}% "
                      f"MDD {v['mdd']*100:+.2f}%", flush=True)
        out["cells"] = grid_out

    if args.sweep:
        # 定位分歧:同一张卡、同一批票,谁的记账口径能对上 T-352 已发布的三个数
        # (C0 cap_n14: 358 张 / +97.24% / MDD -24.69%;cap_n10: 325 张 / +107.13% / -21.22%)
        TGT = {14: (358, 0.9724, -0.2469), 10: (325, 1.0713, -0.2122)}
        rows = []
        for om in (0, 1):
            for ce in (0, 1):
                for ef in (0, 1):
                    for gb in ("entry", "marked"):
                        for eo in (0, 1):
                            sc = 0.0
                            detail = []
                            for cn, (tk, rt, md) in TGT.items():
                                s = run_cell(bars, tickets, meta["nav_to"], f=0.005,
                                             gross_cap=0.40, cap_n=cn,
                                             open_mark=bool(om), cost_at_entry=bool(ce),
                                             exits_first=bool(ef), gross_basis=gb,
                                             eq_open_after_exits=bool(eo))
                                d = (abs(s["taken"] - tk) + abs(s["total_return"] - rt) * 100
                                     + abs(s["mdd"] - md) * 100)
                                sc += d
                                detail.append((cn, s["taken"], s["total_return"], s["mdd"], d))
                            rows.append((sc, f"om{om}_ce{ce}_ef{ef}_gb{gb}_eo{eo}", detail))
        rows.sort(key=lambda r: r[0])
        for sc, key, detail in rows:
            txt = " | ".join(
                f"cn{cn}: {tk}张 {rt*100:+.2f}% {md*100:+.2f}% (Δ{d:.2f})"
                for cn, tk, rt, md, d in detail)
            print(f"{sc:8.2f}  {key:28s}  {txt}", flush=True)
        out["sweep"] = [{"score": sc, "key": key,
                         "detail": [{"cap_n": cn, "taken": tk, "ret": rt, "mdd": md, "dist": d}
                                    for cn, tk, rt, md, d in det]}
                        for sc, key, det in rows]

    if args.round:
        # 口径已锁(ef1 + 名义按市值盯市 + 一半成本进场时扣),剩下的差只可能在
        # 「初始净值 + 取整」上:T-352 用 $630 净值且保留了原引擎的取整规则。
        TGT = {14: (358, 0.9724, -0.2469), 10: (325, 1.0713, -0.2122)}
        rows = []
        for nav0 in (1.0, 630.0):
            for qm in ("none", "usd_round", "qty_floor", "qty_round"):
                sc, det = 0.0, []
                for cn, (tk, rt, md) in TGT.items():
                    s = run_cell(bars, tickets, meta["nav_to"], f=0.005, gross_cap=0.40,
                                 cap_n=cn, exits_first=True, gross_basis="marked",
                                 nav0=nav0, qty_mode=qm)
                    d = (abs(s["taken"] - tk) + abs(s["total_return"] - rt) * 100
                         + abs(s["mdd"] - md) * 100)
                    sc += d
                    det.append((cn, s["taken"], s["total_return"], s["mdd"], d))
                rows.append((sc, f"nav0={nav0} qty={qm}", det))
                print(f"{sc:8.3f}  nav0={nav0:6.1f} qty={qm:10s}  " + " | ".join(
                    f"cn{cn}: {tk}张 {rt*100:+.4f}% {md*100:+.4f}% (Δ{d:.3f})"
                    for cn, tk, rt, md, d in det), flush=True)
        rows.sort(key=lambda r: r[0])
        out["round_sweep"] = [{"score": sc, "key": key,
                               "detail": [{"cap_n": cn, "taken": tk, "ret": rt,
                                           "mdd": md, "dist": d}
                                          for cn, tk, rt, md, d in det]}
                              for sc, key, det in rows]

    if args.out:
        with open(args.out, "w") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
        print("写出", args.out, flush=True)


if __name__ == "__main__":
    main()
