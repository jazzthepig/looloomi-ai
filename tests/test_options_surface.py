"""期权面(11-06):合约名解析、期限结构 / 偏斜 / 对冲价格、批量请求、接线。"""
from __future__ import annotations

import asyncio
import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.market import options_surface as os_  # noqa: E402

TODAY = dt.date(2026, 11, 6)


def _opt(exp, k, t, iv, px, oi=10.0, F=100_000.0):
    return {"instrument_name": f"BTC-{exp}-{k}-{t}", "underlying_price": F, "mark_iv": iv, "mark_price": px, "open_interest": oi,
            "volume_usd": 1000.0}


def test_parse_name():
    assert os_.parse_name("BTC-27NOV26-68000-P") == (dt.date(2026, 11, 27), 68000.0, "P")
    assert os_.parse_name("BTC-PERPETUAL") is None and os_.parse_name("BTC-27XXX26-1-P") is None


def test_features_term_skew_and_hedge_cost():
    rows = [_opt("13NOV26", 100000, "C", 50, 0.02), _opt("13NOV26", 100000, "P", 52, 0.02),
            _opt("04DEC26", 100000, "C", 44, 0.04), _opt("04DEC26", 100000, "P", 46, 0.04),
            _opt("04DEC26", 90000, "P", 55, 0.009, oi=30), _opt("04DEC26", 80000, "P", 62, 0.002, oi=20),
            _opt("04DEC26", 110000, "C", 42, 0.008),
            _opt("05FEB27", 100000, "C", 40, 0.08), _opt("05FEB27", 100000, "P", 42, 0.08),
            _opt("05NOV26", 100000, "C", 99, 0.0)]                    # 已到期:丢掉
    f = os_.features(rows, TODAY)
    assert f["n_options"] == 9 and f["atm_iv_7d"] == 51 and f["atm_iv_30d"] == 45 and f["atm_iv_90d"] == 41
    assert f["term_slope"] == 10 and f["skew_30d"] == 13, "偏斜 = 90% 看跌 − 110% 看涨"
    assert f["put90_30d_cost_pct"] == 0.9 and f["put_spread_90_80_30d_cost_pct"] == 0.7
    assert os_.features([], TODAY) == {"n_options": 0}


def test_run_once_one_request_per_currency(monkeypatch):
    urls, written = [], []

    def get(u):
        urls.append(u)
        return {"result": [_opt("04DEC26", 100000, "C", 44, 0.04), _opt("04DEC26", 100000, "P", 46, 0.04)]}

    class W:
        def __bool__(self):
            return True

    async def upsert(table, rows, on_conflict=None):
        written.extend(rows)
        return W()

    import src.api.store as store
    monkeypatch.setattr(store, "supabase_upsert_table", upsert)
    r = asyncio.run(os_.run_once(now=dt.datetime(2026, 11, 6, 9, tzinfo=dt.timezone.utc), get=get))
    assert len(urls) == len(os_.CURRENCIES) and r["ok"] and len(written) == 2 and set(written[0]) == set(os_.COLS)


def test_wiring():
    assert "async def _options_surface_loop" in (ROOT / "src/api/main.py").read_text(encoding="utf-8")
    mig = (ROOT / "migrations/2026-11-06_options_surface_daily.sql").read_text(encoding="utf-8")
    assert all(c in mig for c in os_.COLS)
