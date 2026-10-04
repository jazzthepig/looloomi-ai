"""日线时间戳语义 —— 一处定义(v0.2 原则 P4,T-049)。

**为什么要一处:** 同一类缺陷出过三次,每次都是某个写入端对「这个时间戳代表哪一天」理解错了一天:
S-436(CoinGecko K 线的时间戳是收盘时刻,被当成了开盘那天)、S-459(采样点被当成 K 线,也晚一天)、
S-468(前推的假价)。那时这条规则散在三个文件的注释里,各写各的「减一天」。

**规则(写入的 `trade_date` / `d` 一律 = 这根 bar 覆盖的那一天,UTC):**

| 来源 | 时间戳是什么 | 覆盖日 |
|---|---|---|
| CoinGecko `/ohlc/range`(日 K) | 收盘时刻 = 次日 00:00 UTC | 时间戳日期 − 1 |
| CoinGecko `market_chart` 的 00:00 点 | 那一刻的价格 = 前一天的收盘 | 时间戳日期 − 1 |
| CoinGecko `/global/market_cap_chart` 的 00:00 点 | 同上 | 时间戳日期 − 1 |
| Binance `/klines` 日 K | 开盘时刻 = 当天 00:00 UTC | 时间戳日期 |

新接一个源,先在这里加一行,再写写入端。`tests/test_bar_semantics.py` 钉住每一行,并扫 `src/` 不许别处再自己「减一天」。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

DAY_MS = 86_400_000

#: 来源 → 时间戳标的是 bar 的哪一端。"close" = 收盘时刻(覆盖日 = 前一天),"open" = 开盘时刻(覆盖日 = 当天)。
STAMP = {
    "coingecko_ohlc_range": "close",
    "coingecko_market_chart": "close",
    "coingecko_global_chart": "close",
    "binance_klines": "open",
}


def covered_day(kind: str, ts_ms: int | float) -> date:
    """这根 bar 覆盖的那一天(UTC)。未登记的来源直接报错 —— 不猜。"""
    if kind not in STAMP:
        raise KeyError(f"未登记的时间戳来源 {kind!r} —— 先在 bar_semantics.STAMP 里写清它标的是开盘还是收盘")
    d = datetime.fromtimestamp(float(ts_ms) / 1000, tz=timezone.utc).date()
    return d - timedelta(days=1) if STAMP[kind] == "close" else d


def is_day_boundary(ts_ms: int | float, tolerance_ms: int = 0) -> bool:
    """时间戳是否在 00:00 UTC(容差内,只往后容)。market_chart 只有这一刻的点才是收盘。"""
    return int(ts_ms) % DAY_MS <= tolerance_ms
