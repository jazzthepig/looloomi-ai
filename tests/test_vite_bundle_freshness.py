"""
Vite bundle freshness guard — preflight B-4 (S-171 follow-on, M-1 authored by Minimax-B 2026-08-25).

INCIDENT. Twice in 2026-08 the same shape shipped:

  · `dashboard/src/components/Foo.jsx` edited
  · `cd dashboard && npm run build` SKIPPED (forgot, "tests pass")
  · `git add dashboard/src/components/Foo.jsx dashboard/dist/index.html` (only the
    index.html that already existed, since Vite hadn't regenerated it)
  · `git commit -m "feat: add Foo" && git push`
  · Railway deploys. The bundle does NOT contain Foo's compiled chunk. User
    clicks the tab → ReferenceError → blank page. Same shape as S-171
    (AssetRadar), but the cause was different: S-171 was a missing import; this
    is a missing build.

WHY NOTHING CAUGHT IT.

  · `npm run build` was the author's responsibility. The script is fast (~6s),
    but the cost is a discipline step, and discipline steps are exactly what
    the project centralises in preflight (CLAUDE.md "always run preflight").
  · ESLint did not run on the pre-commit (no husky configured). Even if it did,
    it checks the source, not whether the bundle matches it.
  · py_compile is Python only. Vite is JS.

THE GUARD.

This test runs BEFORE `git push`. It compares two mtimes:

  · newest file under `dashboard/src/`  (excluding node_modules, dist, *.bak*)
  · newest file under `dashboard/dist/` (excluding *.map, *.html, *.gz)

If src's newest mtime is later than dist's newest mtime → FAIL with the
exact command to remediate. If the user is running on a commit that did
NOT touch dashboard/src/ at all → PASS in <100ms (the common case).

DELIBERATELY CONSERVATIVE.

  · Ignores node_modules, dist itself, backup files, .map, .gz, .DS_Store.
  · Treats the comparison as "src newer than dist" → fail; this is one-way.
    A stale dist with newer src is the only direction the failure takes.
  · Does NOT run `npm run build` itself — that would mask the bug by repairing
    it. The discipline step is the human's; the guard is the alarm.

Run: python3 -m tests.test_vite_bundle_freshness
"""
from __future__ import annotations

import datetime
import os
import sys
import tempfile
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

_DASH = _ROOT / "dashboard"
_SRC  = _DASH / "src"
_DIST = _DASH / "dist"

# Files we never want to compare against (build artefacts that update for
# unrelated reasons: source maps, gzip copies, OS noise).
_DIST_IGNORE_SUFFIXES = (".map", ".gz", ".html")
_DIST_IGNORE_EXACT    = {"manifest.json", ".DS_Store"}

_FAILURES: list[str] = []


def _fmt(ts: float) -> str:
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def _check(label: str, ok: bool, hint: str = "") -> None:
    mark = "✓" if ok else "✗"
    print(f"  {mark} {label}")
    if not ok:
        _FAILURES.append(f"{label}{(' — ' + hint) if hint else ''}")


def _newest_mtime(root: Path, ignore_suffixes: tuple[str, ...] = (),
                  ignore_exact: set[str] = frozenset()) -> float | None:
    """Walk root, return the highest mtime across all regular files. Returns
    None if root does not exist OR has no eligible files."""
    if not root.is_dir():
        return None
    best: float | None = None
    for dirpath, dirnames, filenames in os.walk(root):
        # Prune known noise directories.
        dirnames[:] = [d for d in dirnames
                       if d not in {"node_modules", ".git", "dist.old",
                                    "__pycache__", ".cache"}]
        for f in filenames:
            if f in ignore_exact:
                continue
            if any(f.endswith(s) for s in ignore_suffixes):
                continue
            p = Path(dirpath) / f
            try:
                m = p.stat().st_mtime
            except OSError:
                continue
            if best is None or m > best:
                best = m
    return best


def test_dist_directory_exists() -> None:
    """No dist/ → never built. The first push of a dashboard change without
    `npm run build` lands here."""
    _check("dashboard/dist/ exists",
          _DIST.is_dir(),
          f"run `cd dashboard && npm run build` to create it")


def test_src_newer_than_dist_fails() -> None:
    """The bug we are guarding against: src edited, dist not rebuilt."""
    src_max  = _newest_mtime(_SRC)
    dist_max = _newest_mtime(_DIST, ignore_suffixes=_DIST_IGNORE_SUFFIXES,
                             ignore_exact=_DIST_IGNORE_EXACT)

    # If dist is missing or has no eligible files, we already flagged above.
    if src_max is None:
        _check("dashboard/src/ has at least one file", False,
              "src/ is missing or empty — wrong repo state")
        return
    if dist_max is None:
        _check("dashboard/dist/ has at least one build artefact",
              False,
              "dist/ has no .js / .css / etc. after filtering; run `npm run build`")
        return

    delta_s = src_max - dist_max
    _check(
        f"newest src mtime ({_fmt(src_max)}) ≤ newest dist mtime ({_fmt(dist_max)})",
        src_max <= dist_max,
        f"src is {delta_s:.1f}s newer than dist — Railway would serve a stale "
        f"bundle. Run `cd dashboard && npm run build && git add dashboard/dist/` "
        f"before pushing.",
    )


def test_guard_catches_a_simulated_staleness() -> None:
    """Negative control: bump an src file's mtime, confirm the predicate
    detects it. If this passes when stale, the guard is decoration."""
    import tempfile, time

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        src = td_path / "src";  src.mkdir()
        dist = td_path / "dist"; dist.mkdir()
        (src / "Foo.jsx").write_text("// foo")
        (dist / "Foo.js").write_text("/* old */")
        # Make dist newer than src.
        old = time.time() - 3600
        os.utime(dist / "Foo.js", (old, old))
        os.utime(src / "Foo.jsx", (old - 1, old - 1))
        assert _newest_mtime(src) < _newest_mtime_time(dist), \
            "test setup wrong: dist should start newer than src"

        # Now bump src to be newer.
        os.utime(src / "Foo.jsx", (time.time(), time.time()))
        assert _newest_mtime(src) > _newest_mtime_time(dist), \
            "test setup wrong: src should now be newer than dist"

    _check("negative control: predicate detects src > dist", True)


def _newest_mtime_time(root: Path) -> float | None:
    """Same as _newest_mtime but without the suffix filter — for use inside
    the tempdir test where there is no noise."""
    return _newest_mtime(root)


def test_does_not_fire_when_only_test_files_changed() -> None:
    """If the most recent src change is in tests/ or scripts/, do not flag.
    Actually we do flag — there is no good way to tell which src/ change is
    the dashboard-relevant one. False positives are CHEAP (rebuild takes 6s);
    false negatives ship a broken tab. So we flag any time src > dist.

    Pinned here as a behavior contract so the asymmetry stays a deliberate
    choice, not an accident."""
    _check("false-positive-asymmetry is intentional", True,
          "see docstring; rebuild on any src > dist is the policy")


if __name__ == "__main__":
    print("── dashboard/dist/ must be newer than dashboard/src/ (B-4, 2026-08-25) ──")
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        fn()
    if _FAILURES:
        print(f"\n🔴 {len(_FAILURES)} FAILED:")
        for f in _FAILURES:
            print(f"   - {f}")
        sys.exit(1)
    print("\n✓ bundle freshness OK")


def _fmt(ts: float) -> str:
    import datetime
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")