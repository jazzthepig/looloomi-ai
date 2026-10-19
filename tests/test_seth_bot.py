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


def test_blocking_files_are_parsed_from_git_message() -> None:
    from scripts.seth_bot.seth_bot import blocking_files
    msg = ("error: Your local changes to the following files would be overwritten by merge:\n"
           "\tscripts/preflight.sh\n\tscripts/seth_bot/seth_bot.py\n"
           "Please commit your changes or stash them before you merge.\nAborting")
    assert blocking_files(msg) == ["scripts/preflight.sh", "scripts/seth_bot/seth_bot.py"]


def test_stash_is_main_tells_lane_worktree_stashes_apart() -> None:
    from scripts.seth_bot.seth_bot import stash_is_main
    assert stash_is_main("WIP on main: 4baf02b docs(state): …")
    assert stash_is_main("On main: something")
    assert not stash_is_main("WIP on lane-b/T-059: 686ff9a docs(tasks): …"), "lane 在自己 worktree 的 stash 不是主目录事故"
    assert not stash_is_main("On lane-c/T-036: pre-existing dirty state")



def test_fast_forward_through_an_identical_untracked_fixup_copy() -> None:
    """10-15:合并 T-102 时 fixup 把主目录里的新脚本带进提交;主目录那份成了未跟踪的同内容副本,下一个任务快进被拒。
    同内容 ⇒ 让路快进;内容不同 ⇒ 一个都不动。在临时仓库里验证,不碰真仓库的索引。"""
    import os
    import subprocess as sp
    import tempfile
    from unittest import mock
    import scripts.seth_bot.seth_bot as sb
    clean = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}   # 钩子里跑时 GIT_DIR 会把临时仓库指回真仓库

    def g(cwd, *a):
        return sp.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *a], cwd=cwd, capture_output=True, text=True)

    with tempfile.TemporaryDirectory() as td, mock.patch.dict(os.environ, clean, clear=True):
        origin, main = Path(td) / "o.git", Path(td) / "m"
        g(td, "init", "--bare", "-b", "main", str(origin))
        g(td, "clone", str(origin), str(main))
        (main / "a.txt").write_text("a\n")
        g(main, "add", "a.txt"); g(main, "commit", "-m", "a"); g(main, "push", "origin", "main")
        other = Path(td) / "w"
        g(td, "clone", str(origin), str(other))
        (other / "new.py").write_text("x = 1\n")
        g(other, "add", "new.py"); g(other, "commit", "-m", "n"); g(other, "push", "origin", "main")
        g(main, "fetch", "origin")
        if True:
            assert main.resolve() != sb.ROOT.resolve()
            (main / "new.py").write_text("x = 2\n")
            code, out = sb.git("merge", "--ff-only", "--quiet", "origin/main", cwd=main)
            assert code != 0 and sb.blocking_files(out) == ["new.py"]
            code, why = sb._ff_through_local_edits(["new.py"], root=main)
            assert code != 0 and "不同" in why and (main / "new.py").read_text() == "x = 2\n"
            (main / "new.py").write_text("x = 1\n")
            code, _ = sb._ff_through_local_edits(["new.py"], root=main)
            assert code == 0
            assert g(main, "rev-parse", "HEAD").stdout == g(main, "rev-parse", "origin/main").stdout
            assert g(main, "status", "--porcelain").stdout == ""


def test_fast_forward_clears_one_kind_of_blocker_at_a_time() -> None:
    """10-15:T-093 合并之后,主目录里同时有「已跟踪、内容已等于合进来的」卡和「未跟踪、同内容」的 fixup 脚本 ——
    git 先只报第一类,让路之后才报第二类。在临时仓库里验证,不碰真仓库。"""
    import os
    import subprocess as sp
    import tempfile
    from unittest import mock
    import scripts.seth_bot.seth_bot as sb
    clean = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}

    def g(cwd, *a):
        return sp.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *a], cwd=cwd, capture_output=True, text=True)

    with tempfile.TemporaryDirectory() as td, mock.patch.dict(os.environ, clean, clear=True):
        origin, main, other = Path(td) / "o.git", Path(td) / "m", Path(td) / "w"
        g(td, "init", "--bare", "-b", "main", str(origin))
        g(td, "clone", str(origin), str(main))
        (main / "card.json").write_text("v1\n")
        g(main, "add", "card.json"); g(main, "commit", "-m", "a"); g(main, "push", "origin", "main")
        g(td, "clone", str(origin), str(other))
        (other / "card.json").write_text("v2\n")
        (other / "run.py").write_text("x = 1\n")
        g(other, "add", "card.json", "run.py"); g(other, "commit", "-m", "merge"); g(other, "push", "origin", "main")
        g(main, "fetch", "origin")
        (main / "card.json").write_text("v2\n")
        (main / "run.py").write_text("x = 1\n")
        assert main.resolve() != sb.ROOT.resolve()
        code, out = sb.ff_until_clear(root=main)
        assert code == 0, out
        assert g(main, "rev-parse", "HEAD").stdout == g(main, "rev-parse", "origin/main").stdout
        assert g(main, "status", "--porcelain").stdout == ""


def test_consecutive_commits_share_one_batch_and_order_is_kept() -> None:
    """10-19 Jazz「每次都 preflight 效率很低」:连续的普通提交合成一组;合并 / fetch / untrack / 坏 JSON 各自一组。"""
    from scripts.seth_bot.seth_bot import batches
    c = {"by": "seth", "op": "commit", "paths": ["a"], "message": "m"}
    items = [(Path("1"), c), (Path("2"), c), (Path("3"), {"by": "seth", "op": "merge"}), (Path("4"), c),
             (Path("5"), {**c, "untrack": ["x"]}), (Path("6"), None), (Path("7"), c), (Path("8"), c), (Path("9"), c)]
    got = [[str(p) for p, _ in g] for g in batches(items)]
    assert got == [["1", "2"], ["3"], ["4"], ["5"], ["6"], ["7", "8", "9"]], got
    assert batches([(Path("1"), {**c, "by": "lane-a"}), (Path("2"), c)]) == [[(Path("1"), {**c, "by": "lane-a"})], [(Path("2"), c)]]


def test_a_batch_runs_preflight_once_commits_each_job_and_pushes_once() -> None:
    from unittest import mock
    import scripts.seth_bot.seth_bot as sb
    calls = {"preflight": 0, "push": 0, "commit": 0, "verify": []}
    staged: list[str] = []

    def fake_git(*a, cwd=None):
        if a[:2] == ("diff", "--cached") and "--quiet" in a:
            return 0, ""
        if a[0] == "add":
            staged.extend(x for x in a[2:] if x != "c/unchanged.py")
            return 0, ""
        if a[:3] == ("diff", "--cached", "--name-only"):
            return 0, "\n".join(staged)
        if a[0] == "commit":
            calls["commit"] += 1
            staged.clear()
            return 0, ""
        if a[0] == "reset":
            staged.clear()
            return 0, ""
        if a[0] == "rev-parse":
            return 0, f"sha{calls['commit']}\n"
        if a[0] == "push":
            calls["push"] += 1
            return 0, ""
        raise AssertionError(a)

    def fake_preflight(cwd):
        calls["preflight"] += 1
        return True, "PREFLIGHT PASSED"

    def fake_verify(paths, sha):
        calls["verify"].append((paths, sha))
        return {"deploy_ok": True}
    jobs = [{"id": "j1", "paths": ["a/x.py"], "message": "one", "verify": ["/health"]},
            {"id": "j2", "paths": ["b/"], "message": "two"},
            {"id": "j3", "paths": ["c/unchanged.py"], "message": "three"},
            {"id": "j4", "paths": [".env"], "message": "nope"}]
    with mock.patch.object(sb, "git", fake_git), mock.patch.object(sb, "preflight", fake_preflight), \
            mock.patch.object(sb, "sync_main", lambda: None), mock.patch.object(sb, "run", lambda *a, **k: (0, "")), \
            mock.patch.object(sb, "verify_after_deploy", fake_verify):
        res = sb.do_commit_batch(jobs)
    assert calls["preflight"] == 1 and calls["push"] == 1 and calls["commit"] == 2, calls
    assert [r["ok"] for r in res] == [True, True, False, False], res
    assert res[0]["sha"] == "sha1" and res[1]["sha"] == "sha2" and res[0]["pushed_head"] == "sha2"
    assert res[2]["stage"] == "add" and res[3]["stage"] == "validate"
    assert calls["verify"] == [(["/health"], "sha2")], "一次部署核对,验证路径合并"

    calls.update(preflight=0, push=0, commit=0)
    with mock.patch.object(sb, "git", fake_git), mock.patch.object(sb, "preflight", lambda cwd: (False, "✗ x")), \
            mock.patch.object(sb, "sync_main", lambda: None):
        res = sb.do_commit_batch(jobs[:2])
    assert [r["stage"] for r in res] == ["preflight", "preflight"] and calls["commit"] == 0 and calls["push"] == 0


def test_the_queue_loop_goes_through_batches() -> None:
    src = BOT.read_text(encoding="utf-8")
    assert "for group in batches(" in src and "process_batch(group)" in src



def test_clearing_the_index_lock_tolerates_a_worktree() -> None:
    """10-19:合并在临时 worktree 里跑 preflight,那里的 `.git` 是指针文件 —— 清锁不能 NotADirectoryError。"""
    import tempfile
    from unittest import mock
    import scripts.seth_bot.seth_bot as sb
    with tempfile.TemporaryDirectory() as td:
        wt = Path(td)
        (wt / ".git").write_text("gitdir: /elsewhere\n")
        with mock.patch.object(sb, "ROOT", wt):
            sb._clear_index_lock()
        (wt / ".git").unlink()
        (wt / ".git").mkdir()
        (wt / ".git" / "index.lock").write_text("")
        with mock.patch.object(sb, "ROOT", wt):
            sb._clear_index_lock()
        assert not (wt / ".git" / "index.lock").exists()

if __name__ == "__main__":
    print("── S-500 seth_bot ──")
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ✓ {name}")
    print("\n✅ passed")
