#!/usr/bin/env python3
"""
CI compliance scanner — the real PR gate (vs the Claude-Code stdin hook).

Reuses the SAME forbidden-language patterns as `.claude/hooks/compliance_check.py`
(single source of truth) and scans files passed on argv (or all user-facing files).
Exits 1 if any violation lands in a user-facing path → fails the PR check.

Usage:
  python scripts/compliance_scan.py <file> [<file> ...]   # scan specific files (CI: changed files)
  python scripts/compliance_scan.py --all                 # scan all user-facing files
"""
import sys
import os
import importlib.util

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Import the hook module to reuse its patterns + path logic (one source of truth).
_spec = importlib.util.spec_from_file_location(
    "compliance_hook", os.path.join(ROOT, ".claude/hooks/compliance_check.py"))
_hook = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_hook)


VENDORED = {".venv", "venv", "node_modules", "site-packages", "__pycache__",
            "dist", "build", ".git", "Shadow"}


def _vendored(rel: str) -> bool:
    return any(seg in VENDORED for seg in rel.replace("\\", "/").split("/"))


def iter_user_facing_files():
    for base in ("src/api/routers", "dashboard/src", "dashboard/public", "src/data", "src/mcp"):
        for dp, dirs, fns in os.walk(os.path.join(ROOT, base)):
            dirs[:] = [d for d in dirs if d not in VENDORED]   # prune vendored subtrees
            for fn in fns:
                if fn.endswith((".py", ".jsx", ".tsx", ".html", ".js")):
                    yield os.path.relpath(os.path.join(dp, fn), ROOT)


def main(argv):
    if not argv or argv == ["--all"]:
        files = list(iter_user_facing_files())
    else:
        files = argv

    total = 0
    for rel in files:
        path = rel if os.path.isabs(rel) else os.path.join(ROOT, rel)
        if not os.path.isfile(path):
            continue
        if _vendored(rel) or _hook.is_exempt(rel) or not _hook.is_user_facing(rel):
            continue
        try:
            content = open(path, encoding="utf-8", errors="ignore").read()
        except Exception:
            continue
        findings = _hook.scan_content(content, rel)
        if findings:
            for f in findings:
                print(f"::error file={rel},line={f['line']}::[{f['match']}] {f['description']}")
            total += len(findings)

    if total:
        print(f"\nCOMPLIANCE FAILED: {total} forbidden-language violation(s) in user-facing files.")
        print("Reference: .claude/skills/compliance-language/SKILL.md")
        return 1
    print("Compliance OK — no forbidden transactional language in user-facing files.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
