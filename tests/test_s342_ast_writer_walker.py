"""S-342: AST-derived writer detection replaces the S-330 hand-maintained set.

THE BUG IT CLOSES. schema_manifest previously enumerated writer names in a
hand-maintained ``_WRITE_FUNCS`` set. When ``beta_core._write()`` renamed
itself to ``insert_with_detail`` (S-329), the manifest went blind to
``beta_core_nav`` writes — the watcher was guarding with a list that no
longer matched the code it was supposed to guard. S-330 documented this.

ROOT CAUSE. A list of writer names and the writers themselves evolved
separately; renaming a writer hides it from the manifest until someone
notices and updates the list. The list was a contract that drifted.

THE FIX. Detect writers by INTENT — a function is a writer iff its name
ENDS with a structural suffix (``_insert_table``, ``_insert_batch``,
``_upsert_table``, ``_delete_table``, ``_with_detail``, ``_rpc_write``) OR
equals ``write_nav_row`` (S-342 catch-up). End-anchored regex. Rename a
writer; the predicate keeps matching. Wrap a writer in a helper like
``_check_insert_table_safe``; the predicate rejects it (suffix ``_safe``
is not a writer suffix).

THIS FILE pins the predicate with three legs:

1. POSITIVE: every currently-known production writer matches.
2. NEGATIVE: helpers and non-writers do NOT match.
3. MUTATION: helpers and over-matching case names fail loudly.

If you came here because a rename broke the predicate, the fix is at the
call site — the predicate is exhaustive for the names the AST walker
discovers in src/. Add a new suffix pattern only for genuinely novel
writer shapes.

Run: python3 -m pytest tests/test_s342_ast_writer_walker.py -q
or:   python3 -m tests.test_s342_ast_writer_walker
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from src.api.schema_manifest import (       # noqa: E402
    _is_rpc_call_name,
    _is_table_write_name,
    _WRITE_FUNCS,
)

# ⚠️ S-356:这个文件曾经 import `_is_writer_name`,而 A-28/A-29 的 manifest 拆分
# 把那个谓词**一分为二**:`_is_table_write_name`(表在 args[0])和
# `_is_rpc_call_name`(函数名在 args[0])。拆分是对的 —— `supabase_rpc_write`
# 是一个写 RPC,不是表写入者,两者需要存在于不同的目录里。
#
# 但 `bb23fa9`(21:29)加谓词、`e61a7ad`(23:31)拆掉它,**两小时,同一个人,
# 后一个提交打断了前一个提交的测试**,而这个测试在 preflight 里注册着 ——
# 所以 main 上的 preflight 从那一刻起一直是红的,挡住了之后每一次 push。
#
# **一个跨两次提交的重构,和它守卫的测试分开演化**(S-330 同形:换写入函数
# 让 manifest 扫描器失明,只是那次隔的是两个文件,这次隔的是两个提交)。
#
# ⚠️ 我自己的账:我连着两轮说「归 A,我不动他的 lane」—— **那是错的**。
# CLAUDE.md 规则 3 写着 `src/` 和 `tests/` 是 Seth/Austin lane。
# **我用一条不存在的边界推掉了两次,而它一直在挡着 push。**

# LEG 1 — POSITIVE: every currently-shipped writer matches the predicate.
# If a future writer ships under one of the standard suffixes but is
# missing here, the predicate itself needs a new branch (or it already
# catches it via the suffix regex, in which case this list is just
# documentation).
_POSITIVE = (
    # Pattern A — table-as-args[0]:
    "supabase_insert_table",
    "supabase_upsert_table",
    "supabase_delete_table",
    "insert_with_detail",                # S-328/S-329 catch-up (was S-330's bug)
    "write_nav_row",                     # S-342 catch-up (factor_tilt_paper.py:493 etc.)
    # Pattern B — rows-as-args[0] (table is in each row / is the RPC name):
    "supabase_insert_batch",             # S-342 catch-up (Router batch inserts)
    "supabase_rpc_write",                # S-342 catch-up (Mac-side role-gated RPC)
)


# LEG 2 — NEGATIVE: helpers and read-shapes do NOT match. The risk the
# predicate runs is over-matching (an unrelated suffix like ``_safe``
# triggering on ``_check_insert_table_safe``). These names are required
# to reject.
_NEGATIVE = (
    "_check_insert_table_safe",          # suffix ``_safe`` — wrapper, not writer
    "_validate_insert_table_v2",         # suffix ``_v2`` — wrapper
    "supabase_get_history",              # getter, not writer
    "supabase_get_latest_trending",      # getter
    "fetch_latest_signal_track_record",  # domain-specific fetcher
    "compute_cis_score",                 # pure compute
    "",                                  # empty string
)


def test_every_current_writer_matches_the_predicate() -> None:
    """POSITIVE: the AST walker recognizes every shipping writer."""
    # 拆分之后要分两侧验:表写入者走 `_is_table_write_name`,
    # 写 RPC 走 `_is_rpc_call_name`。**一个写入者必须被其中恰好一侧认领** ——
    # 两侧都不认 = 扫描器看不见它;两侧都认 = 它会被数两次。
    unclaimed, double = [], []
    for name in _POSITIVE:
        t, r = _is_table_write_name(name), _is_rpc_call_name(name)
        if not (t or r):
            unclaimed.append(name)
        elif t and r:
            double.append(name)
    assert not unclaimed, (
        f"{unclaimed} are writers but NEITHER predicate matches them — "
        f"the AST walker is blind to them. Add to _TABLE_WRITE_SUFFIX/"
        f"_TABLE_WRITE_EXACT or to the RPC side, whichever they belong to."
    )
    assert not double, (
        f"{double} match BOTH predicates — they would be counted twice, "
        f"and a table would appear in rpc_functions or vice versa."
    )


def test_non_writers_and_helpers_do_not_match() -> None:
    """NEGATIVE: helpers and getters are NOT picked up as writers.

    Over-matching here is worse than under-matching: if the predicate
    flags ``_check_insert_table_safe`` as a writer, the manifest will
    start collecting fake tables from helper internals — and the test
    that protects this is the one that catches the regression.
    """
    # 负样本必须被**两侧**都拒绝 —— 只验一侧的话,一个名字可以从另一侧溜进来。
    failures = [name for name in _NEGATIVE
                if _is_table_write_name(name) or _is_rpc_call_name(name)]
    assert not failures, (
        f"{failures} are NOT writers but the predicate says they are. "
        f"Loosen the regex end-anchoring so helpers like "
        f"``_check_insert_table_safe`` (suffix ``_safe``) are not flagged."
    )


def test_predicate_rejects_none_and_empty() -> None:
    """EDGE: the predicate must not crash on None / empty inputs.

    ``ast.Call.func`` is occasionally ``Attribute`` whose ``attr`` may be
    None for malformed AST — the predicate should reject, not raise.
    """
    assert _is_table_write_name(None) is False
    assert _is_rpc_call_name(None) is False
    assert _is_table_write_name("") is False
    assert _is_rpc_call_name("") is False


def test_write_funcs_snapshot_includes_s342_catch_ups() -> None:
    """The legacy ``_WRITE_FUNCS`` snapshot must list S-342's catch-ups so
    three downstream tests don't silently regress (S-244 shape).

    Tests that import ``_WRITE_FUNCS``:
      - tests/test_a_book_asks_the_table_not_the_cache.py
      - tests/test_nav_policy.py
      - tests/test_a_failed_write_cannot_report_marked.py

    Each builds a regex alternation over the set to scan for writer call
    sites in paper files. If a new writer (like ``write_nav_row``) ships
    but is missing from the snapshot, those tests don't catch it.
    """
    must = {"write_nav_row", "supabase_insert_batch", "supabase_rpc_write"}
    missing = must - _WRITE_FUNCS
    assert not missing, (
        f"{missing} are not in the legacy _WRITE_FUNCS snapshot. The three "
        f"downstream tests will silently miss these writers' call sites. "
        f"Add them — the predicate already catches them by suffix."
    )


def test_predicate_is_a_superset_of_write_funcs() -> None:
    """Consistency: any name in the legacy set must also pass the predicate.

    The legacy set is a SNAPSHOT of writers the codebase has shipped so
    far. The predicate is structural. They must agree on what they BOTH
    cover; if they don't, one of them drifted.
    """
    # 拆分之后:快照里的每个名字必须被**恰好一侧**认领。实测(2026-09-16)
    # 6 个在表侧、`supabase_rpc_write` 在 RPC 侧、两侧都不认的为 0。
    not_pred = [n for n in _WRITE_FUNCS
                if not (_is_table_write_name(n) or _is_rpc_call_name(n))]
    both = [n for n in _WRITE_FUNCS
            if _is_table_write_name(n) and _is_rpc_call_name(n)]
    assert not not_pred, (
        f"_WRITE_FUNCS lists {not_pred} but NEITHER predicate accepts them — "
        f"the AST walker is blind to those writers. S-330 was the same drift "
        f"in reverse (the function moved, the list did not)."
    )
    assert not both, (
        f"{both} match both predicates — a table would be counted as an RPC "
        f"or vice versa, and the two manifests would double-count it."
    )


if __name__ == "__main__":
    """Stand-alone runner for preflight stage registration.

    pytest collects ``test_*`` functions above; this block lets the file
    also be invoked directly (parallel to tests/test_every_written_table_
    exists.py). preflight uses ``python3 -m pytest`` for pytest-style
    files; this block is here so future tooling can run it bare.
    """
    test_every_current_writer_matches_the_predicate()
    test_non_writers_and_helpers_do_not_match()
    test_predicate_rejects_none_and_empty()
    test_write_funcs_snapshot_includes_s342_catch_ups()
    test_predicate_is_a_superset_of_write_funcs()
    print("\n✅ S-342 AST walker verified — predicate matches intent, not enumeration")
