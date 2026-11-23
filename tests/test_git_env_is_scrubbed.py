"""S-903:测试进程里不许带着会把 git 指到别处的环境变量。

2026-11-23:`GIT_DIR=<主仓库>/.git GIT_WORK_TREE=<草稿目录>` 下跑 `tests/test_deploy_paths.py`,临时目录里的
`git init / config / add -A / commit` 全打在真仓库上(本地 main 多了一个 99 个文件的提交,`.git/config` 被改)。
这里钉三件事:危险是真的(变量在时 cwd 不起作用)、清理之后靶子回到临时目录、起临时仓库的测试文件都清了。
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests._git_env import REDIRECTING, scrub_git_env  # noqa: E402


def _git_dir(cwd: Path, env: dict) -> str:
    r = subprocess.run(["git", "rev-parse", "--absolute-git-dir"], cwd=cwd, env=env, capture_output=True, text=True)
    return r.stdout.strip()


def test_the_hazard_is_real_and_the_scrub_removes_it(tmp_path) -> None:
    decoy, work = tmp_path / "decoy", tmp_path / "work"
    decoy.mkdir()
    work.mkdir()
    clean = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    for d in (decoy, work):
        assert subprocess.run(["git", "init", "-q"], cwd=d, env=clean).returncode == 0
    dirty = dict(clean, GIT_DIR=str(decoy / ".git"), GIT_WORK_TREE=str(decoy))
    assert Path(_git_dir(work, dirty)) == (decoy / ".git").resolve(), \
        "前提:带着 GIT_DIR 时,在别的目录里跑的 git 打在 GIT_DIR 指的仓库上(cwd 不起作用)"
    gone = scrub_git_env(dirty)
    assert set(gone) == {"GIT_DIR", "GIT_WORK_TREE"}
    assert Path(_git_dir(work, dirty)) == (work / ".git").resolve(), "清理之后回到 cwd 所在的仓库"
    assert scrub_git_env(dirty) == [], "再清一次没有东西可清"


def test_scrub_keeps_variables_that_only_reduce_writes() -> None:
    env = {"GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0", "GIT_AUTHOR_DATE": "x", "GIT_INDEX_FILE": "/tmp/i",
           "GIT_COMMON_DIR": "/x", "PATH": "/bin"}
    assert sorted(scrub_git_env(env)) == ["GIT_COMMON_DIR", "GIT_INDEX_FILE"]
    assert env == {"GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0", "GIT_AUTHOR_DATE": "x", "PATH": "/bin"}
    assert {"GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"} <= set(REDIRECTING)


def test_this_process_is_already_clean() -> None:
    """pytest 走 conftest;`python3 -m tests.x` 不走 —— 所以起临时仓库的文件自己还要清(下一条)。"""
    conf = (ROOT / "tests/conftest.py").read_text(encoding="utf-8")
    assert "scrub_git_env()" in conf
    if "pytest" in sys.modules:
        assert not [k for k in REDIRECTING if k in os.environ], "conftest 没把变量清掉"


#: 测试里「在临时目录起一个仓库」的写法:git 的 init 子命令 —— `_git(x, "init", …)` / `g(x, "init", …)` / `["git", …, "init"`。
#: (只认 `"init"` 会误伤事件流里的 `"subtype": "init"`。)
_STARTS_A_REPO = re.compile(r"""\b_?g(?:it)?\([^)\n]*["']init["']|["']git["'][^\n]*["']init["']""")
_CLEANS = re.compile(r"scrub_git_env\(|startswith\(\s*[\"']GIT_[\"']\s*\)")


def test_every_test_that_starts_a_repo_cleans_the_environment_first() -> None:
    bad = []
    for p in sorted((ROOT / "tests").glob("test_*.py")):
        if p.name == Path(__file__).name:
            continue
        src = p.read_text(encoding="utf-8")
        if _STARTS_A_REPO.search(src) and not _CLEANS.search(src):
            bad.append(p.name)
    found = [p.name for p in sorted((ROOT / "tests").glob("test_*.py")) if _STARTS_A_REPO.search(p.read_text(encoding="utf-8"))]
    assert {"test_deploy_paths.py", "test_seth_bot.py", "test_lane_bot_dispatch.py"} <= set(found), \
        f"探测器认不出已知的三份起仓库的测试(只找到 {found})—— 认不出就等于没查"
    assert not bad, (f"这些测试在临时目录里起 git 仓库,却没有先清掉 GIT_DIR / GIT_WORK_TREE:{bad} —— "
                     "带着这些变量跑,它们的 init / add / commit 会打在真仓库上(S-903)。用 tests/_git_env.scrub_git_env()")


if __name__ == "__main__":
    import tempfile
    print("── S-903 测试进程不带改靶子的 GIT_* 变量 ──")
    with tempfile.TemporaryDirectory() as td:
        test_the_hazard_is_real_and_the_scrub_removes_it(Path(td))
    print("  ✓ test_the_hazard_is_real_and_the_scrub_removes_it")
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn) and name != "test_the_hazard_is_real_and_the_scrub_removes_it":
            fn()
            print(f"  ✓ {name}")
    print("\n✅ passed")
