# Deploy Verifier — Agent Memory

## Railway production (as of 2026-04-12)

### Latest deployed commit
- Live on Railway: `6c09dad` (Phase A: compliance skills + 12 violation fixes)
- Pending push (HEAD.lock issue): Phase B+C commits (hooks + subagents) + dist rebuild

### Railway environment variable status
| Variable | Status |
|---|---|
| UPSTASH_REDIS_REST_URL | ✅ Set |
| UPSTASH_REDIS_REST_TOKEN | ✅ Set |
| INTERNAL_TOKEN | ✅ Set |
| COINGECKO_API_KEY | ❌ NOT YET SET — CIS universe empty without it |
| SUPABASE_URL | ❌ NOT YET SET |
| SUPABASE_KEY | ❌ NOT YET SET |
| EODHD_API_KEY | ✅ Set (added 2026-04-12) |

### Known production health (as of 2026-04-12)
- CIS Universe: ❌ EMPTY — COINGECKO_API_KEY missing + Mac Mini not pushing
- Macro Pulse: ✅ LIVE — BTC=$68,795, F&G=8 (Extreme Fear), Dom=56.3%
- Signal Feed: ✅ LIVE — 19 signals with full data
- DeFi Overview: ✅ LIVE — $92B TVL
- Share/OG Image: ✅ Endpoint mounted (share_router added in src/api/main.py)

### Fastest path to full health
1. Jazz: Add COINGECKO_API_KEY to Railway environment variables
2. Jazz: Add SUPABASE_URL + SUPABASE_KEY to Railway
3. Minimax: Confirm cis_scheduler.py is running and pushing to /internal/cis-scores

## Typical Railway deploy behavior
- Auto-deploys on push to main branch
- Build time: ~45–90 seconds
- After deploy: Mac Mini scores take up to ~30min to appear (next scheduler cycle)
- Redis TTL: 2h — scores persist across deploys if pushed within 2h window

## Health check command (quick)
```bash
# From Mac Mini terminal or any machine with curl
curl -s https://[RAILWAY_URL]/api/v1/market/macro-pulse | python3 -m json.tool | head -20
curl -s https://[RAILWAY_URL]/api/v1/cis/universe | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'Assets: {len(d.get(\"assets\", []))}, Source: {d.get(\"source\")}')"
```

## Routers registered in main.py (as of 6c09dad)
market_router, cis_router, vault_router, analytics_router, auth_router,
leads_router, quant_router, agent_router, internal_router, share_router

(share_router was missing and added — verify it's present in main.py before each deploy)
