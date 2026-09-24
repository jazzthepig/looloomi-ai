"""S-421 — 任务卡合法,看板最新,「完成」不能自己宣布。

1. 每张卡都有:负责人、允许改的文件、禁止碰的文件、验收查询、之前的值
2. status=done 必须带合并者(seth)验证后的值和时间 —— agent 自己写 done 会被拦下
3. tasks/BOARD.md 必须和卡片一致(看板是生成物,手改会和卡片分开演化)
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.task_board import load_cards, problems  # noqa: E402


def test_cards_are_valid() -> None:
    cards = load_cards()
    assert cards, "tasks/ 里没有任务卡"
    bad = problems(cards)
    assert not bad, "\n".join(bad)
    print(f"  ✓ {len(cards)} 张任务卡字段完整")


def test_done_cannot_be_self_declared() -> None:
    fake = [{"_file": "T-999.json", "id": "T-999", "title": "x", "owner": "lane-a", "status": "done",
             "created": "2026-09-24", "source": "x", "allowed_paths": ["a"], "forbidden_paths": ["b"],
             "acceptance": {"check": "q", "expect": "e"}, "prior_value": "0",
             "verified": {"by": "lane-a", "value": "ok", "at": "2026-09-24"}}]
    bad = problems(fake)
    assert any("不能自己宣布完成" in b for b in bad), bad
    print("  ✓ lane 自己写 done 会被拦下(必须 seth 验证)")


def test_board_is_current() -> None:
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "task_board.py"), "--check"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    print("  " + r.stdout.strip())


if __name__ == "__main__":
    print("── S-421 任务卡 ──")
    test_cards_are_valid()
    test_done_cannot_be_self_declared()
    test_board_is_current()
    print("\n✅ 3/3 passed")
