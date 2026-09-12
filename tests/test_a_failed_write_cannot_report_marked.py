"""A book may not discard the result of its own NAV write (S-334).

THE DEFECT, measured live 2026-09-12. Six books reported `marked`/`ok` for three
days while their NAV tables stood still at 09-09:

    causal_paper_nav   combined_book_nav   dingge_paper_nav
    fusion_paper_nav   scalable_book_nav   two_layer_paper_nav

The mechanism is one line, repeated six times:

    await supabase_insert_table("causal_paper_nav", [{...}])   # value discarded

`supabase_insert_table` reports failure by RETURNING False, not by raising. A
PostgREST 400, an RLS refusal and an open circuit breaker all come back as a
return value. Every one of those six calls sat inside a `try/except Exception`
that could therefore never fire — **the guard was placed at a point the actual
failure could not reach.** The write failed, nobody looked, the function returned
normally, and the loop recorded a success.

AND THE CALLER MADE IT PERMANENT. Each book advanced its Redis state BEFORE
writing, so a failed write left the cache asserting a mark the table did not
have. §3 forbids backfilling a gap, so each of those days is gone.

WHY THIS ONE MATTERS MORE THAN ITS SIZE. The product is a verifiable forward
track record; the NAV tables ARE the record. A book that reports `marked` on a
day it did not write does not merely fail — it produces a false record of having
succeeded, and does so on the exact surface the product is judged on.

THE PART THAT SHOULD HAVE PREVENTED IT. `beta_core_paper` hit this same bug,
fixed it, and wrote the reason down at the call site:

    "CAPTURE THE RETURN VALUE. `supabase_insert_table` reports failure by
     RETURNING False, not by raising — a PostgREST 400 (unknown column, RLS
     refusal, constraint) never reaches the except branch."

**The lesson stayed in the file where it was learned.** Five other books kept the
shape for months. That is this codebase's most expensive recurring pattern: a fix
applied to the call site under investigation rather than to the class, and this
file is the class-level form of it. A comment cannot enforce; a test can.
"""
from __future__ import annotations

import ast
import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_SIGNALS = _ROOT / "src" / "data" / "signals"

#: Call sites that mean "a durable write just happened".
#:
#: Kept in sync with `schema_manifest._WRITE_FUNCS` by
#: `test_the_write_function_list_has_not_drifted` below — S-330 and S-334 were
#: both caused by a hand-written copy of this same knowledge going stale, so the
#: two copies are made to check each other rather than trusted to agree.
_WRITE_FUNCS = {
    "supabase_insert_table",
    "supabase_upsert_table",
    # Added because the drift check below failed on its first run — the manifest
    # had it and this list did not. That is the check earning its place before
    # anyone had to be disciplined about remembering.
    "supabase_delete_table",
    "insert_with_detail",
    # Not in the manifest (it wraps one of the above rather than being a call
    # site the AST scanner counts), but it IS a durable write from a book's
    # point of view, which is what this file guards.
    "write_nav_row",
}

#: Discards that are correct, each with the reason it is correct.
#:
#: ⚠️ NO "同上" / "see above" ENTRIES. A pointer to another entry breaks the
#: moment that entry is edited, and an exemption whose reason cannot be read is
#: indistinguishable from one nobody thought about.
_EXEMPT: dict[tuple[str, str], str] = {
    ("beta_core_paper.py", "nav_exceptions"):
        "_record_exception() is the last-resort refusal logger. It lives on an "
        "error path and must never raise, so it cannot propagate a failure to a "
        "caller — there is no caller left to tell. It DOES capture the value and "
        "log a distinct NOT PERSISTED error (S-334), which is the strongest thing "
        "available at that position.",
}


def _local_writers(tree: ast.Module) -> set[str]:
    """Names of this module's OWN NAV-writer functions, derived from the source.

    ⚠️ THE HOLE THIS CLOSES, found by mutating a real book rather than trusting
    the synthetic control below. The first version of this guard watched only
    direct `supabase_*` calls, so it caught a writer discarding the store's
    result — and completely missed a CALLER discarding the writer's result:

        await _write(today, nav, ...)        # returns (ok, why), thrown away

    That is the same defect one layer up, and it is the layer the six books
    actually broke at. **The guard passed its own negative control while the real
    bug walked past it**, because the control exercised the level I had thought
    about instead of the level that fails.

    Derived, not listed: any async function returning a `(bool, ...)` tuple is
    treated as a writer whose answer must be read. A hand-written list here would
    have the same blind spot as `_WRITE_FUNCS` did in S-330/S-334.
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            continue
        if not node.name.startswith("_write"):
            continue
        for sub in ast.walk(node):
            if (isinstance(sub, ast.Return) and isinstance(sub.value, ast.Tuple)
                    and sub.value.elts
                    and isinstance(sub.value.elts[0], ast.Constant)
                    and isinstance(sub.value.elts[0].value, bool)):
                names.add(node.name)
                break
    return names


def _discarded_writes(path: pathlib.Path) -> list[tuple[int, str, str]]:
    """(lineno, fn, table) for every write call whose value is thrown away.

    A discarded call is an `ast.Expr` — a statement whose entire content is an
    expression nobody binds. `await f(...)` wraps the Call in an Await, so both
    shapes are unwrapped before the function name is read.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return []
    watched = _WRITE_FUNCS | _local_writers(tree)
    out: list[tuple[int, str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Expr):
            continue
        value = node.value
        if isinstance(value, ast.Await):
            value = value.value
        if not isinstance(value, ast.Call):
            continue
        fn = getattr(value.func, "id", None) or getattr(value.func, "attr", None)
        if fn not in watched:
            continue
        if fn not in _WRITE_FUNCS:
            # A LOCAL writer's first argument is a date, not a table — reading it
            # as one produced `_write_nav(1)` → table "1", a label that is not
            # merely useless but wrong, and wrong labels are what get exempted by
            # mistake. Only store-level helpers take the table first.
            table = "<local writer>"
        elif value.args and isinstance(value.args[0], ast.Constant):
            table = str(value.args[0].value)
        else:
            # A non-literal table (a module constant, an f-string) is still a
            # write. Reported as <dynamic> rather than skipped: the thing being
            # guarded is the discard, and the discard is visible either way.
            table = "<dynamic>"
        out.append((node.lineno, fn or "?", table))
    return out


def test_no_book_discards_the_result_of_its_nav_write() -> None:
    offenders: list[str] = []
    for path in sorted(_SIGNALS.glob("*.py")):
        for lineno, fn, table in _discarded_writes(path):
            if (path.name, table) in _EXEMPT:
                continue
            offenders.append(f"{path.name}:{lineno} {fn}({table}) — value discarded")
    assert not offenders, (
        "A book discards the result of a durable write:\n  "
        + "\n  ".join(offenders)
        + "\n\n`supabase_insert_table` reports failure by RETURNING False, not by "
          "raising, so a surrounding try/except cannot see a PostgREST 400, an RLS "
          "refusal or an open breaker. Capture it, refuse to advance state, and "
          "return status='mark_failed' with the reason (see causal_paper._write_nav)."
    )


def test_state_is_not_advanced_before_the_write_that_justifies_it() -> None:
    """Writing after saving state is how a failed write became permanent.

    Order matters and is invisible at review: both versions are two adjacent
    awaits. If state is saved first, a failed write leaves the cache asserting a
    mark the table does not have — and the next run believes it.
    """
    offenders: list[str] = []
    for path in sorted(_SIGNALS.glob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            body = getattr(node, "body", None)
            if not isinstance(body, list):
                continue
            saved_at: int | None = None
            for stmt in body:
                call = stmt.value if isinstance(stmt, ast.Expr) else None
                if isinstance(call, ast.Await):
                    call = call.value
                name = (getattr(getattr(call, "func", None), "id", None)
                        or getattr(getattr(call, "func", None), "attr", None))
                if name in ("_redis_set", "_save_state"):
                    saved_at = stmt.lineno
                elif saved_at is not None and name in ("_write_nav", "_write"):
                    offenders.append(
                        f"{path.name}: state saved at line {saved_at}, "
                        f"NAV written at line {stmt.lineno} — write first")
                    saved_at = None
    assert not offenders, (
        "State is advanced before the write that justifies it:\n  "
        + "\n  ".join(offenders)
        + "\n\nA failed write then leaves the cache asserting a mark the table does "
          "not have, and §3 forbids backfilling the gap."
    )


def test_the_write_function_list_has_not_drifted() -> None:
    """The two hand-written copies of "what counts as a write" must agree.

    S-330: moving `beta_core._write` to `insert_with_detail` made the manifest
    scanner blind to `beta_core_nav`, because its `_WRITE_FUNCS` was a separate
    hand-written list. S-334: the same move broke a guard in test_nav_policy for
    the same reason. **Two copies of one fact is one copy too many** — so if they
    cannot be merged, they are at least made to fail loudly when they disagree.
    """
    sys.path.insert(0, str(_ROOT))
    from src.api.schema_manifest import _WRITE_FUNCS as manifest_funcs

    missing = manifest_funcs - _WRITE_FUNCS
    assert not missing, (
        f"schema_manifest._WRITE_FUNCS has {sorted(missing)} and this guard does "
        "not, so a book could discard the result of one and stay green. Add it here."
    )


def test_the_guard_actually_fires() -> None:
    """NEGATIVE CONTROL. A guard nobody has seen fail is a guard nobody has tested.

    Three of this week's defects were tests that existed and could not fire, so
    the detector is run against a synthetic offender rather than trusted.
    """
    import tempfile

    src = ('async def mark():\n'
           '    await supabase_insert_table("some_nav", [{"a": 1}])\n')
    with tempfile.TemporaryDirectory() as d:
        p = pathlib.Path(d) / "fake_book.py"
        p.write_text(src)
        found = _discarded_writes(p)
    assert found == [(2, "supabase_insert_table", "some_nav")], found

    # THE LEVEL THAT ACTUALLY FAILED: a caller discarding the book's own writer.
    # The first version of this control only covered the case above, and the real
    # mutation walked straight past the guard — so the control now covers the
    # layer the six books broke at, not the layer I had in mind.
    wrapper_src = ('async def _write_nav(d):\n'
                   '    return True, ""\n'
                   'async def mark():\n'
                   '    await _write_nav(1)\n')
    with tempfile.TemporaryDirectory() as d:
        p = pathlib.Path(d) / "fake_wrapper.py"
        p.write_text(wrapper_src)
        found2 = _discarded_writes(p)
    assert found2 == [(4, "_write_nav", "<local writer>")], found2

    # And the inverse: a captured result must NOT be flagged, or the guard is
    # noise and the next person deletes it.
    ok_src = ('async def mark():\n'
              '    ok = await supabase_insert_table("some_nav", [{"a": 1}])\n'
              '    return ok\n')
    with tempfile.TemporaryDirectory() as d:
        p = pathlib.Path(d) / "fake_book_ok.py"
        p.write_text(ok_src)
        assert _discarded_writes(p) == []


def main() -> int:
    fails = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_") or not callable(fn):
            continue
        try:
            fn()
            print(f"  ✓ {name}")
        except AssertionError as e:
            fails += 1
            print(f"  ✗ {name}\n    {e}")
    print(f"\n{'✅' if not fails else '🔴'} a failed write cannot report marked "
          f"— {fails} failing")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
