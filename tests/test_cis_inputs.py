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


def test_global_rows_recent_takes_first_point_after_midnight() -> None:
    """S-536:days=max 的最后一个整点是昨天的;最近一天从 days=1(5 分钟粒度)取 00:00 后第一个点。"""
    ms = lambda *a: _ts(*a) * 1000  # noqa: E731
    gm = {"market_cap": [[ms(2026, 10, 10, 23) + 55 * 60_000, 2.9e12], [ms(2026, 10, 11) + 3 * 60_000, 3.0e12],
                         [ms(2026, 10, 11) + 8 * 60_000, 3.05e12], [ms(2026, 10, 11, 1), 3.1e12]],
          "volume": [[ms(2026, 10, 11) + 3 * 60_000, 1.0e11]]}
    from src.data.market.cis_inputs import RECENT_TOLERANCE_MS
    rows = global_rows(gm, tolerance_ms=RECENT_TOLERANCE_MS)
    assert {(r["series"], r["d"], r["value"]) for r in rows} == {("total_mcap", "2026-10-10", 3.0e12),
                                                                 ("total_volume", "2026-10-10", 1.0e11)}
    assert global_rows(gm) == [], "没有容差时 00:03 不算收盘"


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


def test_fundamentals_rows_both_shapes_and_availability() -> None:
    from src.data.market.cis_inputs import fundamentals_rows
    nested = {"Earnings": {"History": {"2024-06-30": {"date": "2024-06-30", "reportDate": "2024-08-01", "epsActual": 1.4},
                                       "2019-12-31": {"date": "2019-12-31", "reportDate": "2020-01-30", "epsActual": 1.0}}},
              "Financials": {"Income_Statement": {"quarterly": {"2024-06-30": {"date": "2024-06-30", "filing_date": "2024-08-02",
                                                                               "totalRevenue": "85777000000"}}}}}
    rows = fundamentals_rows("AAPL", nested)
    assert rows == [{"symbol": "AAPL", "period_end": "2024-06-30", "available_d": "2024-08-01", "eps": 1.4,
                     "revenue": 85777000000.0, "source": "eodhd_fundamentals"}], "可得日 = EPS 公布日;2020 前的不收"
    flat = {"Earnings::History": {"2024-06-30": {"date": "2024-06-30", "reportDate": "2024-08-01", "epsActual": 1.4}},
            "Financials::Income_Statement::quarterly": {}}
    assert fundamentals_rows("AAPL", flat)[0]["revenue"] is None
    assert fundamentals_rows("X", {"Earnings::History": {"2024-06-30": {"date": "2024-06-30", "epsActual": 1}}}) == [], "没有可得日不收"


def test_github_rows_weeks_start_sunday_and_drop_current() -> None:
    from src.data.market.cis_inputs import github_rows
    rows = github_rows("BTC", "bitcoin/bitcoin", [5, 6, 7], date(2026, 10, 14))   # 周三;本周从 10-11(周日)开始
    assert [(r["week_start"], r["commits"]) for r in rows] == [("2026-09-27", 5), ("2026-10-04", 6)], "本周没走完,不收"


def test_sentiment_history_goes_back_to_2018_and_volume_backfill_threshold() -> None:
    """10-16(S-590):恐惧贪婪 / 全市场 / VIX 存全历史(研究要 2018–2021 的牛熊);全量加密成交额回填只在空行超过门槛时重取。"""
    from src.data.market import cis_inputs as ci
    data = [{"value": "30", "timestamp": str(_ts(2020, 1, 1))}, {"value": "59", "timestamp": str(_ts(2026, 10, 9))}]
    assert [r["d"] for r in fng_rows(data, ci.MACRO_HISTORY_START)] == ["2020-01-01", "2026-10-09"]
    assert ci.MACRO_HISTORY_START <= "2018-02-01"
    src = (ROOT / "src/data/market/cis_inputs.py").read_text(encoding="utf-8")
    assert "fng_rows(raw, MACRO_HISTORY_START)" in src and "global_rows(raw, MACRO_HISTORY_START)" in src
    assert not ci.needs_volume_history(5) and ci.needs_volume_history(31)
    from src.data.market.binance_hf_collector import FUNDING_BACKFILL_START_MS
    assert FUNDING_BACKFILL_START_MS <= int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)


def test_volume_history_also_covers_past_leaders_not_only_todays_members():
    """10-19:当前分类成员之外的历史大名字(AXS / FTT / NEO …)2020–2024 的成交额全空,S-595 的前 50 覆盖只有中位 35 名。"""
    from src.data.market import cis_inputs as ci
    q = ci.quarter_ends("2019-06-01", "2020-06-30")
    assert q == ["2019-06-30", "2019-09-30", "2019-12-31", "2020-03-31", "2020-06-30"]
    rows = [{"d": "2020-03-31", "symbol": "FTT", "coin_id": "ftx-token", "mcap": 5e8},
            {"d": "2020-03-31", "symbol": "ETH", "coin_id": "ethereum", "mcap": 1.5e10},
            {"d": "2020-03-31", "symbol": "TINY", "coin_id": "tiny", "mcap": 1e3},
            {"d": "2020-06-30", "symbol": "ETH", "coin_id": "ethereum", "mcap": 2.6e10},
            {"d": "2020-06-30", "symbol": "NOMC", "coin_id": "nomc", "mcap": None}]
    assert ci.top_pairs(rows, 2) == [{"symbol": "ETH", "coin_id": "ethereum"}, {"symbol": "FTT", "coin_id": "ftx-token"}]


def test_global_recent_zero_rows_before_the_publish_deadline_is_pending_not_error():
    """10-29:每天 00:52 的那一轮,CG `days=1` 还没有 00:00 的点(10-28 / 10-29 两天都是,13:00 就有了)
    —— 循环被记成 error,而正式发布器每小时自己补(S-538)。截止钟点前 = 等待;过了截止还没有 = 错;昨天已有 = 没事做。"""
    from src.data.market.cis_inputs import RECENT_PENDING_UNTIL_HOUR, global_recent_status
    from src.data.cis.official import PUBLISH_DEADLINE_HOUR
    assert RECENT_PENDING_UNTIL_HOUR == PUBLISH_DEADLINE_HOUR
    today = date(2026, 10, 29)
    assert global_recent_status([], set(), today, 0) is None
    assert global_recent_status([], set(), today, 5) is None
    assert global_recent_status([], set(), today, 7) == "global_recent: 0 行"
    assert global_recent_status([], {("total_mcap", "2026-10-28")}, today, 12) is None
    assert global_recent_status([{"d": "2026-10-28"}], set(), today, 12) is None
