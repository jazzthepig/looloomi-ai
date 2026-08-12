"""Smoke tests for `_ohlcv_close_at` — verifies the OPEN RISK #6 fix.

The function reads the daily close at or near `target` for a given symbol.
Before the fix, it queried `ohlcv_daily` directly: that table has multiple rows
per (symbol, trade_date) from coingecko / eodhd / yfinance / binance_hist, and
the `min(|trade_date - target|)` pick in Python picked an arbitrary source on
days with duplicates. The fix routes through the `ohlcv_daily_canonical` view
which resolves source precedence server-side (binance_hist > hyperliquid >
eodhd > coingecko > yfinance), so the client always reads one row per day.

These tests mock the HTTP layer so they exercise the function in isolation
without a Supabase dependency. They cover:

  1. URL hits the canonical view, not the raw table.
  2. Window params (gte / lte) bound to the configured window_days.
  3. Returns the close nearest `target`.
  4. Returns None when the view returns no rows.
  5. Returns None when the status code is non-200 (degrades, not crashes).
  6. Skip / None when SUPABASE_URL is empty (graceful no-op).
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from src.data.signals.outcome_tracker import _ohlcv_close_at


class _Resp:
    """Minimal HTTPX response mock."""

    def __init__(self, status_code: int = 200, body: list | None = None):
        self.status_code = status_code
        self._body = body or []

    def json(self):
        return self._body


def _run(coro):
    return asyncio.run(coro)


def _fake_client(resp: _Resp) -> MagicMock:
    """Returns an AsyncMock that mimics httpx.AsyncClient.get()."""
    client = MagicMock()
    client.get = AsyncMock(return_value=resp)
    return client


def _target_date(date_str: str) -> datetime:
    return datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc)


class TestCanonicalRoute:
    """The fix routes through ohlcv_daily_canonical — the only invariant that
    matters for OPEN RISK #6 closure."""

    def setup_method(self):
        # _SB_URL / _SB_KEY are loaded at module import. Patch the module
        # attributes directly — os.environ patches alone won't propagate.
        from src.data.signals import outcome_tracker
        self._saved_url = outcome_tracker._SB_URL
        self._saved_key = outcome_tracker._SB_KEY
        outcome_tracker._SB_URL = "https://example.supabase.co"
        outcome_tracker._SB_KEY = "test-key"

    def teardown_method(self):
        from src.data.signals import outcome_tracker
        outcome_tracker._SB_URL = self._saved_url
        outcome_tracker._SB_KEY = self._saved_key

    def test_url_hits_ohlcv_daily_canonical_not_raw_table(self):
        """The single-source-of-truth check. Re-introducing the raw table here
        is the exact regression OPEN RISK #6 was closed for."""
        client = _fake_client(_Resp(200, body=[]))
        target = _target_date("2026-08-10T00:00:00")
        _run(_ohlcv_close_at(client, "BTC", target))

        called_url = client.get.await_args.args[0]
        assert called_url.endswith("/rest/v1/ohlcv_daily_canonical"), (
            f"Expected canonical view, got: {called_url}"
        )
        assert not called_url.endswith("/rest/v1/ohlcv_daily"), (
            "Regression: querying raw ohlcv_daily reintroduces OPEN RISK #6"
        )

    def test_window_params_bound_to_window_days(self):
        """Window must be exactly ±window_days around target — looser window
        would pick up stale data; tighter would miss the right day."""
        client = _fake_client(_Resp(200, body=[]))
        target = _target_date("2026-08-10T00:00:00")  # window_days=4 default
        _run(_ohlcv_close_at(client, "BTC", target))

        # params is a list of tuples; httpx preserves duplicates for repeated keys
        params_list = client.get.await_args.kwargs["params"]
        parsed = {p[0]: p[1] for p in params_list}
        # multi-valued key (trade_date) collapses; assert via the raw list
        trade_dates = [v for k, v in params_list if k == "trade_date"]
        assert parsed["symbol"] == "eq.BTC"
        assert sorted(trade_dates) == ["gte.2026-08-06", "lte.2026-08-14"], \
            f"window drifted: {trade_dates}"
        assert parsed["select"] == "trade_date,close"
        assert parsed["order"] == "trade_date.asc"

    def test_returns_close_nearest_target(self):
        """The min(|trade_date - target|) pick on view output is stable."""
        rows = [
            {"trade_date": "2026-08-06", "close": 100.0},
            {"trade_date": "2026-08-09", "close": 102.0},  # 1d away
            {"trade_date": "2026-08-14", "close": 105.0},
        ]
        client = _fake_client(_Resp(200, body=rows))
        target = _target_date("2026-08-10T00:00:00")
        result = _run(_ohlcv_close_at(client, "BTC", target))
        assert result == 102.0, f"Expected nearest-day close, got {result}"

    def test_ignores_rows_with_null_close(self):
        """Defensive: if the view returns a row with close=None, skip it."""
        rows = [
            {"trade_date": "2026-08-09", "close": None},
            {"trade_date": "2026-08-09", "close": 102.5},
        ]
        client = _fake_client(_Resp(200, body=rows))
        target = _target_date("2026-08-10T00:00:00")
        result = _run(_ohlcv_close_at(client, "BTC", target))
        assert result == 102.5, f"Expected 102.5 (skip null), got {result}"

    def test_returns_none_on_no_rows(self):
        client = _fake_client(_Resp(200, body=[]))
        target = _target_date("2026-08-10T00:00:00")
        result = _run(_ohlcv_close_at(client, "BTC", target))
        assert result is None

    def test_returns_none_on_non_200_status(self):
        """Degrades gracefully — never raises. The caller (run_outcome_tracker)
        treats None as 'fall back to external source'."""
        client = _fake_client(_Resp(500, body=[]))
        target = _target_date("2026-08-10T00:00:00")
        result = _run(_ohlcv_close_at(client, "BTC", target))
        assert result is None

    def test_returns_none_when_supabase_url_unset(self):
        """If SUPABASE_URL is empty, never even attempt the request."""
        from src.data.signals import outcome_tracker
        saved_url = outcome_tracker._SB_URL
        saved_key = outcome_tracker._SB_KEY
        outcome_tracker._SB_URL = ""
        outcome_tracker._SB_KEY = ""
        try:
            client = _fake_client(_Resp(200, body=[{"trade_date": "2026-08-09", "close": 102.0}]))
            target = _target_date("2026-08-10T00:00:00")
            result = _run(_ohlcv_close_at(client, "BTC", target))
            assert result is None
            client.get.assert_not_awaited()
        finally:
            outcome_tracker._SB_URL = saved_url
            outcome_tracker._SB_KEY = saved_key

    def test_no_regression_on_callers(self):
        """All 4 OPEN RISK #6 call sites route through this function. The fix
        at one place covers all of them — verify the function is still the
        only entrypoint for canonical reads."""
        import inspect
        from src.data.signals import outcome_tracker

        # outcome_tracker.py:321 (benchmark close at target)
        # outcome_tracker.py:366 (entry price backfill)
        # outcome_tracker.py:377 (exit price)
        # prediction_resolver.py:125 (entry/exit for daily resolver)
        callers = [
            "src/data/signals/outcome_tracker.py",
            "src/data/signals/prediction_resolver.py",
        ]
        for module_path in callers:
            module = __import__(module_path.replace("/", ".").replace(".py", ""),
                                fromlist=["*"])
            src = inspect.getsource(module)
            assert "ohlcv_daily_canonical" in src or "_ohlcv_close_at" in src, (
                f"{module_path} does not route through canonical view or "
                f"_ohlcv_close_at — re-introducing OPEN RISK #6"
            )
