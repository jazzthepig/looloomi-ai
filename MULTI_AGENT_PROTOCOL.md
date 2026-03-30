# Multi-Agent Protocol — CometCloud AI / Looloomi
*Version 1.0 — 2026-03-30*

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

## 8. L3 Readiness Checklist

Before enabling fully autonomous deploys:

- [ ] `staging` branch created, Railway staging env configured
- [ ] Staging auto-deploys on push to `staging` branch
- [ ] Monitor Agent runs smoke tests on staging before PR to main
- [ ] Auto-merge rule: staging → main if all health checks pass
- [ ] Rollback endpoint: `/internal/rollback` or Railway one-click rollback tested
- [ ] At least 2 weeks of L2.5 without production incidents

---

## 9. Current Week (Apr 1–5) Assignments

**Seth (this session):**
- [x] Wallet auth security hardening
- [x] og:image endpoint + social meta tags
- [x] Performance optimization (lazy-load, -30% bundle)
- [x] My Portfolio feature
- [ ] Staging branch + Railway staging env
- [ ] Freqtrade CIS integration (after Minimax dry run)
- [ ] Trading Agent P&L dashboard

**Minimax:**
- [ ] P0: `git pull` + v4.1 grade threshold alignment
- [ ] P0: Verify `cis_push.py` → Redis (T1 badge should be green)
- [ ] P0: Freqtrade dry run active + metrics JSON endpoint
- [ ] P1: LAS calculation in local engine output
- [ ] P1: T1 push metadata (`engine_version`, `push_timestamp` ms)
- [ ] P1: SLA heartbeat (alert if T1 data >2h stale)

**Jazz:**
- [ ] `git push origin main` (7 commits pending)
- [ ] Strategy.html walkthrough with Nic
- [ ] Seed investor deck draft

---

*Build things that feel alive.*
