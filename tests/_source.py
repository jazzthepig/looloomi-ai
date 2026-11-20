"""Shared source-scanning helpers for guard tests.

⚠️ THE RULE THIS FILE EXISTS TO ENFORCE: a guard must match the CONSTRUCT, never
a nearby string. Matching a bare name against raw source means comments and
docstrings satisfy the match, and since the comment explaining a bug always sits
next to the fix for that bug, the guard ends up ANTI-correlated with what it
guards — the better the explanation, the more thoroughly it disables the test.

Measured, not theorised. Four occurrences in a single session (2026-08-20):
  · `redis_get_key_status` matched in the comment above the fix (S-180)
  · `supabase_fresh_t1_symbols` matched in an import, not at its call site
  · `max-age=600` matched inside the comment explaining why 600 was wrong
  · "write ... macro brief" matched `_persist_brief`'s docstring
Plus S-167's JSX component name matched inside a docstring, and
`supabase_insert_batch` matched at an import line rather than a call.

So: run `code_only()` first, then match a call-shaped pattern.

**2026-11-20(S-895 阶段 3)**:实现搬到 `scripts/_source.py` —— `scripts/loop_status.py`
的「取数入口」计数也要用它(那个守卫 11-20 被一句 docstring 里的
`/ohlc/range` 绊倒,见那边)。**一份实现,两个消费者。**
"""
from __future__ import annotations

import pathlib
import re
import sys

_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts._source import code_only                          # noqa: E402,F401


def flat(src: str) -> str:
    """Whitespace collapsed to single spaces.

    For matching prose that the source has wrapped across lines — a rule reading
    "compresses grades by\\n  design" does not contain "compresses grades by
    design", and a guard that fails on line wrapping teaches nothing except to
    delete the guard.
    """
    return re.sub(r"\s+", " ", src)


def tracked_py(base) -> list:
    """`*.py` under `base` that git tracks — what a ratchet should count.

    2026-09-26:`rglob` 数的是**磁盘上的目录**,不是仓库。主工作目录里有两个未跟踪文件
    (4 处裸日期),于是同一个提交在主目录算 111、在 lane worktree 算 107 ——
    lane-b 的 preflight 红了,主目录的是绿的,**同一份代码两个判决**。
    多 worktree 之后这必然反复发生,所以棘轮一律数 `git ls-files`。
    git 不可用时退回 rglob(并不比以前差)。`--no-optional-locks`:只读,不碰 index 锁(规则 4)。
    """
    import subprocess
    from pathlib import Path
    base = Path(base).resolve()
    try:
        top = subprocess.run(["git", "-C", str(base), "--no-optional-locks", "rev-parse",
                              "--show-toplevel"], capture_output=True, text=True, check=True).stdout.strip()
        out = subprocess.run(["git", "-C", top, "--no-optional-locks", "ls-files", "-z", "--",
                              str(base.relative_to(top))], capture_output=True, check=True).stdout
        files = [Path(top) / f for f in out.decode().split("\0") if f.endswith(".py")]
        return sorted(p for p in files if p.exists())
    except Exception:                                             # noqa: BLE001
        return sorted(base.rglob("*.py"))
