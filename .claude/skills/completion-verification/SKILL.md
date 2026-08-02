---
name: completion-verification
description: Hook that runs before any "done", "complete", "shipped", "✅" claim. Verifies the claim against actual git state, preflight, and the smoke tests that touch the changed files. Closes the "I said done but git didn't see it" failure mode (CLAUDE.md's behavioral discipline: "don't trust memory of what's committed" — event from 2026-07-02).
---

# Completion Verification — The done-claim hook

Before ANY claim that work is "done", "complete", "shipped", "ready", or marked with a green check, this skill runs. It **does not trust** the agent's memory. It runs the actual commands and reports the verdict.

## Hard rule

> **No "done" claim without first running completion-verification.**
> This is structural. The previous discipline was "remember to check git status" — and that failed repeatedly (2026-07-02 commit-mismatch, 2026-07-13 main.py unimported Response, 2026-07-19 §OHLCV-DEAD silent for 7 days).
> The new discipline is: **`completion-verification` is a check, not a habit.**

## When to run

| Trigger | When |
|---|---|
| **Before any "done" / "shipped" / ✅ claim** | Mandatory |
| **End of batch of changes** | If > 3 files edited in a single turn |
| **Before user-facing reporting** | "OK I shipped X" → run first |
| **Before updating PROJECT_STATE.md "Last updated"** | If you say "Last updated: <date>" — prove it |

**Forbidden behaviors:**
- ❌ "Done ✅" with no command evidence in the same turn
- ❌ "Last updated: 2026-07-26" when the header was actually written on a different day
- ❌ "5/5 tests pass" without showing the actual test output
- ❌ "Pushed to origin/main" without `git log origin/main` evidence

## The 5 checks (always run all 5)

### Check 1 — Working tree state

```bash
git status --porcelain
```

**Verdict:**
- ✅ PASS if output is empty (clean tree)
- 🟡 WARN if files exist but ALL are in `Shadow/` (which is intentionally trackable-but-not-committed)
- 🔴 FAIL if any file in `src/`, `dashboard/`, `scripts/`, `docs/`, `MEMORY.md`, `MINIMAX_SYNC.md`, `PROJECT_STATE.md` is unstaged or untracked

### Check 2 — Staged changes vs claimed scope

```bash
git diff --stat --staged
git diff --stat          # unstaged
```

Compare against the claim ("I edited X, Y, Z"):
- ✅ PASS if the staged + unstaged files match what's claimed
- 🔴 FAIL if files appear that weren't mentioned (implies silent scope creep)
- 🔴 FAIL if claimed files don't appear (implies the edit didn't actually land)

### Check 3 — Committed but not pushed

```bash
git log origin/main..HEAD --oneline
git log origin/main -1 --pretty="format:%h %ad %s" --date=short
```

**Verdict:**
- ✅ PASS if `git log origin/main..HEAD` is empty (everything pushed)
- 🟡 WARN if there are unpushed commits but the claim is "code-complete, awaiting Mac-side push" (acceptable FUSE-blocked state)
- 🔴 FAIL if there are unpushed commits AND the claim is "shipped" / "deployed" / "live"

### Check 4 — Preflight (RAW + test for changed files)

```bash
bash scripts/preflight.sh 2>&1 | tail -10
```

If the change touched Python files under `src/`:
```bash
# Find the file's test directory and run its tests
python3 -m pytest <test_path>/tests/ -v 2>&1 | tail -10
```

**Verdict:**
- ✅ PASS if preflight imports + boots
- ✅ PASS for tests if the relevant suite is green (>0 collected, all pass)
- 🔴 FAIL if preflight errors or tests fail
- 🟡 WARN if preflight skipped (e.g., only `.md` files changed — but say so explicitly)

### Check 5 — Drift against PROJECT_STATE.md

```bash
grep -E "^\*\*Last updated:\*\*" PROJECT_STATE.md | head -1
```

If the claim is "done today" and "Last updated" header is older than today:
- 🔴 FAIL — either update the header or don't claim done.

If the claim is "done with X" and X has no row in PROJECT_STATE.md's latest building log entry:
- 🟡 WARN — "Will add X to PROJECT_STATE.md now (5 lines) before claiming done."

## Output format

```
COMPLETION VERIFICATION — <claim>

  Check 1 — Working tree      : ✅ / 🟡 / 🔴
  Check 2 — Staged vs scope   : ✅ / 🟡 / 🔴
  Check 3 — Pushed to main    : ✅ / 🟡 / 🔴
  Check 4 — Preflight + tests : ✅ / 🟡 / 🔴
  Check 5 — State doc drift   : ✅ / 🟡 / 🔴

  Verdict: PASS / PASS-WITH-WARNINGS / FAIL
  Action items: <list>
```

**PASS** — all 5 checks green. The "done" claim is supported.
**PASS-WITH-WARNINGS** — at least one 🟡. Tell the user what the warning is and let them decide.
**FAIL** — at least one 🔴. The "done" claim is NOT supported. List the action items that would move it to PASS.

## Examples

### Example 1: real done claim

```
COMPLETION VERIFICATION — "BETA-METRIC-AGG shipped"

  Check 1 — Working tree      : 🟡 13 files staged (not yet committed — FUSE blocks sandbox commit)
  Check 2 — Staged vs scope   : ✅ matches the 13 files in the Mac-side commit handoff list
  Check 3 — Pushed to main    : 🟡 0 unpushed commits (because 0 commits — Mac-side still pending)
  Check 4 — Preflight + tests : ✅ 16/16 track-record tests pass, 7/7 strategy-store tests pass
  Check 5 — State doc drift   : ✅ Last updated header rewritten to 2026-07-26

  Verdict: PASS-WITH-WARNINGS
  Warnings: FUSE blocks git-write in sandbox; Mac-side commit still required.
  Action items: hand off the 13-file list to Mac-side.
```

### Example 2: false done claim

```
COMPLETION VERIFICATION — "Done, all tests pass"

  Check 1 — Working tree      : 🔴 3 files dirty (src/api/store.py, src/api/routers/signals.py, ...)
  Check 2 — Staged vs scope   : 🔴 memory claim was "store.py modified" — actual: src/api/store.py MODIFIED, src/data/.../c1.py UNEXPECTED
  Check 3 — Pushed to main    : 🔴 1 unpushed commit claiming "ship feature X"
  Check 4 — Preflight + tests : ✅ 16/16 pass
  Check 5 — State doc drift   : 🔴 Last updated header still 2026-07-25

  Verdict: FAIL
  Action items:
    1. Review the 3 dirty files; either commit or revert the unexpected c1.py change
    2. Discuss the unpushed commit (was it meant to ship?)
    3. Update PROJECT_STATE.md "Last updated" header to 2026-07-26
    4. Then re-run this verification
```

## Failure modes this skill prevents

| Failure mode | How it caught |
|---|---|
| 2026-07-02 "pending push" was actually never committed | Check 1 + Check 3 |
| 2026-07-13 `Response` unimported in main.py (py_compile passed, prod 502'd) | Check 4 (preflight) |
| 2026-07-19 §OHLCV-DEAD silent for 7 days (no detection) | Mostly NOT caught — but `task-audit` Block 4 catches it |
| 2026-07-26 "shipped" with 13 files staged but no commit | Check 1 + Check 3 (warned "FUSE-blocked; Mac-side still required") |
| Updating PROJECT_STATE.md "Last updated" without actually doing work | Check 5 (the date MUST match what was actually done) |

## Linked

- `task-audit/SKILL.md` — the read-side of the same loop (this is the write-side hook)
- `scripts/preflight.sh` — the actual preflight script (must exist; if it doesn't, the skill fails)
- `CLAUDE.md` §"Operational loop" — the meta-loop that ties these together
