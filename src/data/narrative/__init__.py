"""
CometCloud Narrative Module
NMA (Narrative-Market Alignment) data pipeline for CIS S-pillar injection.

Sub-modules:
  social_collector.py    — CoinGecko community data + CryptoPanic RSS
  orderflow_collector.py — Binance depth imbalance + funding rate
  narrative_engine.py    — Aggregation into NarrativeSignal + CIS injection

Usage:
  from data.narrative import compute_narrative_signal, batch_narrative_signals
  from data.narrative.narrative_engine import apply_narrative_to_s_pillar

Author: CometCloud Intelligence
"""

from data.narrative.narrative_engine import (  # noqa: F401
    NarrativeSignal,
    compute_narrative_signal,
    batch_narrative_signals,
    compute_narrative_modifier,
    apply_narrative_to_s_pillar,
)

__all__ = [
    "NarrativeSignal",
    "compute_narrative_signal",
    "batch_narrative_signals",
    "compute_narrative_modifier",
    "apply_narrative_to_s_pillar",
]