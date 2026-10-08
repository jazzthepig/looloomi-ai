"""S-526 / T-076:链景气读数 —— 选链、按 UTC 日取点、今天的占位点不收、缺的不补 0、增量只写近几天。"""
from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.market.chain_activity import by_day, merge_rows, pick_chains  # noqa: E402


def _ts(y: int, m: int, d: int, h: int = 0) -> int:
    return int(datetime(y, m, d, h, tzinfo=timezone.utc).timestamp())


def test_pick_chains_needs_gecko_id_and_tvl() -> None:
    chains = [{"name": "B", "gecko_id": "b", "tvl": 2e7}, {"name": "A", "gecko_id": "a", "tvl": 5e9},
              {"name": "Base", "gecko_id": None, "tvl": 6e9}, {"name": "C", "gecko_id": "c", "tvl": 9e6},
              {"name": "D", "gecko_id": "d", "tvl": "bad"}]
    assert [c["name"] for c in pick_chains(chains)] == ["A", "B"]


def test_by_day_utc_last_point_drops_today_and_unreadable() -> None:
    today = date(2026, 10, 8)
    pts = [[_ts(2026, 10, 6, 1), 1.0], [_ts(2026, 10, 6, 23), 2.0], [_ts(2026, 10, 7), None],
           [_ts(2026, 10, 7), "x"], [_ts(2026, 10, 8), 99.0], ["bad", 5.0], [7]]
    assert by_day(pts, today) == {"2026-10-06": 2.0}, "今天(UTC)的占位点不收;读不出的值不收"


def test_merge_rows_union_of_days_no_fake_zero_and_since() -> None:
    c = {"name": "Starknet", "gecko_id": "starknet", "tokenSymbol": "STRK"}
    rows = merge_rows(c, {"2026-09-01": 1.0, "2026-09-02": 2.0}, {"2026-09-02": 3.0}, {"2026-09-03": 4.0})
    assert [r["d"] for r in rows] == ["2026-09-01", "2026-09-02", "2026-09-03"]
    assert rows[0]["fees_usd"] is None and rows[0]["dex_volume_usd"] is None, "没有的数据为空,不补 0"
    assert rows[2]["tvl_usd"] is None and rows[2]["dex_volume_usd"] == 4.0
    assert all(r["chain"] == "Starknet" and r["gecko_id"] == "starknet" and r["symbol"] == "STRK" for r in rows)
    assert [r["d"] for r in merge_rows(c, {"2026-09-01": 1.0, "2026-09-02": 2.0}, {}, {}, since="2026-09-02")] == ["2026-09-02"]
