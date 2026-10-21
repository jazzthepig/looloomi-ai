"""协议收入与持币人收入(DeFiLlama)—— S-661 在留出段证实的「价值捕获比」的前向数据(台账 S-661)。

## 为什么

S-661(10-21):持币人拿到的那一份(回购 / 分红 / 燃烧)占协议收入的比例,能在之后一个月挑出相对更好的币 ——
发现段 2021–23 与留出段 2024–26 同号,留出段 IC +0.086、t 3.45、三分位差每月 +10.7%。窗口 30 / 60 / 90 天
几乎一样(30 天 IC 0.086、60 天 0.087、90 天 0.086),所以前向直接用 DeFiLlama 概览接口自带的 30 天与「前 30 天」两段。

## 怎么取(不扇出)

`/overview/fees?dataType=dailyRevenue` 与 `dataType=dailyHoldersRevenue` —— **两次请求覆盖全部协议**
(source_policy:免费源只许走批量接口)。子协议按 `parentProtocol` 并到母协议(Uniswap = v2 + v3 + v4 …),
`gecko_id` 来自 `defillama_gecko.json`(母协议 slug → CoinGecko id,由 S-661 的研究缓存生成;新协议没有映射就只存不接)。
每天一行 / 母协议,`d` = 写入时的前一个 UTC 日(概览的 24h / 30d 是截至最近一个完整日的)。

判活:`select max(d), count(*) from protocol_revenue_daily where d = max(d)` —— 每天约 2,000 个母协议;
`loop_attempt` 里 `_protocol_revenue_loop` 每天一条。少于 500 个母协议 ⇒ 不写、记 refused(接口半挂时不覆盖)。
"""
from __future__ import annotations

import datetime as dt
import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Optional

log = logging.getLogger(__name__)

TABLE = "protocol_revenue_daily"
WRITES_TABLES = (TABLE,)
OVERVIEW = "https://api.llama.fi/overview/fees?excludeTotalDataChart=true&excludeTotalDataChartBreakdown=true&dataType={}"
MIN_PROTOCOLS = 500
GECKO_MAP = Path(__file__).with_name("defillama_gecko.json")


def parent_slug(p: dict) -> Optional[str]:
    par = p.get("parentProtocol")
    return par.split("#", 1)[1] if par and "#" in par else p.get("slug")


def _f(x: Any) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 0.0
    return v if v == v else 0.0


def aggregate(revenue: Iterable[dict], holders: Iterable[dict], gecko: dict[str, str], d: str) -> list[dict]:
    """纯函数。两份概览 → 每个母协议一行(子协议相加)。"""
    agg: dict[str, dict] = defaultdict(lambda: {"revenue_24h": 0.0, "revenue_30d": 0.0, "revenue_60to30d": 0.0,
                                                "holders_24h": 0.0, "holders_30d": 0.0, "holders_60to30d": 0.0,
                                                "name": None, "category": None})
    for src, pre in ((revenue, "revenue"), (holders, "holders")):
        for p in src:
            s = parent_slug(p)
            if not s:
                continue
            a = agg[s]
            a[f"{pre}_24h"] += _f(p.get("total24h"))
            a[f"{pre}_30d"] += _f(p.get("total30d"))
            a[f"{pre}_60to30d"] += _f(p.get("total60dto30d"))
            a["name"] = a["name"] or (p.get("name") if not p.get("parentProtocol") else s)
            a["category"] = a["category"] or p.get("category")
    return [{"slug": s, "d": d, "gecko_id": gecko.get(s), **{k: (round(v, 2) if isinstance(v, float) else v)
                                                           for k, v in a.items()}}
            for s, a in sorted(agg.items())]


def value_capture(rows: Iterable[dict]) -> dict[str, dict]:
    """纯函数。同一天的行 → {gecko_id: 价值捕获比(持币人收入 ÷ 收入,60 天)、持币人收入 30 天、收入 30 天}。
    同一个 gecko_id 的几个母协议相加;收入为 0 ⇒ 不给比值(None,不是 0)。"""
    by: dict[str, dict] = defaultdict(lambda: {"h": 0.0, "r": 0.0, "h30": 0.0, "r30": 0.0})
    for r in rows:
        g = r.get("gecko_id")
        if not g:
            continue
        b = by[g]
        b["h"] += _f(r.get("holders_30d")) + _f(r.get("holders_60to30d"))
        b["r"] += _f(r.get("revenue_30d")) + _f(r.get("revenue_60to30d"))
        b["h30"] += _f(r.get("holders_30d"))
        b["r30"] += _f(r.get("revenue_30d"))
    return {g: {"value_capture": (b["h"] / b["r"]) if b["r"] > 0 else None, "holders_rev_30d": b["h30"],
                "revenue_30d": b["r30"]} for g, b in by.items()}


async def run_once(now: Optional[dt.datetime] = None) -> dict[str, Any]:
    import httpx

    from src.api.store import supabase_upsert_table
    now = now or dt.datetime.now(dt.timezone.utc)
    d = (now.astimezone(dt.timezone.utc).date() - dt.timedelta(days=1)).isoformat()
    try:
        async with httpx.AsyncClient(timeout=60.0, headers={"User-Agent": "cometcloud"}) as c:
            rv = (await c.get(OVERVIEW.format("dailyRevenue"))).json().get("protocols") or []
            hv = (await c.get(OVERVIEW.format("dailyHoldersRevenue"))).json().get("protocols") or []
    except Exception as e:                                       # noqa: BLE001
        return {"status": "error", "reason": f"DeFiLlama 读不到:{type(e).__name__}: {str(e)[:200]}"}
    gecko = json.loads(GECKO_MAP.read_text(encoding="utf-8")) if GECKO_MAP.exists() else {}
    rows = aggregate(rv, hv, gecko, d)
    if len(rows) < MIN_PROTOCOLS:
        return {"status": "refused", "reason": f"只拿到 {len(rows)} 个母协议(< {MIN_PROTOCOLS})—— 接口半挂,不写",
                "detail": {"d": d, "revenue_protocols": len(rv), "holders_protocols": len(hv)}}
    written = 0
    for k in range(0, len(rows), 1000):
        w = await supabase_upsert_table(TABLE, rows[k:k + 1000], on_conflict="slug,d")
        if not w:
            return {"status": "error", "reason": f"{TABLE} 写不进去:{getattr(w, 'why', '')}", "detail": {"written": written}}
        written += len(rows[k:k + 1000])
    vc = value_capture(rows)
    return {"status": "ok", "reason": f"{d}:{written} 个母协议,{sum(1 for r in rows if r['gecko_id'])} 个接上 gecko_id",
            "detail": {"d": d, "written": written, "with_gecko": sum(1 for r in rows if r["gecko_id"]),
                       "with_value_capture": sum(1 for v in vc.values() if v["value_capture"] is not None)}}


async def latest_value_capture() -> dict[str, dict]:
    """最近一天的价值捕获比,按 gecko_id。读不到就抛(S-180);还没有任何一天 ⇒ {}。"""
    from src.data.style.header import _read_all
    from src.data.vector.market_state_writer import _sb_get
    last = await _sb_get(TABLE, {"select": "d", "order": "d.desc", "limit": "1"})
    if not last.ok:
        raise RuntimeError(f"{TABLE} 读不到:{last.reason}")
    if not last.rows:
        return {}
    rows = await _read_all(TABLE, {"select": "slug,d,gecko_id,revenue_30d,revenue_60to30d,holders_30d,holders_60to30d",
                                   "d": f"eq.{last.rows[0]['d']}", "gecko_id": "not.is.null", "order": "slug.asc"})
    return value_capture(rows)
