#!/usr/bin/env bash
# T-085 7-day sweep cron entry — fire at UTC 00:00 / 08:00 / 16:00 daily.
#
# Each invocation picks the slot the script is being run in (≤ current UTC hour).
# The sweep_7d.py inside skips duplicate-write within 6h so double-fires are safe.
#
# Cron line (lane-c responsibility — installs into lane-bot scheduler per §Seth-1013b):
#   0 0,8,16 * * * /Volumes/CometCloudAI/cometcloud-local/research/t085/sweep_7d_runner.sh >> /Volumes/CometCloudAI/cometcloud-local/_logs/t085_sweep.log 2>&1
#
# After 7 days: run aggregate_7d.py to produce t085_report_7d_<ts>.json
set -euo pipefail
cd "$(dirname "$0")"
date -u
python3 sweep_7d.py
echo "---"
