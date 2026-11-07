"""韩国散户数据(11-07,Jazz:「找疯狂和绝望的大众 / 散户资金作为对手盘」)—— Upbit 的三条免费流。

## 为什么

我们手上的「散户」量都是**全球、按全市场**的(Binance 多空账户比、主动买卖比、韩国所**总**成交份额),而 S-737 / S-765 已经说明
全市场版本读不出东西。散户的疯狂与绝望是**按币**发生的,而且韩国是唯一一个「散户为主、币种齐全、数据公开」的市场:

1. **`upbit_daily`** —— 每个 KRW 市场的日线(UTC 00:00 切日,与 Binance 同一根)。按币算两个量:**韩国溢价**(KRW 价 ÷ 全球美元价,
   再除以 BTC 自己的溢价 ⇒ 去掉汇率与全市场溢价,只剩「韩国人对这个币多付了多少」)与**韩国成交份额**(KRW 成交额 ÷ 全球成交额)。
2. **`upbit_market_event_daily`** —— Upbit 自己给每个市场打的标签:`warning`(投资警告)与五个 caution(价格急变 / 成交暴增 /
   入金暴增 / **与海外价差** / **小额账户集中**)。这是交易所自己说「这里有散户在疯」,只有当前状态、没有历史 ⇒ 从今天起每天记,
   同一天里见过就算(取当天各轮的 OR)。
3. **Upbit 交易公告 → `events`(source = upbit)** —— 2017-10 起约 800 条:KRW 上币(「신규 거래지원」「KRW 마켓 디지털 자산 추가」,
   韩国散户最有名的追涨事件)、下架(「거래지원 종료」)、유의 종목 지정(警告,Binance 监控标签的韩国版)及延长 / 解除、유의 촉구(劝告)。

## 免费源的请求量(登记,Jazz 免费源规则)

Upbit 行情接口公开、无钥匙,限 10 次 / 秒 / IP —— 这里 ≤ 5 次 / 秒。**每天:** 日线 ≈ 300 次(每个 KRW 市场 count=3,一天一次)+
市场标签 24 次 + 公告第 1 页 24 次。**一次性回填:** 日线 ≈ 2,400 次(每轮 `BF_MARKETS` 个市场,约 10 轮翻完)+ 公告 41 页
(公告接口在 Cloudflare 后面,连发 1 秒间隔就 1015 ⇒ 每轮最多 `NOTICE_BF_PAGES` 页、间隔 3 秒,遇 1015 当轮停)。

## 已知的偏

**Upbit 已下架的市场取不到日线**(KRW-LUNA ⇒ 404)⇒ 日线有幸存者偏差:「追涨之后跑输」会被低估(死掉的最差的看不见,保守),
「恐慌之后反弹」会被高估(不保守)—— 研究时必须写明。公告不受影响(下架公告本身在)。

判活:`select count(distinct market), min(d), max(d) from upbit_daily` · `select d, count(*) filter (where n_caution > 0 or warning)
from upbit_market_event_daily group by 1` · `select kind, count(*), min(ts), max(ts) from events where source = 'upbit' group by 1`。
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Any, Optional

DAILY_TABLE = "upbit_daily"
EVENT_TABLE = "upbit_market_event_daily"
WRITES_TABLES = (DAILY_TABLE, EVENT_TABLE, "events")
WRITES_COLUMNS = {
    DAILY_TABLE: ("market", "symbol", "d", "o", "h", "l", "c", "vol_base", "vol_krw"),
    EVENT_TABLE: ("d", "market", "symbol", "warning", "caution", "n_caution", "last_seen_at"),
    "events": ("id", "ts", "kind", "source", "symbols", "title", "url", "payload"),
}
LOOP_NAME = "_retail_flow_loop"
CODE_REF = "korea_retail v1 (11-07)"

UPBIT = "https://api.upbit.com/v1"
NOTICES = "https://api-manager.upbit.com/api/v1/announcements"
NOTICE_URL = "https://upbit.com/service_center/notice?id={id}"
CAUTION_KEYS = ("PRICE_FLUCTUATIONS", "TRADING_VOLUME_SOARING", "DEPOSIT_AMOUNT_SOARING",
                "GLOBAL_PRICE_DIFFERENCES", "CONCENTRATION_OF_SMALL_ACCOUNTS")
BF_MARKETS = 30                 # 每轮回填的市场数(约 240 次请求)
NOTICE_BF_PAGES = 5
NOTICE_PER_PAGE = 20
CANDLE_SLEEP_S = 0.22           # ≤ 5 次 / 秒
NOTICE_SLEEP_S = 3.0
BF_KEY = "korea:upbit_candles_backfill"
NOTICE_BF_KEY = "korea:upbit_notice_backfill"
DAILY_KEY = "korea:upbit_daily_refresh:{d}"

_CODE = r"[A-Z0-9]{2,12}"
_MARKETS = {"KRW", "BTC", "USDT", "ETH"}


# ── 纯函数 ──────────────────────────────────────────────────────────────

def market_symbol(market: str) -> Optional[str]:
    """'KRW-BTC' → 'BTC';不是 KRW 市场 ⇒ None。"""
    m = str(market or "")
    return m[4:].upper() if m.startswith("KRW-") and len(m) > 4 else None


def candle_rows(market: str, candles: list[dict], today: dt.date) -> list[dict]:
    """纯函数。Upbit 日线 → 行;**丢掉今天(还没收盘)的那根**,只留已完成的 UTC 日。"""
    sym = market_symbol(market)
    out = []
    for c in candles or []:
        try:
            d = dt.date.fromisoformat(str(c["candle_date_time_utc"])[:10])
        except (KeyError, ValueError):
            continue
        if d >= today or sym is None:
            continue
        out.append({"market": market, "symbol": sym, "d": d.isoformat(),
                    "o": c.get("opening_price"), "h": c.get("high_price"), "l": c.get("low_price"), "c": c.get("trade_price"),
                    "vol_base": c.get("candle_acc_trade_volume"), "vol_krw": c.get("candle_acc_trade_price")})
    return out


def event_rows(markets: list[dict], d: dt.date, now: dt.datetime, prev: Optional[dict[str, dict]] = None) -> list[dict]:
    """纯函数。market/all?isDetails=true → 当天的标签行;prev(当天之前几轮的同一行)⇒ 取 OR(当天见过就算)。"""
    prev = prev or {}
    out = []
    for m in markets or []:
        mk = str(m.get("market") or "")
        sym = market_symbol(mk)
        if sym is None:
            continue
        ev = m.get("market_event") or {}
        caut = {k: bool((ev.get("caution") or {}).get(k)) for k in CAUTION_KEYS}
        warn = bool(ev.get("warning"))
        p = prev.get(mk)
        if p:
            warn = warn or bool(p.get("warning"))
            pc = p.get("caution") or {}
            caut = {k: caut[k] or bool(pc.get(k)) for k in CAUTION_KEYS}
        out.append({"d": d.isoformat(), "market": mk, "symbol": sym, "warning": warn, "caution": caut,
                    "n_caution": sum(caut.values()), "last_seen_at": now.isoformat()})
    return out


def notice_kind(title: str) -> Optional[str]:
    """纯函数。公告标题 → kind;不关心的(入出金、网络升级、活动)⇒ None。次序有意义:先看更具体的。"""
    t = str(title or "")
    if "유의 종목 지정 해제" in t or "유의종목 지정 해제" in t:
        return "warning_lift"
    if "유의 종목 지정 기간 연장" in t or "유의종목 지정 기간 연장" in t:
        return "warning_extend"
    if "유의 종목 지정" in t or "유의종목 지정" in t or "투자유의" in t:
        return "warning"
    if "유의 촉구" in t:
        return "caution_urge"
    head = re.split(r"\s\((?=[^()]*(?:안내|변경|추가|수정)\))", t)[0]     # 尾部「(… 변경 안내)」之类的更新说明不改类别
    if "거래지원 종료" in head:
        return "delisting"
    if "신규 거래지원" in head or "디지털 자산 추가" in head or re.search(r"상장(?:\s*안내)?$", head) or " 상장" in head:
        return "listing"
    return None


def notice_markets(title: str) -> list[str]:
    """纯函数。标题里的市场(「(KRW, BTC, USDT 마켓)」「KRW, USDT 마켓 디지털 자산 추가」「(ETH/KRW)」)。"""
    t = str(title or "")
    out: list[str] = []
    for grp in re.findall(r"((?:(?:KRW|BTC|USDT|ETH)\s*,\s*)*(?:KRW|BTC|USDT|ETH))\s*마켓", t):
        out += [x.strip() for x in grp.split(",")]
    for _a, b in re.findall(r"\b(" + _CODE + r")/(KRW|BTC|USDT)\b", t):
        out.append(b)
    seen, res = set(), []
    for x in out:
        if x not in seen:
            seen.add(x)
            res.append(x)
    return res


def notice_symbols(title: str) -> list[str]:
    """纯函数。标题里的代币代号:括号里逗号分隔的全大写代码;市场名(KRW / BTC / USDT 后跟「마켓」)不算;「(ETH/KRW)」取 ETH。"""
    t = str(title or "")
    out: list[str] = []
    for grp in re.findall(r"\(([^()]*)\)", t):
        g = grp.strip()
        if g.endswith("마켓"):
            continue
        m = re.fullmatch(r"(" + _CODE + r")/(?:KRW|BTC|USDT)", g)
        if m:
            out.append(m.group(1))
            continue
        parts = [p.strip() for p in g.split(",")]
        if parts and all(re.fullmatch(_CODE, p) for p in parts):
            out += [p for p in parts if not (p in _MARKETS and len(parts) > 1 and all(q in _MARKETS for q in parts))]
    if not out:                                                   # 2017 的「ETH/KRW 상장 …」没有括号
        out += [a for a, _b in re.findall(r"\b(" + _CODE + r")/(KRW|BTC|USDT)\b", t)]
    seen, res = set(), []
    for s in out:
        if s.isdigit() or s in seen:
            continue
        seen.add(s)
        res.append(s)
    return res


def parse_notices(payload: dict) -> list[dict]:
    """纯函数。公告接口返回 → events 行(只留 notice_kind 认得的)。ts = 首次发布时间(KST 带时区 ⇒ 转 UTC)。"""
    from src.data.market.events import event_id
    out = []
    for n in (((payload or {}).get("data") or {}).get("notices") or []):
        title, nid = str(n.get("title") or ""), n.get("id")
        kind = notice_kind(title)
        if kind is None or nid is None:
            continue
        raw = n.get("first_listed_at") or n.get("listed_at")
        try:
            ts = dt.datetime.fromisoformat(str(raw)).astimezone(dt.timezone.utc).isoformat()
        except ValueError:
            continue
        mk = notice_markets(title)
        out.append({"id": event_id("upbit", str(nid)), "ts": ts, "kind": kind, "source": "upbit",
                    "symbols": notice_symbols(title), "title": title[:300], "url": NOTICE_URL.format(id=nid),
                    "payload": {"notice_id": nid, "markets": mk, "krw": ("KRW" in mk) if mk else None,   # 标题没写市场 ⇒ 不知道
                                "category": n.get("category")}})
    return out


# ── I/O ────────────────────────────────────────────────────────────────

async def _candles(client, market: str, to: Optional[str] = None, count: int = 200) -> Optional[list[dict]]:
    import asyncio
    params = {"market": market, "count": count}
    if to:
        params["to"] = to
    for attempt in range(3):
        r = await client.get(f"{UPBIT}/candles/days", params=params)
        if r.status_code == 429:
            await asyncio.sleep(1.5 * (attempt + 1))
            continue
        if r.status_code == 404:
            return []
        if r.status_code != 200:
            return None
        j = r.json()
        return j if isinstance(j, list) else None
    return None


async def _backfill_market(client, market: str, today: dt.date) -> tuple[list[dict], Optional[str]]:
    """一个市场从今天往前翻到上市第一天。→ (行, 错误)。"""
    import asyncio
    rows: list[dict] = []
    to: Optional[str] = None
    for _ in range(40):                                   # 40 × 200 天 ≫ 2017-10 至今
        got = await _candles(client, market, to)
        await asyncio.sleep(CANDLE_SLEEP_S)
        if got is None:
            return rows, f"{market}: 日线请求失败"
        rows += candle_rows(market, got, today)
        if len(got) < 200:
            return rows, None
        oldest = min(str(c["candle_date_time_utc"]) for c in got)
        to = oldest[:19] + "Z"
    return rows, f"{market}: 翻了 40 页还没到底"


async def run_once(now: Optional[dt.datetime] = None) -> dict[str, Any]:
    import asyncio
    import httpx
    from src.api.store import redis_get_key_status, redis_set_key, supabase_upsert_table
    from src.data.style.header import _read_all
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    today = now.date()
    errors: list[str] = []
    out: dict[str, Any] = {}
    async with httpx.AsyncClient(timeout=20, headers={"User-Agent": "CometCloud-korea/1.0", "Accept": "application/json"}) as client:
        # 1. 市场列表 + 标签(当天 OR)
        markets: list[dict] = []
        try:
            r = await client.get(f"{UPBIT}/market/all", params={"isDetails": "true"})
            markets = r.json() if r.status_code == 200 else []
            if r.status_code != 200:
                errors.append(f"market/all: HTTP {r.status_code}")
        except Exception as e:                                            # noqa: BLE001
            errors.append(f"market/all: {type(e).__name__}")
        krw = sorted(m["market"] for m in markets if market_symbol(m.get("market")))
        if markets:
            prev_rows = await _read_all(EVENT_TABLE, {"select": "market,warning,caution", "d": f"eq.{today.isoformat()}",
                                                      "order": "market.asc"})
            ev = event_rows(markets, today, now, {p["market"]: p for p in prev_rows or []})
            if ev and not await supabase_upsert_table(EVENT_TABLE, ev, on_conflict="d,market"):
                errors.append(f"写 {EVENT_TABLE} 失败")
            out["flagged"] = sorted(x["symbol"] for x in ev if x["warning"] or x["n_caution"])
        # 2. 日线:每天一次补最近两天(全部市场);其余时间回填 BF_MARKETS 个市场的全历史
        daily_rows: list[dict] = []
        dkey = DAILY_KEY.format(d=today.isoformat())
        dst, _ = await redis_get_key_status(dkey)
        if krw and not dst:
            n_ok = 0
            for mk in krw:
                got = await _candles(client, mk, count=3)
                await asyncio.sleep(CANDLE_SLEEP_S)
                if got is None:
                    errors.append(f"{mk}: 日线失败")
                    continue
                daily_rows += candle_rows(mk, got, today)
                n_ok += 1
            if n_ok >= 0.9 * len(krw):
                await redis_set_key(dkey, {"at": now.isoformat(), "markets": n_ok}, ttl=3 * 86400)
            out["daily_refresh"] = {"markets": n_ok, "of": len(krw)}
        elif krw:
            st, _ = await redis_get_key_status(BF_KEY)
            done = set((st or {}).get("done") or [])
            todo = [m for m in krw if m not in done][:BF_MARKETS]
            for mk in todo:
                rows, err = await _backfill_market(client, mk, today)
                daily_rows += rows
                if err:
                    errors.append(err)
                else:
                    done.add(mk)
            await redis_set_key(BF_KEY, {"done": sorted(done), "at": now.isoformat()}, ttl=120 * 86400)
            out["backfill"] = {"done": len(done), "of": len(krw), "this_run": len(todo)}
        for i in range(0, len(daily_rows), 1000):
            if not await supabase_upsert_table(DAILY_TABLE, daily_rows[i:i + 1000], on_conflict="market,d"):
                errors.append(f"写 {DAILY_TABLE} 失败")
                break
        out["candle_rows"] = len(daily_rows)
        # 3. 公告:第 1 页 + 回填(Cloudflare 限速 ⇒ 慢翻,遇 1015 当轮停)
        notices: list[dict] = []
        nst, _ = await redis_get_key_status(NOTICE_BF_KEY)
        page = int((nst or {}).get("next_page") or 2)
        ndone = bool((nst or {}).get("done"))
        pages = [1] + ([] if ndone else list(range(page, page + NOTICE_BF_PAGES)))
        total_pages = int((nst or {}).get("total_pages") or 0)
        for p in pages:
            if p > 1 and total_pages and p > total_pages:
                ndone = True
                break
            try:
                r = await client.get(NOTICES, params={"os": "web", "page": p, "per_page": NOTICE_PER_PAGE, "category": "trade"})
                if r.status_code != 200 or not r.text.strip().startswith("{"):
                    errors.append(f"公告 p{p}: HTTP {r.status_code}")
                    break
                j = r.json()
                total_pages = int(((j.get("data") or {}).get("total_pages")) or total_pages or 0)
                notices += parse_notices(j)
                if p > 1:
                    page = p + 1
                    if not ((j.get("data") or {}).get("notices")):
                        ndone = True
                        break
            except Exception as e:                                        # noqa: BLE001
                errors.append(f"公告 p{p}: {type(e).__name__}")
                break
            await asyncio.sleep(NOTICE_SLEEP_S)
        if total_pages and page > total_pages:
            ndone = True
        await redis_set_key(NOTICE_BF_KEY, {"next_page": page, "done": ndone, "total_pages": total_pages,
                                            "at": now.isoformat()}, ttl=120 * 86400)
        notices = list({n["id"]: n for n in notices}.values())
        if notices and not await supabase_upsert_table("events", notices, on_conflict="id"):
            errors.append("写 events 失败")
        kinds: dict[str, int] = {}
        for n in notices:
            kinds[n["kind"]] = kinds.get(n["kind"], 0) + 1
        out["notices"] = {"written": len(notices), "kinds": kinds, "next_page": page, "done": ndone}
    ok = bool(markets) and not any("写 " in e for e in errors)
    flagged = out.get("flagged") or []
    return {"ok": ok, **out, "errors": errors[:20],
            "why": (f"KRW 市场 {len(krw)} 个,带标签 {len(flagged)} 个 · 日线 {out.get('candle_rows', 0)} 行"
                    + (f"(回填 {out['backfill']['done']}/{out['backfill']['of']})" if out.get("backfill") else "")
                    + f" · 公告 {out['notices']['written']} 条 {out['notices']['kinds']}"
                    + (f" · 错 {len(errors)}:{errors[:3]}" if errors else ""))}
