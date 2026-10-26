"""行情新鲜度的年龄从日线**收盘**算(trade_date + 1 天),不是从开盘算(2026-10-26 用户报告)。

从开盘算时,一个完全最新的行情源在每个 UTC 下午都会「超过 36 小时」,β 调整层的闸门天天下午关上,
报告里读成「行情 39.8 小时没更新」—— 那时 10-24 的日线才收盘 15.8 小时。
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.api.store import _OHLCV_FRESH_OPEN_S, ohlcv_bar_age_seconds  # noqa: E402


def test_age_counts_from_the_bar_close_so_a_current_feed_is_fresh_all_day():
    afternoon = datetime(2026, 10, 25, 15, 48, tzinfo=timezone.utc)
    age = ohlcv_bar_age_seconds("2026-10-24", afternoon)
    assert abs(age - 15.8 * 3600) < 1, "10-24 的日线 10-25 00:00 收盘,到 15:48 是 15.8 小时"
    assert age < _OHLCV_FRESH_OPEN_S
    late = datetime(2026, 10, 25, 23, 59, tzinfo=timezone.utc)
    assert ohlcv_bar_age_seconds("2026-10-24", late) < _OHLCV_FRESH_OPEN_S, "整个 UTC 日都应判新鲜"


def test_a_missed_day_still_trips_the_gate():
    now = datetime(2026, 10, 26, 13, 0, tzinfo=timezone.utc)
    assert ohlcv_bar_age_seconds("2026-10-24", now) > _OHLCV_FRESH_OPEN_S, "10-25 那根没写进来 ⇒ 37 小时 ⇒ 关"


def test_a_forming_bar_reports_zero_not_negative():
    now = datetime(2026, 10, 26, 3, 0, tzinfo=timezone.utc)
    assert ohlcv_bar_age_seconds("2026-10-26", now) == 0.0
