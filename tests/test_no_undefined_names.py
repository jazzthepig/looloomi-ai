"""
Undefined-name guard — the class of bug that killed T2 silently (2026-08-06).
============================================================================

INCIDENT. `/health` began reporting universe build-phase timings and immediately
answered a question three hypotheses had failed to:

    "railway_t2_ms": 5207, "slowest": "railway_t2_ms",
    "railway_error": "name 'market_cap' is not defined"

`calculate_cis_universe()` referenced a bare `market_cap` that exists as a local
in a *different* function. Every asset carrying open interest raised NameError
inside the per-asset loop, killing the entire T2 universe calculation. The caller
caught it into `_logger.warning(...)`, so:

  · T2 — the fallback for when the Mac engine is down — had been dead silently,
    leaving production on a single point of failure;
  · each failed attempt still burned ~5.2 s, which was the reproducible 12 s
    build-budget overrun the external probe kept flagging.

Python cannot catch this at import time: a NameError on a path that only executes
for some inputs is invisible to `py_compile` and to the boot smoke test. So we
check it statically here.

WHY THIS TEST EXISTS AND NOT JUST "BE CAREFUL": the defect survived because an
exception was downgraded to a warning and nobody read the warning. A guard that
depends on someone reading logs is not a guard. This one fails the build.

Run: python3 -m tests.test_no_undefined_names
"""
import ast
import builtins
import os
import pathlib
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

REPO = pathlib.Path(__file__).resolve().parent.parent

# Modules on the serving path, where a NameError becomes a silent capability loss
# rather than a loud crash. Extend deliberately; this is not meant to be a
# whole-repo linter, it is a tripwire on the paths that matter.
SCANNED = [
    "src/data/cis/cis_provider.py",
    "src/api/routers/cis.py",
    "src/api/store.py",
    "src/api/main.py",
    "src/api/loop_health.py",
]

# Module-level dunders are bound by the interpreter, not by any statement the AST
# can see. `__file__` is the one that actually appears on our serving path.
_BUILTINS = set(dir(builtins)) | {
    "__file__", "__name__", "__doc__", "__package__", "__spec__", "__loader__",
    "__builtins__", "__debug__",
}


def _undefined_names(path: pathlib.Path) -> list[str]:
    """Names read inside a function that are never bound anywhere it can see.

    Deliberately conservative — it only reports a name when it is bound NOWHERE
    in the function, its enclosing functions, module scope, imports or builtins.
    A false positive here would get the whole test muted, and a muted guard is
    worse than no guard: it manufactures assurance. Better to miss some real
    cases than to cry wolf once.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))

    module_names = set(_BUILTINS)
    for n in ast.walk(tree):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
            module_names.add(n.id)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            module_names.add(n.name)
        elif isinstance(n, ast.Import):
            module_names.update((al.asname or al.name.split(".")[0]) for al in n.names)
        elif isinstance(n, ast.ImportFrom):
            module_names.update((a.asname or a.name) for a in n.names)
        elif isinstance(n, ast.Global):
            module_names.update(n.names)

    # Enclosing-function chain. A nested function closes over its parents' locals,
    # so `async def _heartbeat(): await websocket.close()` inside a handler whose
    # parameter is `websocket` is perfectly valid. Scanning each function in
    # isolation reported it as undefined — the third false-positive class this
    # scanner produced before it produced a true positive. Each was a scanner bug,
    # and each was fixed rather than suppressed: the moment you start adding
    # exemptions to silence a guard, the guard is already decoration.
    parent: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parent[child] = node

    def _enclosing_bindings(fn: ast.AST) -> set[str]:
        out: set[str] = set()
        p = parent.get(fn)
        while p is not None:
            if isinstance(p, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                pa = p.args
                for arg in (*pa.args, *pa.posonlyargs, *pa.kwonlyargs):
                    out.add(arg.arg)
                if pa.vararg:
                    out.add(pa.vararg.arg)
                if pa.kwarg:
                    out.add(pa.kwarg.arg)
                for n2 in ast.walk(p):
                    if isinstance(n2, ast.Name) and isinstance(n2.ctx, ast.Store):
                        out.add(n2.id)
                    elif isinstance(n2, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        out.add(n2.name)
                    elif isinstance(n2, ast.ExceptHandler) and n2.name:
                        out.add(n2.name)
                    elif isinstance(n2, (ast.Import, ast.ImportFrom)):
                        out.update((al.asname or al.name.split(".")[0]) for al in n2.names)
            p = parent.get(p)
        return out

    problems: list[str] = []
    for fn in [n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        bound = set(module_names) | _enclosing_bindings(fn)
        a = fn.args
        for arg in (*a.args, *a.posonlyargs, *a.kwonlyargs):
            bound.add(arg.arg)
        if a.vararg:
            bound.add(a.vararg.arg)
        if a.kwarg:
            bound.add(a.kwarg.arg)
        for n in ast.walk(fn):
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
                bound.add(n.id)
            elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                bound.add(n.name)
                # …and its parameters. ast.walk descends into nested functions, so
                # their bodies are scanned here; without binding their args,
                # `def _has(a, block, inner)` reports its own parameters as
                # undefined. (First attempt put this in a later elif — unreachable,
                # because this branch matches FunctionDef first. The scanner has now
                # caught two of its own bugs before catching anyone else's, which is
                # the correct order of operations for a guard.)
                if not isinstance(n, ast.ClassDef):
                    na = n.args
                    for arg in (*na.args, *na.posonlyargs, *na.kwonlyargs):
                        bound.add(arg.arg)
                    if na.vararg:
                        bound.add(na.vararg.arg)
                    if na.kwarg:
                        bound.add(na.kwarg.arg)
            elif isinstance(n, ast.ExceptHandler) and n.name:
                bound.add(n.name)
            elif isinstance(n, (ast.Import, ast.ImportFrom)):
                bound.update((al.asname or al.name.split(".")[0]) for al in n.names)
            elif isinstance(n, (ast.Global, ast.Nonlocal)):
                bound.update(n.names)
            elif isinstance(n, ast.comprehension):
                for t in ast.walk(n.target):
                    if isinstance(t, ast.Name):
                        bound.add(t.id)
            # Parameters of NESTED functions and lambdas. ast.walk descends into
            # them, so their bodies are scanned as part of this function — without
            # this, `lambda x: x["k"]` and `def _has(a, block, inner)` both report
            # their own parameters as undefined. Three such false positives showed
            # up on the first run; the correct response was to fix the scanner, not
            # to add an ignore list. An ignore list would have been the start of the
            # guard rotting into decoration.
            elif isinstance(n, (ast.Lambda, ast.FunctionDef, ast.AsyncFunctionDef)):
                na = n.args
                for arg in (*na.args, *na.posonlyargs, *na.kwonlyargs):
                    bound.add(arg.arg)
                if na.vararg:
                    bound.add(na.vararg.arg)
                if na.kwarg:
                    bound.add(na.kwarg.arg)

        for n in ast.walk(fn):
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and n.id not in bound:
                problems.append(f"{path.name}:{n.lineno} in {fn.name}() → '{n.id}'")
    return problems


def test_serving_path_has_no_undefined_names():
    """A NameError on a rarely-taken branch is invisible to py_compile and to the
    boot smoke test, and — when the caller downgrades it to a warning — invisible
    in production too. That combination cost us a silently dead T2 fallback."""
    found: list[str] = []
    for rel in SCANNED:
        p = REPO / rel
        if p.exists():
            found += _undefined_names(p)
    assert not found, (
        "Undefined name(s) on the serving path:\n  " + "\n  ".join(sorted(set(found)))
        + "\n\nThese raise NameError only when the branch executes. If the caller "
          "catches broadly, the capability dies silently — which is exactly how the "
          "T2 universe fallback was lost (2026-08-06).")


def test_guard_actually_catches_the_original_bug():
    """A guard that cannot fail is not a guard. Reconstruct the exact shape of the
    original defect and assert this scanner flags it."""
    import tempfile
    src = (
        "def calc(market_data, deriv):\n"
        "    oi = float(deriv.get('open_interest_usd') or 0)\n"
        "    if oi > 0 and market_cap > 0:\n"   # the bug: bare name from another scope
        "        return oi / market_cap\n"
        "    return 0\n"
    )
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(src); tmp = pathlib.Path(f.name)
    try:
        probs = _undefined_names(tmp)
        assert any("market_cap" in p for p in probs), \
            "scanner failed to flag the original T2 defect — it would not have caught it"
    finally:
        tmp.unlink(missing_ok=True)


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    p = f = 0
    for t in TESTS:
        try:
            t(); print(f"  ✓ {t.__name__}"); p += 1
        except AssertionError as e:
            print(f"  ✗ {t.__name__}\n      {e}"); f += 1
    print(f"\n{'✅' if not f else '🔴'} {p}/{len(TESTS)} undefined-name checks passed")
    sys.exit(1 if f else 0)
