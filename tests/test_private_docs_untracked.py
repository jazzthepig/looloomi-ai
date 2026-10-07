"""S-501:仓库是 public —— 研究台账、策略手册、Jazz 的裁决不能再进 git。

`.gitignore` 挡不住两件事:`git add -f`,和有人删掉 .gitignore 里那几行。这里看的是**索引**(git ls-files),
不是忽略规则:只要有一份被跟踪,下一次推送就把它公开。lane 改动范围(check_pr_scope)与 seth_bot 的
永不提交清单也各挡一层。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.check_pr_scope import GLOBAL_FORBIDDEN  # noqa: E402
from scripts.seth_bot.seth_bot import DENY  # noqa: E402
from tests._private_docs import PRIVATE_DOCS  # noqa: E402


def _tracked() -> set[str]:
    out = subprocess.run(["git", "--no-optional-locks", "ls-files"], cwd=ROOT, check=True,
                         capture_output=True, text=True).stdout
    return set(out.splitlines())


def test_private_docs_are_not_tracked() -> None:
    leaked = sorted(set(PRIVATE_DOCS) & _tracked())
    assert not leaked, f"这些文件被 git 跟踪 —— 推送即公开:{leaked}。git rm --cached(内容留在本机)"


def test_private_docs_are_ignored() -> None:
    for rel in PRIVATE_DOCS:
        r = subprocess.run(["git", "--no-optional-locks", "check-ignore", "-q", "--no-index", "--", rel], cwd=ROOT)
        assert r.returncode == 0, f".gitignore 没有忽略 {rel}"


def test_every_gate_refuses_them() -> None:
    for rel in PRIVATE_DOCS:
        assert rel in GLOBAL_FORBIDDEN, f"check_pr_scope 的全局禁区缺 {rel}"
        assert rel in DENY, f"seth_bot 的永不提交清单缺 {rel}"


if __name__ == "__main__":
    print("── S-501 私有文档不入库 ──")
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ✓ {name}")
    print("\n✅ passed")
