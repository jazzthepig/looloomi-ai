"""预测市场的先验(backlog「Polymarket / Kalshi priors」,11-06)—— Polymarket 公开 Gamma API,按标签取 24h 成交最大的事件,
每个市场记「Yes」的价格(= 市场给的概率),进 `prediction_markets`(每天一行,当天内按小时覆盖成最新)。

## 为什么

情景台账(S-709 / S-725)里我们和 agent 臂写概率;市场也在写 —— 「BTC 11 月底在 X 之上」「12 月 FOMC 降息」。
把市场的概率并排记下,才能问:我们的 Brier 比市场好还是差。**只记,不进敞口;不作为我们的观点对外。**

## 范围

- 一轮 = `len(TAGS)` 次 `/events` 请求(批量端点:一次返回一页事件及其全部市场),不是逐个市场调;`source_policy.assert_bulk_source`
  按请求数判。每个标签取 24h 成交前 `EVENTS_PER_TAG` 个事件。
- 价格是 Polymarket 的 `outcomePrices[0]`(二元市场的 Yes);多选事件(negRisk)每个选项一行,`item` = 选项名。
- Kalshi 下一步(同表,venue = 'kalshi')。

判活:`select d, tag, count(*) from prediction_markets group by 1, 2 order by 1 desc limit 6`。
"""
from __future__ import annotations

import datetime as dt
import json
from typing import Any, Callable, Optional

TABLE = "prediction_markets"
WRITES_TABLES = (TABLE,)
WRITES_COLUMNS = {TABLE: ("d", "venue", "market_id", "tag", "event_slug", "event_title", "question", "item", "p_yes",
                          "volume_24h", "liquidity", "end_date", "fetched_at")}
LOOP_NAME = "_prediction_markets_loop"
VENUE = "polymarket"
BASE = "https://gamma-api.polymarket.com"
TAGS = ("crypto", "fed-rates", "economy")
EVENTS_PER_TAG = 15


def _f(x: Any) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def parse_events(events: Any, tag: str, d: str, fetched_at: str) -> list[dict]:
    """纯函数。Gamma `/events` 的一页 → 行。没有价格 / 已关闭的市场丢掉;概率夹在 [0, 1] 之外的丢掉(不修)。"""
    out = []
    for e in events if isinstance(events, list) else []:
        for m in e.get("markets") or []:
            if m.get("closed") or not m.get("active", True):
                continue
            try:
                prices = json.loads(m.get("outcomePrices") or "[]")
            except (TypeError, ValueError):
                continue
            p = _f(prices[0]) if prices else None
            if p is None or not 0.0 <= p <= 1.0 or not m.get("id"):
                continue
            out.append({"d": d, "venue": VENUE, "market_id": str(m["id"]), "tag": tag, "event_slug": e.get("slug"),
                        "event_title": (e.get("title") or "")[:300], "question": (m.get("question") or "")[:400],
                        "item": (m.get("groupItemTitle") or None), "p_yes": round(p, 6),
                        "volume_24h": _f(m.get("volume24hr")), "liquidity": _f(m.get("liquidityNum")),
                        "end_date": (m.get("endDate") or None), "fetched_at": fetched_at})
    return out


def _get(url: str) -> Any:
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "cometcloud-research/1.0", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


async def run_once(now: Optional[dt.datetime] = None, get: Optional[Callable[[str], Any]] = None) -> dict[str, Any]:
    import asyncio

    from src.api.store import supabase_upsert_table
    from src.data.market.source_policy import assert_bulk_source
    assert_bulk_source(len(TAGS), VENUE, job="prediction-market priors (one /events page per tag)")
    get = get or _get
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    d, fetched = now.date().isoformat(), now.isoformat()
    rows, failed = [], {}
    for tag in TAGS:
        url = f"{BASE}/events?limit={EVENTS_PER_TAG}&active=true&closed=false&order=volume24hr&ascending=false&tag_slug={tag}"
        try:
            rows += parse_events(await asyncio.to_thread(get, url), tag, d, fetched)
        except Exception as e:                                             # noqa: BLE001 —— 一个标签不通不挡其余
            failed[tag] = f"{type(e).__name__}: {str(e)[:120]}"
    seen, uniq = set(), []
    for r in rows:                                    # 同一个市场可能挂在两个标签下 —— 只留第一个
        if r["market_id"] not in seen:
            seen.add(r["market_id"])
            uniq.append(r)
    if not uniq:
        return {"ok": False, "refused": True, "why": f"一行都没取到:{failed or '空页'}"}
    w = await supabase_upsert_table(TABLE, uniq, on_conflict="d,venue,market_id")
    if not w:
        return {"ok": False, "why": f"写 {TABLE} 失败:{(getattr(w, 'why', '') or '')[:200]}"}
    return {"ok": not failed, "written": len(uniq), "failed": failed or None,
            "why": f"{d}:{len(uniq)} 个市场" + (f" · 不通:{', '.join(failed)}" if failed else "")}
