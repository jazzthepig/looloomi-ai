"""S-500:Mac 侧执行器只做三件事,且路径清单本身先过一道。

执行器替 Jazz 粘贴交接块 —— 它推的是生产(Railway 推送即部署)。这里钉住它**不**做的事:
-A / 绝对路径 / .. / 永不提交清单;只合并 lane 分支;不执行队列里的任意命令。
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.seth_bot.seth_bot import LANE_BRANCH, VERIFY_PATH, path_problems  # noqa: E402

BOT = ROOT / "scripts" / "seth_bot" / "seth_bot.py"


def test_explicit_paths_pass() -> None:
    assert path_problems(["src/api/routers/cis.py", "tests/test_cis_data_source.py", "tasks/T-023.json"]) == []


def test_never_stage_list_and_wildcards_are_refused() -> None:
    for bad in (["-A"], ["."], ["/etc/hosts"], ["../x"], ["Shadow/x.py"], [".env"], ["MINIMAX_SYNC.md"],
                ["docs/reading/notes.md"], ["deck.pptx"], ["scripts/lesson_enforcement_baseline.txt"], []):
        assert path_problems(bad), bad


def test_merge_only_takes_lane_branches() -> None:
    assert LANE_BRANCH.match("lane-a/T-003") and LANE_BRANCH.match("lane-b/T-036-internal")
    for bad in ("main", "staging", "claude/x", "lane-d/T-001", "lane-a/T-1"):
        assert not LANE_BRANCH.match(bad), bad


def test_verify_is_a_relative_get_not_a_command() -> None:
    assert VERIFY_PATH.match("/api/v1/proof/books")
    for bad in ("https://evil.example/x", "; rm -rf ~", "$(id)", "/x`id`"):
        assert not VERIFY_PATH.match(bad), bad


def test_no_shell_strings_in_the_executor() -> None:
    tree = ast.parse(BOT.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "shell":
            raise AssertionError("seth_bot 不许 shell=True")
        if isinstance(node, ast.Attribute) and node.attr in ("system", "popen") and \
                isinstance(node.value, ast.Name) and node.value.id == "os":
            raise AssertionError("seth_bot 不许 os.system/os.popen")


if __name__ == "__main__":
    print("── S-500 seth_bot ──")
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ✓ {name}")
    print("\n✅ passed")
