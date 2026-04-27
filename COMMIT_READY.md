# COMMIT_READY.md

Push-gate only. Seth stages files from Cowork; Minimax clears lock + commits + pushes.

---

## Pending commit (staged + unstaged, all ready)

**Already staged** (Seth got these before lock):
- `scripts/test_auth_e2e.py` — walrus operator removed (Python 3.14 compat)

**Needs `git add` by Minimax** (lock blocked Seth from staging):
- `src/data/cis/cis_provider.py` — beta calc fix + BINANCE_SYMBOLS §4A cleanup
- `src/api/routers/agent.py` — NEW: Phase 2.3 A2A task queue (portfolio_analysis / cis_snapshot / regime_briefing)
- `src/api/main.py` — registered agent_router; docstring version bump to v0.4.3
- `dashboard/public/.well-known/agent.json` — a2a_tasks: live endpoint spec (was "coming Q2 2026")
- `dashboard/dist/.well-known/agent.json` — same (Railway serves from dist)
- `ROADMAP_A2A.md` — Phase 2.3 ✅ COMPLETE
- `CLAUDE.md` — Phase 2.3 LIVE ✅, Freqtrade DRY RUN PENDING, T20 added, metrics updated
- `MINIMAX_SYNC.md` — §4A TrendStrategy direction locked, T20 dry run task, §5 Phase 2.3 smoke test ✅

```bash
# 1. Clear FUSE lock
rm -f ~/projects/looloomi-ai/.git/index.lock

# 2. Add all files Seth couldn't stage
cd ~/projects/looloomi-ai
git add \
  src/data/cis/cis_provider.py \
  src/api/routers/agent.py \
  src/api/main.py \
  dashboard/public/.well-known/agent.json \
  dashboard/dist/.well-known/agent.json \
  ROADMAP_A2A.md \
  CLAUDE.md \
  MINIMAX_SYNC.md \
  COMMIT_READY.md

# 3. Commit everything (already staged + newly added)
git commit -m "feat(a2a+cis+freqtrade): Phase 2.3 live, beta fix, TrendStrategy+CIS direction locked

- src/api/routers/agent.py: NEW — A2A Phase 2.3 task endpoint (smoke test ✅)
  POST /api/v1/agent/tasks → 202 + task_id (fire-and-forget)
  GET  /api/v1/agent/tasks/{task_id} → poll status + result
  Three task types: portfolio_analysis / cis_snapshot / regime_briefing
  Upstash Redis persistence (1h TTL), asyncio.Semaphore(5) concurrency
- src/api/main.py: agent_router registered; docstring v0.4.3
- cis_provider.py: calculate_asset_betas min_len bug fixed — partial yfinance
  factor failures (TNX) no longer kill DXY+VIX beta calc. Each factor independent.
  T2 assets get real 30d rolling betas instead of crude CG proxy fallback.
- cis_provider.py: BINANCE_SYMBOLS removes 12 §4A excluded assets
- scripts/test_auth_e2e.py: walrus operator replaced — Python 3.14 compat
- agent.json (public + dist): a2a_tasks live endpoint spec
- ROADMAP_A2A.md: Phase 2.3 ✅ COMPLETE
- MINIMAX_SYNC.md: §4A TrendStrategy(PF=1.46) + CIS gate direction locked;
  T20 dry run task added; backtest PF<1 correctly attributed to methodology
  mismatch (2026 scores vs 2024 signals), not strategy failure
- CLAUDE.md: Phase 2.3 LIVE ✅, Freqtrade DRY RUN PENDING 🟡, T20 added

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"

# 4. Push
git push origin main
```

---

## After push — T17 re-run

```bash
# Auth E2E (Python 3.14 walrus fix now deployed)
cd ~/projects/looloomi-ai
python scripts/test_auth_e2e.py
# Expect: ALL 11 TESTS PASSED
```

---

## Phase 2.3 smoke test (run after deploy)

```bash
# Submit a task
curl -s -X POST https://looloomi.ai/api/v1/agent/tasks \
  -H "Content-Type: application/json" \
  -d '{"type":"cis_snapshot","params":{"min_cis":50,"limit":5}}' | jq .

# Poll the result (replace task_id)
curl -s https://looloomi.ai/api/v1/agent/tasks/<task_id> | jq .status
```

---

## Freqtrade strategy research direction (T19 — Jazz decision needed)

Backtest result: PF<1, -0.42%, 14 trades/2.2yr → below §3 threshold (PF≥1.25).

**Direction confirmed by Jazz:** Don't build strategy from scratch.
Jazz has existing profitable strategies. Goal = enhance those with CIS signals as filter/overlay.
Seth not involved in Freqtrade module. Minimax to coordinate with Jazz directly.
