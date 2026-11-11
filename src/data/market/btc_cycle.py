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
| `btc_price_usd` | 参考价(2011 起;Binance 现货只到 2017-08,周期空间要四轮周期)| `PriceUSD` |
| `btc_puell` | **Puell 倍数** = 当日矿工收入 ÷ 它自己过去 365 天均值(「对比挖矿收益」)| 由 `puell()` 从上面算 |
| `btc_hash_30d` | 算力 30 天变化 = ln(近 7 天均值 ÷ 30 天前的 7 天均值)(矿工投降 / 扩张)| 由 `hash_30d()` 算 |

两条派生序列只有一个定义(本模块的纯函数,只用 ≤ d 的数据),写入端与读的人用同一个函数。
`macro_daily` 的每条序列会自动并进融合特征表(`feature_matrix_daily` 的 `macro:<series>` 键)⇒ MVRV / Puell / 算力变化
从此是市场态向量空间里的维(11-11 Jazz「keep in high dimension」;用法见 `state/cycle_space.py`,S-814)。

## 口径

d = Coin Metrics 时间戳的 UTC 日期(日度值在当天 00:00 UTC 标记,覆盖的是那一天);第一次跑从 `HISTORY_FROM` 全量写,
之后每天只取最近 `RECENT_D` 天(覆盖修订)。读不到 ⇒ 报错不写(读不到 ≠ 没有)。

判活:`select series, min(d), max(d), count(*) from macro_daily where series like 'btc_%' group by 1`。
"""
from __future__ import annotations

import datetime as dt
import math
from typing import Any, Optional

TABLE = "macro_daily"
WRITES_TABLES = (TABLE,)
WRITES_COLUMNS = {TABLE: ("series", "d", "value", "source")}
METRICS = {"CapMVRVCur": "btc_mvrv", "IssTotUSD": "btc_issuance_usd", "HashRate": "btc_hashrate", "PriceUSD": "btc_price_usd"}
DERIVED = ("btc_puell", "btc_hash_30d")
DERIVE_LOOKBACK_D = 420         # 派生序列要 365 天历史;日常只取这么多天就够重算最近 RECENT_D 天
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


def hash_30d(hashrate: dict[str, float], d: str) -> Optional[float]:
    """纯函数。算力 30 天变化 = ln(截至 d 的 7 天均值 ÷ 截至 d − 30 天的 7 天均值);任一窗口不满 7 天 ⇒ None。只用 ≤ d。"""
    d0 = dt.date.fromisoformat(d)

    def avg(end: dt.date) -> Optional[float]:
        vals = [hashrate.get((end - dt.timedelta(days=i)).isoformat()) for i in range(7)]
        if any(v is None or v <= 0 for v in vals):
            return None
        return sum(vals) / 7
    a, b = avg(d0), avg(d0 - dt.timedelta(days=30))
    return math.log(a / b) if a and b else None


def derived_rows(base: list[dict], since: str) -> list[dict]:
    """纯函数。原始序列的行 → 派生序列(Puell、算力 30 天变化)在 d ≥ since 的行;算不出的那天不写。"""
    iss = {r["d"]: r["value"] for r in base if r["series"] == "btc_issuance_usd"}
    hr = {r["d"]: r["value"] for r in base if r["series"] == "btc_hashrate"}
    out = []
    for d in sorted(k for k in set(iss) | set(hr) if k >= since):
        p = puell(iss, d) if d in iss else None
        if p is not None and p > 0:
            out.append({"series": "btc_puell", "d": d, "value": p, "source": SOURCE})
        h = hash_30d(hr, d) if d in hr else None
        if h is not None:
            out.append({"series": "btc_hash_30d", "d": d, "value": h, "source": SOURCE})
    return out


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
    # 以**最晚加进来的那条序列**判断要不要全量:派生序列还没有 ⇒ 全史重取重算(upsert 幂等)
    have = await _sb_get(TABLE, {"select": "d", "series": f"eq.{DERIVED[0]}", "order": "d.desc", "limit": "1"})
    if not have.ok:
        return {"ok": False, "why": f"读 {TABLE} 失败:{(have.why or '')[:120]}"}
    full = not have.rows
    start = HISTORY_FROM if full else (now.date() - dt.timedelta(days=RECENT_D)).isoformat()
    fetch_from = HISTORY_FROM if full else (now.date() - dt.timedelta(days=DERIVE_LOOKBACK_D)).isoformat()
    raw = await get_coinmetrics_btc(list(METRICS), fetch_from)
    base = to_rows(raw)
    rows = [r for r in base if r["d"] >= start] + derived_rows(base, start)
    for i in range(0, len(rows), 1000):
        if not await supabase_upsert_table(TABLE, rows[i:i + 1000], on_conflict="series,d"):
            return {"ok": False, "why": f"写 {TABLE} 失败(第 {i} 行起)"}
    last = max((r["d"] for r in rows), default=None)
    await redis_set_key(key, {"rows": len(rows), "last": last}, ttl=2 * 86400)
    return {"ok": True, "rows": len(rows), "from": start, "last": last,
            "why": f"BTC 周期指标 {len(rows)} 行(自 {start},最新 {last})"}
