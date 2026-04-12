# Current State — Updated 2026-04-12 (~5pm JST)

## Commits on Railway (pushed)
- `6c09dad` — Phase A: compliance-language + cis-methodology skills, 12 violations fixed
- `9ebc5a8` — Auth graceful degradation (wallet-signin no longer 503 without Supabase) + Phase D session handoff

## Commits local only (need Jazz to push from Mac Mini)

```bash
rm -f .git/index.lock .git/HEAD.lock
git add \
  .claude/hooks/compliance_check.py \
  .claude/settings.json \
  .claude/agents/compliance-auditor.md \
  .claude/agents/cis-validator.md \
  .claude/agents/deploy-verifier.md \
  .claude/agent-memory/compliance-auditor/MEMORY.md \
  .claude/agent-memory/cis-validator/MEMORY.md \
  .claude/agent-memory/deploy-verifier/MEMORY.md \
  dashboard/src/App.jsx \
  dashboard/dist/
git commit -m "feat: Phase B+C — compliance hook, 3 subagents + Portfolio section mounted"
git push origin main
```

## Files changed but NOT yet in any commit (need staging + commit above)
- `.claude/hooks/compliance_check.py` — Phase B compliance hook (dry-run, PreToolUse)
- `.claude/settings.json` — hooks registration
- `.claude/agents/compliance-auditor.md` — compliance audit subagent
- `.claude/agents/cis-validator.md` — CIS scoring validation subagent
- `.claude/agents/deploy-verifier.md` — post-deploy health check subagent
- `.claude/agent-memory/*/MEMORY.md` — seeded memory for 3 new agents
- `dashboard/src/App.jsx` — Portfolio added as Section 6 (lazy MyPortfolio mount)
- `dashboard/dist/` — rebuilt after Portfolio section + compliance signal map cleanup

## Active feature: Portfolio tab (wired, not yet on Railway)
MyPortfolio.jsx (741 lines, fully built) is now mounted as Section 6 in App.jsx:
- Wallet-gated: shows connect prompt if not signed in
- Watchlist: pin assets from CIS universe (localStorage)
- Position tracker: cost basis → live P&L
- CIS grade change alerts since asset was added
- No extra API calls — reads cisUniverse prop from parent

## Auth is now unblocked (on Railway since 9ebc5a8)
wallet-signin no longer returns 503 without Supabase configured.
Session token issued from Redis. Profile creation is soft-optional.
→ Wallet connect E2E with Phantom devnet should work now.

## Production health (as of 6c09dad / 9ebc5a8)
- CIS Universe: ❌ EMPTY — COINGECKO_API_KEY still missing in Railway
- Macro Pulse: ✅ LIVE
- Signal Feed: ✅ LIVE
- DeFi Overview: ✅ LIVE
- Wallet auth: ✅ FIXED (9ebc5a8) — can sign in without Supabase
- Portfolio tab: ⏳ PENDING Railway deploy after push above

## Next tasks (in order)
1. **Jazz**: `rm -f .git/index.lock .git/HEAD.lock` + run git add + commit + push above
2. **Jazz**: Add `COINGECKO_API_KEY` to Railway → CIS universe populates
3. **Jazz**: Add `SUPABASE_URL` + `SUPABASE_KEY` → full profile persistence
4. **Jazz/Seth**: Wallet connect E2E test on devnet (Phantom)
5. **Seth**: Phase E — CometCloud plugin packaging (optional, no blocker)

## HARNESS_UPGRADE.md progress
- Phase A: ✅ Skills (committed + pushed)
- Phase B: ✅ Hook (on disk, pending commit)
- Phase C: ✅ Subagents + memory (on disk, pending commit)
- Phase D: ✅ Session handoff (committed + pushed in 9ebc5a8)
- Phase E: Plugin packaging — not started
- Phase F: GitHub Agentic Workflows — not started
- Phase G: Scheduled task migration — not started
