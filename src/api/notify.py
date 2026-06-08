"""
Telegram notifications — one helper, two jobs.

Internal ops (now): heartbeat / health alerts to the team channel.
GTM (later): user-facing alerts (grade changes, signal crossings, regime shifts)
to LPs and agents who opt in via the bot — same bot, per-user chat_id.

Config (Railway env — never hardcode the token):
  TELEGRAM_BOT_TOKEN      from BotFather
  TELEGRAM_ALERT_CHAT_ID  default destination for internal ops alerts

Safe by design: if the token is unset, every call is a no-op (returns False) —
no exceptions bubble into the request path.
"""
from __future__ import annotations

import os
import logging
from typing import Optional

import httpx

_log = logging.getLogger("notify")

_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
_DEFAULT_CHAT = os.environ.get("TELEGRAM_ALERT_CHAT_ID", "")
_API = "https://api.telegram.org"


def telegram_configured() -> bool:
    return bool(_TOKEN)


async def notify_telegram(
    text: str,
    chat_id: Optional[str] = None,
    parse_mode: Optional[str] = None,
    disable_preview: bool = True,
) -> bool:
    """
    Send a Telegram message. Returns True on success, False on no-op/failure.
    chat_id defaults to TELEGRAM_ALERT_CHAT_ID (the internal ops channel).

    parse_mode defaults to None (plain text) on purpose: ops alerts routinely
    contain underscores / asterisks (asset symbols, git shas, the bot handle),
    which break Telegram's Markdown parser and 400 the whole message. Pass
    "MarkdownV2"/"HTML" explicitly only when the text is properly escaped.
    """
    if not _TOKEN:
        _log.info("[NOTIFY] TELEGRAM_BOT_TOKEN unset — skipping")
        return False
    dest = chat_id or _DEFAULT_CHAT
    if not dest:
        _log.warning("[NOTIFY] no chat_id (set TELEGRAM_ALERT_CHAT_ID) — skipping")
        return False
    body = {"chat_id": dest, "text": text, "disable_web_page_preview": disable_preview}
    if parse_mode:
        body["parse_mode"] = parse_mode
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(f"{_API}/bot{_TOKEN}/sendMessage", json=body)
            if r.status_code == 200 and r.json().get("ok"):
                return True
            _log.warning("[NOTIFY] telegram HTTP %s: %s", r.status_code, r.text[:160])
    except Exception as e:
        _log.warning("[NOTIFY] telegram error: %s", e)
    return False


def notify_telegram_sync(text: str, chat_id: Optional[str] = None,
                         parse_mode: Optional[str] = None) -> bool:
    """Blocking variant for scripts / non-async callers (deploy gate, cron)."""
    if not _TOKEN:
        return False
    dest = chat_id or _DEFAULT_CHAT
    if not dest:
        return False
    body = {"chat_id": dest, "text": text, "disable_web_page_preview": True}
    if parse_mode:
        body["parse_mode"] = parse_mode
    try:
        with httpx.Client(timeout=10) as client:
            r = client.post(f"{_API}/bot{_TOKEN}/sendMessage", json=body)
            return r.status_code == 200 and r.json().get("ok", False)
    except Exception:
        return False
