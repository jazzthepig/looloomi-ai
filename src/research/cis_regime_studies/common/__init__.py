"""common package for cis_regime_studies."""
from .data_loader import load_cis_history, load_ohlcv_panel, build_research_panel
from .metrics import (
    ic_pearson, ic_spearman, ic_table,
    quantile_spreads,
    annualised_sharpe, annualised_sortino, calmar,
    holm_bonferroni, bonferroni,
    normalise_regime,
)

__all__ = [
    "load_cis_history", "load_ohlcv_panel", "build_research_panel",
    "ic_pearson", "ic_spearman", "ic_table",
    "quantile_spreads",
    "annualised_sharpe", "annualised_sortino", "calmar",
    "holm_bonferroni", "bonferroni",
    "normalise_regime",
]