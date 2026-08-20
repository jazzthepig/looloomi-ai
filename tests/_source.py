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


def flat(src: str) -> str:
    """Whitespace collapsed to single spaces.

    For matching prose that the source has wrapped across lines — a rule reading
    "compresses grades by\\n  design" does not contain "compresses grades by
    design", and a guard that fails on line wrapping teaches nothing except to
    delete the guard.
    """
    return re.sub(r"\s+", " ", src)
