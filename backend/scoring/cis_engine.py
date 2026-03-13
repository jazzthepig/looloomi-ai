"""
CIS (CometCloud Intelligence Score) Engine
==========================================
Core scoring calculation for the five-pillar CIS framework.

Pillars:
- F: Fundamental Score
- M: Market Structure Score
- O: On-Chain Health Score
- S: Sentiment & Social Score
- alpha: Alpha Independence Score

Author: Seth
Version: 1.0
"""

import json
import os
from dataclasses import dataclass
from typing import Optional, Dict, List, Any
from enum import Enum


class AssetClass(Enum):
    RWA = "RWA"
    DEFI = "DeFi"
    MEMECOIN = "Memecoin"
    L1 = "L1"
    L2 = "L2"
    AI = "AI"
    INFRASTRUCTURE = "Infrastructure"


@dataclass
class PillarScores:
    """Individual pillar scores (0-100)"""
    F: float  # Fundamental
    M: float  # Market Structure
    O: float  # On-Chain Health
    S: float  # Sentiment & Social
    alpha: float  # Alpha Independence


@dataclass
class CISResult:
    """Complete CIS scoring result"""
    asset_id: str
    asset_name: str
    asset_class: str
    total_score: float
    grade: str
    pillars: PillarScores
    weights_used: Dict[str, float]
    disqualification: Optional[str] = None
    metadata: Optional[Dict] = None


class CISEngine:
    """Core CIS scoring engine"""

    def __init__(self, weights_path: Optional[str] = None):
        if weights_path is None:
            weights_path = os.path.join(
                os.path.dirname(__file__),
                '..',
                'data',
                'weights.json'
            )

        with open(weights_path, 'r') as f:
            self.config = json.load(f)

        self.asset_weights = self.config['asset_classes']
        self.grades = self.config['grades']
        self.disqualification_triggers = self.config['disqualification_triggers']

    def _get_weights(self, asset_class: str) -> Dict[str, float]:
        """Get weight profile for asset class"""
        if asset_class in self.asset_weights:
            return self.asset_weights[asset_class]['weights']

        # Default fallback
        return self.config['pillar_weights_default']

    def _calculate_weighted_score(
        self,
        pillars: PillarScores,
        weights: Dict[str, float]
    ) -> float:
        """Calculate weighted CIS total"""
        return (
            weights['F'] * pillars.F +
            weights['M'] * pillars.M +
            weights['O'] * pillars.O +
            weights['S'] * pillars.S +
            weights['alpha'] * pillars.alpha
        )

    def _get_grade(self, score: float) -> str:
        """Determine letter grade from score"""
        for grade, bounds in self.grades.items():
            if bounds['min'] <= score <= bounds['max']:
                return grade
        return 'F'

    def _check_disqualification(
        self,
        asset_data: Dict[str, Any],
        asset_class: str = "DeFi"
    ) -> Optional[str]:
        """Check if asset triggers automatic F grade"""
        for trigger_name, trigger_config in self.disqualification_triggers.items():
            condition = trigger_config.get('condition', '')

            # Simple condition evaluation (can be extended)
            try:
                # Build evaluation context
                context = {
                    'contract_audit': asset_data.get('has_audit', True),
                    'team_anonymous': asset_data.get('team_anonymous', False),
                    'mvp_exists': asset_data.get('has_mvp', True),
                    'liquidity_usd': asset_data.get('liquidity_usd', float('inf')),
                    'regulatory_flag': asset_data.get('regulatory_flag', False),
                    'rugpull_score': asset_data.get('rugpull_score', 0.0),
                    'asset_class': asset_class,
                }

                # Evaluate condition (basic implementation)
                if self._evaluate_condition(condition, context):
                    return trigger_config['reason']
            except Exception:
                continue

        return None

    def _evaluate_condition(self, condition: str, context: Dict) -> bool:
        """Evaluate a simple condition string"""
        # Basic condition parser
        condition = condition.strip()

        # Check for asset_class exclusion (e.g., "NOT IN ['Memecoin']")
        if 'NOT IN' in condition:
            import re
            match = re.search(r"NOT IN \[([^\]]+)\]", condition)
            if match:
                excluded_classes = [c.strip().strip("'\"") for c in match.group(1).split(',')]
                current_class = context.get('asset_class', '')
                if current_class in excluded_classes:
                    return False  # Skip this trigger for excluded classes

        if 'contract_audit == false' in condition:
            return not context.get('contract_audit', True)
        if 'team_anonymous == true' in condition:
            return context.get('team_anonymous', False)
        if 'mvp_exists == false' in condition:
            return not context.get('mvp_exists', True)
        if 'liquidity_usd <' in condition:
            threshold = float(condition.split('<')[1].strip())
            return context.get('liquidity_usd', float('inf')) < threshold
        if 'regulatory_flag == true' in condition:
            return context.get('regulatory_flag', False)
        if 'rugpull_score >' in condition:
            threshold = float(condition.split('>')[1].strip())
            return context.get('rugpull_score', 0.0) > threshold

        return False

    def calculate(
        self,
        asset_id: str,
        asset_name: str,
        asset_class: str,
        pillar_scores: Dict[str, float],
        asset_data: Optional[Dict[str, Any]] = None
    ) -> CISResult:
        """
        Calculate CIS score for an asset.

        Args:
            asset_id: Unique identifier for the asset
            asset_name: Display name
            asset_class: Asset class (RWA, DeFi, Memecoin, etc.)
            pillar_scores: Dict with keys F, M, O, S, alpha (0-100)
            asset_data: Additional data for disqualification checks

        Returns:
            CISResult with total score, grade, and breakdown
        """
        if asset_data is None:
            asset_data = {}

        # Check disqualification triggers first
        disqualification = self._check_disqualification(asset_data, asset_class)

        # Get weights for asset class
        weights = self._get_weights(asset_class)

        # Create pillar scores object
        pillars = PillarScores(
            F=pillar_scores.get('F', 0),
            M=pillar_scores.get('M', 0),
            O=pillar_scores.get('O', 0),
            S=pillar_scores.get('S', 0),
            alpha=pillar_scores.get('alpha', 0)
        )

        # Calculate total score
        if disqualification:
            total_score = 0
            grade = 'F'
        else:
            total_score = self._calculate_weighted_score(pillars, weights)
            grade = self._get_grade(total_score)

        return CISResult(
            asset_id=asset_id,
            asset_name=asset_name,
            asset_class=asset_class,
            total_score=round(total_score, 2),
            grade=grade,
            pillars=pillars,
            weights_used=weights,
            disqualification=disqualification,
            metadata={
                'calculated_at': self._get_timestamp(),
                'version': '1.0'
            }
        )

    def _get_timestamp(self) -> str:
        """Get current timestamp"""
        from datetime import datetime
        return datetime.utcnow().isoformat() + 'Z'

    def batch_calculate(
        self,
        assets: List[Dict[str, Any]]
    ) -> List[CISResult]:
        """
        Calculate CIS scores for multiple assets.

        Args:
            assets: List of asset dicts with required fields

        Returns:
            List of CISResult sorted by total_score descending
        """
        results = []

        for asset in assets:
            result = self.calculate(
                asset_id=asset['id'],
                asset_name=asset['name'],
                asset_class=asset['asset_class'],
                pillar_scores=asset['pillars'],
                asset_data=asset.get('metadata', {})
            )
            results.append(result)

        # Sort by total score descending
        results.sort(key=lambda x: x.total_score, reverse=True)

        return results

    def get_leaderboard(
        self,
        results: List[CISResult],
        asset_class: Optional[str] = None,
        min_score: float = 0,
        limit: int = 50
    ) -> List[Dict]:
        """
        Generate leaderboard from CIS results.

        Args:
            results: List of CISResult
            asset_class: Optional filter by asset class
            min_score: Minimum score threshold
            limit: Maximum number of results

        Returns:
            List of dicts suitable for API response
        """
        filtered = results

        if asset_class:
            filtered = [r for r in filtered if r.asset_class == asset_class]

        filtered = [r for r in filtered if r.total_score >= min_score]

        return [
            {
                'rank': i + 1,
                'asset_id': r.asset_id,
                'asset_name': r.asset_name,
                'asset_class': r.asset_class,
                'total_score': r.total_score,
                'grade': r.grade,
                'pillars': {
                    'F': round(r.pillars.F, 1),
                    'M': round(r.pillars.M, 1),
                    'O': round(r.pillars.O, 1),
                    'S': round(r.pillars.S, 1),
                    'alpha': round(r.pillars.alpha, 1),
                },
                'disqualification': r.disqualification,
            }
            for i, r in enumerate(filtered[:limit])
        ]


# Example usage
if __name__ == '__main__':
    engine = CISEngine()

    # Example: Calculate CIS for a RWA token
    result = engine.calculate(
        asset_id='ondo',
        asset_name='Ondo Finance',
        asset_class='RWA',
        pillar_scores={
            'F': 85,  # Strong fundamentals
            'M': 78,  # Good liquidity
            'O': 82,  # Active on-chain
            'S': 70,  # Moderate sentiment
            'alpha': 75,  # Some BTC correlation
        },
        asset_data={
            'has_audit': True,
            'liquidity_usd': 50000000,
        }
    )

    print(f"Asset: {result.asset_name}")
    print(f"CIS Score: {result.total_score}")
    print(f"Grade: {result.grade}")
    print(f"Weights: {result.weights_used}")
    print(f"Pillars: F={result.pillars.F}, M={result.pillars.M}, O={result.pillars.O}, S={result.pillars.S}, alpha={result.pillars.alpha}")
