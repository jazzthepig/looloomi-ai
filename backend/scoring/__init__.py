"""
CometCloud Intelligence Score (CIS) Scoring Module
=================================================

Pillars:
- F: Fundamental
- M: Market Structure
- O: On-Chain Health
- S: Sentiment & Social
- alpha: Alpha Independence
"""

from .cis_engine import CISEngine, CISResult, PillarScores, AssetClass
from .fundamental import FundamentalScorer, FundamentalInput
from .market import MarketScorer, MarketInput
from .onchain import OnChainScorer, OnChainInput
from .sentiment import SentimentScorer, SentimentInput
from .alpha import AlphaScorer, AlphaInput

__all__ = [
    'CISEngine',
    'CISResult',
    'PillarScores',
    'AssetClass',
    'FundamentalScorer',
    'FundamentalInput',
    'MarketScorer',
    'MarketInput',
    'OnChainScorer',
    'OnChainInput',
    'SentimentScorer',
    'SentimentInput',
    'AlphaScorer',
    'AlphaInput',
]
