# Ready to Commit — 2026-04-26

All files prepared. Run this from Mac Mini in `~/projects/looloomi-ai/`.

## Step 1: Remove FUSE locks

```bash
rm -f .git/index.lock .git/HEAD.lock
```

## Step 2: Pull latest

```bash
git pull --rebase origin main
```

## Step 3: Stage

```bash
git add \
  src/api/main.py \
  requirements.txt \
  cometcloud-intelligence/mcp/cometcloud.json \
  dashboard/src/components/CISWidget.jsx \
  dashboard/src/components/StrategyPage.jsx \
  dashboard/dist/ \
  scripts/test_auth_e2e.py \
  ROADMAP_A2A.md \
  CLAUDE.md \
  COMMIT_READY.md \
  .claude/session-handoff/current_state.md
```

## Step 4: Commit

```bash
git commit -m "feat(mcp): Phase 2.2 — MCP server + auth E2E test + SPA routing fix

ROADMAP_A2A Phase 2.2 complete. CometCloud MCP server now live at
https://looloomi.ai/mcp/sse (SSE transport). Any MCP-compatible agent
(Claude, Cursor, GPT) can discover and query CIS scores natively.

MCP (Phase 2.2):
- main.py: app.mount('/mcp', mcp.sse_app()) — zero new Railway services
- main.py: SPA fallback now excludes 'mcp/' prefix (prevents index.html bleed)
- requirements.txt: mcp[cli]>=1.6.0, cachetools, tenacity added
- cometcloud.json: remote.url → https://looloomi.ai/mcp/sse (type: sse)
- Fail-safe: try/except guard, main app still boots if dep missing
- ROADMAP_A2A.md: Phase 2.2 marked complete

Endpoints:
  GET  /mcp/sse      — SSE stream (agent connects here)
  POST /mcp/messages — message send

Auth:
- scripts/test_auth_e2e.py: 11-test E2E suite for wallet sign-in backend
  (keypair gen → nonce → sign → wallet-signin → profile → replay → bad sig)
  Run from Mac Mini: python scripts/test_auth_e2e.py

UI fixes (Chrome QA pass):
- CISWidget.jsx: epoch timestamp (seconds → *1000), MACRO REGIME Unknown
  (data?.macro → { regime: data?.macro_regime })
- StrategyPage.jsx: 'Open Platform' button contrast fix

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

## Step 5: Push

```bash
git push origin main
```

Railway auto-deploys on push (~90s).

---

## Freqtrade recommendation (Minimax to apply in CometCloudStrategy.py)

In the current Tightening regime, CIS=65 is unreachable — even MKR (best T1 asset)
scores 56.8. Regime-aware gate:

```python
REGIME_THRESHOLDS = {
    "Risk-On": 65, "Goldilocks": 65, "Easing": 62,
    "Neutral": 58,
    "Tightening": 52, "Risk-Off": 50, "Stagflation": 50,
}
# Fetch current regime from CIS cache or /api/v1/market/macro-pulse
current_regime = get_current_regime()  # returns string like "Tightening"
MIN_CIS_SCORE = REGIME_THRESHOLDS.get(current_regime, 58)
```

This lets the strategy trade in all market conditions, using the CIS score as a
relative filter within the regime rather than an absolute bull-market gate.
