"""执行器核心(T-122,TRADE_PATH §3c;Jazz 10-18「执行期提前」)。

X1V 的降回撤靠**及时出场**(S-602 模拟五:出场推迟 3 天,BTC 回撤 −39% → −64%),所以执行方式就是规则的一部分:
- UTC 收盘后 1 小时内,按刚收盘的日线算 X1V 目标(信号与 tom_trader 前向账本同一个核 `tom.trade_path`),出订单计划;
- 盘中只做一件事:**灾难止损** —— 价格低于前 20 日最低收盘 × 0.92 ⇒ 立刻平(防跳空崩盘,不替代收盘规则);
- 现货、不借杠杆:X1V 的加仓部分(> 1.0)在现货版里截到 1.0。

这里全是纯函数 + 一个 dry-run 周期(只算不发,意图落 `execution_intents`,TRADE_PATH §5 第 1–2 天)。
真下单要 Jazz 的 HL API 钱包(只可交易、不可提币),私钥只在云主机的环境变量里,不经过 Seth、不经过任何 lane。
"""
from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from src.data.execution.fill_log import BUY, SELL, TAKER, Intent

#: 交易的币与各自在加密腿里的份额(各半)
SLEEVES = {"BTC": 0.5, "ETH": 0.5}
CATASTROPHE = 0.92            # 盘中价 < 前 20 日最低收盘 × 0.92 ⇒ 立刻平
SPOT_CAP = 1.0                # 现货不借杠杆
SIGNAL_REF = "x1v_spot_v1:TRADE_PATH §3c / S-601"


@dataclass
class Limits:
    min_trade_frac: float = 0.05        # 目标与当前权重差 < 5% 不动(出场 / 进场除外)
    max_order_usd: float = 2_000.0      # 单笔上限(3,000U 试跑)
    max_daily_turnover_usd: float = 6_000.0
    max_price_age_s: float = 120.0      # 价格过期就拒绝,不猜价
    min_notional_usd: float = 10.0
    halted: bool = False                # 一键停(Redis 标志位由调用方读进来)


@dataclass
class Plan:
    orders: list[dict] = field(default_factory=list)
    refused: list[str] = field(default_factory=list)
    targets: dict[str, float] = field(default_factory=dict)


def x1v_spot_target(close: pd.Series) -> float:
    """一个币当天收盘后定下的现货目标敞口 ∈ [0, 1]。与前向账本同一个核(tom.trade_path, X1V)。纯函数。"""
    from src.data.signals.tom import trade_path
    g = trade_path(close, "rally", 0.0, exit_mode="l20", vol=True)
    return float(min(SPOT_CAP, max(0.0, g.iloc[-1])))


def target_weights(closes: dict[str, pd.Series], sleeves: dict[str, float] = SLEEVES) -> dict[str, float]:
    """{币: 占交易账户净值的目标权重}。纯函数。"""
    return {sym: share * x1v_spot_target(closes[sym]) for sym, share in sleeves.items() if sym in closes}


def catastrophe_hit(price_now: float, closes: pd.Series, factor: float = CATASTROPHE) -> bool:
    """盘中灾难止损:当前价 < 前 20 日(不含今天)最低收盘 × factor。纯函数。"""
    c = closes.dropna()
    if len(c) < 20 or not price_now or price_now <= 0:
        return False
    return bool(price_now < float(c.iloc[-20:].min()) * factor)


def plan_orders(targets: dict[str, float], holdings_usd: dict[str, float], cash_usd: float,
                prices: dict[str, tuple[float, float]], now_ts: float, limits: Limits = Limits()) -> Plan:
    """targets:{币: 目标权重};holdings_usd:{币: 当前市值};prices:{币: (价格, 价格时间戳)}。纯函数。
    规则:一键停 ⇒ 不出单;价格过期 ⇒ 该币拒单;|Δw| < min_trade_frac 不动,但目标 0 的出场与从 0 进场照做;
    单笔与当日换手上限截断(出场优先,先卖后买)。"""
    plan = Plan(targets=dict(targets))
    if limits.halted:
        plan.refused.append("halted:一键停")
        return plan
    nav = cash_usd + sum(holdings_usd.values())
    if nav <= 0:
        plan.refused.append("nav<=0")
        return plan
    wanted = []
    for sym, tw in targets.items():
        px = prices.get(sym)
        if not px or not px[0] or now_ts - px[1] > limits.max_price_age_s:
            plan.refused.append(f"{sym}:价格过期或缺失,不猜价")
            continue
        cur = holdings_usd.get(sym, 0.0)
        cw = cur / nav
        dw = tw - cw
        exit_all = tw == 0 and cur > 0
        enter = cw == 0 and tw > 0
        if not (exit_all or enter or abs(dw) >= limits.min_trade_frac):
            continue
        notional = -cur if exit_all else dw * nav
        wanted.append((sym, notional, px[0]))
    wanted.sort(key=lambda x: x[1])                       # 卖单在前
    budget = limits.max_daily_turnover_usd
    for sym, notional, price in wanted:
        side = SELL if notional < 0 else BUY
        size = min(abs(notional), limits.max_order_usd, budget)
        if size < limits.min_notional_usd:
            plan.refused.append(f"{sym}:{side} {abs(notional):.2f} 低于最小名义额或超出当日换手")
            continue
        budget -= size
        plan.orders.append({"symbol": sym, "side": side, "notional_usd": round(size, 2), "price": price,
                            "truncated": size < abs(notional) - 1e-9})
    return plan


def intents_from_plan(plan: Plan, decided_at: Optional[dt.datetime] = None, sleeve: str = "x1v_spot") -> list[Intent]:
    """计划 → fill_log 的意图(决策时中间价 = 计划用的价)。纯函数。"""
    ts = (decided_at or dt.datetime.now(dt.timezone.utc)).isoformat()
    return [Intent(intent_id=str(uuid.uuid4()), ts_decision=ts, symbol=o["symbol"], side=o["side"],
                   target_notional_usd=o["notional_usd"], decision_mid=o["price"], sleeve=sleeve,
                   signal_ref=SIGNAL_REF, order_type=TAKER) for o in plan.orders]


async def dry_run_cycle(closes: dict[str, pd.Series], holdings_usd: dict[str, float], cash_usd: float,
                        prices: dict[str, tuple[float, float]], now_ts: float, limits: Limits = Limits(),
                        write: bool = True) -> dict:
    """只算不发:目标 → 计划 → 意图落表(不下单)。返回本轮的全部中间量,供人工核对(TRADE_PATH §5)。"""
    from src.data.execution.fill_log import write_intent
    targets = target_weights(closes)
    plan = plan_orders(targets, holdings_usd, cash_usd, prices, now_ts, limits)
    intents = intents_from_plan(plan)
    written = 0
    if write:
        for i in intents:
            written += int(await write_intent(i))
    return {"targets": targets, "orders": plan.orders, "refused": plan.refused, "intents": len(intents), "written": written}
