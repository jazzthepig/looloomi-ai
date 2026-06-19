"""
CometCloud Telegram agent — a conversational interface to the intelligence,
not a settings panel.

The difference between "ERP SaaS" and a product with taste: an LP shouldn't fill
out a subscription form — they should *talk* to the intelligence. Type `ONDO` and
get a living scorecard (grade, positioning, a one-line read, and how much you can
actually move). Say `alert me` and you're subscribed. It demos itself.

Built agent-native: a Telegram webhook (`/internal/telegram/webhook`) routes each
message; replies are drawn from the same CIS universe the agents and dashboard
read, so the bot speaks with one voice. Subscriptions live in Redis; grade
upgrades fan out to subscribers via `broadcast_subscribers()`.

Compliance: positioning language only (grades + OUTPERFORM/NEUTRAL/etc.).
"""
from __future__ import annotations

import re
import logging

_log = logging.getLogger("tg_bot")

_SUBS_KEY = "telegram:subscribers"

_WELCOME = (
    "CometCloud — institutional intelligence, in your pocket.\n\n"
    "Talk to me like a person:\n"
    "• type a ticker (e.g. ONDO, BTC, SPY) for its live read\n"
    "• \"top\" — what's screening strongest right now\n"
    "• \"regime\" — the macro state we're scoring against\n"
    "• \"alert me\" — get pinged when assets upgrade to A / B+\n\n"
    "Built for humans and autonomous agents alike."
)
_HELP = (
    "Try: a ticker (ONDO / BTC / NVDA), \"top\", \"regime\", \"alert me\", \"stop\"."
)
_FALLBACK = (
    "I didn't catch a ticker there. Try one (ONDO, BTC, SPY), or \"top\" / \"regime\"."
)


async def _universe() -> dict:
    from src.api.routers.cis import get_cis_universe
    return await get_cis_universe()


def _detect_symbol(text: str) -> str | None:
    # uppercase tokens that look like tickers
    for tok in re.findall(r"\b[A-Za-z]{2,6}\b", text):
        t = tok.upper()
        if t in {"TOP", "THE", "FOR", "AND", "WHAT", "HOW", "ALERT", "STOP",
                 "REGIME", "ME", "IS", "ARE", "NOW", "CIS"}:
            continue
        return t
    return None


def _grade_emoji(grade: str) -> str:
    return {"A+": "🟢", "A": "🟢", "B+": "🟢", "B": "🟡", "C+": "🟡",
            "C": "🟠", "D": "🔴", "F": "🔴"}.get(grade or "", "•")


async def _asset_card(symbol: str) -> str:
    data = await _universe()
    uni = data.get("universe") or []
    a = next((x for x in uni if (x.get("symbol") or "").upper() == symbol), None)
    if not a:
        return f"{symbol} isn't in the curated universe right now. Try \"top\" to see what is."
    grade = a.get("grade") or "—"
    sig = a.get("signal") or "—"
    cis = a.get("cis_score")
    cis_s = f"{cis:.1f}" if isinstance(cis, (int, float)) else "—"
    narr = a.get("narrative") or ""
    ex = a.get("executability") or {}
    lines = [
        f"{_grade_emoji(grade)} {symbol} · {grade} · {sig}",
        f"CIS {cis_s}/100 · {a.get('asset_class','')} · regime {data.get('macro_regime','—')}",
    ]
    if narr:
        lines.append("")
        lines.append(narr)
    mx = ex.get("max_notional_25bps_usd")
    if isinstance(mx, (int, float)) and mx > 0:
        lines.append("")
        lines.append(f"Executable: ~${mx/1e6:.1f}M at <25bps ({ex.get('liquidity_tier','')}).")
    return "\n".join(lines)


async def _top(n: int = 6) -> str:
    data = await _universe()
    uni = sorted(data.get("universe") or [],
                 key=lambda x: x.get("cis_score") or 0, reverse=True)[:n]
    if not uni:
        return "No scores live this moment — try again shortly."
    out = [f"Strongest now · regime {data.get('macro_regime','—')}"]
    for a in uni:
        g = a.get("grade") or "—"
        out.append(f"{_grade_emoji(g)} {a.get('symbol')}  {g}  {a.get('signal','')}")
    return "\n".join(out)


async def _regime() -> str:
    data = await _universe()
    return (f"Macro regime: {data.get('macro_regime','—')}\n"
            f"Scoring {len((data.get('universe') or []))} assets against it right now.")


async def _subscribe(chat_id) -> str:
    try:
        from src.api.store import redis_get_key, redis_set_key
        subs = set((await redis_get_key(_SUBS_KEY) or {}).get("ids") or [])
        subs.add(str(chat_id))
        await redis_set_key(_SUBS_KEY, {"ids": list(subs)}, ttl=365 * 86400)
    except Exception:
        pass
    return "Done — I'll ping you when assets upgrade to A or B+. Say \"stop\" anytime."


async def _unsubscribe(chat_id) -> str:
    try:
        from src.api.store import redis_get_key, redis_set_key
        subs = set((await redis_get_key(_SUBS_KEY) or {}).get("ids") or [])
        subs.discard(str(chat_id))
        await redis_set_key(_SUBS_KEY, {"ids": list(subs)}, ttl=365 * 86400)
    except Exception:
        pass
    return "Alerts off. Type \"alert me\" to turn them back on."


async def broadcast_subscribers(text: str) -> int:
    """Fan a message out to all subscribers. Returns count sent."""
    from src.api.store import redis_get_key
    from src.api.notify import notify_telegram
    ids = (await redis_get_key(_SUBS_KEY) or {}).get("ids") or []
    sent = 0
    for cid in ids:
        if await notify_telegram(text, chat_id=str(cid)):
            sent += 1
    return sent


async def _route(text: str, chat_id) -> str:
    low = text.strip().lower()
    if low.startswith("/start"):
        return _WELCOME
    if low in ("/help", "help", "?", "帮助"):
        return _HELP
    if "alert" in low or "subscribe" in low or low.startswith("/alerts") or "订阅" in low:
        return await _subscribe(chat_id)
    if low in ("stop", "/stop", "unsubscribe", "unsub", "取消订阅", "mute"):
        return await _unsubscribe(chat_id)
    if low in ("top", "/top", "strong") or "strong" in low or "什么强" in low or "最强" in low:
        return await _top()
    if "regime" in low or "macro" in low or "宏观" in low:
        return await _regime()
    sym = _detect_symbol(text)
    if sym:
        return await _asset_card(sym)
    return _FALLBACK


async def handle_update(update: dict) -> None:
    """Entry point for a Telegram webhook update."""
    msg = update.get("message") or update.get("edited_message") or {}
    chat = msg.get("chat") or {}
    chat_id = chat.get("id")
    text = msg.get("text") or ""
    if not chat_id or not text:
        return
    try:
        reply = await _route(text, chat_id)
    except Exception as e:
        _log.warning("[TG_BOT] route error: %s", e)
        reply = "Something hiccupped on my end — try again in a moment."
    if reply:
        from src.api.notify import notify_telegram
        await notify_telegram(reply, chat_id=str(chat_id))
