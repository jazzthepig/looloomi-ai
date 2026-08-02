"""Local SQLite OHLCV loader — off-engine data source for research code.

Background — Jazz 2026-07-26:
  Production reads from Supabase ohlcv_daily (Mac-side daily loop covers 22
  crypto + AAPL). The 35 TradFi symbols (US Equity/Bond/Commodity/FX/REIT/EM
  Equity) are NOT in Supabase — Mac-side doesn't write them, Railway daily
  loop has been silently dead (httpx UA bug + publishable-key INSERT 401).
  Per Jazz decision, do NOT push to Supabase. Local SQLite is now the
  off-engine data source for any research that needs the full 58-symbol
  universe (especially cross-asset / risk-on-off factor work).

Source: /tmp/cometcloud_data/ohlcv.db (idempotent, key = (symbol, trade_date, source))
Schema:
    symbol, asset_class, source, trade_date, open, high, low, close, volume

Refresh: `python3 scripts/fetch_ohlcv_to_local.py`  (CG Pro + Hyperliquid + EODHD,
~60s for full 58-symbol × 365d).

Usage:
    from src.research.data.ohlcv_local import load_local_daily, get_coverage

    df = load_local_daily("SPY")                     # single symbol, full history
    panel = load_local_panel(["BTC","ETH","SPY"])    # multi-symbol
    cov = get_coverage()                             # what's in the buffer
"""
from __future__ import annotations

import logging
import os
import sqlite3
import subprocess
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd

OHLCV_LOCAL_DB = Path("/tmp/cometcloud_data/ohlcv.db")
FETCH_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "fetch_ohlcv_to_local.py"
DEFAULT_MAX_AGE_DAYS = 7
WARNING_AGE_DAYS = 14   # > 14 days = stale, anything in between = warning
_LOUD = os.environ.get("LOUD_LOCAL_OHLCV", "").strip() in ("1", "true", "yes")

_logger = logging.getLogger(__name__)


def _conn() -> sqlite3.Connection:
    if not OHLCV_LOCAL_DB.exists():
        raise FileNotFoundError(
            f"Local OHLCV buffer not found at {OHLCV_LOCAL_DB}. "
            f"Run: python3 {FETCH_SCRIPT}"
        )
    return sqlite3.connect(OHLCV_LOCAL_DB)


def _maybe_warn_stale() -> None:
    """If LOUD_LOCAL_OHLCV=1, emit a UserWarning when buffer is stale."""
    if not _LOUD:
        return
    status = check_local_buffer_freshness(max_age_days=DEFAULT_MAX_AGE_DAYS)
    if status["verdict"] == "stale":
        warnings.warn(
            f"Local OHLCV buffer is {status['buffer_age_days']}d stale "
            f"(last={status['last_trade_date']}). "
            f"Run: python3 {FETCH_SCRIPT}",
            UserWarning,
            stacklevel=3,
        )
    elif status["verdict"] == "warning":
        warnings.warn(
            f"Local OHLCV buffer is {status['buffer_age_days']}d old "
            f"(warning band, last={status['last_trade_date']})",
            UserWarning,
            stacklevel=3,
        )


def load_local_daily(
    symbol: str,
    source: str | None = None,
    start: str | None = None,
    end: str | None = None,
) -> pd.DataFrame:
    """Load daily OHLCV for one symbol from local SQLite.

    Args:
        symbol: ticker (e.g. "BTC", "SPY", "TLT")
        source: filter by source ("coingecko"|"hyperliquid"|"eodhd"|None=any)
        start/end: ISO date strings ("2024-06-01"), inclusive start, exclusive end

    Returns:
        DataFrame with columns [trade_date, open, high, low, close, volume, source]
        indexed by trade_date (UTC).
    """
    _maybe_warn_stale()
    where, params = ["symbol = ?"], [symbol.upper()]
    if source:
        where.append("source = ?")
        params.append(source)
    if start:
        where.append("trade_date >= ?")
        params.append(start)
    if end:
        where.append("trade_date < ?")
        params.append(end)
    sql = (
        "SELECT trade_date, open, high, low, close, volume, source "
        f"FROM ohlcv_daily WHERE {' AND '.join(where)} ORDER BY trade_date"
    )
    df = pd.read_sql_query(sql, _conn(), params=params)
    if df.empty:
        return df
    df["trade_date"] = pd.to_datetime(df["trade_date"], utc=True)
    df = df.set_index("trade_date").sort_index()
    return df


def load_local_panel(
    symbols: Iterable[str],
    source: str | None = None,
    start: str | None = None,
    end: str | None = None,
) -> pd.DataFrame:
    """Multi-symbol close-price panel (Date × symbol).

    Returns the close-price matrix from the local buffer. Useful for cross-asset
    return/correlation/factor work where Supabase would have a 35-symbol gap.
    """
    _maybe_warn_stale()
    syms = [s.upper() for s in symbols]
    where, params = [f"symbol IN ({','.join('?' * len(syms))})"], syms
    if source:
        where.append("source = ?")
        params.append(source)
    if start:
        where.append("trade_date >= ?")
        params.append(start)
    if end:
        where.append("trade_date < ?")
        params.append(end)
    sql = (
        "SELECT symbol, trade_date, close FROM ohlcv_daily "
        f"WHERE {' AND '.join(where)} ORDER BY trade_date"
    )
    df = pd.read_sql_query(sql, _conn(), params=params)
    df["trade_date"] = pd.to_datetime(df["trade_date"], utc=True)
    if df.empty:
        # No data for any requested symbol — return an empty panel that still
        # has the requested symbols as columns (all NaN) so callers can detect
        # the missing universe slice without surprise.
        idx = pd.DatetimeIndex([], tz="UTC", name="trade_date")
        return pd.DataFrame(index=idx, columns=list(syms))
    panel = df.pivot(index="trade_date", columns="symbol", values="close").sort_index()
    # Re-index columns to ensure every requested symbol appears (even if all-NaN).
    panel = panel.reindex(columns=list(syms))
    panel.index.name = "trade_date"
    return panel


def get_coverage() -> pd.DataFrame:
    """Per-symbol row counts + date range + source — for the audit dashboard."""
    sql = """
        SELECT symbol, asset_class, source,
               COUNT(*) AS rows,
               MIN(trade_date) AS first_date,
               MAX(trade_date) AS last_date
        FROM ohlcv_daily
        GROUP BY symbol, asset_class, source
        ORDER BY asset_class, symbol
    """
    return pd.read_sql_query(sql, _conn(), parse_dates=["first_date", "last_date"])


def check_local_buffer_freshness(max_age_days: int = DEFAULT_MAX_AGE_DAYS) -> dict:
    """Lightweight probe — does NOT re-fetch.

    Args:
        max_age_days: threshold (days) below which the buffer is "fresh".
            Above `WARNING_AGE_DAYS` (14) is "stale"; in between is "warning".

    Returns:
        dict with keys: last_trade_date, buffer_age_days, max_age_days,
        verdict ("fresh"|"warning"|"stale"), symbols (distinct), rows_total.

    Use this at the top of research scripts to fail-fast on stale data,
    or set LOUD_LOCAL_OHLCV=1 to auto-warn on every loader call.
    """
    if not OHLCV_LOCAL_DB.exists():
        return {
            "buffer_exists": False,
            "verdict": "stale",
            "error": f"buffer not found at {OHLCV_LOCAL_DB}",
            "max_age_days": max_age_days,
        }
    sql = """
        SELECT MAX(trade_date) AS last_trade_date,
               COUNT(DISTINCT symbol) AS symbols,
               COUNT(*) AS rows_total
        FROM ohlcv_daily
    """
    with _conn() as conn:
        row = conn.execute(sql).fetchone()
    last_str = row[0]
    today = datetime.now(timezone.utc).date()
    if last_str:
        last_date = datetime.fromisoformat(last_str).date()
        age = (today - last_date).days
    else:
        last_date = None
        age = 9999
    if age <= max_age_days:
        verdict = "fresh"
    elif age <= WARNING_AGE_DAYS:
        verdict = "warning"
    else:
        verdict = "stale"
    return {
        "buffer_exists": True,
        "last_trade_date": last_str,
        "last_trade_date_iso": last_date.isoformat() if last_date else None,
        "buffer_age_days": age,
        "max_age_days": max_age_days,
        "verdict": verdict,
        "symbols": row[1] or 0,
        "rows_total": row[2] or 0,
    }


# ── Data quality validation ──────────────────────────────────────────────────
def validate_local_buffer(
    outlier_ratio: float = 10.0,
    source_divergence_pct: float = 5.0,
    max_date_gap_days: int = 5,
) -> pd.DataFrame:
    """Scan the SQLite buffer for quality issues.

    Args:
        outlier_ratio: flag close/prev_close moves above this ratio (default 10x).
            10x covers most legitimate BTC halving pumps; larger moves are likely bad data.
        source_divergence_pct: flag same (symbol, date) from 2+ sources where
            prices diverge by more than this pct (default 5%).
        max_date_gap_days: flag symbols with consecutive-day gaps exceeding this
            (default 5 — covers weekend + holiday for TradFi; crypto has no
            legitimate gap so any 1+ day crypto gap is real; pass smaller value
            if you want strict crypto gap detection).

    Returns:
        DataFrame with one row per issue, columns:
          issue_type    ("outlier" | "date_gap" | "source_conflict" | "stale")
          symbol, asset_class, source, trade_date (or NaT),
          details (string), magnitude (numeric, where applicable).
        Empty DataFrame if buffer is clean.

    Examples of issues caught:
        - BTC 2026-07-26 close=99999.0 (10x prior) → outlier, magnitude=10.5
        - SPY missing 2026-07-23 → date_gap, magnitude=1
        - BTC 2026-07-26 close=65000 (CG) vs 60000 (HL), |diff|=7.7% → source_conflict
        - AAPL last_date=2026-06-30 (more than 14d ago) → stale
    """
    issues: list[dict] = []
    today = datetime.now(timezone.utc).date()

    with _conn() as conn:
        # 1) Outliers — close vs previous close, per (symbol, source)
        rows = conn.execute("""
            SELECT symbol, asset_class, source, trade_date, close
            FROM ohlcv_daily
            WHERE close IS NOT NULL AND close > 0
            ORDER BY symbol, source, trade_date
        """).fetchall()
        prev: dict[tuple, tuple[str, float]] = {}  # (symbol, source) → (prev_date, prev_close)
        for sym, cls, src, d, c in rows:
            key = (sym, src)
            if key in prev:
                pd_, pc = prev[key]
                if pc > 0:
                    ratio = c / pc
                    if ratio > outlier_ratio or ratio < (1.0 / outlier_ratio):
                        issues.append({
                            "issue_type": "outlier",
                            "symbol": sym, "asset_class": cls, "source": src,
                            "trade_date": d,
                            "details": f"close={c:.4g} vs prev_close={pc:.4g} on {pd_} ({ratio:.2f}x)",
                            "magnitude": round(ratio, 4),
                        })
            prev[key] = (d, c)

        # 2) Date gaps — per (symbol, source) gaps > max_date_gap_days
        date_rows = conn.execute("""
            SELECT symbol, asset_class, source, trade_date
            FROM ohlcv_daily
            ORDER BY symbol, source, trade_date
        """).fetchall()
        prev_d: dict[tuple, tuple[str, str]] = {}  # (sym, src) → (prev_date, asset_class)
        for sym, cls, src, d in date_rows:
            key = (sym, src)
            if key in prev_d:
                pd_, _ = prev_d[key]
                gap = (datetime.fromisoformat(d).date() - datetime.fromisoformat(pd_).date()).days
                if gap > max_date_gap_days:
                    issues.append({
                        "issue_type": "date_gap",
                        "symbol": sym, "asset_class": cls, "source": src,
                        "trade_date": pd_,  # the gap STARTS at prev_d
                        "details": f"gap of {gap} days until {d}",
                        "magnitude": gap,
                    })
            prev_d[key] = (d, cls)

        # 3) Source conflicts — same (symbol, date) from 2+ sources, |price diff| > threshold
        conflict_rows = conn.execute("""
            SELECT symbol, asset_class, trade_date,
                   GROUP_CONCAT(source || ':' || printf('%.6f', close), ' | ') AS sources
            FROM ohlcv_daily
            WHERE close IS NOT NULL AND close > 0
            GROUP BY symbol, trade_date
            HAVING COUNT(DISTINCT source) >= 2
        """).fetchall()
        for sym, cls, d, sources_str in conflict_rows:
            # Parse source:close pairs
            pairs = []
            for part in (sources_str or "").split(" | "):
                if ":" not in part:
                    continue
                s, c = part.split(":", 1)
                try:
                    pairs.append((s, float(c)))
                except ValueError:
                    continue
            if len(pairs) < 2:
                continue
            closes = [c for _, c in pairs]
            mean = sum(closes) / len(closes)
            if mean == 0:
                continue
            # Worst pair divergence from mean
            worst = max(abs(c - mean) / mean for c in closes)
            if worst > source_divergence_pct / 100.0:
                issues.append({
                    "issue_type": "source_conflict",
                    "symbol": sym, "asset_class": cls, "source": "MULTI",
                    "trade_date": d,
                    "details": f"max divergence {worst*100:.2f}% across {len(pairs)} sources: {sources_str}",
                    "magnitude": round(worst * 100, 4),  # as pct
                })

        # 4) Stale — per-symbol last_date > 14 days old
        stale_rows = conn.execute("""
            SELECT symbol, asset_class, source, MAX(trade_date) AS last_d
            FROM ohlcv_daily
            GROUP BY symbol, asset_class, source
        """).fetchall()
        for sym, cls, src, last_d in stale_rows:
            if not last_d:
                continue
            age = (today - datetime.fromisoformat(last_d).date()).days
            if age > WARNING_AGE_DAYS:
                issues.append({
                    "issue_type": "stale",
                    "symbol": sym, "asset_class": cls, "source": src,
                    "trade_date": last_d,
                    "details": f"{age} days since last update",
                    "magnitude": age,
                })

    if not issues:
        return pd.DataFrame(columns=[
            "issue_type", "symbol", "asset_class", "source",
            "trade_date", "details", "magnitude",
        ])
    df = pd.DataFrame(issues)
    # Sort: source_conflict first (most actionable), then outlier, gap, stale
    order = {"source_conflict": 0, "outlier": 1, "date_gap": 2, "stale": 3}
    df["_sort"] = df["issue_type"].map(order)
    df = df.sort_values(["_sort", "symbol", "trade_date"]).drop(columns="_sort").reset_index(drop=True)
    return df


def refresh(days: int = 365, only: str | None = None) -> dict:
    """Re-run the local fetcher to top up the buffer.

    Returns a small dict with exit status. Use this from research scripts when
    the buffer is stale (e.g. > 7 days since last refresh).
    """
    env = {"DAYS": str(days)}
    if only:
        env["ONLY"] = only
    proc = subprocess.run(
        ["python3", str(FETCH_SCRIPT)],
        env={**env, **__import__("os").environ},
        capture_output=True,
        text=True,
        timeout=300,
    )
    return {
        "ok": proc.returncode == 0,
        "exit_code": proc.returncode,
        "stdout_tail": proc.stdout[-400:],
        "stderr_tail": proc.stderr[-400:],
    }


if __name__ == "__main__":
    # Smoke test
    print(f"Local DB: {OHLCV_LOCAL_DB}  size: {OHLCV_LOCAL_DB.stat().st_size:,} bytes")
    cov = get_coverage()
    print(f"\nCoverage: {len(cov)} (symbol, source) pairs, {cov['rows'].sum():,} total rows")
    print(f"Asset classes: {sorted(cov['asset_class'].unique())}")
    print(f"Sources: {sorted(cov['source'].unique())}")
    print()
    btc = load_local_daily("BTC")
    spy = load_local_daily("SPY")
    print(f"BTC: {len(btc)} rows, {btc.index.min().date()} → {btc.index.max().date()}")
    print(f"SPY: {len(spy)} rows, {spy.index.min().date()} → {spy.index.max().date()}")
    panel = load_local_panel(["BTC", "ETH", "SPY", "TLT"])
    print(f"\n4-symbol panel: {panel.shape}, {panel.dropna().shape[0]} non-NaN rows")
    print(panel.tail(3))