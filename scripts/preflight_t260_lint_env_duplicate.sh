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
#   1 = duplicate detected, identical bytes, NO launchd wrapper reads it
#       → WARN (safe for JAZZ to rm orphan)
#   2 = duplicate detected, byte DRIFT from canonical → FAIL (09-28 漏改 pattern)
#   3 = canonical missing (catastrophic, lane should not silently fix)
#   6 = duplicate detected, identical bytes, BUT ≥1 launchd wrapper sources it
#       → WARN (JAZZ must change wrapper source path BEFORE rm orphan;
#       otherwise cg_news_listener + ohlcv.collector will 401 / abort)
#       — per T-036 2026-10-09 round-2 lane-c finding

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
    # 3a. identical bytes — check whether any launchd wrapper still sources it.
    # T-036 2026-10-09 round-2 finding: _launchd_run_cg_news_listener.sh L17
    # + _launchd_run_ohlcv.sh L9 both `source ~/.config/cometcloud/.env`
    # (Seth 2026-09-24 directive). If JAZZ rm's the orphan without first
    # rewriting those wrapper lines, both launchd-managed processes will
    # 401 / abort (ohlcv 静默失败; cg_news 显式 abort 写 stderr).
    # We scan `~/Library/LaunchAgents/_launchd_run_*.sh` for any line
    # referencing the orphan path (no value read, pattern-only).
    WRAPPER_READERS=""
    WRAPPER_RC=0
    if [ -d "$HOME/Library/LaunchAgents" ]; then
        # $(...) is a subshell: grep exit-1 (no match) does NOT abort the
        # parent. Capture and discard if no match.
        WRAPPER_READERS=$(grep -lE '(source|\.)[[:space:]]+"?~/\.config/cometcloud/\.env"?' \
            "$HOME"/Library/LaunchAgents/_launchd_run_*.sh 2>/dev/null) || WRAPPER_RC=$?
        if [ "$WRAPPER_RC" -ne 0 ]; then
            WRAPPER_READERS=""
        fi
    fi
    if [ -n "$WRAPPER_READERS" ]; then
        cat <<EOF
⚠ WARN: orphan Mac env at $ORPHAN_PATH is byte-identical to canonical,
   but the following launchd wrappers still source it:
$WRAPPER_READERS

   If JAZZ rm's the orphan NOW without rewriting these wrappers first,
   cg_news_listener + ohlcv.collector will 401 / abort (recreates the
   09-28 S-435 漏改 incident).

   **Action: JAZZ must FIRST change wrapper source path to canonical**
   (e.g. /Volumes/CometCloudAI/cometcloud-local/.env), THEN rm the orphan.
   Lane cannot edit ~/Library/LaunchAgents/ (outside allowed_paths).
EOF
        exit 6
    fi
    cat <<EOF
⚠ WARN: orphan Mac env at $ORPHAN_PATH is byte-identical to canonical.
   No launchd wrapper reads it → safe for JAZZ to rm.
   Design future is "1 file only" (per §Seth-1006e).
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
