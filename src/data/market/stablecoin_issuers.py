"""稳定币**按发行方**的流通量(铸造 / 赎回)—— 原因层「被迫交易的人」的一块(Jazz 11-06 排序第 1 步)。

S-508 已证明**总量**会翻号、不能当边际流动性;拆开看:USDT(离岸 / 交易所)、USDC(美国机构)、USDe(期现基差交易的
需求 —— 资金费为正时铸造)、DAI + USDS(链上借贷)。DeFiLlama `stablecoincharts/all?stablecoin=<id>` 每个发行方一次请求,
返回 2017 起的日序列;一轮 5 次请求(`source_policy.assert_bulk_source` 按请求数判)。
表 `stablecoin_issuer_daily`(d, coin)。第一轮整段回填,之后每轮只写最近 `RECENT_DAYS` 天。
判活:`select coin, max(d), count(*) from stablecoin_issuer_daily group by 1`。
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Callable, Optional

TABLE = "stablecoin_issuer_daily"
WRITES_TABLES = (TABLE,)
WRITES_COLUMNS = {TABLE: ("d", "coin", "circulating_usd", "source")}
LOOP_NAME = "_stablecoin_issuers_loop"
API = "https://stablecoins.llama.fi/stablecoincharts/all?stablecoin={id}"
ISSUERS = {"USDT": 1, "USDC": 2, "USDe": 146, "DAI": 5, "USDS": 209}
RECENT_DAYS = 10


def parse(payload: Any, coin: str) -> list[dict]:
    """纯函数。[{date: 秒, totalCirculatingUSD: {peggedUSD: x}}, …] → 行;缺值 / 非正丢掉。"""
    out = []
    for r in payload if isinstance(payload, list) else []:
        try:
            d = dt.datetime.fromtimestamp(int(r["date"]), dt.timezone.utc).date().isoformat()
            v = float((r.get("totalCirculatingUSD") or {}).get("peggedUSD"))
        except (KeyError, TypeError, ValueError):
            continue
        if v > 0:
            out.append({"d": d, "coin": coin, "circulating_usd": round(v, 0), "source": "defillama_stablecoins"})
    return out


def _get(url: str) -> Any:
    import json
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "cometcloud-research/1.0", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


async def run_once(now: Optional[dt.datetime] = None, get: Optional[Callable[[str], Any]] = None, full: Optional[bool] = None) -> dict[str, Any]:
    import asyncio

    from src.api.store import supabase_upsert_table
    from src.data.market.source_policy import assert_bulk_source
    from src.data.style.header import _read_all
    assert_bulk_source(len(ISSUERS), "defillama", job="stablecoin supply by issuer (one chart request per issuer)")
    get = get or _get
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    if full is None:
        have = await _read_all(TABLE, {"select": "coin", "limit": "1"})
        full = not have
    cutoff = (now.date() - dt.timedelta(days=RECENT_DAYS)).isoformat()
    written, failed = 0, {}
    for coin, sid in ISSUERS.items():
        try:
            rows = parse(await asyncio.to_thread(get, API.format(id=sid)), coin)
        except Exception as e:                                             # noqa: BLE001
            failed[coin] = f"{type(e).__name__}: {str(e)[:120]}"
            continue
        if not full:
            rows = [r for r in rows if r["d"] >= cutoff]
        for i in range(0, len(rows), 1000):
            w = await supabase_upsert_table(TABLE, rows[i:i + 1000], on_conflict="d,coin")
            if not w:
                return {"ok": False, "why": f"写 {TABLE} 失败:{(getattr(w, 'why', '') or '')[:200]}", "written": written}
        written += len(rows)
    return {"ok": not failed, "written": written, "full": full, "failed": failed or None,
            "why": f"{'回填' if full else '续写'} {written} 行" + (f" · 不通:{', '.join(failed)}" if failed else "")}
