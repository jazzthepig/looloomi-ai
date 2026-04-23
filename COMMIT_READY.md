# Ready to Commit — 2026-04-21

All files prepared. Run this from Mac Mini in `~/projects/looloomi-ai/`.

## Step 1: Remove FUSE locks

```bash
rm -f .git/index.lock .git/HEAD.lock
```

## Step 2: Pull latest

```bash
git pull --rebase origin main
```

## Step 3: Stage harness artifacts + docs

```bash
git add \
  .claude/agents/code-frontend-reviewer.md \
  .claude/agents/local-data-coordinator.md \
  .claude/session-handoff/current_state.md \
  .claude/skills/mac-mini-coordination/ \
  .claude/skills/deploy-workflow/ \
  .claude/skills/design-system/ \
  .claude/skills/tech-stack/ \
  .github/workflows/ \
  cometcloud-intelligence/ \
  dashboard/public/.well-known/ \
  dashboard/dist/.well-known/ \
  HARNESS_UPGRADE.md \
  ROADMAP_A2A.md \
  MINIMAX_SYNC.md \
  tests/
```

## Step 4: Commit

```bash
git commit -m "feat(harness): Phase A-F complete + A2A agent card + Shadow sync record

Phase A — 4 remaining skills:
- mac-mini-coordination, deploy-workflow, design-system, tech-stack

Phase C — 2 additional agents:
- code-frontend-reviewer, local-data-coordinator

Phase E — cometcloud-intelligence plugin:
- plugin.json v0.1.0 + 5 skills + 2 commands + cis-analyst + MCP config (stdio mode)

Phase F — GitHub Agentic Workflows:
- compliance-pr-check, post-deploy-verify, weekly-cis-audit

ROADMAP_A2A Phase 2.1 — A2A discovery:
- dashboard/public/.well-known/agent.json + dist copy

MINIMAX_SYNC.md §7 — Shadow sync record:
- Cache key fixes (fundamental→coingecko, fundamental→tvl)
- STX/ONDO symbol mapping corrections
- CIS scheduler confirmed running, macro_regime=Tightening

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

## Step 5: Push

```bash
git push origin main
```

Railway auto-deploys on push (~90s). The /.well-known/agent.json will be live
at https://looloomi.ai/.well-known/agent.json after deploy.
