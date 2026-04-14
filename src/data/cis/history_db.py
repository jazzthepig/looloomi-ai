"""
CIS Historical Data Storage
=========================
SQLite database for storing CIS scores over time.

Author: Seth
"""

import logging
import sqlite3
import json
from datetime import datetime, date
from typing import List, Dict, Any, Optional
import os

_logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), "cis_history.db")


def get_db():
    """Get database connection."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Initialize database schema."""
    conn = get_db()
    cursor = conn.cursor()

    # CIS scores history table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cis_scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            name TEXT NOT NULL,
            asset_class TEXT NOT NULL,
            cis_score REAL NOT NULL,
            grade TEXT NOT NULL,
            signal TEXT NOT NULL,
            f REAL NOT NULL,
            m REAL NOT NULL,
            o REAL NOT NULL,
            s REAL NOT NULL,
            a REAL NOT NULL,
            change_30d REAL,
            percentile INTEGER,
            market_cap REAL,
            volume_24h REAL,
            tvl REAL,
            recorded_at TEXT NOT NULL,
            UNIQUE(symbol, recorded_at)
        )
    """)

    # Create index for faster queries
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_symbol_date
        ON cis_scores(symbol, recorded_at)
    """)

    # Macro regime history
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cis_macro (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            regime TEXT NOT NULL,
            fed_funds REAL,
            treasury_10y REAL,
            vix REAL,
            dxy REAL,
            cpi_yoy REAL,
            recorded_at TEXT NOT NULL,
            UNIQUE(recorded_at)
        )
    """)

    # Backtest results - stores realized returns per grade
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS backtest_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asset TEXT NOT NULL,
            entry_date TEXT NOT NULL,
            exit_date TEXT NOT NULL,
            holding_days INTEGER NOT NULL,
            grade_entry TEXT,
            grade_exit TEXT,
            score_entry REAL,
            score_exit REAL,
            return_pct REAL NOT NULL,
            btc_return_pct REAL,
            alpha_vs_btc REAL,
            data_source TEXT DEFAULT 'binance',
            calculated_at TEXT NOT NULL,
            UNIQUE(asset, entry_date, exit_date)
        )
    """)

    conn.commit()
    conn.close()


def save_cis_snapshot(universe: List[Dict], macro: Dict):
    """Save a CIS snapshot to database."""
    conn = get_db()
    cursor = conn.cursor()

    now = datetime.now().isoformat()

    # Save macro data
    cursor.execute("""
        INSERT OR REPLACE INTO cis_macro
        (regime, fed_funds, treasury_10y, vix, dxy, cpi_yoy, recorded_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        macro.get("regime", "Unknown"),
        macro.get("fed_funds"),
        macro.get("treasury_10y"),
        macro.get("vix"),
        macro.get("dxy"),
        macro.get("cpi_yoy"),
        now
    ))

    # Save asset scores
    for asset in universe:
        cursor.execute("""
            INSERT OR REPLACE INTO cis_scores
            (symbol, name, asset_class, cis_score, grade, signal,
             f, m, o, s, a, change_30d, percentile, market_cap, volume_24h, tvl, recorded_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            asset.get("symbol"),
            asset.get("name"),
            asset.get("asset_class"),
            asset.get("cis_score"),
            asset.get("grade"),
            asset.get("signal"),
            asset.get("f", 0),
            asset.get("m", 0),
            asset.get("o", 0),
            asset.get("s", 0),
            asset.get("a", 0),
            asset.get("change_30d"),
            asset.get("percentile"),
            asset.get("market_cap"),
            asset.get("volume_24h"),
            asset.get("tvl"),
            now
        ))

    conn.commit()
    conn.close()

    return True


def get_cis_history(symbol: str, days: int = 30) -> List[Dict]:
    """Get CIS history for a symbol."""
    conn = get_db()
    cursor = conn.cursor()

    # Get date range
    cutoff = datetime.now()
    # SQLite doesn't have good date subtraction, so we'll query all and filter in Python
    # For now, just get last N records

    cursor.execute("""
        SELECT * FROM cis_scores
        WHERE symbol = ?
        ORDER BY recorded_at DESC
        LIMIT ?
    """, (symbol, days))

    rows = cursor.fetchall()
    conn.close()

    # Reverse to get chronological order
    history = [dict(row) for row in rows]
    history.reverse()

    return history


def get_latest_scores(days: int = 1) -> List[Dict]:
    """Get latest scores for all assets."""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT * FROM cis_scores
        WHERE recorded_at >= datetime('now', '-' || ? || ' days')
        ORDER BY cis_score DESC
    """, (days,))

    rows = cursor.fetchall()
    conn.close()

    return [dict(row) for row in rows]


def get_score_change(symbol: str, days: int = 30) -> Optional[Dict]:
    """Get CIS score change over time period."""
    history = get_cis_history(symbol, days)

    if len(history) < 2:
        return None

    first = history[0]
    last = history[-1]

    return {
        "symbol": symbol,
        "change": last["cis_score"] - first["cis_score"],
        "start_score": first["cis_score"],
        "end_score": last["cis_score"],
        "start_date": first["recorded_at"],
        "end_date": last["recorded_at"],
    }


def save_backtest_result(
    asset: str,
    entry_date: str,
    exit_date: str,
    holding_days: int,
    grade_entry: str,
    grade_exit: str,
    score_entry: float,
    score_exit: float,
    return_pct: float,
    btc_return_pct: float,
    alpha_vs_btc: float,
    data_source: str = "binance"
) -> bool:
    """Save backtest result to database."""
    conn = get_db()
    cursor = conn.cursor()

    now = datetime.now().isoformat()

    try:
        cursor.execute("""
            INSERT OR REPLACE INTO backtest_results
            (asset, entry_date, exit_date, holding_days, grade_entry, grade_exit,
             score_entry, score_exit, return_pct, btc_return_pct, alpha_vs_btc,
             data_source, calculated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            asset, entry_date, exit_date, holding_days,
            grade_entry, grade_exit, score_entry, score_exit,
            return_pct, btc_return_pct, alpha_vs_btc,
            data_source, now
        ))
        conn.commit()
        return True
    except Exception as e:
        _logger.warning(f"[BACKTEST] Save error: {e}")
        return False
    finally:
        conn.close()


def get_backtest_results(limit: int = 100) -> List[Dict]:
    """Get backtest results."""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT * FROM backtest_results
        ORDER BY calculated_at DESC
        LIMIT ?
    """, (limit,))

    rows = cursor.fetchall()
    conn.close()

    return [dict(row) for row in rows]


def get_backtest_summary() -> Dict:
    """Get aggregated backtest results by grade."""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT grade_entry,
               COUNT(*) as count,
               AVG(return_pct) as avg_return,
               AVG(alpha_vs_btc) as avg_alpha,
               MIN(return_pct) as min_return,
               MAX(return_pct) as max_return
        FROM backtest_results
        GROUP BY grade_entry
        ORDER BY avg_return DESC
    """)

    rows = cursor.fetchall()
    conn.close()

    return {
        "grades": [dict(row) for row in rows],
        "summary_generated_at": datetime.now().isoformat()
    }


# Initialize on import
init_db()
