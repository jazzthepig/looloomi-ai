"""
Three-Layer Signal Resonance Engine
====================================
Layer 1 (价格，滞后):     RSI, MACD, Bollinger, EMA cross
Layer 2 (量价，同步):     成交量突变, OI change, orderbook imbalance, funding rate divergence
Layer 3 (情绪，领先):     news sentiment, whale movement, 交易所净流入

共振决策树:
  IF Layer1 ≥ 2 signals bullish
  AND Layer2 ≥ 1 confirm
  AND Layer3 ≥ 1 confirm
  → STRONG SIGNAL (entry_tag: RESONANCE_LONG)

  IF Layer1 bearish AND Layer2 confirm → NO ENTRY
  IF Layer1 neutral OR signals disagree → NO TRADE

Returns:
  - resonance_score: float (0.0-1.0)
  - conviction: str (STRONG_LONG / LONG / NEUTRAL / NO_ENTRY)
  - dominant_layer: str
  - layer_scores: dict{L1, L2, L3}
  - key_drivers: list[str]
  - confidence: float

Author: CometCloud Intelligence
"""

import logging
from dataclasses import dataclass, asdict
from typing import Optional

_logger = logging.getLogger(__name__)

# ── Layer score dataclass ─────────────────────────────────────────────────────

@dataclass
class ResonanceResult:
    resonance_score: float   # 0.0-1.0 composite
    conviction: str         # STRONG_LONG / LONG / NEUTRAL / NO_ENTRY
    dominant_layer: str      # which layer drives the signal
    confidence: float        # 0.0-1.0
    layer_scores: dict       # {L1: float, L2: float, L3: float}
    key_drivers: list[str]   # top contributing factors
    pattern_context: str     # description of market context

    def to_dict(self) -> dict:
        return asdict(self)


# ── Layer 1: Price-based (lagging) indicators ─────────────────────────────────

def score_layer1(
    prices: list[float],
    volumes: list[float],
    rsi: Optional[list[float]] = None,
    macd_hist: Optional[list[float]] = None,
    ema_fast: Optional[list[float]] = None,
    ema_slow: Optional[list[float]] = None,
    bb_upper: Optional[list[float]] = None,
    bb_lower: Optional[list[float]] = None,
) -> tuple[float, list[str]]:
    """
    Score Layer 1 (price-based, lagging) signals.
    Range: 0.0 to 1.0 (1.0 = strongly bullish)

    Signals checked:
      - RSI > 60 (bullish) or RSI < 40 (bearish)
      - MACD histogram positive
      - EMA bull cross (fast > slow)
      - Price near upper Bollinger (breakout) or lower (reversal setup)
    """
    score = 0.5  # neutral baseline
    drivers = []

    # RSI
    if rsi and len(rsi) >= 1:
        r = rsi[-1]
        if r > 70:
            score += 0.15
            drivers.append("RSI_overbought")
        elif r > 60:
            score += 0.10
            drivers.append("RSI_bullish_zone")
        elif r < 30:
            score -= 0.15
            drivers.append("RSI_oversold")
        elif r < 40:
            score -= 0.10
            drivers.append("RSI_bearish_zone")

    # MACD histogram
    if macd_hist and len(macd_hist) >= 1:
        h = macd_hist[-1]
        if h > 0:
            score += 0.15
            drivers.append("MACD_histogram_positive")
        else:
            score -= 0.10
            drivers.append("MACD_histogram_negative")

    # EMA cross
    if ema_fast and ema_slow and len(ema_fast) >= 1 and len(ema_slow) >= 1:
        ef = ema_fast[-1]
        es = ema_slow[-1]
        if ef > es:
            score += 0.15
            drivers.append("EMA_bull_cross")
        else:
            score -= 0.10
            drivers.append("EMA_bear_cross")

    # Bollinger position
    if bb_upper and bb_lower and len(bb_upper) >= 1 and len(prices) >= 1:
        p = prices[-1]
        upper = bb_upper[-1]
        lower = bb_lower[-1]
        mid = (upper + lower) / 2
        band = upper - lower
        if band > 0:
            position = (p - lower) / band  # 0 = at lower, 1 = at upper
            if position > 0.85:
                score += 0.10
                drivers.append("Price_upper_Bollinger")
            elif position < 0.15:
                score -= 0.10
                drivers.append("Price_lower_Bollinger")

    score = max(0.0, min(1.0, score))
    return round(score, 3), drivers


# ── Layer 2: Orderflow (synchronous) ─────────────────────────────────────────

def score_layer2(
    bid_imbalance: float = 0.0,       # -1 to +1 (from Binance depth)
    funding_rate: float = 0.0,        # annualised %
    funding_divergence: float = 0.0,  # % deviation from 7d avg
    oi_change_pct: float = 0.0,       # OI change 24h %
    volume_surge_ratio: float = 1.0,  # current / 20-bar MA
) -> tuple[float, list[str]]:
    """
    Score Layer 2 (orderflow, synchronous) signals.
    Range: 0.0 to 1.0

    Signals:
      - Bid imbalance > 0 (buyers dominating)
      - Funding rate positive but not excessive (bullish leverage)
      - Funding divergence > 0 (funding increasing vs avg)
      - OI increasing (position building)
      - Volume surge confirming directional flow
    """
    score = 0.5
    drivers = []

    # Bid imbalance: map -1..+1 to 0..1
    # +0.5 means buyers dominating; +1.0 = extreme bid side
    bid_score = (bid_imbalance + 1) / 2  # 0 at -1, 0.5 at 0, 1 at +1
    if bid_imbalance > 0.3:
        score += 0.20
        drivers.append(f"Bid_imbalance_{bid_imbalance:.2f}")
    elif bid_imbalance < -0.3:
        score -= 0.15
        drivers.append(f"Bid_imbalance_{bid_imbalance:.2f}")

    # Funding rate: positive = bullish leverage, but >5% annual = warning sign
    if funding_rate > 0.01:  # 1% annual = 0.01 in fraction
        score += 0.10
        drivers.append(f"Funding_positive_{funding_rate:.4f}")
    elif funding_rate < -0.01:
        score -= 0.10
        drivers.append(f"Funding_negative_{funding_rate:.4f}")

    # Funding divergence: current vs avg
    if funding_divergence > 10:  # >10% above avg
        score += 0.15
        drivers.append(f"Funding_divergence_{funding_divergence:.1f}%")
    elif funding_divergence < -10:
        score -= 0.10
        drivers.append(f"Funding_divergence_{funding_divergence:.1f}%")

    # OI change
    if oi_change_pct > 10:
        score += 0.15
        drivers.append(f"OI_surge_{oi_change_pct:.1f}%")
    elif oi_change_pct < -10:
        score -= 0.10
        drivers.append(f"OI_drop_{oi_change_pct:.1f}%")

    # Volume surge
    if volume_surge_ratio >= 2.0:
        score += 0.15
        drivers.append(f"Volume_surge_{volume_surge_ratio:.1f}x")
    elif volume_surge_ratio < 0.5:
        score -= 0.10
        drivers.append(f"Volume_contraction_{volume_surge_ratio:.1f}x")

    score = max(0.0, min(1.0, score))
    return round(score, 3), drivers


# ── Layer 3: Sentiment (leading) ──────────────────────────────────────────────

def score_layer3(
    nma_score: float = 50.0,          # 0-100 NMA narrative score
    news_sentiment: float = 50.0,     # 0-100 news sentiment
    social_score: float = 50.0,       # 0-100 social score
    google_trend_score: float = 50.0, # 0-100 Google trend score
) -> tuple[float, list[str]]:
    """
    Score Layer 3 (sentiment, leading) signals.
    Range: 0.0 to 1.0

    Signals:
      - NMA score > 65 (STRONG_NARRATIVE)
      - News sentiment > 60 (positive news flow)
      - Social score elevated (Twitter/Reddit activity)
      - Google trend rising (search interest)
    """
    score = 0.5
    drivers = []

    # NMA score
    if nma_score >= 65:
        score += 0.20
        drivers.append(f"NMA_STRONG_{nma_score:.1f}")
    elif nma_score <= 40:
        score -= 0.15
        drivers.append(f"NMA_FADE_{nma_score:.1f}")

    # News sentiment
    if news_sentiment >= 60:
        score += 0.15
        drivers.append(f"News_bullish_{news_sentiment:.1f}")
    elif news_sentiment <= 40:
        score -= 0.10
        drivers.append(f"News_bearish_{news_sentiment:.1f}")

    # Social score
    if social_score >= 65:
        score += 0.15
        drivers.append(f"Social_elevated_{social_score:.1f}")
    elif social_score <= 40:
        score -= 0.10
        drivers.append(f"Social_depressed_{social_score:.1f}")

    # Google trend
    if google_trend_score >= 70:
        score += 0.10
        drivers.append(f"Trend_hot_{google_trend_score:.1f}")
    elif google_trend_score <= 30:
        score -= 0.05
        drivers.append(f"Trend_cold_{google_trend_score:.1f}")

    score = max(0.0, min(1.0, score))
    return round(score, 3), drivers


# ── Resonance computation ─────────────────────────────────────────────────────

def compute_resonance(
    layer1_score: float,
    layer2_score: float,
    layer3_score: float,
    min_layer1_confirm: int = 2,  # N signals needed in Layer 1
) -> ResonanceResult:
    """
    Compute three-layer resonance signal.

    Resonance rules:
      - L1 must show ≥ 2 confirmations (bullish or bearish)
      - L2 must confirm direction (>0.55 or <0.45)
      - L3 must agree (leading indicator)
      - Overall score is weighted: L1=35%, L2=35%, L3=30%

    Conviction mapping:
      STRONG_LONG:  L1≥0.60, L2≥0.60, L3≥0.55
      LONG:         L1≥0.55, L2≥0.55, L3≥0.50
      NEUTRAL:      all layers 0.40-0.60
      NO_ENTRY:     disagreement (L1 bearish while L2/L3 bullish) or L1 weak
    """
    weights = {"L1": 0.35, "L2": 0.35, "L3": 0.30}

    composite = round(
        layer1_score * weights["L1"] +
        layer2_score * weights["L2"] +
        layer3_score * weights["L3"],
        3,
    )

    # Layer dominance
    layer_scores = {"L1": layer1_score, "L2": layer2_score, "L3": layer3_score}
    dominant = max(layer_scores, key=lambda k: layer_scores[k])

    # Confidence: based on agreement between layers
    layer_agree = 1 - abs(layer1_score - layer2_score) / 2 - abs(layer2_score - layer3_score) / 2 - abs(layer1_score - layer3_score) / 2
    confidence = round(max(0.0, min(1.0, layer_agree)), 2)

    # Conviction
    bullish_layers = sum(1 for s in layer_scores.values() if s > 0.55)
    bearish_layers = sum(1 for s in layer_scores.values() if s < 0.45)

    if layer1_score < 0.45 and layer2_score < 0.45:
        conviction = "NO_ENTRY"
    elif composite >= 0.60 and layer1_score >= 0.55 and layer2_score >= 0.55 and layer3_score >= 0.50:
        conviction = "STRONG_LONG"
    elif composite >= 0.50 and layer1_score >= 0.50 and layer2_score >= 0.50:
        conviction = "LONG"
    else:
        conviction = "NEUTRAL"

    # Key drivers
    drivers = [f"L1={layer1_score:.2f}", f"L2={layer2_score:.2f}", f"L3={layer3_score:.2f}"]

    # Pattern context description
    if conviction == "STRONG_LONG":
        context = "Strong 3-layer resonance — all layers bullish, high conviction entry"
    elif conviction == "LONG":
        context = "Moderate 3-layer resonance — 2+ layers confirm direction"
    elif conviction == "NO_ENTRY":
        context = "Layer disagreement — price momentum bearish despite orderflow/sentiment"
    else:
        context = "Mixed signals — no clear 3-layer alignment"

    return ResonanceResult(
        resonance_score=composite,
        conviction=conviction,
        dominant_layer=dominant,
        confidence=confidence,
        layer_scores=layer_scores,
        key_drivers=drivers,
        pattern_context=context,
    )


# ── Compute resonance from full market data ──────────────────────────────────

def compute_resonance_from_market(
    prices: list[float],
    volumes: list[float],
    rsi_values: list[float],
    macd_hist: list[float],
    ema_fast: list[float],
    ema_slow: list[float],
    bb_upper: list[float],
    bb_lower: list[float],
    bid_imbalance: float = 0.0,
    funding_rate: float = 0.0,
    funding_divergence: float = 0.0,
    oi_change_pct: float = 0.0,
    volume_surge_ratio: float = 1.0,
    nma_score: float = 50.0,
    news_sentiment: float = 50.0,
    social_score: float = 50.0,
    google_trend_score: float = 50.0,
) -> ResonanceResult:
    """
    Full pipeline: compute all three layers from raw market data.
    """
    l1_score, l1_drivers = score_layer1(
        prices, volumes, rsi_values, macd_hist, ema_fast, ema_slow, bb_upper, bb_lower
    )
    l2_score, l2_drivers = score_layer2(
        bid_imbalance, funding_rate, funding_divergence, oi_change_pct, volume_surge_ratio
    )
    l3_score, l3_drivers = score_layer3(
        nma_score, news_sentiment, social_score, google_trend_score
    )

    result = compute_resonance(l1_score, l2_score, l3_score)
    # Enrich drivers
    all_drivers = l1_drivers + l2_drivers + l3_drivers
    result.key_drivers = all_drivers[:5]  # top 5
    return result


# ── Standalone test ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import random
    random.seed(42)

    # Synthetic trending market
    prices = [50000 + i * 50 + random.uniform(-100, 200) for i in range(100)]
    volumes = [1e9 + random.uniform(-2e8, 5e8) for _ in range(100)]

    print("=== Trending market resonance ===")
    result = compute_resonance(0.70, 0.65, 0.60)
    print(f"Resonance score: {result.resonance_score}")
    print(f"Conviction: {result.conviction}")
    print(f"Layer scores: {result.layer_scores}")
    print(f"Context: {result.pattern_context}")

    print("\n=== Bearish divergence (no entry) ===")
    result2 = compute_resonance(0.35, 0.60, 0.55)
    print(f"Conviction: {result2.conviction}")
    print(f"Context: {result2.pattern_context}")

    print("\n=== Neutral mixed ===")
    result3 = compute_resonance(0.52, 0.48, 0.55)
    print(f"Conviction: {result3.conviction}")
    print(f"Resonance: {result3.resonance_score}")