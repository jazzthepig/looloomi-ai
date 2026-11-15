"""三态敞口 R6(S-823)与「闸门关时空大盘」(S-819)的前向内核 —— **纯函数**,参数照搬研究脚本,一个都没改。

出处(研究侧,逐行对照;测试 `tests/test_state_arms.py` 用 T-392 导出的逐日净值证明逐日相同):
- **R6(S-823)**:`docs/research/s823_three_state.py` 的 `states(p)["R6"]` 与 `account(...)`
  — 明显向上 e=+1.0 / 不明确 e=+0.3 / 明显向下 e=−0.3;成本 0.10% 每次换敞口;信号 d 日收盘定、d+1 生效。
  R6 = 「在 200 日线上方且 200 日线斜率为正」⇒ 上;「在 200 日线下方且斜率为负、且不在 V 形护栏外」⇒ 下;其余中间。
- **闸门空头(S-819)**:`docs/research/s819_gate_short.py` 的 `short_ret(gs, s)`
  — 闸门用**前一天**的;闸门关着时空大盘(BTC/ETH 永续 50/50),规模 s;翻转当天扣 0.05%×s;空头**收**资金费。
- **闸门定义**:`docs/research/t310_slots.py` 的 `load_gate` —— majors 市值加权指数按日收益复原水平,
  收盘在自己的 200 日均线上方 = 闸门开(不足 200 天算开)。生产从 `style_index_pit_daily`
  (`style=eq.majors`, `weighting=eq.cap`) 取同一条序列 —— 与研究闸门在重叠历史上逐日相同(测试证明)。

三条纪律:
1. **参数写死,前向只追加** —— 改任何常数都会让这条前向账与已经写下的行接不上缝。
2. **纯函数** —— 这里不读库、不写库、不取当前时间;输入给什么就算什么(回放与前向同一个核)。
3. **不预测、不调参** —— 这里只算账;信号是「资产在哪里」,不是「该买该卖」。
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

# ── R6(S-823 三态敞口)─────────────────────────────────────────────────────────
E_DOWN, E_MID, E_UP = -0.3, 0.3, 1.0          # s823_three_state.py:E_DOWN, E_MID, E_UP
R6_COST = 0.0010                               # s823_three_state.py:COST(每次换敞口 10bp)
R6_MA, R6_SLOPE, R6_LOW = 200, 30, 90          # 200 日均线 / 斜率回看 30 日 / V 形护栏用前 90 日最低


def r6_exposure(close: pd.Series) -> pd.Series:
    """close:日收盘。返回 e[d] = **d 日收盘定下**的敞口(作用于 d+1),取值 {−0.3, +0.3, +1.0}。纯函数。

    与 `s823_three_state.py::states` 的 R6 逐行相同:
      均线 m200 = 收盘的 200 日均值;斜率 = m200 − m200.shift(30);
      上 = (收盘 > m200) 且 (斜率 > 0);下 = (收盘 < m200) 且 (斜率 < 0) 且 不在 V 形护栏外(收盘 ≤ 1.25 × 前 90 日最低);
      其余 = +0.3。历史不足(均线/斜率还没成形)时一律 +0.3。
    """
    p = close.dropna().astype(float)
    m200 = p.rolling(R6_MA).mean()
    slope = m200 - m200.shift(R6_SLOPE)
    low90 = p.rolling(R6_LOW).min()
    ok = m200.notna() & slope.notna()
    up = (p > m200) & (slope > 0)
    dn = (p < m200) & (slope < 0) & ~(p > 1.25 * low90)
    e = pd.Series(E_MID, index=p.index, dtype=float)
    e[up & ok] = E_UP
    e[dn & ok] = E_DOWN
    return e


def r6_returns(close: pd.Series, exposure: pd.Series, funding: Optional[pd.Series] = None,
               start: Optional[str] = None, end: Optional[str] = None):
    """返回 (日收益, 生效敞口, 空头腿日收益) —— 与 `s823_three_state.py::account` 逐行相同。纯函数。

    敞口 d−1 作用于 d;资金费按天求和(不是年化)填在有数的日子,缺的日子记 0;
    成本 = |Δ敞口| × 0.10%;空头腿 = (敞口 < 0) 时的 (敞口×收益 + |敞口|×资金费)。
    """
    p = close.dropna().astype(float)
    e = exposure.reindex(p.index)
    r = p.pct_change()
    pos = e.shift(1)
    fd = (funding.reindex(p.index).fillna(0.0) if funding is not None
          else pd.Series(0.0, index=p.index, dtype=float))
    ret = pos * r + (-pos.clip(upper=0)) * fd - R6_COST * (pos - pos.shift(1)).abs().fillna(0)
    short_leg = (pos < 0) * (pos * r + (-pos) * fd)
    keep = pd.Series(True, index=p.index)
    if start is not None:
        keep &= p.index >= pd.Timestamp(start)
    if end is not None:
        keep &= p.index <= pd.Timestamp(end)
    m = keep.to_numpy()
    return ret[m].fillna(0.0), pos[m], short_leg[m].fillna(0.0)


# ── 闸门(S-819 的闸门 + 同一个读法)────────────────────────────────────────────
GATE_FLIP_COST = 0.0005                        # s819_gate_short.py:翻转扣 0.05% × s


def majors_gate_from_ret(ret: pd.Series) -> pd.Series:
    """majors 市值加权指数按日收益复原水平 → 收盘在自己的 200 日均线上方 = **闸门开**。纯函数。

    与 `t310_slots.py::load_gate` 同一读法:水平 = cumprod(1+ret);SMA200 含当天;不足 200 天算开;
    单日跌幅超过 95% 的行整行丢掉(与研究同一处理)。
    """
    r = ret.dropna().astype(float)
    r = r[r > -0.95]
    if r.empty:
        return pd.Series(dtype=bool)
    lvl = (1.0 + r).cumprod()
    sma = lvl.rolling(200, min_periods=1).mean()
    n = lvl.rolling(200, min_periods=1).count()
    return (n < 200) | (lvl > sma)


def gate_short_returns(basket_ret: pd.Series, funding: pd.Series, gate_open: pd.Series, s: float):
    """返回 (空头腿日收益, 闸门是否关着) —— 与 `s819_gate_short.py::short_ret` 逐行相同。纯函数。

    闸门用**前一天**的:`closed[d] = 闸门在 d−1 关着`。关着时收 `−s × 篮子收益 + s × 资金费`(空头收资金费);
    闸门开↔关翻转当天扣 0.05% × s。篮子与资金费要在同一条日历上(调用方负责)。
    """
    g = gate_open.astype(bool)
    closed = (~g).shift(1).fillna(False).astype(bool)
    flips = (closed != closed.shift(1).fillna(False)).astype(float)
    b = basket_ret.reindex(closed.index).fillna(0.0)
    f = funding.reindex(closed.index).fillna(0.0)
    ret = closed * (-s * b + s * f) - flips * GATE_FLIP_COST * s
    return ret, closed


def basket_returns(closes: dict[str, pd.Series]) -> pd.Series:
    """篮子日收益 = 各成分等权平均(缺的日子按 0 计)。纯函数。S-819 的篮子 = BTC/ETH 永续 50/50。"""
    parts = [c.pct_change() for c in closes.values()]
    if not parts:
        return pd.Series(dtype=float)
    df = pd.concat(parts, axis=1)
    return df.mean(axis=1, skipna=False).fillna(0.0)


def basket_funding(funding: dict[str, pd.Series]) -> pd.Series:
    """篮子资金费 = 各成分按天求和后的等权平均(缺的日子 0)。纯函数。"""
    parts = []
    for c in funding.values():
        s = c.groupby(c.index.normalize()).sum() if len(c) else c
        parts.append(s)
    if not parts:
        return pd.Series(dtype=float)
    df = pd.concat(parts, axis=1).fillna(0.0)
    return df.mean(axis=1)


def gate_calendar(basket: pd.Series, funding: pd.Series, gate: pd.Series,
                  start: Optional[str] = None, end: Optional[str] = None):
    """把篮子 / 资金费 / 闸门对到**同一条日历**上。纯函数。

    闸门是慢状态:非交易日沿用上一个值(`.ffill()`)—— 与研究 `s819_gate_short.py` 的
    `g.reindex(cal).ffill()` 同一读法(研究那条 `cal` 是自然日历、周末也记 ⇒ 周末的涨跌不丢)。
    篮子缺的日子按 0 计(不猜),资金费缺的日子按 0 计。

    返回 (basket, funding, gate_open) 三条同索引的序列。
    """
    idx = basket.index.union(funding.index).union(gate.index)
    if start is not None:
        idx = idx[idx >= pd.Timestamp(start)]
    if end is not None:
        idx = idx[idx <= pd.Timestamp(end)]
    if len(idx) == 0:
        empty = pd.Series(dtype=float)
        return empty, empty, pd.Series(dtype=bool)
    b = basket.reindex(idx).fillna(0.0)
    f = funding.reindex(idx).fillna(0.0)
    g = gate.reindex(idx).ffill()
    if g.isna().any():
        g = g.fillna(True)          # 闸门历史还没开始 ⇒ 按研究的读法「不足 200 天算开」
    return b, f, g.astype(bool)
