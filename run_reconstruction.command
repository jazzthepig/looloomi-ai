#!/bin/bash
# CIS Historical Reconstruction — double-click to run
# Or: bash run_reconstruction.command
cd "$(dirname "$0")"

export SUPABASE_URL="https://soupjamxlfsmgmmtoeok.supabase.co"
export SUPABASE_KEY="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InNvdXBqYW14bGZzbWdtbXRvZW9rIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzM3MzMzNjUsImV4cCI6MjA4OTMwOTM2NX0.zvdKO2Obwpb3xIyt7OWzisE9B-W8hAPjOT2zO35vC4I"
export COINGECKO_API_KEY="CG-Rv47zv5eFuL2N9DXunbEQsrK"

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
