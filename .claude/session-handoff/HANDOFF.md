# CometCloud Session Handoff — Last updated 2026-06-04

## Quick state for new session
Read `current_state.md` first. Then read CLAUDE.md "Production health" and "Task matrix".

## Top 3 for next session
1. Signal outcome tracker — match signal_journal entries to OHLCV 30D later, calculate win rate
2. QuantMonitor paper P&L auto-refresh — show live paper trading once Minimax trigger is in
3. win.html enhancements — live regime badge, protocol scores, more proof points

## Key files from Jun 2026 session
- `MINIMAX_TRADING_TRIGGER.md` → send to Minimax, paste into cis_scheduler.py
- `CometCloud_Investor_Deck_2026.pptx` → 10-slide LP deck (in repo root)
- `dashboard/win.html` → How to Win page (live after git push)

---

# CometCloud Session Handoff Protocol (original)

Every Cowork session has a finite context window. When it fills, the next session
starts cold. This file defines how Seth and Austin leave a clean handoff so the
next session can pick up precisely where things stopped — no re-reading all of
CLAUDE.md, no "what was I doing?" delay.

## The contract

At the end of every session (or before context runs out):
1. Update `current_state.md` with WHAT IS DONE, WHAT IS NEXT, WHAT IS BLOCKED.
2. Save any in-progress code to disk (files, not clipboard).
3. Commit staged changes or note the exact `git add` command for the next session.
4. Next session opens `current_state.md` before reading anything else.

## What goes in current_state.md

Keep it under 80 lines. Ruthlessly discard anything not needed to resume work.
- **Last commit**: hash + one-line description
- **Staged but not committed**: exact `git add` command to re-stage
- **Active task**: what we were doing when the session ended
- **Next task**: the very next thing to do, specific enough to start without thinking
- **Blocked on**: who or what is blocking, what they need to do
- **Production health**: current known state of Railway

## What goes in feature-spec.json

For larger multi-session features (>1 session of work), create a spec file in
`.claude/session-handoff/features/` named after the feature. Keeps the overall
feature context out of current_state.md.

Format: see `features/TEMPLATE.json`

## What NOT to put here

- Code (put it in the actual source files)
- Full file contents (link by path)
- Completed tasks older than 3 sessions (archive or delete)
- Meeting notes, investor content, strategy (those go in docs/)
