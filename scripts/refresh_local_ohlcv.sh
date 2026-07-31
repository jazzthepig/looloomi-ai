#!/usr/bin/env bash
# Refresh the local OHLCV SQLite buffer (off-engine data source for research).
#
# Per Jazz 2026-07-26: do NOT push to Supabase. Local SQLite at
# /tmp/cometcloud_data/ohlcv.db is the off-engine data source. Refresh when
# buffer is stale (>7 days) before running cross-asset research.
#
# Usage:
#   bash scripts/refresh_local_ohlcv.sh                # full 58×365d (~60s)
#   DAYS=180 bash scripts/refresh_local_ohlcv.sh       # 180d window
#   ONLY=BTC,ETH,SPY bash scripts/refresh_local_ohlcv.sh  # subset
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DAYS="${DAYS:-365}"
ONLY="${ONLY:-}"

echo "================================================================"
echo "Local OHLCV refresh"
echo "  script:  scripts/fetch_ohlcv_to_local.py"
echo "  target:  /tmp/cometcloud_data/ohlcv.db"
echo "  days:    ${DAYS}"
echo "  only:    ${ONLY:-(all 58 symbols)}"
echo "  started: $(date -u +'%Y-%m-%d %H:%M:%S UTC')"
echo "================================================================"

ENV_ARGS=()
if [ -n "${DAYS}" ]; then ENV_ARGS+=("DAYS=${DAYS}"); fi
if [ -n "${ONLY}" ]; then ENV_ARGS+=("ONLY=${ONLY}"); fi

START_TS=$(date +%s)
env "${ENV_ARGS[@]}" python3 "${SCRIPT_DIR}/fetch_ohlcv_to_local.py"
END_TS=$(date +%s)

echo
echo "================================================================"
echo "✅ Done in $((END_TS - START_TS))s"
echo "  ended: $(date -u +'%Y-%m-%d %H:%M:%S UTC')"
echo "  next check: bash scripts/check_local_ohlcv.sh"
echo "================================================================"