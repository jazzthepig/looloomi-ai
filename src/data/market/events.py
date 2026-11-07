"""事件库(11-02,`docs/UPGRADE_PATHS.md` B2):把「发生了什么」从各处的文件和记忆里拿出来,变成一张能查的表。

## 为什么

情景分析从一张能查的表开始,不从「我记得」开始。Jazz 11-02:密集营销时是高位;「开闸」(上所)之后往往是跌
(UNI −27%、PUMP −67%)。这些都是**事件**,而我们没有一张按时间、按实体的事件表 —— 新闻在 feed_items、上币在交易所公告页、
解锁在别人的 API 后面。这里先立表、接三个免费的写入端;之后 T-226 的钱包流出事件、宏观日历、CIS 换档都往这里写。

## 表 `events`

`id`(写入端 + 外部 id 的 sha1)· `ts`(事件时间 UTC)· `kind`(news / listing / delisting / perp_listing)· `source`
(the_block / binance / hyperliquid …)· `symbols`(jsonb 列表,我们的符号)· `title` · `url` · `payload`(原始字段)· `recorded_at`。
只追加语义(写入端按 id upsert,不删)。lane 可读。

## 写入端(`_events_loop`,每小时)

1. **新闻** ← `feed_items`:点到名字的(hits 非空)每条一个 news 事件,ts = 发布时间(没有就抓取时间)。
2. **Binance 公告**:公开的 CMS 接口(New Cryptocurrency Listing = catalog 48、Delisting = 161);标题里解析代币 ——
   「Will List X (XXX)」「Will Delist A, B, C」「Launch USDⓈ-Margined XXXUSDT Perpetual」。解析不出代币的只记标题,symbols 空。
3. **Hyperliquid 现货新代币**:`spotMeta.tokens` 里**上一轮没见过**的名字 ⇒ listing(source hyperliquid);第一轮只登记、不当事件
   (否则 300 个老代币全成「今天上市」)。

判活:`select kind, source, count(*), max(ts) from events group by 1,2`。
"""
from __future__ import annotations

import datetime as dt
import hashlib
import re
from typing import Any, Iterable, Optional

TABLE = "events"
WRITES_TABLES = (TABLE,)
WRITES_COLUMNS = {"events": ("id", "ts", "kind", "source", "symbols", "title", "url", "payload")}
LOOP_NAME = "_events_loop"
BINANCE_CMS = "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query"
BINANCE_CATALOGS = {48: "listing", 161: "delisting", 49: "notice"}
#: 11-07:catalog 49(Latest Binance News,4,484 篇)里只留「监控标签」公告 —— 下架的前一步(S-753);其余新闻不进事件表
BINANCE_ARTICLE = "https://www.binance.com/en/support/announcement/{code}"
HL_SEEN_KEY = "events:hl_spot_tokens_seen"
BF_KEY = "events:binance_backfill:{cat}"
PAGE = 20
BACKFILL_PAGES = 10            # 每轮往后翻 10 页(200 条);2,200 条上币公告约 11 轮翻完
_SYM = r"[A-Z0-9]{2,10}"
_PAREN = re.compile(r"\((" + _SYM + r")\)")
_LIST_AFTER = re.compile(r"(?:Will (?:List|Delist|Remove)|Removal of|Adds?)\s+(.+?)(?:\s+on\s+\d{4}|\s*\(\d{4}| - \d{4}|$)", re.IGNORECASE)
_PERP = re.compile(r"\b(" + _SYM + r")USDT\b")
#: 11-06(lane-b T-262 查出 perp_listing 818 条里 453 条 symbols 为空):Binance 标题的另外几种写法 ——
#: 「USDⓈ-M OXT Perpetual」「UNI USDT-Margined Perpetual」「XMR/USDT Perpetual」「DOGSUSD COIN-M」「ZK and ZRO Perpetual」、
#: 「COCOS, IQ, PHA & TWT Enabled on …Margin」「Binance Margin to Delist ANC and MIR on …」「Add WTC(Walton) on August 27」。
_SYMLIST = r"(" + _SYM + r"(?:\s*(?:,|&|and)\s*" + _SYM + r")*)"
_PERP_AFTER_M = re.compile(r"(?:USDⓈ-M|USDⓈ-Margined|USDC-Margined|USDT-Margined|Coin-Margined|COIN-Margined|COIN-M)\s+"
                           + _SYMLIST + r"\s+Perpetual")
_PERP_BEFORE_M = re.compile(r"\b(" + _SYM + r")\s+(?:USDT|USDC|USDⓈ|Coin|COIN)-(?:Margined|M)\b")
_PERP_SLASH = re.compile(r"\b(" + _SYM + r")/USD[TC]?\b")
_PERP_COINM = re.compile(r"\b(" + _SYM + r")USD\s+(?:COIN|Coin)-M")
_ENABLED = re.compile(r"^" + _SYMLIST + r"\s+(?:Enabled|Added)\b")
_TO_DELIST = re.compile(r"\bto (?:Delist|List|Remove)\s+" + _SYMLIST + r"\s+(?:on|from)\b")
_ADD_WORD = re.compile(r"\bAdds?\s+(" + _SYM + r")\s*\(")
_NOISE = {"USDT", "USDC", "USD", "BTC", "ETH", "BNB", "MARGIN", "SPOT", "FUTURES", "PERPETUAL", "CONTRACT", "ALPHA", "AND",
          "USDⓈ", "TRADING", "PAIRS", "MULTIPLE", "TRADFI", "LOAN"}


def event_id(source: str, external: str) -> str:
    return hashlib.sha1(f"{source}:{external}".encode("utf-8")).hexdigest()[:24]


def _ts_ms(ms: Any) -> Optional[str]:
    try:
        return dt.datetime.fromtimestamp(int(ms) / 1000, tz=dt.timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def symbols_from_title(title: str) -> list[str]:
    """纯函数。Binance 公告标题 → 代币列表(大写,去噪;解析不出 ⇒ [])。"""
    t = title or ""
    out: list[str] = []
    out += _ADD_WORD.findall(t)                                         # 「Add WTC(Walton)」—— 括号里是名字不是代码
    out += _PAREN.findall(t)
    if "Perpetual" in t or "Futures" in t:
        out += _PERP.findall(t)
        for grp in _PERP_AFTER_M.findall(t):
            out += re.split(r"\s*(?:,|&|\band\b)\s*", grp)
        out += _PERP_BEFORE_M.findall(t) + _PERP_SLASH.findall(t) + _PERP_COINM.findall(t)
    for rx in (_ENABLED, _TO_DELIST):
        for grp in rx.findall(t):
            out += re.split(r"\s*(?:,|&|\band\b)\s*", grp)
    m = _LIST_AFTER.search(t)
    if m and not out:
        chunk = re.sub(r"\(.*?\)", "", m.group(1))
        for w in re.split(r"[,&/]|\band\b", chunk):
            w = w.strip().strip(".")
            if re.fullmatch(_SYM, w):
                out.append(w)
    seen, res = set(), []
    for s in out:
        s = s.upper()
        if s in _NOISE or s in seen or s.isdigit() or (s.endswith("USD") and s[:-3] in out):   # 「DOGSUSD COIN-M」⇒ DOGS
            continue
        seen.add(s)
        res.append(s)
    return res


def binance_kind(title: str, catalog_kind: str) -> str:
    t = (title or "").lower()
    if "futures" in t or "perpetual" in t:
        return "perp_listing" if catalog_kind == "listing" else "perp_delisting"
    return catalog_kind


def binance_scope(title: str) -> str:
    """alpha / margin / futures / spot —— Alpha 上币与现货上币不是一回事(回测时要分)。"""
    t = (title or "").lower()
    for k in ("alpha", "margin", "futures"):
        if k in t:
            return k
    return "spot"


_MON_TAG = re.compile(r"monitoring\s+tag", re.IGNORECASE)
_MON_STOP = {"ON", "TO", "AND", "THE", "FOR", "OF"}


def monitoring_tag(title: str) -> tuple[Optional[str], list[str]]:
    """纯函数。监控标签公告 → (kind, 代币);不是 ⇒ (None, [])。
    标题写法各异(on X, Y and Z / to Include X & Y / on Tokens: X, Y),通用解析器会漏 —— 这里只取「Monitoring Tag」之后、
    日期之外的全大写代号。"""
    t = str(title or "")
    m = _MON_TAG.search(t)
    if not m:
        return None, []
    kind = "monitoring_tag_removed" if re.search(r"\bremov", t, re.IGNORECASE) else "monitoring_tag"
    seg = re.sub(r"\(?\d{4}-\d{2}-\d{2}\)?", " ", t[m.end():])
    syms, seen = [], set()
    for s in re.findall(r"\b[A-Z0-9]{2,12}\b", seg):
        if s.isdigit() or s in _MON_STOP or s in seen:
            continue
        seen.add(s)
        syms.append(s)
    return kind, syms


def n_articles(payload: dict) -> int:
    """纯函数。CMS 返回里的文章数(判断翻到底用它,不用解析后的行数)。"""
    return sum(len(c.get("articles") or []) for c in ((payload or {}).get("data") or {}).get("catalogs") or [])


def parse_binance(payload: dict, catalog_id: int) -> list[dict]:
    """纯函数。CMS 返回 → 事件行。catalog 49 只留监控标签公告。"""
    kind = BINANCE_CATALOGS.get(catalog_id, "notice")
    out = []
    for cat in ((payload or {}).get("data") or {}).get("catalogs") or []:
        for a in cat.get("articles") or []:
            code, title = str(a.get("code") or ""), str(a.get("title") or "")
            if not code or not title:
                continue
            if kind == "notice":
                k, syms = monitoring_tag(title)
                if k is None:
                    continue
            else:
                k, syms = binance_kind(title, kind), symbols_from_title(title)
            out.append({"id": event_id("binance", code), "ts": _ts_ms(a.get("releaseDate")) or dt.datetime.now(dt.timezone.utc).isoformat(),
                        "kind": k, "source": "binance", "symbols": syms,
                        "title": title[:300], "url": BINANCE_ARTICLE.format(code=code),
                        "payload": {"article_id": a.get("id"), "catalog": catalog_id, "scope": binance_scope(title)}})
    return out


def hl_new_tokens(meta: dict, seen: Optional[set[str]], now: dt.datetime) -> tuple[list[dict], set[str]]:
    """纯函数。spotMeta.tokens 里上一轮没见过的 ⇒ listing 事件;seen 为 None(第一轮)⇒ 只登记不发。→ (事件, 新的 seen)。"""
    names = {str(t.get("name") or "") for t in (meta or {}).get("tokens") or [] if t.get("name")}
    if seen is None:
        return [], names
    new = sorted(names - seen)
    evs = [{"id": event_id("hyperliquid", f"spot:{n}"), "ts": now.isoformat(), "kind": "listing", "source": "hyperliquid",
            "symbols": [n], "title": f"Hyperliquid spot lists {n}", "url": "https://app.hyperliquid.xyz/trade",
            "payload": {"token": n}} for n in new]
    return evs, names


def news_events(items: Iterable[dict]) -> list[dict]:
    """纯函数。feed_items(有 hits 的)→ news 事件。"""
    out = []
    for it in items:
        hits = it.get("hits") or []
        if not hits or not it.get("id"):
            continue
        out.append({"id": event_id("news", it["id"]), "ts": it.get("published_at") or it.get("fetched_at"), "kind": "news",
                    "source": str(it.get("source") or "").lower().replace(" ", "_"), "symbols": list(hits),
                    "title": str(it.get("title") or "")[:300], "url": it.get("link"),
                    "payload": {"feed_item": it["id"], "score": it.get("score")}})
    return out


async def run_once(now: Optional[dt.datetime] = None) -> dict[str, Any]:
    import asyncio
    import httpx
    from src.api.store import redis_get_key_status, redis_set_key, supabase_upsert_table
    from src.data.style.header import _read_all
    from src.data.venues.hl_spot import HlSpotClient
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    rows: list[dict] = []
    errors: list[str] = []
    # 1. 新闻
    since = (now - dt.timedelta(hours=36)).isoformat()
    try:
        items = await _read_all("feed_items", {"select": "id,source,title,link,published_at,fetched_at,hits,score",
                                               "fetched_at": f"gte.{since}"})
        rows += news_events(items)
    except Exception as e:                                                # noqa: BLE001
        errors.append(f"feed_items: {type(e).__name__}")
    # 2. Binance 公告:每轮第 1 页(最新)+ 历史回填(每轮往后翻 BACKFILL_PAGES 页,翻完为止 —— 上币公告 2,200+ 条、2017 起,
    #    是「开闸」回测的整段历史;Redis 记翻到哪一页)
    backfill: dict[str, Any] = {}
    async with httpx.AsyncClient(timeout=20, headers={"User-Agent": "CometCloud-events/1.0"}) as client:
        for cat in BINANCE_CATALOGS:
            try:
                r = await client.get(BINANCE_CMS, params={"type": 1, "pageNo": 1, "pageSize": PAGE, "catalogId": cat})
                if r.status_code != 200:
                    errors.append(f"binance {cat}: HTTP {r.status_code}")
                    continue
                j = r.json()
                rows += parse_binance(j, cat)
                total = int((((j.get("data") or {}).get("catalogs") or [{}])[0].get("total")) or 0)
                key = BF_KEY.format(cat=cat) + (":v2" if BINANCE_CATALOGS[cat] == "notice" else "")   # 11-07 第一轮误标 done
                st, _s = await redis_get_key_status(key)
                page = int((st or {}).get("next_page") or 2)
                done = bool((st or {}).get("done"))
                fetched = 0
                while not done and fetched < BACKFILL_PAGES and (page - 1) * PAGE < total:
                    rr = await client.get(BINANCE_CMS, params={"type": 1, "pageNo": page, "pageSize": PAGE, "catalogId": cat})
                    if rr.status_code != 200:
                        errors.append(f"binance {cat} p{page}: HTTP {rr.status_code}")
                        break
                    jj = rr.json()
                    got = parse_binance(jj, cat)
                    rows += got
                    fetched += 1
                    page += 1
                    if not n_articles(jj):                  # 11-07:看文章数,不看解析出的行数 —— catalog 49 只留监控标签,
                        done = True                          # 一页没有标签不等于翻到底(第一轮就因此在第 2 页停了)
                    await asyncio.sleep(0.5)
                if (page - 1) * PAGE >= total:
                    done = True
                await redis_set_key(key, {"next_page": page, "done": done, "total": total, "at": now.isoformat()}, ttl=90 * 86400)
                backfill[str(cat)] = {"next_page": page, "done": done, "total": total}
            except Exception as e:                                        # noqa: BLE001
                errors.append(f"binance {cat}: {type(e).__name__}")
    # 3. HL 现货新代币
    try:
        meta = await asyncio.to_thread(HlSpotClient().spot_meta)
        prev, _st = await redis_get_key_status(HL_SEEN_KEY)
        seen = set((prev or {}).get("names") or []) if prev else None
        evs, names = hl_new_tokens(meta, seen, now)
        rows += evs
        await redis_set_key(HL_SEEN_KEY, {"names": sorted(names), "at": now.isoformat()}, ttl=30 * 86400)
    except Exception as e:                                                # noqa: BLE001
        errors.append(f"hyperliquid: {type(e).__name__}")
    rows = list({r["id"]: r for r in rows if r.get("ts")}.values())
    written = 0
    if rows:
        w = await supabase_upsert_table(TABLE, rows, on_conflict="id")
        if not w:
            return {"ok": False, "why": f"写 {TABLE} 失败:{(getattr(w, 'why', '') or '')[:200]}", "errors": errors}
        written = len(rows)
    kinds: dict[str, int] = {}
    for r in rows:
        kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
    repair_error = None
    try:
        repaired = await repair_symbols(_read_all, supabase_upsert_table)
    except Exception as e:                                                # noqa: BLE001 —— 补代币是附带的,不影响本轮判活
        repaired, repair_error = 0, f"{type(e).__name__}: {str(e)[:120]}"
    return {"ok": not errors or written > 0, "written": written, "kinds": kinds, "errors": errors, "backfill": backfill,
            "repaired": repaired, "repair_error": repair_error,
            "why": f"写 {written} 条 {kinds}" + (f";回填 {backfill}" if backfill else "") + (f";补代币 {repaired} 条" if repaired else "")
                   + (f";错 {errors}" if errors else "")}


REPAIR_BATCH = 1000


async def repair_symbols(read, upsert) -> int:
    """已入库、symbols 为空的 Binance 公告用新解析器重读标题(11-06:lane-b T-262 查出 perp_listing 818 条里 453 条为空)。
    只补能解析出代币的;解析不出的(「Notice of Removal of Spot Trading Pairs - 日期」这类,代币在正文里)原样留空。幂等。"""
    rows = await read(TABLE, {"select": "id,ts,kind,source,symbols,title,url,payload", "source": "eq.binance",
                              "symbols": "eq.[]", "order": "ts.asc", "limit": str(REPAIR_BATCH)})
    fixed = []
    for r in rows[:REPAIR_BATCH]:
        syms = symbols_from_title(r.get("title") or "")
        if syms:
            fixed.append({**{k: r.get(k) for k in WRITES_COLUMNS[TABLE]}, "symbols": syms})
    if fixed and not await upsert(TABLE, fixed, on_conflict="id"):
        raise RuntimeError("repair upsert failed")
    return len(fixed)
