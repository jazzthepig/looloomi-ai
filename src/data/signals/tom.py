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
