"""
CIS Pillar S: Sentiment & Social Score
======================================
Captures market psychology through social signals and KOL activity.
Inherits methodology from Looloomi MMI framework.

Sub-metrics:
- Social media (Twitter/X followers, engagement)
- On-chain social (Discord members, Telegram)
- KOL mentions and sentiment
- News sentiment
- MMI-derived momentum (for memecoins)
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class SentimentInput:
    """Input data for sentiment scoring"""
    # Social media
    twitter_followers: int = 0
    twitter_followers_growth_30d: float = 0  # %
    twitter_engagement_rate: float = 0  # %
    twitter_sentiment: float = 0.5  # 0-1 (bearish to bullish)

    # Community
    discord_members: int = 0
    telegram_members: int = 0
    community_growth_30d: float = 0  # %

    # KOL/Influencer
    kol_mentions_30d: int = 0
    kol_sentiment: float = 0.5  # 0-1

    # News
    news_mentions_30d: int = 0
    news_sentiment: float = 0.5  # 0-1

    # MMI (for memecoins)
    mmi_score: float = 50  # 0-100 Memecoin Momentum Index
    mmi_extreme: bool = False  # True if > 85 or < 15


class SentimentScorer:
    """Calculate Sentiment & Social pillar score (0-100)"""

    def __init__(self, is_memecoin: bool = False):
        self.is_memecoin = is_memecoin

    def score(self, inp: SentimentInput) -> float:
        """Calculate sentiment score"""
        social_score = self._score_social(inp)
        community_score = self._score_community(inp)
        kol_score = self._score_kol(inp)
        news_score = self._score_news(inp)

        # For memecoins, MMI is significant
        if self.is_memecoin:
            mmi_score = self._score_mmi(inp)
            return round(
                social_score * 0.20 +
                community_score * 0.15 +
                kol_score * 0.20 +
                news_score * 0.15 +
                mmi_score * 0.30,
                1
            )

        return round(
            social_score * 0.30 +
            community_score * 0.25 +
            kol_score * 0.25 +
            news_score * 0.20,
            1
        )

    def _score_social(self, inp: SentimentInput) -> float:
        """Score social media presence (0-100)"""
        score = 0

        # Followers (max 30)
        if inp.twitter_followers >= 1e6:
            score += 30
        elif inp.twitter_followers >= 100e3:
            score += 25
        elif inp.twitter_followers >= 10e3:
            score += 15
        elif inp.twitter_followers > 0:
            score += 5

        # Growth (max 30)
        if inp.twitter_followers_growth_30d >= 50:
            score += 30
        elif inp.twitter_followers_growth_30d >= 20:
            score += 20
        elif inp.twitter_followers_growth_30d >= 0:
            score += 10
        elif inp.twitter_followers_growth_30d >= -20:
            score += 5

        # Engagement (max 25)
        if inp.twitter_engagement_rate >= 5:
            score += 25
        elif inp.twitter_engagement_rate >= 2:
            score += 20
        elif inp.twitter_engagement_rate >= 1:
            score += 15
        elif inp.twitter_engagement_rate > 0:
            score += 10

        # Sentiment (max 15)
        if inp.twitter_sentiment >= 0.7:
            score += 15
        elif inp.twitter_sentiment >= 0.5:
            score += 10
        elif inp.twitter_sentiment >= 0.3:
            score += 5

        return min(100, score)

    def _score_community(self, inp: SentimentInput) -> float:
        """Score community size (0-100)"""
        score = 0
        total_community = inp.discord_members + inp.telegram_members

        # Size (max 50)
        if total_community >= 500e3:
            score += 50
        elif total_community >= 100e3:
            score += 40
        elif total_community >= 10e3:
            score += 25
        elif total_community > 0:
            score += 10

        # Growth (max 30)
        if inp.community_growth_30d >= 30:
            score += 30
        elif inp.community_growth_30d >= 10:
            score += 20
        elif inp.community_growth_30d >= 0:
            score += 10
        elif inp.community_growth_30d >= -15:
            score += 5

        # Active engagement proxy (max 20)
        if inp.discord_members > 0:
            score += 20  # Discord is more engaged than Telegram-only

        return min(100, score)

    def _score_kol(self, inp: SentimentInput) -> float:
        """Score KOL/influencer coverage (0-100)"""
        score = 30  # Base

        # Mention volume (max 40)
        if inp.kol_mentions_30d >= 100:
            score += 40
        elif inp.kol_mentions_30d >= 50:
            score += 30
        elif inp.kol_mentions_30d >= 20:
            score += 20
        elif inp.kol_mentions_30d > 0:
            score += 10

        # Sentiment (max 30)
        if inp.kol_sentiment >= 0.7:
            score += 30
        elif inp.kol_sentiment >= 0.5:
            score += 20
        elif inp.kol_sentiment >= 0.3:
            score += 10

        return min(100, score)

    def _score_news(self, inp: SentimentInput) -> float:
        """Score news coverage (0-100)"""
        score = 30  # Base

        # Mention volume (max 40)
        if inp.news_mentions_30d >= 50:
            score += 40
        elif inp.news_mentions_30d >= 20:
            score += 30
        elif inp.news_mentions_30d >= 10:
            score += 20
        elif inp.news_mentions_30d > 0:
            score += 10

        # Sentiment (max 30)
        if inp.news_sentiment >= 0.7:
            score += 30
        elif inp.news_sentiment >= 0.5:
            score += 20
        elif inp.news_sentiment >= 0.3:
            score += 10

        return min(100, score)

    def _score_mmi(self, inp: SentimentInput) -> float:
        """Score MMI for memecoins (0-100)"""
        # MMI is inverse for sentiment scoring
        # High MMI (>85) = euphoria = negative for scoring (contrarian)
        # Low MMI (<15) = fear = positive for scoring

        mmi = inp.mmi_score

        # Base score from MMI
        if mmi <= 15:  # Extreme fear - bullish contrarian
            return 90
        elif mmi <= 30:  # Fear
            return 75
        elif mmi <= 45:  # Neutral
            return 60
        elif mmi <= 55:  # Neutral
            return 50
        elif mmi <= 70:  # Greed
            return 40
        elif mmi <= 85:  # High greed
            return 25
        else:  # Extreme greed - bearish contrarian
            return 10


if __name__ == '__main__':
    # Example: High sentiment AI token
    scorer = SentimentScorer(is_memecoin=False)

    inp = SentimentInput(
        twitter_followers=500e3,
        twitter_followers_growth_30d=15,
        twitter_engagement_rate=3.5,
        twitter_sentiment=0.65,
        discord_members=100e3,
        telegram_members=50e3,
        community_growth_30d=10,
        kol_mentions_30d=30,
        kol_sentiment=0.7,
        news_mentions_30d=20,
        news_sentiment=0.6,
    )

    score = scorer.score(inp)
    print(f"Sentiment Score: {score}")

    # Example: Memecoin with extreme MMI
    memecoin_scorer = SentimentScorer(is_memecoin=True)

    memecoin_inp = SentimentInput(
        twitter_followers=200e3,
        mmi_score=88,  # Euphoric
        mmi_extreme=True,
    )

    memecoin_score = memecoin_scorer.score(memecoin_inp)
    print(f"Memecoin Sentiment Score: {memecoin_score}")
