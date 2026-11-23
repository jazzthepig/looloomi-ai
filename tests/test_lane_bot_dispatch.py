"""lane_bot 派卡:分支名的三个坑(11-17)。

**为什么有这个测试。** 11-17 实测:三条 lane 全部 0 张可动 —— lane_bot 一轮轮醒来(额度在烧),
却无事可做,因为 `branch_card_status` 只看 `origin/{lane}/{cid}` 一个引用。三个坑:

  ① **返工分支带后缀。** lane 的交付分支常叫 `lane-a/T-308-null` / `lane-b/T-089-v3` ——
     实测三条 lane 名下 57 条这样的分支(22 / 17 / 18)。只看无后缀那个引用 ⇒ 这 57 条上的卡
     永远读不到 ⇒ 卡被判成「等审」⇒ lane 再也不醒。
  ② **已经并进 main 的分支永远挡路。** T-366:分支 `lane-b/T-366` 已经合进 main(ca52b589),
     Seth 把卡退回 lane-b 返工(main 上 status=open),但分支上那张卡还是 in_review ——
     于是 lane-b 永远看到「等审」,永远不醒。
  ③ **不能改的一条:** 未合并、且卡在分支上仍是 in_review 的,必须继续挡路(S-558:
     等审的卡不叫醒 lane,否则 lane 会一轮轮去「重验」已经交了的活)。

这个测试钉死:①带后缀的分支能被看见;②已合并的分支不再挡路;③未合并的 in_review 仍然挡路;
④同一张卡有多条分支时,最新的那条说了算;⑤分支上读不到卡 = 「不知道」,不是「在等审」。

用真的临时 git 仓库(不是 mock subprocess):分支枚举、祖先判定、提交时间排序三样都依赖 git 的
真实行为,mock 掉就等于把要测的东西换成了另一套东西。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.lane_bot.lane_bot as lb  # noqa: E402

CARD = "T-366"


def _git(repo: Path, *args: str, date: str | None = None) -> str:
    from tests._git_env import scrub_git_env
    scrub_git_env()                    # S-903:`-C repo` 挡不住 GIT_DIR —— 带着它,下面的 init / commit 打在真仓库上
    env = dict(os.environ)
    if date:
        env["GIT_AUTHOR_DATE"] = date
        env["GIT_COMMITTER_DATE"] = date
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, env=env)
    assert r.returncode == 0, f"git {' '.join(args)} 失败:{r.stderr}"
    return r.stdout.strip()


def _make_repo(tmp_path: Path, status: str = "open") -> Path:
    """一个最小的仓库:main 上一张 open 的卡 + 一个远端 main 的引用。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "seth@test")
    _git(repo, "config", "user.name", "seth")
    (repo / "tasks").mkdir()
    (repo / "tasks" / f"{CARD}.json").write_text(
        json.dumps({"id": CARD, "owner": "lane-b", "status": status}), encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base", date="2026-01-01T00:00:00+00:00")
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    return repo


def _branch(repo: Path, name: str, status: str, date: str, *, drop_card: bool = False) -> str:
    """在 main 上开一条 lane 分支,把卡改成 status,提交,回到 main。返回 tip sha。"""
    _git(repo, "checkout", "-q", "-b", name)
    card = repo / "tasks" / f"{CARD}.json"
    if drop_card:
        card.unlink()
    else:
        c = json.loads(card.read_text(encoding="utf-8"))
        c["status"] = status
        card.write_text(json.dumps(c), encoding="utf-8")
    _git(repo, "commit", "-qam", f"card {status}", date=date)
    sha = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "main")
    return sha


def _use(monkeypatch, repo: Path) -> None:
    monkeypatch.setattr(lb, "ROOT", repo)
    monkeypatch.setattr(lb, "_REFS_CACHE", {})


def test_带后缀的分支上的卡能被看见(monkeypatch, tmp_path):
    """坑 ①:`lane-b/T-366-null` 上的 in_review 必须被看见 ⇒ 这张卡在等审,不该叫醒 lane。"""
    repo = _make_repo(tmp_path)
    _branch(repo, f"lane-b/{CARD}-null", "in_review", "2026-01-02T00:00:00+00:00")
    _use(monkeypatch, repo)
    assert lb.branch_card_status("lane-b", CARD) == "in_review"
    assert lb.actionable_cards("lane-b") == [], "分支上已交(in_review)的卡不该再被派出去"


def test_已经并进main的分支不再挡路(monkeypatch, tmp_path):
    """坑 ②(T-366 的真身):分支合进 main 后,Seth 把卡退回重做 —— lane 必须能醒。"""
    repo = _make_repo(tmp_path)
    sha = _branch(repo, f"lane-b/{CARD}", "in_review", "2026-01-02T00:00:00+00:00")
    # 模拟合并:main 指向那条分支的 tip ⇒ 分支 tip 是 origin/main 的祖先
    _git(repo, "update-ref", "refs/remotes/origin/main", sha)
    _use(monkeypatch, repo)
    assert lb.branch_card_status("lane-b", CARD) is None
    assert lb.actionable_cards("lane-b") == [CARD], "合过的分支上的 in_review 是记账残留,不该挡住返工的卡"


def test_未合并的in_review仍然挡路(monkeypatch, tmp_path):
    """S-558 不能被这次修复顺手拆掉:还在等审的卡,不等 lane 去重验。"""
    repo = _make_repo(tmp_path)
    _branch(repo, f"lane-b/{CARD}", "in_review", "2026-01-02T00:00:00+00:00")
    _use(monkeypatch, repo)
    assert lb.branch_card_status("lane-b", CARD) == "in_review"
    assert lb.actionable_cards("lane-b") == []


def test_同一张卡两条分支_最新的那条说了算(monkeypatch, tmp_path):
    """返工分支比原分支新 ⇒ 它的状态才是当前状态(原来的写法只看无后缀那条,永远看旧状态)。"""
    repo = _make_repo(tmp_path)
    _branch(repo, f"lane-b/{CARD}", "claimed", "2026-01-02T00:00:00+00:00")
    _branch(repo, f"lane-b/{CARD}-v2", "in_review", "2026-01-03T00:00:00+00:00")
    _use(monkeypatch, repo)
    assert lb.branch_card_status("lane-b", CARD) == "in_review"
    assert lb.actionable_cards("lane-b") == []
    # 反过来:新分支是 claimed ⇒ 以它为准,卡可动
    repo2 = tmp_path / "repo2"
    repo2.mkdir()
    _git(repo2, "init", "-q", "-b", "main")
    _git(repo2, "config", "user.email", "seth@test")
    _git(repo2, "config", "user.name", "seth")
    (repo2 / "tasks").mkdir()
    (repo2 / "tasks" / f"{CARD}.json").write_text(
        json.dumps({"id": CARD, "owner": "lane-b", "status": "open"}), encoding="utf-8")
    _git(repo2, "add", "-A")
    _git(repo2, "commit", "-qm", "base", date="2026-01-01T00:00:00+00:00")
    _git(repo2, "update-ref", "refs/remotes/origin/main", "HEAD")
    _branch(repo2, f"lane-b/{CARD}", "in_review", "2026-01-02T00:00:00+00:00")
    _branch(repo2, f"lane-b/{CARD}-v2", "claimed", "2026-01-03T00:00:00+00:00")
    _use(monkeypatch, repo2)
    assert lb.branch_card_status("lane-b", CARD) == "claimed"
    assert lb.actionable_cards("lane-b") == [CARD]


def test_分支上读不到卡_是不知道而不是在等审(monkeypatch, tmp_path):
    """读不到 ≠ 在等审。合在一起就又是一个盲区(和坑 ① 同一种病)。"""
    repo = _make_repo(tmp_path)
    _branch(repo, f"lane-b/{CARD}-null", "in_review", "2026-01-02T00:00:00+00:00", drop_card=True)
    _use(monkeypatch, repo)
    assert lb.branch_card_status("lane-b", CARD) is None
    assert lb.actionable_cards("lane-b") == [CARD]


def test_远端分支和本地分支都算数(monkeypatch, tmp_path):
    """lane 推的是 origin/lane-x/...;本机那条 refs/heads/lane-x/... 也可能是最新的那份。"""
    repo = _make_repo(tmp_path)
    sha = _branch(repo, f"lane-b/{CARD}-null", "in_review", "2026-01-02T00:00:00+00:00")
    _git(repo, "update-ref", f"refs/remotes/origin/lane-b/{CARD}-null", sha)
    _use(monkeypatch, repo)
    assert lb.branch_card_status("lane-b", CARD) == "in_review"
    assert lb.actionable_cards("lane-b") == []
