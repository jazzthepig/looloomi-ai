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
_REDIS_TTL      = 43200   # 12 hours — briefs are twice daily
_AUTO_TTL       = 3600    # 1 hour TTL for auto-generated briefs
_AUTO_STALE     = 3600    # regenerate auto-brief after 1 hour


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
            # S-180 (2026-08-20). Was `stale-while-revalidate=3600`, which lets a
            # CDN edge keep serving an expired brief for a further HOUR while it
            # refreshes behind the scenes. On a warm edge (the phone you use every
            # day) you never notice; on a cold one you get a copy up to 70 minutes
            # old, which is exactly the "从别的手机登陆看是滞后的" report.
            #
            # SWR is the right tool for content whose staleness is cosmetic. A
            # macro brief is read as a statement about the market right now, so
            # its staleness is not cosmetic — and an hour of it is longer than the
            # 30-minute cadence that produces it, meaning the window could span an
            # entire missed update. Cut to 5 minutes: still absorbs a thundering
            # herd, no longer outlives the thing it caches.
            response.headers["Cache-Control"] = "public, max-age=600, stale-while-revalidate=300"
            return {
                "brief":        brief_text,
                "brief_chars":  len(brief_text),
                "market_data":  data.get("market_data"),
                "model":        data.get("model"),
                "generated_at": data.get("generated_at"),
                "received_at":  data.get("received_at"),
                "age_seconds":  age,
                "stale":        age > _REDIS_TTL,
                "source":       source,
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
            "source":       "auto",
        }
        # Cache with 1h TTL so it refreshes regularly
        await redis_set_key(_REDIS_KEY, payload, ttl=_AUTO_TTL)
        _logger.info(f"[MACRO] Auto-generated brief from macro-pulse data — {len(brief_text)} chars")

        return {**payload, "age_seconds": 0, "stale": False}

    except Exception as e:
        _logger.error(f"[MACRO] Auto-generate failed: {e}", exc_info=True)
        # Last resort: return stale data or empty
        if data:
            age = now - data.get("received_at", 0)
            payload = {**data, "age_seconds": age, "stale": True, "source": data.get("source", "mac_mini")}
            payload["brief_chars"] = len(payload.get("brief") or "")
            return payload
        return {
            "brief":       None,
            "brief_chars": 0,
            "stale":       True,
            "source":      "none",
            "message":     "Macro brief unavailable — data fetch failed.",
        }
