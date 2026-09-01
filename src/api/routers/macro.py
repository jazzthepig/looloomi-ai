"""
Macro Brief router — receives AI-generated macro analysis from Mac Mini,
stores in Redis, and serves to the dashboard.

Endpoints:
  POST /internal/macro-brief  — Mac Mini pushes analysis (same auth as CIS)
  GET  /api/v1/macro/brief    — Dashboard reads latest brief (auto-generates if empty)
"""
import os, json, time, re, ast
from datetime import datetime

import logging
from fastapi import APIRouter, HTTPException, Header, Response

from src.api.store import redis_set_key, redis_get_key, supabase_insert_table

_logger = logging.getLogger(__name__)

router = APIRouter()


def _sanitize_brief(text) -> str:
    """Clean a macro brief before it reaches users. The Mac-side push has shipped
    malformed briefs — a stringified Python dict (`{'brief': '...'}`), placeholder
    dates, and internal notes leaking into the card. Unwrap and strip them.
    Defensive: any failure returns the original text untouched."""
    if not text:
        return ""
    try:
        s = text if isinstance(text, str) else str(text)
        s = s.strip()
        # Unwrap a stringified dict/JSON: {'brief': '...'} or {"brief": "..."}
        if s[:1] in "{[":
            parsed = None
            for loader in (json.loads, ast.literal_eval):
                try:
                    parsed = loader(s); break
                except Exception:
                    continue
            if isinstance(parsed, dict):
                for k in ("brief", "text", "content", "analysis", "markdown"):
                    if isinstance(parsed.get(k), str) and parsed[k].strip():
                        s = parsed[k].strip(); break
                else:
                    s = "\n".join(str(v) for v in parsed.values() if isinstance(v, str)).strip()
            elif isinstance(parsed, (list, tuple, set)):
                s = "\n".join(str(v) for v in parsed if isinstance(v, str)).strip()
            else:
                # Parse failed (e.g. a multi-line repr — a raw newline in a quoted
                # literal isn't valid Python). Regex-extract the brief value across
                # newlines, else just peel the wrapper braces.
                m = re.search(r"['\"](?:brief|text|content|analysis|markdown)['\"]\s*:\s*(['\"])(.*?)\1\s*[,}]", s, re.S | re.I)
                if m:
                    s = m.group(2).strip()
                else:
                    s = re.sub(r"^[\{\[]\s*['\"]?", "", s)
                    s = re.sub(r"['\"]?\s*[\}\]]$", "", s)
        # Strip a surviving leading wrapper:  {'brief': '   or   brief:
        s = re.sub(r"^\{?\s*['\"]?(?:brief|text|content)['\"]?\s*:\s*['\"]?", "", s, flags=re.I)
        # Convert any escaped newlines (from a repr) back to real ones
        s = s.replace("\\n", "\n")
        # Drop internal placeholders / notes that must never be user-facing
        s = re.sub(r"\(\s*sample date\s*\)", "", s, flags=re.I)
        s = re.sub(r"\(\s*note:[^)]*\)", "", s, flags=re.I)
        s = re.sub(r"\b(?:market update|update)\s+\d{1,2}/\d{1,2}/\d{2,4}\s*[:\-]?\s*", "", s, flags=re.I)
        # Trim a dangling closing quote/brace from an unwrapped dict
        s = s.rstrip("'\"} \t")
        # Collapse only runs of spaces/tabs (NOT newlines — preserve markdown), and
        # cap blank-line runs at 2.
        s = re.sub(r"[ \t]{2,}", " ", s)
        s = re.sub(r"\n{3,}", "\n\n", s)
        return s.strip()
    except Exception:
        return text if isinstance(text, str) else str(text)


def _looks_like_brief(s: str) -> bool:
    """True if the string reads like a real prose macro brief, not corrupt/structured
    junk. Guards against malformed Mac pushes the sanitizer can't salvage."""
    if not s or len(s) < 80:
        return False
    # Telltale corruption signatures seen in bad pushes
    if re.search(r'-DAT-DAT|-fmt-|-text-text|"?action_name"?|"?action"?\s*:\s*-?\d', s, re.I):
        return False
    # Real prose: enough spaces + a healthy letter ratio
    letters = sum(c.isalpha() for c in s)
    if s.count(" ") < 12 or letters / max(len(s), 1) < 0.55:
        return False
    return True


async def _persist_brief(brief: str, model: str, data_snapshot: dict, source: str) -> bool:
    """Write a macro brief to the Supabase macro_briefs table (history). Best-effort."""
    if not brief:
        return False
    try:
        return await supabase_insert_table("macro_briefs", [{
            "brief":         brief,
            "model":         model,
            "data_snapshot": data_snapshot,
            "source":        source,
            "recorded_at":   datetime.utcnow().isoformat() + "Z",
        }])
    except Exception as e:
        _logger.warning(f"[MACRO] persist failed: {e}")
        return False

_INTERNAL_TOKEN = os.environ.get("INTERNAL_TOKEN", "")
_REDIS_KEY      = "macro:brief"
# S-187 (2026-08-20). These were sized for "briefs are twice daily". The Mac now
# polls every 5 minutes and regenerates on material change (see
# `contracts/macro_brief.py`), so a 12-hour TTL and a 1-hour staleness window
# are no longer describing the system — they are the ceiling that would hide it.
#
# The TTL stays generous on purpose: it is the LAST-RESORT survival window for
# the brief if the Mac goes dark, and shortening it would turn a Mac outage into
# a blank panel. Staleness, which decides when Railway generates its own
# template fallback, is what has to track the real cadence.
_REDIS_TTL      = 43200   # 12h — survival window only, NOT the refresh cadence
_AUTO_TTL       = 900     # 15 min — an auto-generated (template) brief is a
                          # stopgap; it must not outlive a Mac recovery by much
_AUTO_STALE     = 900     # regenerate the template fallback after 15 min

# Must be ≤ the Mac's poll interval, or the CDN becomes the binding constraint
# and the 5-minute target is silently a 10-minute one. Imported rather than
# restated so the two cannot drift (this is exactly how `max-age=600` survived
# alongside a 5-minute requirement in the first draft of this change).
from src.api.contracts.macro_brief import POLL_INTERVAL_S as _POLL_S
from src.api.contracts import serving_tier as _tier
_BRIEF_MAX_AGE  = min(300, _POLL_S)
_BRIEF_SWR      = 120     # brief SWR: a cold edge may serve up to 2 min past
                          # expiry, never the hour that caused S-183


# ── Template brief generator (no LLM required) ───────────────────────────────

def _generate_template_brief(mp: dict) -> str:
    """
    Build a structured data-driven macro brief from macro-pulse snapshot.
    Runs inline on Railway — no LLM dependency.
    """
    regime        = mp.get("macro_regime", "Unknown")
    fg_val        = mp.get("fear_greed_index") or mp.get("fear_greed", {}).get("value")
    fg_lbl        = mp.get("fear_greed_label") or mp.get("fear_greed", {}).get("label", "—")
    btc_dom       = mp.get("btc_dominance")
    btc_price     = mp.get("btc_price") or mp.get("btc", {}).get("price")
    btc_chg       = mp.get("btc_change_24h") or mp.get("btc", {}).get("change_24h")
    mcap          = mp.get("total_market_cap_usd")
    defi_tvl      = mp.get("defi_tvl_usd")

    # Regime colour-coding
    regime_signals = {
        "TIGHTENING":   ("Tightening monetary conditions persist.", "Risk-off positioning favoured. Selective exposure to high-CIS assets above regime threshold (CIS≥52)."),
        "EASING":       ("Easing cycle underway.", "Risk-on conditions improve. Broader exposure warranted for assets above CIS≥60."),
        "RISK_ON":      ("Risk-on macro environment.", "Broad participation supported. Quality filter still applies — CIS≥65 preferred."),
        "RISK_OFF":     ("Risk-off macro environment.", "Capital preservation priority. High-CIS defensives and stablecoins preferred."),
        "STAGFLATION":  ("Stagflation signals present.", "Commodities, RWA, and BTC screen as inflation hedges. High-beta altcoins rank UNDERWEIGHT."),
        "GOLDILOCKS":   ("Goldilocks regime — growth without excess inflation.", "Full-spectrum participation. Allocate across grades B+ and above."),
    }
    regime_key = (regime or "").upper()
    regime_context, regime_action = regime_signals.get(regime_key, (
        f"Current regime: {regime}.",
        "Monitor CIS universe for grade changes before adjusting exposure."
    ))

    # Sentiment read
    if fg_val is not None:
        if fg_val <= 25:
            sentiment_read = f"Extreme Fear ({fg_val}) signals capitulation risk but potential contrarian entry for high-conviction positions."
        elif fg_val <= 45:
            sentiment_read = f"Fear ({fg_val}) — market participants remain cautious. Accumulation zones possible for A-grade assets."
        elif fg_val <= 55:
            sentiment_read = f"Neutral ({fg_val}) — indecision. Await confirmation before adding risk."
        elif fg_val <= 75:
            sentiment_read = f"Greed ({fg_val}) — momentum positive but watch for mean-reversion signals."
        else:
            sentiment_read = f"Extreme Greed ({fg_val}) — elevated complacency. Reduce risk exposure incrementally."
    else:
        sentiment_read = "Sentiment data unavailable."

    # BTC dominance read
    if btc_dom is not None:
        if btc_dom > 60:
            dom_read = f"BTC dominance at {btc_dom:.1f}% — alt-season conditions absent. BTC-led market structure."
        elif btc_dom > 52:
            dom_read = f"BTC dominance at {btc_dom:.1f}% — selective altcoin strength possible in L1/DeFi."
        else:
            dom_read = f"BTC dominance at {btc_dom:.1f}% — broad altcoin participation. Diversified exposure warranted."
    else:
        dom_read = "Dominance data unavailable."

    # Format numbers
    def _fmt_mcap(v):
        if v is None: return "—"
        if v >= 1e12: return f"${v/1e12:.2f}T"
        if v >= 1e9:  return f"${v/1e9:.1f}B"
        return f"${v:,.0f}"

    btc_str  = f"${btc_price:,.0f}" if btc_price else "—"
    chg_str  = (f"+{btc_chg:.1f}%" if btc_chg >= 0 else f"{btc_chg:.1f}%") if btc_chg is not None else "—"
    mcap_str = _fmt_mcap(mcap)
    tvl_str  = _fmt_mcap(defi_tvl)

    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    brief = f"""**CometCloud Macro Brief** · {ts}

**Regime: {regime}** — {regime_context}

Total crypto market cap stands at {mcap_str} with BTC at {btc_str} ({chg_str} 24h). {dom_read} DeFi TVL: {tvl_str}.

**Sentiment:** {sentiment_read}

**Positioning:** {regime_action}

Powered by Looloomi-AI"""

    return brief


# ── Internal push (Mac Mini → Railway) ───────────────────────────────────────

@router.post("/internal/macro-brief")
async def receive_macro_brief(payload: dict, x_internal_token: str = Header(None)):
    """
    Receives AI-generated macro analysis from the Mac Mini.
    Expected payload:
    {
        "brief": "...",          # The analysis text (markdown)
        "market_data": {...},    # Raw data snapshot used for the analysis
        "model": "gemma4-26b",   # Model that generated it
        "generated_at": "..."   # ISO timestamp
    }
    """
    if not _INTERNAL_TOKEN or not x_internal_token or x_internal_token != _INTERNAL_TOKEN:
        raise HTTPException(status_code=403, detail="Forbidden")

    if not payload.get("brief"):
        raise HTTPException(status_code=400, detail="Missing 'brief' field")

    payload["brief"] = _sanitize_brief(payload["brief"])  # unwrap malformed Mac-side pushes
    payload["received_at"] = int(time.time())
    payload["source"] = "mac_mini"

    # ── S-186: validate before it can reach a reader ────────────────────────
    # Every compliance rule in the prompt is a REQUEST to a 9B local model.
    # "Usually obeyed" is not a compliance posture for a firm with no 投顾
    # licence publishing to allocators, so the request is now also enforced.
    #
    # This REJECTS, unlike the cis_push receiver which echoes and never rejects
    # (S-178). The difference is not inconsistency: that receiver faces a schema
    # disagreement where it cannot know which of two deployments is right. Here
    # there is no ambiguity — CLAUDE.md #1 makes BUY/SELL vocabulary a P0. The
    # previous brief keeps serving, which is a stale page; the alternative is a
    # compliance breach on an investor page, and only one of those is
    # recoverable.
    from src.api.contracts.macro_brief import validate_brief, PROMPT_VERSION
    verdict = validate_brief(payload["brief"], payload.get("market_data"))
    payload["validation"] = verdict
    payload["prompt_version"] = payload.get("prompt_version") or "unknown"
    if payload["prompt_version"] != PROMPT_VERSION:
        # Recorded, never rejected — the Mac may legitimately be a deploy behind.
        _logger.warning("[MACRO] brief arrived with prompt_version=%s, contract is %s",
                        payload["prompt_version"], PROMPT_VERSION)

    if not verdict["ok"]:
        _logger.error("[MACRO] REJECTED brief from Mac — %s", verdict["violations"])
        raise HTTPException(
            status_code=422,
            detail={"error": "brief failed compliance validation; not published",
                    "violations": verdict["violations"],
                    "prompt_version_seen": payload["prompt_version"],
                    "prompt_version_expected": PROMPT_VERSION,
                    "note": "the previously published brief remains in force"})
    if verdict["warnings"]:
        _logger.warning("[MACRO] brief warnings: %s", verdict["warnings"])

    ok = await redis_set_key(_REDIS_KEY, payload, ttl=_REDIS_TTL)
    if not ok:
        raise HTTPException(status_code=502, detail="Redis write failed")

    # Persist to Supabase history (best-effort) so macro_briefs is never empty
    await _persist_brief(payload["brief"], payload.get("model", "mac_mini"),
                         payload.get("market_data"), "mac_mini")

    _logger.info(f"[MACRO] Brief received — {len(payload['brief'])} chars, model={payload.get('model', '?')}")
    return {
        "status": "ok",
        "chars": len(payload["brief"]),
        "key": _REDIS_KEY,
    }


# ── Public read (with inline auto-generation fallback) ───────────────────────

async def daily_macro_brief_snapshot() -> dict:
    """Guarantee a daily macro_briefs row even if the Mac LM never pushes.
    Generates the Railway template brief from live macro-pulse and persists it."""
    try:
        try:
            from src.data.market.data_layer import get_macro_pulse
        except ImportError:
            from data.market.data_layer import get_macro_pulse
        mp = await get_macro_pulse()
        brief_text = _generate_template_brief(mp)
        ok = await _persist_brief(brief_text, "template", mp, "auto")
        _logger.info(f"[MACRO] daily fallback brief persisted: ok={ok}")
        return {"ok": bool(ok), "chars": len(brief_text)}
    except Exception as e:
        _logger.warning(f"[MACRO] daily fallback failed: {e}")
        return {"ok": False, "error": str(e)}


@router.get("/api/v1/macro/brief")
async def get_macro_brief(response: Response):
    """
    Returns the latest macro brief from Redis.
    If empty or stale >1h, auto-generates a data-driven brief from live macro-pulse
    and caches it — no Mac Mini or LLM required.
    """
    data = await redis_get_key(_REDIS_KEY)
    now  = int(time.time())

    brief_text = _sanitize_brief((data or {}).get("brief") or "")  # clean cached/legacy briefs too

    # Serve the Mac brief only if it reads like real prose. A corrupt push (e.g.
    # `{"action":-1,"action_name":"-", -fmt-text-DAT…}`) can't be salvaged by the
    # sanitizer — reject it and fall through to the data-driven template below.
    if brief_text and not _looks_like_brief(brief_text):
        _logger.warning(f"[MACRO] rejecting non-prose brief ({len(brief_text)} chars) → template fallback")
        brief_text = ""

    # Serve LLM brief if fresh AND has actual content
    if brief_text:
        age    = now - data.get("received_at", 0)
        source = data.get("source", "mac_mini")
        # Always serve Mac Mini LLM briefs until they expire (12h TTL)
        if source == "mac_mini" or age < _AUTO_STALE:
            # S-183 → S-187. This was `max-age=600, swr=3600`: a cold CDN edge
            # could serve a brief 70 minutes past expiry, which is exactly the
            # "从别的手机登陆看是滞后的" report. Cut to 5 min, and now DERIVED
            # from the Mac's poll interval rather than restated — a hand-written
            # 600 next to a 5-minute requirement is how the CDN quietly becomes
            # the binding constraint on freshness.
            response.headers["Cache-Control"] = (
                f"public, max-age={_BRIEF_MAX_AGE}, "
                f"stale-while-revalidate={_BRIEF_SWR}")
            return {
                "brief":        brief_text,
                "brief_chars":  len(brief_text),
                "market_data":  data.get("market_data"),
                "model":        data.get("model"),
                "generated_at": data.get("generated_at"),
                "received_at":  data.get("received_at"),
                "age_seconds":  age,
                "stale":        age > _REDIS_TTL,
                # S-265:`source` 原本直接吐 "mac_mini" —— 面向用户的响应里的硬件名
                # (规则 #8;那条守卫只扫 dashboard/*.jsx,API 响应从不在范围内)。
                "source":       _tier.public_source(source),
                **_tier.describe(_tier.UPSTREAM, age_s=age),
            }

    # Auto-generate from live macro-pulse data
    try:
        try:
            from src.data.market.data_layer import get_macro_pulse
        except ImportError:
            from data.market.data_layer import get_macro_pulse

        mp = await get_macro_pulse()
        brief_text = _generate_template_brief(mp)

        payload = {
            "brief":        brief_text,
            "brief_chars":  len(brief_text),
            "market_data":  mp,
            "model":        "template",
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "received_at":  now,
            "source":       _tier.FALLBACK,
            **_tier.describe(
                _tier.FALLBACK,
                reason="上游 macro:brief 缺失或过期,这份由 Railway 用 macro-pulse "
                       "现算的模板顶上 —— 它的 regime 来自阈值兜底,不是引擎的判断"),
        }
        # S-265:**兜底不得写回上游那把钥匙。**
        # 原本是 `redis_set_key(_REDIS_KEY, ...)`,而 health.py 判活读的就是
        # `macro:brief`。于是 Mac 死 → health 报 missing → 兜底跑一次把自己写进去
        # → **health 变绿而 Mac 仍然是死的**。缓解措施抹掉了自己存在的证据。
        # 分开存,判活才分得开「上游活着」和「兜底顶着」。
        await redis_set_key(_tier.fallback_key(_REDIS_KEY), payload, ttl=_AUTO_TTL)
        _logger.info(f"[MACRO] Auto-generated brief from macro-pulse data — {len(brief_text)} chars")

        return {**payload, "age_seconds": 0, "stale": False}

    except Exception as e:
        _logger.error(f"[MACRO] Auto-generate failed: {e}", exc_info=True)
        # Last resort: return stale data or empty
        if data:
            age = now - data.get("received_at", 0)
            payload = {**data, "age_seconds": age, "stale": True,
                       "source": _tier.public_source(data.get("source")),
                       **_tier.describe(_tier.STALE, age_s=age,
                                        reason="上游旧值 + 兜底生成也失败了")}
            payload["brief_chars"] = len(payload.get("brief") or "")
            return payload
        return {
            "brief":       None,
            "brief_chars": 0,
            "stale":       True,
            "source":      _tier.NONE,
            **_tier.describe(_tier.NONE, reason="上游缺失,且兜底生成抛异常"),
            "message":     "Macro brief unavailable — data fetch failed.",
        }
