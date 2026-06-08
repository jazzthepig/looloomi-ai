# Autonomous Harness — Design Doc (for Seth ↔ Minimax ↔ Jazz review)

**Date:** 2026-06-06 · **Status:** proposal, not yet built · **Author:** Seth

## Problem

The system can't yet **report on itself** or **improve itself**. Every loop has a
human as the scheduler/poller. Every failure this session — empty universe,
missing modules, absent Mac Mini push, DeFiLlama paywall, LM Studio OOM — was
found *reactively*, by someone happening to look. We have the machinery
(`build-state`, health gate, outcome tracker, contract normalizer); what's
missing is the autonomous layer that runs it on a schedule, watches, alerts, and
feeds results back.

Three loops to close, in priority order.

---

## Loop 1 — Heartbeat / Observability (P0)

**Goal:** turn "discover by accident" into "told immediately."

**What it checks (every 15–30 min):**
- Mac Mini push freshness — `build-state.last_cis_push.age_seconds` > 2h ⇒ alert
- Contract drift — `last_cis_push.drift_warnings` > 0 ⇒ alert (which fields)
- Universe health — `/cis/universe` count ≥ 50, source, no `status:error`
- Data-source health — `/cis/debug/datasources` (binance/cg/defillama/eodhd/fng) any 0
- MacroBrief — NULL state
- Deploy lag — live git sha vs `main` HEAD (commits pending push)
- Compliance — any banned signal in universe (defense in depth)

**Where it runs:** scheduled task (Cowork scheduler or a Railway cron/APScheduler
job). Reads existing endpoints — no new data plumbing.

**Output:**
- **Alert on state change** (healthy→broken) to a channel — Slack recommended
  (finance:slack plugin available), or email. Only fire on transitions, not every tick.
- **Daily digest** (one message / a refreshable artifact): green/amber/red per
  subsystem + key numbers. The "is everything ok?" glance.

**New components:** `/internal/health-summary` (aggregates the checks into one
JSON verdict) + a scheduled poller + alert sender. ~small.

**Ownership:** Seth (Railway endpoint + poller). Alert channel = Jazz decision.

---

## Loop 2 — Learning (outcome → IC → pillar weights) (P1, live ~June 24)

**Goal:** CIS self-improves instead of being static.

**Flow:** signal outcomes (`signal_journal.outcome_30d`) → compute Information
Coefficient per pillar per regime (does a high F/M/O/S/A actually predict the 30d
outcome?) → adjust pillar weights via the existing §8 Simons IC multiplier path
→ engine uses regime-conditional weights.

**Guardrails (critical):**
- Notify-only first: propose weight changes, human approves before they go live.
  Auto-apply only after the IC signal is stable over N samples.
- Floor/cap on weight drift per cycle (e.g. ±15%) so one bad month can't wreck it.
- Min sample size before any adjustment (≥30 resolved outcomes per regime).
- Log every adjustment with the IC evidence (auditable, investor-credible).

**Ownership:** Minimax owns the engine-side weight application (`cis_v4_engine.py`);
Seth owns the IC computation from Supabase + the proposal surface. Needs the
outcome tracker to have a real sample first.

**Blocker:** no mature outcomes until ~June 24. Wire now, activate then.

---

## Loop 3 — Autonomous deploy + verify (P1)

**Goal:** remove the human from the push/verify cycle.

- Post-push: `deploy_health_gate.py` runs automatically (GitHub Action on push to
  main, or the heartbeat poller detects a new sha and runs the gate).
- On red: open an incident / alert Jazz with the specific failure + remediation.
- On green: silent (or a ✅ in the daily digest).
- Optional later: auto-push on green CI from a staging branch (bigger trust step —
  not first).

**Ownership:** Seth. Reuses the existing gate script; just needs a runner +
alert wiring. The current `post-deploy-verify.md` is a spec, not a running job —
make it run.

---

## Architecture notes

- **One verdict surface.** `/internal/health-summary` becomes the single source
  of truth all three loops + the dashboard read. Avoids each loop re-implementing
  checks (the drift disease).
- **Alerts fire on transitions, not every poll** — store last state in Redis,
  compare, alert on change. No alert fatigue.
- **Everything reads endpoints we already have** — build-state, debug/datasources,
  universe, signals/performance. Minimal new code; mostly orchestration.

## Decisions (locked — Jazz, 2026-06-06)

1. **Alert channel → Telegram** (changed from Slack, 2026-06-06). Rationale is
   GTM, not just ops: Telegram is the crypto-native channel, and the **same bot
   serves double duty** — internal heartbeat/digest alerts now, and user-facing
   alerts (signal crossings, grade changes, regime shifts) to LPs and trading
   agents at go-to-market. One piece of infra, two payoffs; ties directly into
   the existing `webhooks` router (grade-change subscriptions get a Telegram
   delivery channel).
   - **Build:** a thin `notify_telegram(text, chat_id)` helper → Telegram Bot API
     `sendMessage`. No plugin/dependency — just an HTTPS call.
   - **Env:** `TELEGRAM_BOT_TOKEN` (from BotFather), `TELEGRAM_ALERT_CHAT_ID`
     (internal ops channel). Later: per-user/per-LP chat IDs for GTM alerts.
   - **Reuse:** the heartbeat sender and the user-facing webhook delivery share
     this one helper — build once.
2. **Learning loop → auto-apply after stability.** Weights adjust automatically
   once the IC signal is stable, NOT notify-and-approve. Guardrails become
   load-bearing: min sample ≥30/regime, ±15% drift cap per cycle, stability
   window before any auto-apply, full audit log of every change. Kill-switch env
   flag to freeze weights if it misbehaves.
3. **Deploy → keep manual `git push` for now.** Loop 3 is **auto-verify only**:
   the health gate fires automatically after a deploy is detected and alerts
   Slack on red. No auto-push from staging yet.

## Multi-agent topology & logistics loop

The system is already a mesh of agents; we've just never drawn it. Naming it
exposes where coordination is missing.

### Who's in the mesh

| Agent | Brain | Owns | Interface to the mesh |
|---|---|---|---|
| **Seth / Austin** | Claude | `src/`, `dashboard/`, docs, Railway | git, MINIMAX_SYNC, the contract |
| **Minimax** | MiniMax M3 | Mac-local engine, scoring, scheduler, push | `/internal/cis-scores`, MINIMAX_SYNC |
| **Jazz** | human | strategy, `git push`, financing, license, GTM | everything |
| **Nic** | human | network, sales, LP intros | offline |
| **Trading agent** | Freqtrade + CIS strategy | paper/live execution | reads CIS cache |
| **External agents** | various (GTM) | consume intelligence | MCP `/mcp/sse`, Agent API, `agent.json` |
| **Heartbeat/loop agents** | scheduled jobs | observability, learning, verify | internal endpoints |

### The value logistics loop (data path)

`ingest` (CG / EODHD / DeFiLlama / RSS / CryptoRank)
→ `score` (Minimax engine, M3)
→ `push` (contract v1, /internal/cis-scores)
→ `normalize + serve` (Railway: normalizer, never-empty floor, narratives, executability)
→ `consume` (dashboard · LP via Telegram · trading agent · external agents via MCP)
→ `outcome` (30d tracker → signal_journal)
→ `learn` (IC → pillar weights, auto-apply after stability)
→ back to `score`.

Each arrow is a handoff with an owner and a failure mode. Today the only
*programmatic* handoff guard is the contract (normalizer + `/schema` echo +
build-state). Everything else is trust + markdown.

### The work-coordination loop (how agents stay in sync)

Today: **async, file-based** — MINIMAX_SYNC.md + git + the live contract echo.
This is why §2 drifted for weeks and why the same HOLD fix was made on both
sides independently. It works but it's lossy.

### Multi-agent gaps (the missing coordination loops)

1. **No live shared task/state ledger.** Who's doing what, what's blocked, what's
   pending push — lives in markdown that drifts. Proposal: a `coordination`
   Supabase table (or `/internal/coordination`) both agents read+write: open
   tasks, owner, status, blockers, contract_version, last_sync_at. The work
   analog of build-state.
2. **No automated handoff.** Session recaps (like today's) are hand-written.
   Proposal: a session-end job that snapshots state (deployed sha, pending
   commits, open tasks, health verdict) into the ledger + Telegram.
3. **No conflict detection.** Both sides can edit overlapping concerns (HOLD fix
   happened twice). Proposal: `config_hash` + contract_version comparison surfaced
   in the heartbeat — flag when Mac-local and Railway diverge.
4. **Internal A2A is weaker than external A2A.** External agents get MCP + a
   structured Agent API + `agent.json`; Seth↔Minimax have only files. The
   contract echo is read-only *system* state, not *work* state. Close the gap with
   the coordination ledger above.
5. **External agent mesh is one-directional.** They consume; nothing flows back.
   Later: capture agent tool-call telemetry (what they query, what they trust) as
   a product-signal loop — feeds both GTM and the learning loop.

### Where this plugs in

The coordination ledger (#1) is the multi-agent analog of the heartbeat: build it
alongside Loop 1, reading/writing the same `/internal/health-summary` surface.
Conflict detection (#3) rides the heartbeat. Both are Seth-buildable; the ledger
needs Minimax to write its side (current task/status) each cycle.

## Suggested sequence

1. `/internal/health-summary` + heartbeat poller + alerts (Loop 1) — catches
   today's failure classes immediately.
2. Auto-verify on deploy (Loop 3) — small, reuses the gate.
3. Learning loop (Loop 2) — wire now, activate when outcomes mature (~June 24).
