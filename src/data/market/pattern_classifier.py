"""
Pattern Library — Pre-compiled decision tree for market pattern classification
===================================================================
4预编译形态:
  TREND_FOLLOWER    — MACD>0持续X小时, MA5>MA20>MA60, 成交量放量
  MOMENTUM_REVERSAL — RSI连续N根<35, MACD底背离, 成交量收缩>50%
  RANGE_BOUND      — Bollinger带宽<threshold, RSI在40-60游走, OI横盘
  BREAKOUT         — 波动率压缩后突破, vol>2xMA, BTC_DOM确认

Each pattern returns:
  - pattern_type: str (one of 4 above)
  - confidence: float (0.0-1.0)
  - signal: str (BULLISH / BEARISH / NEUTRAL)
  - match_reasons: list[str] — which conditions were met

Author: CometCloud Intelligence
"""

import logging
from dataclasses import dataclass, asdict
from typing import Optional

_logger = logging.getLogger(__name__)

# ── Pattern definitions ───────────────────────────────────────────────────────

@dataclass
class PatternMatch:
    pattern_type: str       # TREND_FOLLOWER / MOMENTUM_REVERSAL / RANGE_BOUND / BREAKOUT
    confidence: float       # 0.0-1.0
    signal: str             # BULLISH / BEARISH / NEUTRAL
    match_reasons: list[str]  # which sub-conditions fired
    pattern_weight: float   # base weight of this pattern type

    def to_dict(self) -> dict:
        return asdict(self)


# ── Indicator calculations ────────────────────────────────────────────────────

def compute_ema(prices: list[float], period: int) -> list[float]:
    """Exponential Moving Average."""
    if len(prices) < period:
        return []
    k = 2 / (period + 1)
    ema = [prices[0]]
    for p in prices[1:]:
        ema.append(p * k + ema[-1] * (1 - k))
    return ema


def compute_macd(prices: list[float], fast: int = 12, slow: int = 26, signal: int = 9):
    """
    MACD line, signal line, histogram.
    Returns: (macd_line, signal_line, histogram)
    """
    if len(prices) < slow:
        return [], [], []
    ema_fast = compute_ema(prices, fast)
    ema_slow = compute_ema(prices, slow)
    macd_line = [f - s for f, s in zip(ema_fast, ema_slow)]
    sig = compute_ema(macd_line, signal)
    hist = [m - s for m, s in zip(macd_line, sig)]
    return macd_line, sig, hist


def compute_rsi(prices: list[float], period: int = 14) -> list[float]:
    """RSI over N periods."""
    if len(prices) < period + 1:
        return []
    deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    gains = [max(d, 0) for d in deltas]
    losses = [abs(min(d, 0)) for d in deltas]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    rsi_values = [50.0]  # seed
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            rsi_values.append(100.0)
        else:
            rs = avg_gain / avg_loss
            rsi_values.append(100 - 100 / (1 + rs))
    return rsi_values


def compute_bollinger(prices: list[float], period: int = 20, std_mult: float = 2.0):
    """
    Bollinger Bands: middle (20EMA), upper, lower, bandwidth.
    Returns: (upper, middle, lower, bandwidth)
    """
    if len(prices) < period:
        return [], [], [], []
    middle = compute_ema(prices, period)
    # Rolling std
    stds = []
    for i in range(period - 1, len(prices)):
        slice_ = prices[i - period + 1: i + 1]
        mean = sum(slice_) / period
        variance = sum((p - mean) ** 2 for p in slice_) / period
        stds.append(variance ** 0.5)
    upper = [middle[i] + std_mult * stds[i] for i in range(len(stds))]
    lower = [middle[i] - std_mult * stds[i] for i in range(len(stds))]
    bandwidth = [(upper[i] - lower[i]) / middle[i] if middle[i] != 0 else 0 for i in range(len(stds))]
    return upper, middle, lower, bandwidth


def compute_volume_profile(volumes: list[float], window: int = 20) -> dict:
    """Volume stats: current vs MA, momentum."""
    if len(volumes) < window:
        return {"current": 0, "ma": 0, "ratio": 1.0, "momentum": 0.0}
    ma = sum(volumes[-window:]) / window
    current = volumes[-1] if volumes else 0
    ratio = current / ma if ma > 0 else 1.0
    # 5-bar momentum: volume now vs 5 bars ago
    if len(volumes) >= 5:
        mom = (volumes[-1] - volumes[-5]) / volumes[-5] if volumes[-5] != 0 else 0.0
    else:
        mom = 0.0
    return {"current": current, "ma": ma, "ratio": ratio, "momentum": mom}


# ── Pattern classifiers ───────────────────────────────────────────────────────

def classify_trend_follower(
    prices: list[float],
    volumes: list[float],
    macd_line: list[float],
    macd_signal: list[float],
    macd_hist: list[float],
    ema_fast: list[float],
    ema_mid: list[float],
    ema_slow: list[float],
    threshold_macd_positive: float = 0.0,
    min_ema_bull_crosses: int = 1,
) -> Optional[PatternMatch]:
    """
    TREND_FOLLOWER conditions:
      1. MACD histogram positive for last N bars
      2. MA5 > MA20 > MA60 (full bull alignment)
      3. Volume surge vs 20-bar MA
    """
    reasons = []
    lookback = min(5, len(macd_hist))
    if lookback == 0:
        return None

    # Condition 1: MACD histogram positive (bullish momentum)
    hist_positive = all(h >= threshold_macd_positive for h in macd_hist[-lookback:])
    if hist_positive:
        reasons.append("MACD_histogram_positive")

    # Condition 2: EMA triple bull alignment
    if len(ema_fast) >= 3 and len(ema_mid) >= 3 and len(ema_slow) >= 3:
        if ema_fast[-1] > ema_mid[-1] > ema_slow[-1]:
            reasons.append("EMA_bull_alignment")

    # Condition 3: Volume surge
    vp = compute_volume_profile(volumes)
    if vp["ratio"] >= 1.5:
        reasons.append(f"Volume_surge_{vp['ratio']:.1f}x")

    if len(reasons) < 2:
        return None  # need at least 2/3 conditions

    confidence = min(1.0, len(reasons) / 3.0 + 0.3)
    return PatternMatch(
        pattern_type="TREND_FOLLOWER",
        confidence=round(confidence, 2),
        signal="BULLISH",
        match_reasons=reasons,
        pattern_weight=0.25,
    )


def classify_momentum_reversal(
    prices: list[float],
    volumes: list[float],
    rsi_values: list[float],
    macd_hist: list[float],
    lookback_rsi: int = 5,
    rsi_oversold: float = 35.0,
) -> Optional[PatternMatch]:
    """
    MOMENTUM_REVERSAL conditions:
      1. RSI oversold for N consecutive bars (RSI < 35)
      2. MACD histogram bottoming (divergence detection)
      3. Volume contraction > 50% vs 20-bar MA
    """
    reasons = []
    if not rsi_values or len(rsi_values) < lookback_rsi:
        return None

    # Condition 1: RSI oversold consecutive bars
    if all(r < rsi_oversold for r in rsi_values[-lookback_rsi:]):
        reasons.append(f"RSI_oversold_{lookback_rsi}b")

    # Condition 2: MACD histogram turning up (from negative toward zero)
    if len(macd_hist) >= 3:
        recent = macd_hist[-3:]
        if recent[-1] > recent[-2] > recent[-3] and recent[-1] > 0:
            reasons.append("MACD_histogram_recovering")
        elif recent[-1] > recent[-2] and recent[-1] > -0.5:  # still neg but bottomed
            reasons.append("MACD_histogram_bottoming")

    # Condition 3: Volume contraction
    vp = compute_volume_profile(volumes)
    if vp["ratio"] < 0.5:
        reasons.append(f"Volume_contraction_{vp['ratio']:.1f}x")

    if len(reasons) < 2:
        return None

    confidence = min(1.0, len(reasons) / 3.0 + 0.25)
    return PatternMatch(
        pattern_type="MOMENTUM_REVERSAL",
        confidence=round(confidence, 2),
        signal="BULLISH",
        match_reasons=reasons,
        pattern_weight=0.30,
    )


def classify_range_bound(
    prices: list[float],
    volumes: list[float],
    rsi_values: list[float],
    bollinger_bandwidth: list[float],
    bandwidth_threshold: float = 0.05,
) -> Optional[PatternMatch]:
    """
    RANGE_BOUND conditions:
      1. Bollinger bandwidth < threshold (volatility compression)
      2. RSI oscillating in neutral zone (40-60)
      3. OI (volume proxy) relatively flat — no directional bets
    """
    reasons = []

    # Condition 1: Low Bollinger bandwidth (volatility compression → potential breakout setup)
    if bollinger_bandwidth and len(bollinger_bandwidth) >= 3:
        recent_bw = bollinger_bandwidth[-3:]
        if all(bw < bandwidth_threshold for bw in recent_bw):
            reasons.append(f"Bollinger_compressed_{recent_bw[-1]:.3f}")

    # Condition 2: RSI in neutral zone (40-60 = no overbought/oversold)
    if rsi_values and len(rsi_values) >= 3:
        recent_rsi = rsi_values[-3:]
        if all(40 <= r <= 60 for r in recent_rsi):
            reasons.append("RSI_neutral_zone")

    # Condition 3: Volume flat (no surge)
    vp = compute_volume_profile(volumes)
    if 0.7 <= vp["ratio"] <= 1.3:
        reasons.append("Volume_stable")

    if len(reasons) < 2:
        return None

    confidence = min(1.0, len(reasons) / 3.0 + 0.25)
    return PatternMatch(
        pattern_type="RANGE_BOUND",
        confidence=round(confidence, 2),
        signal="NEUTRAL",
        match_reasons=reasons,
        pattern_weight=0.20,
    )


def classify_breakout(
    prices: list[float],
    volumes: list[float],
    bollinger_upper: list[float],
    bollinger_lower: list[float],
    macd_hist: list[float],
    btc_dom: Optional[float] = None,
    vol_ratio_threshold: float = 2.0,
) -> Optional[PatternMatch]:
    """
    BREAKOUT conditions:
      1. Volatility compression followed by Bollinger expansion
      2. Volume > 2x 20-bar MA (confirming breakout)
      3. BTC dominance confirming cross-asset momentum
    """
    reasons = []

    if not bollinger_upper or not bollinger_lower or len(bollinger_upper) < 3:
        return None

    # Condition 1: Bandwidth expanding (volatility break)
    bw_recent = bollinger_upper[-1] - bollinger_lower[-1]
    bw_prev   = bollinger_upper[-3] - bollinger_lower[-3] if len(bollinger_upper) >= 3 else bw_recent
    if bw_recent > bw_prev * 1.5:
        reasons.append("Bollinger_expansion")

    # Condition 2: Volume surge confirming breakout
    vp = compute_volume_profile(volumes)
    if vp["ratio"] >= vol_ratio_threshold:
        reasons.append(f"Volume_confirms_{vp['ratio']:.1f}x")

    # Condition 3: MACD histogram positive (momentum behind breakout)
    if macd_hist and len(macd_hist) >= 1 and macd_hist[-1] > 0:
        reasons.append("MACD_bullish")

    # Condition 4 (optional): BTC DOM strength
    if btc_dom is not None and btc_dom > 55:
        reasons.append("BTC_DOM_confirm")

    if len(reasons) < 2:
        return None

    confidence = min(1.0, len(reasons) / 4.0 + 0.3)
    # Breakout signal: BULLISH if volume+MACD, BEARISH if expanding but vol low
    signal = "BULLISH" if vp["ratio"] >= 1.5 and (macd_hist and macd_hist[-1] > 0) else "NEUTRAL"
    return PatternMatch(
        pattern_type="BREAKOUT",
        confidence=round(confidence, 2),
        signal=signal,
        match_reasons=reasons,
        pattern_weight=0.25,
    )


# ── Main pattern classifier ────────────────────────────────────────────────────

def classify_pattern(
    prices: list[float],
    volumes: list[float],
    btc_dom: Optional[float] = None,
    oi_data: Optional[dict] = None,  # optional open interest dict
) -> Optional[PatternMatch]:
    """
    Classify which pattern best matches current market structure.
    Returns the highest-confidence match among all 4 patterns.

    Args:
        prices:    list of close prices (at least 60 for full pattern)
        volumes:   list of volumes (same length as prices)
        btc_dom:   BTC dominance % (optional)
        oi_data:   dict with oi_change_pct_24h (optional)

    Returns:
        PatternMatch or None if no pattern qualifies (confidence >= 0.4 required)
    """
    if len(prices) < 30:
        return None

    min_required = 60

    # Compute all indicators
    ema_fast = compute_ema(prices, 5)
    ema_mid  = compute_ema(prices, 20)
    ema_slow = compute_ema(prices, 60)
    macd_line, macd_signal, macd_hist = compute_macd(prices)
    rsi_values = compute_rsi(prices, period=14)
    bollinger_upper, _, bollinger_lower, bollinger_bandwidth = compute_bollinger(prices)

    # Run all 4 classifiers
    classifiers = [
        classify_trend_follower(prices, volumes, macd_line, macd_signal, macd_hist, ema_fast, ema_mid, ema_slow),
        classify_momentum_reversal(prices, volumes, rsi_values, macd_hist),
        classify_range_bound(prices, volumes, rsi_values, bollinger_bandwidth),
        classify_breakout(prices, volumes, bollinger_upper, bollinger_lower, macd_hist, btc_dom),
    ]

    # Filter to valid matches (confidence >= 0.4)
    valid = [c for c in classifiers if c is not None and c.confidence >= 0.40]
    if not valid:
        return None

    # Return highest confidence
    best = max(valid, key=lambda x: x.confidence)
    return best


# ── Batch pattern classifier for multiple assets ───────────────────────────────

def batch_classify_patterns(
    price_data: dict[str, list[float]],
    volume_data: dict[str, list[float]],
    btc_dom: Optional[float] = None,
) -> dict[str, PatternMatch]:
    """
    Classify patterns for multiple assets.
    price_data: {symbol: [prices]}
    volume_data: {symbol: [volumes]}
    Returns: {symbol: PatternMatch}
    """
    results = {}
    for symbol in price_data:
        vols = volume_data.get(symbol, [])
        match = classify_pattern(price_data[symbol], vols, btc_dom=btc_dom)
        if match:
            results[symbol] = match
    return results


# ── Standalone test ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import asyncio

    async def _test():
        logging.basicConfig(level=logging.INFO)
        # Synthetic test data
        import random
        random.seed(42)

        # Generate 100 bars of synthetic price data — trending up
        base_price = 50000
        prices = []
        p = base_price
        for i in range(100):
            p = p * (1 + random.uniform(-0.02, 0.03))
            prices.append(p)
        volumes = [random.uniform(1e8, 5e8) for _ in range(100)]

        print("=== Synthetic trending data ===")
        match = classify_pattern(prices, volumes, btc_dom=58.0)
        if match:
            print(f"Pattern: {match.pattern_type}")
            print(f"Confidence: {match.confidence}")
            print(f"Signal: {match.signal}")
            print(f"Reasons: {match.match_reasons}")
        else:
            print("No pattern matched (need >30 bars, confidence>=0.40)")

        # Range-bound test
        print("\n=== Synthetic range-bound data ===")
        flat_prices = [50000 + random.uniform(-200, 200) for _ in range(100)]
        flat_volumes = [1e8 + random.uniform(-1e7, 1e7) for _ in range(100)]
        match2 = classify_pattern(flat_prices, flat_volumes, btc_dom=52.0)
        if match2:
            print(f"Pattern: {match2.pattern_type}, confidence={match2.confidence}, signal={match2.signal}")
        else:
            print("No pattern matched")

    asyncio.run(_test())