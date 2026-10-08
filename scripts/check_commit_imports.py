"""推送前最后一道:已提交的代码 import 了一个**磁盘上有、但没提交**的本仓库模块吗?(S-456)

为什么 preflight 抓不到:preflight 跑在**工作目录**上,未跟踪的新文件就在磁盘上,import 照样成功;
而交接块是「先 preflight、后 git add」。09-30 一个路由在函数体里懒加载 `src.data.interpret.validate`,
路由所在文件被提交了,`validate.py` 没被 add —— 线上一调用就 500。

用法(交接块里放在 `git push` 之前,commit 之后):`python3 scripts/check_commit_imports.py &&`
只读 git(`--no-optional-locks`),不碰 index 锁。
"""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ("src", "paper_trading")


def tracked() -> set[str]:
    out = subprocess.run(["git", "-C", str(ROOT), "--no-optional-locks", "ls-files", "-z"],
                         capture_output=True, check=True).stdout.decode()
    return {f for f in out.split("\0") if f}


def module_paths(mod: str) -> list[str]:
    rel = mod.replace(".", "/")
    return [f"{rel}.py", f"{rel}/__init__.py"]


def missing_imports(files: set[str]) -> list[tuple[str, str, str]]:
    bad = []
    for f in sorted(files):
        if not f.endswith(".py") or not f.startswith(PACKAGES):
            continue
        try:
            # 读「已提交」的内容,不读磁盘:工作区里别的没提交的改动(一个还没提交的 import)
            # 不该挡住一个与它无关的提交(10-08 seth_bot 的一个提交就被这样拦下)。
            src = subprocess.run(["git", "-C", str(ROOT), "--no-optional-locks", "show", f"HEAD:{f}"],
                                 capture_output=True, check=True).stdout.decode("utf-8")
            tree = ast.parse(src)
        except (SyntaxError, OSError, subprocess.CalledProcessError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            mods = []
            if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                mods = [node.module]
            elif isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            for m in mods:
                if not m.startswith(tuple(p + "." for p in PACKAGES)):
                    continue
                cands = module_paths(m)
                on_disk = [c for c in cands if (ROOT / c).exists()]
                if on_disk and not any(c in files for c in on_disk):
                    bad.append((f, m, on_disk[0]))
    return bad


def main() -> int:
    files = tracked()
    bad = missing_imports(files)
    if bad:
        print("✗ 已提交的代码 import 了没提交的模块 —— 推上去线上会 ImportError:")
        for f, m, p in bad:
            print(f"    {f}  →  {m}  (磁盘上有 {p},但 git 没跟踪)")
        print("  把这些文件 git add 进同一批提交再推。")
        return 1
    print("✓ 已提交代码 import 的本仓库模块都已提交")
    return 0


if __name__ == "__main__":
    sys.exit(main())
