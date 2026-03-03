"""
CIS Pillar O: On-Chain Health Score
===================================
Measures real on-chain activity and holder behavior.

Sub-metrics:
- Network activity (transactions, active addresses)
- Holder distribution (whale concentration, holder growth)
- Smart money flows (institutional wallets)
- Protocol usage (TVL changes, revenue)
"""

from dataclasses import dataclass


@dataclass
class OnChainInput:
    """Input data for on-chain health scoring"""
    # Activity
    daily_transactions: int = 0
    daily_active_addresses: int = 0
    transaction_growth_30d: float = 0  # %

    # Holders
    total_holders: int = 0
    holder_growth_30d: float = 0  # %
    top_10_concentration: float = 100  # % of supply held by top 10

    # Smart money
    institutional_wallets: int = 0
    smart_money_inflow_30d: float = 0  # USD
    smart_money_outflow_30d: float = 0  # USD

    # Protocol
    tvl_change_30d: float = 0  # %
    protocol_revenue_30d: float = 0  # USD
    staking_rate: float = 0  # % of supply staked


class OnChainScorer:
    """Calculate On-Chain Health pillar score (0-100)"""

    def score(self, inp: OnChainInput) -> float:
        """Calculate on-chain health score"""
        activity_score = self._score_activity(inp)
        holder_score = self._score_holders(inp)
        smart_money_score = self._score_smart_money(inp)
        protocol_score = self._score_protocol(inp)

        return round(
            activity_score * 0.25 +
            holder_score * 0.25 +
            smart_money_score * 0.25 +
            protocol_score * 0.25,
            1
        )

    def _score_activity(self, inp: OnChainInput) -> float:
        """Score network activity (0-100)"""
        score = 0

        # Transactions (max 50)
        if inp.daily_transactions >= 1e6:
            score += 50
        elif inp.daily_transactions >= 100e3:
            score += 40
        elif inp.daily_transactions >= 10e3:
            score += 25
        elif inp.daily_transactions >= 1e3:
            score += 15
        elif inp.daily_transactions > 0:
            score += 5

        # Active addresses (max 50)
        if inp.daily_active_addresses >= 500e3:
            score += 50
        elif inp.daily_active_addresses >= 100e3:
            score += 40
        elif inp.daily_active_addresses >= 10e3:
            score += 25
        elif inp.daily_active_addresses >= 1e3:
            score += 15
        elif inp.daily_active_addresses > 0:
            score += 5

        # Growth bonus (max 20)
        if inp.transaction_growth_30d >= 50:
            score += 20
        elif inp.transaction_growth_30d >= 20:
            score += 15
        elif inp.transaction_growth_30d >= 0:
            score += 10
        elif inp.transaction_growth_30d >= -20:
            score += 5

        return min(100, score)

    def _score_holders(self, inp: OnChainInput) -> float:
        """Score holder distribution (0-100)"""
        score = 30  # Base

        # Holder count (max 30)
        if inp.total_holders >= 1e6:
            score += 30
        elif inp.total_holders >= 100e3:
            score += 25
        elif inp.total_holders >= 10e3:
            score += 15
        elif inp.total_holders >= 1e3:
            score += 10
        elif inp.total_holders > 0:
            score += 5

        # Holder growth (max 20)
        if inp.holder_growth_30d >= 20:
            score += 20
        elif inp.holder_growth_30d >= 10:
            score += 15
        elif inp.holder_growth_30d >= 0:
            score += 10
        elif inp.holder_growth_30d >= -10:
            score += 5

        # Concentration (lower is better, max 20)
        conc = inp.top_10_concentration
        if conc <= 20:
            score += 20
        elif conc <= 40:
            score += 15
        elif conc <= 60:
            score += 10
        elif conc <= 80:
            score += 5

        return min(100, score)

    def _score_smart_money(self, inp: OnChainInput) -> float:
        """Score smart money flows (0-100)"""
        score = 30  # Base

        # Institutional wallets (max 30)
        score += min(30, inp.institutional_wallets * 3)

        # Net flow (max 40)
        net_flow = inp.smart_money_inflow_30d - inp.smart_money_outflow_30d
        if net_flow >= 10e6:  # $10M+ net inflow
            score += 40
        elif net_flow >= 1e6:
            score += 30
        elif net_flow >= 0:
            score += 20
        elif net_flow >= -1e6:
            score += 10
        else:
            # Net outflow penalty
            score -= 10

        return max(0, min(100, score))

    def _score_protocol(self, inp: OnChainInput) -> float:
        """Score protocol metrics (0-100)"""
        score = 30  # Base

        # TVL change (max 30)
        if inp.tvl_change_30d >= 50:
            score += 30
        elif inp.tvl_change_30d >= 20:
            score += 25
        elif inp.tvl_change_30d >= 0:
            score += 15
        elif inp.tvl_change_30d >= -20:
            score += 5

        # Revenue (max 20)
        if inp.protocol_revenue_30d >= 10e6:
            score += 20
        elif inp.protocol_revenue_30d >= 1e6:
            score += 15
        elif inp.protocol_revenue_30d >= 100e3:
            score += 10
        elif inp.protocol_revenue_30d > 0:
            score += 5

        # Staking (max 20)
        if inp.staking_rate >= 70:
            score += 20
        elif inp.staking_rate >= 50:
            score += 15
        elif inp.staking_rate >= 30:
            score += 10
        elif inp.staking_rate > 0:
            score += 5

        return min(100, score)


if __name__ == '__main__':
    scorer = OnChainScorer()

    # Example: ETH-like token
    inp = OnChainInput(
        daily_transactions=1.2e6,
        daily_active_addresses=500e3,
        transaction_growth_30d=5,
        total_holders=1e6,
        holder_growth_30d=3,
        top_10_concentration=25,
        institutional_wallets=50,
        smart_money_inflow_30d=500e6,
        smart_money_outflow_30d=200e6,
        tvl_change_30d=8,
        protocol_revenue_30d=0,  # Not applicable
        staking_rate=25,
    )

    score = scorer.score(inp)
    print(f"On-Chain Health Score: {score}")
