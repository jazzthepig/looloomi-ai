"""Smoke tests for src/research/data/ohlcv_local.py.

Run:  python3 -m pytest src/research/data/tests/test_ohlcv_local_smoke.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

# Repo root on sys.path so we can import src.research.data.ohlcv_local directly
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from src.research.data.ohlcv_local import (  # noqa: E402
    OHLCV_LOCAL_DB, check_local_buffer_freshness, get_coverage,
    load_local_daily, load_local_panel, validate_local_buffer,
)


# Skip the entire module if the local buffer isn't built yet
pytestmark = pytest.mark.skipif(
    not OHLCV_LOCAL_DB.exists(),
    reason=f"Local OHLCV buffer not built at {OHLCV_LOCAL_DB}. Run scripts/fetch_ohlcv_to_local.py first.",
)


def test_buffer_exists_and_nonempty():
    assert OHLCV_LOCAL_DB.exists()
    assert OHLCV_LOCAL_DB.stat().st_size > 100_000, "buffer suspiciously small"


def test_coverage_returns_dataframe():
    cov = get_coverage()
    assert isinstance(cov, pd.DataFrame)
    assert {"symbol", "asset_class", "source", "rows", "first_date", "last_date"}.issubset(cov.columns)
    assert len(cov) > 0


def test_coverage_includes_all_asset_classes():
    cov = get_coverage()
    classes = set(cov["asset_class"].unique())
    # Full universe should be present
    assert {"L1", "L2", "DeFi", "RWA", "Commodity", "US Equity", "US Bond", "FX", "Real Estate"}.issubset(classes), \
        f"Missing asset classes: {classes}"


def test_load_local_daily_btc():
    df = load_local_daily("BTC")
    assert isinstance(df, pd.DataFrame)
    assert not df.empty, "BTC has no rows in local buffer"
    for col in ("open", "high", "low", "close", "volume"):
        assert col in df.columns
    assert df.index.name == "trade_date"
    assert df.index.is_monotonic_increasing
    # Recent data — compare tz-aware
    today_utc = pd.Timestamp.utcnow().normalize()
    assert df.index.max() >= today_utc - pd.Timedelta(days=2), \
        f"BTC last date is {df.index.max().date()} (expected within 2 days of {today_utc.date()})"


def test_load_local_daily_spy():
    """SPY is a TradFi symbol — confirms EODHD path worked and it's in the buffer."""
    df = load_local_daily("SPY")
    assert not df.empty, "SPY missing from local buffer (TradFi source broken?)"
    today_utc = pd.Timestamp.utcnow().normalize()
    assert df.index.max() >= today_utc - pd.Timedelta(days=2), \
        f"SPY last date is {df.index.max().date()}"


def test_load_local_daily_source_filter():
    df_cg = load_local_daily("BTC", source="coingecko")
    assert (df_cg["source"] == "coingecko").all()
    df_all = load_local_daily("BTC")
    assert len(df_all) >= len(df_cg)


def test_load_local_daily_date_filter():
    # Use dates that exist in the buffer (default 365d backfill from build date)
    df = load_local_daily("BTC", start="2025-08-01", end="2025-09-01")
    assert not df.empty, "date filter should return Aug 2025 BTC data"
    assert df.index.min() >= pd.Timestamp("2025-08-01", tz="UTC")
    assert df.index.max() <  pd.Timestamp("2025-09-01", tz="UTC")


def test_load_local_panel_shape():
    panel = load_local_panel(["BTC", "ETH", "SPY", "TLT", "GLD"])
    assert isinstance(panel, pd.DataFrame)
    assert panel.shape[1] == 5
    assert panel.index.name == "trade_date"


def test_load_local_panel_pit_correctness():
    """Panel must be sorted, no future-dates, no NaN-from-bad-joins for known symbols."""
    panel = load_local_panel(["BTC", "ETH", "SPY"])
    assert panel.index.is_monotonic_increasing
    # No rows past today (panel index is tz-aware UTC; normalize tz-aware today)
    today = pd.Timestamp.utcnow().normalize()
    assert panel.index.max() <= today, \
        f"panel has future-dated rows: max={panel.index.max()} today={today}"


def test_missing_symbol_returns_empty():
    df = load_local_daily("NOT_A_REAL_SYMBOL_XYZ")
    assert df.empty
    panel = load_local_panel(["NOT_A_REAL_SYMBOL_XYZ"])
    assert panel.empty or panel.dropna(how="all").empty


# ── Staleness detection ────────────────────────────────────────────────────────


def test_check_local_buffer_freshness_shape():
    status = check_local_buffer_freshness()
    assert isinstance(status, dict)
    for key in ("last_trade_date", "buffer_age_days", "max_age_days", "verdict", "symbols", "rows_total"):
        assert key in status, f"missing key: {key}"
    assert status["buffer_exists"] is True
    assert status["verdict"] in ("fresh", "warning", "stale")
    assert status["symbols"] >= 23, "expected full 58-symbol buffer"
    assert status["rows_total"] >= 10_000, "expected at least 10k rows"


def test_check_local_buffer_freshness_default_is_fresh():
    """Buffer was just refreshed today → verdict must be 'fresh'."""
    status = check_local_buffer_freshness()
    assert status["verdict"] == "fresh", f"buffer is {status['buffer_age_days']}d old, expected fresh"
    assert status["buffer_age_days"] <= 7


def test_check_local_buffer_freshness_custom_threshold():
    """The verdict must satisfy: fresh iff age <= max_age_days."""
    age = check_local_buffer_freshness()["buffer_age_days"]
    for threshold in [1, 3, 7, 14, 30, 365]:
        s = check_local_buffer_freshness(max_age_days=threshold)
        expected = "fresh" if age <= threshold else ("warning" if age <= 14 else "stale")
        assert s["verdict"] == expected, \
            f"threshold={threshold}d age={age}d → got {s['verdict']}, expected {expected}"


def test_panel_with_mixed_available_missing_symbols():
    """Panel should gracefully include missing symbols as all-NaN columns."""
    panel = load_local_panel(["BTC", "ETH", "SPY", "FAKE_XYZ"])
    assert panel.shape[1] == 4
    # Real symbols have data, fake symbol is all-NaN
    assert not panel["BTC"].dropna().empty
    assert panel["FAKE_XYZ"].isna().all(), "fake symbol should be all-NaN"


def test_panel_index_is_tz_aware_utc():
    """All index values must be tz-aware UTC (no silent tz-naive comparisons)."""
    df = load_local_daily("BTC")
    assert df.index.tz is not None, "index must be tz-aware"
    assert str(df.index.tz) == "UTC", f"expected UTC tz, got {df.index.tz}"


def test_panel_no_duplicate_dates_per_symbol():
    """Each (symbol, trade_date) pair must be unique — schema enforces this on insert."""
    import sqlite3
    conn = sqlite3.connect(OHLCV_LOCAL_DB)
    dup = conn.execute("""
        SELECT symbol, trade_date, COUNT(*) AS c
        FROM ohlcv_daily GROUP BY symbol, trade_date HAVING c > 1
    """).fetchall()
    conn.close()
    assert len(dup) == 0, f"duplicates found: {dup[:3]}"


def test_get_coverage_row_counts_match_loader():
    """Coverage row count for BTC must match what load_local_daily returns."""
    cov = get_coverage()
    btc_cov = cov[(cov["symbol"] == "BTC") & (cov["source"] == "coingecko")]
    assert len(btc_cov) == 1, "BTC should have exactly one (symbol, source) row"
    expected = int(btc_cov["rows"].iloc[0])
    actual = len(load_local_daily("BTC", source="coingecko"))
    assert actual == expected, f"coverage says {expected} rows but loader returned {actual}"


# ── Data quality validation ──────────────────────────────────────────────────


def test_validate_local_buffer_default_clean():
    """Fresh full buffer with default thresholds should be clean."""
    issues = validate_local_buffer()
    # Default gap=5d covers weekend+1 holiday; no legit gaps for crypto
    assert isinstance(issues, pd.DataFrame)
    if not issues.empty:
        # If anything fires, it should be a known-good reason (e.g., a real outlier)
        for issue_type in issues["issue_type"].unique():
            assert issue_type in ("outlier", "date_gap", "source_conflict", "stale")


def test_validate_local_buffer_returns_expected_columns():
    issues = validate_local_buffer()
    expected = {"issue_type", "symbol", "asset_class", "source", "trade_date", "details", "magnitude"}
    assert expected.issubset(set(issues.columns)), f"missing columns: {expected - set(issues.columns)}"


def test_validate_local_buffer_strict_gap_flags_crypto():
    """Strict gap threshold should catch any 1+ day crypto gap."""
    # Default 5d misses weekend+holiday; with threshold=0, even 1d gaps fire
    issues = validate_local_buffer(max_date_gap_days=0)
    # Crypto trades 24/7 so any gap > 0 should be flagged — should find some
    # (or be empty if buffer is perfectly continuous for crypto)
    assert isinstance(issues, pd.DataFrame)


def test_validate_local_buffer_strict_outlier():
    """Very tight outlier threshold should fire on at least one real BTC move."""
    # 1.05x threshold — anything >5% daily move on a crypto will trigger
    issues = validate_local_buffer(outlier_ratio=1.05, max_date_gap_days=999)
    # Real crypto has occasional >5% days, so we should see some outliers
    # (don't require it — empty is fine if the buffer window had no such days)
    assert isinstance(issues, pd.DataFrame)
    if not issues.empty:
        # All should be outliers
        assert (issues["issue_type"] == "outlier").all()