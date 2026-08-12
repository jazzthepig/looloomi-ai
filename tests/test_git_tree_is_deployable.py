"""
Guard: what is IN GIT can boot — not just what is on this disk (S-156).

THE INCIDENT, 2026-08-12 23:40. `origin/main:src/api/store.py:11` carried

    from src.api.runtime_role import note_refusal, refuse_write

at module level, while `src/api/runtime_role.py` had never been committed. The
file existed on the laptop, so every local check passed; it did not exist in the
repository, so Railway deployed a tree that could not import `store`, and
`store` is on the boot path. Production went down with 504 preflight checks
green.

THE STRUCTURAL HOLE. **Preflight validates the WORKING TREE. Railway deploys the
GIT TREE. Nothing compared them.** Every existing gate — py_compile, the boot
smoke, all 500-odd discipline checks — reads files from disk, and an untracked
file is indistinguishable from a tracked one when you are reading a directory.
The gate was not weak; it was pointed at the wrong tree.

HOW THE UNTRACKED FILE HAPPENED, because the mechanism is worth keeping. Under
zsh, `git commit -m "fix(c3)!: ..."` never reaches git: `!` triggers history
expansion inside double quotes and `!:` is a modifier, so the shell aborts the
line first. `git add` had already run, the commit silently did not, and later
work reset the index. Commits written with a `git commit -F- <<'MSG'` heredoc
were unaffected — which is exactly the split observed: three heredoc commits
landed complete, two `-m` commits landed as docs-only while their code stayed
untracked.

WHAT THIS FAILS ON, and what it deliberately does not:

  · a MODULE-LEVEL import of a `src.*` module absent from the tree  → FAIL.
    This is a boot failure; nothing downstream runs.
  · a function-local import of a missing module, NOT inside a try  → FAIL.
    Deferred, but it is still a 500 on whatever endpoint reaches it.
  · a function-local import inside `try:` with a fallback  → ALLOWED, listed.
    `share.py:407` imports the long-dead `src.api.data_layer` and falls back to
    `routers.market.get_macro_pulse`. That is a deliberate optional path, and a
    guard that fails on it is a guard that gets muted — which is how the real
    one would have been ignored.

Run: python3 -m tests.test_git_tree_is_deployable
"""
from __future__ import annotations

import ast
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

_FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name} :: {detail}")
        _FAILURES.append(name)


def _export_head() -> Path | None:
    """Materialise HEAD — what a push would deliver — into a temp dir.

    HEAD, not the index and not the working tree: the index can hold files a
    failed commit left staged, and the working tree is the thing that lied."""
    tmp = Path(tempfile.mkdtemp(prefix="gittree_"))
    try:
        blob = subprocess.run(["git", "archive", "HEAD"], cwd=_ROOT,
                              capture_output=True, timeout=120)
        if blob.returncode != 0:
            return None
        tar_path = tmp / "head.tar"
        tar_path.write_bytes(blob.stdout)
        with tarfile.open(tar_path) as t:
            t.extractall(tmp / "tree")
        return tmp / "tree"
    except Exception:
        return None


def _module_index(root: Path) -> set[str]:
    mods: set[str] = set()
    for p in root.rglob("*.py"):
        rel = p.relative_to(root)
        mods.add(str(rel.with_suffix("")).replace("/", "."))
        if rel.name == "__init__.py":
            mods.add(str(rel.parent).replace("/", "."))
    return mods


def _guarded_by_try(tree: ast.AST, node: ast.AST) -> bool:
    """Is this import lexically inside a `try:` body? A try/except around an
    import is an author saying 'this may be absent'; failing on it would be
    failing on an intention."""
    for n in ast.walk(tree):
        if isinstance(n, ast.Try):
            for stmt in n.body:
                for sub in ast.walk(stmt):
                    if sub is node:
                        return True
    return False


def _scan(root: Path):
    present = _module_index(root)
    fatal, optional = [], []
    files = sorted(root.glob("src/**/*.py"))
    for p in files:
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        top_level = {id(n) for n in tree.body}
        for n in ast.walk(tree):
            mods = []
            if isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
                mods = [n.module]
            elif isinstance(n, ast.Import):
                mods = [a.name for a in n.names]
            for m in mods:
                if not m.startswith("src."):
                    continue
                if m in present or any(x.startswith(m + ".") for x in present):
                    continue
                where = f"{p.relative_to(root)}:{n.lineno} -> {m}"
                if id(n) in top_level:
                    fatal.append(f"MODULE-LEVEL {where}")
                elif _guarded_by_try(tree, n):
                    optional.append(where)
                else:
                    fatal.append(f"unguarded    {where}")
    return len(files), fatal, optional


def test_every_src_import_in_HEAD_resolves_inside_HEAD() -> None:
    root = _export_head()
    if root is None:
        check("git archive HEAD succeeded", False,
              "cannot export HEAD — this guard cannot run, which is itself a fail")
        return
    n, fatal, optional = _scan(root)
    check(f"{n} files in HEAD scanned", n > 100, f"only {n} — the export looks empty")
    check("no src.* import in HEAD points at a file missing from HEAD",
          not fatal,
          "\n      " + "\n      ".join(fatal)
          + "\n      → the file exists on this disk and NOT in the repository. "
            "Railway deploys the repository.")
    if optional:
        print(f"    · {len(optional)} optional import(s) inside try/except, allowed:")
        for o in optional[:5]:
            print(f"        {o}")


def test_the_guard_catches_the_incident_it_was_built_for() -> None:
    """A scan that finds nothing passes for the same reason a broken one does.
    So: synthesise the exact 2026-08-12 shape and require a FAIL."""
    tmp = Path(tempfile.mkdtemp(prefix="gittree_probe_"))
    (tmp / "src" / "api").mkdir(parents=True)
    (tmp / "src" / "__init__.py").write_text("")
    (tmp / "src" / "api" / "__init__.py").write_text("")
    (tmp / "src" / "api" / "store.py").write_text(
        "from src.api.runtime_role import refuse_write\n")   # module never written
    _, fatal, _ = _scan(tmp)
    check("a module-level import of a missing module is caught",
          any("runtime_role" in f and "MODULE-LEVEL" in f for f in fatal), str(fatal))

    (tmp / "src" / "api" / "share.py").write_text(
        "def f():\n"
        "    try:\n"
        "        from src.api.data_layer import get_macro_pulse\n"
        "    except Exception:\n"
        "        from src.api.store import supabase_insert_table\n")
    _, fatal2, optional2 = _scan(tmp)
    check("a try-guarded optional import is NOT treated as fatal",
          not any("data_layer" in f for f in fatal2), str(fatal2))
    check("but it is still listed",
          any("data_layer" in o for o in optional2), str(optional2))


def test_preflight_runs_this_before_the_push() -> None:
    """The gate is only a gate if it is in the gate. The suite that would have
    caught 2026-08-12 must run in the same script that guards the push."""
    pf = (_ROOT / "scripts/preflight.sh").read_text(encoding="utf-8")
    check("preflight invokes this suite",
          "test_git_tree_is_deployable" in pf,
          "a guard outside the gate is indistinguishable from no guard")


if __name__ == "__main__":
    print("── what is in git can boot (S-156) ──")
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        fn()
    if _FAILURES:
        print(f"\n🔴 {len(_FAILURES)} FAILED: {_FAILURES}")
        sys.exit(1)
    print("\n✅ the tree that deploys is the tree that was checked")
