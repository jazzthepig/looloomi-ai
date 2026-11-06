"""CoinGecko 全部分类的市值 / 成交量,每天落一份(`/coins/categories`,一次请求 ≈ 600 个分类)。

`test_paid_capability_is_known` 把这个端点记成 **ephemeral**:`data_layer` 一直在调,但只取十几家 VC 组合、10 分钟就扔 ——
「叙事层没有历史」不是拿不到,是**拿了就扔**。时点风格指数(`style_index_pit_daily`)只有 4 个板块;这里是 CoinGecko 自己的
~600 个分类(AI agents、DePIN、各链 meme ……),前向攒出叙事轮动的细粒度历史。CG 不给分类的历史 ⇒ 前向。
随 `_cg_supply_loop` 每 12 小时一轮,当天覆盖。判活:`select d, count(*) from cg_category_daily group by 1 order by 1 desc limit 3`。
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Optional

TABLE = "cg_category_daily"
WRITES_TABLES = (TABLE,)
WRITES_COLUMNS = {TABLE: ("d", "category_id", "name", "market_cap", "volume_24h", "mcap_change_24h_pct", "top3", "fetched_at")}
MIN_MCAP = 1e6


def _f(x: Any) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def rows_from(payload: Any, d: str, fetched_at: str) -> list[dict]:
    """纯函数。/coins/categories → 每个分类一行;市值缺或 < 100 万美元的不收(噪声分类)。"""
    out = []
    for c in payload if isinstance(payload, list) else []:
        mc = _f(c.get("market_cap"))
        if not c.get("id") or not mc or mc < MIN_MCAP:
            continue
        out.append({"d": d, "category_id": str(c["id"])[:120], "name": str(c.get("name") or "")[:160], "market_cap": mc,
                    "volume_24h": _f(c.get("volume_24h")), "mcap_change_24h_pct": _f(c.get("market_cap_change_24h")),
                    "top3": [str(x) for x in (c.get("top_3_coins_id") or [])][:3], "fetched_at": fetched_at})
    return out


async def run_once(now: Optional[dt.datetime] = None, fetch=None, upsert=None) -> dict[str, Any]:
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    if fetch is None:
        from src.data.market.data_layer import CG_API_KEY, CG_PRO_BASE, _cg_headers, _get_cg_client
        if not CG_API_KEY:
            return {"ok": False, "refused": True, "why": "COINGECKO_API_KEY 没配"}

        async def fetch():
            r = await _get_cg_client().get(f"{CG_PRO_BASE}/coins/categories", headers=_cg_headers(), timeout=60)
            r.raise_for_status()
            return r.json()
    if upsert is None:
        from src.api.store import supabase_upsert_table as upsert
    rows = rows_from(await fetch(), now.date().isoformat(), now.isoformat())
    if not rows:
        return {"ok": False, "refused": True, "why": "/coins/categories 没有一个分类过市值门槛"}
    if not await upsert(TABLE, rows, on_conflict="d,category_id"):
        return {"ok": False, "why": f"写 {TABLE} 失败"}
    return {"ok": True, "written": len(rows), "why": f"{len(rows)} 个分类"}
