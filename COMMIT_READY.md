# Ready to Commit — 2026-04-26 (Phase 2.2 MCP + auth test)

## Current state
- HEAD = `2ddbaef` — fix(cis): T2 beta fallback, A base +25, tighten regime S weight
- `dashboard/dist/` is CLEAN (Minimax's build included the CISWidget + StrategyPage fixes)
- Phase 2.2 MCP changes are still uncommitted — run steps below to push

---

## Step 1: Remove FUSE locks

```bash
rm -f .git/index.lock .git/HEAD.lock
```

## Step 2: Pull latest (absorb 2ddbaef)

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
  scripts/test_auth_e2e.py \
  ROADMAP_A2A.md \
  CLAUDE.md \
  COMMIT_READY.md \
  .claude/session-handoff/current_state.md
```

Note: `dashboard/dist/` is NOT staged — already committed in `2ddbaef`. Source files (CISWidget.jsx, StrategyPage.jsx) are staged so they stay in sync with the dist.

## Step 4: Commit

```bash
git commit -m "feat(mcp): Phase 2.2 — MCP server at /mcp/sse + auth E2E test

ROADMAP_A2A Phase 2.2 complete. CometCloud MCP server live at
https://looloomi.ai/mcp/sse (SSE transport). Any MCP-compatible
agent (Claude, Cursor, GPT) can query CIS scores natively.

MCP:
- main.py: app.mount('/mcp', mcp.sse_app()) — zero new Railway services
- main.py: SPA fallback now excludes 'mcp/' prefix
- requirements.txt: mcp[cli]>=1.6.0, cachetools, tenacity
- cometcloud.json: remote.url → https://looloomi.ai/mcp/sse (type: sse)
- Fail-safe: try/except guard, main app still boots if dep missing
- ROADMAP_A2A.md: Phase 2.2 marked complete

Auth:
- scripts/test_auth_e2e.py: 11-test backend E2E for wallet sign-in
  Run: python scripts/test_auth_e2e.py

UI fixes (source files — dist already in 2ddbaef):
- CISWidget.jsx: epoch timestamp *1000, MACRO REGIME field name fix
- StrategyPage.jsx: 'Open Platform' button contrast raised

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

## Step 5: Push

```bash
git push origin main
```

Railway auto-deploys on push (~90s).

---

## Freqtrade — regime-aware threshold (apply when ready)

`2ddbaef` lowered `MIN_CIS_SCORE` to 55 as a quick fix. The better long-term approach is regime-aware dynamic thresholds in `CometCloudStrategy.py`:

```python
REGIME_THRESHOLDS = {
    "Risk-On":    65,
    "Goldilocks": 65,
    "Easing":     62,
    "Neutral":    58,
    "Tightening": 52,
    "Risk-Off":   50,
    "Stagflation":50,
}

def get_current_regime() -> str:
    # Read from CIS cache or /api/v1/market/macro-pulse
    try:
        import requests
        r = requests.get("https://looloomi.ai/api/v1/market/macro-pulse", timeout=5)
        return r.json().get("macro_regime", "Neutral")
    except Exception:
        return "Neutral"   # safe default

current_regime = get_current_regime()
MIN_CIS_SCORE = REGIME_THRESHOLDS.get(current_regime, 58)
```

This uses CIS score as a relative filter within the regime rather than an absolute bull-market gate. In current Tightening regime: threshold = 52, MKR at 56.8 would trade.
