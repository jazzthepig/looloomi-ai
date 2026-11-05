"""新闻流(11-02,Jazz「先做成 All Things AI 那样的 feed」):相关性整词匹配、同一故事多家报只留先到的、
没模型时模板帖子合规、干跑不发、模型吐买卖词整条丢掉。"""
from __future__ import annotations

import asyncio
import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.ops import news_feed as nf  # noqa: E402


def test_relevance_matches_whole_words_and_scores_sources():
    hits, macro = nf.relevance("Hyperliquid liquidations top $1B as Bitcoin slides; SEC weighs stablecoin rules", "")
    assert hits == ["BTC", "HYPE"] and "liquidations" in macro and "sec" in macro
    assert nf.relevance("Solar panel maker raises Series A", "")[0] == [], "sol 不能从 solar 里匹出来"
    assert nf.score(["BTC", "HYPE"], ["sec", "stablecoin", "liquidations", "etf"], "SEC") == 2 * 2 + 3 + 2
    assert nf.score([], [], "Decrypt") < nf.MIN_SCORE, "没点到名字也没宏观词的不发"


def test_same_story_from_a_second_outlet_is_marked_dup():
    a = {"id": "a", "title": "Circle files for IPO on NYSE, seeks $5B valuation", "source": "The Block"}
    b = {"id": "b", "title": "Circle files IPO on NYSE seeking $5B valuation", "source": "CoinDesk"}
    c = {"id": "c", "title": "Fed holds rates, signals one cut this year", "source": "Federal Reserve"}
    out = nf.dedupe([a, b, c], recent=[{"id": "old", "title": "Fed holds rates steady, signals one cut this year"}])
    assert [o["dup_of"] for o in out] == [None, "a", "old"]


def test_template_post_is_html_escaped_and_uses_the_compliance_enum_only():
    it = {"title": "Tether & Circle <rivalry> heats up", "summary_raw": "USDT supply hits record", "source": "DL News",
          "link": "https://example.com/a?b=1&c=2"}
    txt = nf.template_post(it, {"CRCL": {"grade": "C", "signal": "NEUTRAL"}, "USDT": {"grade": None}})
    assert txt.startswith("<b>Tether &amp; Circle &lt;rivalry&gt; heats up</b>")
    assert "CometCloud 视角 · CRCL C · NEUTRAL" in txt and 'href="https://example.com/a?b=1&amp;c=2"' in txt
    import re
    assert not re.search(r"\b(buy|sell|accumulate|avoid|reduce)\b", txt, re.I)


def test_llm_post_drops_banned_words_and_falls_back(monkeypatch):
    from src.data.narrative import llm_narrator as ln
    monkeypatch.setattr(ln, "configured", lambda: True)

    async def chat_bad(msgs, temperature=0.4, max_tokens=1400):
        return "Great news, investors should buy BTC now."

    async def chat_ok(msgs, temperature=0.4, max_tokens=1400):
        return "Circle filed. It matters for stablecoin rails. CometCloud view: CRCL C, NEUTRAL."
    it = {"title": "Circle files", "summary_raw": "", "source": "The Block", "link": "https://x/y"}
    monkeypatch.setattr(ln, "_chat", chat_bad)
    assert asyncio.run(nf.llm_post(it, {})) is None
    monkeypatch.setattr(ln, "_chat", chat_ok)
    out = asyncio.run(nf.llm_post(it, {"CRCL": {"grade": "C", "signal": "NEUTRAL"}}))
    assert out and out.startswith("<b>Circle files</b>") and "CometCloud view" in out


def test_run_once_is_dry_without_channel_and_writes_every_new_item(monkeypatch):
    import src.api.notify as notify
    import src.api.store as store
    import src.data.style.header as hdr
    sent, up = [], []
    now = dt.datetime(2026, 11, 2, 12, 0, tzinfo=dt.timezone.utc)

    async def fetch(_now):
        return [{"id": "n1", "source": "The Block", "title": "Hyperliquid volumes hit record as HYPE rallies", "link": "https://t/1",
                 "published_at": None, "fetched_at": _now.isoformat(), "summary_raw": "perps dex"},
                {"id": "n2", "source": "Decrypt", "title": "Celebrity launches memecoin", "link": "https://t/2",
                 "published_at": None, "fetched_at": _now.isoformat(), "summary_raw": ""},
                {"id": "old", "source": "Decrypt", "title": "already here", "link": "https://t/old",
                 "published_at": None, "fetched_at": _now.isoformat(), "summary_raw": ""}], ["SEC"]

    async def read_all(t, params):
        if t == nf.TABLE:
            return [{"id": "old", "title": "already here", "posted_at": None}]
        if t == "cis_official_daily":
            return [{"symbol": "HYPE", "d": "2026-11-01", "grade": "B", "signal": "STRONG OUTPERFORM"}]
        raise AssertionError(t)

    async def ups(t, rows, on_conflict):
        up.extend(rows)
        return True

    async def tg(text, chat_id=None, parse_mode=None, disable_preview=True):
        sent.append((chat_id, text))
        return True
    monkeypatch.setattr(nf, "fetch_items", fetch)
    monkeypatch.setattr(hdr, "_read_all", read_all)
    monkeypatch.setattr(store, "supabase_upsert_table", ups)
    monkeypatch.setattr(notify, "notify_telegram", tg)
    monkeypatch.setattr(notify, "telegram_configured", lambda: True)
    monkeypatch.delenv("TELEGRAM_FEED_CHAT_ID", raising=False)
    found = {}

    async def find(title):
        return found.get(title)

    async def rget(key):
        return None, "miss"

    async def rset(key, data, ttl=7200):
        return True
    monkeypatch.setattr(notify, "telegram_find_chat", find)
    monkeypatch.setattr(store, "redis_get_key_status", rget)
    monkeypatch.setattr(store, "redis_set_key", rset)
    r = asyncio.run(nf.run_once(now))
    assert r["ok"] and r["dry"] and r["new"] == 2 and r["candidates"] == 1 and r["posted"] == 0 and sent == []
    assert {x["id"] for x in up} == {"n1", "n2"} and next(x for x in up if x["id"] == "n1")["hits"] == ["HYPE"]
    assert "STRONG OUTPERFORM" in next(x for x in up if x["id"] == "n1")["post_text"]
    assert r["failed_sources"] == ["SEC"]
    up.clear()
    monkeypatch.setenv("TELEGRAM_FEED_CHAT_ID", "-100123")
    r = asyncio.run(nf.run_once(now))
    assert r["posted"] == 1 and sent[0][0] == "-100123" and "<b>Hyperliquid volumes" in sent[0][1]
    assert next(x for x in up if x["id"] == "n1")["posted_at"] == now.isoformat()
    # 没 env 时按群名从 getUpdates 找(11-02 Jazz 建的「Looloomi AI」群)
    monkeypatch.delenv("TELEGRAM_FEED_CHAT_ID", raising=False)
    found["Looloomi AI"] = {"id": "-4001", "title": "Looloomi AI", "type": "group"}
    sent.clear()
    r = asyncio.run(nf.run_once(now))
    assert r["posted"] == 1 and sent[0][0] == "-4001" and "getUpdates" in r["chat"]


def test_loop_is_registered_and_table_is_in_the_migration():
    src = (ROOT / "src/api/main.py").read_text(encoding="utf-8")
    assert "_news_feed_loop" in src and "_start_news_feed_loop" in src
    mig = (ROOT / "migrations/2026-11-02_feed_items.sql").read_text(encoding="utf-8")
    for col in nf.WRITES_COLUMNS[nf.TABLE]:
        assert col in mig, col


def test_third_party_price_targets_are_not_reposted_and_boilerplate_is_stripped():
    """11-02 第一批真帖:Coinbase「price target slashed 53%」、Bitwise「fair value $197,000」—— 别人的目标价转一下也是我们在说。"""
    assert nf.unpostable("Coinbase downgraded; price target slashed 53%", "") == "含「price target」"
    assert nf.unpostable("Bitcoin's \"Fair Value\" of $197,000", "") == "含「fair value」"
    assert nf.unpostable("Strategy resumes Bitcoin purchases with $66M", "") is None, "purchase 是新闻事实,不是建议"
    assert nf.clean_summary("Andre details BTC as a liquidity canary. This post Bitwise: X first appeared on Bitcoin Magazine.") \
        == "Andre details BTC as a liquidity canary."
    assert nf.clean_summary("Plain body.") == "Plain body."


def test_narrator_status_never_carries_the_key():
    """11-03:httpx 把整段 Authorization 头写进异常,状态口把它原样回给了 curl(密钥进了聊天记录)。"""
    from src.data.narrative import llm_narrator as ln
    ln._note("LocalProtocolError: Illegal header value b'Bearer sk-cp-opaiJT32bm7mWkn73v5YVH5tjtqFUZsK \\n  aJ7jTMe0EFp'")
    assert "opaiJT32" not in ln.LAST_ERROR["why"] and "aJ7jTMe0" not in ln.LAST_ERROR["why"] and "Illegal header value" in ln.LAST_ERROR["why"]
    ln._note("HTTP 401: invalid api key sk-cp-abcdefghijklmnopqrstuvwxyz")
    assert "abcdefghij" not in ln.LAST_ERROR["why"]
    src = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert "mcp[cli]>=1.6.0,<2" in src, "mcp 2.x 改名 FastMCP,不钉死 /mcp 整个不挂"


def test_configured_but_failing_llm_is_reported_as_degraded(monkeypatch):
    """11-03:key 带换行 / URL 少 /v1 时帖子悄悄回落模板,库里看不出 —— 配了模型却没用上 ⇒ 这一轮记 degraded + 原因。"""
    from src.data.narrative import llm_narrator as ln
    import src.api.notify as notify
    import src.api.store as store
    import src.data.style.header as hdr
    now = dt.datetime(2026, 11, 3, 3, 0, tzinfo=dt.timezone.utc)

    async def fetch(_now):
        return [{"id": "n9", "source": "The Block", "title": "Hyperliquid volumes hit record", "link": "https://t/9",
                 "published_at": None, "fetched_at": _now.isoformat(), "summary_raw": "x"}], []

    async def read_all(t, params):
        return [] if t == nf.TABLE else [{"symbol": "HYPE", "d": "2026-11-02", "grade": "B", "signal": "OUTPERFORM"}]

    async def ups(t, rows, on_conflict):
        return True

    async def chat_fail(msgs, temperature=0.4):
        ln._note("HTTP 401: invalid key")
        return None
    monkeypatch.setattr(nf, "fetch_items", fetch)
    monkeypatch.setattr(hdr, "_read_all", read_all)
    monkeypatch.setattr(store, "supabase_upsert_table", ups)
    monkeypatch.setattr(notify, "telegram_configured", lambda: False)
    monkeypatch.setenv("TELEGRAM_FEED_CHAT_ID", "-1")
    monkeypatch.setattr(ln, "configured", lambda: True)
    monkeypatch.setattr(ln, "_chat", chat_fail)
    r = asyncio.run(nf.run_once(now))
    assert r["ok"] is False and r["status"] == "degraded" and "401" in r["reason"] and r["candidates"] == 1


def test_reasoning_model_thinking_never_reaches_the_channel(monkeypatch):
    """11-05:MiniMax-M3 回复带 <think>…</think> —— 剥掉再发;思考段没闭合(被截断)就整条弃用,绝不把思考发进群。"""
    from src.data.narrative import llm_narrator as ln
    monkeypatch.setattr(ln, "configured", lambda: True)
    it = {"title": "Circle files", "summary_raw": "", "source": "The Block", "link": "https://x/y"}

    async def chat_think(msgs, temperature=0.4, max_tokens=1400):
        return "<think>The user wants a post. Facts: CRCL C.</think>\nCircle filed. It matters for stablecoin rails."

    async def chat_cut(msgs, temperature=0.4, max_tokens=1400):
        return "<think>The user wants a post and I am still thinking about"
    monkeypatch.setattr(ln, "_chat", chat_think)
    out = asyncio.run(nf.llm_post(it, {}))
    assert out and "think" not in out.lower() and "Circle filed." in out
    monkeypatch.setattr(ln, "_chat", chat_cut)
    assert asyncio.run(nf.llm_post(it, {})) is None
