"""
CometCloud Nautilus Sleeve A — engine parity port (Seth, 2026-07-17)
=====================================================================

End-to-end runnable skeleton for parity verification of
`freqtrade/user_data/strategies/CometCloudMultiFactorV2.py` against
Nautilus Trader 1.229+.  Lives in `src/research/nautilus/sleeve_a/`
(engine-specific work area, intentionally NOT registered in the project
strategy registry — this lane is about plumbing parity, not strategy
framework introspection).

Public surface:

    strategy.CometCloudNautilusMultiFactorV2  — main strategy class
    strategy.SleeveAConfig                    — frozen StrategyConfig
    data_adapter.build_catalog                — feather → Nautilus ParquetDataCatalog
    runner.run_parity                         — BacktestNode run, emits JSON+CSV
    parity_check.diff_runs                    — Nautilus vs freqtrade side-by-side

Per the 大象无形 principle: engine plumbing lives here, alpha stays in
`CometCloudMultiFactorV2.py` (the freqtrade reference) and in the Macro
/ CIS / risk layer (live systems).  Parity is measured against freqtrade
MultiFactorV2 OOS run: 2025-01-01 → 2026-03-12, 3 pairs (BTC/ETH/SOL
perpetuals), 1h bars.  Expected gap: ±1 trade per pair on the 14mo
window (the daily-cap off-by-one when UTC midnight crosses mid-bar in
freqtrade's Trade-proxy lookup), ≤ 0.5% of notional PnL gap.

Per MINIMAX_SYNC.md §STRATEGY-REVIVE (2026-07-17): Sleeve A is the
"durable fundamental core" of the surviving two-layer book.  It must
clear Minimax-C's C-S3 out-of-sample walk-forward gate before any
"production" label lands.

Import surface — the Strategy class requires `nautilus_trader`, which
the Cowork sandbox does NOT have.  Sandbox-side code that needs only
the duck-typed contract (compliance check, parquet write, parity diff)
must import from the submodules directly: e.g.
`from src.research.nautilus.sleeve_a.parity_check import diff_runs`.
The package-level re-exports below are guarded so import fails gracefully
when nautilus is missing — this lets the smoke tests run in both the
Cowork sandbox (skipping the Strategy-dependent ones) and the Mac venv
(running all tests).
"""

from __future__ import annotations

import importlib as _importlib
import logging

logger = logging.getLogger(__name__)


# ── Top-level re-exports (guarded) ───────────────────────────────────────────

_STRATEGY_EXPORTS = [
    "CometCloudNautilusMultiFactorV2",
    "SleeveAConfig",
]
_DATA_ADAPTER_EXPORTS = [
    "build_catalog",
    "CATALOG_DIR",
    "FEATHER_DIR",
    "INSTRUMENTS",
]
_RUNNER_EXPORTS = [
    "run_parity",
    "OUT_DIR",
    "RUNNER_CATALOG_DIR",
]


def _try_get_submodule(name: str):
    """Import a submodule without crashing the whole package.

    Returns the module on success, None on ImportError.
    """
    try:
        return _importlib.import_module(f".{name}", __name__)
    except ImportError as exc:
        logger.debug(
            f"[sleeve_a] skip {name} re-export: {exc} "
            f"(run on Mac venv for full surface)"
        )
        return None


_strategy = _try_get_submodule("strategy")
_data_adapter = _try_get_submodule("data_adapter")
_runner = _try_get_submodule("runner")

_globals = globals()
for _name in _STRATEGY_EXPORTS:
    if _strategy is not None and hasattr(_strategy, _name):
        _globals[_name] = getattr(_strategy, _name)
for _name in _DATA_ADAPTER_EXPORTS:
    if _data_adapter is not None and hasattr(_data_adapter, _name):
        _globals[_name] = getattr(_data_adapter, _name)
for _name in _RUNNER_EXPORTS:
    if _runner is not None and hasattr(_runner, _name):
        _globals[_name] = getattr(_runner, _name)


__all__ = _STRATEGY_EXPORTS + _DATA_ADAPTER_EXPORTS + _RUNNER_EXPORTS
