"""
CIS × Macro Regime Interaction — research package (Seth/Austin, 2026-07-06)
==============================================================================

Five testable hypotheses at AQR / Millennium standards of empirical rigor:

    H1 — regime-conditional IC (AQR): Pearson + Spearman IC of CIS pillars vs
         forward returns, broken down by macro regime.
    H2 — floor calibration (AQR): empirical calibration of REGIME_CIS_FLOOR
         against walk-forward OOS Sharpe; percentile-based vs hand-tuned.
    H3 — continuous vs hard gate (Millennium): replace binary CIS gate with
         conviction-scaled entry; compare 5 Nautilus variants.
    H4 — regime transition vintage (AQR): first-N-days post-transition
         distribution differs from stable-bucket baseline.
    H5 — signal diversification (Millennium): CIS + funding rate + momentum
         combinations per regime; diversification benefit.

Public surface:
    common.data_loader.load_cis_history       — daily CIS → long-form DataFrame
    common.data_loader.load_ohlcv_panel      — parquets → panel
    common.data_loader.build_research_panel  — join CIS × regime × fwd returns
    common.regime_history.regime_series      — extract regime time-series
    common.metrics.ic_table                  — IC per (pillar, regime) cell
    common.metrics.quantile_spreads          — top-q vs bottom-q fwd returns
    common.metrics.sharpe_sortino_calmar     — risk-adjusted return helpers

    h1_regime_ic.run_h1                      — full H1 pipeline → report + JSON
    h2_floor_calibration.run_h2              — H2 sweep (BLOCKED on H1)
    h3_continuous_gate.run_h3                — H3 Nautilus variants (BLOCKED on H2)

Per CLAUDE.md: research-only work lives in `src/research/`. No deploy
implications until Jazz signs off.
"""