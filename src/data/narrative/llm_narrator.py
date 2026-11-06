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
#: 11-03:Railway 里粘贴的 key 带了换行,httpx 报 Illegal header value —— 值一律 strip();URL 去尾斜杠。
def normalize_base(u: str) -> str:
    """11-05:`_agent_judgment_loop` 第一次留下原因就是「HTTP 302 … alb」—— Railway 里填的是 `http://api.minimax.io`(没 https、没 /v1),
    POST 被负载均衡 302 到 https,httpx 不跟。只对 MiniMax 的公网域名补 https 与 /v1;局域网 / 本机(LM Studio)原样不动。"""
    u = (u or "").strip().rstrip("/")
    m = re.match(r"^(?:https?://)?(api\.minimax(?:i)?\.(?:io|chat))(/.*)?$", u, re.IGNORECASE)
    if not m:
        return u
    path = (m.group(2) or "").rstrip("/")
    if not path.startswith("/v1"):
        path = "/v1"
    return f"https://{m.group(1).lower()}{path}"


_BASE  = normalize_base(os.environ.get("NARRATIVE_LLM_BASE_URL") or os.environ.get("LLM_BASE_URL") or "")
_KEY   = (os.environ.get("NARRATIVE_LLM_API_KEY") or os.environ.get("LLM_API_KEY") or "").strip()
_MODEL = (os.environ.get("NARRATIVE_LLM_MODEL") or os.environ.get("LLM_MODEL") or "MiniMax-Text-01").strip()
_TIMEOUT = float(os.environ.get("NARRATIVE_LLM_TIMEOUT", "45"))
#: 11-06(Jazz):主 key 是 5 小时窗口的套餐、与 lane 的挖掘共用,挖得多就会用完 —— 另备一把按量付费的后备 key。
#: 只在主 key 撞到额度(HTTP 429 / base_resp 1002 限速 / 1008 余额)时用;没配就和以前一样。base 不配 ⇒ 与主 key 同一个端点。
_FB_KEY = (os.environ.get("LLM_FALLBACK_API_KEY") or "").strip()
_FB_BASE = normalize_base(os.environ.get("LLM_FALLBACK_BASE_URL") or "") or _BASE
_QUOTA_CODES = {1002, 1008}


def quota_hit(status: int, data) -> bool:
    """纯函数。这次回复是不是「额度 / 限速」(换后备 key 有用),而不是请求本身错了。"""
    if status == 429:
        return True
    try:
        return int(((data or {}).get("base_resp") or {}).get("status_code") or 0) in _QUOTA_CODES
    except (TypeError, ValueError, AttributeError):
        return False


def credentials(fallback: bool = False) -> tuple[str, str]:
    """(base, key)。fallback=True 且配了后备 key ⇒ 后备;否则主。"""
    return (_FB_BASE, _FB_KEY) if fallback and _FB_KEY else (_BASE, _KEY)

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


#: 11-02:模型为什么没答(状态码 / 异常 / 未配),留给 `GET /internal/news-feed` 看 —— Railway 日志这边读不到。
LAST_ERROR: dict = {"at": None, "why": None, "model": _MODEL, "base": _BASE[:40] if _BASE else None}


_SECRET = re.compile(r"[A-Za-z0-9_\-]{16,}")          # 任何像 token 的长串都抹掉;Bearer 之后整段不留


def _note(why: str | None) -> None:
    """留错误原因,**不留密钥**(11-03:httpx 的 Illegal header value 把整段 Authorization 头原样写进了异常文本)。"""
    import datetime as _dt
    LAST_ERROR.update(at=_dt.datetime.now(_dt.timezone.utc).isoformat(),
                      why=None if why is None else _SECRET.sub("…", re.sub(r"(?i)bearer\s.*", "Bearer …", why, flags=re.DOTALL))[:200])


async def _chat(messages: list, temperature: float = 0.4, max_tokens: int = 1400, timeout: float | None = None) -> str | None:
    if not _BASE:
        _note("LLM_BASE_URL 未配")
        return None
    payload = {"model": _MODEL, "messages": messages, "temperature": temperature,
               "max_tokens": int(max_tokens), "stream": False}
    try:
        async with httpx.AsyncClient(timeout=timeout or _TIMEOUT) as cli:   # 推理模型长回复按调用方给的时限(agent 臂 300 秒)
            for fb in ((False, True) if _FB_KEY else (False,)):
                base, key = credentials(fb)
                headers = {"Content-Type": "application/json", **({"Authorization": f"Bearer {key}"} if key else {})}
                r = await cli.post(f"{base}/chat/completions", headers=headers, content=json.dumps(payload))
                try:
                    body = r.json() if r.status_code in (200, 429) else None
                except ValueError:
                    body = None
                if not quota_hit(r.status_code, body):
                    break
                _logger.warning(f"[NARRATOR] LLM quota hit on {'fallback' if fb else 'primary'} key")
            if r.status_code != 200:
                _logger.warning(f"[NARRATOR] LLM {r.status_code}: {r.text[:200]}")
                _note(f"HTTP {r.status_code}: {r.text[:160]}")
                return None
            data = r.json()
            _note(None)
            return (data.get("choices") or [{}])[0].get("message", {}).get("content")
    except Exception as e:
        _logger.warning(f"[NARRATOR] LLM call failed: {e}")
        _note(f"{type(e).__name__}: {str(e)[:160]}")
        return None


_THINK = re.compile(r"<think>.*?(</think>|$)", re.DOTALL | re.IGNORECASE)


def _extract_json(text: str) -> dict | None:
    """模型回的文字 → 里面**最后一个**能完整解析的 JSON 对象。
    11-05:MiniMax-M3 是推理模型,先吐 `<think>…</think>` 再给 JSON;原来的贪婪正则从思考里的第一个 `{` 吞到最后一个 `}`,
    整段解析失败(agent 臂 refused:「回的不是三档概率 JSON」)。现在先去掉思考段,再逐个 `{` 用 raw_decode 试,取最后一个成功的。"""
    if not text:
        return None
    t = _THINK.sub("", text)
    dec = json.JSONDecoder()
    found, i = None, 0
    while i < len(t):
        j = t.find("{", i)
        if j < 0:
            break
        try:
            obj, n = dec.raw_decode(t[j:])
        except ValueError:
            i = j + 1
            continue
        if isinstance(obj, dict):
            found = obj                     # 顶层对象;跳过它的内部,不把嵌套的小对象当答案
        i = j + n
    return found


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
        max_tokens=4000,                                                 # 11-05:推理模型先想再答
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
