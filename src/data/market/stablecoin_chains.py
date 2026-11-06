"""稳定币**按链**的流通量 —— 「干火药放在哪」(T-258 ② 的免费口径,DeFiLlama)。

发行方(`stablecoin_issuers.py`)回答「谁印的」;链回答「印出来放在哪」:Tron ≈ 亚洲 / 新兴市场散户的 USDT 通道,
Ethereum ≈ 机构与 DeFi 抵押,Solana / Base / Arbitrum ≈ 链上投机,BSC ≈ 交易所周边。
**取法(守 Jazz 的免费源规则):** 每轮 1 次 `stablecoinchains`(全部链的当前值,一次请求)写当天;历史只在表为空时
按 `CHAINS` 每链一次 `stablecoincharts/{chain}` 回填一次(6 次,≤ BULK_THRESHOLD)。
表 `stablecoin_chain_daily`(d, chain)。判活:`select chain, max(d), count(*) from stablecoin_chain_daily group by 1`。
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Callable, Optional

TABLE = "stablecoin_chain_daily"
WRITES_TABLES = (TABLE,)
WRITES_COLUMNS = {TABLE: ("d", "chain", "circulating_usd", "source")}
LOOP_NAME = "_stablecoin_chains_loop"
SNAPSHOT_API = "https://stablecoins.llama.fi/stablecoinchains"
CHART_API = "https://stablecoins.llama.fi/stablecoincharts/{chain}"
CHAINS = ("Ethereum", "Tron", "Solana", "BSC", "Arbitrum", "Base")


def chart_rows(payload: Any, chain: str) -> list[dict]:
    """纯函数。[{date: 秒, totalCirculatingUSD: {peggedUSD: x}}] → 行(只取美元锚定)。"""
    out = []
    for r in payload if isinstance(payload, list) else []:
        try:
            d = dt.datetime.fromtimestamp(int(r["date"]), dt.timezone.utc).date().isoformat()
            v = float((r.get("totalCirculatingUSD") or {}).get("peggedUSD"))
        except (KeyError, TypeError, ValueError):
            continue
        if v > 0:
            out.append({"d": d, "chain": chain, "circulating_usd": round(v, 0), "source": "defillama_stablecoincharts"})
    return out


def snapshot_rows(payload: Any, d: str) -> list[dict]:
    """纯函数。stablecoinchains(全部链的当前值)→ 只留 CHAINS 里的链。"""
    want = {c.lower(): c for c in CHAINS}
    out = []
    for r in payload if isinstance(payload, list) else []:
        name = str(r.get("name") or "")
        try:
            v = float((r.get("totalCirculatingUSD") or {}).get("peggedUSD"))
        except (TypeError, ValueError):
            continue
        if name.lower() in want and v > 0:
            out.append({"d": d, "chain": want[name.lower()], "circulating_usd": round(v, 0), "source": "defillama_stablecoinchains"})
    return out


def _get(url: str) -> Any:
    import json
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "cometcloud-research/1.0", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


async def run_once(now: Optional[dt.datetime] = None, get: Optional[Callable[[str], Any]] = None, read=None, upsert=None) -> dict[str, Any]:
    import asyncio

    from src.data.market.source_policy import assert_bulk_source
    if read is None:
        from src.data.style.header import _read_all as read
    if upsert is None:
        from src.api.store import supabase_upsert_table as upsert
    get = get or _get
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    have = await read(TABLE, {"select": "chain", "limit": "1"})
    rows: list[dict] = []
    failed: dict[str, str] = {}
    if not have:
        assert_bulk_source(len(CHAINS), "defillama", job="stablecoin supply by chain — one-time history backfill (one chart per chain)")
        for c in CHAINS:
            try:
                rows += chart_rows(await asyncio.to_thread(get, CHART_API.format(chain=c)), c)
            except Exception as e:                                         # noqa: BLE001
                failed[c] = f"{type(e).__name__}: {str(e)[:120]}"
    try:
        snap = snapshot_rows(await asyncio.to_thread(get, SNAPSHOT_API), now.date().isoformat())
        rows += snap
    except Exception as e:                                                 # noqa: BLE001
        snap, failed["snapshot"] = [], f"{type(e).__name__}: {str(e)[:120]}"
    rows = list({(r["d"], r["chain"]): r for r in rows}.values())          # 当天:快照覆盖图表的同日点
    for i in range(0, len(rows), 1000):
        if not await upsert(TABLE, rows[i:i + 1000], on_conflict="d,chain"):
            return {"ok": False, "why": f"写 {TABLE} 失败", "written": i}
    return {"ok": bool(rows) and "snapshot" not in failed, "written": len(rows), "backfill": not have, "failed": failed or None,
            "why": f"{'回填 + ' if not have else ''}快照 {len(snap)} 条链 · 写 {len(rows)} 行" + (f" · 不通:{', '.join(failed)}" if failed else "")}
