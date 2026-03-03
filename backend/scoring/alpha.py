"""
CIS Pillar α: Alpha Independence Score
=====================================
Measures whether an asset provides genuinely differentiated return streams.
Draws from Carhart (1997) and Fama-French (2015) factor models.

Key insight: Many crypto assets appear to generate alpha but are actually
just loading on BTC beta + momentum + size factors.

Factors:
- BTC beta: Correlation with Bitcoin returns
- ETH correlation: Correlation with Ethereum
- Momentum: Past 30d return
- Size: Market cap effect
- Sector-specific: DeFi-specific, RWA-specific factors
"""

from dataclasses import dataclass
from typing import Optional, List
import math


@dataclass
class AlphaInput:
    """Input data for alpha independence scoring"""
    # Returns
    returns_30d: float = 0  # %
    returns_90d: float = 0  # %
    returns_180d: float = 0  # %

    # Factor loadings (from regression)
    btc_beta: float = 1.0  # Beta vs BTC
    eth_beta: float = 1.0  # Beta vs ETH
    momentum_factor: float = 0.0  # Factor exposure
    size_factor: float = 0.0  # Factor exposure

    # Correlations
    btc_correlation_30d: float = 1.0
    eth_correlation_30d: float = 1.0

    # Sector
    sector_btc_correlation: float = 0.7  # Typical sector correlation

    # For RWA
    traditional_correlation: float = 0.0  # Correlation with traditional assets


class AlphaScorer:
    """Calculate Alpha Independence pillar score (0-100)"""

    def __init__(self, asset_class: str = "DeFi"):
        self.asset_class = asset_class

    def score(self, inp: AlphaInput) -> float:
        """Calculate alpha independence score"""
        beta_score = self._score_beta(inp)
        correlation_score = self._score_correlation(inp)
        momentum_score = self._score_momentum(inp)
        sector_score = self._score_sector(inp)

        # Weight based on asset class
        weights = self._get_weights()

        return round(
            beta_score * weights['beta'] +
            correlation_score * weights['correlation'] +
            momentum_score * weights['momentum'] +
            sector_score * weights['sector'],
            1
        )

    def _get_weights(self) -> dict:
        """Get scoring weights by asset class"""
        weights = {
            'DeFi': {'beta': 0.30, 'correlation': 0.25, 'momentum': 0.25, 'sector': 0.20},
            'RWA': {'beta': 0.20, 'correlation': 0.30, 'momentum': 0.20, 'sector': 0.30},
            'Memecoin': {'beta': 0.25, 'correlation': 0.20, 'momentum': 0.35, 'sector': 0.20},
            'L1': {'beta': 0.35, 'correlation': 0.20, 'momentum': 0.20, 'sector': 0.25},
            'L2': {'beta': 0.30, 'correlation': 0.25, 'momentum': 0.20, 'sector': 0.25},
            'AI': {'beta': 0.25, 'correlation': 0.25, 'momentum': 0.25, 'sector': 0.25},
        }
        return weights.get(self.asset_class, weights['DeFi'])

    def _score_beta(self, inp: AlphaInput) -> float:
        """Score factor loadings (0-100)"""
        # Lower beta = more independent
        score = 50  # Base

        # BTC Beta (max 30)
        btc = inp.btc_beta
        if btc <= 0.3:
            score += 30
        elif btc <= 0.5:
            score += 25
        elif btc <= 0.7:
            score += 20
        elif btc <= 1.0:
            score += 10
        elif btc <= 1.3:
            score += 0
        else:  # > 1.3
            score -= 15

        # ETH Beta (max 20)
        eth = inp.eth_beta
        if eth <= 0.3:
            score += 20
        elif eth <= 0.5:
            score += 15
        elif eth <= 0.7:
            score += 10
        elif eth <= 1.0:
            score += 5

        return max(0, min(100, score))

    def _score_correlation(self, inp: AlphaInput) -> float:
        """Score correlation independence (0-100)"""
        score = 50  # Base

        btc_corr = inp.btc_correlation_30d

        # Lower correlation = higher score
        if btc_corr <= 0.3:
            score += 40
        elif btc_corr <= 0.5:
            score += 30
        elif btc_corr <= 0.7:
            score += 15
        elif btc_corr <= 0.85:
            score += 5

        # RWA-specific: traditional asset correlation
        if self.asset_class == 'RWA':
            trad_corr = inp.traditional_correlation
            if 0.1 <= trad_corr <= 0.4:  # Moderate positive = good diversification
                score += 10
            elif trad_corr < 0.1:
                score += 5  # Uncorrelated = good

        return max(0, min(100, score))

    def _score_momentum(self, inp: AlphaInput) -> float:
        """Score momentum factor (0-100)"""
        # Moderate momentum is acceptable, extreme is not
        score = 60  # Base

        ret = inp.returns_30d

        # Don't punish normal returns, reward differentiation
        # Too high returns (>100% in 30d) = likely BTC-dependent rally
        if ret > 100:  # >100% in 30 days
            score -= 20
        elif ret > 50:
            score -= 10

        # Momentum factor exposure
        mom = inp.momentum_factor
        if abs(mom) <= 0.2:
            score += 20  # Low momentum exposure
        elif abs(mom) <= 0.4:
            score += 10
        elif abs(mom) <= 0.6:
            score += 0
        else:
            score -= 10  # High momentum loading

        # Negative momentum = mean reversion candidate
        if ret < -20 and mom < -0.3:
            score += 20  # Contrarian opportunity

        return max(0, min(100, score))

    def _score_sector(self, inp: AlphaInput) -> float:
        """Score sector-specific diversification (0-100)"""
        score = 50  # Base

        # Compare to sector average correlation
        sector_corr = inp.sector_btc_correlation
        actual_corr = inp.btc_correlation_30d

        # Lower than sector average = better
        if actual_corr < sector_corr - 0.2:
            score += 30
        elif actual_corr < sector_corr:
            score += 20
        elif actual_corr < sector_corr + 0.1:
            score += 10

        # Size factor (for smaller caps = higher risk but more alpha potential)
        size = inp.size_factor
        if size > 0.2:  # Small cap exposure
            score += 20  # Potential for outsized returns

        return min(100, score)


if __name__ == '__main__':
    # Example: RWA token with low BTC correlation
    scorer = AlphaScorer(asset_class='RWA')

    inp = AlphaInput(
        returns_30d=5,
        returns_90d=12,
        btc_beta=0.4,
        eth_beta=0.3,
        momentum_factor=0.1,
        size_factor=0.0,
        btc_correlation_30d=0.35,
        eth_correlation_30d=0.25,
        sector_btc_correlation=0.6,
        traditional_correlation=0.25,  # Moderate correlation with traditional
    )

    score = scorer.score(inp)
    print(f"Alpha Independence Score: {score}")

    # Example: Memecoin (high BTC correlation expected)
    memecoin_scorer = AlphaScorer(asset_class='Memecoin')

    memecoin_inp = AlphaInput(
        returns_30d=150,  # Mooning
        btc_beta=1.2,
        btc_correlation_30d=0.85,
        momentum_factor=0.8,
    )

    memecoin_score = memecoin_scorer.score(memecoin_inp)
    print(f"Memecoin Alpha Score: {memecoin_score}")
