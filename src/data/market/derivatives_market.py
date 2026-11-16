"""全市场永续的持仓与基差(CoinGecko Analyst `/derivatives`,一次请求 ≈ 2.7 万个合约 —— Jazz 11-06「先把 Analyst API 用足」)。

我们只在 HL / Binance 上看持仓和资金费;CoinGecko 这一次调用覆盖约 100 个衍生品场所的全部未到期永续。每 6 小时取一次,按标的(`index_id`)汇总:
全场所持仓(美元)、24h 成交、场所数、按持仓加权的**基差**(合约价对指数价的 %,各场所可比)、持仓最大的那个场所的资金费(原单位,不跨场所平均 ——
各场所结算周期不同,硬平均没有意义)。**CG 不给历史 ⇒ 前向积累**。表 `derivatives_market_daily`(d, symbol),当天覆盖。

**11-16 加两列**(迁移 `migrations/2026-11-16_derivatives_market_funding_oiw.sql`):`funding_oiw_sum`(Σ funding_rate×OI)与
`oi_funding_usd`(同一批行的 OI 合计)。这两个相除 = **OI 加权平均资金费**,和 `src/data/cis/positioning.py` 的口径完全一致 ——
positioning 原来每 30 分钟直接打 CoinGecko 的**公开** `/derivatives`,和这张表的写入端是同一个数据、同一个端点,却分了两个额度池
(公开端点每分钟十几次,429 是家常便饭;Analyst 档每分钟 500 次却几乎没被这条路径用上)。现在 positioning 先读这张表,读不到才回落 **Pro** 端点。
存分子分母而不是存算好的比例:读者自己除一次,口径永远不会和 API 路径悄悄分叉。

进 `feature_matrix_daily` 的是全市场合计:持仓 ÷ 总市值(杠杆)、山寨持仓占比。
判活:`select d, count(*), sum(oi_usd) from derivatives_market_daily group by 1 order by 1 desc limit 3`。
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Optional

TABLE = "derivatives_market_daily"
WRITES_TABLES = (TABLE,)
WRITES_COLUMNS = {TABLE: ("d", "symbol", "oi_usd", "volume_24h_usd", "n_markets", "basis_oiw_pct", "top_market", "top_funding_raw",
                           "funding_oiw_sum", "oi_funding_usd", "fetched_at")}
#: 11-16 新增的两列。迁移没跑时写入端会退回旧列集(见 run_once),别把这两列当必备。
FUNDING_COLS = ("funding_oiw_sum", "oi_funding_usd")
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
        a = agg.setdefault(sym, {"oi": 0.0, "vol": 0.0, "n": 0, "bw": 0.0, "bwoi": 0.0, "fw_sum": 0.0, "fw_oi": 0.0,
                                 "top": (0.0, None, None)})
        a["oi"] += oi
        a["vol"] += _f(t.get("volume_24h")) or 0.0
        a["n"] += 1
        b = _f(t.get("basis"))
        if b is not None:
            a["bw"] += b * oi
            a["bwoi"] += oi
        f = _f(t.get("funding_rate"))
        if f is not None:                       # 没有 funding_rate 的行不参与加权(和 positioning 的 API 路径同口径)
            a["fw_sum"] += f * oi
            a["fw_oi"] += oi
        if oi > a["top"][0]:
            a["top"] = (oi, str(t.get("market") or "")[:60], f)
    out = []
    for sym, a in agg.items():
        if a["oi"] < MIN_OI_USD:
            continue
        out.append({"d": d, "symbol": sym[:30], "oi_usd": round(a["oi"], 0), "volume_24h_usd": round(a["vol"], 0), "n_markets": a["n"],
                    "basis_oiw_pct": round(a["bw"] / a["bwoi"], 5) if a["bwoi"] else None, "top_market": a["top"][1],
                    "top_funding_raw": a["top"][2], "funding_oiw_sum": round(a["fw_sum"], 6),
                    "oi_funding_usd": round(a["fw_oi"], 0), "fetched_at": fetched_at})
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
    degraded = False
    for i in range(0, len(rows), 1000):
        chunk = rows[i:i + 1000]
        res = await supabase_upsert_table(TABLE, chunk, on_conflict="d,symbol")
        if res:
            continue
        # 列还不存在(迁移 2026-11-16_derivatives_market_funding_oiw 还没跑 ⇒ PostgREST PGRST204):
        # 退回旧列集重写,别把这一轮 6 小时的数据整轮丢掉;资金费两列等迁移补上后自动回到全列。
        legacy = [{k: v for k, v in r.items() if k not in FUNDING_COLS} for r in chunk]
        if not await supabase_upsert_table(TABLE, legacy, on_conflict="d,symbol"):
            return {"ok": False, "why": f"写 {TABLE} 失败: {str(getattr(res, 'why', ''))[:160]}"}
        degraded = True
    tot = sum(r["oi_usd"] for r in rows)
    btc = next((r["oi_usd"] for r in rows if r["symbol"] == "BTC"), 0.0)
    why = f"{len(rows)} 个标的 · 全场所持仓 ${tot / 1e9:.0f}B(BTC ${btc / 1e9:.0f}B)"
    if degraded:
        why += " · ⚠️ 资金费两列写不进去(迁移未跑),已退回旧列集"
    return {"ok": True, "written": len(rows), "degraded": degraded, "why": why}
