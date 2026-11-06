"""交易所级储备 / 净流入 / 杠杆(T-258 前三之三)—— DeFiLlama `/cexs` 一次请求覆盖全部交易所,每天一行一所。

`cleanAssetsTvl`(去掉平台币的储备)、`inflows_24h / 1w / 1m`(净流入,DeFiLlama 按储备变动扣价格变动)、`oi`、`leverage = oi ÷ 储备`。
**没有历史**(只有当下快照)⇒ 从 2026-11-06 起前向积累,训练期用不上;进 `feature_matrix_daily` 的是全市场合计。
一轮 = 1 次请求(`source_policy.assert_bulk_source`)。判活:`select d, count(*), sum(clean_assets_usd) from cex_reserves_daily group by 1 order by 1 desc limit 3`。
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Callable, Optional

TABLE = "cex_reserves_daily"
WRITES_TABLES = (TABLE,)
WRITES_COLUMNS = {TABLE: ("d", "exchange", "clean_assets_usd", "total_assets_usd", "inflow_24h_usd", "inflow_1w_usd", "inflow_1m_usd",
                          "oi_usd", "leverage", "spot_volume_usd", "deriv_volume_usd", "fetched_at")}
LOOP_NAME = "_cex_reserves_loop"
API = "https://api.llama.fi/cexs"


def _f(x: Any) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def parse(payload: Any, d: str, fetched_at: str) -> list[dict]:
    """纯函数。/cexs → 行;没有储备的交易所丢掉。"""
    rows = payload.get("cexs") if isinstance(payload, dict) else payload
    out = []
    for r in rows if isinstance(rows, list) else []:
        clean = _f(r.get("cleanAssetsTvl"))
        if not r.get("name") or not clean or clean <= 0:
            continue
        out.append({"d": d, "exchange": str(r["name"])[:80], "clean_assets_usd": clean, "total_assets_usd": _f(r.get("currentTvl")),
                    "inflow_24h_usd": _f(r.get("inflows_24h")), "inflow_1w_usd": _f(r.get("inflows_1w")),
                    "inflow_1m_usd": _f(r.get("inflows_1m")), "oi_usd": _f(r.get("oi")), "leverage": _f(r.get("leverage")),
                    "spot_volume_usd": _f(r.get("spotVolume")), "deriv_volume_usd": _f(r.get("derivVolume")), "fetched_at": fetched_at})
    return out


def _get(url: str) -> Any:
    import json
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "cometcloud-research/1.0", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


async def run_once(now: Optional[dt.datetime] = None, get: Optional[Callable[[str], Any]] = None) -> dict[str, Any]:
    import asyncio

    from src.api.store import supabase_upsert_table
    from src.data.market.source_policy import assert_bulk_source
    assert_bulk_source(1, "defillama", job="exchange reserves / flows / leverage (one /cexs request)")
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    rows = parse(await asyncio.to_thread(get or _get, API), now.date().isoformat(), now.isoformat())
    if not rows:
        return {"ok": False, "refused": True, "why": "/cexs 没有一所有储备"}
    w = await supabase_upsert_table(TABLE, rows, on_conflict="d,exchange")
    if not w:
        return {"ok": False, "why": f"写 {TABLE} 失败:{(getattr(w, 'why', '') or '')[:200]}"}
    tot = sum(r["clean_assets_usd"] for r in rows)
    w1 = sum(r["inflow_1w_usd"] or 0 for r in rows)
    return {"ok": True, "written": len(rows), "why": f"{len(rows)} 所 · 储备 ${tot / 1e9:.0f}B · 一周净流入 ${w1 / 1e9:+.1f}B"}
