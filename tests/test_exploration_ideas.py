"""T-074 / S-522:探索仓入口 —— 没有因果假设不收;窗口取值受限;提交日是 UTC。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.exploration.ideas import validate  # noqa: E402


def test_requires_asset_and_a_real_thesis() -> None:
    row, probs = validate({"asset": "TRUMP", "thesis": "短"})
    assert row is None and any("thesis" in p for p in probs)
    row, probs = validate({"thesis": "链上早期介入,上所后动量转负即退出"})
    assert row is None and any("asset" in p for p in probs)


def test_valid_idea_is_stamped_utc_and_open() -> None:
    row, probs = validate({"asset": "TRUMP", "thesis": "链上早期介入;上所后短周期动量转负即退出并做空",
                           "chain": "solana", "horizon": "days"})
    assert probs == [] and row["status"] == "open" and row["submitted_at"].endswith("+00:00")
    assert row["d"] == row["submitted_at"][:10]


def test_horizon_is_bounded() -> None:
    _, probs = validate({"asset": "X", "thesis": "一个足够长的因果假设句子", "horizon": "forever"})
    assert any("horizon" in p for p in probs)


def test_ideas_are_part_of_the_daily_anchor() -> None:
    from src.data.accounting.anchor import SOURCES
    assert any(t == "exploration_ideas" for t, _, _ in SOURCES), "提交当天就要被锚定 —— 先于结果"
