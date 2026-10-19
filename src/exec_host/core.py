"""云主机执行器的纯函数(T-015 / TRADE_PATH §3c–§5)。没有 I/O,全部可测。

订单逻辑**不在这里重写**:目标 → 订单用 `executor.plan_orders`,取整 / 最小名义额 / 盘口滑点用 `dry_run.size_orders`,
与 Railway 上的纸面空跑是同一组函数。这里只补主机才有的三件事:
1. 真实余额 → 账面(持仓市值、可用 USDC、按 `EXECUTOR_MAX_NAV_USD` 封顶的记账净值);
2. IOC 限价(HL 现货价格规则:5 位有效数字、小数位 ≤ 8 − szDecimals);
3. 交易所回报 → `fill_log.Outcome`(每个意图恰好一个结果;没成交也是结果)。
"""
from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import fields
from typing import Any, Optional

from src.data.execution.dry_run import SPOT_TOKENS
from src.data.execution.fill_log import (BUY, CANCELLED, EXPIRED, FILLED, MAKER, PARTIAL, SELL, TAKER, Intent,
                                         Outcome)

MAX_SPOT_DECIMALS = 8
#: IOC 在限价内一档都吃不到时 HL 返回的错误(这是市场结果 = expired,不是我们的错)
_NO_MATCH = "could not immediately match"


def _f(x: Any) -> Optional[float]:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def round_size(qty: float, sz_decimals: int) -> float:
    from src.data.venues.hl_spot import round_size as _rs
    return _rs(qty, sz_decimals)


def parse_balances(state: Any) -> dict[str, dict[str, float]]:
    """`spotClearinghouseState` → {币: {"total", "hold"}}。"""
    out: dict[str, dict[str, float]] = {}
    for b in (state or {}).get("balances") or []:
        coin, total = b.get("coin"), _f(b.get("total"))
        if coin and total is not None:
            out[coin] = {"total": total, "hold": _f(b.get("hold")) or 0.0}
    return out


def free(balances: dict[str, dict[str, float]], coin: str) -> float:
    b = balances.get(coin) or {}
    return max(0.0, b.get("total", 0.0) - b.get("hold", 0.0))


def round_px_spot(px: float, sz_decimals: int) -> float:
    """HL 现货价格:5 位有效数字,小数位不超过 8 − szDecimals(整数价总是合法)。"""
    return round(float(f"{px:.5g}"), MAX_SPOT_DECIMALS - int(sz_decimals))


def ioc_limit_px(mid: float, side: str, slip_bps: float, sz_decimals: int) -> float:
    """IOC 限价 = 中间价 ±slip_bps。超出这条线的深度宁可不成交(结果记 expired),也不扫穿盘口。"""
    k = slip_bps / 10_000.0
    return round_px_spot(mid * (1 + k) if side == BUY else mid * (1 - k), sz_decimals)


def book_state(balances: dict, quotes: dict, nav_cap: Optional[float], min_notional: float) -> dict[str, Any]:
    """真实余额 → 记账用的账面。低于最小名义额的零头不算持仓(卖不掉,只会天天拒单),单列 `dust`。
    `nav_cap`:账户里超过上限的 USDC 不参与(主账户可以放别的钱,执行器只动它被授权的那一份)。"""
    holdings, dust = {}, {}
    for sym, tok in SPOT_TOKENS.items():
        q = quotes.get(sym) or {}
        qty = (balances.get(tok) or {}).get("total", 0.0)
        if not qty or not q.get("mid"):
            continue
        v = qty * q["mid"]
        (holdings if v >= min_notional else dust)[sym] = v
    cash = free(balances, "USDC")
    held = sum(holdings.values())
    cash_eff = cash if not nav_cap else max(0.0, min(cash, nav_cap - held))
    nav_raw = (balances.get("USDC") or {}).get("total", 0.0) + held + sum(dust.values())
    return {"holdings_usd": holdings, "dust_usd": dust, "cash_usd": cash, "cash_eff": cash_eff,
            "nav_raw": nav_raw, "nav_book": cash_eff + held}


def plan_host_orders(plan: dict, balances: dict, quotes: dict, now_ts: float, nav_cap: Optional[float],
                     halted: bool) -> dict[str, Any]:
    """计划 + 真实余额 + 盘口 → 已取整的订单。卖单数量不超过可用余额。"""
    from src.data.execution import executor as ex
    from src.data.execution.dry_run import size_orders
    known = {f.name for f in fields(ex.Limits)}
    limits = ex.Limits(**{k: v for k, v in (plan.get("limits") or {}).items() if k in known})
    limits.halted = bool(halted)
    st = book_state(balances, quotes, nav_cap, limits.min_notional_usd)
    prices = {s: (q["mid"], now_ts) for s, q in quotes.items() if q.get("mid")}
    p = ex.plan_orders(plan.get("targets") or {}, st["holdings_usd"], st["cash_eff"], prices, now_ts, limits)
    sized, refused = size_orders(p.orders, quotes)
    for o in sized:
        if o["side"] == SELL:
            cap = round_size(free(balances, SPOT_TOKENS[o["symbol"]]), int(quotes[o["symbol"]]["sz_decimals"]))
            o["qty_base"] = min(o["qty_base"], cap)
    return {**st, "orders": sized, "refused": p.refused + refused, "targets": plan.get("targets") or {},
            "limits": limits}


def cap_buy_qty(qty: float, usdc_free: float, limit_px: float, sz_decimals: int, buffer: float = 0.002) -> float:
    """买单数量不超过可用 USDC / 限价(留 0.2% 给手续费与取整)。"""
    if limit_px <= 0:
        return 0.0
    return min(qty, round_size(usdc_free * (1 - buffer) / limit_px, sz_decimals))


def cloid_for(intent_id: str) -> str:
    """意图 id(uuid4)→ HL 客户端订单号(16 字节 hex)。交易所里的每一笔都能追回到它的意图。"""
    return "0x" + uuid.UUID(intent_id).hex


def make_intent(order: dict, sleeve: str, signal_ref: str, decided_at: dt.datetime, limit_px: float) -> Intent:
    return Intent(intent_id=str(uuid.uuid4()), ts_decision=decided_at.isoformat(), symbol=order["symbol"],
                  side=order["side"], target_notional_usd=round(order["qty_base"] * order["price"], 2),
                  decision_mid=order["price"], decision_bid=order.get("bid"), decision_ask=order.get("ask"),
                  sleeve=sleeve, signal_ref=signal_ref, order_type=TAKER, limit_price=limit_px)


def parse_order_response(resp: Any) -> dict[str, Any]:
    """`exchange.order` 的回报 → {"kind": filled | resting | error, ...}。"""
    if not isinstance(resp, dict) or resp.get("status") != "ok":
        return {"kind": "error", "error": str(resp)[:300]}
    try:
        s = resp["response"]["data"]["statuses"][0]
    except (KeyError, IndexError, TypeError):
        return {"kind": "error", "error": f"unexpected response shape: {str(resp)[:300]}"}
    if "filled" in s:
        f = s["filled"]
        return {"kind": "filled", "filled_sz": _f(f.get("totalSz")) or 0.0, "avg_px": _f(f.get("avgPx")),
                "oid": f.get("oid")}
    if "resting" in s:
        return {"kind": "resting", "oid": (s.get("resting") or {}).get("oid")}
    return {"kind": "error", "error": str(s.get("error", s))[:300]}


def fee_for(oid: Any, fills: list[dict]) -> tuple[float, Optional[str]]:
    """同一订单号的手续费合计(USDC)与流动性方向。手续费以基础币计价时按成交价折算。"""
    total, crossed = 0.0, None
    for f in fills or []:
        if oid is None or f.get("oid") != oid:
            continue
        fee, px = _f(f.get("fee")) or 0.0, _f(f.get("px")) or 0.0
        total += fee if (f.get("feeToken") or "USDC") == "USDC" else fee * px
        crossed = f.get("crossed", crossed)
    liq = None if crossed is None else (TAKER if crossed else MAKER)
    return total, liq


def outcome_for(intent: Intent, qty_sent: float, parsed: dict, fills: list[dict], mid_after: Optional[float],
                t_sent: float, t_done: float, resolved_at: dt.datetime) -> Outcome:
    """每个意图恰好一个结果。IOC 一档都没吃到 = expired(市场没给);被交易所拒 = cancelled(写明原因)。"""
    base = dict(intent_id=intent.intent_id, ts_resolved=resolved_at.isoformat(),
                seconds_to_resolve=round(t_done - t_sent, 3), mid_at_resolve=mid_after)
    if parsed["kind"] == "filled" and parsed.get("filled_sz"):
        fee, liq = fee_for(parsed.get("oid"), fills)
        filled = parsed["filled_sz"]
        status = FILLED if filled >= qty_sent * (1 - 1e-9) else PARTIAL
        return Outcome(**base, status=status, filled_notional_usd=round(filled * (parsed.get("avg_px") or 0.0), 6),
                       avg_fill_price=parsed.get("avg_px"), fee_usd=round(fee, 6), liquidity=liq or TAKER,
                       note=f"oid={parsed.get('oid')} qty={filled}/{qty_sent}")
    err = str(parsed.get("error") or parsed.get("kind"))
    if parsed["kind"] == "error" and _NO_MATCH in err.lower():
        return Outcome(**base, status=EXPIRED, note=f"IOC 限价 {intent.limit_price} 内无对手盘:{err[:200]}")
    return Outcome(**base, status=CANCELLED, note=f"未成交:{err[:240]}")


def stop_hits(stop_px: dict, balances: dict, mids: dict, min_notional: float, already: list[str]) -> list[str]:
    """盘中灾难止损:持仓 ≥ 最小名义额 且 现价 < 止损线 且 今天还没止过。"""
    out = []
    for sym, tok in SPOT_TOKENS.items():
        line, mid = (stop_px or {}).get(sym), mids.get(sym)
        if sym in already or not line or not mid:
            continue
        if free(balances, tok) * mid >= min_notional and mid < line:
            out.append(sym)
    return out


def minutes_after_close(now: dt.datetime) -> float:
    from src.data.execution.dry_run import minutes_after_close as _m
    return _m(now)
