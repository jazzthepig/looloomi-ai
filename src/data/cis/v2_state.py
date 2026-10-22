"""CIS v2 状态层(台账 S-669;Jazz 10-22)—— 只描述,不进分数,不冒充预测。

S-669 的结论决定了这里给什么:
- **趋势标签**(上升 / 下降 / 震荡)够稳,可以展示;历史不足 200 天的名字只用 SMA50,标 `short_history`。
- **动量、资金费**换得太快,不贴标签,**只给数值**(30 日收益、7 日平均资金费年化)。
- **市场情绪**是组级的:加密看恐惧贪婪(≥ 75 贪婪 / ≤ 25 恐惧),传统资产看 VIX(≥ 25 紧张 / ≤ 15 平静)。
- 没有一个标签过得了置换对照 ⇒ 对外写「描述,不是预测」。

全部纯函数;数据由 `v2_shadow` 读好传进来。
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Optional, Sequence

TREND_LONG, TREND_SHORT = 200, 50
FNG_GREED, FNG_FEAR = 75.0, 25.0
VIX_STRESS, VIX_CALM = 25.0, 15.0
#: 资金费每年结算次数(币安 8 小时一次;Hyperliquid 每小时一次)
FUNDING_PERIODS_PER_YEAR = {"binance_perp": 3 * 365, "hyperliquid": 24 * 365}


def _mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs)


def trend(closes: Sequence[float]) -> dict[str, Any]:
    """closes = 日收盘,升序,最后一个是 d 当天。S-669 原文的标签。"""
    cs = [float(c) for c in closes if c]
    if len(cs) < TREND_SHORT:
        return {"label": None, "basis": "insufficient"}
    c, s50 = cs[-1], _mean(cs[-TREND_SHORT:])
    if len(cs) >= TREND_LONG:
        s200 = _mean(cs[-TREND_LONG:])
        label = "up" if c > s50 > s200 else "down" if c < s50 < s200 else "range"
        return {"label": label, "basis": "sma50_sma200", "close_vs_sma50": round(c / s50 - 1, 4),
                "sma50_vs_sma200": round(s50 / s200 - 1, 4)}
    return {"label": "up" if c > s50 else "down", "basis": "short_history", "close_vs_sma50": round(c / s50 - 1, 4)}


def momentum_30d(series: Sequence[tuple[str, float]], d: Any) -> Optional[float]:
    """series = [(日期, 收盘)] 升序;d 当天收盘 ÷ 30 个日历日前(当天或之前最后一个)收盘 − 1。"""
    day = d if isinstance(d, dt.date) else dt.date.fromisoformat(str(d)[:10])
    then_d = (day - dt.timedelta(days=30)).isoformat()
    now = [c for s, c in series if s <= day.isoformat()]
    then = [c for s, c in series if s <= then_d]
    if not now or not then or not then[-1]:
        return None
    return round(now[-1] / then[-1] - 1.0, 4)


def funding_apr_7d(rows: Sequence[dict], d: Any) -> Optional[dict[str, Any]]:
    """rows = funding_history 的行(symbol 已筛好);优先币安,没有再用 Hyperliquid。7 天平均,年化。"""
    day = d if isinstance(d, dt.date) else dt.date.fromisoformat(str(d)[:10])
    lo = (day - dt.timedelta(days=7)).isoformat()
    hi = (day + dt.timedelta(days=1)).isoformat()
    for venue in ("binance_perp", "hyperliquid"):
        rs = [float(r["funding_rate"]) for r in rows if r.get("venue") == venue and r.get("funding_rate") is not None
              and lo <= str(r["funding_time"])[:10] < hi]
        if rs:
            return {"apr": round(_mean(rs) * FUNDING_PERIODS_PER_YEAR[venue], 4), "venue": venue, "n": len(rs)}
    return None


def sentiment(group: str, value: Optional[float]) -> dict[str, Any]:
    if value is None:
        return {"label": None, "source": "fng" if group == "crypto" else "vix", "value": None}
    if group == "crypto":
        lab = "greed" if value >= FNG_GREED else "fear" if value <= FNG_FEAR else "neutral"
        return {"label": lab, "source": "fng", "value": value}
    lab = "stress" if value >= VIX_STRESS else "calm" if value <= VIX_CALM else "normal"
    return {"label": lab, "source": "vix", "value": value}


def state_for(group: str, closes: Sequence[tuple[str, float]], d: Any, funding_rows: Sequence[dict] = (),
              market_value: Optional[float] = None) -> dict[str, Any]:
    """一个名字在 d 的状态。closes 只用 ≤ d 的。"""
    day = d if isinstance(d, dt.date) else dt.date.fromisoformat(str(d)[:10])
    upto = [(s, c) for s, c in closes if s <= day.isoformat() and c]
    out: dict[str, Any] = {"trend": trend([c for _, c in upto]), "momentum_30d": momentum_30d(upto, day),
                           "market": sentiment(group, market_value), "is_forecast": False}
    if group == "crypto":
        out["funding_7d"] = funding_apr_7d(funding_rows, day)
    return out
