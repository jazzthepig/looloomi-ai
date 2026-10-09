#!/bin/bash
# verify_rotation_alive.sh  (SKELETON — T-036 §7.2)
#
# Per §Seth-1006e acceptance:
#   "轮换后 1h 内 mac_mini 简报与 T1 推送都有新行"
#
# Usage:
#   bash scripts/verify_rotation_alive.sh <rotation_timestamp_unix>
#   bash scripts/verify_rotation_alive.sh "2026-10-15 14:30 UTC"
#
# Exit codes:
#   0 = both alive (mac_mini 简报 + T1 push 新行 in 1h)
#   1 = mac_mini 简报 stale
#   2 = T1 push stale
#   3 = both stale
#   4 = missing argument
#   5 = source files missing (preflight data not present) OR T1 push source unwired
#       (T-036 §Seth-1008o: until first real rotation test, T1 source emits
#       NOT_MEASURED and the script exits 5 — §7.2 cannot be auto-verified yet)
#
# ⚠ SKELETON — paths are placeholders. After T-036 shipped, fill in:
#   • actual mac_mini 简报 latest path (line ~30)
#   • actual T1 push source (Supabase table or Redis key, line ~45)
#
# Real test = wait for next INTERNAL_TOKEN rotation (per §Seth-1006e acceptance).

set -e
if [ "$#" -lt 1 ]; then
    echo "Usage: $0 <rotation_timestamp_unix|YYYY-MM-DD HH:MM TZ>"
    exit 4
fi

ROT_INPUT="$1"
# accept either unix ts or "YYYY-MM-DD HH:MM UTC"
if [[ "$ROT_INPUT" =~ ^[0-9]+$ ]]; then
    ROT_TS="$ROT_INPUT"
else
    ROT_TS=$(date -j -u -f "%Y-%m-%d %H:%M %Z" "$ROT_INPUT" "+%s" 2>/dev/null) || {
        echo "Bad timestamp format. Use unix seconds or 'YYYY-MM-DD HH:MM UTC'."
        exit 4
    }
fi
HORIZON_TS=$((ROT_TS + 3600))   # 1h window per acceptance
NOW_TS=$(date +%s)

echo "=== T-036 verify_rotation_alive (skeleton) ==="
echo "  rotation_ts = $ROT_TS ($(date -u -r "$ROT_TS" '+%Y-%m-%d %H:%M:%S UTC'))"
echo "  horizon_ts  = $HORIZON_TS ($(date -u -r "$HORIZON_TS" '+%Y-%m-%d %H:%M:%S UTC'))"
echo "  now_ts      = $NOW_TS ($(date -u -r "$NOW_TS" '+%Y-%m-%d %H:%M:%S UTC'))"
echo ""

# === 1. mac_mini 简报 ===
# SKELETON PLACEHOLDER — replace path after first real rotation test
MAC_BRIEF_PATH="/Volumes/CometCloudAI/cometcloud-local/_data/mac_mini/latest.md"
if [ ! -f "$MAC_BRIEF_PATH" ]; then
    echo "🔴 FAIL: mac_mini 简报 path missing: $MAC_BRIEF_PATH"
    echo "   SKELETON: implement after T-036 ship + first real rotation."
    exit 5
fi
LATEST_BRIEF_TS=$(stat -f %m "$MAC_BRIEF_PATH" 2>/dev/null || echo 0)
LATEST_BRIEF_HUMAN=$(date -u -r "$LATEST_BRIEF_TS" '+%Y-%m-%d %H:%M:%S UTC' 2>/dev/null || echo "n/a")
echo "[1] mac_mini 简报 last update: $LATEST_BRIEF_HUMAN ($LATEST_BRIEF_TS)"
if [ "$LATEST_BRIEF_TS" -lt "$ROT_TS" ]; then
    BRIEF_OK=0
    echo "    ✗ STALE: pre-rotation ($LATEST_BRIEF_TS < $ROT_TS)"
else
    BRIEF_OK=1
    echo "    ✓ ALIVE post-rotation"
fi
echo ""

# === 2. T1 push ===
# SKELETON PLACEHOLDER — wire to actual T1 source
# Option candidates per probe (settle ~1):
#   a) Supabase table `cis_scores` latest `updated_at`
#   b) Redis bridge `cis:local_scores` last write
#   c) Mac local log file mtime
#   → choose after first real rotation test
#
# Per §Seth-1008o: T1_TS source not wired yet — emit NOT_MEASURED + exit 5.
# After first real rotation test, replace `T1_TS=""` block with real probe
# (Supabase / Redis / mtime) and remove the `exit 5`.
T1_TS=""
T1_HUMAN="NOT_MEASURED"
echo "[2] T1 push last write: $T1_HUMAN (T1 source unwired — §Seth-1008o)"
echo "    ⚠ NOT_MEASURED: wire T1 source after first real rotation test, then"
echo "      remove this guard. Until then, §7.2 cannot be auto-verified."
exit 5
echo ""

# === Verdict ===
if [ "$BRIEF_OK" = "1" ] && [ "$PUSH_OK" = "1" ]; then
    echo "✓ T-036 §7.2 PASS: mac_mini 简报 + T1 push 都 1h 内有新行"
    exit 0
elif [ "$BRIEF_OK" = "0" ] && [ "$PUSH_OK" = "0" ]; then
    echo "🔴 T-036 §7.2 FAIL: mac_mini 简报 + T1 push 都没新行(rotation可能破坏了凭证)"
    exit 3
elif [ "$BRIEF_OK" = "0" ]; then
    echo "✗ T-036 §7.2 FAIL: mac_mini 简报 stale"
    exit 1
else
    echo "✗ T-036 §7.2 FAIL: T1 push stale"
    exit 2
fi
