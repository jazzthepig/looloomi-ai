"""S-513:稳定币借贷池 —— 选池、按日取最后一个点、读不出的不补 0。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.market.stable_lending import chart_rows, pick_pools  # noqa: E402


def test_pick_largest_ethereum_pool_per_project_and_symbol() -> None:
    pools = [
        {"pool": "a", "project": "aave-v3", "chain": "Ethereum", "symbol": "USDC", "tvlUsd": 5e9},
        {"pool": "b", "project": "aave-v3", "chain": "Ethereum", "symbol": "USDC", "tvlUsd": 1e6},
        {"pool": "c", "project": "aave-v3", "chain": "Arbitrum", "symbol": "USDC", "tvlUsd": 9e9},
        {"pool": "d", "project": "aave-v2", "chain": "Ethereum", "symbol": "USDT", "tvlUsd": 2e8},
        {"pool": "e", "project": "compound-v3", "chain": "Ethereum", "symbol": "USDC", "tvlUsd": 9e9},
    ]
    assert [p["pool"] for p in pick_pools(pools)] == ["d", "a"]


def test_chart_rows_one_per_day_last_point_and_no_fake_zero() -> None:
    pool = {"pool": "a", "project": "aave-v3", "chain": "Ethereum", "symbol": "USDC"}
    pts = [{"timestamp": "2024-01-01T01:00:00Z", "tvlUsd": 1, "apyBase": 3.0},
           {"timestamp": "2024-01-01T23:00:00Z", "tvlUsd": 2, "apyBase": 4.0},
           {"timestamp": "2024-01-02T23:00:00Z", "tvlUsd": 3, "apyBase": None},
           {"timestamp": "", "tvlUsd": 9, "apyBase": 9.0}]
    rows = chart_rows(pool, pts)
    assert [r["d"] for r in rows] == ["2024-01-01", "2024-01-02"]
    assert rows[0]["apy_base"] == 4.0 and rows[0]["tvl_usd"] == 2.0, "同一天取最后一个点"
    assert rows[1]["apy_base"] is None, "读不出的 APY 不补 0"
