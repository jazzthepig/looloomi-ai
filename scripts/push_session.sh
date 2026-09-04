#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# push_session.sh — MAC-SIDE push helper. Lane-safe, preflight-gated.
# Replaces the 2026-07-17 hardcoded session-push block; encodes:
#   · CLAUDE.md rule #6 — NEVER `git add -A`; stage only explicit paths
#   · CLAUDE.md rule #5 — preflight BEFORE push
#   · CLAUDE.md rule #4 — git write-commands are Mac-side only (this script
#     will not work in the Cowork sandbox; FUSE denies unlink)
#   · 防御性:对"不是我拥有的 dirty 文件"显式拒绝,免得 `git add -A` 误吞
#     别人的活(scripts/lesson_enforcement_baseline.txt 是前科)
#
# Usage:
#   PUSH_PATHS="<space-separated files I own>" \
#   PUSH_SUBJECT="<commit subject>" \
#   PUSH_BODY="<multi-line commit body>" \
#   PUSH_REFUSE_DIRTY="<files I do NOT own — refuse if any are dirty/staged>" \
#   bash scripts/push_session.sh
#
#   PUSH_DRY_RUN=1  → show plan, do nothing
#   PUSH_SESSION_TAG=<name>  → used in commit footer + log lines
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

# ── arg parsing ──────────────────────────────────────────────────────────────
: "${PUSH_PATHS:?PUSH_PATHS is required (CLAUDE.md rule #6: NEVER git add -A)}"
: "${PUSH_SUBJECT:?PUSH_SUBJECT is required}"

PUSH_BODY="${PUSH_BODY:-}"
PUSH_REFUSE_DIRTY="${PUSH_REFUSE_DIRTY:-}"
PUSH_SESSION_TAG="${PUSH_SESSION_TAG:-session}"
PUSH_DRY_RUN="${PUSH_DRY_RUN:-0}"

DRY=""
[ "$PUSH_DRY_RUN" = "1" ] && DRY=" (DRY RUN)"

echo "▸ push_session$PUSH_SESSION_TAG$DRY — $(date -u +%Y-%m-%dT%H:%M:%SZ)"

# ── clear stranded sandbox lock (harmless if none) ───────────────────────────
echo "▸ clear any stranded sandbox lock"
rm -f "$(git rev-parse --git-dir)/index.lock" 2>/dev/null || true

# ── preflight: app must IMPORT + BOOT (only gate that protects prod) ─────────
echo "▸ preflight"
if ! bash scripts/preflight.sh; then
  echo "🔴 preflight FAILED — fix before push"
  exit 1
fi

# ── sanity: refuse if files I do NOT own are dirty or staged ────────────────
if [ -n "$PUSH_REFUSE_DIRTY" ]; then
  echo "▸ refuse-dirty check: ${PUSH_REFUSE_DIRTY// /, }"
  for f in $PUSH_REFUSE_DIRTY; do
    # dirty = either unstaged-change OR staged
    if ! git diff --quiet -- "$f" 2>/dev/null \
       || ! git diff --cached --quiet -- "$f" 2>/dev/null; then
      echo "🔴 $f is dirty/staged — I do NOT own it."
      echo "   Either unstage:  git restore --staged -- $f"
      echo "   Or remove from PUSH_REFUSE_DIRTY if you DO own it."
      echo "   Or accept that the OTHER lane will commit it themselves."
      exit 1
    fi
  done
fi

# ── sanity: every PUSH_PATHS file should be dirty (warn if not) ──────────────
echo "▸ paths-to-stage check"
DIRTY=$(git status --porcelain | awk '{print $2}')
for f in $PUSH_PATHS; do
  if [ ! -f "$f" ] && [ ! -d "$f" ]; then
    echo "🔴 $f does not exist — refusing"
    exit 1
  fi
  if ! echo "$DIRTY" | grep -qxF "$f"; then
    echo "  ⚠️  $f is in PUSH_PATHS but not dirty — did you save?"
  fi
done

# ── stage explicit paths (NEVER -A) ─────────────────────────────────────────
echo "▸ stage explicit paths"
echo "$PUSH_PATHS" | tr ' ' '\n' | xargs git add

# ── check for OTHER unstaged changes after staging (mixed-hunks case) ──────
# porcelain format: " M file" = unstaged, "M  file" = staged, "??" = untracked.
# After `git add PUSH_PATHS`, anything still in porcelain is NOT staged by me.
OTHER_DIRTY=$(git status --porcelain | awk '$1 == "??" || $1 ~ /^ ?M$/ {print $2}' || true)
if [ -n "$OTHER_DIRTY" ]; then
  echo ""
  echo "⚠️  OTHER unstaged changes remain after my staging:"
  echo "$OTHER_DIRTY" | sed 's/^/    /'
  echo ""
  echo "These are likely mixed-hunk files (my hunks + another session's hunks)."
  echo "Per CLAUDE.md rule #6 I will NOT 'git add -A' them."
  echo "If you want them in THIS commit, run:"
  echo "    git add -p <file>            # stage ONLY your hunks"
  echo "    bash scripts/push_session.sh # re-run"
  echo "Otherwise they wait for their own commit."
  echo ""
  if [ "$PUSH_DRY_RUN" = "1" ]; then exit 0; fi
  read -r -p "Continue? [y/N] " ans
  case "$ans" in y|Y|yes|YES) ;; *) echo "aborted"; exit 1 ;; esac
fi

# ── commit ──────────────────────────────────────────────────────────────────
echo "▸ commit"
COMMIT_MSG="$PUSH_SUBJECT"
if [ -n "$PUSH_BODY" ]; then
  COMMIT_MSG="$PUSH_SUBJECT

$PUSH_BODY"
fi
COMMIT_MSG="$COMMIT_MSG

ledger: REFUTATION_LEDGER.md $PUSH_SESSION_TAG"

if [ "$PUSH_DRY_RUN" = "1" ]; then
  echo "── DRY RUN — would commit with message: ──"
  echo "$COMMIT_MSG"
  echo "── end ──"
  exit 0
fi

git commit -m "$COMMIT_MSG"

# ── push (Railway auto-deploys on push) ────────────────────────────────────
echo "▸ push"
git push origin main

echo "✅ pushed: $PUSH_SUBJECT"