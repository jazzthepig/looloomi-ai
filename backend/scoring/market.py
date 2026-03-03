"""
CIS Pillar M: Market Structure Score
====================================
Assesses tradability, liquidity, and price integrity.

Sub-metrics:
- Liquidity depth (TVL, order book depth)
- Trading volume (24h volume, volume/mcap ratio)
- Spread quality (bid-ask spread)
- Slippage tolerance
- Exchange support (CEX + DEX)
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class MarketInput:
    """Input data for market structure scoring"""
    # Liquidity
    tvl_usd: float = 0  # Total Value Locked
    liquidity_usd: float = 0  # Spot liquidity
    reserve_usd: float = 0  # Treasury/reserve

    # Volume
    volume_24h_usd: float = 0
    volume_7d_usd: float = 0
    market_cap_usd: float = 0

    # Spread
    bid_ask_spread_bps: float = 100  # basis points

    # Trading
    cex_listed: bool = False
    cex_count: int = 0  # Number of CEX listings
    dex_count: int = 0  # Number of DEX pools

    # Price integrity
    price_deviation_24h: float = 0  # % deviation from fair value
    has_liquid_markets: bool = True


class MarketScorer:
    """Calculate Market Structure pillar score (0-100)"""

    def score(self, inp: MarketInput) -> float:
        """Calculate market structure score"""
        liquidity_score = self._score_liquidity(inp)
        volume_score = self._score_volume(inp)
        spread_score = self._score_spread(inp)
        exchange_score = self._score_exchanges(inp)

        return round(
            liquidity_score * 0.30 +
            volume_score * 0.25 +
            spread_score * 0.20 +
            exchange_score * 0.25,
            1
        )

    def _score_liquidity(self, inp: MarketInput) -> float:
        """Score liquidity (0-100)"""
        score = 0

        # TVL (max 40)
        if inp.tvl_usd >= 1e9:  # $1B+
            score += 40
        elif inp.tvl_usd >= 100e6:  # $100M+
            score += 35
        elif inp.tvl_usd >= 10e6:  # $10M+
            score += 25
        elif inp.tvl_usd >= 1e6:  # $1M+
            score += 15
        elif inp.tvl_usd > 0:
            score += 5

        # Spot liquidity (max 35)
        if inp.liquidity_usd >= 50e6:  # $50M+
            score += 35
        elif inp.liquidity_usd >= 10e6:
            score += 25
        elif inp.liquidity_usd >= 1e6:
            score += 15
        elif inp.liquidity_usd >= 100e3:
            score += 8
        elif inp.liquidity_usd > 0:
            score += 3

        # Reserve (max 25)
        if inp.reserve_usd >= 10e6:
            score += 25
        elif inp.reserve_usd >= 1e6:
            score += 15
        elif inp.reserve_usd >= 100e3:
            score += 8
        elif inp.reserve_usd > 0:
            score += 3

        return min(100, score)

    def _score_volume(self, inp: MarketInput) -> float:
        """Score trading volume (0-100)"""
        score = 0

        # 24h volume (max 50)
        if inp.volume_24h_usd >= 100e6:
            score += 50
        elif inp.volume_24h_usd >= 10e6:
            score += 35
        elif inp.volume_24h_usd >= 1e6:
            score += 20
        elif inp.volume_24h_usd >= 100e3:
            score += 10
        elif inp.volume_24h_usd > 0:
            score += 5

        # Volume/MCap ratio (max 50)
        if inp.market_cap_usd > 0 and inp.volume_24h_usd > 0:
            vol_ratio = inp.volume_24h_usd / inp.market_cap_usd
            if vol_ratio >= 0.1:  # 10%+ daily turnover
                score += 50
            elif vol_ratio >= 0.05:
                score += 40
            elif vol_ratio >= 0.02:
                score += 30
            elif vol_ratio >= 0.01:
                score += 20
            elif vol_ratio >= 0.005:
                score += 10

        return min(100, score)

    def _score_spread(self, inp: MarketInput) -> float:
        """Score bid-ask spread (0-100)"""
        spread = inp.bid_ask_spread_bps

        # Lower is better
        if spread <= 5:  # 0.05%
            return 100
        elif spread <= 10:  # 0.1%
            return 90
        elif spread <= 20:  # 0.2%
            return 75
        elif spread <= 50:  # 0.5%
            return 55
        elif spread <= 100:  # 1%
            return 35
        elif spread <= 200:  # 2%
            return 20
        else:
            return 10

    def _score_exchanges(self, inp: MarketInput) -> float:
        """Score exchange support (0-100)"""
        score = 0

        # CEX listing (max 50)
        if inp.cex_listed:
            score += 30
            score += min(20, inp.cex_count * 5)

        # DEX presence (max 50)
        score += min(50, inp.dex_count * 10)

        return min(100, score)


if __name__ == '__main__':
    # Example: Score a liquid token like SOL
    scorer = MarketScorer()

    inp = MarketInput(
        tvl_usd=0,  # Not a DeFi
        liquidity_usd=500e6,
        reserve_usd=0,
        volume_24h_usd=3e9,
        volume_7d_usd=20e9,
        market_cap_usd=60e9,
        bid_ask_spread_bps=8,
        cex_listed=True,
        cex_count=15,
        dex_count=20,
    )

    score = scorer.score(inp)
    print(f"Market Structure Score: {score}")
