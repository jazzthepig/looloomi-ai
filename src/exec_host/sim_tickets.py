"""R-v2 单票的代入模拟(S-647)—— 不是把收益序列乘杠杆,而是让实盘执行器的同一个决策函数逐日过一遍真钱账户会经历的事。

## 和回测差在哪

回测(S-638 / S-646)问的是「这条规则赚多少」;这里问的是「一个 \\$704 的 HL 账户照着执行器去做,会发生什么」:
- **决策**:每天开盘一轮,调的就是主机用的 `exec_host.tickets.ticket_actions`(进 / 出 / 不可执行、按风险定仓、
  单票与合计名义上限、同时最多 10 张、组合杠杆 L);占位用 Railway 计划的 `ticket_plan.taken_ids`。
- **成交**:开盘价 ± 滑点,吃单手续费;止损是交易所触发单,跳空按开盘成交。
- **账户**:USDC 保证金账户。开仓前要有足够的可用保证金(不够 ⇒ 交易所拒单);每天按「所有持仓同时落在当日最低」
  检查维持保证金,不够 ⇒ 整户强平(比 HL 的逐仓减仓保守)。资金费按币按日扣。闲置现金(扣掉初始保证金)按放贷利率计息。
- **组合政策**:恒定 L,或回撤刹车(越亏杠杆越小,只作用于新票)。

票与它们各自的日线路径是输入(`SimTicket`);日历只是一个整数日序。历史回放与蒙特卡洛(把历史月份重抽后搬到合成日历上)
走的是同一个 `simulate`。

纯函数:没有 I/O,全部可测。数据装载与报告在 `docs/research/s647_sim_r_v2.py`。
"""
from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from src.data.execution.ticket_plan import taken_ids
from src.exec_host import tickets as tk

EPOCH = dt.date(2000, 1, 1)


@dataclass(frozen=True)
class SimTicket:
    tid: str
    symbol: str
    entry_day: int                    # 进场日(整数日序;回放 = (日期 − EPOCH).days)
    exit_off: Optional[int]           # 第几天开盘那一轮不再在持有单里(None = 到数据末尾仍持有)
    paper_exit_off: Optional[int]     # 纸面账本的出场日偏移(占位规则用;None = 仍持有)
    stop_frac: float
    path: tuple                       # ((open, high, low, close, funding_sum_of_day), ...) 从进场日起
    signal_day: int = 0
    major: bool = False               # BTC / ETH:滑点更小、最大杠杆更高


@dataclass(frozen=True)
class Venue:
    slip_bps: float = 25.0
    slip_bps_major: float = 5.0
    stop_slip_bps: float = 50.0
    stop_slip_bps_major: float = 10.0
    fee_bps: float = 4.5
    max_lev: float = 5.0
    max_lev_btc: float = 40.0
    max_lev_eth: float = 25.0
    liq_slip: float = 0.01
    funding_fallback_ann: float = 0.10


@dataclass
class SimResult:
    equity: list = field(default_factory=list)       # 每天收盘权益
    liquidations: int = 0
    fees: float = 0.0
    funding: float = 0.0
    lending: float = 0.0
    refused: dict = field(default_factory=dict)       # 不可执行原因 → 张数
    entered: int = 0
    stops: int = 0
    peak_gross_frac: float = 0.0
    peak_margin_frac: float = 0.0


def sz_decimals_for(price: float) -> int:
    """HL 的 szDecimals 让一个最小单位约值 \\$0.1–1:BTC 5、ETH 4、几美元的币 1、几分钱的币 0。"""
    if not price or price <= 0:
        return 0
    return int(min(5, max(0, math.ceil(math.log10(price)))))


def max_lev_for(coin: str, v: Venue) -> float:
    return v.max_lev_btc if coin == "BTC" else v.max_lev_eth if coin == "ETH" else v.max_lev


def brake(lev: float, equity: float, peak: float, dd_full: float = 0.30, floor: float = 0.25) -> float:
    """回撤刹车:L_t = L × clip(1 + DD / dd_full, floor, 1)。"""
    dd = equity / peak - 1 if peak > 0 else 0.0
    return lev * min(1.0, max(floor, 1 + dd / dd_full))


def _bar(t: SimTicket, off: int) -> tuple:
    """路径上第 off 天的 (o, h, l, c, funding);越界 ⇒ 用最后收盘平推、资金费 0。"""
    if 0 <= off < len(t.path):
        return t.path[off]
    c = t.path[-1][3]
    return (c, c, c, c, 0.0)


def taken_set(tickets_: list[SimTicket], cap: int) -> set[str]:
    """纸面账本的占位(= r_tickets_nav / ticket_plan.taken_ids),在**全部**票上走。"""
    rows = []
    for t in tickets_:
        x = None if t.paper_exit_off is None else EPOCH + dt.timedelta(days=t.entry_day + t.paper_exit_off)
        rows.append({"ticket_id": t.tid, "symbol": t.symbol, "status": "open" if x is None else "closed",
                     "signal_d": (EPOCH + dt.timedelta(days=t.signal_day)).isoformat(),
                     "entry_d": (EPOCH + dt.timedelta(days=t.entry_day)).isoformat(),
                     "exit_d": None if x is None else x.isoformat()})
    return taken_ids(rows, cap, EPOCH)


def simulate(tickets_: list[SimTicket], equity0: float, lev: float, *, policy: str = "const",
             risk_frac: float = 0.005, cap: int = 10, executable: Optional[Callable[[SimTicket], bool]] = None,
             apy_for_day: Optional[Callable[[int], float]] = None, venue: Venue = Venue(),
             start_day: Optional[int] = None, end_day: Optional[int] = None,
             collateral_mult: Optional[float] = None, collateral_gross: Optional[float] = None) -> SimResult:
    """逐日模拟一个 HL 永续账户。`executable(t)` = 这张票的币在 HL 上有没有(没有 ⇒ 执行器记不可执行)。

    `collateral_mult` —— 钱放在哪(决定强平时能用来扛的是多少):
      None  = 预注册口径:全部现金都算作 HL 上的保证金缓冲,同时(权益 − 初始保证金)又在拿放贷利息 —— 两头都偏乐观;
      inf   = 全部现金留在 HL 上,不放贷(缓冲最厚,没有利息);
      k     = HL 上只留 k × 初始保证金(每天收盘调拨一次,开盘前补足),其余放贷 —— 强平只能用 HL 上那一份扛,
              HL 上的钱亏光为止(超出部分由 HL 的强平机制承担,不追到放贷的钱)。
    `collateral_gross` = g(给了就覆盖 collateral_mult):HL 上留 g × 持仓名义,其余放贷(S-647 补 2 的 C')。"""
    v = venue
    taken = taken_set(tickets_, cap)
    by_entry: dict[int, list[SimTicket]] = {}
    for t in tickets_:
        if t.tid in taken:
            by_entry.setdefault(t.entry_day, []).append(t)
    for lst in by_entry.values():
        lst.sort(key=lambda t: (t.signal_day, t.symbol))
    d0 = start_day if start_day is not None else min(t.entry_day for t in tickets_)
    d1 = end_day if end_day is not None else max(t.entry_day + (t.exit_off if t.exit_off is not None else len(t.path))
                                                 for t in tickets_)
    tmap = {t.tid: t for t in tickets_}
    res = SimResult()
    split = collateral_gross is not None or (collateral_mult is not None and math.isfinite(collateral_mult))

    def target_on(im: float, gross: float) -> float:
        return collateral_gross * gross if collateral_gross is not None else collateral_mult * im
    lend = apy_for_day is not None and not (collateral_mult is not None and math.isinf(collateral_mult))
    on, off = (0.0, float(equity0)) if split else (float(equity0), 0.0)   # HL 上的 USDC / 放贷里的 USDC
    peak = float(equity0)
    pos: dict[str, dict] = {}                          # tid → {coin, qty, entry, stop, szd, lev}
    done: set[str] = set()

    def bar(tid: str, day: int) -> tuple:
        t = tmap[tid]
        return _bar(t, day - t.entry_day)

    def realize(tid: str, fill: float) -> None:
        nonlocal on
        p = pos.pop(tid)
        fee = p["qty"] * fill * v.fee_bps / 1e4
        on += p["qty"] * (fill - p["entry"]) - fee
        res.fees += fee
        done.add(tid)

    def topup(target: float) -> None:
        """把 HL 上的权益调到 target(从放贷里取 / 存回放贷);放贷里不够就有多少给多少。"""
        nonlocal on, off
        e_on = on + sum(p["qty"] * (bar(tid, day)[0] - p["entry"]) for tid, p in pos.items())
        delta = min(target - e_on, off) if target > e_on else target - e_on
        on += delta
        off -= delta

    for day in range(d0, d1 + 1):
        opens = {tid: bar(tid, day)[0] for tid in pos}
        eq_open = on + off + sum(p["qty"] * (opens[tid] - p["entry"]) for tid, p in pos.items())
        lev_t = brake(lev, eq_open, peak) if policy == "brake" else lev
        enter = by_entry.get(day, [])
        leaving = [tid for tid in pos
                   if tmap[tid].exit_off is not None and day >= tmap[tid].entry_day + tmap[tid].exit_off]
        if (enter or leaving) and eq_open > 0:
            # 1) 主机一轮:实盘的 ticket_actions
            hold = [{"ticket_id": tid} for tid in pos if tid not in leaving]
            ent = [{"ticket_id": t.tid, "symbol": t.symbol, "signal_d": str(t.signal_day), "stop_frac": t.stop_frac}
                   for t in enter]
            szd = {p["coin"]: p["szd"] for p in pos.values()}
            mids = {p["coin"]: opens[tid] for tid, p in pos.items()}
            for t in enter:
                if executable is None or executable(t):
                    szd[t.symbol] = sz_decimals_for(t.path[0][0])
                    mids[t.symbol] = t.path[0][0]
            book = {tid: {"coin": p["coin"], "qty": p["qty"], "entry_px": p["entry"], "stop_px": p["stop"]}
                    for tid, p in pos.items()}
            plan = {"ready": True, "risk_frac": risk_frac, "cap": cap, "portfolio_leverage": lev_t,
                    "enter": ent, "hold": hold, "exit": []}
            act = tk.ticket_actions(plan, book, {p["coin"]: p["qty"] for p in pos.values()}, mids, szd, eq_open, done)
            for x in act["exits"]:
                s = (v.slip_bps_major if tmap[x["ticket_id"]].major else v.slip_bps) / 1e4
                realize(x["ticket_id"], opens[x["ticket_id"]] * (1 - s))
            for n in act["not_executable"]:
                key = str(n.get("why"))[:12]
                res.refused[key] = res.refused.get(key, 0) + 1
                done.add(n["ticket_id"])
            if act["entries"] and split:               # 开盘前把要用的保证金从放贷里调过来
                need = sum(e["qty"] * e["mid"] / max_lev_for(e["coin"], v) for e in act["entries"])
                need_g = sum(e["qty"] * e["mid"] for e in act["entries"])
                im = sum(p["qty"] * opens.get(tid, p["entry"]) / p["lev"] for tid, p in pos.items())
                g0 = sum(p["qty"] * opens.get(tid, p["entry"]) for tid, p in pos.items())
                topup(target_on(im + need, g0 + need_g))
            for e in act["entries"]:
                t = tmap[e["ticket_id"]]
                s = (v.slip_bps_major if t.major else v.slip_bps) / 1e4
                fill = t.path[0][0] * (1 + s)
                qty, ml = e["qty"], max_lev_for(e["coin"], v)
                used = sum(pp["qty"] * bar(tt, day)[0] / pp["lev"] for tt, pp in pos.items())
                e_on = on + sum(pp["qty"] * (bar(tt, day)[0] - pp["entry"]) for tt, pp in pos.items())
                if qty * fill / ml > e_on - used:      # 交易所:可用保证金不够 ⇒ 拒单
                    res.refused["保证金不够"] = res.refused.get("保证金不够", 0) + 1
                    done.add(t.tid)
                    continue
                fee = qty * fill * v.fee_bps / 1e4
                on -= fee
                res.fees += fee
                pos[t.tid] = {"coin": e["coin"], "qty": qty, "entry": fill, "szd": e["sz_decimals"], "lev": ml,
                              "stop": fill * (1 - t.stop_frac)}
                res.entered += 1
        # 2) 盘中:交易所止损触发单(当日进场当日可触发)
        for tid in list(pos):
            p = pos[tid]
            o, h, lo, c, _f = bar(tid, day)
            if lo <= p["stop"]:
                ss = (v.stop_slip_bps_major if tmap[tid].major else v.stop_slip_bps) / 1e4
                realize(tid, min(o, p["stop"]) * (1 - ss))
                res.stops += 1
        # 3) 维持保证金:所有持仓同时落在当日最低;只能用 HL 上的权益扛
        if pos:
            lows = {tid: bar(tid, day)[2] for tid in pos}
            e_low = on + sum(p["qty"] * (lows[tid] - p["entry"]) for tid, p in pos.items())
            maint = sum(p["qty"] * lows[tid] / p["lev"] / 2 for tid, p in pos.items())
            if e_low < maint:
                for tid in list(pos):
                    realize(tid, lows[tid] * (1 - v.liq_slip))
                on = max(on, 0.0)                      # HL 上的钱亏光为止
                res.liquidations += 1
        # 4) 资金费(多头付正费率)、收盘权益、放贷、调拨
        closes = {tid: bar(tid, day) for tid in pos}
        for tid, p in pos.items():
            b = closes[tid]
            off_i = day - tmap[tid].entry_day
            f = b[4] if off_i < len(tmap[tid].path) and b[4] is not None else v.funding_fallback_ann / 365.0
            fpay = p["qty"] * b[3] * f
            on -= fpay
            res.funding += fpay
        e_on = on + sum(p["qty"] * (closes[tid][3] - p["entry"]) for tid, p in pos.items())
        gross = sum(p["qty"] * closes[tid][3] for tid, p in pos.items())
        margin = sum(p["qty"] * closes[tid][3] / p["lev"] for tid, p in pos.items())
        if lend:
            base = off if split else max(0.0, e_on - margin)
            y = base * apy_for_day(day) / 365.0
            if split:
                off += y
            else:
                on += y
            res.lending += y
        if split:                                      # 收盘调拨:HL 上只留 k × 初始保证金
            target = min(e_on + off, target_on(margin, gross))
            delta = target - e_on
            if delta > 0:
                delta = min(delta, off)
            on += delta
            off -= delta
            e_on += delta
        eq = e_on + off
        if eq > 0:
            res.peak_gross_frac = max(res.peak_gross_frac, gross / eq)
            res.peak_margin_frac = max(res.peak_margin_frac, margin / eq)
        peak = max(peak, eq)
        res.equity.append(eq)
    return res


def stats(equity: list, equity0: float, days_per_year: float = 365.0) -> dict[str, Any]:
    if not equity:
        return {"cagr": None, "mdd": None, "end": equity0}
    end = equity[-1]
    yrs = len(equity) / days_per_year
    cagr = (end / equity0) ** (1 / yrs) - 1 if end > 0 and yrs > 0 else -1.0
    peak, mdd = equity0, 0.0
    for e in equity:
        peak = max(peak, e)
        mdd = min(mdd, e / peak - 1 if peak > 0 else -1.0)
    return {"cagr": cagr, "mdd": mdd, "end": end}
