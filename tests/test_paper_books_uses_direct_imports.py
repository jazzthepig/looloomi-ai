"""S-345 — paper_books/daily_runner.py uses direct imports, not subprocess (S-345).

THE BUG THIS CLOSES. Before S-345, `daily_runner.py:50-58` ran each sleeve
and the nav_ledger module via:

    subprocess.run([sys.executable, str(path)], capture_output=True, text=True, timeout=180)

Three problems with that shape:
  (a) **Tracebacks disappeared into `capture_output`.** A sleeve that raised
      printed to its own stdout, which the orchestrator then printed to the
      outer stdout — but a sleeve that raised AN EXCEPTION during import or
      main() had its traceback captured in `res.stderr` and only printed when
      `rc != 0`. The two paths looked different from the operator's seat;
      only one of them was visible by default. **A bridge between two code
      paths that shows them differently is the same bridge that hides the
      one that actually broke.**
  (b) **The orchestrator depended on the on-disk path layout.** `path =
      _REPO_ROOT / "src" / "research" / "paper_books" / f"{module_name}.py"`
      plus `subprocess.run([sys.executable, ...])` meant the orchestrator
      could not run from an installed package, could not be tested without
      the working tree present, and broke the moment a sleeve was renamed.
  (c) **The orchestrator could not be unit-tested without running the whole
      chain.** A test that wanted to assert "sleeve_2 is skipped on rc != 0"
      could not mock the subprocess; it had to actually run the sleeve.

THE FIX. Direct import via `importlib.import_module(module_name)` + call to
`mod.main()`. Same call sequence as before, none of (a)/(b)/(c) costs.
    - Exceptions surface in this process's traceback.
    - `sys.path` already has the paper_books dir (set at module top), so
      `importlib.import_module("sleeve_1_vol_carry")` resolves.
    - Tests can mock `mod.main` directly.

THE LIE THIS GUARD REJECTS. The pre-S-345 shape looked safe — rc=0 was the
common path, the stdout pipe worked, capture_output did not leak secrets.
But "looks safe" + "rc=0 always returned" is exactly the shape that lets a
broken chain stay broken: every precondition for the bridge is satisfied by
default, and the failure mode (a swallowed exception) is silent. This file
pins the new shape so a future "let me speed this up with subprocess again"
refactor fails the test before it ships.

Run: python3 -m pytest tests/test_paper_books_uses_direct_imports.py -q
or:   python3 -m tests.test_paper_books_uses_direct_imports
"""
from __future__ import annotations

import ast
import pathlib
import re
import sys

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

# Where daily_runner lives + which modules it claims to orchestrate.
DAILY_RUNNER = _ROOT / "src" / "research" / "paper_books" / "daily_runner.py"
PAPER_BOOKS = _ROOT / "src" / "research" / "paper_books"
SLEEVES = ("sleeve_1_vol_carry", "sleeve_2_regime_nowcast", "sleeve_3_macro_overlay")
NAV_LEDGER_MODULE = "nav_ledger"


# ── STATIC GUARD: no subprocess in daily_runner.py ─────────────────────────────

def test_daily_runner_does_not_use_subprocess() -> None:
    """The pre-S-345 shape had `_run_sleeve` use `subprocess.run`. The
    post-S-345 orchestrator dispatches via `importlib.import_module`. Pin it.

    AST-level scan: substring grep would match this docstring's "subprocess"
    mentions. Walking `ast.Call` and rejecting anything whose function is
    `subprocess.run` / `subprocess.Popen` / `subprocess.call` / etc. is the
    structural version — the same discipline `_source.py` documents under
    "匹配构造,不匹配附近的字符串".
    """
    src = DAILY_RUNNER.read_text(encoding="utf-8")
    tree = ast.parse(src)

    banned_attrs = {"run", "Popen", "call", "check_call", "check_output",
                    "getoutput", "getstatusoutput"}
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if not (isinstance(fn, ast.Attribute) and fn.attr in banned_attrs):
            continue
        base = fn.value
        if isinstance(base, ast.Name) and base.id == "subprocess":
            offenders.append(f"line {node.lineno}: subprocess.{fn.attr}(...)")

    # Also reject any `import subprocess` statement — the orchestrator should
    # not even bring it in. The exception is the `subprocess.run` import-as-
    # type alias in modern typing patterns, which is a `from subprocess import
    # ...` form; both are caught by AST below.
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for n in node.names:
                if n.name == "subprocess" or n.name.startswith("subprocess."):
                    offenders.append(f"line {node.lineno}: imports {n.name}")
        if isinstance(node, ast.ImportFrom) and node.module == "subprocess":
            offenders.append(f"line {node.lineno}: from subprocess import ...")

    assert not offenders, (
        "daily_runner.py uses subprocess — this is the pre-S-345 shape.\n  "
        + "\n  ".join(offenders)
        + "\n\nDirect import via importlib.import_module() + mod.main() is the "
          "post-S-345 contract; subprocess hides tracebacks, blocks unit tests, "
          "and depends on the on-disk path layout."
    )


def test_daily_runner_does_import_dispatch() -> None:
    """Positive side of the same contract: the orchestrator dispatches via
    importlib (or equivalent direct-call), not just "any non-subprocess".
    A future refactor that removes subprocess but replaces it with a
    no-op `def _run_module(): return 0` would pass the negative test and
    silently break the orchestrator. This test asserts the importlib dispatch
    is structurally present.
    """
    src = DAILY_RUNNER.read_text(encoding="utf-8")
    # Direct call to importlib.import_module(...)
    tree = ast.parse(src)
    has_importlib_import = any(
        isinstance(n, (ast.Import, ast.ImportFrom))
        and (
            (isinstance(n, ast.Import) and any(x.name == "importlib" for x in n.names))
            or (isinstance(n, ast.ImportFrom) and n.module == "importlib")
        )
        for n in ast.walk(tree)
    )
    assert has_importlib_import, (
        "daily_runner.py does not import importlib — without it the orchestrator "
        "cannot dispatch to sleeve / nav_ledger modules. Either the negative "
        "test above passed by accident (a no-op `_run_module`) or the bridge "
        "shape regressed."
    )

    # And there is at least one `importlib.import_module(...)` call.
    has_call = any(
        isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "import_module"
        and isinstance(n.func.value, ast.Name)
        and n.func.value.id == "importlib"
        for n in ast.walk(tree)
    )
    assert has_call, (
        "daily_runner.py imports importlib but does not call import_module — "
        "the dispatch mechanism is wired wrong."
    )


# ── STATIC GUARD: each sleeve + nav_ledger have a callable main() ────────────

def _module_has_main(py_path: pathlib.Path) -> tuple[bool, str]:
    """Return (ok, reason). ok=True iff the module parses AND defines main()."""
    try:
        tree = ast.parse(py_path.read_text(encoding="utf-8"))
    except SyntaxError as e:
        return False, f"SyntaxError: {e}"
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "main":
            return True, ""
    return False, "no top-level def main()"


def test_each_sleeve_module_has_a_callable_main() -> None:
    """The orchestrator's contract: each entry in SLEEVES exposes main().

    If a sleeve is renamed or refactored away from the def-main() shape, the
    orchestrator's `_run_module` raises (post-S-345: returns rc=1 + a clear
    error). The orchestrator already protects against this at runtime; this
    test makes the protection structural so the next refactor can't quietly
    bypass it by ALSO making `_run_module` forgiving.
    """
    for name in SLEEVES + (NAV_LEDGER_MODULE,):
        path = PAPER_BOOKS / f"{name}.py"
        assert path.exists(), f"{name} module missing at {path}"
        ok, reason = _module_has_main(path)
        assert ok, f"{name}: {reason}" if reason else f"{name}: missing main()"


# ── CLAUDE.md ACKNOWLEDGMENT ──────────────────────────────────────────────────

def test_claude_md_acknowledges_paper_books_as_prototype() -> None:
    """OPEN RISK 0c requires paper_books to be explicitly acknowledged as
    older prototype (per the plan-evaluation's option-(b) sanity check).

    Without an acknowledgment, a cold agent reading CLAUDE.md would not
    know that paper_books/daily_runner.py is NOT a spec_runner entry
    point, and the two paper-book paths (S-284 H fix noted this risk)
    would drift apart in silence.
    """
    claude = (_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    # Look for a line that pairs paper_books with language that says it's
    # older / pre-spec_runner / prototype / deprecated. Exact phrasing
    # varies — match the spirit.
    ok = bool(re.search(
        r"paper_books[^\n]*(?:older|prototype|pre-spec|deprecated|sleeve\+ledger)",
        claude, re.IGNORECASE))
    assert ok, (
        "CLAUDE.md does not acknowledge paper_books as older prototype. "
        "OPEN RISK 0c requires the lane table to distinguish paper_books "
        "(prototype) from paper_trading/spec_runner (canonical). A reader "
        "without this distinction cannot tell which file to use as the "
        "entry point for new work."
    )


# ── RUNTIME GUARD: orchestrator import path ────────────────────────────────────

def test_daily_runner_module_imports_clean() -> None:
    """The orchestrator must be importable (no top-level side effects that
    would block unit tests).

    `import daily_runner` should succeed without running main() or writing
    files. If a future refactor adds top-level work to daily_runner.py, this
    test catches it.
    """
    # Drop any cached version so the import is from disk.
    for k in list(sys.modules):
        if k == "daily_runner" or k.startswith("daily_runner."):
            del sys.modules[k]
    # Add paper_books to sys.path because the module is at
    # src/research/paper_books/daily_runner.py, not at the repo root.
    pb = str(PAPER_BOOKS)
    sys.path.insert(0, pb)
    try:
        import daily_runner as dr  # noqa: F401
        assert hasattr(dr, "main"), "daily_runner.main() missing"
        assert hasattr(dr, "_run_module"), "daily_runner._run_module() missing"
        assert hasattr(dr, "SLEEVES"), "daily_runner.SLEEVES constant missing"
        assert tuple(dr.SLEEVES) == SLEEVES, (
            f"daily_runner.SLEEVES = {dr.SLEEVES}, expected {SLEEVES}"
        )
    finally:
        # Restore sys.path to avoid leaking into other tests.
        try:
            sys.path.remove(pb)
        except ValueError:
            pass


# ── RUNNER ────────────────────────────────────────────────────────────────────

TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]


def main() -> int:
    p = f = 0
    for t in TESTS:
        try:
            t(); print(f"  ✓ {t.__name__}"); p += 1
        except AssertionError as e:
            print(f"  ✗ {t.__name__}\n      {e}"); f += 1
        except Exception as e:
            print(f"  💥 {t.__name__}: {type(e).__name__}: {e}"); f += 1
    print(f"\n{'✅' if not f else '🔴'} {p}/{len(TESTS)} S-345 paper_books bridge checks passed"
          + (f" · {f} FAILING" if f else ""))
    return 1 if f else 0


if __name__ == "__main__":
    sys.exit(main())