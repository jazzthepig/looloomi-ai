"""v0.2 阶段 1 —— 公用记账内核。所有账本的逐日 NAV 都从这里算,**其他地方不许自己写记账**。

为什么(S-437):ETH 多空回测持仓数周、却每笔只记前 5 天盈亏 —— 每个策略各写一套记账,错法各不相同,
而且没有任何东西会发现两本账对同一天用了不同的记账规则。一套内核,同一套规则:

1. 权重随价格漂移:收益 = Σ w_i · r_i,之后 w_i ← w_i (1 + r_i) / (1 + 收益)。
2. 当天没有真实收盘的持仓按 0 收益记,**并计数**(`n_filled`);有真实收盘的持仓权重 < `min_quoted_weight`
   ⇒ 抛异常 —— 读不到,不记成没涨跌(S-180)。
3. `orders[d]` = 在 d 收盘时要换成的目标权重。**信号在哪天出、滞后几天,是调用方的事**:
   内核只负责「在这天收盘按这个目标成交」。滞后放在调用方,内核才能对所有策略是同一个。
4. 成交成本 = 换手 × cost_bps;先记当天价格收益,再扣成本(与既有两本账的运算顺序逐位一致)。

仓位缩放、提前离场、回撤止损都是**进内核之前**对 `orders` 的变换(S-442),不是内核参数。
"""
from __future__ import annotations

from typing import Mapping, Optional

import pandas as pd


def run_nav(prices: pd.DataFrame, orders: Mapping[pd.Timestamp, Mapping[str, float]], *,
            cost_bps: float, min_quoted_weight: float, label: str = "",
            renormalize_to_quoted: bool = True,
            days: Optional[list] = None) -> list[dict]:
    """逐日记账。返回每天一条:nav、价格收益、成本、含成本收益、收盘后持仓、是否成交、换手、补零个数、有报价个数。

    `prices`:行 = 日期,列 = 标的;NaN = 当天没有真实收盘(前推价应由调用方抹掉)。
    `days`:要记账的日子(默认 prices 的全部行)。第一天没有持仓,只有当天的 order 会建仓。
    `renormalize_to_quoted`:成交时只在当天有报价的标的上分配,并把权重重新归一。
    """
    days = list(days if days is not None else prices.index)
    w: dict[str, float] = {}
    last: dict[str, float] = {}
    nav = 1.0
    out: list[dict] = []
    for i, d in enumerate(days):
        row_px = prices.loc[d]
        quoted = {s for s in row_px.index if pd.notna(row_px[s])}
        ret, n_filled = 0.0, 0
        if i > 0 and w:
            qw = sum(v for s, v in w.items() if s in quoted)
            if qw < min_quoted_weight:
                raise ValueError(f"{pd.Timestamp(d).date()} {label}:有真实收盘的持仓权重只有 {qw:.0%} "
                                 f"< {min_quoted_weight:.0%} —— 读不到,不记成没涨跌")
            rets = {}
            for s in w:
                if s in quoted and s in last:
                    rets[s] = float(row_px[s]) / last[s] - 1
                else:
                    rets[s] = 0.0
                    n_filled += 1
            ret = sum(w[s] * rets[s] for s in w)
            nav *= 1 + ret
            w = {s: v * (1 + rets[s]) / (1 + ret) for s, v in w.items()}
        for s in quoted:
            last[s] = float(row_px[s])

        traded, turnover, cost = False, 0.0, 0.0
        tgt = orders.get(d)
        if tgt is not None:
            if renormalize_to_quoted:
                tgt = {s: v for s, v in tgt.items() if s in quoted}
                tot = sum(tgt.values())
                tgt = {s: v / tot for s, v in tgt.items()}
            else:
                tgt = dict(tgt)
            keys = set(tgt) | set(w)
            turnover = sum(abs(tgt.get(s, 0.0) - w.get(s, 0.0)) for s in keys)
            cost = turnover * cost_bps / 1e4
            nav *= 1 - cost
            w, traded = tgt, True
        out.append({"d": d, "nav": nav, "ret_gross": ret, "cost": cost,
                    "ret": (1 + ret) * (1 - cost) - 1, "w": dict(w), "traded": traded,
                    "turnover": turnover, "n_filled": n_filled, "n_quoted": len(quoted & set(w))})
    return out
