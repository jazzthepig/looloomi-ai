"""
freqtrade package — parity-check helpers for the empirical-grid edge gate.

This package complements `src/research/nautilus/ls_v1/` (Minimax-B's lane) so that
Minimax-C's freqtrade V-family strategies can run the SAME gate that Nautilus LS v1
runs (B1 → C1 parity per §ASSIGNMENTS 2026-07-06).

Components:
  - empirical_grid_gate.py: the freqtrade-compatible wrapper that loads the shrunk
    edge-map grid + BTC band snapshot and exposes `gate_passes(tier, band, side)`
    so a strategy can call it from `confirm_trade_entry` (defense-in-depth) or
    `populate_entry_trend` (pre-filter).
  - c1_parity_ab.py: A/B driver that replays a cached freqtrade backtest JSON
    against BOTH the legacy CIS-floor gate AND the empirical-grid gate,
    producing a side-by-side CSV with n_trades / pnl / sharpe / max_loss.

Owner: minimax-b (Austin) per CLAUDE.md. The wrapper is purely additive — it does
NOT modify any strategy file under `/Volumes/CometCloudAI/cometcloud-local/
user_data/strategies/`. Minimax-C imports the wrapper into V-family strategies
when wiring C1.
"""
