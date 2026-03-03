"""
CIS Pillar F: Fundamental Score
===============================
Evaluates intrinsic quality of the project behind the token.

Sub-metrics:
- Team (founders, advisors, team size)
- Tokenomics (supply, distribution, vesting)
- Product (MVP, roadmap, traction)
- Back partnerships (audits, grants, ecosystem)

RWA-specific modifiers:
- Collateral quality
- Custody proof
- Legal wrapper clarity
- Redemption mechanism
"""

from dataclasses import dataclass
from typing import Optional, Dict, Any


@dataclass
class FundamentalInput:
    """Input data for fundamental scoring"""
    # Team
    team_size: int = 0  # 0 = unknown, 1 = solo, 2 = small, 3 = medium, 4 = large
    has_ceo: bool = False
    has_tech_lead: bool = False
    team_identified: bool = True  # False if anonymous
    advisors_count: int = 0

    # Tokenomics
    total_supply: float = 0
    circulating_supply: float = 0
    inflation_rate: float = 0  # annual
    treasury_tokens: float = 0  # % of supply

    # Product
    has_mvp: bool = False
    has_audit: bool = False
    product_age_days: int = 0
    daily_active_users: int = 0
    weekly_transactions: int = 0

    # Partnerships
    audit_firms: list = None  # ["certik", "hacken"]
    grants_received: list = None  # ["a16z", "foundation"]
    ecosystem_partners: list = None
    exchange_listings: list = None

    # RWA specific
    collateral_type: str = ""  # "us_treasury", "real_estate", "commodity"
    custody_provider: str = ""  # "fireblocks", "bitgo"
    legal_wrapper: str = ""  # "sec_registered", "reg_s", "none"
    redemption_mechanism: str = ""  # "on_demand", "periodic", "none"

    def __post_init__(self):
        if self.audit_firms is None:
            self.audit_firms = []
        if self.grants_received is None:
            self.grants_received = []
        if self.ecosystem_partners is None:
            self.ecosystem_partners = []
        if self.exchange_listings is None:
            self.exchange_listings = []


class FundamentalScorer:
    """Calculate Fundamental pillar score (0-100)"""

    def __init__(self, is_rwa: bool = False):
        self.is_rwa = is_rwa

    def score(self, inp: FundamentalInput) -> float:
        """Calculate fundamental score"""
        team_score = self._score_team(inp)
        tokenomics_score = self._score_tokenomics(inp)
        product_score = self._score_product(inp)
        partnership_score = self._score_partnerships(inp)

        # Base score (0-100)
        base_score = (
            team_score * 0.25 +
            tokenomics_score * 0.25 +
            product_score * 0.30 +
            partnership_score * 0.20
        )

        # RWA modifiers
        if self.is_rwa:
            rwa_modifier = self._score_rwa_modifiers(inp)
            # RWA expands to 120-point scale, normalize back to 100
            base_score = min(100, base_score + rwa_modifier)

        return round(base_score, 1)

    def _score_team(self, inp: FundamentalInput) -> float:
        """Score team quality (0-100)"""
        score = 0

        # Team size (max 20)
        score += min(20, inp.team_size * 5)

        # Leadership (max 30)
        if inp.has_ceo:
            score += 15
        if inp.has_tech_lead:
            score += 15

        # Identified team (max 20)
        if inp.team_identified:
            score += 20
        else:
            # Anonymous team penalty
            score -= 10

        # Advisors (max 10)
        score += min(10, inp.advisors_count * 3)

        return max(0, min(100, score))

    def _score_tokenomics(self, inp: FundamentalInput) -> float:
        """Score tokenomics (0-100)"""
        score = 50  # Base

        if inp.circulating_supply > 0 and inp.total_supply > 0:
            circ_ratio = inp.circulating_supply / inp.total_supply

            # Good distribution (max 30)
            if circ_ratio >= 0.5:
                score += 30
            elif circ_ratio >= 0.3:
                score += 20
            elif circ_ratio >= 0.15:
                score += 10

            # Low inflation (max 20)
            if inp.inflation_rate <= 5:
                score += 20
            elif inp.inflation_rate <= 10:
                score += 10
            elif inp.inflation_rate <= 20:
                score += 5

        # Treasury (max 10)
        if inp.treasury_tokens >= 15:
            score += 10
        elif inp.treasury_tokens >= 5:
            score += 5

        return max(0, min(100, score))

    def _score_product(self, inp: FundamentalInput) -> float:
        """Score product readiness (0-100)"""
        score = 0

        # MVP (max 30)
        if inp.has_mvp:
            score += 30

        # Audit (max 25)
        if inp.has_audit:
            score += 25
            # Bonus for multiple audits
            if len(inp.audit_firms) > 1:
                score += 5

        # Product age (max 20)
        if inp.product_age_days >= 365:
            score += 20
        elif inp.product_age_days >= 180:
            score += 15
        elif inp.product_age_days >= 90:
            score += 10
        elif inp.product_age_days >= 30:
            score += 5

        # Traction (max 25)
        if inp.daily_active_users >= 10000:
            score += 25
        elif inp.daily_active_users >= 1000:
            score += 20
        elif inp.daily_active_users >= 100:
            score += 15
        elif inp.daily_active_users > 0:
            score += 10

        return max(0, min(100, score))

    def _score_partnerships(self, inp: FundamentalInput) -> float:
        """Score partnerships and ecosystem (0-100)"""
        score = 30  # Base

        # Audits (max 20)
        score += min(20, len(inp.audit_firms) * 10)

        # Grants (max 20)
        score += min(20, len(inp.grants_received) * 7)

        # Ecosystem (max 15)
        score += min(15, len(inp.ecosystem_partners) * 3)

        # Exchange listings (max 15)
        tier1_exchanges = ['binance', 'coinbase', 'kraken']
        tier2_exchanges = ['bybit', 'okx', 'huobi', 'gate', 'kucoin']

        for exchange in inp.exchange_listings:
            if exchange.lower() in tier1_exchanges:
                score += 5
            elif exchange.lower() in tier2_exchanges:
                score += 2

        return max(0, min(100, score))

    def _score_rwa_modifiers(self, inp: FundamentalInput) -> float:
        """RWA-specific modifiers (0-20 bonus)"""
        bonus = 0

        # Collateral quality (+5)
        if inp.collateral_type in ['us_treasury', 'gold', 'cash']:
            bonus += 5

        # Custody proof (+5)
        if inp.custody_provider:
            bonus += 5

        # Legal wrapper (+5)
        if inp.legal_wrapper in ['sec_registered', 'reg_s', 'reg_d']:
            bonus += 5

        # Redemption mechanism (+5)
        if inp.redemption_mechanism == 'on_demand':
            bonus += 5
        elif inp.redemption_mechanism == 'periodic':
            bonus += 2

        return bonus


# Example usage
if __name__ == '__main__':
    # Example: Score a RWA like Ondo
    scorer = FundamentalScorer(is_rwa=True)

    inp = FundamentalInput(
        team_size=4,
        has_ceo=True,
        has_tech_lead=True,
        team_identified=True,
        advisors_count=3,
        total_supply=10000000000,
        circulating_supply=3000000000,
        inflation_rate=0,
        treasury_tokens=20,
        has_mvp=True,
        has_audit=True,
        audit_firms=['certik', 'slowmist'],
        grants_received=['polychain', 'debug'],
        ecosystem_partners=['ethereum', 'solana'],
        exchange_listings=['binance', 'coinbase', 'bybit'],
        collateral_type='us_treasury',
        custody_provider='fireblocks',
        legal_wrapper='sec_registered',
        redemption_mechanism='on_demand',
    )

    score = scorer.score(inp)
    print(f"Fundamental Score: {score}")
