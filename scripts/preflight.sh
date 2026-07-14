#!/usr/bin/env bash
# Preflight — the MANDATORY pre-push gate. The app must IMPORT and BOOT, not just
# compile. `py_compile` only checks syntax; it MISSES import-time NameErrors (e.g. a
# name used in a function annotation that isn't imported) — exactly the class that
# 502'd production on 2026-07-13 (`Response` unimported in main.py, py_compile passed).
#
# Run this before EVERY push. It is the same check CI runs, but locally, before the
# broken commit ever reaches Railway (which auto-deploys on push regardless of CI).
#
#   bash scripts/preflight.sh   &&   git push origin main
set -euo pipefail
cd "$(dirname "$0")/.."

echo "→ [1/2] byte-compile all src ..."
python3 -m py_compile $(git ls-files 'src/**/*.py') && echo "  ✓ syntax OK"

echo "→ [2/2] import + boot smoke (the real gate py_compile can't do) ..."
INTERNAL_TOKEN=preflight ENVIRONMENT=ci python3 scripts/smoke_test.py

echo ""
echo "✅ PREFLIGHT PASSED — app imports + boots. Safe to push."
