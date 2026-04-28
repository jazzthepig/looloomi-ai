"""
Macro Brief router — receives AI-generated macro analysis from Mac Mini,
stores in Redis, and serves to the dashboard.

Endpoints:
  POST /internal/macro-brief  — Mac Mini pushes analysis (same auth as CIS)
  GET  /api/v1/macro/brief    — Dashboard reads latest brief (auto-generates if empty)
"""
import os, json, time
from datetime import datetime

import logging
from fastapi import APIRouter, HTTPException, Header

from src.api.store import redis_set_key, redis_get_key

_logger = logging.getLogger(__name__)

router = APIRouter()

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
        "STAGFLATION":  ("Stagflation signals present.", "Commodities, RWA, and BTC as inflation hedges. Avoid high-beta altcoins."),
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

*Auto-generated from live market data. Mac Mini LLM brief updates 2× daily when available.*"""

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

    payload["received_at"] = int(time.time())
    payload["source"] = "mac_mini"

    ok = await redis_set_key(_REDIS_KEY, payload, ttl=_REDIS_TTL)
    if not ok:
        raise HTTPException(status_code=502, detail="Redis write failed")

    _logger.info(f"[MACRO] Brief received — {len(payload['brief'])} chars, model={payload.get('model', '?')}")
    return {
        "status": "ok",
        "chars": len(payload["brief"]),
        "key": _REDIS_KEY,
    }


# ── Public read (with inline auto-generation fallback) ───────────────────────

@router.get("/api/v1/macro/brief")
async def get_macro_brief():
    """
    Returns the latest macro brief from Redis.
    If empty or stale >1h, auto-generates a data-driven brief from live macro-pulse
    and caches it — no Mac Mini or LLM required.
    """
    data = await redis_get_key(_REDIS_KEY)
    now  = int(time.time())

    # Serve LLM brief if fresh
    if data:
        age    = now - data.get("received_at", 0)
        source = data.get("source", "mac_mini")
        # Always serve Mac Mini LLM briefs until they expire (12h TTL)
        if source == "mac_mini" or age < _AUTO_STALE:
            return {
                "brief":        data.get("brief"),
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
            "market_data":  mp,
            "model":        "template",
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "received_at":  now,
            "source":       "auto",
        }
        # Cache with 1h TTL so it refreshes regularly
        await redis_set_key(_REDIS_KEY, payload, ttl=_AUTO_TTL)
        _logger.info("[MACRO] Auto-generated brief from macro-pulse data")

        return {**payload, "age_seconds": 0, "stale": False}

    except Exception as e:
        _logger.error(f"[MACRO] Auto-generate failed: {e}", exc_info=True)
        # Last resort: return stale data or empty
        if data:
            age = now - data.get("received_at", 0)
            return {**data, "age_seconds": age, "stale": True, "source": data.get("source", "mac_mini")}
        return {
            "brief":   None,
            "stale":   True,
            "source":  "none",
            "message": "Macro brief unavailable — data fetch failed.",
        }
