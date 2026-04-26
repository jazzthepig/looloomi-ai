# COMMIT_READY.md

Push-gate only. Seth stages files from Cowork; Minimax clears lock + commits + pushes.

---

## Pending commit (staged, ready to push)

Files staged by Seth — waiting on lock clear:
- `COMMIT_READY.md` — reformatted to push-gate (no more 5-step sequence for Minimax)
- `MINIMAX_SYNC.md` — §4 deploy verification tasks, §5 HEAD updated to `01327bc`

```bash
# 1. Clear FUSE lock (Cowork VM leaves this)
rm -f ~/projects/looloomi-ai/.git/index.lock

# 2. Commit (files already staged)
cd ~/projects/looloomi-ai
git commit -m "chore(harness): COMMIT_READY.md → push-gate; MINIMAX_SYNC.md §4/§5 updated

- COMMIT_READY.md: push-gate only format — Seth commits, Minimax pushes
- MINIMAX_SYNC.md §4: P0 deploy verification + P1 auth E2E + Freqtrade dynamic threshold
- MINIMAX_SYNC.md §5: HEAD = 01327bc, commit timeline updated

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"

# 3. Push
git push origin main
```

---

## After push — deploy verification (P0 from §4 MINIMAX_SYNC.md)

```bash
# Health check
curl https://looloomi.ai/health | python3 -m json.tool

# MCP mounted?
curl -I https://looloomi.ai/mcp/sse

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
