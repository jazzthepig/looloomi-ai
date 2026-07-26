"""
Smoke tests for the data-align package (sandbox-safe, synthetic data only).

Tests the three modules:
  - cis_history_schema.py: CSV_COLUMNS, EXPECTED_NCOLS, assert_schema, header_line
  - cis_history_loader.py: header detection, load_cis_history (synthetic),
    prepend_header_if_missing (sandbox-safe temp files), write_with_header
  - cis_history_enrich.py: compute_beta_adjusted_returns (PIT-safe expansion,
    insufficient priors → NaN), compute_regime_zscores (PIT-safe rolling,
    degenerate σ → NaN), coverage_report
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))


def t_schema_constants():
    """CSV_COLUMNS has exactly 20 entries in the documented order."""
    from src.research.data_align.cis_history_schema import (
        CSV_COLUMNS, EXPECTED_NCOLS, NUMERIC_COLUMNS, REQUIRED_COLUMNS,
        REGIMES, VALID_GRADES, VALID_SIGNALS, header_line,
    )
    assert EXPECTED_NCOLS == 20, f"EXPECTED_NCOLS must be 20, got {EXPECTED_NCOLS}"
    assert len(CSV_COLUMNS) == 20, f"CSV_COLUMNS len must be 20, got {len(CSV_COLUMNS)}"
    # Required columns present in canonical order
    assert CSV_COLUMNS[0] == "symbol"
    assert CSV_COLUMNS[10] == "pillar_a", "pillar_a MUST be at position 11 (DATA-ALIGN directive)"
    assert CSV_COLUMNS[-1] == "recorded_at"
    # Numeric vs categorical partitioning
    assert set(NUMERIC_COLUMNS).issubset(set(CSV_COLUMNS))
    assert "pillar_a" in NUMERIC_COLUMNS
    # Required columns all present
    for req in ("symbol", "score", "pillar_f", "pillar_m", "pillar_o",
                "pillar_s", "pillar_a", "recorded_at"):
        assert req in REQUIRED_COLUMNS
    # Header line is comma-separated and starts with 'symbol'
    h = header_line()
    assert h.startswith("symbol,")
    assert h.count(",") == 19, f"Header must have 19 commas (20 cols), got {h.count(',')}"
    # Regimes
    assert len(REGIMES) == 6
    # Compliance-safe signal vocabulary
    assert "OUTPERFORM" in VALID_SIGNALS
    assert "BUY" not in VALID_SIGNALS
    print("  ✓ Schema constants: 20 cols, pillar_a at pos 11, header has 19 commas")


def t_assert_schema_passes():
    """assert_schema accepts canonical column list."""
    from src.research.data_align.cis_history_schema import CSV_COLUMNS, assert_schema
    assert_schema(CSV_COLUMNS)
    # Trailing extras are allowed (enrichment outputs)
    assert_schema(CSV_COLUMNS + ["beta_adj_return", "_date"])
    print("  ✓ assert_schema accepts canonical + extras")


def t_assert_schema_fails_on_wrong_order():
    """assert_schema raises if column order is wrong."""
    from src.research.data_align.cis_history_schema import CSV_COLUMNS, assert_schema
    bad = list(CSV_COLUMNS)
    bad[0], bad[1] = bad[1], bad[0]
    try:
        assert_schema(bad)
    except AssertionError as e:
        assert "Schema mismatch" in str(e)
        print(f"  ✓ assert_schema rejects wrong order: {str(e)[:80]}…")
        return
    raise AssertionError("assert_schema must raise on wrong order")


def t_assert_schema_fails_on_missing_column():
    """assert_schema raises if a required column is missing."""
    from src.research.data_align.cis_history_schema import assert_schema
    bad = ["symbol", "name", "score"]  # missing pillar_a and more
    try:
        assert_schema(bad)
    except AssertionError:
        print("  ✓ assert_schema rejects missing-required")
        return
    raise AssertionError("assert_schema must raise on missing column")


def t_loader_detects_header():
    """Header detection: first token == 'symbol'."""
    from src.research.data_align.cis_history_loader import _detect_header
    assert _detect_header("symbol,name,score,...")
    assert not _detect_header("BTC,BTC,29.76,...")
    print("  ✓ _detect_header correctly classifies header vs data rows")


def t_loader_synthetic_round_trip():
    """load_cis_history returns a DataFrame matching CSV_COLUMNS (synthetic)."""
    from src.research.data_align.cis_history_loader import load_cis_history
    from src.research.data_align.cis_history_schema import CSV_COLUMNS

    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        # Header-less synthetic 5-row CSV (header will be auto-prepended in load)
        rows = []
        for i in range(5):
            # 20 fields, 19 commas: symbol,name,score,raw,grade,signal,f,m,o,s,a,class,regime,tier,las,conf,score_delta,score_zscore,source,recorded_at
            rows.append("BTC,BTC,50.0,50.0,B,OUTPERFORM,40,50,60,50,50,L1,EASING,T2_historical,50.0,0.7,,,historical_reconstruction,2024-01-{:02d}T12:00:00+00:00".format(i + 1))
        # Use raw concat (no header line — the loader will detect & name)
        f.write("\n".join(rows))
        tmp = f.name

    try:
        df = load_cis_history(tmp, force_schema=True)
        assert len(df) == 5, f"Expected 5 rows, got {len(df)}"
        assert list(df.columns)[:20] == CSV_COLUMNS
        # Numeric coercion works
        assert df["score"].dtype.kind == "f"
        assert df["pillar_a"].iloc[0] == 50.0
        # Date parsed to _date column
        assert "_date" in df.columns
        assert pd.notna(df["_date"].iloc[0])
        print(f"  ✓ load_cis_history round-trip: 5 rows × {len(df.columns)} cols, "
              f"date col parsed")
    finally:
        os.unlink(tmp)


def t_prepend_header_idempotent():
    """prepend_header_if_missing is idempotent."""
    from src.research.data_align.cis_history_loader import prepend_header_if_missing

    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        f.write("BTC,BTC,50.0,...\n")  # no header
        tmp = f.name

    try:
        added = prepend_header_if_missing(tmp)
        assert added is True, "First call should add header"
        added_again = prepend_header_if_missing(tmp)
        assert added_again is False, "Second call should be a no-op"
        # First line should now be the canonical header
        with open(tmp) as f:
            first = f.readline().strip()
        assert first.startswith("symbol,"), f"Header line malformed: {first}"
        # Row count preserved (75,477 + 1 header in production; here just 2)
        with open(tmp) as f:
            line_count = sum(1 for _ in f)
        assert line_count == 2, f"Expected 2 lines (1 header + 1 row), got {line_count}"
        print(f"  ✓ prepend_header_if_missing: idempotent (added=True → False on 2nd)")
    finally:
        os.unlink(tmp)


def t_beta_adjusted_returns_pit_safe():
    """β at time t uses ONLY prior observations. First 20 rows get NaN."""
    from src.research.data_align.cis_history_enrich import compute_beta_adjusted_returns

    # 60 days × 2 assets (BTC + ALT). Synthetic returns: ALT = 1.5 * BTC + noise
    rng = np.random.default_rng(42)
    n_days = 60
    dates = pd.date_range("2024-01-01", periods=n_days, freq="D")
    btc_ret = rng.normal(0.001, 0.02, n_days)
    alt_ret = 1.5 * btc_ret + rng.normal(0, 0.005, n_days)
    rets_wide = pd.DataFrame({"BTC": btc_ret, "ALT": alt_ret}, index=dates)

    # Build input df: 2 rows per date (BTC + ALT) → 120 rows total
    df = pd.DataFrame({
        "symbol": (["BTC"] * n_days) + (["ALT"] * n_days),
        "score": 50.0,
        "_date": list(dates) + list(dates),
    })

    out = compute_beta_adjusted_returns(df, rets_wide, benchmark="BTC")
    # BTC's beta-adj should be NaN (BTC vs itself = β=1, but α = btc - 1*btc = 0;
    # however MIN_PRIORS=20 means first 19 are NaN, then 0 thereafter for BTC).
    btc_rows = out[out["symbol"] == "BTC"].sort_values("_date")
    alt_rows = out[out["symbol"] == "ALT"].sort_values("_date")
    # First 19 BTC rows: NaN
    assert btc_rows["beta_adj_return"].iloc[:19].isna().all(), "BTC β should be NaN for first 19 rows"
    # After row 19, BTC β ≈ 1.0, so α ≈ 0
    btc_finite = btc_rows["beta_adj_return"].dropna()
    assert (btc_finite.abs() < 1e-6).all(), f"BTC α should be ~0, got max |α|={btc_finite.abs().max()}"
    # ALT: first 19 NaN, then nonzero (residual)
    assert alt_rows["beta_adj_return"].iloc[:19].isna().all(), "ALT β should be NaN for first 19 rows"
    alt_finite = alt_rows["beta_adj_return"].dropna()
    # ALT has true β=1.5 + noise; after β-adj, residual is the noise term only
    assert alt_finite.std() < 0.01, f"ALT β-adj std should be small (~noise), got {alt_finite.std()}"
    print(f"  ✓ β-adj PIT-safe: first 19 NaN, BTC α≈0 (max={btc_finite.abs().max():.2e}), "
          f"ALT residual std={alt_finite.std():.4f}")


def t_regime_zscores_pit_safe():
    """regime_zscore at t uses only prior rows (rolling+shift)."""
    from src.research.data_align.cis_history_enrich import compute_regime_zscores

    # 300 days × 5 assets × 1 regime (RISK_ON). Synthetic pillar values.
    rng = np.random.default_rng(7)
    n_days, n_assets = 300, 5
    dates = pd.date_range("2024-01-01", periods=n_days, freq="D")
    rows = []
    for d in dates:
        for a in range(n_assets):
            rows.append({
                "symbol": f"A{a}",
                "score": rng.normal(50, 10),
                "pillar_f": rng.normal(40, 8),
                "pillar_m": rng.normal(60, 12),
                "pillar_o": rng.normal(55, 9),
                "pillar_s": rng.normal(50, 10),
                "pillar_a": rng.normal(45, 11),
                "macro_regime": "RISK_ON",
                "_date": d,
            })
    df = pd.DataFrame(rows)
    out = compute_regime_zscores(df, lookback=60, pillars=("f", "a"))

    # With lookback=60, min_periods=20, shift(1): first 20 rows per asset must be NaN.
    # Rolling window at row t uses rows [t-59, t-1]; min_periods=20 means at least
    # 20 obs required. Row 0 has 0 prior obs; row 19 has 19 obs (still < 20); row 20
    # has 20 obs. So rows 0-19 should be NaN, rows 20+ finite.
    for sym in [f"A{i}" for i in range(n_assets)]:
        g = out[out["symbol"] == sym].sort_values("_date")
        first_20 = g.iloc[:20]
        later = g.iloc[20:]
        assert first_20["regime_zscore_f"].isna().all(), \
            f"{sym} regime_zscore_f should be NaN for first 20 rows (min_periods=20+shift(1))"
        assert first_20["regime_zscore_a"].isna().all(), \
            f"{sym} regime_zscore_a should be NaN for first 20 rows"
        finite_f = later["regime_zscore_f"].dropna()
        finite_a = later["regime_zscore_a"].dropna()
        assert len(finite_f) > 0, f"{sym} should have finite z-scores after row 20"
        # |z| values are roughly bounded (mostly within ±5 for N(0,1)-ish)
        assert finite_f.abs().max() < 10, \
            f"{sym} z-scores should be bounded, got max |z|={finite_f.abs().max()}"
    print(f"  ✓ regime_zscores PIT-safe: first 20 NaN per asset (lookback=60, min_periods=20, shift(1))")


def t_coverage_report():
    """coverage_report: empty series → coverage_ok=False (uses MIN_PRIORS=20)."""
    from src.research.data_align.cis_history_enrich import coverage_report, MIN_PRIORS
    # HAS has 3 obs (< MIN_PRIORS=20 → coverage_ok=False even though it has data)
    # EMPTY has 0 obs → coverage_ok=False
    rets_wide = pd.DataFrame({"HAS": [0.01, 0.02, np.nan, 0.03], "EMPTY": [np.nan] * 4})
    cov = coverage_report(rets_wide)
    has_row = cov[cov["symbol"] == "HAS"].iloc[0]
    empty_row = cov[cov["symbol"] == "EMPTY"].iloc[0]
    assert has_row["n_obs"] == 3
    assert empty_row["n_obs"] == 0
    assert bool(has_row["coverage_ok"]) is False, \
        f"HAS has 3 obs < MIN_PRIORS={MIN_PRIORS} → coverage_ok=False expected"
    assert bool(empty_row["coverage_ok"]) is False
    # First/last_date for EMPTY should be NaT
    assert pd.isna(empty_row["first_date"])
    assert pd.isna(empty_row["last_date"])
    print(f"  ✓ coverage_report: HAS n_obs=3 (False, {MIN_PRIORS} floor), EMPTY n_obs=0 (False)")


# === Test runner ==============================================================
TESTS = [
    t_schema_constants,
    t_assert_schema_passes,
    t_assert_schema_fails_on_wrong_order,
    t_assert_schema_fails_on_missing_column,
    t_loader_detects_header,
    t_loader_synthetic_round_trip,
    t_prepend_header_idempotent,
    t_beta_adjusted_returns_pit_safe,
    t_regime_zscores_pit_safe,
    t_coverage_report,
]


def main() -> int:
    print(f"Running {len(TESTS)} data-align smoke tests …\n")
    failed = 0
    for t in TESTS:
        try:
            t()
        except AssertionError as e:
            print(f"  ✗ {t.__name__} FAILED: {e}")
            failed += 1
        except Exception as e:
            print(f"  ✗ {t.__name__} ERROR: {type(e).__name__}: {e}")
            failed += 1
    total = len(TESTS)
    passed = total - failed
    print(f"\n{passed}/{total} test(s) passed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())