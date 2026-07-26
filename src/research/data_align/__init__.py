"""
Data-align package — single source of truth for the 11yr CIS historical CSV.

Modules:
  cis_history_schema   canonical column order + validation
  cis_history_loader   header-aware CSV reader
  cis_history_enrich   β-adj returns + regime-normalized pillar z-scores
"""
from src.research.data_align.cis_history_schema import (
    CSV_COLUMNS,
    NUMERIC_COLUMNS,
    CATEGORICAL_COLUMNS,
    REQUIRED_COLUMNS,
    EXPECTED_NCOLS,
    REGIMES,
    VALID_GRADES,
    VALID_SIGNALS,
    assert_schema,
    header_line,
)

__all__ = [
    "CSV_COLUMNS", "NUMERIC_COLUMNS", "CATEGORICAL_COLUMNS", "REQUIRED_COLUMNS",
    "EXPECTED_NCOLS", "REGIMES", "VALID_GRADES", "VALID_SIGNALS",
    "assert_schema", "header_line",
]