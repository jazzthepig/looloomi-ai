#!/bin/bash
# CometCloud — Build + Stage helper
# Run from repo root. Pushes must be done from Mac Mini (FUSE lock issue in Cowork VM).
set -euo pipefail

echo "=== CometCloud Build Script ==="
echo "Working dir: $(pwd)"
echo ""

# Verify we're in the right repo
if [ ! -f "CLAUDE.md" ]; then
  echo "ERROR: Must run from looloomi-ai repo root (CLAUDE.md not found)"
  exit 1
fi

# Clean old chunks and build
echo "Building React frontend..."
cd dashboard
rm -rf dist/assets
npm run build
cd ..
echo "✓ Build complete"

# Show what will be staged
echo ""
echo "Files to stage:"
git status --short src/ dashboard/src/ dashboard/dist/ .claude/ 2>/dev/null

echo ""
echo "Ready. Run from Mac Mini terminal:"
echo "  git add src/ dashboard/src/ dashboard/dist/ .claude/"
echo "  git commit -m '<type>(<scope>): <description>'"
echo "  git push origin main"
echo ""
echo "Post-deploy: check https://looloomi.ai/api/v1/cis/universe after ~2 min"
