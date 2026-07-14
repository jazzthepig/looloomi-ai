#!/usr/bin/env bash
# Build the React dashboard IN-SANDBOX. Vite's emptyDir hits the Cowork FUSE deny-unlink,
# so we build to /tmp (outside the mount) then copy dist/ back in (copy = write, allowed).
# Removes the "wait for a Mac npm run build" bottleneck. (2026-07-13.)
set -euo pipefail
cd "$(dirname "$0")/../dashboard"

OUT="/tmp/dash_dist_$$"
echo "→ vite build → $OUT ..."
npx vite build --outDir "$OUT" --emptyOutDir

echo "→ copy build into dashboard/dist (old hashed chunks remain as harmless orphans) ..."
cp -r "$OUT"/* dist/
rm -rf "$OUT"

APP=$(grep -oE 'app-[A-Za-z0-9_]+\.js' dist/app.html | head -1)
echo "✅ frontend built. app.html → $APP  (verify it exists: $([ -f "dist/assets/$APP" ] && echo present || echo MISSING))"
