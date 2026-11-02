"""CometCloud 新闻流(Jazz 11-02「最简单也先做成 telegram 我这个 All Things AI 那样的 feed」)—— RSS → 相关性 → 摘要 → 频道。

## 为什么

「All Things AI」那种 feed 的价值不在转发,在**挑选 + 一段人话 + 链接**。我们有别人没有的:每条新闻点到的名字,
我们手里有它今天的 CIS 档位、信号、资金费、深度。所以每条 = 新闻一段(模型写,只许用给它的事实)+「CometCloud 视角」
一行(我们的数据)+ 原文链接。合规语言(compliance-language 技能):只有 STRONG OUTPERFORM / OUTPERFORM / NEUTRAL /
UNDERPERFORM / UNDERWEIGHT;模型吐出买卖词整条丢掉(`llm_narrator._BANNED`)。

## 管道(每 20 分钟一轮,`_news_feed_loop`)

1. 取:`backend.macro_events_scraper._RSS_FEEDS`(The Block / Blockworks / CryptoSlate / Bitcoin Magazine / The Defiant /
   CoinTelegraph / DL News)+ 本文件的补充(CoinDesk / Decrypt / 美联储新闻稿 / SEC 新闻稿)。取不到的源跳过、记名。
2. 去重:链接 sha1 为主键(`feed_items`);同一故事多家报(标题词集 Jaccard ≥ 0.6、48 小时内)只留第一家。
3. 相关:标题 + 摘要里点到我们的名字(CIS 宇宙的币 + 轨道公司 + 宏观关键词)⇒ `hits`;打分 = 名字数 × 2 + 宏观词 + 源权重;
   低于 `MIN_SCORE` 的只入表不发。
4. 摘要:`llm_narrator._chat`(OpenAI 兼容端点,`LLM_BASE_URL`;没配 ⇒ 模板:标题 + 原摘要)。事实 = 新闻正文 + 点到名字的
   今日 CIS 行;模型只写两三句 + 一句视角。
5. 发:chat_id 按 `resolve_feed_chat` 找 —— env `TELEGRAM_FEED_CHAT_ID` > Redis 缓存 > 按群名(默认「Looloomi AI」,
   11-02 Jazz 建的群)从 getUpdates 找一次。**找不到 ⇒ 干跑**:入表、打分、不发(`posted_at` 空)—— 判活不依赖频道。
   每轮最多 `MAX_POSTS_PER_RUN` 条,按分数高的先。

判活:`select count(*), max(fetched_at), count(posted_at) from feed_items where fetched_at > now() - interval '1 day'`。
"""
from __future__ import annotations

import datetime as dt
import hashlib
import html
import os
import re
from typing import Any, Optional

TABLE = "feed_items"
WRITES_TABLES = (TABLE,)
WRITES_COLUMNS = {"feed_items": ("id", "source", "title", "link", "published_at", "fetched_at", "summary_raw", "hits", "score",
                          "post_text", "posted_at", "dup_of")}
LOOP_NAME = "_news_feed_loop"
MIN_SCORE = 3
MAX_POSTS_PER_RUN = 3
DUP_JACCARD = 0.6
DUP_WINDOW_H = 48

EXTRA_FEEDS = [
    {"url": "https://www.coindesk.com/arc/outboundfeeds/rss/", "source": "CoinDesk"},
    {"url": "https://decrypt.co/feed", "source": "Decrypt"},
    {"url": "https://www.federalreserve.gov/feeds/press_all.xml", "source": "Federal Reserve"},
    {"url": "https://www.sec.gov/news/pressreleases.rss", "source": "SEC"},
]
SOURCE_WEIGHT = {"Federal Reserve": 2, "SEC": 2, "The Block": 1, "CoinDesk": 1, "Blockworks": 1, "DL News": 1}

#: 名字 → 在文本里认的别名(小写、整词)。CIS 加密宇宙 + 轨道公司 + 几个我们盯着的发行方 / 场所。
ALIASES: dict[str, tuple[str, ...]] = {
    "BTC": ("bitcoin", "btc"), "ETH": ("ethereum", "ether", "eth"), "SOL": ("solana", "sol"), "BNB": ("bnb", "binance coin"),
    "XRP": ("xrp", "ripple"), "ADA": ("cardano",), "AVAX": ("avalanche",), "DOT": ("polkadot",), "NEAR": ("near protocol",),
    "APT": ("aptos",), "SUI": ("sui",), "HYPE": ("hyperliquid", "hype"), "TIA": ("celestia",), "INJ": ("injective",),
    "LINK": ("chainlink",), "ARB": ("arbitrum",), "OP": ("optimism",), "POL": ("polygon",), "STRK": ("starknet",),
    "AAVE": ("aave",), "UNI": ("uniswap",), "LDO": ("lido",), "PENDLE": ("pendle",), "ONDO": ("ondo",), "SKY": ("sky protocol", "makerdao"),
    "CRCL": ("circle", "usdc"), "USDT": ("tether", "usdt"), "COIN": ("coinbase",), "HOOD": ("robinhood",), "MSTR": ("microstrategy", "strategy inc"),
    "GLXY": ("galaxy digital",), "PYPL": ("paypal", "pyusd"), "BLSH": ("bullish",), "FIGR": ("figure technology",), "GEMI": ("gemini",),
    "XAUT0": ("gold", "xaut"), "SPYX": ("s&p 500", "spy"),
}
MACRO_WORDS = ("fed", "fomc", "rate cut", "rate hike", "powell", "treasury", "stablecoin", "etf", "sec", "hkma", "sfc", "hong kong",
               "liquidation", "liquidations", "funding rate", "exploit", "hack", "unlock", "buyback", "tokenized", "tokenised",
               "bank of japan", "boj", "cpi", "inflation", "genius act", "mica", "perpetual", "perps", "dex")
_WORD = re.compile(r"[a-z0-9&$]+")


def _f(x: Any) -> Optional[float]:
    try:
        return None if x is None else float(x)
    except (TypeError, ValueError):
        return None


def item_id(link: str) -> str:
    return hashlib.sha1(link.strip().lower().encode("utf-8")).hexdigest()[:24]


def tokens(title: str) -> set[str]:
    stop = {"the", "a", "an", "of", "to", "in", "on", "for", "and", "as", "is", "at", "by", "with", "from", "its", "it", "s"}
    return {w for w in _WORD.findall(title.lower()) if w not in stop and len(w) > 1}


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def relevance(title: str, summary: str) -> tuple[list[str], list[str]]:
    """纯函数。→ (点到的名字, 命中的宏观词)。整词匹配,别名不分大小写。"""
    text = " " + re.sub(r"[^a-z0-9&$ ]", " ", (title + " " + summary).lower()) + " "
    hits = [sym for sym, als in ALIASES.items() if any(f" {a} " in text for a in als)]
    macro = [w for w in MACRO_WORDS if f" {w} " in text]
    return hits, macro


def score(hits: list[str], macro: list[str], source: str) -> int:
    return len(hits) * 2 + min(len(macro), 3) + SOURCE_WEIGHT.get(source, 0)


def dedupe(new: list[dict], recent: list[dict]) -> list[dict]:
    """纯函数。同一故事多家报只留先到的:与 48 小时内已有标题 Jaccard ≥ 0.6 ⇒ 标 dup_of。new 内部也互相比。"""
    seen: list[tuple[set[str], str]] = [(tokens(r.get("title") or ""), r["id"]) for r in recent]
    out = []
    for it in new:
        t = tokens(it["title"])
        dup = next((rid for rt, rid in seen if jaccard(t, rt) >= DUP_JACCARD), None)
        out.append({**it, "dup_of": dup})
        if dup is None:
            seen.append((t, it["id"]))
    return out


def template_post(it: dict, facts: dict[str, dict]) -> str:
    """没有模型时的帖子:标题加粗 + 原摘要 + 视角行 + 链接。HTML parse_mode,已转义。"""
    body = html.escape((it.get("summary_raw") or "").strip())
    lines = [f"<b>{html.escape(it['title'].strip())}</b>", ""]
    if body:
        lines += [body, ""]
    view = view_line(facts)
    if view:
        lines += [view, ""]
    lines.append(f'{html.escape(it["source"])} · <a href="{html.escape(it["link"])}">原文</a>')
    return "\n".join(lines)


def view_line(facts: dict[str, dict]) -> str:
    """「CometCloud 视角」:点到的名字今天的档位 / 信号(合规枚举原样)。没有事实 ⇒ 空。"""
    parts = [f"{s} {r.get('grade')} · {r.get('signal')}" for s, r in facts.items() if r.get("grade") and r.get("signal")]
    return html.escape("CometCloud 视角 · " + " | ".join(parts)) if parts else ""


async def llm_post(it: dict, facts: dict[str, dict]) -> Optional[str]:
    """模型写两三句 + 视角一句;只许用给它的事实;含买卖词或空 ⇒ None(回落模板)。"""
    from src.data.narrative.llm_narrator import _BANNED, _chat, configured
    if not configured():
        return None
    fact_lines = [f"- {s}: CIS grade {r.get('grade')}, signal {r.get('signal')}" for s, r in facts.items()]
    msgs = [
        {"role": "system", "content": (
            "You write one short post for a professional crypto/macro news channel run by a HK-based buy-side desk. "
            "2-3 plain sentences: what happened and why it matters to allocators. Then ONE sentence starting with "
            "'CometCloud view:' that uses ONLY the facts given (grades/signals verbatim; if no facts, skip that sentence). "
            "No bullet points, no markdown, no emoji, no hype. Never write buy, sell, accumulate, avoid, reduce, invest, "
            "allocate, price target, or any instruction to act. Never invent numbers. Output the text only.")},
        {"role": "user", "content": f"SOURCE: {it['source']}\nTITLE: {it['title']}\nBODY: {it.get('summary_raw') or ''}\n"
                                    f"FACTS:\n" + ("\n".join(fact_lines) or "- none")},
    ]
    try:
        text = await _chat(msgs, temperature=0.3)
    except Exception:                                                     # noqa: BLE001 —— 模型挂了用模板
        return None
    text = (text or "").strip()
    if not text or len(text) > 1200 or _BANNED.search(text):
        return None
    return (f"<b>{html.escape(it['title'].strip())}</b>\n\n{html.escape(text)}\n\n"
            f'{html.escape(it["source"])} · <a href="{html.escape(it["link"])}">原文</a>')


async def fetch_items(now: dt.datetime) -> tuple[list[dict], list[str]]:
    """取所有源 → 标准化条目;→ (条目, 取不到的源)。"""
    import httpx
    from src.backend.macro_events_scraper import _RSS_FEEDS, _fetch_rss
    feeds = list(_RSS_FEEDS) + EXTRA_FEEDS
    items, failed = [], []
    async with httpx.AsyncClient(headers={"User-Agent": "CometCloud-feed/1.0"}) as client:
        for feed in feeds:
            try:
                evs = await _fetch_rss(feed, client)
            except Exception:                                             # noqa: BLE001
                evs = []
            if not evs:
                failed.append(feed["source"])
                continue
            for e in evs:
                link = str(e.get("url") or e.get("link") or "").strip()
                title = str(e.get("title") or "").strip()
                if not link or not title:
                    continue
                items.append({"id": item_id(link), "source": feed["source"], "title": title[:300], "link": link[:500],
                              "published_at": e.get("published_at") or None,
                              "fetched_at": now.isoformat(), "summary_raw": str(e.get("summary") or e.get("description") or "")[:600]})
    return items, failed


CHAT_KEY = "feed:chat_id"
DEFAULT_CHAT_TITLE = "Looloomi AI"


async def resolve_feed_chat() -> tuple[str, str]:
    """→ (chat_id, 来源)。优先 env `TELEGRAM_FEED_CHAT_ID`;否则 Redis 缓存;否则按群名(`TELEGRAM_FEED_CHAT_TITLE`,
    默认「Looloomi AI」)从 getUpdates 找一次并缓存 30 天(11-02 Jazz 建群加机器人,chat_id 不用他去查)。找不到 ⇒ ("", why)。"""
    from src.api.notify import telegram_find_chat
    from src.api.store import redis_get_key_status, redis_set_key
    env = os.environ.get("TELEGRAM_FEED_CHAT_ID", "").strip()
    if env:
        return env, "env"
    cached, _st = await redis_get_key_status(CHAT_KEY)
    if cached and cached.get("id"):
        return str(cached["id"]), f"redis({cached.get('title')})"
    title = os.environ.get("TELEGRAM_FEED_CHAT_TITLE", DEFAULT_CHAT_TITLE)
    found = await telegram_find_chat(title)
    if found:
        await redis_set_key(CHAT_KEY, found, ttl=30 * 86400)
        return found["id"], f"getUpdates({found.get('title')}, {found.get('type')})"
    return "", f"没有 TELEGRAM_FEED_CHAT_ID,getUpdates 里也没有叫「{title}」的群(机器人加进群后 24 小时内会出现;或直接填 env)"


async def run_once(now: Optional[dt.datetime] = None) -> dict[str, Any]:
    from src.api.notify import notify_telegram, telegram_configured
    from src.api.store import supabase_upsert_table
    from src.data.style.header import _read_all
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    items, failed = await fetch_items(now)
    if not items:
        return {"ok": False, "why": f"所有源都取不到:{failed}"}
    since = (now - dt.timedelta(hours=DUP_WINDOW_H)).isoformat()
    recent = await _read_all(TABLE, {"select": "id,title,posted_at", "fetched_at": f"gte.{since}"})
    have = {r["id"] for r in recent}
    new = [it for it in {it["id"]: it for it in items}.values() if it["id"] not in have]
    if not new:
        return {"ok": True, "status": "skipped", "new": 0, "failed_sources": failed, "why": "没有新条目"}
    new = dedupe(new, recent)
    for it in new:
        hits, macro = relevance(it["title"], it["summary_raw"])
        it["hits"] = hits
        it["score"] = score(hits, macro, it["source"]) if it["dup_of"] is None else 0
    cand = sorted([it for it in new if it["score"] >= MIN_SCORE], key=lambda x: -x["score"])[:MAX_POSTS_PER_RUN]
    chat, chat_why = await resolve_feed_chat()
    syms = sorted({s for it in cand for s in it["hits"]})
    facts_all: dict[str, dict] = {}
    if syms:
        rows = await _read_all("cis_official_daily", {"select": "symbol,d,grade,signal", "symbol": f"in.({','.join(syms)})",
                                                      "order": "d.desc", "limit": str(len(syms) * 3)})
        for r in rows:
            facts_all.setdefault(r["symbol"], r)
    posted = 0
    for it in cand:
        facts = {s: facts_all[s] for s in it["hits"] if s in facts_all}
        it["post_text"] = (await llm_post(it, facts)) or template_post(it, facts)
        if chat and telegram_configured():
            if await notify_telegram(it["post_text"], chat_id=chat, parse_mode="HTML", disable_preview=False):
                it["posted_at"] = now.isoformat()
                posted += 1
    rows = [{k: it.get(k) for k in WRITES_COLUMNS[TABLE]} for it in new]
    w = await supabase_upsert_table(TABLE, rows, on_conflict="id")
    if not w:
        return {"ok": False, "why": f"写 {TABLE} 失败:{(getattr(w, 'why', '') or '')[:200]}"}
    return {"ok": True, "new": len(new), "candidates": len(cand), "posted": posted, "dry": not chat, "chat": chat_why,
            "failed_sources": failed,
            "why": f"新 {len(new)} 条,候选 {len(cand)},发 {posted}" + (f"(干跑:{chat_why})" if not chat else f"(→ {chat_why})")}
