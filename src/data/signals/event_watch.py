"""Binance 上币 / 永续上线的前向记录(S-763 / S-758 ✅ 之后,11-07)—— 事件族里站住的另两条,和下架(`delisting_watch`)同一个做法。

## 研究说了什么

- **现货上币(S-708 / S-763):** 真实公告日之后 d+1 → d+30 相对 PIT 加密篮中位 −21.4%,随机日对照分位 0.000;公告前 30 天中位 +41%。
- **USDT 永续上线(S-740 / S-758 / S-764):** 现货先有、后上永续的代币,30 天相对 BTC 中位 −21.9%(n 142),盲复算吻合。

两条都是**描述 / 前向记录**,不是交易规则(④ 的空票在 S-761 / S-762 收卷了:期望是真的,左尾吃不下)。这里把 2026-11-07 起的
每一条新公告记下来,到期补 30 / 90 天相对 BTC 的超额(`cohort = forward`);之前的只作对照(`backfill`)。探索仓与 AI 判断臂
遇到「刚上币 / 刚上永续」的名字时查这张表。

## 口径

- 事件 = `events` source = binance:`listing` 只取 scope = spot 且标题含 "Will List"(不含 "Trading Pair");`perp_listing` 去掉 Alpha 与
  COIN-M(币本位)。代号用 `events.symbols`(S-764 用它复算吻合)。同一 (类别, 代号) 取第一次。
- d0 = 公告时刻所在 UTC 日;价取 d0 当天或之后最近的收盘(上币常在公告后才开盘,最多等 `LISTING_GAP_DAYS` 天);超额 = 代币 − BTC 的简单收益。
  没价就空着,不写 0(新币在 `asset_mcap_daily` 收录有滞后 —— S-763 的 703 条里 480 条无价)。

判活:`select kind, cohort, count(*), count(excess_30d) from binance_event_watch group by 1, 2`。
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Optional

TABLE = "binance_event_watch"
WRITES_TABLES = (TABLE,)
WRITES_COLUMNS = {TABLE: ("kind", "symbol", "announced_at", "d0", "title", "cohort", "excess_30d", "excess_90d",
                          "price_source", "code_ref", "settled_at")}
CODE_REF = "event_watch v1 (11-07, S-763 / S-758)"
FORWARD_FROM = dt.datetime(2026, 11, 7, tzinfo=dt.timezone.utc)
KINDS = ("listing", "perp_listing")
LISTING_GAP_DAYS = 10
HORIZONS = ((30, "excess_30d"), (90, "excess_90d"))
PRICE_TABLE = "asset_mcap_daily"


def _ts(v: Any) -> dt.datetime:
    t = dt.datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def keep(row: dict) -> bool:
    """纯函数。这条公告进不进记录(口径见模块头)。"""
    kind, title = row.get("kind"), str(row.get("title") or "")
    scope = str(((row.get("payload") or {}) if isinstance(row.get("payload"), dict) else {}).get("scope") or "")
    if kind == "listing":
        return scope == "spot" and "Will List" in title and "Trading Pair" not in title
    if kind == "perp_listing":
        t = title.lower()
        return scope != "alpha" and "coin-m" not in t and "coin-margined" not in t
    return False


def entries(events: list[dict]) -> list[dict]:
    """纯函数。events → 每个 (类别, 代号) 第一次公告。"""
    seen: dict[tuple[str, str], dict] = {}
    for e in sorted(events, key=lambda e: str(e.get("ts"))):
        if not keep(e):
            continue
        ts = _ts(e["ts"])
        syms = e.get("symbols") or []
        for s in syms if isinstance(syms, list) else []:
            s = str(s).upper()
            if not s or (e["kind"], s) in seen:
                continue
            seen[(e["kind"], s)] = {"kind": e["kind"], "symbol": s, "announced_at": ts.isoformat(), "d0": ts.date().isoformat(),
                                    "title": str(e.get("title") or "")[:300], "cohort": "forward" if ts >= FORWARD_FROM else "backfill"}
    return list(seen.values())


def settle(entry: dict, px: dict[str, float], btc: dict[str, float], today: dt.date) -> dict:
    """纯函数。到期才结算;没价 ⇒ 空着。起点价最多等 LISTING_GAP_DAYS 天(新币开盘晚)。"""
    from src.data.signals.delisting_watch import price_on_or_after
    d0 = dt.date.fromisoformat(entry["d0"])
    out = dict(entry)
    p0, b0 = price_on_or_after(px, d0, LISTING_GAP_DAYS), price_on_or_after(btc, d0, LISTING_GAP_DAYS)
    for h, key in HORIZONS:
        out[key] = None
        if p0 is None or b0 is None or (today - d0).days < h + LISTING_GAP_DAYS + 1:
            continue
        p1, b1 = price_on_or_after(px, d0 + dt.timedelta(days=h), 3), price_on_or_after(btc, d0 + dt.timedelta(days=h), 3)
        if p1 is not None and b1 is not None:
            out[key] = round((p1 / p0 - 1) - (b1 / b0 - 1), 6)
    out["price_source"] = PRICE_TABLE if p0 is not None else None
    out["code_ref"] = CODE_REF
    out["settled_at"] = dt.datetime.now(dt.timezone.utc).isoformat() if out.get("excess_90d") is not None else None
    return out


def recent(rows: list[dict], symbol: str, now: dt.datetime, days: int = 30) -> list[dict]:
    """纯函数。某个代号过去 days 天里的上币 / 上永续公告(给探索仓 / AI 判断臂的提示)。"""
    s, cut = str(symbol or "").upper(), now - dt.timedelta(days=days)
    return [r for r in rows if r.get("symbol") == s and _ts(r["announced_at"]) >= cut]


async def run_once(now: Optional[dt.datetime] = None, read=None, upsert=None) -> dict[str, Any]:
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    if read is None:
        from src.data.style.header import _read_all as read
    if upsert is None:
        from src.api.store import supabase_upsert_table as upsert
    ev = await read("events", {"select": "ts,kind,title,symbols,payload", "source": "eq.binance",
                               "kind": f"in.({','.join(KINDS)})", "order": "ts.asc"})
    ents = entries(ev or [])
    if not ents:
        return {"ok": False, "refused": True, "why": f"events 里没有可记录的上币 / 上永续公告({len(ev or [])} 条)"}
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
        if not await upsert(TABLE, out[i:i + 500], on_conflict="kind,symbol"):
            return {"ok": False, "why": f"写 {TABLE} 失败"}
    by = {k: sum(1 for r in out if r["kind"] == k) for k in KINDS}
    fwd = sum(1 for r in out if r["cohort"] == "forward")
    settled = sum(1 for r in out if r["excess_30d"] is not None)
    return {"ok": True, "written": len(out), "by_kind": by, "forward": fwd, "settled_30d": settled,
            "why": f"{len(out)} 个(上币 {by['listing']} / 上永续 {by['perp_listing']};前向 {fwd})· 30 天已结算 {settled}"}
