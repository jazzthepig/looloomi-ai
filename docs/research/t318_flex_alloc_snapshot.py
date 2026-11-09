"""组合层 v2 的核(S-797,11-10):用「策略风格矢量」配灵活组合 —— 回放与前向同一个核。

## 为什么

Jazz 09-16:「叠加到策略风格矢量里再应用整个 portfolio,就完全不一样了,就不是裸跑了。」SPINE §5 第 7b 段一直是缺段:
真钱 T25 的权重是常数(`forward_books.FLEX_X1V_ARMS['T25']`:加密 ① X1V 30% / 股票 30% / 黄金 20% / 现金),
`book_vectors` 量出了每条腿「在哪种天气里挣钱」,却没有任何一个组合读它。这里是那条边:**天气 → 风格矢量 → 权重**。

## 两条臂(都以 T25 为底,都守 DECISIONS 的偏离预算:加密 0–0.9、金 / 股腿 ±10pp)

- **RB(风险预算,不预测收益):** 最近 `VOL_WINDOW` 个共同日的波动倒数配比,整体缩放到与 T25 同一个事前波动
  (同一份协方差),再按偏离预算截断。台账里按天气预测收益的配法屡次失败(S-585 / S-622–624 / S-650 / S-793),
  风险这一面不需要预测,所以单列一条臂。
- **STYLE(风格矢量):** 每条腿在四种天气(面板在 200 日线上 / 下 × 30/180 波动比 > 1 / ≤ 1,与 `book_vectors` 同口径)里
  的日均收益,减去它全天候的日均收益 = 「这条腿在这种天气里的优势」。此刻天气下优势为正的腿 +`TILT`,为负的 −`TILT`。
  风格表(`StyleTable`)回放里按时点逐月重估(只用 ≤ t 的数据),前向用回放末端**冻结**的那一份(不前向重估)。

纯函数;取数、写库在 `forward_books.run_flex_x1v`。
"""
from __future__ import annotations

import math
from typing import Any, Callable, Optional

import numpy as np
import pandas as pd

LEGS = ("crypto", "equity", "gold")
BASE_T25 = {"crypto": 0.30, "equity": 0.30, "gold": 0.20}
BOUNDS = {"crypto": (0.0, 0.90), "equity": (0.20, 0.40), "gold": (0.10, 0.30)}   # DECISIONS 11-01 / 10-08 偏离预算
VOL_WINDOW = 63
MIN_OBS = 40
SIGMA_FLOOR = 0.002          # 日波动下限:X1V 空仓时腿的波动 ≈ 0,倒数会吃掉全部预算
TILT = 0.10
MIN_BUCKET_DAYS = 60
WEATHERS = ("up_cold", "up_hot", "down_cold", "down_hot")
StyleTable = dict          # {leg: {"all": μ, weather: μ, ...}}


def weather_of(dist_200: Optional[float], vratio_30_180: Optional[float]) -> Optional[str]:
    """纯函数。面板距 200 日线(>0 = 上)与 30/180 波动比(>1 = 热)→ 四种天气之一;缺一个就 None(不猜)。"""
    if dist_200 is None or vratio_30_180 is None:
        return None
    try:
        d, v = float(dist_200), float(vratio_30_180)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(d) and math.isfinite(v)):
        return None
    return ("up" if d > 0 else "down") + ("_hot" if v > 1.0 else "_cold")


def clip_to_budget(w: dict[str, float], bounds: dict[str, tuple[float, float]] = BOUNDS) -> dict[str, float]:
    """纯函数。逐腿截到偏离预算;合计 > 1 时等比缩回 1(余下是现金,收益 0)。"""
    out = {k: min(max(float(w.get(k, 0.0)), bounds[k][0]), bounds[k][1]) for k in LEGS}
    s = sum(out.values())
    if s > 1.0:
        out = {k: v / s for k, v in out.items()}
    return out


def rb_weights(rets: pd.DataFrame, base: dict[str, float] = BASE_T25) -> dict[str, float]:
    """纯函数。rets = 截至当天(含)的日收益(列 = LEGS)。最近 VOL_WINDOW 行里有效行 < MIN_OBS ⇒ 原样返回 base。"""
    win = rets[list(LEGS)].dropna().tail(VOL_WINDOW)
    if len(win) < MIN_OBS:
        return dict(base)
    cov = win.cov().values
    sig = np.maximum(np.sqrt(np.diag(cov)), SIGMA_FLOOR)
    inv = (1.0 / sig) / (1.0 / sig).sum()
    b = np.array([base[k] for k in LEGS])
    vb = float(math.sqrt(max(b @ cov @ b, 0.0)))
    vi = float(math.sqrt(max(inv @ cov @ inv, 0.0)))
    if vi <= 0 or vb <= 0:
        return dict(base)
    w = inv * (vb / vi)
    return clip_to_budget(dict(zip(LEGS, w.tolist())))


def style_table(rets: pd.DataFrame, weather: pd.Series, min_days: int = MIN_BUCKET_DAYS) -> StyleTable:
    """纯函数。每条腿全天候日均与四种天气各自的日均(某天气样本 < min_days ⇒ 该格不写,用的时候当作没有优势)。
    weather 与 rets 按日期对齐;weather 缺的那天只进「全天候」。"""
    df = rets[list(LEGS)].join(weather.rename("w"), how="left")
    out: StyleTable = {}
    for leg in LEGS:
        s = df[[leg, "w"]].dropna(subset=[leg])
        tab = {"all": float(s[leg].mean()) if len(s) else 0.0}
        for w in WEATHERS:
            x = s.loc[s["w"] == w, leg]
            if len(x) >= min_days:
                tab[w] = float(x.mean())
        out[leg] = tab
    return out


def style_weights(table: Optional[StyleTable], weather_now: Optional[str], base: dict[str, float] = BASE_T25) -> dict[str, float]:
    """纯函数。此刻天气下「优势」(该天气日均 − 全天候日均)为正的腿 +TILT、为负的 −TILT;没有表 / 天气未知 / 该格样本不够 ⇒ 不动。"""
    w = dict(base)
    if not table or not weather_now:
        return clip_to_budget(w)
    for leg in LEGS:
        tab = table.get(leg) or {}
        if weather_now in tab and "all" in tab:
            adv = tab[weather_now] - tab["all"]
            if adv > 0:
                w[leg] = base[leg] + TILT
            elif adv < 0:
                w[leg] = base[leg] - TILT
    return clip_to_budget(w)


def dynamic_mix_nav(legs: dict[str, pd.Series], weights_fn: Callable[[pd.DataFrame, Any], dict[str, float]],
                    reb: int = 21, cost: float = 20 / 1e4, start: Optional[pd.Timestamp] = None) -> tuple[pd.Series, list[dict]]:
    """纯函数。与 `forward_books.mix_nav` 同一套记账(共同日期、权重随涨跌漂移、现金收益 0、换手 × cost),
    区别只在目标权重:每 reb 个共同日期调用 weights_fn(截至当天的日收益, 当天日期) 取新目标 —— **只给它当天及以前的数据**。
    start = 从哪天起记 NAV(之前的日期只作历史喂给 weights_fn)。返回 (NAV Series, 每次调仓的 {d, 权重})。"""
    df = pd.concat({k: v for k, v in legs.items()}, axis=1).dropna().sort_index()
    if df.empty:
        return pd.Series(dtype=float), []
    rets = df.pct_change()
    idx = [d for d in df.index if start is None or d >= start]
    if not idx:
        return pd.Series(dtype=float), []
    first = idx[0]
    tgt = pd.Series(weights_fn(rets.loc[:first].iloc[1:], first), dtype=float).reindex(list(LEGS)).fillna(0.0)
    hold = tgt.copy()
    nav, out, log = 1.0, {first: 1.0}, [{"d": first.date().isoformat(), **{k: round(float(v), 4) for k, v in tgt.items()}}]
    for i, d in enumerate(idx[1:], start=1):
        row = rets.loc[d, list(LEGS)]
        g = float((hold * row).sum())
        nav *= 1 + g
        hold = hold * (1 + row) / (1 + g)
        if i % reb == 0:
            new = pd.Series(weights_fn(rets.loc[:d].iloc[1:], d), dtype=float).reindex(list(LEGS)).fillna(0.0)
            nav *= 1 - float((hold - new).abs().sum()) * cost
            hold = new.copy()
            log.append({"d": d.date().isoformat(), **{k: round(float(v), 4) for k, v in new.items()}})
        out[d] = nav
    return pd.Series(out), log
