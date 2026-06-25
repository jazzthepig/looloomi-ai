#!/bin/bash
# CIS Historical Reconstruction — double-click to run
# Or: bash run_reconstruction.command
cd "$(dirname "$0")"

# URL is public — keep hardcoded (matches SUPABASE_SETUP.md)
export SUPABASE_URL="https://soupjamxlfsmgmmtoeok.supabase.co"

# Key: NEVER hardcode the anon key in this file (was: eyJ...anon JWT).
# Reads from env: prefer SUPABASE_SERVICE_KEY (backend writes, bypasses RLS),
# fallback SUPABASE_KEY (anon — read-only by design).
# Source your .env file before running, or set in your shell.
if [ -f "$(dirname "$0")/.env" ]; then
  set -a; source "$(dirname "$0")/.env"; set +a
fi
export SUPABASE_KEY="${SUPABASE_KEY:-${SUPABASE_SERVICE_KEY:-}}"
if [ -z "$SUPABASE_KEY" ]; then
  echo "ERROR: SUPABASE_KEY or SUPABASE_SERVICE_KEY must be set."
  echo "Add it to your .env (gitignored) or export in your shell."
  exit 1
fi

export COINGECKO_API_KEY="${COINGECKO_API_KEY:-CG-Rv47zv5eFuL2N9DXunbEQsrK}"

echo "=============================="
echo "  CIS Historical Reconstruction"
echo "  365 days | ~40 min unattended"
echo "=============================="
echo ""

# Dry-run first (3 symbols, no writes)
echo "[1/2] Dry-run on BTC, ETH, SOL..."
python3 scripts/reconstruct_cis_history.py --dry-run --symbols BTC --days 7
echo ""

read -p "Dry-run OK? Press Enter to start full 365d reconstruction, Ctrl-C to abort..."
echo ""

echo "[2/2] Starting full reconstruction (resume-safe, ~40 min)..."
python3 scripts/reconstruct_cis_history.py --resume
echo ""
echo "Done. Check Supabase cis_scores for historical_reconstruction rows."
read -p "Press any key to close..."
