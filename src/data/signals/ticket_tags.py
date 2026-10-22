"""R-v2 票的基本面标签:开票当时的 90 日流通量增长(稀释)—— 台账 S-665 的前向记录。

S-665(10-21):开在高稀释币上的 R-v2 票平均少赚约一半(低稀释一半 − 高稀释一半 +0.54R,年内打乱 p 0.022,
2023 前后两段同号;最高三分位 = 一个季度流通量涨 > 2.2%,平均 +0.28R,其余两档 +0.57R / +0.76R)。
**10-22 稳健性(T-178 独立复算 + Seth 复跑):** 中位数切半的 ① 只在「信号日当天的流通量」下成立,测量日往前挪 1 / 2 / 3 / 7 天
p 都 ≥ 0.31 —— 形式上的「过」不当证据。稳的只有「一季度稀释 > 2.2%」那一档(每个挪法下平均 R 0.24–0.31,其余 0.64–0.69),
而 2.2% 是看过结果才定的 ⇒ **前向假设,不是已验证**。前向判时用 > 2.2% 那一档,测量日用**信号日前一天**
(信号日多是突破日,当天的 市值 ÷ 价格 掺着当天的价格变动)—— 前一天的值从 asset_mcap_daily 现算,本表照旧记信号日的。
**前向才是证据**:每张新票(含闸门挡下的 blocked)在信号日打上 dil90 = ln(供给[t] / 供给[t − 90])。
实盘不因此跳过任何票 —— 那是前向攒够之后 Jazz 的决定。

流通量 = asset_mcap_daily 的 市值 ÷ 价格(CoinGecko),按 symbol 接(去掉 1000 前缀;同 symbol 取当日市值最大的 coin_id),
t 与 t − 90 前后 7 天内要有观测,否则记 why_missing(不是 0)。
判活:`select count(*) from r_tickets_paper p left join r_ticket_tags t using (ticket_id) where t.ticket_id is null`
= 0(或只剩当天刚出的);`_r_tickets_paper_loop` 的 detail 里 `tags`。
"""
from __future__ import annotations

import datetime as dt
import math
from typing import Any, Iterable, Optional

TABLE = "r_ticket_tags"
WRITES_TABLES = (TABLE,)
HIGH_DIL = 0.022            # S-665 历史最高三分位的下界(看过结果才定的门槛 ⇒ 前向假设;只报,不进任何执行)
TOL_DAYS = 7


def norm_symbol(sym: str) -> str:
    s = str(sym or "").upper()
    return s[4:] if s.startswith("1000") and len(s) > 4 else s


def pick_coin(rows: Iterable[dict]) -> dict[str, str]:
    """纯函数。asset_mcap_daily 某一天的行 → {symbol: 市值最大的 coin_id}。"""
    best: dict[str, tuple[float, str]] = {}
    for r in rows:
        s, c, m = str(r.get("symbol") or "").upper(), r.get("coin_id"), float(r.get("mcap") or 0.0)
        if s and c and (s not in best or m > best[s][0]):
            best[s] = (m, c)
    return {s: v[1] for s, v in best.items()}


def supply_at(series: list[tuple[dt.date, float]], d: dt.date) -> Optional[float]:
    """纯函数。[(日, 供给)] 升序 → d 当天或之前 TOL_DAYS 天内最近的供给。"""
    best = None
    for day, s in series:
        if day > d:
            break
        best = (day, s)
    return best[1] if best and (d - best[0]).days <= TOL_DAYS else None


def tag(ticket: dict, coin_id: Optional[str], series: list[tuple[dt.date, float]]) -> dict[str, Any]:
    """纯函数。一张票 → 一行标签。"""
    d = dt.date.fromisoformat(str(ticket["signal_d"])[:10])
    row = {"ticket_id": ticket["ticket_id"], "symbol": ticket["symbol"], "signal_d": d.isoformat(), "coin_id": coin_id,
           "supply_t": None, "supply_t90": None, "dil90": None, "why_missing": None, "rule": "S-665"}
    if not coin_id:
        row["why_missing"] = "asset_mcap_daily 里没有这个 symbol"
        return row
    a, b = supply_at(series, d), supply_at(series, d - dt.timedelta(days=90))
    row["supply_t"], row["supply_t90"] = a, b
    if a and b and a > 0 and b > 0:
        row["dil90"] = math.log(a / b)
    else:
        row["why_missing"] = "信号日或 90 天前 7 天内没有市值 / 价格"
    return row


async def tag_new_tickets() -> dict[str, Any]:
    """给还没有标签的票打标签。读不到就抛(S-180);写不进去返回 error。"""
    from src.api.store import supabase_upsert_table
    from src.data.style.header import _read_all
    from src.data.vector.market_state_writer import _sb_get
    tickets = await _read_all("r_tickets_paper", {"select": "ticket_id,symbol,signal_d", "order": "ticket_id.asc"})
    done = {r["ticket_id"] for r in await _read_all(TABLE, {"select": "ticket_id", "order": "ticket_id.asc"})}
    todo = [t for t in tickets if t["ticket_id"] not in done]
    if not todo:
        return {"status": "ok", "tagged": 0, "missing": 0}
    syms = sorted({norm_symbol(t["symbol"]) for t in todo})
    last = await _sb_get("asset_mcap_daily", {"select": "d", "order": "d.desc", "limit": "1"})
    if not last.ok or not last.rows:
        raise RuntimeError(f"asset_mcap_daily 读不到:{last.reason}")
    lo = min(dt.date.fromisoformat(str(t["signal_d"])[:10]) for t in todo) - dt.timedelta(days=90 + TOL_DAYS)
    rows = await _read_all("asset_mcap_daily", {"select": "symbol,coin_id,d,price,mcap",
                                                "symbol": f"in.({','.join(syms)})", "d": f"gte.{lo.isoformat()}",
                                                "order": "symbol.asc,coin_id.asc,d.asc"})
    latest = pick_coin(r for r in rows if str(r["d"])[:10] == max(str(x["d"])[:10] for x in rows)) if rows else {}
    series: dict[str, list[tuple[dt.date, float]]] = {}
    for r in rows:
        if r.get("price") and r.get("mcap") and float(r["price"]) > 0:
            series.setdefault(r["coin_id"], []).append((dt.date.fromisoformat(str(r["d"])[:10]),
                                                        float(r["mcap"]) / float(r["price"])))
    out = []
    for t in todo:
        cid = latest.get(norm_symbol(t["symbol"]))
        out.append(tag(t, cid, series.get(cid, [])))
    w = await supabase_upsert_table(TABLE, out, on_conflict="ticket_id")
    if not w:
        return {"status": "error", "reason": f"{TABLE} 写不进去:{getattr(w, 'why', '')}"}
    return {"status": "ok", "tagged": len(out), "missing": sum(1 for r in out if r["dil90"] is None),
            "high_dil": sum(1 for r in out if r["dil90"] is not None and r["dil90"] > HIGH_DIL)}
