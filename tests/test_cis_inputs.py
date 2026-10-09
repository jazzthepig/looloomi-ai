"""T-079 / S-531:CIS 统一标准缺的维度 —— 时点与口径(恐惧贪婪按日期、CG 采样点 = 前一天收盘、EODHD 复权、TVL 今天不收)。"""
from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.api.routers.ohlcv import eodhd_adjusted_rows  # noqa: E402
from src.data.market.cis_inputs import eod_rows, fng_rows, global_rows, tvl_rows  # noqa: E402
from src.data.style.header import parse_market_chart  # noqa: E402


def _ts(y, m, d, h=0) -> int:
    return int(datetime(y, m, d, h, tzinfo=timezone.utc).timestamp())


def test_fng_rows_date_from_timestamp_and_skip_unreadable() -> None:
    data = [{"value": "59", "timestamp": str(_ts(2026, 10, 9))}, {"value": "x", "timestamp": str(_ts(2026, 10, 8))},
            {"value": "40", "timestamp": "bad"}, {"value": "30", "timestamp": str(_ts(2020, 1, 1))}]
    rows = fng_rows(data)
    assert rows == [{"series": "fng", "d": "2026-10-09", "value": 59.0, "source": "alternative.me"}]


def test_eod_rows_prefers_adjusted_close() -> None:
    rows = eod_rows("vix", [{"date": "2026-10-08", "close": 20.0, "adjusted_close": 19.5},
                            {"date": "2026-10-07", "close": 18.0}, {"date": "2026-10-06", "close": None}])
    assert [(r["d"], r["value"]) for r in rows] == [("2026-10-08", 19.5), ("2026-10-07", 18.0)]


def test_global_rows_only_day_boundary_and_previous_day() -> None:
    ms = lambda *a: _ts(*a) * 1000  # noqa: E731
    gm = {"market_cap": [[ms(2026, 10, 9), 3.0e12], [ms(2026, 10, 9, 13), 3.1e12]], "volume": [[ms(2026, 10, 9), 1.0e11]]}
    rows = global_rows(gm)
    assert {(r["series"], r["d"], r["value"]) for r in rows} == {("total_mcap", "2026-10-08", 3.0e12),
                                                                 ("total_volume", "2026-10-08", 1.0e11)}


def test_tvl_rows_drop_today_placeholder() -> None:
    pts = [[_ts(2026, 10, 7), 1.0e9], [_ts(2026, 10, 8), 1.1e9], [_ts(2026, 10, 9), 1.1e9]]
    rows = tvl_rows("AAVE", "aave", "aave", pts, date(2026, 10, 9))
    assert [r["d"] for r in rows] == ["2026-10-07", "2026-10-08"]


def test_eodhd_adjusted_rows_scale_ohlc_by_adjustment() -> None:
    rows = eodhd_adjusted_rows([{"date": "2024-06-07", "open": 1200, "high": 1250, "low": 1190, "close": 1208,
                                 "adjusted_close": 120.8, "volume": 10},
                                {"date": "2024-06-10", "open": 120, "high": 123, "low": 117, "close": 121.8,
                                 "adjusted_close": 121.8, "volume": 100},
                                {"date": "bad", "close": None}])
    assert len(rows) == 2
    assert abs(rows[0]["close"] - 120.8) < 1e-9 and abs(rows[0]["open"] - 120.0) < 1e-9, "拆股前按系数缩放,不出假跌"
    assert rows[1]["close"] == 121.8 and rows[0]["volume"] == 10


def test_parse_market_chart_volume_only_when_given() -> None:
    ms = lambda *a: _ts(*a) * 1000  # noqa: E731
    p = [[ms(2026, 10, 9), 2.0]]
    assert "volume" not in parse_market_chart(p, [[ms(2026, 10, 9), 5.0]])[0], "没给成交额就不带这个键(另一张表没有这一列)"
    r = parse_market_chart(p, [[ms(2026, 10, 9), 5.0]], [[ms(2026, 10, 9), 7.0]])[0]
    assert r == {"d": "2026-10-08", "price": 2.0, "mcap": 5.0, "volume": 7.0}
