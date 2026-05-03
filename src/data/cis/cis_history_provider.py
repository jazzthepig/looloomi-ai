"""
CIS Historical Score Provider
==============================
Serves CIS scores for any (symbol, datetime) pair from the Supabase time-series.
Used by Freqtrade strategies to gate entries with historical CIS data.

Key functions:
    get_cis_at(symbol, dt)        — nearest CIS score at/before a given datetime
    get_cis_window(symbol, dt, n) — last N CIS scores before dt (for velocity signals)
    get_cis_dataframe(symbol)     — pandas DataFrame of full history (for vectorised backtest)
    get_pillar_at(symbol, dt)     — full 5-pillar vector at a given datetime

Usage in Freqtrade strategy:
    from src.data.cis.cis_history_provider import CISHistoryProvider
    provider = CISHistoryProvider()
    score = provider.get_cis_at("BTC", datetime(2024, 6, 15))

Author: Seth
"""

import os
import logging
from datetime import datetime, timezone
from typing import Optional
import httpx

_log = logging.getLogger(__name__)

# ── Config ─────────────────────────────────────────────────────────────────────

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv(
    "SUPABASE_SERVICE_KEY",
    os.getenv("SUPABASE_KEY", os.getenv("SUPABASE_ANON_KEY", "")),
)

# Fallback: Railway public API (no Supabase creds needed, but slower)
RAILWAY_BASE = os.getenv("COMETCLOUD_API_BASE", "https://looloomi.ai")


class CISHistoryProvider:
    """
    Provides historical CIS scores for Freqtrade strategy integration.

    Instantiate once at strategy load; it caches fetched data in memory
    to avoid repeated Supabase queries during backtesting.
    """

    def __init__(self, use_railway_fallback: bool = True):
        self._cache: dict[str, list[dict]] = {}  # symbol → sorted list of rows
        self._use_railway = use_railway_fallback
        self._loaded: set[str] = set()

    # ── Public API ─────────────────────────────────────────────────────────────

    def get_cis_at(
        self,
        symbol: str,
        dt: datetime,
        max_age_hours: int = 26,
    ) -> Optional[float]:
        """
        Return the CIS score at or immediately before `dt`.
        `max_age_hours`: if the nearest score is older than this, return None
        (stale data is worse than no data in a trading context).
        """
        rows = self._get_rows(symbol)
        row  = self._nearest_row_before(rows, dt, max_age_hours)
        return row["score"] if row else None

    def get_grade_at(self, symbol: str, dt: datetime) -> Optional[str]:
        rows = self._get_rows(symbol)
        row  = self._nearest_row_before(rows, dt)
        return row["grade"] if row else None

    def get_signal_at(self, symbol: str, dt: datetime) -> Optional[str]:
        rows = self._get_rows(symbol)
        row  = self._nearest_row_before(rows, dt)
        return row["signal"] if row else None

    def get_pillar_at(self, symbol: str, dt: datetime) -> Optional[dict]:
        """Returns {F, M, O, S, A, regime} or None."""
        rows = self._get_rows(symbol)
        row  = self._nearest_row_before(rows, dt)
        if not row:
            return None
        return {
            "F":      row.get("pillar_f"),
            "M":      row.get("pillar_m"),
            "O":      row.get("pillar_o"),
            "S":      row.get("pillar_s"),
            "A":      row.get("pillar_a"),
            "regime": row.get("macro_regime"),
            "data_tier": row.get("data_tier"),
        }

    def get_cis_window(
        self,
        symbol: str,
        dt: datetime,
        n: int = 10,
    ) -> list[float]:
        """
        Returns the last `n` CIS scores before `dt`, oldest first.
        Useful for computing velocity: scores[-1] - scores[0]
        """
        rows  = self._get_rows(symbol)
        dt_ts = dt.timestamp()
        before = [r for r in rows if _parse_ts(r["recorded_at"]).timestamp() <= dt_ts]
        window = before[-n:]
        return [r["score"] for r in window if r.get("score") is not None]

    def get_score_velocity(self, symbol: str, dt: datetime, window: int = 7) -> Optional[float]:
        """
        Score delta over last `window` observations before `dt`.
        Positive = accelerating upward. Negative = deteriorating.
        Returns None if insufficient data.
        """
        scores = self.get_cis_window(symbol, dt, window + 1)
        if len(scores) < 2:
            return None
        return round(scores[-1] - scores[0], 2)

    def get_cis_dataframe(self, symbol: str):
        """
        Returns a pandas DataFrame with columns:
            recorded_at, score, grade, signal, pillar_f..a, macro_regime, score_delta, score_zscore
        Sorted by recorded_at ASC. Suitable for vectorised backtest analysis.
        """
        try:
            import pandas as pd
        except ImportError:
            raise ImportError("pandas required: pip install pandas")

        rows = self._get_rows(symbol)
        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        df["recorded_at"] = pd.to_datetime(df["recorded_at"], utc=True)
        df = df.sort_values("recorded_at").reset_index(drop=True)
        return df

    def get_regime_at(self, symbol: str, dt: datetime) -> str:
        """Returns macro regime at the given datetime, or 'UNKNOWN'."""
        rows = self._get_rows(symbol)
        row  = self._nearest_row_before(rows, dt)
        return row.get("macro_regime", "UNKNOWN") if row else "UNKNOWN"

    def passes_cis_gate(
        self,
        symbol: str,
        dt: datetime,
        min_score: float,
        regime_thresholds: Optional[dict] = None,
    ) -> bool:
        """
        Returns True if the asset passes the CIS entry gate at datetime `dt`.

        regime_thresholds overrides min_score per regime:
            {
                "TIGHTENING": 52,
                "RISK_OFF":   60,
                "GOLDILOCKS": 45,
                ...
            }
        If no regime match, falls back to min_score.
        """
        score = self.get_cis_at(symbol, dt)
        if score is None:
            return False  # No data = no entry

        if regime_thresholds:
            regime    = self.get_regime_at(symbol, dt)
            threshold = regime_thresholds.get(regime, min_score)
        else:
            threshold = min_score

        return score >= threshold

    # ── Data loading ──────────────────────────────────────────────────────────

    def _get_rows(self, symbol: str) -> list[dict]:
        """Lazy-load and cache rows for a symbol."""
        s = symbol.upper()
        if s not in self._loaded:
            rows = self._load_from_supabase(s)
            if not rows and self._use_railway:
                rows = self._load_from_railway(s)
            self._cache[s] = sorted(rows, key=lambda r: r["recorded_at"])
            self._loaded.add(s)
        return self._cache.get(s, [])

    def _load_from_supabase(self, symbol: str) -> list[dict]:
        if not SUPABASE_URL or not SUPABASE_KEY:
            return []
        try:
            with httpx.Client(timeout=30) as client:
                r = client.get(
                    f"{SUPABASE_URL}/rest/v1/cis_scores",
                    params={
                        "select": "recorded_at,score,grade,signal,pillar_f,pillar_m,pillar_o,pillar_s,pillar_a,macro_regime,data_tier,score_delta,score_zscore",
                        "symbol": f"eq.{symbol}",
                        "order":  "recorded_at.asc",
                        "limit":  "10000",
                    },
                    headers={
                        "apikey":        SUPABASE_KEY,
                        "Authorization": f"Bearer {SUPABASE_KEY}",
                    },
                )
            if r.status_code == 200:
                rows = r.json()
                _log.info(f"[CISHistory] Loaded {len(rows)} rows for {symbol} from Supabase")
                return rows
            _log.warning(f"[CISHistory] Supabase {symbol}: {r.status_code}")
        except Exception as e:
            _log.warning(f"[CISHistory] Supabase error for {symbol}: {e}")
        return []

    def _load_from_railway(self, symbol: str) -> list[dict]:
        """Fallback: Railway CIS history endpoint (last 30 days only)."""
        try:
            with httpx.Client(timeout=20) as client:
                r = client.get(f"{RAILWAY_BASE}/api/v1/cis/history/{symbol}", params={"days": 30})
            if r.status_code == 200:
                data  = r.json()
                rows  = data.get("history", data.get("rows", []))
                # Normalise field names (Railway uses `score`, Supabase uses `score`)
                normed = []
                for row in rows:
                    normed.append({
                        "recorded_at": row.get("recorded_at", row.get("timestamp", "")),
                        "score":       row.get("score", row.get("cis_score")),
                        "grade":       row.get("grade"),
                        "signal":      row.get("signal"),
                        "pillar_f":    row.get("pillar_f", row.get("f")),
                        "pillar_m":    row.get("pillar_m", row.get("m")),
                        "pillar_o":    row.get("pillar_o", row.get("o")),
                        "pillar_s":    row.get("pillar_s", row.get("s")),
                        "pillar_a":    row.get("pillar_a", row.get("a")),
                        "macro_regime": row.get("macro_regime"),
                        "data_tier":   row.get("data_tier", "T2"),
                    })
                _log.info(f"[CISHistory] Loaded {len(normed)} rows for {symbol} from Railway")
                return normed
        except Exception as e:
            _log.warning(f"[CISHistory] Railway fallback error for {symbol}: {e}")
        return []

    # ── Helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _nearest_row_before(
        rows: list[dict],
        dt: datetime,
        max_age_hours: int = 48,
    ) -> Optional[dict]:
        if not rows:
            return None
        dt_ts    = dt.timestamp()
        max_age_s = max_age_hours * 3600
        candidates = [
            r for r in rows
            if _parse_ts(r["recorded_at"]).timestamp() <= dt_ts
            and dt_ts - _parse_ts(r["recorded_at"]).timestamp() <= max_age_s
        ]
        return candidates[-1] if candidates else None


def _parse_ts(ts_str: str) -> datetime:
    """Parse ISO 8601 timestamp, always returns timezone-aware datetime."""
    if not ts_str:
        return datetime.fromtimestamp(0, tz=timezone.utc)
    try:
        if ts_str.endswith("Z"):
            ts_str = ts_str[:-1] + "+00:00"
        dt = datetime.fromisoformat(ts_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return datetime.fromtimestamp(0, tz=timezone.utc)


# ── Module-level singleton (used by Freqtrade strategies) ─────────────────────

_provider: Optional[CISHistoryProvider] = None


def get_provider() -> CISHistoryProvider:
    global _provider
    if _provider is None:
        _provider = CISHistoryProvider()
    return _provider
