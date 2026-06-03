"""
Narrative Engine — Aggregates social/orderflow/trend into NarrativeSignal
===========================================================
Final aggregation layer for NMA (Narrative-Market Alignment) scoring.

NarrativeSignal schema:
  - symbol: str
  - timestamp: str
  - nma_score: float          # 0-100 weighted total
  - social_score: float       # 40% weight
  - trend_score: float        # 30% weight
  - orderflow_score: float   # 30% weight
  - signal: str               # STRONG_NARRATIVE / NARRATIVE_FADE / NEUTRAL
  - confidence: float         # 0.0-1.0
  - nma_7d_delta: float       # 7-day momentum change
  - social_raw: dict
  - trend_raw: dict
  - orderflow_raw: dict

CIS injection:
  - NMA > 65: S pillar +10-15%
  - NMA < 40: S pillar -5-10%
  - else: no change

Author: CometCloud Intelligence
"""

import asyncio
import logging
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional

_logger = logging.getLogger(__name__)

# ── NarrativeSignal dataclass ───────────────────────────────────────────────────

@dataclass
class NarrativeSignal:
    symbol: str
    timestamp: str
    nma_score: float          # 0-100 weighted total
    social_score: float       # 40% weight
    trend_score: float        # 30% weight
    orderflow_score: float    # 30% weight
    signal: str               # STRONG_NARRATIVE / NARRATIVE_FADE / NEUTRAL
    confidence: float         # 0.0-1.0
    nma_7d_delta: float     # 7d momentum change
    # Raw sub-scores for debugging
    twitter_score: float
    reddit_score: float
    news_sentiment: float
    bid_imbalance: float
    funding_divergence: float
    google_trend: float
    # Metadata
    data_complete: bool       # True if all 3 sources returned data

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


# ── Weights for NMA aggregation ───────────────────────────────────────────────

_NMA_WEIGHTS = {
    "social":   0.40,
    "trend":    0.30,
    "orderflow": 0.30,
}


def _score_to_signal(nma_score: float, confidence: float) -> str:
    """Map NMA score to signal label."""
    if nma_score >= 65 and confidence >= 0.6:
        return "STRONG_NARRATIVE"
    elif nma_score <= 40 and confidence >= 0.6:
        return "NARRATIVE_FADE"
    else:
        return "NEUTRAL"


def _compute_confidence(social_ok: bool, trend_ok: bool, orderflow_ok: bool) -> float:
    """
    Confidence based on data completeness and source quality.
    Returns 0.0-1.0.
    """
    score = 0.0
    if social_ok:    score += 0.40
    if trend_ok:     score += 0.30
    if orderflow_ok: score += 0.30
    return min(1.0, score / 0.70)  # Normalise to 1.0 if at least 2/3 sources present


# ── Main aggregation function ─────────────────────────────────────────────────

async def compute_narrative_signal(
    symbol: str,
    coin_id: str,
    social_collector,
    orderflow_collector,
    google_trend_keyword: str = None,
) -> NarrativeSignal:
    """
    Aggregate social + orderflow + trend data into a NarrativeSignal.

    Args:
        symbol:           Asset symbol (e.g. "BTC")
        coin_id:          CoinGecko coin ID (e.g. "bitcoin")
        social_collector: social_collector module
        orderflow_collector: orderflow_collector module
        google_trend_keyword: keyword for Google Trends (default: symbol.lower())
    """
    keyword = google_trend_keyword or symbol.lower()

    # ── Parallel fetch all three sources ──────────────────────────────────────
    social_fut  = social_collector.get_social_signals(coin_id)
    trend_fut    = social_collector.get_google_trend_score(keyword, days=7)
    orderflow_fut = orderflow_collector.batch_orderflow([symbol])

    social_data, trend_data, orderflow_data = await asyncio.gather(
        social_fut, trend_fut, orderflow_fut
    )

    of = orderflow_data.get(symbol, {})
    social_ok = "error" not in social_data and social_data.get("social_score", 0) > 0
    trend_ok  = "error" not in trend_data   and trend_data.get("trend_score", 0) > 0
    orderflow_ok = "error" not in of        and of.get("bid_imbalance", None) is not None

    # ── Sub-scores ─────────────────────────────────────────────────────────────
    social_score   = social_data.get("social_score",   50.0) or 50.0
    trend_score    = trend_data.get("trend_score",     50.0) or 50.0
    twitter_score  = social_data.get("twitter_score",  50.0) or 50.0
    reddit_score   = social_data.get("reddit_score",   50.0) or 50.0
    news_sentiment = social_data.get("news_sentiment", 50.0) or 50.0

    # Orderflow score: derived from bid_imbalance + funding_divergence
    bid_imbalance  = of.get("bid_imbalance", 0.0) or 0.0
    funding_div     = of.get("divergence_pct", 0.0) or 0.0
    # Scale bid_imbalance (-1 to +1) to (0 to 100)
    orderflow_raw_score = (bid_imbalance + 1) / 2 * 100  # 0 at -1, 50 at 0, 100 at +1
    # Funding divergence: if abs(div) > 20% that's notable; cap at ±50%
    funding_score = max(0, min(100, 50 + funding_div / 2))  # 50 neutral, 0-100 range
    orderflow_score = (orderflow_raw_score * 0.6 + funding_score * 0.4)

    # ── NMA composite ──────────────────────────────────────────────────────────
    nma_score = round(
        social_score   * _NMA_WEIGHTS["social"]   +
        trend_score    * _NMA_WEIGHTS["trend"]    +
        orderflow_score * _NMA_WEIGHTS["orderflow"],
        1,
    )

    confidence  = _compute_confidence(social_ok, trend_ok, orderflow_ok)
    signal      = _score_to_signal(nma_score, confidence)

    # 7d delta: compare current vs prior week (approximated from trend data)
    nma_7d_delta = 0.0  # Would require historical storage; placeholder

    result = NarrativeSignal(
        symbol           = symbol.upper(),
        timestamp        = datetime.now(timezone.utc).isoformat(),
        nma_score        = nma_score,
        social_score     = round(social_score,   1),
        trend_score      = round(trend_score,    1),
        orderflow_score  = round(orderflow_score, 1),
        signal           = signal,
        confidence       = round(confidence, 2),
        nma_7d_delta     = nma_7d_delta,
        twitter_score    = round(twitter_score,  1),
        reddit_score     = round(reddit_score,   1),
        news_sentiment   = round(news_sentiment, 1),
        bid_imbalance    = round(bid_imbalance,  4),
        funding_divergence = round(funding_div, 4),
        google_trend     = round(trend_data.get("trend_score", 50.0), 1),
        data_complete    = social_ok and trend_ok and orderflow_ok,
    )
    return result


async def batch_narrative_signals(
    symbols: list[str],
    social_collector,
    orderflow_collector,
) -> dict[str, NarrativeSignal]:
    """
    Compute NarrativeSignals for multiple assets in parallel.
    Returns: {symbol: NarrativeSignal}
    """
    COINGECKO_IDS = {
        "BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana",
        "BNB": "binancecoin", "XRP": "ripple", "ADA": "cardano",
        "AVAX": "avalanche-2", "DOT": "polkadot", "NEAR": "near",
        "SUI": "sui", "APT": "aptos", "HYPE": "hyperliquid",
        "ARB": "arbitrum", "OP": "optimism", "LINK": "chainlink",
        "UNI": "uniswap", "AAVE": "aave", "MKR": "maker",
    }

    tasks = [
        compute_narrative_signal(
            symbol   = sym,
            coin_id  = COINGECKO_IDS.get(sym, sym.lower()),
            social_collector  = social_collector,
            orderflow_collector = orderflow_collector,
        )
        for sym in symbols
    ]

    signals = {}
    for sig in await asyncio.gather(*tasks, return_exceptions=True):
        if isinstance(sig, Exception):
            _logger.warning(f"[narrative_engine] batch failed for a symbol: {sig}")
            continue
        signals[sig.symbol] = sig

    return signals


# ── CIS S-pillar modifier ──────────────────────────────────────────────────────

def compute_narrative_modifier(nma_score: float) -> float:
    """
    Compute S-pillar modifier from NMA score.
    Applied as ±% adjustment to S pillar score.

    Returns:
      > 65: +0.10 to +0.15 (positive narrative boost)
      < 40: -0.05 to -0.10 (negative narrative drag)
      else:  0.0 (no change)
    """
    if nma_score >= 65:
        # Linearly interpolate: 65→+10%, 80→+15%
        modifier = 0.10 + (nma_score - 65) / (80 - 65) * 0.05
        return round(min(0.15, modifier), 3)
    elif nma_score <= 40:
        # Linearly interpolate: 40→-5%, 25→-10%
        modifier = -0.05 - (40 - nma_score) / (40 - 25) * 0.05
        return round(max(-0.10, modifier), 3)
    else:
        return 0.0


def apply_narrative_to_s_pillar(s_pillar_base: float, nma_score: float) -> float:
    """
    Apply narrative modifier to base S pillar score.

    Args:
        s_pillar_base: Base S pillar score (0-100)
        nma_score: NMA score (0-100)

    Returns:
        Adjusted S pillar score, clamped to [0, 100]
    """
    modifier = compute_narrative_modifier(nma_score)
    adjusted = s_pillar_base * (1 + modifier)
    return round(max(0.0, min(100.0, adjusted)), 1)


# ── Standalone test ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    from data.narrative import social_collector, orderflow_collector

    async def _test():
        logging.basicConfig(level=logging.INFO)
        print("=== BTC Narrative Signal ===")
        sig = await compute_narrative_signal(
            symbol   = "BTC",
            coin_id  = "bitcoin",
            social_collector  = social_collector,
            orderflow_collector = orderflow_collector,
        )
        print(sig.to_dict())

        print("\n=== Modifier Test ===")
        for nma in [30, 40, 50, 60, 65, 75, 85]:
            mod = compute_narrative_modifier(nma)
            adjusted = apply_narrative_to_s_pillar(60.0, nma)
            print(f"  NMA={nma:3d} → modifier={mod:+.2%} → S_adj={adjusted:.1f}")

    asyncio.run(_test())