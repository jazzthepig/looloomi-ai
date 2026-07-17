"""
LLM narrator — turns the deterministic briefing FACTS into plain-language prose.
=================================================================================
Seth 2026-07-17. Jazz: "必须要ai分析的，我们用minimax也可以啊" — the signal-feed
narrative must be genuinely AI-written, not template-composed. This is the enrichment
layer: the structured facts (symbols, scores, layers, directions, crowding, accuracy)
stay the deterministic, compliance-safe GROUND TRUTH; the LLM only writes the sentences.

Design guarantees:
  · OpenAI-compatible client — points at MiniMax cloud API, Mac Mini LM Studio, or any
    OpenAI-shaped endpoint via env (NARRATIVE_LLM_* → falls back to LLM_* already in prod).
  · The model is given FACTS and asked to write narrative ONLY. It never invents numbers
    (we pass the numbers; it phrases them). Item ids are echoed back so we overlay prose
    onto our own structure — the model cannot add/drop items.
  · Compliance hard gate: the output is REJECTED (→ template fallback) if it contains any
    buy/sell/advice language. Positioning language only. A model that misbehaves degrades
    to templates with zero compliance risk.
  · Fully optional: no endpoint configured ⇒ returns None ⇒ caller uses templates. No
    regression on hosts without an LLM.

Runs in a background loop (see main.py) that caches the result to Redis `signal:ai_briefing`,
so the feed request itself never blocks on the model.
"""
from __future__ import annotations

import json
import logging
import os
import re

import httpx

_logger = logging.getLogger(__name__)

# env — narrative-specific first, then the shared LLM_* already documented in CLAUDE.md
_BASE  = (os.environ.get("NARRATIVE_LLM_BASE_URL") or os.environ.get("LLM_BASE_URL") or "").rstrip("/")
_KEY   = os.environ.get("NARRATIVE_LLM_API_KEY") or os.environ.get("LLM_API_KEY") or ""
_MODEL = os.environ.get("NARRATIVE_LLM_MODEL") or os.environ.get("LLM_MODEL") or "MiniMax-Text-01"
_TIMEOUT = float(os.environ.get("NARRATIVE_LLM_TIMEOUT", "45"))

# Compliance: if the model emits any of these (whole-word), we DROP its output and fall
# back to templates. Positioning language only — no advice, no buy/sell. (Mirrors the
# compliance-language skill's banned list.)
_BANNED = re.compile(
    r"\b(buy|sell|strong buy|strong sell|accumulate|avoid|reduce|dump|"
    r"long it|short it|take profit|stop loss|price target|guaranteed|"
    r"invest in|allocate to|purchase)\b",
    re.IGNORECASE,
)

_SYSTEM = (
    "You are the senior market strategist for CometCloud AI, an institutional crypto "
    "intelligence desk. You write a tiered market briefing for professional investors and "
    "autonomous trading agents. Voice: precise, calm, buy-side analyst — think Glassnode "
    "'Week On-chain'. You explain WHAT is happening and WHY IT MATTERS.\n\n"
    "HARD RULES (compliance — a HK-regulated desk without an advisory licence):\n"
    "  · POSITIONING LANGUAGE ONLY. Never write buy, sell, accumulate, avoid, reduce, "
    "invest, allocate, price target, or any instruction to act. Use: outperform, "
    "underperform, lean into, fade, crowded, squeeze, quality strengthening/eroding.\n"
    "  · You are given FACTS with numbers already computed. Phrase them — never invent a "
    "number, ticker, or claim not in the facts. Do not add or remove items.\n"
    "  · 2–3 sentences per item. No bullet points, no headers, no markdown. Plain prose.\n"
    "  · A reader (human or agent) must understand it WITHOUT decoding our internal scores.\n"
    "Return STRICT JSON only, no prose around it."
)

_INSTRUCTION = (
    "Write the briefing from these facts. Return JSON of this exact shape:\n"
    '{\n'
    '  "headline": "<one sentence, the top-of-briefing frame for this regime>",\n'
    '  "items": { "<item_id>": "<2-3 sentence narrative>", ... }\n'
    '}\n'
    "Write a narrative for EVERY item_id present in facts.items. Keep each item's own "
    "symbol/direction/numbers consistent with its facts. FACTS:\n"
)


def configured() -> bool:
    """True when an LLM endpoint is set — caller can skip the whole pass otherwise."""
    return bool(_BASE)


async def _chat(messages: list, temperature: float = 0.4) -> str | None:
    if not _BASE:
        return None
    url = f"{_BASE}/chat/completions"
    headers = {"Content-Type": "application/json"}
    if _KEY:
        headers["Authorization"] = f"Bearer {_KEY}"
    payload = {"model": _MODEL, "messages": messages, "temperature": temperature,
               "max_tokens": 1400, "stream": False}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as cli:
            r = await cli.post(url, headers=headers, content=json.dumps(payload))
            if r.status_code != 200:
                _logger.warning(f"[NARRATOR] LLM {r.status_code}: {r.text[:200]}")
                return None
            data = r.json()
            return (data.get("choices") or [{}])[0].get("message", {}).get("content")
    except Exception as e:
        _logger.warning(f"[NARRATOR] LLM call failed: {e}")
        return None


def _extract_json(text: str) -> dict | None:
    if not text:
        return None
    # models sometimes wrap JSON in ```json fences or add a preamble — grab the object
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def _clean(s: str) -> str | None:
    """Strip markdown/whitespace; REJECT (→ None) if it contains banned advice language."""
    if not isinstance(s, str):
        return None
    s = re.sub(r"[*_`#>]", "", s).strip()
    s = re.sub(r"\s+", " ", s)
    if not s:
        return None
    if _BANNED.search(s):
        _logger.warning(f"[NARRATOR] compliance reject: {s[:80]!r}")
        return None
    return s


async def compose_ai_briefing(facts: dict) -> dict | None:
    """Given the structured briefing facts (regime + items[{id, ...}]), ask the LLM to write
    prose for each item + a top headline. Returns {headline, items:{id: narrative}} with every
    narrative compliance-checked, or None if the model is unconfigured / failed / non-compliant.
    The caller overlays these onto its own deterministic structure."""
    if not _BASE:
        return None
    items = facts.get("items") or []
    if not items:
        return None
    raw = await _chat(
        [{"role": "system", "content": _SYSTEM},
         {"role": "user", "content": _INSTRUCTION + json.dumps(facts, ensure_ascii=False)}],
    )
    parsed = _extract_json(raw or "")
    if not parsed or not isinstance(parsed.get("items"), dict):
        _logger.warning("[NARRATOR] no usable JSON from model — falling back to templates")
        return None

    out_items: dict = {}
    for it in items:
        iid = it.get("id")
        cleaned = _clean(parsed["items"].get(iid, ""))
        if cleaned:
            out_items[iid] = cleaned
    if not out_items:               # everything got rejected/empty — no AI value, use templates
        return None
    headline = _clean(parsed.get("headline") or "")
    return {"headline": headline, "items": out_items,
            "model": _MODEL, "coverage": f"{len(out_items)}/{len(items)}"}
