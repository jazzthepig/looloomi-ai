#!/bin/bash
# Resolve script's own directory robustly (works when double-clicked from Finder)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || { echo "ERROR: cannot cd to $SCRIPT_DIR"; read -n1; exit 1; }
echo "Working in: $SCRIPT_DIR"

echo "=== Removing git locks if present ==="
for f in .git/index.lock .git/HEAD.lock; do [ -f "$f" ] && mv "$f" "$f.old" 2>/dev/null; done

echo "=== Pushing all local commits ==="
git push origin main

echo ""
echo "=== Commits being pushed ==="
git log origin/main..HEAD --oneline 2>/dev/null || git log -4 --oneline

echo ""
echo "=== REQUIRED: Run scripts/supabase_all_tables.sql in Supabase dashboard ==="
echo "===  → Creates signal_journal table (idempotent, safe to re-run)"
echo "===  → URL: https://supabase.com/dashboard/project/soupjamxlfsmgmmtoeok/sql/new"
echo ""
echo "=== AFTER DEPLOY: Signal track record starts automatically ==="
echo "===  → Next Mac Mini push logs OUTPERFORM assets to signal_journal"
echo "===  → /api/v1/signals/performance computes Sharpe/Sortino/CAGR live"
echo "===  → Quant Monitor → Signal Performance tab shows real metrics"
echo ""
echo "=== Railway auto-deploys in ~2min. Press any key to close ==="
read -n1
