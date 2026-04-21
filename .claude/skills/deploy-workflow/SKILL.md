---
name: deploy-workflow
description: Standard deploy sequence for CometCloud/Looloomi Railway deployments. Use this skill when preparing to commit code, building the React frontend, pushing to Railway, or verifying a deployment landed. Triggers include "deploy", "build", "git push", "Railway", "release", "commit", "branch", "staging". This skill enforces the build-before-commit rule, handles FUSE git lock workaround, and describes the L2/L2.5 workflow from MULTI_AGENT_PROTOCOL.md.
---

# Deploy Workflow — CometCloud Railway

## Standard deploy sequence

```bash
# 1. Build the React frontend (ALWAYS before staging frontend changes)
cd dashboard && rm -rf dist/assets && npm run build && cd ..

# 2. Stage files (Seth scope only — src/, dashboard/src/, dashboard/dist/, docs)
git add src/ dashboard/src/ dashboard/dist/

# 3. Commit
git commit -m "<type>(<scope>): <description>"

# 4. Push — triggers Railway auto-deploy (~2 min)
git push origin main
```

**Railway auto-deploys on push to `main`.** No manual trigger needed. Deploy takes ~90 seconds; Railway serves the new version automatically.

---

## Commit message format

```
feat(cis): add dual-score display (raw + regime-adjusted)
fix(api): hoist fng_value before if/else in calculate_cis_score
chore(deps): add email-validator to requirements.txt
docs: update CLAUDE.md task matrix for Week 6
```

Types: `feat`, `fix`, `chore`, `docs`, `style`, `refactor`, `perf`, `test`
Scope: `cis`, `api`, `dashboard`, `signals`, `vault`, `auth`, `agents`, `harness`

---

## Critical rules

1. **Build before commit.** Never commit frontend changes without running `npm run build` first. Railway serves `dashboard/dist/` directly — stale dist = broken site.

2. **Stale chunk cleanup.** `rm -rf dashboard/dist/assets` before each build. Old chunk filenames accumulate and bloat the repo.

3. **No secrets in commits.** Env vars live in Railway dashboard. Never commit `.env`, API keys, or tokens. Shadow/ had this problem — it's why Shadow/ was removed from git.

4. **Seth scope only.** Only stage files in `src/`, `dashboard/`, `.claude/`, docs. Never stage `/Volumes/CometCloudAI/` paths — those are Minimax's files and are on the Mac Mini filesystem, not this repo.

5. **FUSE lock issue.** The Cowork VM has a FUSE filesystem that creates `.git/HEAD.lock` files that cannot be removed from inside the VM. **All git pushes must be executed from the Mac Mini terminal.** Seth prepares commits and stages files; Jazz or Minimax pushes.

   Mac Mini fix if HEAD.lock blocks: `rm /Users/sbb/projects/looloomi-ai/.git/HEAD.lock`

6. **No broken builds on main.** `main = production`. If the npm build fails or Python has a syntax error, fix it before committing.

---

## FUSE lock workaround (in detail)

Because the Cowork VM cannot push to git directly:
1. Seth stages and commits from Cowork (using `git add` + `git commit`)
2. Reports the commit hash and summary to Jazz
3. Jazz runs `git push origin main` from Mac Mini terminal
4. Railway auto-deploys on push
5. Deploy Verifier agent confirms health after ~3 min

This is L2 automation (Jazz push gate) per MULTI_AGENT_PROTOCOL.md §2.

---

## Staging branch (L2.5 — future)

```bash
# Seth commits to staging branch (Cowork → Mac Mini push)
git add src/ dashboard/src/ dashboard/dist/
git commit -m "feat: <description>"
git push origin staging          # → Railway staging auto-deploys

# Jazz reviews staging URL, then:
git checkout main
git merge staging --no-ff
git push origin main             # → Railway production auto-deploys
```

Railway staging environment: **pending Jazz creation** (as of Apr 2026).
See `MULTI_AGENT_PROTOCOL.md §8` for staging setup instructions.

---

## Post-deploy verification

After every push, run the `deploy-verifier` agent (`.claude/agents/deploy-verifier.md`) or manually check:

```
GET https://looloomi.ai/api/v1/cis/universe       → assets > 0, grades B+
GET https://looloomi.ai/api/v1/market/macro-pulse  → btc_price > 1000
GET https://looloomi.ai/api/v1/market/signals      → signals.length > 3
```

Production URL: `https://web-production-0cdf76.up.railway.app` / `https://looloomi.ai`

---

## Build output

```
dashboard/dist/
├── index.html
├── app.html
├── strategy.html
├── vision.html
└── assets/
    ├── main-[hash].js          (~252KB — core app bundle)
    ├── ScoreAnalytics-[hash].js (~401KB lazy — recharts)
    └── [other lazy chunks]
```

Vite creates content-hash filenames. Each build produces new hashes. Always commit the full `dist/` folder — Railway serves it as static files.

---

## Scripts

`scripts/build_and_push.sh` — helper for clean builds. Run from repo root.
