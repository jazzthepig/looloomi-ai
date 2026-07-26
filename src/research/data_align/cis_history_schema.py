"""
Canonical schema for the 11yr CIS historical CSV (`cis_historical_11yr.csv`).

This is the SINGLE SOURCE OF TRUTH for the column order and pillar semantics
of the 11yr historical reconstruction. Replaces the duplicated definitions that
previously lived in:

  - scripts/cis_historical_ingest.py::CSV_COLUMNS
  - src/research/cis_regime_studies/absorption_sweep_runner.py::_CIS_HIST_COLS

Both modules now `from src.research.data_align.cis_history_schema import CSV_COLUMNS`.

Schema alignment contract (per MINIMAX_SYNC §DATA-ALIGN directive, Jazz 2026-07-24):
  - Column order MUST match the Supabase `cis_scores` table (see
    scripts/supabase_migration_timeseries.sql). Mismatch ⇒ ingest fails silently.
  - pillar_a (Alpha) is REQUIRED. Earlier versions of the reconstruction skipped
    pillar_a for some legacy rows; the 2026-07-18 rebuild is 100% populated
    (75,478 rows × 34 assets, verified 2026-07-24 by Seth).
  - regime normalization is TRAILING-ONLY per §PIT-LEAK-C 2026-07-21. Never
    full-sample — that is the look-ahead bug class `pit_guard.py` exists to
    catch.

Naming conventions:
  - Pillar column names match the production schema (`pillar_f/m/o/s/a`), not
    the abbreviated `f/m/o/s/a` keys used in the live CIS push payload.
  - snake_case throughout. The Supabase columns are snake_case; matching that
    keeps the ingest path one-to-one.
"""
from __future__ import annotations

# ── Canonical column order (matches Supabase cis_scores schema) ──────────────
# Order is significant: this is the position-indexed read order for the
# header-less CSV. Adding/removing columns requires a migration (column reorder
# is breaking — older readers will misalign positional fields).
CSV_COLUMNS: list[str] = [
    "symbol",          #  1. ticker (e.g. "BTC")
    "name",            #  2. human-readable name (often == symbol)
    "score",           #  3. final composite CIS score (regime-adjusted)
    "raw_cis_score",   #  4. pre-regime composite
    "grade",           #  5. letter grade (A+/A/B+/B/C+/C/D/F)
    "signal",          #  6. positioning signal (compliance-safe vocabulary)
    "pillar_f",        #  7. Fundamental pillar (TVL, revenue, user growth)
    "pillar_m",        #  8. Momentum pillar
    "pillar_o",        #  9. On-chain / Risk-adjusted pillar
    "pillar_s",        # 10. Sentiment pillar
    "pillar_a",        # 11. Alpha pillar (independent of BTC/SPY)
    "asset_class",     # 12. L1 / L2 / DeFi / RWA / Memecoin / Gaming / AI / Commodity / US Equity / US Bond
    "macro_regime",    # 13. regime label at time of scoring
    "data_tier",       # 14. T1 / T2 / T2_historical
    "las",             # 15. Liquidity-Adjusted Score
    "confidence",      # 16. data completeness 0..1
    "score_delta",     # 17. change vs previous push for same symbol
    "score_zscore",    # 18. z-score vs 30-day rolling mean/std (trailing-only)
    "source",          # 19. ingest source (historical_reconstruction / local_engine / ...)
    "recorded_at",     # 20. timestamp (ISO8601 with timezone)
]

# ── Type coercion hints (for pandas readers / dtypes) ────────────────────────
NUMERIC_COLUMNS: tuple[str, ...] = (
    "score", "raw_cis_score",
    "pillar_f", "pillar_m", "pillar_o", "pillar_s", "pillar_a",
    "las", "confidence", "score_delta", "score_zscore",
)

CATEGORICAL_COLUMNS: tuple[str, ...] = (
    "grade", "signal", "asset_class", "macro_regime", "data_tier", "source",
)

# Columns that MUST be present (rebuild fails if any is missing).
REQUIRED_COLUMNS: tuple[str, ...] = (
    "symbol", "score", "pillar_f", "pillar_m", "pillar_o", "pillar_s", "pillar_a",
    "recorded_at",
)

# ── Validation: column count ─────────────────────────────────────────────────
EXPECTED_NCOLS: int = len(CSV_COLUMNS)  # 20


def assert_schema(df_columns: list[str]) -> None:
    """Raise AssertionError if `df_columns` does not match the canonical order.

    Permits EXTRA trailing columns (e.g. enrichment outputs `beta_adj_return`,
    `regime_zscore_f`, etc.) but the first 20 must be in the canonical order.
    """
    n = len(df_columns)
    if n < EXPECTED_NCOLS:
        raise AssertionError(
            f"Schema mismatch: expected ≥{EXPECTED_NCOLS} columns, got {n}. "
            f"Got: {df_columns}"
        )
    for i, expected in enumerate(CSV_COLUMNS):
        if df_columns[i] != expected:
            raise AssertionError(
                f"Schema mismatch at position {i}: expected '{expected}', got "
                f"'{df_columns[i]}'. The 11yr CSV column order must match the "
                f"canonical CSV_COLUMNS list."
            )
    for req in REQUIRED_COLUMNS:
        if req not in df_columns[:EXPECTED_NCOLS]:
            raise AssertionError(f"Required column missing: {req}")


def header_line() -> str:
    """Return the canonical CSV header line (comma-separated, no trailing newline)."""
    return ",".join(CSV_COLUMNS)


# ── Regimes (canonical names; mirrors CISMethodology §6) ─────────────────────
REGIMES: tuple[str, ...] = (
    "RISK_ON", "RISK_OFF", "TIGHTENING", "EASING", "STAGFLATION", "GOLDILOCKS",
)

VALID_GRADES: frozenset[str] = frozenset(
    {"A+", "A", "B+", "B", "C+", "C", "D", "F"}
)

# Compliance-safe signal vocabulary (NEVER buy/sell — CLAUDE.md rule #1).
VALID_SIGNALS: frozenset[str] = frozenset({
    "STRONG OUTPERFORM", "OUTPERFORM", "NEUTRAL", "UNDERPERFORM", "UNDERWEIGHT",
})