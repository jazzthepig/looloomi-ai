"""小股东待遇(Jazz 11-02:CIS 的核心维度)—— 每天一行:这家发行方把多少钱分给持有人、稀释了多少。

## 为什么

「对公开市场和小股东有没有预留可分配利润,还是自己团队通过关联交易瓜分了利润」——这是 Jazz 给 CIS 定的核心维度。
滞后的那一半(分利给持有人)在 S-661 / S-664 测过(价值捕获比留出段有效,控制规模后所剩无几);但它从来没有被
**按天、按名字、按时点**记成一张表,CIS v2 想用也没得用。这里只做记账,不打分、不判。

## 口径(全部只用 d 当天及以前的数)

- `revenue_30d` / `holders_30d`:`protocol_revenue_daily`(DeFiLlama 快照,2026-10-21 起)里该 coingecko id 下**所有 slug 之和**
  (hyperliquid = 交易所 + L1;arbitrum = 链 + 基金会)。没有条目 ⇒ NULL(BTC 这类没有协议收入,是 NULL 不是 0)。
- `holders_share` = holders_30d / revenue_30d(revenue_30d = 0 ⇒ NULL)。
- `mcap` / `price`:`asset_mcap_daily`(symbol, d);`supply` = mcap / price;`supply_growth_30d` = supply_d / supply_{d−30} − 1(稀释)。
- `revenue_yield_ann` = revenue_30d × 12 / mcap;`holder_yield_ann` = holders_30d × 12 / mcap。
- `rank_holder_yield`:当天 25 名里按 holder_yield_ann 降序(NULL 排最后)。

表 `treatment_daily`(symbol, d)主键;`_treatment_loop` 每小时看、当天写过就跳;lane 可读。
判活:`select d, count(*), sum((holders_share is not null)::int) from treatment_daily group by 1 order by 1 desc limit 3`。
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Optional

TABLE = "treatment_daily"
WRITES_TABLES = (TABLE,)
WRITES_COLUMNS = {"treatment_daily": ("symbol", "d", "coin_id", "revenue_30d", "holders_30d", "holders_share", "mcap", "price", "supply",
                                      "supply_growth_30d", "revenue_yield_ann", "holder_yield_ann", "rank_holder_yield", "n_slugs", "code_ref")}
CODE_REF = "treatment v1 (11-03)"
LOOP_NAME = "_treatment_loop"


def _f(x: Any) -> Optional[float]:
    try:
        v = None if x is None else float(x)
    except (TypeError, ValueError):
        return None
    return v if v is None or v == v else None


def rows_for(d: str, assets: dict[str, dict], revenue: list[dict], mcap_today: dict[str, dict], mcap_30: dict[str, dict]) -> list[dict]:
    """纯函数。assets = {symbol: {coingecko}};revenue = protocol_revenue_daily 当天行;mcap_today / mcap_30 = {symbol: {mcap, price}}。"""
    by_gecko: dict[str, dict] = {}
    for r in revenue:
        g = r.get("gecko_id")
        if not g:
            continue
        a = by_gecko.setdefault(g, {"rev": 0.0, "hold": 0.0, "n": 0})
        a["rev"] += _f(r.get("revenue_30d")) or 0.0
        a["hold"] += _f(r.get("holders_30d")) or 0.0
        a["n"] += 1
    out = []
    for sym, cfg in assets.items():
        g = cfg.get("coingecko")
        rv = by_gecko.get(g)
        m, p = (_f((mcap_today.get(sym) or {}).get("mcap")), _f((mcap_today.get(sym) or {}).get("price")))
        m30, p30 = (_f((mcap_30.get(sym) or {}).get("mcap")), _f((mcap_30.get(sym) or {}).get("price")))
        supply = m / p if m and p else None
        supply30 = m30 / p30 if m30 and p30 else None
        rev = rv["rev"] if rv else None
        hold = rv["hold"] if rv else None
        out.append({"symbol": sym, "d": d, "coin_id": g, "revenue_30d": rev, "holders_30d": hold,
                    "holders_share": (round(hold / rev, 4) if rv and rev else None),
                    "mcap": m, "price": p, "supply": supply,
                    "supply_growth_30d": (round(supply / supply30 - 1.0, 5) if supply and supply30 else None),
                    "revenue_yield_ann": (round(rev * 12 / m, 5) if rev is not None and m else None),
                    "holder_yield_ann": (round(hold * 12 / m, 5) if hold is not None and m else None),
                    "n_slugs": rv["n"] if rv else 0, "code_ref": CODE_REF})
    ranked = sorted(out, key=lambda r: (r["holder_yield_ann"] is None, -(r["holder_yield_ann"] or 0.0)))
    for i, r in enumerate(ranked, 1):
        r["rank_holder_yield"] = i if r["holder_yield_ann"] is not None else None
    return out


async def run_once(now: Optional[dt.datetime] = None) -> dict[str, Any]:
    from src.api.store import supabase_upsert_table
    from src.data.cis.cis_provider import CRYPTO_ASSETS
    from src.data.style.header import _read_all
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    d = (now.date() - dt.timedelta(days=1)).isoformat()
    have = await _read_all(TABLE, {"select": "symbol", "d": f"eq.{d}", "limit": "1"})
    if have:
        return {"ok": True, "status": "skipped", "why": f"{d} 已写"}
    revenue = await _read_all("protocol_revenue_daily", {"select": "gecko_id,revenue_30d,holders_30d", "d": f"eq.{d}", "gecko_id": "not.is.null"})
    if not revenue:
        return {"ok": True, "status": "skipped", "why": f"{d} 的 protocol_revenue_daily 还没到"}
    syms = ",".join(CRYPTO_ASSETS)
    today = {r["symbol"]: r for r in await _read_all("asset_mcap_daily", {"select": "symbol,mcap,price", "d": f"eq.{d}", "symbol": f"in.({syms})"})}
    d30 = (dt.date.fromisoformat(d) - dt.timedelta(days=30)).isoformat()
    ago = {r["symbol"]: r for r in await _read_all("asset_mcap_daily", {"select": "symbol,mcap,price", "d": f"eq.{d30}", "symbol": f"in.({syms})"})}
    rows = rows_for(d, CRYPTO_ASSETS, revenue, today, ago)
    w = await supabase_upsert_table(TABLE, rows, on_conflict="symbol,d")
    if not w:
        return {"ok": False, "why": f"写 {TABLE} 失败:{(getattr(w, 'why', '') or '')[:200]}"}
    covered = sum(1 for r in rows if r["holders_share"] is not None)
    return {"ok": True, "d": d, "written": len(rows), "with_share": covered,
            "why": f"{d} 写 {len(rows)} 名,{covered} 名有分配率"}
