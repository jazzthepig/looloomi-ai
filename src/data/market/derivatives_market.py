"""全市场永续的持仓与基差(CoinGecko Analyst `/derivatives`,一次请求 ≈ 2.7 万个合约 —— Jazz 11-06「先把 Analyst API 用足」)。

我们只在 HL / Binance 上看持仓和资金费;CoinGecko 这一次调用覆盖约 100 个衍生品场所的全部未到期永续。每 6 小时取一次,按标的(`index_id`)汇总:
全场所持仓(美元)、24h 成交、场所数、按持仓加权的**基差**(合约价对指数价的 %,各场所可比)、持仓最大的那个场所的资金费(原单位,不跨场所平均 ——
各场所结算周期不同,硬平均没有意义)。**CG 不给历史 ⇒ 前向积累**。表 `derivatives_market_daily`(d, symbol),当天覆盖。
进 `feature_matrix_daily` 的是全市场合计:持仓 ÷ 总市值(杠杆)、山寨持仓占比。
判活:`select d, count(*), sum(oi_usd) from derivatives_market_daily group by 1 order by 1 desc limit 3`。
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Optional

TABLE = "derivatives_market_daily"
WRITES_TABLES = (TABLE,)
WRITES_COLUMNS = {TABLE: ("d", "symbol", "oi_usd", "volume_24h_usd", "n_markets", "basis_oiw_pct", "top_market", "top_funding_raw", "fetched_at")}
LOOP_NAME = "_derivatives_market_loop"
MIN_OI_USD = 1e6


def _f(x: Any) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def aggregate(tickers: list[dict], d: str, fetched_at: str) -> list[dict]:
    """纯函数。/derivatives 的合约行 → 每个标的一行(只收永续、持仓 ≥ 100 万美元的标的)。"""
    agg: dict[str, dict] = {}
    for t in tickers if isinstance(tickers, list) else []:
        if (t.get("contract_type") or "perpetual") != "perpetual":
            continue
        sym = str(t.get("index_id") or "").upper().strip()
        oi = _f(t.get("open_interest"))
        if not sym or not oi or oi <= 0:
            continue
        a = agg.setdefault(sym, {"oi": 0.0, "vol": 0.0, "n": 0, "bw": 0.0, "bwoi": 0.0, "top": (0.0, None, None)})
        a["oi"] += oi
        a["vol"] += _f(t.get("volume_24h")) or 0.0
        a["n"] += 1
        b = _f(t.get("basis"))
        if b is not None:
            a["bw"] += b * oi
            a["bwoi"] += oi
        if oi > a["top"][0]:
            a["top"] = (oi, str(t.get("market") or "")[:60], _f(t.get("funding_rate")))
    out = []
    for sym, a in agg.items():
        if a["oi"] < MIN_OI_USD:
            continue
        out.append({"d": d, "symbol": sym[:30], "oi_usd": round(a["oi"], 0), "volume_24h_usd": round(a["vol"], 0), "n_markets": a["n"],
                    "basis_oiw_pct": round(a["bw"] / a["bwoi"], 5) if a["bwoi"] else None, "top_market": a["top"][1],
                    "top_funding_raw": a["top"][2], "fetched_at": fetched_at})
    return out


async def run_once(now: Optional[dt.datetime] = None, fetch=None) -> dict[str, Any]:
    from src.api.store import supabase_upsert_table
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    if fetch is None:
        from src.data.market.data_layer import CG_PRO_BASE, _cg_headers, _get_cg_client
        async def fetch():
            r = await _get_cg_client().get(f"{CG_PRO_BASE}/derivatives", headers=_cg_headers(), params={"include_tickers": "unexpired"},
                                           timeout=60)
            r.raise_for_status()
            return r.json()
    rows = aggregate(await fetch(), now.date().isoformat(), now.isoformat())
    if not rows:
        return {"ok": False, "refused": True, "why": "/derivatives 没有一个标的过持仓门槛"}
    for i in range(0, len(rows), 1000):
        if not await supabase_upsert_table(TABLE, rows[i:i + 1000], on_conflict="d,symbol"):
            return {"ok": False, "why": f"写 {TABLE} 失败"}
    tot = sum(r["oi_usd"] for r in rows)
    btc = next((r["oi_usd"] for r in rows if r["symbol"] == "BTC"), 0.0)
    return {"ok": True, "written": len(rows), "why": f"{len(rows)} 个标的 · 全场所持仓 ${tot / 1e9:.0f}B(BTC ${btc / 1e9:.0f}B)"}
