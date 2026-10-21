"""R-v2 单票在 HL 永续上的执行 —— 纯函数(没有 I/O,全部可测)。runner.Executor 只负责读写交易所与发件箱。

## 每天一轮(计划 ready 且 asof = 昨天)

1. **对账:** 主机账上的票,交易所上已经没有仓位 ⇒ 止损触发单成交了(或被人手动平了),记「交易所上已平」。
2. **出场:** 主机账上的票不在计划的 `hold` 里 ⇒ 减仓 IOC 卖出(先撤它的止损触发单)。原因写进意图的 signal_ref。
3. **进场:** 计划的 `enter`,按信号日、名字的顺序;不在 HL 上 / 主机已满 10 张 / 同一个币已有仓 / 按风险算出来不到
   最小名义额 ⇒ 记「不可执行」,不找别的票替补。仓位 = 风险预算 ÷ 止损距离:
   `名义 = 净值 × risk_frac ÷ stop_frac`(单票名义不超过净值的一半,合计不超过净值本身);成交后按成交价挂减仓止损触发单
   `止损 = 成交价 × (1 − stop_frac)`。

## 盘中(每分钟)

交易所上的触发单是第一道止损(主机掉线也在);主机每分钟再看一次现价 ≤ 止损线且仓位还在 ⇒ 补一张减仓 IOC
(触发单没挂上或被拒时的后备)。减仓单不会把多头翻成空头,两道同时触发也只平掉一次。
空跑没有交易所仓位:按中间价「虚拟成交」,止损按现价 ≤ 止损线虚拟平仓 —— 空跑账本就是第一张票与回放对账用的那本。
"""
from __future__ import annotations

import math
from typing import Any, Optional

PERP_MAX_DECIMALS = 6
MIN_NOTIONAL_USD = 10.0
MAX_TICKET_NOTIONAL_FRAC = 0.5      # 单票名义不超过净值的一半(止损很窄时风险预算会算出很大的名义)
MAX_GROSS_FRAC = 1.0                # 策略层:名义合计 ≤ 分到的资金(Jazz 10-21:策略 0–1 倍;S-638 f = 1% 回放峰值 0.99 倍)
MAX_PORTFOLIO_LEVERAGE = 5.0        # 组合层杠杆 L 的硬上限(Jazz 10-21);分到的资金 = 账户净值 × L
TRIGGER_LIMIT_SLIP = 0.10           # 止损触发后按市价成交;HL 仍要一个限价 = 触发价再让 10%


def _f(x: Any) -> Optional[float]:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def round_px_perp(px: float, sz_decimals: int) -> float:
    """HL 永续价格:5 位有效数字,小数位不超过 6 − szDecimals。"""
    return round(float(f"{px:.5g}"), max(0, PERP_MAX_DECIMALS - int(sz_decimals)))


def round_size_down(qty: float, sz_decimals: int) -> float:
    k = 10 ** int(sz_decimals)
    return math.floor(qty * k + 1e-9) / k


def ioc_px_perp(mid: float, is_buy: bool, slip_bps: float, sz_decimals: int) -> float:
    k = slip_bps / 10_000.0
    return round_px_perp(mid * (1 + k) if is_buy else mid * (1 - k), sz_decimals)


def perp_meta(meta: Any) -> dict[str, int]:
    """`info.meta()` → {币: szDecimals}(下架的不算)。"""
    out = {}
    for u in (meta or {}).get("universe") or []:
        if u.get("name") and not u.get("isDelisted"):
            out[u["name"]] = int(u.get("szDecimals") or 0)
    return out


def resolve_coin(symbol: str, names: dict[str, int] | set[str]) -> Optional[str]:
    """账本里的名字 → HL 永续的币名。HL 把小面值币做成 1000 倍面值(PEPE → kPEPE);止损按比例给,所以不用换算价格。"""
    if symbol in names:
        return symbol
    if f"k{symbol}" in names:
        return f"k{symbol}"
    return None


def parse_perp_state(us: Any) -> dict[str, Any]:
    """`info.user_state(地址)` → {"ok", "equity": 账户净值, "positions": {币: 张数(多为正)}}。"""
    ms = (us or {}).get("marginSummary") or {}
    pos = {}
    for ap in (us or {}).get("assetPositions") or []:
        p = ap.get("position") or {}
        szi = _f(p.get("szi"))
        if p.get("coin") and szi:
            pos[p["coin"]] = szi
    # ok = 读到了账户(有 marginSummary)。读不到 ≠ 没有仓位 —— 调用方据此决定能不能记「交易所上已平」
    return {"ok": bool(ms), "equity": _f(ms.get("accountValue")) or 0.0, "positions": pos}


def size_entry(equity: float, risk_frac: float, stop_frac: float, mid: float, sz_decimals: int) -> dict[str, Any]:
    """风险预算 → 张数。返回 qty = 0 时带原因。"""
    if not (equity > 0 and stop_frac and 0 < stop_frac < 0.9 and mid and mid > 0):
        return {"qty": 0.0, "notional": 0.0, "why": f"参数不全:净值 {equity}、止损比例 {stop_frac}、现价 {mid}"}
    risk = equity * risk_frac
    notional = min(risk / stop_frac, equity * MAX_TICKET_NOTIONAL_FRAC)
    qty = round_size_down(notional / mid, sz_decimals)
    n = qty * mid
    if n < MIN_NOTIONAL_USD:
        return {"qty": 0.0, "notional": round(n, 2),
                "why": f"按风险 ${risk:.2f} ÷ 止损 {stop_frac:.1%} 只够 ${n:.2f},低于 HL 最小名义额 ${MIN_NOTIONAL_USD:.0f}"}
    return {"qty": qty, "notional": round(n, 2), "risk_usd": round(risk, 2), "why": None,
            "capped": notional < risk / stop_frac}


def stop_px_for(fill_px: float, stop_frac: float, sz_decimals: int) -> float:
    return round_px_perp(fill_px * (1 - stop_frac), sz_decimals)


def trigger_order(stop_px: float, sz_decimals: int) -> tuple[float, dict]:
    """减仓止损触发单:(限价, order_type)。触发后按市价,限价只是滑点上限。"""
    return (round_px_perp(stop_px * (1 - TRIGGER_LIMIT_SLIP), sz_decimals),
            {"trigger": {"triggerPx": stop_px, "isMarket": True, "tpsl": "sl"}})


def ticket_actions(tplan: dict, book: dict[str, dict], positions: dict[str, float], mids: dict[str, float],
                   szd: dict[str, int], equity: float, done: set[str]) -> dict[str, Any]:
    """纯函数。计划 + 主机账 + 交易所仓位(空跑 = 账上的虚拟仓位)→ 今天要做的事。不下单。"""
    hold = {h["ticket_id"] for h in tplan.get("hold") or []}
    why_exit = {x["ticket_id"]: x.get("why") for x in tplan.get("exit") or []}
    closed_on_venue, exits = [], []
    for tid, b in sorted(book.items()):
        have = positions.get(b["coin"], 0.0)
        if have <= 0:
            closed_on_venue.append({"ticket_id": tid, "coin": b["coin"], "stop_px": b.get("stop_px")})
        elif tid not in hold:
            exits.append({"ticket_id": tid, "coin": b["coin"], "qty": min(b["qty"], have),
                          "why": why_exit.get(tid) or "不在账本的持有单里"})
    open_after = len(book) - len(closed_on_venue) - len(exits)
    held_coins = {b["coin"] for t, b in book.items() if t not in {x["ticket_id"] for x in exits + closed_on_venue}}
    cap = int(tplan.get("cap") or 10)
    # 组合层杠杆:策略按「分到的资金」= 净值 × L 记账;L 读不到按 1,超过 5 按 5(主机这一侧再守一次上限)
    lev = min(max(float(tplan.get("portfolio_leverage") or 1.0), 1.0), MAX_PORTFOLIO_LEVERAGE)
    alloc = equity * lev
    gone = {x["ticket_id"] for x in exits + closed_on_venue}
    gross = sum(b["qty"] * (mids.get(b["coin"]) or b.get("entry_px") or 0.0) for t, b in book.items() if t not in gone)
    entries, not_exec = [], []
    for e in tplan.get("enter") or []:
        tid = e["ticket_id"]
        if tid in book or tid in done:
            continue
        coin = resolve_coin(e["symbol"], szd)
        if coin is None:
            not_exec.append({**e, "why": "HL 上没有这个永续"})
            continue
        if open_after >= cap:
            not_exec.append({**e, "coin": coin, "why": f"主机已满 {cap} 张"})
            continue
        if coin in held_coins:
            not_exec.append({**e, "coin": coin, "why": "同一个币已有一张票的仓位"})
            continue
        mid = mids.get(coin)
        s = size_entry(alloc, float(tplan.get("risk_frac") or 0), e.get("stop_frac"), mid, szd[coin])
        if not s["qty"]:
            not_exec.append({**e, "coin": coin, "why": s["why"], "mid": mid})
            continue
        if gross + s["notional"] > alloc * MAX_GROSS_FRAC:
            not_exec.append({**e, "coin": coin, "mid": mid,
                             "why": f"名义合计会到 ${gross + s['notional']:.0f},超过分到的资金 ${alloc:.0f}"
                                    f"(净值 × 组合杠杆 {lev:g})的 {MAX_GROSS_FRAC} 倍"})
            continue
        entries.append({**e, "coin": coin, "mid": mid, "sz_decimals": szd[coin], **s})
        gross += s["notional"]
        open_after += 1
        held_coins.add(coin)
    return {"closed_on_venue": closed_on_venue, "exits": exits, "entries": entries, "not_executable": not_exec,
            "portfolio_leverage": lev, "alloc": alloc}


def stop_breaches(book: dict[str, dict], mids: dict[str, float]) -> list[str]:
    """现价 ≤ 止损线的票(后备止损 / 空跑的虚拟止损)。"""
    return [tid for tid, b in sorted(book.items())
            if b.get("stop_px") and mids.get(b["coin"]) and mids[b["coin"]] <= b["stop_px"]]
