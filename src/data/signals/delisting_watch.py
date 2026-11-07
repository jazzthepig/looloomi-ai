"""S-751 ✅ 的落地:Binance 整币下架公告 → 观察名单 + 前向记录(lane-b T-272;11-07)。

## 研究说了什么

2022-02 → 2026-10 的 39 条整币下架公告、164 个代币里,下架后 CoinGecko 还有价的 53 个:公告日收盘之后 30 天相对 BTC
**中位 −37.7%、81% 为负**,随机日期对照分位 0.000。大头在公告**之前**已经跌了(前 30 天 −34%、公告当天 −24%),
所以它更像「坏币的持续性」而不是公告的因果 —— 但对一个持有者来说结论一样:**名字一上下架公告,就不该再拿着**。
另两个限制写在这里:111 个代币下架后没有价(看不见,很可能更差);2022–23 段只有 1 个有价样本(S-751 判据 (d) 只是形式上过)。

## 这个模块做两件事(都不动钱)

1. **观察名单** `watchlist()`:过去 `WATCH_DAYS` 天里被 Binance 宣布整币下架的代币。② 面板卫生规则的**候选**输入 ——
   真正让账本剔除它们要 Jazz 拍(R-v2 是真钱账本)。
2. **前向记录**:`FORWARD_FROM` 起的每一条新公告,到期后补 7 / 30 天相对 BTC 的超额(`kind = forward`);之前的只作回填对照
   (`kind = backfill`,不算前向证据)。口径与 T-272 一字不差:d0 = 公告时刻所在的 UTC 日(`asset_mcap_daily` 的 d 是当日收盘,
   在公告之后),价取 d0 当天或之后 3 天内最近的收盘,超额 = 代币简单收益 − BTC 简单收益。

筛选规则照抄 lane-b `docs/research/t272_delisting.py`(标题含 "Will Delist" 且不含杠杆 / 借贷 / 交易对 / 板块等标记;一个代币多次
公告取第一次)。判活:`select kind, count(*), count(excess_30d), max(announced_at) from delisting_watch group by 1`。
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Any, Optional

TABLE = "delisting_watch"
WRITES_TABLES = (TABLE,)
WRITES_COLUMNS = {TABLE: ("symbol", "announced_at", "d0", "title", "kind", "excess_7d", "excess_30d",
                          "ret_30d", "btc_30d", "price_source", "code_ref", "settled_at")}
LOOP_NAME = "_delisting_watch_loop"
CODE_REF = "delisting_watch v1 (11-07, S-751 / T-272)"
FORWARD_FROM = dt.datetime(2026, 11, 7, tzinfo=dt.timezone.utc)
WATCH_DAYS = 90
MAX_GAP_DAYS = 3
PRICE_TABLE = "asset_mcap_daily"

BANNED = ("Margin", "Loan", "Leveraged Token", "Options", "Alpha", "Staking",
          "Earn", "Redemption", "Trading Pair", "Collateral", "Stocks")


def screen_title(title: str) -> bool:
    """纯函数。整币现货下架公告 ⇒ True(T-272 的纳入规则)。"""
    t = str(title or "")
    return "Will Delist" in t and not any(b in t for b in BANNED)


def extract_symbols(title: str) -> list[str]:
    """纯函数。标题里 "Will Delist" 之后的代币列表(T-272 原样)。"""
    m = re.search(r"\bWill Delist\b(.*)$", str(title or ""))
    if not m:
        return []
    seg = re.sub(r"\s+on\s+\d{4}-\d{2}-\d{2}.*$", "", m.group(1))
    seg = re.sub(r"\s*\(.*?\)\s*$", "", seg)
    out = []
    for part in re.split(r",|\band\b", seg):
        s = part.strip().strip(".").strip()
        if s and re.fullmatch(r"[A-Za-z0-9]{1,12}", s):
            out.append(s.upper())
    return out


def _ts(v: Any) -> dt.datetime:
    t = dt.datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def entries(events: list[dict]) -> list[dict]:
    """纯函数。events(binance / delisting)→ 每个代币第一次整币下架公告:{symbol, announced_at, d0, title, kind}。"""
    seen: dict[str, dict] = {}
    for e in sorted(events, key=lambda e: str(e.get("ts"))):
        if not screen_title(e.get("title")):
            continue
        ts = _ts(e["ts"])
        for s in extract_symbols(e.get("title")):
            if s not in seen:
                seen[s] = {"symbol": s, "announced_at": ts.isoformat(), "d0": ts.date().isoformat(),
                           "title": str(e.get("title"))[:300], "kind": "forward" if ts >= FORWARD_FROM else "backfill"}
    return list(seen.values())


def price_on_or_after(series: dict[str, float], d: dt.date, max_gap: int = MAX_GAP_DAYS) -> Optional[float]:
    """纯函数。d 当天或之后 max_gap 天内最早的收盘。"""
    for k in range(max_gap + 1):
        v = series.get((d + dt.timedelta(days=k)).isoformat())
        if v is not None and v > 0:
            return v
    return None


def settle(entry: dict, px: dict[str, float], btc: dict[str, float], today: dt.date) -> dict:
    """纯函数。到期的那一档补超额;没到期 / 没价 ⇒ None(不写 0)。"""
    d0 = dt.date.fromisoformat(entry["d0"])
    out = dict(entry)
    p0, b0 = price_on_or_after(px, d0), price_on_or_after(btc, d0)
    for h, key in ((7, "excess_7d"), (30, "excess_30d")):
        out[key] = None
        if (today - d0).days < h + MAX_GAP_DAYS + 1 or p0 is None or b0 is None:
            continue
        p1, b1 = price_on_or_after(px, d0 + dt.timedelta(days=h)), price_on_or_after(btc, d0 + dt.timedelta(days=h))
        if p1 is None or b1 is None:
            continue
        r, rb = p1 / p0 - 1, b1 / b0 - 1
        out[key] = round(r - rb, 6)
        if h == 30:
            out["ret_30d"], out["btc_30d"] = round(r, 6), round(rb, 6)
    out.setdefault("ret_30d", None)
    out.setdefault("btc_30d", None)
    out["price_source"] = PRICE_TABLE if p0 is not None else None
    out["code_ref"] = CODE_REF
    out["settled_at"] = dt.datetime.now(dt.timezone.utc).isoformat() if out.get("excess_30d") is not None else None
    return out


def watchlist(rows: list[dict], now: dt.datetime, days: int = WATCH_DAYS) -> list[dict]:
    """纯函数。过去 days 天里被宣布整币下架的代币(新的在前)。"""
    cut = now - dt.timedelta(days=days)
    return sorted([{"symbol": r["symbol"], "announced_at": r["announced_at"], "title": r.get("title")}
                   for r in rows if _ts(r["announced_at"]) >= cut], key=lambda r: r["announced_at"], reverse=True)


async def run_once(now: Optional[dt.datetime] = None, read=None, upsert=None) -> dict[str, Any]:
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    if read is None:
        from src.data.style.header import _read_all as read
    if upsert is None:
        from src.api.store import supabase_upsert_table as upsert
    ev = await read("events", {"select": "ts,title", "source": "eq.binance", "kind": "eq.delisting", "order": "ts.asc"})
    ents = entries(ev or [])
    if not ents:
        return {"ok": False, "refused": True, "why": f"events 里读不到整币下架公告({len(ev or [])} 条 delisting)"}
    syms = sorted({e["symbol"] for e in ents} | {"BTC"})
    since = (min(dt.date.fromisoformat(e["d0"]) for e in ents) - dt.timedelta(days=2)).isoformat()
    series: dict[str, dict[str, float]] = {}
    for i in range(0, len(syms), 60):
        rows = await read(PRICE_TABLE, {"select": "symbol,d,price", "symbol": f"in.({','.join(syms[i:i + 60])})",
                                        "d": f"gte.{since}", "order": "symbol.asc,d.asc"})
        for r in rows or []:
            if r.get("price") is not None:
                series.setdefault(str(r["symbol"]).upper(), {})[str(r["d"])[:10]] = float(r["price"])
    btc = series.get("BTC", {})
    if not btc:
        return {"ok": False, "refused": True, "why": f"{PRICE_TABLE} 里读不到 BTC"}
    out = [settle(e, series.get(e["symbol"], {}), btc, now.date()) for e in ents]
    for i in range(0, len(out), 500):
        if not await upsert(TABLE, out[i:i + 500], on_conflict="symbol"):
            return {"ok": False, "why": f"写 {TABLE} 失败"}
    fwd = [r for r in out if r["kind"] == "forward"]
    w = watchlist(out, now)
    return {"ok": True, "written": len(out), "forward": len(fwd), "settled_30d": sum(r["excess_30d"] is not None for r in out),
            "watch": [x["symbol"] for x in w][:20],
            "why": f"{len(out)} 个代币(前向 {len(fwd)})· 30 天已结算 {sum(r['excess_30d'] is not None for r in out)} · 观察名单 {len(w)}"}
