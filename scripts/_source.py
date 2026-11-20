"""Source-scanning helpers shared by the guards (`scripts/` + `tests/`).

⚠️ THE RULE THIS FILE EXISTS TO ENFORCE: a guard must match the CONSTRUCT,
never a nearby string. Matching a bare name against raw source means comments
and docstrings satisfy the match, and since the comment explaining a bug always
sits next to the fix for that bug, the guard ends up ANTI-correlated with what it
guards — the better the explanation, the more thoroughly it disables the test.

Measured, not theorised. Four occurrences in a single session (2026-08-20):
  · `redis_get_key_status` matched in the comment above the fix (S-180)
  · `supabase_fresh_t1_symbols` matched in an import, not at its call site
  · `max-age=600` matched inside the comment explaining why 600 was wrong
  · "write ... macro brief" matched `_persist_brief`'s docstring
Plus S-167's JSX component name matched inside a docstring, and
`supabase_insert_batch` matched at an import line rather than a call.

**And again on 2026-11-20(S-895 阶段 3)**: `sense_entrypoints()` 数「哪些文件
各自打外网取价」,判据是「文件里有价格端点字面量 **且** 有 HTTP 调用」——
而它匹配的是**原文**。于是 `cg_panel_sync.py` 的 **docstring** 里写了一句
「/ohlc/range」,这个**从不自己取价**的文件(它把取价委托给
`cg_pro_backfill.backfill`)就被算成了**第 24 条私有取价路径**,preflight 红。
实测:剥掉注释与 docstring 之后,24 → 16,掉下来的 8 个文件**在代码里一个价格
端点字面量都没有**(逐个查过:`main.py` / `cis.py` / `signals.py` /
`cg_panel_sync.py` / `global_history.py` / `dingge_paper.py` /
`outcome_tracker.py` / `pod_aggregator_paper.py`)。
⇒ 判据改成**构造**,不是附近的字符串。
"""
from __future__ import annotations

import ast
import re


def code_only(src: str) -> str:
    """Source with comments and docstrings blanked, line numbers preserved."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return re.sub(r"#.*", "", src)
    doc_lines: set[int] = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)):
            doc_lines.update(range(node.value.lineno, node.value.end_lineno + 1))
    return "\n".join(
        "" if i in doc_lines else re.sub(r"#.*", "", line)
        for i, line in enumerate(src.split("\n"), start=1))


__all__ = ["code_only"]
