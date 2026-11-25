"""S-501:仓库是 public —— 研究台账、策略手册、Jazz 的裁决不能再进 git。

S-902(11-23):T-056 把台账 R 段的逐字快照与五份策略报告合进了公开仓库 —— 下面三道门当时都只认四个确切文件名。
现在多三条:派生物的路径不许被跟踪、被跟踪的文件名里不许有台账 / 手册的名字、**任何被跟踪的文本里台账条目标题成串出现就红**。

`.gitignore` 挡不住两件事:`git add -f`,和有人删掉 .gitignore 里那几行。这里看的是**索引**(git ls-files),
不是忽略规则:只要有一份被跟踪,下一次推送就把它公开。lane 改动范围(check_pr_scope)与 seth_bot 的
永不提交清单也各挡一层。
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.check_pr_scope import GLOBAL_FORBIDDEN  # noqa: E402
from scripts.seth_bot.seth_bot import DENY  # noqa: E402
from tests._git_env import scrub_git_env  # noqa: E402
from tests._private_docs import (LEDGER_HEADING, LEDGER_HEADINGS_LIMIT, PRIVATE_DERIVED, PRIVATE_DOCS,  # noqa: E402
                                 PRIVATE_NAME_PARTS)


def _tracked() -> set[str]:
    out = subprocess.run(["git", "--no-optional-locks", "ls-files"], cwd=ROOT, check=True,
                         capture_output=True, text=True).stdout
    return set(out.splitlines())


def _ignored(rel: str) -> tuple[bool, str]:
    """`.gitignore` 必须忽略 rel —— 但 git 拒绝穿过软链。

    合并用的临时 worktree 里,`docs/strategy_sources/sidecars/` 是 seth_bot 从主目录软链过去的
    (LOCAL_ONLY),于是 `check-ignore docs/strategy_sources/sidecars/x/REPORT.md` 报
    「beyond a symbolic link」并退出 128 —— 规则明明在,检查却红。2026-11-25 T-424 的合并
    就是被这一行挡在 preflight 门外的(`.gitignore 没有忽略 docs/strategy_sources/sidecars/x/REPORT.md`)。

    遇到这种情况就把仓库的 `.gitignore` 原样搬进一个空临时仓库,在那里问同一个问题:规则本身
    够不够,与本机那个目录是软链还是真目录无关。软链是**合并机器**的形状,不是规则的问题。
    """
    r = subprocess.run(["git", "--no-optional-locks", "check-ignore", "-q", "--no-index", "--", rel],
                       cwd=ROOT, capture_output=True, text=True)
    if r.returncode == 0:
        return True, "仓库内直接判定:已忽略"
    err = (r.stderr or "").strip()
    if "symbolic link" not in err:
        return False, err or f"check-ignore 退出码 {r.returncode}"
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        scrub_git_env()  # S-903:临时仓库里的 git init 不能被 GIT_DIR 指到别处
        shutil.copyfile(ROOT / ".gitignore", tdp / ".gitignore")
        subprocess.run(["git", "init", "-q", "."], cwd=tdp, check=True, capture_output=True)
        r2 = subprocess.run(["git", "--no-optional-locks", "check-ignore", "-q", "--no-index", "--", rel],
                            cwd=tdp, capture_output=True, text=True)
        if r2.returncode == 0:
            return True, "本机是软链 ⇒ 在临时仓库里复核同一份 .gitignore:已忽略"
        return False, (r2.stderr or "").strip() or f"临时仓库里 check-ignore 退出码 {r2.returncode}"


def test_private_docs_are_not_tracked() -> None:
    leaked = sorted(set(PRIVATE_DOCS) & _tracked())
    assert not leaked, f"这些文件被 git 跟踪 —— 推送即公开:{leaked}。git rm --cached(内容留在本机)"


def test_private_docs_are_ignored() -> None:
    for rel in PRIVATE_DOCS:
        ok, detail = _ignored(rel)
        assert ok, f".gitignore 没有忽略 {rel}({detail})"


def test_every_gate_refuses_them() -> None:
    for rel in PRIVATE_DOCS:
        assert rel in GLOBAL_FORBIDDEN, f"check_pr_scope 的全局禁区缺 {rel}"
        assert rel in DENY, f"seth_bot 的永不提交清单缺 {rel}"


# ── S-902:派生物也不入库;守卫认内容,不只认文件名 ───────────────────────────────────────────

def _under(path: str, rel: str) -> bool:
    return path.startswith(rel) if rel.endswith("/") else path == rel


def test_derived_copies_are_not_tracked() -> None:
    leaked = sorted(p for p in _tracked() if any(_under(p, rel) for rel in PRIVATE_DERIVED))
    assert not leaked, f"台账快照 / 策略报告被 git 跟踪 —— 推送即公开:{leaked}"


def test_derived_copies_are_ignored_and_every_gate_refuses_them() -> None:
    from scripts.seth_bot.seth_bot import LOCAL_ONLY, path_problems
    for rel in PRIVATE_DERIVED:
        probe = rel + "x/REPORT.md" if rel.endswith("/") else rel
        ok, detail = _ignored(probe)
        assert ok, f".gitignore 没有忽略 {probe}({detail})"
        assert path_problems([probe]), f"seth_bot 会提交 {probe}"
        assert any(_under(probe, g) or probe.startswith(g) for g in GLOBAL_FORBIDDEN), f"check_pr_scope 的全局禁区没挡 {probe}"
        assert rel.rstrip("/") in LOCAL_ONLY, f"合并用的临时 worktree 里读不到 {rel}(策略向量的 smoke 会红)"


def test_no_tracked_path_carries_a_private_name() -> None:
    import re
    pat = re.compile("|".join(PRIVATE_NAME_PARTS), re.I)
    leaked = sorted(p for p in _tracked() if pat.search(Path(p).name))
    assert not leaked, f"被跟踪的文件名里有台账 / 手册的名字(改个后缀不算换了一份东西):{leaked}"


def ledger_like(text: str) -> int:
    import re
    return len(re.findall(LEDGER_HEADING, text))


def test_no_tracked_text_is_a_copy_of_the_ledger() -> None:
    """认内容:四个确切文件名之外的任何地方出现一份台账的拷贝,这里红。"""
    hits = []
    for p in sorted(_tracked()):
        if not p.endswith((".md", ".txt", ".markdown", ".rst", ".json", ".html")):
            continue
        f = ROOT / p
        if not f.is_file() or f.stat().st_size < 4096:
            continue
        n = ledger_like(f.read_text(encoding="utf-8", errors="ignore"))
        if n >= LEDGER_HEADINGS_LIMIT:
            hits.append(f"{p}({n} 个条目标题)")
    assert not hits, f"被跟踪的文件里有台账的成段拷贝:{hits}"


def test_the_fingerprint_sees_a_renamed_copy() -> None:
    fake = "\n".join(f"## R{i} — 一条实验\n正文\n" for i in range(12)) + "\n## S-902 — 一条\n## M-118 一条\n"
    assert ledger_like(fake) == 14 and ledger_like(fake) >= LEDGER_HEADINGS_LIMIT
    assert ledger_like("## Results\n## R&D\n## Summary\n## S-curve\n") == 0, "普通标题不该命中"
    if (ROOT / "REFUTATION_LEDGER.md").exists():
        assert ledger_like((ROOT / "REFUTATION_LEDGER.md").read_text(encoding="utf-8")) >= 100, "指纹认不出真的台账"


if __name__ == "__main__":
    print("── S-501 私有文档不入库 ──")
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ✓ {name}")
    print("\n✅ passed")
