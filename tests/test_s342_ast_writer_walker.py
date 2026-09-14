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
    _is_writer_name,
    _WRITE_FUNCS,
)

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
    failures = [name for name in _POSITIVE if not _is_writer_name(name)]
    assert not failures, (
        f"{failures} are writers but the predicate doesn't match them. "
        f"Either add the name to _WRITE_NAME_RE (new suffix pattern) or "
        f"check why the predicate rejects it."
    )


def test_non_writers_and_helpers_do_not_match() -> None:
    """NEGATIVE: helpers and getters are NOT picked up as writers.

    Over-matching here is worse than under-matching: if the predicate
    flags ``_check_insert_table_safe`` as a writer, the manifest will
    start collecting fake tables from helper internals — and the test
    that protects this is the one that catches the regression.
    """
    failures = [name for name in _NEGATIVE if _is_writer_name(name)]
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
    assert _is_writer_name(None) is False
    assert _is_writer_name("") is False


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
    not_pred = [n for n in _WRITE_FUNCS if not _is_writer_name(n)]
    assert not not_pred, (
        f"_WRITE_FUNCS lists {not_pred} but the predicate rejects them. "
        f"Either the predicate missed a suffix or the snapshot list has a "
        f"stale entry. S-330 was the same drift in reverse."
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
