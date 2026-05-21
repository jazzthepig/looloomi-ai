#!/bin/bash
# Resolve script's own directory robustly (works when double-clicked from Finder)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || { echo "ERROR: cannot cd to $SCRIPT_DIR"; read -n1; exit 1; }
echo "Working in: $SCRIPT_DIR"

echo "=== Removing git locks if present ==="
rm -f .git/index.lock .git/HEAD.lock .git/index_tmp.lock

echo "=== Staging — UX readability pass ==="
git add dashboard/src/App.jsx
git add dashboard/src/analytics.jsx
git add dashboard/src/components/QuantMonitor.jsx
git add dashboard/src/components/MacroPulse.jsx
git add dashboard/src/components/PortfolioAllocation.jsx
git add dashboard/src/components/CISLeaderboard.jsx
git add dashboard/src/components/IntelligencePage.jsx
git add dashboard/src/components/ProtocolIntelligence.jsx
git add dashboard/src/components/VaultPage.jsx
git add dashboard/src/components/StrategiesPage.jsx

echo "=== Staging — Multi-Factor Strategies ==="
git add src/api/routers/strategies.py
git add src/api/main.py
git add dashboard/src/components/MultiFactorStrategies.jsx
git add strategies/BreakoutStrategy.py
git add strategies/ValueOnChainStrategy.py
git add MINIMAX_SYNC.md

echo "=== Staging — VC rounds + data_layer fix ==="
git add src/data/market/data_layer.py
git add dashboard/src/components/IntelligencePage.jsx
git add dashboard/dist/

echo "=== Committing ==="
git commit -m "fix: VC rounds + events data_layer + frontend empty state

Backend:
  - data_layer.py _get_llama_client(): add User-Agent + Accept headers
    (Cloudflare was blocking bare httpx on Railway → 403 → empty VC data)
  - get_vc_raises(): 403 detection returns stale cache not empty list;
    key variation handling (raises / data / fundraises); HTTP status logging

Frontend:
  - IntelligencePage.jsx: remove (loading || raises.length > 0) guard —
    VC Funding Rounds card always renders; empty state with Retry button
    shown when DeFiLlama returns 0 results

Also includes (from prior wave):
  - Multi-Factor Strategies: strategies router + MultiFactorStrategies.jsx
    + BreakoutStrategy.py + ValueOnChainStrategy.py + MINIMAX_SYNC.md §9
  - Readability sweep: all 7px fonts → 9px+ across 7 components
  - SectionLoader label prop; analytics AbortController 20s timeout

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>" || echo "(nothing new to commit, pushing existing commits)"

echo "=== Pushing ==="
git push origin main

echo ""
echo "=== REMINDER: Run scripts/supabase_all_tables.sql in Supabase dashboard ==="
echo ""
echo "=== MINIMAX ACTION REQUIRED ==="
echo "=== §9: Copy strategies/BreakoutStrategy.py + strategies/ValueOnChainStrategy.py"
echo "===      to Freqtrade user_data/strategies/ and start dry runs"
echo "=== §8: Add check_and_run_discovery() to cis_scheduler.py (still pending)"
echo ""
echo "=== Done. Railway auto-deploys in ~2min. Press any key to close ==="
read -n1
