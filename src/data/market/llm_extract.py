"""
LLM funding-round extractor — turns messy news headlines into structured rounds.

Why: aggregators (CryptoRank, DeFiLlama) paywall funding-round data, but the raw
facts are public in crypto news. Our old free path used regex on headlines, which
is brittle ("Monad closes $225M Series B led by Paradigm" parses; a hundred other
phrasings don't). An LLM reads any phrasing and returns clean JSON — turning the
free RSS feeds into a reliable source at ~zero marginal cost.

Design:
  - Calls any OpenAI-compatible /v1/chat/completions endpoint, configured by env:
        LLM_BASE_URL   e.g. http://mac-mini.local:1234/v1  (LM Studio) or a cloud URL
        LLM_API_KEY    optional (LM Studio ignores it; cloud needs it)
        LLM_MODEL      small model is plenty — extraction is easy (default below)
  - If LLM_BASE_URL is unset or the call fails, returns None → caller falls back
    to the existing regex path. Zero regression until an endpoint is wired.
  - Compliance is N/A here (factual extraction, no positioning language).
"""
from __future__ import annotations

import os
import json
import logging
from datetime import datetime, timezone

import httpx

_log = logging.getLogger("llm_extract")

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "").rstrip("/")
LLM_API_KEY  = os.getenv("LLM_API_KEY", "")
LLM_MODEL    = os.getenv("LLM_MODEL", "qwen/qwen3.5-9b")  # local instruct; qwen2.5-7b retired

_SYSTEM = (
    "You extract cryptocurrency VC funding rounds from news items. "
    "Return ONLY a JSON array, no prose. For each item that is clearly a company "
    "or project RAISING capital (seed/series/strategic/private/token sale), output: "
    '{"id": <int matching input>, "project": <name>, "amount_usd": <number, 0 if '
    'undisclosed>, "round": <stage e.g. "Seed","Series A","Strategic">, '
    '"lead_investors": [<names>], "investors": [<names>]}. '
    "Skip price moves, market commentary, fund/vehicle launches that are not a "
    "specific round, listings, hacks, and partnerships. If none qualify, return []."
)


def llm_configured() -> bool:
    return bool(LLM_BASE_URL)


def _coerce_amount(v) -> int:
    try:
        n = float(v)
        return int(n) if n >= 0 else 0
    except (TypeError, ValueError):
        return 0


def _extract_json_array(text: str) -> list:
    """Pull the first JSON array out of an LLM response (tolerates code fences/prose)."""
    if not text:
        return []
    t = text.strip()
    if t.startswith("```"):
        t = t.split("```", 2)[1] if "```" in t[3:] else t.strip("`")
        t = t[t.find("["):] if "[" in t else t
    start, end = t.find("["), t.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return []
    try:
        data = json.loads(t[start:end + 1])
        return data if isinstance(data, list) else []
    except Exception:
        return []


async def llm_extract_rounds(items: list[dict], cutoff_ts: float) -> list[dict] | None:
    """
    items: [{id, title, summary, source, date_ts}]
    Returns a list of round dicts (our canonical raise shape), or None if the LLM
    is unavailable/failed (caller should then use the regex fallback).
    """
    if not LLM_BASE_URL or not items:
        return None

    numbered = "\n".join(
        f'{it["id"]}. {it.get("title","")} — {(it.get("summary") or "")[:200]}'
        for it in items
    )
    by_id = {it["id"]: it for it in items}

    headers = {"Content-Type": "application/json"}
    if LLM_API_KEY:
        headers["Authorization"] = f"Bearer {LLM_API_KEY}"

    payload = {
        "model": LLM_MODEL,
        "temperature": 0,
        "max_tokens": 1500,
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": f"News items:\n{numbered}\n\nJSON array:"},
        ],
    }

    try:
        async with httpx.AsyncClient(timeout=45) as client:
            r = await client.post(f"{LLM_BASE_URL}/chat/completions", json=payload, headers=headers)
            if r.status_code != 200:
                _log.info(f"[LLM_EXTRACT] endpoint HTTP {r.status_code}")
                return None
            content = (r.json().get("choices") or [{}])[0].get("message", {}).get("content", "")
    except Exception as e:
        _log.warning(f"[LLM_EXTRACT] call failed: {e}")
        return None

    rows = _extract_json_array(content)
    if not rows:
        return []

    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        src_item = by_id.get(row.get("id")) or {}
        project = (row.get("project") or "").strip()
        if not project or project.lower() in ("unknown", "n/a", ""):
            continue
        date_ts = src_item.get("date_ts") or 0
        if date_ts and date_ts < cutoff_ts:
            continue
        lead = [str(x).strip() for x in (row.get("lead_investors") or []) if str(x).strip()]
        allf = [str(x).strip() for x in (row.get("investors") or []) if str(x).strip()]
        amount = _coerce_amount(row.get("amount_usd"))
        out.append({
            "name":             project,
            "amount":           amount,
            "amount_disclosed": amount > 0,
            "round":            (row.get("round") or "Funding").strip() or "Funding",
            "date":             date_ts or int(datetime.now(timezone.utc).timestamp()),
            "category":         "Crypto",
            "categoryGroup":    "Crypto",
            "sector":           "Crypto",
            "chains":           [],
            "leadInvestors":    lead,
            "investors":        allf or lead,
            "description":      (src_item.get("title") or "")[:200],
            "source":           f"llm:{src_item.get('source','rss')}",
        })
    _log.info(f"[LLM_EXTRACT] extracted {len(out)} rounds from {len(items)} items")
    return out
