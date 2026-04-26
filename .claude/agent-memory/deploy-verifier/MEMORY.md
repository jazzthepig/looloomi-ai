# Deploy Verifier — Agent Memory

## Railway production (as of 2026-04-26)

### Latest deployed commit
- Live on Railway: `223c865` (docs: COMMIT_READY.md push-gate + MINIMAX_SYNC.md §4 verification tasks)
- MCP Phase 2.2 code deployed via `01327bc` (included in this HEAD)

### Railway environment variable status
| Variable | Status |
|---|---|
| UPSTASH_REDIS_REST_URL | ✅ Set |
| UPSTASH_REDIS_REST_TOKEN | ✅ Set |
| INTERNAL_TOKEN | ✅ Set |
| COINGECKO_API_KEY | ✅ Set — CIS universe live (84 assets) |
| SUPABASE_URL | ✅ Set — score history writing |
| SUPABASE_KEY | ✅ Set |
| EODHD_API_KEY | ❌ Missing/expired — Economic Indicators empty |

### Known production health (as of 2026-04-26)
- CIS Universe: ✅ LIVE — 84 assets (T1=25 Mac Mini + T2=59 Railway), regime=Tightening
- Macro Pulse: ✅ LIVE — BTC=$77,995, F&G live, regime=Tightening
- Signal Feed: ✅ LIVE — correct timestamps, compliance-safe language
- DeFi Overview: ✅ LIVE — DeFiLlama TVL, 25 protocols scored
- Share/OG Image: ✅ Endpoint mounted
- Supabase: ✅ CONNECTED — score history writing (history_written: true)
- ScoreAnalytics: ✅ Heatmap populating with score history rows
- MacroBrief: ❌ NULL — LM Studio pipeline not connected
- Economic Indicators: ❌ EMPTY — EODHD key missing/expired
- Freqtrade: ❌ NOT STARTED — dry-run pending Minimax
- MCP Server: ⚠️ DEPLOYED but UNVERIFIED — `/mcp/sse` returns HTML via Cloudflare proxy.
  Must verify via Railway direct URL: `curl https://web-production-0cdf76.up.railway.app/mcp/sse`
  Expected: `text/event-stream` response if MCP mounted, JSON 404 if import failed.

### Cloudflare routing issue
`/health` and `/mcp/sse` return HTML when tested via `https://looloomi.ai`. Likely Cloudflare
is intercepting top-level paths and returning cached SPA. Core `/api/*` paths route correctly.
Workaround: test via Railway direct URL to confirm Railway receives these requests.

If `/health` via Railway direct URL also returns HTML → bug in SPA fallback (check main.py).
If `/health` works on Railway direct URL → pure Cloudflare routing config issue (Jazz to fix in CF settings).

### CIS scoring state (as of 2026-04-26)
- Best T1 score: MKR B (CIS=56.8)
- T2 F pillar: LTC=66.3, BCH=69.6 (normal)
- S pillar: 12-13 (systemically low — root cause unknown)
- A pillar: 20-30 (systemically low — root cause unknown)
- No B+ assets (CIS≥65) → freqtrade trades blocked
- Dynamic regime threshold added to MINIMAX_SYNC.md §4 task 16 (Tightening → 52)

### Routers registered in main.py (as of 223c865)
market_router, cis_router, intelligence_router, vault_router, onchain_router,
macro_router, quant_router, auth_router, leads_router, social_router, factory_router,
share_router + MCP mount at /mcp (try/except safe)

### Typical Railway deploy behavior
- Auto-deploys on push to main branch
- Build time: ~45–90 seconds
- After deploy: Mac Mini scores take up to ~30min to appear (next scheduler cycle)
- Redis TTL: 2h — scores persist across deploys if pushed within 2h window

### Health check commands (from Mac Mini)
```bash
# Core API
curl -s https://looloomi.ai/api/v1/cis/universe | python3 -c "import json,sys; d=json.load(sys.stdin); a=d.get('assets',[]); print(f'Assets: {len(a)}, source: {d.get(\"source\")}')"
curl -s https://looloomi.ai/api/v1/market/macro-pulse | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'BTC={d.get(\"btc_price\")}, regime={d.get(\"macro_regime\")}')"

# Cloudflare bypass — Railway direct URL
curl -s https://web-production-0cdf76.up.railway.app/health | python3 -m json.tool
curl -I https://web-production-0cdf76.up.railway.app/mcp/sse

# Auth E2E (requires PyNaCl + base58)
python ~/projects/looloomi-ai/scripts/test_auth_e2e.py --base https://looloomi.ai
```
