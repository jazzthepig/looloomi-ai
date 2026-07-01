"""
Base contract for framework-aware Nautilus strategies.

This module documents the contract a strategy must satisfy to be runnable
under the framework's single-run + walk-forward + multi-testing machinery.

The contract is intentionally lightweight — strategies inherit from
nautilus_trader.trading.strategy.Strategy directly (since the framework
needs full control over Nautilus event lifecycle). Framework concerns are
encoded as classmethods so the registry can introspect them.

Contract surface:
    required_indicators()       -> list[str]
        What pre-computed indicator keys this strategy reads from
        `strategy.indicators[bar.ts_event]`.

    required_timeframes()       -> list[str]
        Which bar types the strategy subscribes to (e.g., ("4h",) or
        ("1h", "4h", "1d")).

    required_history_bars()     -> int
        Minimum bars before signals are valid (warmup).

    regime_filter(cis, regime)  -> bool
        Optional override to block entries in specific regimes.
        Default returns True.

    compliance_tag()            -> str
        Short string used in audit trail (must NOT contain
        buy/sell/accumulate/avoid language per CLAUDE.md).

    metrics_extra()             -> dict
        Optional extra metrics specific to this strategy (e.g.,
        meta_v4 reports per-alpha-channel contribution).
        Default returns {}.

Concrete strategies use `nautilus_trader.trading.strategy.Strategy`
directly, NOT a subclass — the base class here is a mixin / duck-typed
contract enforced via the registry.
"""

from __future__ import annotations

from typing import Optional


class ResearchStrategyContract:
    """Mixin documenting the contract. Concrete strategies implement these."""

    @classmethod
    def required_indicators(cls) -> list[str]:
        """Indicator keys required from pre-computed indicators dict.

        Must include: at minimum, anything the strategy reads on each bar.
        Example: ["adx_14", "ema_9", "ema_21", "atr", "rsi"]
        """
        raise NotImplementedError

    @classmethod
    def required_timeframes(cls) -> list[str]:
        """Bar types the strategy subscribes to. Default: 4h only."""
        return ("4h",)

    @classmethod
    def required_history_bars(cls) -> int:
        """Minimum bars before signals are valid (warmup period)."""
        return 60

    def regime_filter(self, cis: dict, regime: str) -> bool:
        """Optional override to block entries in specific regimes.
        Default: always pass (no regime-based blocking)."""
        return True

    def compliance_tag(self) -> str:
        """Short audit tag (no buy/sell language per CLAUDE.md)."""
        return "RESEARCH"

    def metrics_extra(self) -> dict:
        """Optional extra metrics beyond the standard bundle."""
        return {}


# ── Nautilus-internal lifecycle helpers ─────────────────────────────────────

def attach_indicators(strategy, indicators: dict[int, dict]) -> None:
    """Set pre-computed indicators dict on the strategy.

    Indicators must be keyed by `bar.ts_event` (UNIX nanoseconds).
    Caller is responsible for indicator pre-computation
    (see /tmp/nautilus_data_bridge.py::precompute_indicators).
    """
    strategy.indicators = indicators


def attach_cis_history(strategy, cis_by_date: dict[str, dict]) -> None:
    """Set per-day CIS snapshots on the strategy.

    Keyed by "YYYY-MM-DD" UTC. Each value is the JSON snapshot dict from
    /Volumes/CometCloudAI/cometcloud-local/_data/cis_history/cis_YYYY-MM-DD.json.
    """
    strategy._cis_by_date = cis_by_date


def attach_instrument_map(strategy, instrument_to_symbol: dict[str, str]) -> None:
    """Map Nautilus instrument_id.value → human symbol (BTC, ETH, ...)."""
    strategy.instrument_to_symbol = instrument_to_symbol


__all__ = [
    "ResearchStrategyContract",
    "attach_indicators",
    "attach_cis_history",
    "attach_instrument_map",
]
