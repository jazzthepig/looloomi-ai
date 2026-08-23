#!/usr/bin/env bash
# run_strategy_3_and_4_backtests.sh — Mac-side one-command runner
#
# Executes the two forward-committed paper-book backtests on REAL DATA and
# surfaces per-strategy verdicts. Single source for the "money-making" call
# for Strategy 3 (Pod Aggregator) and Strategy 4 (Cross-Asset Factor Tilt).
#
# The synthetic verdicts (sandbox) are NOT authoritative — this script
# loads /Volumes/CometCloudAI/cometcloud-local/_data/cis_history/ and
# /Volumes/CometCloudAI/data/ohlcv/ for crypto, EODHD cache for TradFi.
#
# Per §STRATEGY-DISCIPLINE, neither strategy ships unless ALL of:
#   (1) cause documented       → STRATEGY_PLAYBOOK.md §Strategy 3 / §Strategy 4
#   (2) oos_survival=True      → verdict.FUSION_LIFT on real data below
#   (3) ≥60d paper trade       → starts AFTER push + Railway mark today
#   (4) regime-conditional     → wired in both NAV endpoints
#
# Output:
#   /tmp/cometcloud_reports/POD_AGGREGATOR_<DATE>.md
#   /tmp/cometcloud_reports/CROSS_ASSET_FACTOR_TILT_<DATE>.md
#   stdout: verdicts + frozen-cell proposals for STRATEGY_PLAYBOOK fill-in

set -euo pipefail

cd "$(dirname "$0")/.."

REPO_ROOT="$(pwd)"
DATE="$(date +%Y-%m-%d)"

PYTHONPATH="$REPO_ROOT:${PYTHONPATH:-}"
export PYTHONPATH

echo "════════════════════════════════════════════════════════════════════════"
echo "  CometCloud — Strategy 3 + Strategy 4 real-data backtests"
echo "  Date:      $DATE"
echo "  Repo:      $REPO_ROOT"
echo "  Py:        $(python3 --version)"
echo "════════════════════════════════════════════════════════════════════════"

mkdir -p /tmp/cometcloud_reports

# ── preflight check: are data volumes mounted? ─────────────────────────────────
if [ ! -d "/Volumes/CometCloudAI/cometcloud-local/_data/cis_history" ]; then
    echo ""
    echo "  ⚠️  /Volumes/CometCloudAI/cometcloud-local/_data/cis_history NOT MOUNTED"
    echo "  Strategy 3 + 4 both require real CIS history data."
    echo "  Mount the CometCloudAI volume first; rerun this script."
    echo ""
    exit 1
fi
if [ ! -d "/Volumes/CometCloudAI/data/ohlcv" ]; then
    echo ""
    echo "  ⚠️  /Volumes/CometCloudAI/data/ohlcv NOT MOUNTED"
    echo "  Strategy 4 (cross-asset) requires real OHLCV panel."
    echo "  Mount the CometCloudAI volume first; rerun this script."
    echo ""
    exit 1
fi

echo ""
echo "  ✓ Volumes mounted"

# ── Strategy 3 — Pod Aggregator ───────────────────────────────────────────────
echo ""
echo "────────────────────────────────────────────────────────────────────────"
echo "  Strategy 3 — Pod Aggregator (Millennium 风格)"
echo "────────────────────────────────────────────────────────────────────────"
S3_OUT="/tmp/cometcloud_reports/POD_AGGREGATOR_${DATE}.md"
if python3 -m src.research.validation.pod_aggregator \
        --output-dir /tmp/cometcloud_reports \
        2>&1 | tee /tmp/cometcloud_reports/pod_aggregator_stdout.log
then
    S3_VERDICT=$(grep -E "^## Decision" /tmp/cometcloud_reports/POD_AGGREGATOR_*${DATE}*.md 2>/dev/null \
                 | head -1 | awk '{print $NF}' || echo "UNKNOWN")
    echo ""
    echo "  Strategy 3 verdict: $S3_VERDICT"
else
    echo ""
    echo "  ⚠️  Strategy 3 backtest FAILED — see /tmp/cometcloud_reports/pod_aggregator_stdout.log"
    S3_VERDICT="FAILED"
fi

# ── Strategy 4 — Cross-Asset Factor Tilt ──────────────────────────────────────
echo ""
echo "────────────────────────────────────────────────────────────────────────"
echo "  Strategy 4 — Cross-Asset Factor Tilt (AQR 风格)"
echo "────────────────────────────────────────────────────────────────────────"
S4_OUT="/tmp/cometcloud_reports/CROSS_ASSET_FACTOR_TILT_${DATE}.md"
if python3 -m src.research.validation.cross_asset_factor_tilt \
        --output-dir /tmp/cometcloud_reports \
        2>&1 | tee /tmp/cometcloud_reports/cross_asset_factor_tilt_stdout.log
then
    S4_VERDICT=$(grep -E "^## Decision" /tmp/cometcloud_reports/CROSS_ASSET_FACTOR_TILT_*${DATE}*.md 2>/dev/null \
                 | head -1 | awk '{print $NF}' || echo "UNKNOWN")
    echo ""
    echo "  Strategy 4 verdict: $S4_VERDICT"
else
    echo ""
    echo "  ⚠️  Strategy 4 backtest FAILED — see /tmp/cometcloud_reports/cross_asset_factor_tilt_stdout.log"
    S4_VERDICT="FAILED"
fi

# ── Strategy 4 sweep fallback (only if default failed OOS) ────────────────────
if [ "$S4_VERDICT" = "NEUTRAL" ] || [ "$S4_VERDICT" = "REFUTED" ]; then
    echo ""
    echo "────────────────────────────────────────────────────────────────────────"
    echo "  Strategy 4 default failed — running parameter sweep on REAL data"
    echo "────────────────────────────────────────────────────────────────────────"
    if python3 -m src.research.validation.cross_asset_factor_tilt \
            --sweep --output-dir /tmp/cometcloud_reports \
            2>&1 | tee /tmp/cometcloud_reports/strategy4_sweep_stdout.log
    then
        echo ""
        echo "  ✓ Sweep complete — see /tmp/cometcloud_reports/CROSS_ASSET_FACTOR_TILT_${DATE}_SWEEP.md"
    else
        echo "  ⚠️  Sweep FAILED — see /tmp/cometcloud_reports/strategy4_sweep_stdout.log"
    fi
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "════════════════════════════════════════════════════════════════════════"
echo "  Summary"
echo "════════════════════════════════════════════════════════════════════════"
echo ""
echo "  Strategy 3 (Pod Aggregator):          $S3_VERDICT"
echo "  Strategy 4 (Cross-Asset Factor Tilt): $S4_VERDICT"
echo ""
echo "  Per §STRATEGY-DISCIPLINE:"
echo "    FUSION_LIFT  → ships to forward paper once pushed + Railway marks"
echo "    NEUTRAL      → hold for next attempt; sweep may surface a config"
echo "    REFUTED      → close the strategy; do not push"
echo ""
echo "  Reports:"
echo "    $S3_OUT"
echo "    $S4_OUT"
echo ""
echo "  Next step: paste the verdict line + frozen-cell metrics into"
echo "  STRATEGY_PLAYBOOK.md §Strategy 3 / §Strategy 4."
echo "════════════════════════════════════════════════════════════════════════"