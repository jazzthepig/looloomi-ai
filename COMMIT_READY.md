# COMMIT_READY.md

Push-gate only. Seth stages files from Cowork; Minimax clears lock + commits + pushes.

---

## Pending commit (staged + unstaged, all ready)

**Already staged** (Seth got these before lock):
- `scripts/test_auth_e2e.py` — walrus operator removed (Python 3.14 compat)

**Needs `git add` by Minimax** (lock blocked Seth from staging):
- `src/data/cis/cis_provider.py` — beta calc fix + BINANCE_SYMBOLS §4A cleanup
- `src/api/routers/agent.py` — Phase 2.3 A2A task queue + bug fixes (try-except, Redis logging, exc_info, division guard)
- `src/api/main.py` — agent_router registered; llms.txt discoverability headers; docstring v0.4.3
- `dashboard/src/components/ScoreAnalytics.jsx` — VITE_API_BASE → VITE_API_URL (was wrong env var)
- `dashboard/public/.well-known/agent.json` — a2a_tasks: live endpoint spec (was "coming Q2 2026")
- `dashboard/dist/.well-known/agent.json` — same (Railway serves from dist)
- `dashboard/public/llms.txt` — NEW: LLM crawler discoverability doc (844K+ site standard)
- `dashboard/dist/llms.txt` — NEW: same, Railway-served copy
- `glama.json` — NEW: repo root, required for Glama.ai auto-index (17,200+ servers)
- `src/mcp/cometcloud_mcp.py` — assertive descriptions on 5 tools (7.5x invocation multiplier)
- `ROADMAP_A2A.md` — Phase 2.3 ✅ COMPLETE
- `CLAUDE.md` — Phase 2.3 LIVE ✅, Freqtrade DRY RUN PENDING, T20 added, metrics updated
- `MINIMAX_SYNC.md` — §4A TrendStrategy direction locked, T20 dry run task, §5 Phase 2.3 smoke test ✅
- `ATTACK_PLAN.md` — NEW: Week 3+ execution plan (Apr 28–May 4)
- `WEEKLY_REVIEW.md` — NEW: weekly strategy review ritual + first entry (2026-04-27)
- `CLAUDE.md` — weekly review section added (cadence, structure, adversarial lenses)
- `examples/GETTING_STARTED.md` — NEW: Agent onboarding guide (Claude Desktop / Cursor / REST / Python)
- `examples/claude-desktop-config.json` — NEW: Drop-in Claude Desktop MCP config
- `examples/cursor-mcp.json` — NEW: Drop-in Cursor MCP config
- `examples/agent_example.py` — NEW: Full Python agent workflow (macro → CIS → signals → A2A task)
- `src/api/routers/cis.py` — NEW: GET /api/v1/cis/history/{symbol} + GET /api/v1/cis/trend/{symbol} (Redis-cached, Supabase-backed)
- `src/api/routers/factory.py` — Solana mock gate: _SOLANA_READY flag, public GETs return 503 when not live
- `dashboard/public/privacy.html` + `dashboard/dist/privacy.html` — NEW: privacy policy (required for Anthropic Connectors Directory)
- `MINIMAX_SYNC.md` — §6 added: T21 (health alert), T22 (MacroBrief fix), T23 (Freqtrade dry run)
- `JAZZ_TODAY.md` — NEW: Apr 27-28 action brief (hackathon + demo + Product Hunt + registries)

```bash
# 1. Clear FUSE lock
rm -f ~/projects/looloomi-ai/.git/index.lock

# 2. Add all files Seth couldn't stage
cd ~/projects/looloomi-ai
git add \
  src/data/cis/cis_provider.py \
  src/api/routers/agent.py \
  src/api/main.py \
  dashboard/src/components/ScoreAnalytics.jsx \
  dashboard/public/.well-known/agent.json \
  dashboard/dist/.well-known/agent.json \
  dashboard/public/llms.txt \
  dashboard/dist/llms.txt \
  glama.json \
  src/mcp/cometcloud_mcp.py \
  examples/GETTING_STARTED.md \
  examples/claude-desktop-config.json \
  examples/cursor-mcp.json \
  examples/agent_example.py \
  ROADMAP_A2A.md \
  CLAUDE.md \
  MINIMAX_SYNC.md \
  ATTACK_PLAN.md \
  COMMIT_READY.md

# 3. Commit everything (already staged + newly added)
git commit -m "feat(a2a+mcp+playbook): Phase 2.3 live, agent.py hardened, llms.txt + glama.json, assertive MCP descriptions

A2A / API:
- src/api/routers/agent.py: Phase 2.3 A2A task queue (smoke test ✅)
  POST /api/v1/agent/tasks → 202 + task_id; GET to poll
  BUG FIX: top-level try-except in _run_task (tasks can no longer stay pending forever)
  BUG FIX: Redis SET/GET now log warnings instead of silent swallow
  BUG FIX: _save_task logs when Redis persist fails (task is in-memory only)
  BUG FIX: all 3 executor error logs now include exc_info=True (stack traces in Railway)
  BUG FIX: 1/len(selected) → 1/max(len(selected),1) division edge case guard
- src/api/main.py: agent_router registered; Link+X-Llms-Txt discoverability headers; v0.4.3
- cis_provider.py: calculate_asset_betas min_len bug fixed; BINANCE_SYMBOLS §4A cleanup

Frontend:
- ScoreAnalytics.jsx: VITE_API_BASE → VITE_API_URL (was wrong env var, diverged from all other components)

MCP / Discoverability (Week 3 playbook — agent ecosystem blitz):
- dashboard/public/llms.txt + dist/llms.txt: NEW — LLM crawler doc (844K+ site standard)
- glama.json (repo root): NEW — Glama.ai auto-index (17,200+ servers, auto-approval)
- src/mcp/cometcloud_mcp.py: assertive descriptions on 5 tools (EMNLP 7.5x invocation multiplier)
  get_cis_exclusions, get_cis_universe, get_macro_pulse, get_cis_report, get_inclusion_standard

Docs:
- ATTACK_PLAN.md: NEW — Week 3 execution plan (Apr 28–May 4)
- ROADMAP_A2A.md: Phase 2.3 ✅; MINIMAX_SYNC.md: T20 dry run + direction locked; CLAUDE.md: updated

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
