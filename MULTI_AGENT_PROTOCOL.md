# Multi-Agent Protocol — CometCloud AI / Looloomi
*Version 1.1 — 2026-03-31*

---

## 1. Agents & Roles

| Agent | Identity | Mode | Owns |
|-------|----------|------|------|
| **Jazz** | Founder, human-in-the-loop | Decision + Deploy | Product direction, git push to main, investor relations |
| **Seth** | Austin/Sebastian Bath (Cowork) | L2 semi-auto | `src/`, `dashboard/src/`, `dashboard/dist/`, docs |
| **Minimax** | Claude Code on Mac Mini | L1 fully-auto | `/Volumes/CometCloudAI/cometcloud-local/`, `Shadow/` ref only |
| **Monitor** | Scheduled agent (Cowork) | L1 fully-auto | Production health checks, no code changes |

**Ownership is hard.** Seth never modifies `cometcloud-local/`. Minimax never modifies `src/` or `dashboard/`. Shadow/ is read-only reference for both.

---

## 2. Automation Levels

```
L1 — Fully Autonomous (no human gate)
  ├── Monitor Agent: hourly health checks, report to Jazz
  ├── Minimax: CIS scoring every 30min, macro brief every 2h
  └── Minimax: Freqtrade dry run, CIS cache writer

L2 — Semi-Automatic (Jazz push gate)
  ├── Seth: feature development → commit → notify Jazz
  ├── Seth: bug fixes from Monitor alerts → commit → notify Jazz
  └── Jazz: reviews diffs, runs `git push origin main` → Railway deploys

L2.5 — Near-Autonomous (current target)
  ├── Seth: pushes to `staging` branch autonomously
  ├── Automated health check on staging (Monitor Agent)
  └── Jazz: one-click merge staging → main (or auto-merge if checks pass)

L3 — Fully Autonomous (future)
  ├── All of L2.5, plus auto-merge with rollback capability
  ├── Requires: staging Railway env + rollback endpoint + smoke tests
  └── Target: Week 5+ after staging env is validated
```

---

## 3. Communication Channels

| From → To | Channel | Format |
|-----------|---------|--------|
| Seth → Jazz | End-of-session summary in Cowork chat | Commit log + pending pushes |
| Monitor → Jazz | Cowork notification (hourly) | Health report card |
| Minimax → Railway | POST `/internal/cis-scores` (Redis bridge) | CIS JSON payload |
| Minimax → Seth | MINIMAX_SYNC.md (file-based) | Schema changes, task status |
| Seth → Minimax | MINIMAX_SYNC.md + Cowork chat relay | Task assignments, API contract |

**No direct API calls between Seth and Minimax.** All coordination is via file-based protocol (MINIMAX_SYNC.md) or Jazz relay.

---

## 4. Task Assignment Flow

```
Jazz states intent (Cowork chat)
  │
  ▼
Seth decomposes into tasks
  ├── Seth-owned (src/, dashboard/) → implement directly
  ├── Minimax-owned (local engine) → write to MINIMAX_SYNC.md
  └── Shared (API contract change) → document in MINIMAX_SYNC.md FIRST, then implement
  │
  ▼
Seth implements, commits, reports to Jazz
  │
  ▼
Jazz reviews diff (optional) → git push origin main
  │
  ▼
Railway auto-deploys → Monitor Agent validates within 1h
```

---

## 5. Parallel Work Rules

When Seth and Minimax work simultaneously:

1. **No overlapping files.** Seth owns `src/api/`, Minimax owns `cometcloud-local/`. Interface = `/internal/cis-scores` POST contract.
2. **Schema changes require sync.** Any change to the CIS push payload schema MUST be documented in MINIMAX_SYNC.md before either side implements. Both must confirm.
3. **Redis key ownership.** `cis:local_scores` is Minimax's key. Seth reads, never writes (except via `/internal/cis-scores` endpoint). All other `cis:*` keys are Seth's.
4. **Conflict resolution.** If both Seth and Minimax need to change the same interface, Jazz decides priority and sequencing.

---

## 6. Deploy Safety Rules

- **Main branch = production.** Never push broken code to main. Build must pass, syntax must be clean.
- **Commit size.** Prefer small, focused commits. One feature or fix per commit.
- **Build before commit.** Always run `cd dashboard && npm run build` before staging frontend changes.
- **No secrets in commits.** Env vars stay in Railway dashboard. Never commit `.env` files.
- **Stale dist cleanup.** Before building, run `rm -rf dashboard/dist/assets && npm run build` to avoid accumulating old chunks.

---

## 7. Escalation Protocol

| Situation | Who acts | Action |
|-----------|----------|--------|
| CIS universe empty >2h | Monitor → Jazz notification | Jazz checks Railway env vars, Minimax checks push script |
| Macro pulse returning zeros | Monitor → Jazz | Jazz verifies `COINGECKO_API_KEY` in Railway |
| T1 data stale >2h | Monitor → Jazz | Jazz notifies Minimax to check `cis_scheduler.py` |
| Build failure on commit | Seth | Fix before committing, never commit broken build |
| Schema contract dispute | Seth + Minimax | Document in MINIMAX_SYNC.md, Jazz arbitrates |
| Production 500 errors | Monitor → Jazz | Seth investigates, hotfix commit, Jazz pushes |

---

## 8. Staging Environment Setup

**Status:** `staging` branch exists (local + remote). Railway staging env: **pending Jazz creation.**

### Railway Configuration (once Jazz creates the env)

1. **Create environment:** Settings → Environments → New Environment → `staging` (duplicate from production)
2. **Set source branch:** In the staging service settings → Source → Branch → `staging`
3. **Add env var:** `ENVIRONMENT=staging` (Railway → staging service → Variables)
4. **Keep all other vars** the same as production (UPSTASH, SUPABASE, COINGECKO_API_KEY, INTERNAL_TOKEN)
5. **Staging URL** will be a separate Railway subdomain (e.g. `web-staging-xxxx.up.railway.app`)

### Staging Deploy Workflow (L2.5)

```bash
# Seth commits feature to staging branch
git add src/ dashboard/src/ dashboard/dist/
git commit -m "feat: <description>"
git push origin staging          # → Railway staging auto-deploys

# Jazz reviews staging URL → if looks good:
git checkout main
git merge staging --no-ff
git push origin main             # → Railway production auto-deploys
```

### Staging Indicator

Backend: `/health` returns `"environment": "staging"` when `ENVIRONMENT=staging` is set.
Frontend: Orange banner `⚠ STAGING ENVIRONMENT — NOT PRODUCTION` appears automatically — invisible on production.

---

## 9. L3 Readiness Checklist

Before enabling fully autonomous deploys:

- [ ] `staging` branch created, Railway staging env configured ← **Jazz action needed**
- [ ] Staging auto-deploys on push to `staging` branch
- [ ] Monitor Agent runs smoke tests on staging before PR to main
- [ ] Auto-merge rule: staging → main if all health checks pass
- [ ] Rollback endpoint: `/internal/rollback` or Railway one-click rollback tested
- [ ] At least 2 weeks of L2.5 without production incidents

---

## 10. Current Status (2026-04-02)

**Seth — done this session:**
- [x] MCP fixes: CIS universe key (`universe` not `assets`), macro_pulse nested fallback, signal feed field names (`description`/`logic`/`affected_assets`)
- [x] MCP CIS timeout 20s → 60s (CIS universe was timing out)
- [x] `data_layer.py`: `get_macro_pulse()` now returns flat fields alongside nested structure (MCP + frontend compat)
- [x] `Shadow/cometcloud-local/data_fetcher.py`: 8 bug fixes (EODHD date format, API keys, symbol case, RateLimitError, yfinance hang, dup import)
- [x] `Shadow/cometcloud-local/config.py`: v4.1 grade thresholds + compliance signals
- [x] `Shadow/freqtrade/`: CometCloudT1Strategy.py + config_backtest_t1.json + run_t1_backtest.sh + T1_BACKTEST_VALIDATION.md
- [x] `MINIMAX_SYNC.md` created (file-based protocol for Seth ↔ Minimax)
- [ ] Freqtrade CIS integration (after Minimax dry run confirms T1)
- [ ] Trading Agent P&L dashboard

**Minimax — pending (see MINIMAX_SYNC.md §3 for full detail):**
- [ ] P0: Rotate EODHD + Finnhub API keys (exposed in git history)
- [ ] P0: Apply `data_fetcher.py` + `config.py` from Shadow → restart `cis_scheduler.py`
- [ ] P0: Confirm CIS scores in Redis (`cis:local_scores`) — T1 badge should turn green
- [ ] P1: Run `run_t1_backtest.sh` → report PF/WR/MaxDD to Jazz
- [ ] P1: Add LAS to local engine output (match Railway schema)
- [ ] P2: Macro Brief LM Studio crash recovery

**Jazz — pending:**
- [ ] `rm -f .git/HEAD.lock` then `git push origin main` (682fdbe + timeout fix pending)
- [ ] Restart Claude Desktop after push (MCP reloads fixed code)
- [ ] Railway → Variables: add `COINGECKO_API_KEY` (CIS universe empty without it)
- [ ] Railway → Variables: add `SUPABASE_URL` + `SUPABASE_KEY` (service_role)
- [ ] Run `scripts/supabase_all_tables.sql` in Supabase SQL Editor
- [ ] Strategy.html walkthrough with Nic
- [ ] Seed investor deck

---

*Build things that feel alive.*
