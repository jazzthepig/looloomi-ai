---
name: task-audit
description: Unified session-start + on-demand status report. Loads when the user says "audit", "卡在哪", "where are we", "what's in flight", or at the start of any session. Produces a 4-block view across TaskList, PROJECT_STATE.md, MINIMAX_OPEN_QUEUE.md, MEMORY.md, and git state. Closes the "half-done things we forgot about" failure mode (§OHLCV-DEAD stalled 7 days before being surfaced).
---

# Task Audit — Unified Session Status

A single 4-block view that answers *"what's in flight, what's stalled, what got done, what's broken"* — across Seth-side, Mac-side, awaiting Jazz, and git drift. Runs automatically on session start, and on-demand whenever the user asks for status.

## When to run

| Trigger | When |
|---|---|
| **Session start** | Auto, before any other work — first 60 seconds of a session |
| **On-demand** | User says "audit", "status", "卡在哪", "we stand?", "where are we?", "what's pending" |
| **Pre-conversation wrap-up** | If the session is closing and the user wants a snapshot before logout |
| **After any "done" claim** | The agent should run this to verify the picture is consistent |

## The 4 blocks (always output in this order)

### Block 1 — In-flight (Seth-side)

Query the Claude Code `TaskList`. For each task with `status == in_progress`:

```
IN-FLIGHT (Seth-side)                        age   risk
  #88 t-update PROJECT_STATE.md                0d   🟢 — just landed
  #X  t-do <name>                             2d   🟡 — review threshold
  #Y  t-do <name>                             5d   🔴 — STALE (open > 3d)
```

If TaskList is empty after a session that touched > 3 files, **flag drift** ("TaskList empty but PROJECT_STATE.md shows 5 things done — sessions don't close cleanly").

### Block 2 — P0/P1 in flight (Mac-side)

Read `MINIMAX_OPEN_QUEUE.md`. For each item flagged P0/P1, look up the resolution entry in `MINIMAX_SYNC.md`. If no resolution entry, age it from the original §XXX date stamp.

```
IN-FLIGHT (Mac-side, via MINIMAX_OPEN_QUEUE)
  §OUTCOMES-STALE — ohlcv_daily restart        4d   ⚠️ STALE (gate 3d)
  §VDB #1 — Mac embedding push                 3d   ⚠️ STALE
  §REGIME-ALIGN ① — T1 engine restart          4d   ⚠️ STALE
```

**Stale thresholds:**
- P0 in OPEN_QUEUE > 3d → **⚠️ STALE** (flag)
- P0 in OPEN_QUEUE > 7d → **🔴 ESCALATE** (next-session priority; surface to user)
- P1 in OPEN_QUEUE > 7d → **⚠️ STALE**
- P1 in OPEN_QUEUE > 14d → **🔴 ESCALATE**
- P2 doesn't stale-threshold by itself (research-lane)

### Block 3 — Awaiting Jazz + Blocked

Combine two sources:
- `MINIMAX_SYNC.md` entries that begin with "**JAZZ DECISION**" or call out a sign-off item
- `PROJECT_STATE.md` recent entries with "awaiting user sign-off" markers
- Things that **can't proceed without a decision** (e.g., CIS v5 weight reweight — documented pattern from `2026-07-20`)

```
AWAITING JAZZ
  (none)
  — OR —
  Phase 2 red vs green ship on Sleeve 2       2d   (per STRATEGY_2_DEFERRED)
```

If anything is in AWAITING JAZZ for > 7d, that's a **decision backlog** — flag.

### Block 4 — Drift check (the most important block)

This block catches the "I said done but git didn't see it" failure mode. Run these shell commands and assemble:

```bash
# A. Working tree vs committed
git status --porcelain | wc -l                    # number of dirty files
git diff --stat --staged                          # what's staged
git log origin/main..HEAD --oneline               # unpushed commits

# B. PROJECT_STATE.md "Last updated" header
grep -E "^\*\*Last updated:\*\*" PROJECT_STATE.md | head -1

# C. MEMORY.md last entry
grep -E "^- \[" MEMORY.md | tail -1

# D. Last commit on origin/main
git log origin/main -1 --pretty="format:%h %ad %s" --date=short

# E. Preflight (only if commit landed)
bash scripts/preflight.sh 2>&1 | tail -3
```

Output:

```
DRIFT CHECK
  Working tree dirty             : 13 files (staged: 13, unstaged: 0)
  Unpushed commits               : 0 (✓ aligned with origin/main)
  PROJECT_STATE "Last updated"   : 2026-07-26 (✓ today)
  Last memory entry              : 2026-07-26 production-push (✓ today)
  Last commit on origin/main     : <hash> 2026-07-26 <subject>
  Preflight                      : PASS (✓ last 3 lines)

  → no drift detected
  — OR —
  → DRIFT: PROJECT_STATE.md "Last updated" header is 5d stale, but you said
    "done" today. Either update the header or revert the done claim.
```

**Drift flags (any one of these = 🔴):**
- Working tree dirty > 0 files AND user said "done"
- Unpushed commits > 0 AND user said "shipped"
- "Last updated" header > 1d stale AND new claims made this session
- Preflight FAIL / not run this session

## Anti-imposter discipline (built-in)

The skill **does not auto-resolve** anything. It reports. The user decides what to do. This is the same anti-imposter principle as the rest of the codebase: surface what's broken, never dress up.

**Forbidden behaviors in this skill:**
- ❌ Auto-closing a "blocked" item because "it looks like it's done"
- ❌ Hiding a stale entry because the user is busy
- ❌ Marking something PASS in Drift Check without running the actual command
- ❌ Glossing over a missing `Last updated` header

## Linked artifacts

| Path | What it knows |
|---|---|
| `MINIMAX_OPEN_QUEUE.md` | Mac-side prioritized queue (P0/P1/P2 + RESOLVED) |
| `MINIMAX_SYNC.md` | Cross-lane coordination log |
| `PROJECT_STATE.md` | Living single source of truth (north star + building log) |
| `MEMORY.md` | Long-term memory index (one-line per memory file) |
| `REFUTATION_LEDGER.md` | R1–Rn experiment registry |
| `STRATEGY_PLAYBOOK.md` | Live strategy 1 (R77 fusion) |
| `STRATEGY_2_DEFERRED.md` | Strategy 2 honest graveyard |

## Output format (the canonical block)

When you run this skill, output exactly this structure. Plain markdown, no decoration. The first 4 lines are the headline; the rest is the body.

```
TASK AUDIT — <date>

[Block 1 — Seth-side in-flight]
[Block 2 — Mac-side in-flight]
[Block 3 — Awaiting]
[Block 4 — Drift check]

→ headline: <1 sentence summary>
```

The headline is required. Examples:
- "12 things done, 1 in-flight (Seth-side), 3 OPEN Mac-side P0, 0 drift."
- "🟡 1 STALE Mac-side P0 (§OUTCOMES-STALE 4d), 0 Seth-side in-flight, drift detected on PROJECT_STATE.md."

## Re-run cadence

- **Every session start** (auto, before any user ask)
- **Every ~90 minutes** during a long session (keep the picture fresh)
- **At end of session** (before saying "done with your day")
- **On user demand** (when they ask, no argument)
