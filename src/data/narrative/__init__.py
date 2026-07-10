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

# Defensive imports — the backend runs under both `src.data.narrative` (routers/main)
# and `data.narrative` (PYTHONPATH=src) conventions; a hard import here crashed the
# whole package under the other style. Never let the package fail to import.
try:
    from data.narrative.narrative_engine import (  # noqa: F401
        NarrativeSignal, compute_narrative_signal, batch_narrative_signals,
        compute_narrative_modifier, apply_narrative_to_s_pillar,
    )
except Exception:  # pragma: no cover
    try:
        from src.data.narrative.narrative_engine import (  # noqa: F401
            NarrativeSignal, compute_narrative_signal, batch_narrative_signals,
            compute_narrative_modifier, apply_narrative_to_s_pillar,
        )
    except Exception:
        NarrativeSignal = None
        compute_narrative_signal = batch_narrative_signals = None
        compute_narrative_modifier = apply_narrative_to_s_pillar = None

__all__ = [
    "NarrativeSignal", "compute_narrative_signal", "batch_narrative_signals",
    "compute_narrative_modifier", "apply_narrative_to_s_pillar",
]