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


def test_executor_checks_the_main_dir_before_any_job() -> None:
    """10-08:lane 在主目录切了分支又 stash —— 执行器必须先看 HEAD 在不在 main,再看有没有新 stash。"""
    src = BOT.read_text(encoding="utf-8")
    assert "def main_dir_guard" in src
    assert "if main_dir_guard() else []" in src, "HEAD 不在 main 时一个任务都不能执行"
    assert "refs/stash" in src and "git stash apply" in src, "新 stash 要留下恢复指令"


def test_merge_fixup_paths_are_validated_like_commit_paths() -> None:
    """10-08:lane 的新测试要注册进 preflight,注册行随合并进同一个提交;fixup 路径同样过禁区检查。"""
    sys.path.insert(0, str(ROOT / "scripts" / "seth_bot"))
    import seth_bot as sb
    r = sb.do_merge({"id": "t", "branch": "lane-c/T-071", "fixup_paths": [".env"]})
    assert r["ok"] is False and r["stage"] == "validate"
    r = sb.do_merge({"id": "t", "branch": "lane-c/T-071", "fixup_paths": ["scripts/no_such_file.sh"]})
    assert r["ok"] is False and r["detail"]["missing"] == ["scripts/no_such_file.sh"]
