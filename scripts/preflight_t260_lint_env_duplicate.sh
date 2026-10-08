#!/bin/bash
# preflight_t260_lint_env_duplicate.sh
# T-036 lint: Mac env canonical = /Volumes/CometCloudAI/cometcloud-local/.env
# any second env file → fail (designed for §Seth-1006e acceptance "1 个文件")
#
# Per §Seth-1006g T-036 裁定: lane-c DELIVERS this lint; the rm of any
# duplicate is **JAZZ's action, not lane's** ("key 文件只经 Jazz 的手,lane
# 不删也不读值"). This script READS NO VALUES — it only `cmp -s` byte-compare
# and emits warnings/failures. The Action text below points at Jazz.
#
# Exit codes:
#   0 = canonical-only (no duplicate detected)
#   1 = duplicate detected, identical bytes → WARN (JAZZ should rm)
#   2 = duplicate detected, drift from canonical → FAIL (09-28 漏改 pattern)
#   3 = canonical missing (catastrophic, lane should not silently fix)

set -u
CANONICAL="/Volumes/CometCloudAI/cometcloud-local/.env"
ORPHAN_DIR="/Users/sbb/.config/cometcloud"
ORPHAN_PATH="${ORPHAN_DIR}/.env"

# 1. canonical exists?
if [ ! -f "$CANONICAL" ]; then
    echo "🔴 FAIL: canonical Mac env missing: $CANONICAL"
    exit 3
fi

# 2. orphan path exists?
if [ ! -e "$ORPHAN_PATH" ]; then
    echo "✓ Mac env lint PASS: only canonical $CANONICAL (no duplicate at $ORPHAN_PATH)"
    exit 0
fi

# 3. duplicate exists — compare bytes ONLY (no value read)
if cmp -s "$CANONICAL" "$ORPHAN_PATH"; then
    cat <<EOF
⚠ WARN: orphan Mac env at $ORPHAN_PATH is byte-identical to canonical.
   Production impact = 0 (no script reads the orphan path).
   But the design future is "1 file only" (per §Seth-1006e).
   **Action: JAZZ rm's $ORPHAN_PATH** (per §Seth-1006g T-036 裁定, lane 不删).
EOF
    exit 1
else
    cat <<EOF
🔴 FAIL: orphan Mac env at $ORPHAN_PATH differs from canonical (byte drift).
   This is exactly the 09-28 漏改 incident pattern.
EOF
    diff "$CANONICAL" "$ORPHAN_PATH" || true
    cat <<EOF
   **Action: JAZZ decides source of truth, reconciles, and rm's
   $ORPHAN_PATH (the orphan, per §Seth-1006g).** Lane does not delete.
EOF
    exit 2
fi
