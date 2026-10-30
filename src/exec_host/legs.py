"""T25 的黄金 / 股票腿在 HL 现货上执行(Jazz 10-30「yes」:XAUT0 @182、SPYX @703,与 X1V 同一个账户)—— 纯函数。

## 规则(与组合层目标表同一份数,`portfolio_targets.plan_fields()["t25"]`)

- 每条腿一个美元目标(T25 资本 × 权重:黄金 20% = $120、股票 30% = $180,起始资本 600)。
- **再平衡日**(开账日起每 21 个工作日)⇒ 每条腿回到目标;**其余日子** ⇒ 只有偏离 > 偏离带 × 资本(5% × 600 = $30)的腿回到目标。
  第一次接上时持仓是 0,偏离 = 目标本身 ⇒ 直接建仓(不用等再平衡日)。
- 差额不到最小名义额($10)或取整后为 0 ⇒ 不动(写明原因)。
- 卖单不超过可用余额;买单在下单那一刻按可用 USDC 再截一次(`runner._execute`)。

现阶段资本固定在 600(与目标表一致);再平衡日按真钱快照重定资本是 P5 的事。
"""
from __future__ import annotations

from typing import Any, Optional

#: 记账名 → HL 现货代币名(都对 USDC)。记账名就用代币名,对账时不用再翻译。
LEG_TOKENS = {"XAUT0": "XAUT0", "SPYX": "SPYX"}
MIN_NOTIONAL_USD = 10.0
SLEEVES = {"dry_run": "t25_legs_host_dry", "live": "t25_legs_live"}


def _f(x: Any) -> Optional[float]:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def holdings_usd(balances: dict[str, dict[str, float]], quotes: dict[str, dict]) -> dict[str, float]:
    """每条腿现在持有多少美元(按盘口中间价)。没有报价的腿不出现 —— 读不到 ≠ 0。"""
    out = {}
    for sym, tok in LEG_TOKENS.items():
        q = quotes.get(sym) or {}
        if q.get("mid"):
            out[sym] = float((balances.get(tok) or {}).get("total", 0.0)) * float(q["mid"])
    return out


def leg_orders(t25: dict, held: dict[str, float]) -> dict[str, Any]:
    """计划的 t25 段 + 每条腿现有美元 → 名义额订单(还没取整)。不下单。"""
    legs = (t25 or {}).get("legs") or {}
    capital = _f((t25 or {}).get("capital_usd")) or 0.0
    band = _f((t25 or {}).get("band")) or 0.05
    rebalance = bool((t25 or {}).get("rebalance_today"))
    orders, skipped = [], []
    for sym in sorted(legs):
        if sym not in LEG_TOKENS:
            skipped.append({"symbol": sym, "why": "不是这个执行器认识的腿"})
            continue
        target = _f(legs[sym].get("target_usd"))
        if target is None or target < 0:
            skipped.append({"symbol": sym, "why": "没有目标额"})
            continue
        if sym not in held:
            skipped.append({"symbol": sym, "why": "没有盘口报价 —— 持仓读不到,不下单"})
            continue
        have = held[sym]
        diff = target - have
        drift = abs(diff) / capital if capital > 0 else 0.0
        if not rebalance and drift <= band:
            skipped.append({"symbol": sym, "why": f"偏离 {drift:.1%} ≤ {band:.0%},不是再平衡日", "held_usd": round(have, 2)})
            continue
        if abs(diff) < MIN_NOTIONAL_USD:
            skipped.append({"symbol": sym, "why": f"差额 ${abs(diff):.2f} 不到最小名义额", "held_usd": round(have, 2)})
            continue
        orders.append({"symbol": sym, "side": "buy" if diff > 0 else "sell", "notional_usd": round(abs(diff), 2),
                       "target_usd": target, "held_usd": round(have, 2),
                       "why": "再平衡日" if rebalance else f"偏离 {drift:.1%} > {band:.0%}"})
    # 卖在前:先腾出 USDC 再买
    orders.sort(key=lambda o: 0 if o["side"] == "sell" else 1)
    return {"orders": orders, "skipped": skipped, "rebalance_today": rebalance, "capital_usd": capital, "band": band}


def size_leg_orders(orders: list[dict], quotes: dict[str, dict],
                    balances: dict[str, dict[str, float]]) -> tuple[list[dict], list[str]]:
    """名义额 → 数量(与 X1V 同一个 `dry_run.size_orders`:szDecimals 向下取整、最小名义额、按盘口估滑点);
    卖单不超过可用余额。"""
    from src.data.execution.dry_run import size_orders
    from src.data.venues.hl_spot import round_size
    sized, refused = size_orders(orders, quotes)
    for o in sized:
        if o["side"] == "sell":
            b = balances.get(LEG_TOKENS[o["symbol"]]) or {}
            # round(…, 10):0.06 − 0.02 = 0.03999… 向下取整会变 0.03,留一截卖不掉的零头
            free = max(0.0, round(float(b.get("total", 0.0)) - float(b.get("hold", 0.0)), 10))
            o["qty_base"] = min(o["qty_base"], round_size(free, int(quotes[o["symbol"]]["sz_decimals"])))
    return [o for o in sized if o["qty_base"] > 0], refused
