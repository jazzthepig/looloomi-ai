"""Trader Tom 的仓位管理(S-596;Jazz 10-16「赢时扩大、只在盈利上加仓、错时少伤」)。

规则(预注册,参数写死,不调):
- 底仓 1.0。未加仓时收盘创 55 日新高 ⇒ 加 0.1、记加仓价;已加仓时收盘 ≥ 上次加仓价 × 1.10 ⇒ 再加 0.1;
  收盘跌破前 20 日最低 ⇒ 加的部分全部撤掉。总敞口上限 1.3(③ 的定义域 0.7–1.3)。
- 防守腿:收盘 < 200 日均线 且 跌破前 20 日最低 ⇒ 底仓 0.7;收盘重新 > 200 日均线 ⇒ 底仓 1.0。
- 第 t 天收盘判断,t+1 生效(调用方负责错一天)。

S-596 在 BTC / ETH 2015–2026 上的结果:PD13 两个资产点估计都高于持有、回撤更浅、涨段跌段都赢;
ETH 四条判据全过,BTC 差在 ab_test 的 p(0.083)与随机分位(0.947)。这里把它放到 ① 的 NAV 上做 ③ 的新臂,前向记。
和 S-568 失败的 ③(按状态择时、反凸性)的区别:**只在自己已经在赚钱时才加**,撤的只是加上去的部分。
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

UNIT, STEP, HI_N, LO_N, MA_N, DEF_BASE, CAP = 0.1, 1.10, 55, 20, 200, 0.7, 1.3


def tom_gross(close: pd.Series, cap: float = CAP, defend: bool = True) -> pd.Series:
    """close:日收盘(或 NAV)。返回 g[d] = d 收盘定下的敞口(作用于 d+1)。历史不足 55 天时 = 1.0。纯函数。"""
    c = close.dropna().astype(float).to_numpy()
    idx = close.dropna().index
    g = np.ones(len(c))
    b, k, last_add = 1.0, 0, None
    for t in range(len(c)):
        x = c[t]
        if t >= HI_N:
            hi = c[t - HI_N:t].max()
            lo = c[t - LO_N:t].min()
            if k > 0 and x < lo:
                k, last_add = 0, None
            elif k == 0 and x > hi and b + UNIT <= cap + 1e-9:
                k, last_add = 1, x
            elif k > 0 and x >= last_add * STEP and b + UNIT * (k + 1) <= cap + 1e-9:
                k, last_add = k + 1, x
            if defend and t >= MA_N - 1:
                ma = c[t - MA_N + 1:t + 1].mean()
                if x < ma and x < lo:
                    b = DEF_BASE
                elif x > ma:
                    b = 1.0
        g[t] = min(cap, b + UNIT * k)
    return pd.Series(g, index=idx)


# ── 交易层(S-600,Jazz 10-16「跌破就空仓,熊市赚了就跑,或者开空」)───────────────────────────────
# ③ 的 0.7 下限是策略层的定义;交易层可以空仓、可以做空。规则与 docs/research/s600_tom_trader.py 逐日一致(测试比对)。
COST_BPS, RALLY_SIZE, RALLY_TP, SHORT_TP, WARM = 10.0, 0.5, 1.15, 0.80, 200


def vol_scale(close: pd.Series) -> pd.Series:
    """S-601:min(1, 过去 730 天 20 日实现波动的中位数 ÷ 当前 20 日实现波动);历史不足 ⇒ 1。只用当天及以前。纯函数。"""
    s = close.dropna().astype(float)
    c = s.to_numpy()
    lr = np.zeros(len(c))
    lr[1:] = np.log(c[1:] / c[:-1])
    v20 = np.full(len(c), np.nan)
    for t in range(20, len(c)):
        v20[t] = lr[t - 19:t + 1].std(ddof=1)
    out = np.ones(len(c))
    for t in range(260, len(c)):
        hist = v20[max(20, t - 730):t + 1]
        hist = hist[np.isfinite(hist)]
        if len(hist) >= 200 and v20[t] > 0:
            out[t] = min(1.0, float(np.median(hist)) / v20[t])
    return pd.Series(out, index=s.index)


def trade_path(close: pd.Series, bear: str, short_size: float = 0.0, exit_mode: str = "ma", vol: bool = False) -> pd.Series:
    """bear ∈ {'flat', 'rally', 'short'}。返回 g[d] = d 收盘定下、d+1 生效的净敞口(前 200 天 = 1.0)。纯函数。
    多头:收盘 > 200 日线且 > 前 20 日高 ⇒ 多 1.0,之后照 tom_gross 加仓(上限 1.3);跌破(< 200 日线且 < 前 20 日低)⇒ 全平。
    熊市:flat 空仓;rally 反弹(> 前 20 日高)多 0.5、+15% 止盈、破前 10 日低止损;short 跌破即开空、−20% 止盈、破前 20 日高止损。"""
    s = close.dropna().astype(float)
    c, n = s.to_numpy(), len(s)
    g = np.ones(n)
    mode, k, last_add, entry = "long", 0, None, None
    for t in range(WARM, n):
        x = c[t]
        ma = c[t - MA_N + 1:t + 1].mean()
        h20, l20, h55, l10 = c[t - 20:t].max(), c[t - 20:t].min(), c[t - 55:t].max(), c[t - 10:t].min()
        long_entry = x > ma and x > h20
        if mode == "long":
            if exit_mode == "l20" and x < l20:          # S-601 X1:多头破前 20 日低即全平(不等 200 日线)
                mode, k, last_add = "flat", 0, None
                g[t] = 0.0
                continue
            if k > 0 and x < l20:
                k, last_add = 0, None
            elif k == 0 and x > h55 and 1 + UNIT <= CAP + 1e-9:
                k, last_add = 1, x
            elif k > 0 and x >= last_add * STEP and 1 + UNIT * (k + 1) <= CAP + 1e-9:
                k, last_add = k + 1, x
            if x < ma and x < l20:
                k, last_add = 0, None
                mode, entry = ("short", x) if bear == "short" else ("flat", None)
        elif mode == "flat":
            if long_entry:
                mode, k = "long", 0
            elif bear == "rally" and x > h20:
                mode, entry = "rally", x
            elif bear == "short" and x < ma and x < l20:
                mode, entry = "short", x
        elif mode == "rally":
            if long_entry:
                mode, k = "long", 0
            elif x >= entry * RALLY_TP or x < l10:
                mode = "flat"
        elif mode == "short":
            if long_entry:
                mode, k = "long", 0
            elif x <= entry * SHORT_TP or x > h20:
                mode = "flat"
        g[t] = {"long": 1 + UNIT * k, "flat": 0.0, "rally": RALLY_SIZE, "short": short_size}[mode]
    out = pd.Series(g, index=s.index)
    if vol:                                               # S-601 V:只在波动高于自己常态时降仓,不放大
        vs = vol_scale(s)
        out = out.where(np.arange(n) < WARM, out * vs)
    return out


def trade_returns(close: pd.Series, g: pd.Series, funding_ann: Optional[pd.Series] = None) -> pd.Series:
    """g[d−1] 作用于 d 的收益:多头 > 1 的部分付资金费、空头收资金费(费率为负则付),|Δg| × 10 bp。现金 0。纯函数。"""
    s = close.dropna().astype(float)
    px = s.pct_change()
    gp = g.reindex(s.index).shift(1)
    prev = g.reindex(s.index).shift(2).fillna(1.0)
    f = (funding_ann.reindex(s.index).ffill().fillna(0.10) if funding_ann is not None else pd.Series(0.10, index=s.index)) / 365
    r = gp * px - (gp - 1).clip(lower=0) * f + (-gp).clip(lower=0) * f - (gp - prev).abs() * COST_BPS / 1e4
    return r.iloc[1:].fillna(0.0)
