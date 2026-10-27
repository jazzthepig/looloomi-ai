"""开票日的规模中性 OI/市值分位 —— S-690 的前向记录(R-v2「去掉高杠杆三分之一」纸面臂)。

## 为什么

S-690(10-27,✅):R-v2 的历史票里,开票当天 OI/市值(控制规模)排在前三分之一的 302 张平均 +0.02R,
其余 354 张 +0.81R;每一年都是这样,大鱼也没有偏在高杠杆那边。按预注册,先上纸面前向,真钱规则 Jazz 定。

## 一个内核

每个信号日:截面 = Binance U 本位当日 OI(`deriv_metrics_daily.oi_value_close`)> 0、CG 市值 ≥ 2,000 万美元、
且过了映射校验的全部名字;r = OI 值 / 市值;当天 rank(r) 对 rank(ln 市值) 做最小二乘,取残差,
p = 残差的 percent_rank(与研究 SQL 的 `percent_rank()` 同一定义)。H = p ≥ 2/3。
研究版是 `docs/research/s690_rv2_oi_filter.sql`;两者在 2024-11-11 的截面上逐名一致(见 tests)。

映射校验:研究版用 2023-01 起的全部重叠日;前向版用信号日前 `CHECK_DAYS` 天(同一把尺子:中位相对误差 ≤ 5%、≥ 30 天)。

## 表

`r_ticket_oi_tags`:每张 R-v2 纸面票一行 —— p、截面名字数、H、缺失原因。OI 归档要隔天才有,当天打不上的票
记 why_missing,下一轮再试(`RETRY_DAYS` 内)。判活同 `ticket_tags`:
`select count(*) from r_tickets_paper p left join r_ticket_oi_tags t using (ticket_id) where t.ticket_id is null`。
"""
from __future__ import annotations

import datetime as dt
import math
from typing import Any, Iterable, Optional

TABLE = "r_ticket_oi_tags"
WRITES_TABLES = (TABLE,)
RULE = "S-690"
H_CUT = 2 / 3
MIN_MCAP = 20_000_000
CHECK_DAYS = 120
RETRY_DAYS = 5


def avg_ranks(values: list[float]) -> list[float]:
    """纯函数。平均名次(1 起),并列取平均 —— 与 SQL 的 rank() + (count − 1)/2 相同。"""
    order = sorted(range(len(values)), key=lambda i: values[i])
    out = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            out[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return out


def size_neutral_pct(rows: Iterable[dict]) -> dict[str, float]:
    """纯函数。[{sym, oi, mcap}] → {sym: p}。p = rank(r) 对 rank(ln 市值) 的 OLS 残差的 percent_rank。"""
    xs = [r for r in rows if r.get("oi") and r.get("mcap") and float(r["oi"]) > 0 and float(r["mcap"]) >= MIN_MCAP]
    n = len(xs)
    if n < 3:
        return {}
    rr = avg_ranks([float(r["oi"]) / float(r["mcap"]) for r in xs])
    rs = avg_ranks([math.log(float(r["mcap"])) for r in xs])
    ms, mr = sum(rs) / n, sum(rr) / n
    sxx = sum((s - ms) ** 2 for s in rs)
    b = sum((s - ms) * (r - mr) for s, r in zip(rs, rr)) / sxx if sxx else 0.0
    a = mr - b * ms
    e = [r - (a + b * s) for r, s in zip(rr, rs)]
    # percent_rank = (rank − 1) / (n − 1),rank 为最小名次(并列同名次)
    order = sorted(range(n), key=lambda i: e[i])
    rank_min = [0] * n
    for pos, i in enumerate(order):
        rank_min[i] = pos + 1 if pos == 0 or e[order[pos - 1]] != e[i] else rank_min[order[pos - 1]]
    return {xs[i]["sym"]: (rank_min[i] - 1) / (n - 1) for i in range(n)}


def mapping_ok(points: dict[str, float], implied: dict[str, float], mult: int = 1) -> bool:
    """纯函数。{d: CG 价} 对 {d: 隐含价} —— 重叠 ≥ 30 天、中位相对误差 ≤ 5%(同 perp_mcap_backfill)。"""
    from src.data.market.perp_mcap_backfill import accept, price_check
    return accept(*price_check([{"d": d, "price": p} for d, p in points.items()], implied, mult))


def tag_row(ticket: dict, pmap: dict[str, float], n_cs: int, why: Optional[str] = None) -> dict[str, Any]:
    """纯函数。一张票 → 一行标签。"""
    p = pmap.get(str(ticket["symbol"]).upper())
    return {"ticket_id": ticket["ticket_id"], "symbol": ticket["symbol"], "signal_d": str(ticket["signal_d"])[:10],
            "p": round(p, 5) if p is not None else None, "n_cs": n_cs or None,
            "high": (p >= H_CUT) if p is not None else None,
            "why_missing": None if p is not None else (why or "名字不在当天截面(无 OI / 市值 < 2,000 万 / 映射校验不过)"),
            "rule": RULE}


async def cross_section(d: dt.date) -> tuple[dict[str, float], int]:
    """d 当天的 {symbol: p} 与截面名字数。只读本库(Binance Vision 归档 + CoinGecko 日线),不打任何交易所。"""
    from src.data.style.header import _read_all
    lo = (d - dt.timedelta(days=CHECK_DAYS)).isoformat()
    oi = await _read_all("deriv_metrics_daily", {"select": "symbol,d,oi_value_close,oi_close", "d": f"gte.{lo}",
                                                 "order": "symbol.asc,d.asc"})
    oi = [r for r in oi if str(r["d"])[:10] <= d.isoformat()]
    if not any(str(r["d"])[:10] == d.isoformat() for r in oi):
        return {}, 0
    syms = sorted({r["symbol"] for r in oi})
    am = await _read_all("asset_mcap_daily", {"select": "symbol,d,price,mcap", "source": "eq.coingecko_pro_market_chart",
                                              "symbol": f"in.({','.join(syms)})", "d": f"gte.{lo}",
                                              "order": "symbol.asc,d.asc"})
    px: dict[str, dict[str, tuple[float, float, int]]] = {}
    for r in am:
        s = str(r.get("symbol") or "").upper()
        if s in syms and str(r["d"])[:10] <= d.isoformat() and r.get("price"):
            px.setdefault(s, {})[str(r["d"])[:10]] = (float(r["price"]), float(r.get("mcap") or 0), 1)
    cgmap = await _read_all("perp_cg_map", {"select": "symbol,coin_id,mult", "verdict": "eq.resolved"})
    extra = {m["symbol"]: m for m in cgmap if m["symbol"] not in px}
    if extra:
        cg = await _read_all("cg_coin_mcap_daily", {"select": "coin_id,d,price,mcap",
                                                    "coin_id": f"in.({','.join(sorted({m['coin_id'] for m in extra.values()}))})",
                                                    "d": f"gte.{lo}", "order": "coin_id.asc,d.asc"})
        by_coin: dict[str, list[dict]] = {}
        for r in cg:
            by_coin.setdefault(r["coin_id"], []).append(r)
        for s, m in extra.items():
            for r in by_coin.get(m["coin_id"], []):
                if str(r["d"])[:10] <= d.isoformat() and r.get("price"):
                    px.setdefault(s, {})[str(r["d"])[:10]] = (float(r["price"]), float(r.get("mcap") or 0), int(m.get("mult") or 1))
    rows = []
    by_sym: dict[str, list[dict]] = {}
    for r in oi:
        by_sym.setdefault(r["symbol"], []).append(r)
    for s, rs in by_sym.items():
        p = px.get(s)
        today = next((r for r in rs if str(r["d"])[:10] == d.isoformat()), None)
        if not p or not today or d.isoformat() not in p:
            continue
        implied = {str(r["d"])[:10]: float(r["oi_value_close"]) / float(r["oi_close"])
                   for r in rs if r.get("oi_close") and r.get("oi_value_close") and float(r["oi_close"]) > 0}
        mult = next(iter(p.values()))[2]
        if not mapping_ok({k: v[0] for k, v in p.items()}, implied, mult):
            continue
        rows.append({"sym": s, "oi": today.get("oi_value_close"), "mcap": p[d.isoformat()][1]})
    pmap = size_neutral_pct(rows)
    return pmap, len(pmap)


async def tag_oi_new_tickets(today: Optional[dt.date] = None) -> dict[str, Any]:
    """给还没有 OI 标签(或之前缺数、仍在重试窗口内)的 R-v2 纸面票打标签。读不到就抛。"""
    from src.api.store import supabase_upsert_table
    from src.data.style.header import _read_all
    today = today or dt.datetime.now(dt.timezone.utc).date()
    tickets = await _read_all("r_tickets_paper", {"select": "ticket_id,symbol,signal_d", "order": "ticket_id.asc"})
    have = {r["ticket_id"]: r for r in await _read_all(TABLE, {"select": "ticket_id,p,signal_d", "order": "ticket_id.asc"})}
    todo = [t for t in tickets if t["ticket_id"] not in have
            or (have[t["ticket_id"]].get("p") is None
                and (today - dt.date.fromisoformat(str(t["signal_d"])[:10])).days <= RETRY_DAYS)]
    if not todo:
        return {"status": "ok", "tagged": 0}
    out = []
    for d in sorted({str(t["signal_d"])[:10] for t in todo}):
        pmap, n = await cross_section(dt.date.fromisoformat(d))
        why = None if n else "当天的 Binance OI 归档还没落库(隔天才有)"
        out += [tag_row(t, pmap, n, why) for t in todo if str(t["signal_d"])[:10] == d]
    w = await supabase_upsert_table(TABLE, out, on_conflict="ticket_id")
    if not w:
        return {"status": "error", "reason": f"{TABLE} 写不进去:{getattr(w, 'why', '')}"}
    return {"status": "ok", "tagged": len(out), "high": sum(1 for r in out if r["high"]),
            "missing": sum(1 for r in out if r["p"] is None)}
