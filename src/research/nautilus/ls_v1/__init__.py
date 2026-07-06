"""
CometCloud Nautilus LS v1 — engine parity port (Minimax-B, 2026-07-04)
======================================================================

End-to-end runnable skeleton for parity verification of
`freqtrade/user_data/strategies/CometCloudLongShortV4.py` against Nautilus
Trader 1.229+. Lives in `src/research/nautilus/ls_v1/` (engine-specific
work area, intentionally NOT registered in the project strategy registry —
this lane is about plumbing parity, not strategy framework introspection).

Public surface:

    strategy.CometCloudNautilusLongShortV1  — main strategy class
    strategy.LSv1Config                    — frozen StrategyConfig
    data_adapter.build_catalog              — feather → Nautilus ParquetDataCatalog
    runner.run_parity                      — BacktestNode run, emits JSON+CSV
    parity_check.diff_runs                 — Nautilus vs freqtrade side-by-side

Per the 大象无形 principle: engine plumbing lives here, alpha stays in
`CometCloudLongShortV4.py` (the freqtrade reference) and in the Macro /
CIS / risk layer (live systems).  Parity is measured against freqtrade LS
V4 OOS run: 2025-05-03 → 2026-03-12, 3 pairs (BTC/ETH/SOL perpetuals),
4h bars.  Expected gap: Nautilus generates MORE trades because the CIS /
regime / funding layer is intentionally behind a feature flag (see
`ENABLE_CIS_GATE` / `ENABLE_ADX_GATE`).

Per the handoff "4 open items" status (2026-07-02):
    1. ADX gate workaround    — implemented (DX + inline Wilder smoothing)
    2. CIS gate wire-in        — implemented as stub (date-keyed lookup,
                                  dense-cache bypass, regime-aware floor)
    3. Side-by-side equity curve — not in this skeleton (runner emits
                                  JSON/CSV; matplotlib is a separate script
                                  to add once we have real data)
    4. Renamed + ship as `CometCloudNautilusLongShortV1` — done.
"""

from .strategy import CometCloudNautilusLongShortV1, LSv1Config
from .data_adapter import build_catalog, CATALOG_DIR, FEATHER_DIR, INSTRUMENTS
from .runner import run_parity, OUT_DIR, RUNNER_CATALOG_DIR

__all__ = [
    "CometCloudNautilusLongShortV1",
    "LSv1Config",
    "build_catalog",
    "CATALOG_DIR",
    "FEATHER_DIR",
    "INSTRUMENTS",
    "run_parity",
    "RUNNER_CATALOG_DIR",
    "OUT_DIR",
]
