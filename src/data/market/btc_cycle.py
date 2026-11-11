"""BTC 的中长线周期指标(11-11,Jazz「我们不是有观察 MVRV 和恐惧贪婪嘛?还有对比挖矿收益,这些都是中长线很好的择时指标」)。

## 为什么建这张表

恐惧贪婪早就在 `macro_daily`(series `fng`,2018-02 起,`cis_inputs`);**MVRV 与矿工收益从来没有按天落库** ——
S-84(07-27)用过的 MVRV 是免费源 2022-07 起的临时取数,挖矿那条(Puell / 难度成本)也是研究脚本里现取的。
没有历史表,任何「配置级、低频、双向」的过热 / 过冷判断(S-812 / S-813)都只能用价格自己。这里把三条接进来:

| series(`macro_daily`) | 含义 | 来源 |
|---|---|---|
| `btc_mvrv` | 市值 / 已实现市值 | Coin Metrics 社区 API `CapMVRVCur` |
| `btc_issuance_usd` | 当日新发行 BTC 的美元价值(矿工的区块奖励收入) | `IssTotUSD` |
| `btc_hashrate` | 全网算力 | `HashRate` |

**Puell 倍数**(矿工收入对它自己 365 天均值的倍数 —— 「对比挖矿收益」最常用的读法)不落库,读的时候由 `puell()` 现算
(纯函数,只用 ≤ d 的数据),避免两份口径。

## 口径

d = Coin Metrics 时间戳的 UTC 日期(日度值在当天 00:00 UTC 标记,覆盖的是那一天);第一次跑从 `HISTORY_FROM` 全量写,
之后每天只取最近 `RECENT_D` 天(覆盖修订)。读不到 ⇒ 报错不写(读不到 ≠ 没有)。

判活:`select series, min(d), max(d), count(*) from macro_daily where series like 'btc_%' group by 1`。
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Optional

TABLE = "macro_daily"
WRITES_TABLES = (TABLE,)
WRITES_COLUMNS = {TABLE: ("series", "d", "value", "source")}
METRICS = {"CapMVRVCur": "btc_mvrv", "IssTotUSD": "btc_issuance_usd", "HashRate": "btc_hashrate"}
SOURCE = "coinmetrics_community"
HISTORY_FROM = "2011-01-01"
RECENT_D = 14
DONE_KEY = "btc_cycle:{d}"
PUELL_WINDOW = 365


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x and x not in (float("inf"), float("-inf")) else None


def to_rows(raw: list[dict]) -> list[dict]:
    """纯函数。Coin Metrics 行 → macro_daily 行;缺值 / 非数 / 非正(MVRV、发行、算力都必须 > 0)丢掉,不写 0。"""
    out = []
    for r in raw or []:
        d = str(r.get("time") or "")[:10]
        if len(d) != 10:
            continue
        for metric, series in METRICS.items():
            v = _f(r.get(metric))
            if v is not None and v > 0:
                out.append({"series": series, "d": d, "value": v, "source": SOURCE})
    return out


def puell(issuance: dict[str, float], d: str, window: int = PUELL_WINDOW) -> Optional[float]:
    """纯函数。Puell 倍数 = d 当天的发行美元价值 ÷ 截至 d(含)最近 window 天的均值;不足 window 天 ⇒ None。只用 ≤ d。"""
    days = sorted(k for k in issuance if k <= d)
    if len(days) < window or days[-1] != d:
        return None
    vals = [issuance[k] for k in days[-window:]]
    m = sum(vals) / window
    return issuance[d] / m if m > 0 else None


async def run_once(now: Optional[dt.datetime] = None, *, force: bool = False) -> dict[str, Any]:
    from src.api.store import redis_get_key_status, redis_set_key, supabase_upsert_table
    from src.data.market.data_layer import get_coinmetrics_btc
    from src.data.vector.market_state_writer import _sb_get
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    key = DONE_KEY.format(d=now.date().isoformat())
    if not force:
        st, _ = await redis_get_key_status(key)
        if st == "hit":
            return {"ok": True, "skipped": True, "why": "今天已经取过"}
    have = await _sb_get(TABLE, {"select": "d", "series": "eq.btc_mvrv", "order": "d.desc", "limit": "1"})
    if not have.ok:
        return {"ok": False, "why": f"读 {TABLE} 失败:{(have.why or '')[:120]}"}
    start = HISTORY_FROM if not have.rows else (now.date() - dt.timedelta(days=RECENT_D)).isoformat()
    raw = await get_coinmetrics_btc(list(METRICS), start)
    rows = to_rows(raw)
    for i in range(0, len(rows), 1000):
        if not await supabase_upsert_table(TABLE, rows[i:i + 1000], on_conflict="series,d"):
            return {"ok": False, "why": f"写 {TABLE} 失败(第 {i} 行起)"}
    last = max((r["d"] for r in rows), default=None)
    await redis_set_key(key, {"rows": len(rows), "last": last}, ttl=2 * 86400)
    return {"ok": True, "rows": len(rows), "from": start, "last": last,
            "why": f"BTC 周期指标 {len(rows)} 行(自 {start},最新 {last})"}
