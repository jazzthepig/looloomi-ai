"""S-751 ✅ 的落地:Binance 整币下架公告 → 观察名单 + 前向记录(lane-b T-272;11-07)。

## 研究说了什么

2022-02 → 2026-10 的 39 条整币下架公告、164 个代币里,下架后 CoinGecko 还有价的 53 个:公告日收盘之后 30 天相对 BTC
**中位 −37.7%、81% 为负**,随机日期对照分位 0.000。大头在公告**之前**已经跌了(前 30 天 −34%、公告当天 −24%),
所以它更像「坏币的持续性」而不是公告的因果 —— 但对一个持有者来说结论一样:**名字一上下架公告,就不该再拿着**。
另两个限制写在这里:111 个代币下架后没有价(看不见,很可能更差);2022–23 段只有 1 个有价样本(S-751 判据 (d) 只是形式上过)。

## 这个模块做两件事(都不动钱)

1. **观察名单** `watchlist()`:过去 `WATCH_DAYS` 天里被 Binance 宣布整币下架的代币。
   **Jazz 11-07 拍成硬规则(「下架对一个代币是致命的」):** 过去 `EXCLUDE_DAYS` 天里被宣布整币下架的代币 ——
   R-v2 计划(`ticket_plan.load_ticket_plan` → `apply_to_plan`)不开新票、已有持仓移到出场;多头账本的面板若出现这些名字,
   本循环记 error 并写明哪本账、哪个名字(面板是 24–25 个大币,11-07 与全部 164 个下架代币零交集)。
   窗口取 365 天而不是永久:代号会被新币复用(T-272 见过 DATA)。
   **Jazz 11-08 前移到「打标签」(S-753 ✅ + S-785;S-789 在逐句解析的 137 个代号上重量:打标签之后 30 天中位 −15.8%、
   打标签 → 下架公告中位 61 天那段 −41%;在 R-v2 回放账本上历史代价 ≈ 0):** 此刻挂着 Binance **监控标签**的代币同样不开新票、已有持仓当天开盘出场。
   「此刻挂着」= 按公告标题逐句走状态机(`events.monitoring_tag_changes`:打上 / 移除监控标签;种子标签那一支不进状态机,
   T-308 查出 v1 按整行判会把 43 次「打上」记成「移除」);标签被移除就不再排除。读不到同样 fail closed。
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
CODE_REF = "delisting_watch v2 (11-08, S-751 / T-272 + 监控标签前移 S-753)"
FORWARD_FROM = dt.datetime(2026, 11, 7, tzinfo=dt.timezone.utc)
WATCH_DAYS = 90
EXCLUDE_DAYS = 365
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


def exclusion_set(rows: list[dict], now: dt.datetime, days: int = EXCLUDE_DAYS) -> set[str]:
    """纯函数。过去 days 天里被宣布整币下架的代币(硬规则的名单)。"""
    cut = now - dt.timedelta(days=days)
    return {str(r["symbol"]).upper() for r in rows if r.get("symbol") and _ts(r["announced_at"]) >= cut}


def active_tags(rows: list[dict]) -> dict[str, str]:
    """纯函数。监控标签公告(ts, title)→ {此刻挂着标签的代号: 这一段打上的那天}。按时间逐句走:打上 ⇒ 开(已开着不改日子),
    移除 ⇒ 关;种子标签不算。"""
    from src.data.market.events import monitoring_tag_changes
    on: dict[str, str] = {}
    for r in sorted(rows or [], key=lambda r: str(r.get("ts") or "")):
        d = str(r.get("ts") or "")[:10]
        ch = monitoring_tag_changes(r.get("title") or "")
        for sym in ch["add"]:
            on.setdefault(sym.upper(), d)
        for sym in ch["rem_mon"]:
            on.pop(sym.upper(), None)
    return on


def is_excluded(symbol: str, excl: set[str]) -> bool:
    """纯函数。R-v2 的代号可能带 1000 前缀(1000PEPE)。"""
    s = str(symbol or "").upper()
    return s in excl or (s.startswith("1000") and s[4:] in excl)


REASON_DELIST = "binance_delisting"
REASON_TAG = "binance_monitoring_tag"
_WHY = {REASON_DELIST: "Binance 整币下架公告(S-751 硬规则)", REASON_TAG: "Binance 监控标签(Jazz 11-08 硬规则前移,S-753)"}


def _reason(symbol: str, reasons: Optional[dict[str, str]]) -> str:
    s = str(symbol or "").upper()
    r = reasons or {}
    return r.get(s) or (r.get(s[4:]) if s.startswith("1000") else None) or REASON_DELIST


def apply_to_plan(plan: dict[str, Any], excl: set[str], reasons: Optional[dict[str, str]] = None) -> dict[str, Any]:
    """纯函数。R-v2 计划 + 名单 → 新票里的剔除到 `skipped_delist`,持有里的移到 `exit`(当天开盘出)。
    reasons = {代号: binance_delisting / binance_monitoring_tag};没给 ⇒ 都按下架记(旧调用)。"""
    enter, skipped = [], []
    for e in plan.get("enter") or []:
        (skipped if is_excluded(e.get("symbol"), excl) else enter).append(e)
    hold, forced = [], []
    for h in plan.get("hold") or []:
        if is_excluded(h.get("symbol"), excl):
            forced.append({"ticket_id": h.get("ticket_id"), "symbol": h.get("symbol"), "why": _reason(h.get("symbol"), reasons),
                           "at": "today_open"})
        else:
            hold.append(h)
    n_tag = sum(1 for v in (reasons or {}).values() if v == REASON_TAG)
    return {**plan, "enter": enter, "hold": hold, "exit": list(plan.get("exit") or []) + forced,
            "skipped_delist": [{**x, "why": _WHY[_reason(x.get("symbol"), reasons)]} for x in skipped],
            "delist_filter": {"status": "ok", "n_names": len(excl), "n_tagged": n_tag, "skipped": [x.get("symbol") for x in skipped],
                              "forced_exit": [x["symbol"] for x in forced]}}


async def excluded_with_reasons(now: Optional[dt.datetime] = None) -> dict[str, str]:
    """硬规则名单 {代号: 原因}:过去 365 天整币下架 ∪ 此刻挂着监控标签(Jazz 11-08)。**任何一张读不到就抛** —— 调用方 fail closed。"""
    from src.data.style.header import _read_all              # 读不到会抛(传输失败 ≠ 0 行)
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    cut = (now - dt.timedelta(days=EXCLUDE_DAYS)).isoformat()
    rows = await _read_all(TABLE, {"select": "symbol,announced_at", "announced_at": f"gte.{cut}", "order": "announced_at.asc"})
    tags = await _read_all("events", {"select": "ts,title", "source": "eq.binance",
                                      "kind": "in.(monitoring_tag,monitoring_tag_removed)", "order": "ts.asc"})
    out = {s: REASON_TAG for s in active_tags(tags or [])}
    out.update({s: REASON_DELIST for s in exclusion_set(rows or [], now)})     # 两样都有 ⇒ 记下架(更重)
    return out


async def excluded_symbols(now: Optional[dt.datetime] = None) -> set[str]:
    """硬规则名单(集合)。**读不到就抛** —— 调用方 fail closed(不开新票),不能把「读不到」当成「名单是空的」。"""
    return set(await excluded_with_reasons(now))


def panel_conflicts(excl: set[str]) -> dict[str, list[str]]:
    """多头账本面板里出现了名单上的名字 ⇒ {账本: [名字]}(硬规则要求剔除;面板是静态的,出现就要人改)。"""
    import importlib
    out = {}
    for m in ("core_cap", "cis_tilt", "beta_plus_momentum", "tokenization_tilt", "treatment_tilt"):
        try:
            mod = importlib.import_module(f"src.data.signals.{m}")
            uni = mod.panel_universe() if hasattr(mod, "panel_universe") else ()
        except Exception:                                              # noqa: BLE001
            continue
        hit = sorted(s for s in uni if is_excluded(s, excl))
        if hit:
            out[m] = hit
    return out


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
    tags = await read("events", {"select": "ts,title", "source": "eq.binance",
                                 "kind": "in.(monitoring_tag,monitoring_tag_removed)", "order": "ts.asc"})
    tagged = active_tags(tags or [])
    conflicts = panel_conflicts(exclusion_set(out, now) | set(tagged))
    if conflicts:
        return {"ok": False, "written": len(out), "panel_conflicts": conflicts,
                "why": f"硬规则冲突(S-751 / 11-08 监控标签):多头账本面板里有 Binance 宣布下架或挂着监控标签的名字 {conflicts} —— 要从面板剔除"}
    return {"ok": True, "written": len(out), "forward": len(fwd), "settled_30d": sum(r["excess_30d"] is not None for r in out),
            "watch": [x["symbol"] for x in w][:20],
            "tagged": sorted(tagged)[:40],
            "why": f"{len(out)} 个代币(前向 {len(fwd)})· 30 天已结算 {sum(r['excess_30d'] is not None for r in out)} · 观察名单 {len(w)}"
                   f" · 挂着监控标签 {len(tagged)}"}
