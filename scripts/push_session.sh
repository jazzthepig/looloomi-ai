#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# push_session.sh — MAC-SIDE deploy for the 2026-07-17 session.
# Run from the repo root on the Mac (NOT the Cowork sandbox — git write-commands
# only work Mac-side; the sandbox FUSE mount denies unlink and strands .git locks).
#
#   bash scripts/push_session.sh
#
# What shipped this session:
#   · Signal feed v5 — tiered AI-narrative briefing (MiniMax over deterministic facts)
#   · Crowd Clock — behavioral-phase primitive + endpoint + dial (R24, candidate)
#   · Crowd-Phase Book — two-layer sizing switch (mean-reversion vs trend)
#   · Trader Tom doctrine (docs/TRADER_TOM_DOCTRINE.md) + §STRATEGY-REVIVE assignment
#   · CJK sweep — zero Chinese anywhere user/agent-facing
#   · Unified design foundation — one index.css (Syne + navy field) imported everywhere
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

echo "▸ clear any stranded sandbox lock (harmless if none)"
rm -f "$(git rev-parse --git-dir)/index.lock" 2>/dev/null || true

echo "▸ preflight — app must IMPORT + BOOT (the only gate that protects prod)"
bash scripts/preflight.sh

echo "▸ prune orphan dist chunks to a fixpoint (anything not reachable from the built HTML —"
echo "  old hashed bundles + their orphan-only preloaders, some carrying stale CJK)"
total=0
while :; do
  # reachable = the HTML entrypoints + everything the SURVIVING js/css still reference
  ref="$(cat dashboard/dist/*.html dashboard/dist/assets/*.js dashboard/dist/assets/*.css 2>/dev/null || true)"
  round=0
  for f in dashboard/dist/assets/*.js dashboard/dist/assets/*.css; do
    [ -e "$f" ] || continue
    b="$(basename "$f")"
    # a chunk never names itself, so if its basename appears anywhere in the html+js+css
    # graph it is referenced by SOMETHING reachable this round; otherwise it is an orphan.
    if ! printf '%s' "$ref" | grep -qF "$b"; then
      rm -f "$f" && round=$((round+1))
    fi
  done
  total=$((total+round))
  [ "$round" -eq 0 ] && break
done
echo "  pruned $total orphan chunk(s) to fixpoint"

echo "▸ sanity: zero CJK in the shipped dist"
if grep -rlP "[\x{4e00}-\x{9fff}]" dashboard/dist/assets/*.js dashboard/dist/assets/*.css dashboard/dist/*.html 2>/dev/null; then
  echo "  ⚠️  CJK still present in dist above — inspect before pushing"; exit 1
fi
echo "  clean ✓"

echo "▸ stage (Shadow/ is gitignored — never staged)"
git add -A

echo "▸ commit"
git commit -m "feat: signal-feed v5 AI narrative + Crowd Clock + Crowd-Phase book; \
fix: full CJK sweep + unified design foundation (single index.css, Syne + navy field)

- signals.py: v5 tiered narrative briefing, AI narrative overlay (MiniMax/LM Studio) over
  deterministic compliance-safe facts, cached to Redis; internal refresh/push endpoints
- crowd_clock.py + /api/v1/market/crowd-clock + CrowdClock.jsx: behavioral-phase primitive
  (candidate, R24), daily snapshot instrumented for validation (scripts/supabase_crowd_clock.sql)
- crowd_phase_book.py: phase-conditional two-layer sizing (mean-reversion vs trend), gross-capped
- docs/TRADER_TOM_DOCTRINE.md + CLAUDE.md: behavioral-edge doctrine, expectancy>win-rate,
  two-layer book, invariant-essence/variable-factors
- MINIMAX_SYNC.md §STRATEGY-REVIVE: verify+develop MultiFactorV2 + SwingOverlayV9 as two-layer book
- CJK: market.py (46 strings), cause_proximity/conviction/portfolio/dingge_rwa/weekly_report/
  quant json, RiskMeter/DinggeBoard/MacroPulse/SignalFeed/MobileApp, proof.html → English
- design: index.css is now the single source of truth (Syne/Exo2/JetBrains + navy field),
  imported by portfolio/analytics/quant entries (were falling back to system fonts)"

echo "▸ push (Railway auto-deploys on push)"
git push origin main

echo "✅ pushed. Railway will redeploy. After deploy, set Railway env if enabling AI narrative:"
echo "   NARRATIVE_LLM_BASE_URL / NARRATIVE_LLM_API_KEY / NARRATIVE_LLM_MODEL (MiniMax)"
echo "   and run scripts/supabase_crowd_clock.sql to create the crowd_clock_log table."
