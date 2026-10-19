"""历史回放:按日线把**实盘执行器的同一组函数**跑一遍(T-134;NautilusTrader 的原则:研究 = 实盘)。

## 为什么

S-610 的 SQL 模拟、Railway 的纸面空跑、东京主机的执行器原来是三份实现 —— 模拟里的行为不一定是实盘的行为。
这里不另写规则:每个交易日
1. 计划 = `host_plan.make_plan`(Railway /plan 用的同一个函数);
2. 订单 = `exec_host.core.plan_host_orders`(主机用的同一个函数:真实余额口径、净值封顶、szDecimals 取整、
   最小名义额、单笔 / 当日换手上限);
3. 盘中灾难止损 = `exec_host.core.stop_hits`(主机每分钟用的同一个判定),日线上用当天最低价近似「盘中碰到」。
回放与实盘只差在**行情从哪来**(这里是日线,实盘是盘口)和**成交价**(这里按假设的价差与费率)。

## 成交假设(写死,可传参)

- 收盘后 1 小时内按收盘价 ± `half_spread_bps` 成交(X1V 的规则就是收盘后马上下单),手续费 `fee_bps`;
- 盘中止损:当天最低价 < 止损线 ⇒ 按 min(开盘价, 止损线) × (1 − `stop_slip_bps`) 卖出(跳空低开按开盘价);
- 盘口用一档极深的合成盘口(只为让 `size_orders` 的滑点估计可用;滑点按 half_spread 计)。
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Optional

import pandas as pd

from src.data.execution.dry_run import SPOT_TOKENS
from src.data.execution.fill_log import BUY, SELL
from src.data.execution.host_plan import make_plan
from src.exec_host import core

#: HL 现货 UBTC / UETH 的 szDecimals(10-18 实测,T-123)
SZ_DECIMALS = {"BTC": 5, "ETH": 4}


def synthetic_quotes(mids: dict[str, float], half_spread_bps: float) -> dict[str, dict]:
    """收盘价 → 主机 quotes 的同一形状(含一档极深的合成盘口)。"""
    from src.data.venues.hl_spot import L2Book, L2Level
    out = {}
    for sym, mid in mids.items():
        h = mid * half_spread_bps / 10_000.0
        book = L2Book(coin=sym, time_ms=0, bids=(L2Level(mid - h, 1e12, 1),), asks=(L2Level(mid + h, 1e12, 1),))
        out[sym] = {"pair": sym, "mid": mid, "bid": mid - h, "ask": mid + h,
                    "sz_decimals": SZ_DECIMALS.get(sym, 4), "book": book}
    return out


def _balances(usdc: float, qty: dict[str, float]) -> dict[str, dict[str, float]]:
    b = {"USDC": {"total": usdc, "hold": 0.0}}
    for sym, tok in SPOT_TOKENS.items():
        b[tok] = {"total": qty.get(sym, 0.0), "hold": 0.0}
    return b


def replay(ohlc: dict[str, pd.DataFrame], start: str, end: Optional[str] = None, account: float = 3_000.0,
           nav_cap: Optional[float] = 3_000.0, half_spread_bps: float = 2.0, fee_bps: float = 7.0,
           stop_slip_bps: float = 30.0) -> dict[str, Any]:
    """ohlc:{币: DataFrame(index = 日期, 列 open/high/low/close)}。返回逐日净值、成交与止损记录。"""
    syms = [s for s in SPOT_TOKENS if s in ohlc]
    days = sorted(set.intersection(*(set(ohlc[s].index) for s in syms)))
    days = [d for d in days if str(d)[:10] >= start and (end is None or str(d)[:10] <= end)]
    usdc, qty = float(account), {s: 0.0 for s in syms}
    nav_rows, trades, stops = [], [], []
    plan: Optional[dict] = None
    for d in days:
        ds = str(d)[:10]
        row = {s: ohlc[s].loc[d] for s in syms}
        # ① 盘中:用前一天收盘后的计划里的止损线(主机缓存的就是它)
        if plan:
            lows = {s: float(row[s]["low"]) for s in syms}
            for sym in core.stop_hits(plan["stop_px"], _balances(usdc, qty), lows, 10.0, []):
                line = plan["stop_px"][sym]
                px = min(float(row[sym]["open"]), line) * (1 - stop_slip_bps / 10_000.0)
                proceeds = qty[sym] * px * (1 - fee_bps / 10_000.0)
                stops.append({"d": ds, "symbol": sym, "qty": qty[sym], "px": px, "line": line})
                usdc, qty[sym] = usdc + proceeds, 0.0
        # ② 收盘后:同一个计划函数、同一个下单函数
        closes = {s: ohlc[s]["close"].loc[:d].astype(float) for s in syms}
        plan = make_plan(closes, ds)
        mids = {s: float(row[s]["close"]) for s in syms}
        res = core.plan_host_orders(plan, _balances(usdc, qty), synthetic_quotes(mids, half_spread_bps),
                                    now_ts=0.0, nav_cap=nav_cap, halted=False)
        for o in res["orders"]:
            sym, q = o["symbol"], o["qty_base"]
            if o["side"] == BUY:
                px = mids[sym] * (1 + half_spread_bps / 10_000.0)
                q = core.cap_buy_qty(q, usdc, px, SZ_DECIMALS.get(sym, 4))
                cost = q * px * (1 + fee_bps / 10_000.0)
                if q <= 0 or cost > usdc:
                    continue
                usdc, qty[sym] = usdc - cost, qty[sym] + q
            else:
                q = min(q, qty[sym])
                px = mids[sym] * (1 - half_spread_bps / 10_000.0)
                usdc, qty[sym] = usdc + q * px * (1 - fee_bps / 10_000.0), qty[sym] - q
            trades.append({"d": ds, "symbol": sym, "side": o["side"], "qty": q, "px": px})
        nav = usdc + sum(qty[s] * mids[s] for s in syms)
        nav_rows.append({"d": ds, "nav": nav, "usdc": usdc, **{f"w_{s}": qty[s] * mids[s] / nav for s in syms},
                         **{f"t_{s}": plan["targets"].get(s, 0.0) for s in syms}})
    return {"nav": pd.DataFrame(nav_rows).set_index("d") if nav_rows else pd.DataFrame(),
            "trades": trades, "stops": stops, "final_plan": plan}


def ideal_nav(ohlc: dict[str, pd.DataFrame], start: str, end: Optional[str] = None) -> pd.Series:
    """对照:按前一天收盘定下的目标权重、零摩擦、零门槛地持有到今天收盘(前向账本的理想口径)。"""
    syms = [s for s in SPOT_TOKENS if s in ohlc]
    days = sorted(set.intersection(*(set(ohlc[s].index) for s in syms)))
    days = [d for d in days if str(d)[:10] >= start and (end is None or str(d)[:10] <= end)]
    nav, out, w = 1.0, {}, {s: 0.0 for s in syms}
    from src.data.execution import executor as ex
    for i, d in enumerate(days):
        if i:
            prev = days[i - 1]
            r = sum(w[s] * (float(ohlc[s]["close"].loc[d]) / float(ohlc[s]["close"].loc[prev]) - 1) for s in syms)
            nav *= 1 + r
        w = ex.target_weights({s: ohlc[s]["close"].loc[:d].astype(float) for s in syms})
        out[str(d)[:10]] = nav
    return pd.Series(out)
