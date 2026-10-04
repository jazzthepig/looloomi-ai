"""T-049:日线时间戳语义一处定义。每个来源钉一个已知例子;src/ 里不许别处再自己「减一天」。"""
import re
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from src.data.market.bar_semantics import STAMP, covered_day, is_day_boundary

ROOT = Path(__file__).resolve().parents[1]


def _ms(y, m, d, h=0):
    return int(datetime(y, m, d, h, tzinfo=timezone.utc).timestamp() * 1000)


def test_coingecko_candle_stamped_at_close_covers_the_previous_day():
    # S-436:CG 日 K 在 D+1 00:00 打戳;10-03 00:00 的那根是 10-02 的 K 线
    assert covered_day("coingecko_ohlc_range", _ms(2026, 10, 3)) == date(2026, 10, 2)


def test_market_chart_midnight_point_is_the_previous_close():
    assert covered_day("coingecko_market_chart", _ms(2026, 1, 1)) == date(2025, 12, 31)
    assert covered_day("coingecko_global_chart", _ms(2026, 3, 1)) == date(2026, 2, 28)


def test_binance_kline_stamped_at_open_covers_that_day():
    assert covered_day("binance_klines", _ms(2026, 10, 2)) == date(2026, 10, 2)


def test_unregistered_source_refuses_to_guess():
    with pytest.raises(KeyError):
        covered_day("some_new_venue", _ms(2026, 10, 2))


def test_day_boundary_tolerance_is_forward_only():
    assert is_day_boundary(_ms(2026, 10, 2)) and not is_day_boundary(_ms(2026, 10, 2) + 1)
    assert is_day_boundary(_ms(2026, 10, 2) + 3_000_000, tolerance_ms=3_600_000)
    assert not is_day_boundary(_ms(2026, 10, 2) - 1, tolerance_ms=3_600_000)


def test_every_registered_source_is_open_or_close():
    assert set(STAMP.values()) <= {"open", "close"}


def test_no_other_writer_shifts_a_timestamp_by_a_day_on_its_own():
    """S-436 / S-459 的形状:fromtimestamp(...) 之后紧跟「− 1 天」。只许出现在 bar_semantics 里。"""
    pat = re.compile(r"fromtimestamp\([^\n]*\)\s*\n?\s*-\s*timedelta\(days=1\)")
    hits = []
    for p in (ROOT / "src").rglob("*.py"):
        if p.name == "bar_semantics.py" or "/research/" in str(p):
            continue
        if pat.search(p.read_text(encoding="utf-8", errors="ignore")):
            hits.append(str(p.relative_to(ROOT)))
    assert hits == [], f"这些文件自己减了一天,改用 bar_semantics.covered_day:{hits}"
