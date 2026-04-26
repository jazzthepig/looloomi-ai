# COMMIT_READY.md

Push-gate only. Seth stages files from Cowork; Minimax clears lock + commits + pushes.

---

## Pending commit (staged, ready to push)

Files staged by Seth — waiting on lock clear:
- `src/api/main.py` — added `/api/v1/health` endpoint (bypasses Cloudflare SPA cache)
- `MINIMAX_SYNC.md` — P0 verification updated: use `/api/v1/health` + Railway direct URL for MCP
- `CLAUDE.md` — production health section updated (HEAD = 223c865, MCP status, BTC price)
- `.claude/agent-memory/deploy-verifier/MEMORY.md` — updated with Apr 26 production state

```bash
# 1. Clear FUSE lock (Cowork VM leaves this)
rm -f ~/projects/looloomi-ai/.git/index.lock

# 2. Stage COMMIT_READY.md (lock blocked this from Cowork — all other files already staged)
cd ~/projects/looloomi-ai
git add COMMIT_READY.md

# 3. Commit
git commit -m "fix(api): add /api/v1/health to bypass Cloudflare SPA cache; update deploy docs

- main.py: /api/v1/health mirrors /health — survives Cloudflare CDN caching
- MINIMAX_SYNC.md §4: verification commands updated to use /api/v1/health
  and Railway direct URL for MCP SSE check
- CLAUDE.md: production health HEAD corrected to 223c865, MCP status clarified
- deploy-verifier MEMORY.md: full Apr 26 state snapshot

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"

# 4. Push
git push origin main
```

---

## After push — deploy verification

```bash
# Health check (API-prefixed — bypasses Cloudflare)
curl https://looloomi.ai/api/v1/health | python3 -m json.tool
# Expect: "version": "0.4.3", "status": "healthy"

# MCP mounted? (Railway direct — bypasses Cloudflare)
curl -I https://web-production-0cdf76.up.railway.app/mcp/sse
# Expect: HTTP 200 + Content-Type: text/event-stream
# If 404 JSON → check Railway build log for "[MCP] ⚠️ Not mounted: ..."

# Auth E2E
python ~/projects/looloomi-ai/scripts/test_auth_e2e.py

# CIS universe
curl https://looloomi.ai/api/v1/cis/universe | python3 -c \
  "import json,sys; d=json.load(sys.stdin); a=d.get('assets',[]); print(f'Assets: {len(a)}, source: {d.get(\"source\")}')"
```

---

## Freqtrade — regime-aware threshold (P1 task 16 in MINIMAX_SYNC.md)

Replace `MIN_CIS_SCORE = 55` in `CometCloudStrategy.py`:

```python
REGIME_THRESHOLDS = {
    "Risk-On": 65, "Goldilocks": 65, "Easing": 62,
    "Neutral": 58,
    "Tightening": 52, "Risk-Off": 50, "Stagflation": 50,
}
def get_current_regime():
    try:
        import requests
        r = requests.get("https://looloomi.ai/api/v1/market/macro-pulse", timeout=5)
        return r.json().get("macro_regime", "Neutral")
    except Exception:
        return "Neutral"

MIN_CIS_SCORE = REGIME_THRESHOLDS.get(get_current_regime(), 58)
```

In current Tightening regime: threshold = 52 → MKR (56.8) passes immediately.
