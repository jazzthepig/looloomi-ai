"""The failure path S-334 added must actually execute (S-335).

WHY THIS FILE EXISTS, and it is not a hypothetical. On 2026-09-12, right after
S-334 rewired six books so a failed write could no longer report `marked`,
`/internal/book-dryrun` came back with six clean `marked` results and zero
errors. It looked like verification. It was not:

    if not dry_run:
        _ok, _why = await _write_nav(...)      # <- everything S-334 changed
        if not _ok:
            return {"status": "mark_failed", ...}
        await _redis_set(...)

`dry_run=True` skips that entire branch. **Six green results, and not one of them
executed a single line of the code being verified.** The dry-run proves a book can
compute a mark; it says nothing about what the book does when the write fails,
which is the only thing S-334 touched.

That is the same shape as the defect S-334 fixed (a guard placed where the
failure cannot reach) and as the hole in S-334's own first guard (a negative
control exercising the layer I had thought about rather than the layer that
breaks). Third instance in one day, so it gets a test instead of a note.

WHAT THIS TESTS. The writers are driven directly with a FAILING insert, because
that is the branch no other check reaches:

    1. the writer returns (False, why) rather than None or a bare False
    2. `why` is non-empty and carries the observed outcome, not a guess
    3. on success it returns (True, "")

Ordering — that a caller checks `_ok` before advancing state — is asserted
structurally in `test_a_failed_write_cannot_report_marked.py`. The two together
cover both halves: this file proves the writer reports, that file proves the
caller listens.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import importlib
import sys
import types
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_TODAY = dt.date(2026, 9, 12)
_W = {"BTC": 0.5, "ETH": -0.5}

# fusion's writer reads `det.loc[ts]` and `ts in det.index`, so the fake has to be
# an indexed Series. A plain dict made the writer return
# (False, "AttributeError: 'dict' object has no attribute 'index'") — technically
# a correct report of a broken payload, but MY fake was the broken thing, and a
# test whose fixture is wrong accuses the code of its own defect.
import pandas as _pd                                                  # noqa: E402
_DET_TS = _pd.Timestamp("2026-09-12")
_DET = _pd.Series([False], index=[_DET_TS])

#: (module, writer, args) — minimal real arguments per writer signature.
_BOOKS = [
    ("causal_paper",    "_write_nav", (_TODAY, 1.01, 0.001, 1.0, 2, 0.0, 0.0, 0.0, False, _W)),
    ("combined_book",   "_write_nav", (_TODAY, 1.01, 0.001, 1.0, 2, 0.0, 0.0, 0.0, False, _W)),
    ("dingge_paper",    "_write_nav", (_TODAY, 1.01, 0.01, 0.0, 0, 0, 0, 0, [])),
    ("scalable_paper",  "_write",     (_TODAY, 1.01, 0.001, 0.0, 0.0, 2, False, _W)),
    ("two_layer_paper", "_write_nav", (_TODAY, 1.01, 0.001, _W, 0.0,
                                       {"book_state": "LONG", "reason": "x"}, {"name": "v5c"})),
    ("fusion_paper",    "_write_nav", (_TODAY, 1.01, 0.001, _W, 0.0,
                                       {"totals": {"fill_ratio_overall": 1.0,
                                                   "weighted_slippage_bps": 0.0},
                                        "capacity": {"status": "OK", "used_pct": 0.0}},
                                       _DET, _DET_TS)),
    # beta_core is here because `test_every_rewired_book_is_covered_here` said so
    # on the first run. I had built the list by hand from the six books I changed
    # and omitted the one that had the pattern already — the derived scope caught
    # exactly the kind of omission a hand-written scope produces (S-327).
    ("beta_core_paper",  "_write",    (_TODAY, 1.01, 1.0, 0.001, 0.0009, 1.0, "RISK_ON",
                                       1.0, 0.42, 2, 1.0, 0.0, False, _W, "note",
                                       "v5_risk_score", 24.0)),
]

_FAIL_DETAIL = {
    "table": "t", "outcome": "http_error", "status": 403,
    "body": "permission denied for table", "elapsed_ms": 12, "role_refusal": True,
}


class _Patched:
    """Swap `rpc_diagnostics.insert_with_detail` for a stub, then put it back.

    The books import it INSIDE the function body (`from src.api.rpc_diagnostics
    import insert_with_detail`), so patching the module attribute is what the
    call actually resolves against — patching the book's globals would miss.
    """

    def __init__(self, result):
        self._result = result
        self._mod = importlib.import_module("src.api.rpc_diagnostics")
        self._orig = self._mod.insert_with_detail

    def __enter__(self):
        async def _stub(table, rows):
            assert isinstance(rows, list) and rows, "writer sent an empty payload"
            return self._result
        self._mod.insert_with_detail = _stub
        return self

    def __exit__(self, *exc):
        self._mod.insert_with_detail = self._orig
        return False


def _run(mod_name, fn_name, args, result):
    mod = importlib.import_module(f"src.data.signals.{mod_name}")
    fn = getattr(mod, fn_name)
    with _Patched(result):
        return asyncio.run(fn(*args))


def test_a_failing_write_returns_false_and_a_reason() -> None:
    """THE BRANCH THE DRY-RUN CANNOT REACH."""
    bad = {}
    for mod_name, fn_name, args in _BOOKS:
        try:
            got = _run(mod_name, fn_name, args, (False, _FAIL_DETAIL))
        except Exception as e:                                    # noqa: BLE001
            bad[mod_name] = f"raised {type(e).__name__}: {e}"
            continue
        if not (isinstance(got, tuple) and len(got) == 2):
            bad[mod_name] = f"returned {got!r}, expected (ok, why)"
            continue
        ok, why = got
        if ok is not False:
            bad[mod_name] = f"reported ok={ok!r} on a FAILED write"
        elif not (isinstance(why, str) and why.strip()):
            bad[mod_name] = f"gave no reason: why={why!r}"
    assert not bad, (
        "A book does not report its own write failure:\n  "
        + "\n  ".join(f"{k}: {v}" for k, v in sorted(bad.items()))
        + "\n\nThis is the branch `dry_run=True` skips entirely, which is why six "
          "green dry-runs on 2026-09-12 verified nothing about S-334."
    )


def test_the_reason_carries_the_observation_not_a_guess() -> None:
    """A reason that names the author's suspects sends every reader back to them.

    S-323m: the old message hardcoded "RPC 不通/熔断/超时" and the real cause (a
    permission error) appeared nowhere in it. The reason must contain what was
    OBSERVED — here the 403 and the PostgREST body.
    """
    thin = {}
    for mod_name, fn_name, args in _BOOKS:
        _ok, why = _run(mod_name, fn_name, args, (False, _FAIL_DETAIL))
        blob = why.lower()
        if "403" not in blob and "permission denied" not in blob:
            thin[mod_name] = why
    assert not thin, (
        "The failure reason omits the observed status/body:\n  "
        + "\n  ".join(f"{k}: {v!r}" for k, v in sorted(thin.items()))
        + "\n\nCarry the observation, not the hypothesis (S-323m)."
    )


def test_a_successful_write_reports_true_and_says_nothing() -> None:
    """NEGATIVE CONTROL. If it returned False either way the guard proves nothing."""
    bad = {}
    for mod_name, fn_name, args in _BOOKS:
        got = _run(mod_name, fn_name, args, (True, {"outcome": "ok", "status": 201}))
        if got != (True, ""):
            bad[mod_name] = f"returned {got!r} on a SUCCESSFUL write"
    assert not bad, (
        "A book misreports a successful write:\n  "
        + "\n  ".join(f"{k}: {v}" for k, v in sorted(bad.items())))


def test_every_rewired_book_is_covered_here() -> None:
    """The book list must not drift away from the books that were changed.

    S-327's first guard used a hand-written scope and missed four of ten books —
    it passed while the four it existed for went unchecked. So the scope is
    derived: any signals module whose writer returns a (bool, ...) tuple is a
    book this file must exercise.
    """
    import ast

    expected = set()
    for path in sorted((_ROOT / "src" / "data" / "signals").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
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
                    expected.add(path.stem)
                    break
    covered = {m for m, _, _ in _BOOKS}
    missing = expected - covered
    assert not missing, (
        f"{sorted(missing)} have a (ok, why) writer and are not exercised here. "
        "A book whose failure path nothing runs is a book whose failure path is "
        "a guess."
    )


def main() -> int:
    fails = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_") or not isinstance(fn, types.FunctionType):
            continue
        try:
            fn()
            print(f"  ✓ {name}")
        except AssertionError as e:
            fails += 1
            print(f"  ✗ {name}\n    {e}")
    print(f"\n{'✅' if not fails else '🔴'} the write failure path actually runs "
          f"— {fails} failing")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
