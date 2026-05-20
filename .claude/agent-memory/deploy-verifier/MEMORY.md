# Deploy Verifier — Agent Memory

## CRITICAL: Startup crash incident — 2026-05-04

### Crash cause (platform was fully down, all endpoints returning errors)
Two import errors at startup caused FastAPI to fail completely:

1. `src/api/routers/cis.py` imported `supabase_get_recent_scores` from `store.py`
   but the function was never implemented in `store.py` (added in Simons Upgrade P1.1
   without writing the corresponding store.py function).
   FIX: Added `supabase_get_recent_scores(symbols, n=30) -> dict` to store.py.
   It does a bulk Supabase query using PostgREST `in.(...)` filter.

2. `src/api/routers/agent.py` line 539: `Response` used as type hint in
   `get_pillar_fitness()` but `Response` was missing from the fastapi import line.
   FIX: Added `Response` to the `from fastapi import ...` line.

### Fix commit
`aac9008` — pushed to main 2026-05-04. Railway auto-deploys on main push.

### Symptom signature for future reference
- All endpoints return errors (not just one router)
- Frontend shows "REGIME · LOADING" and "0 ASSETS" — CIS universe empty
- This means FastAPI never started, not a data issue
- Check: `python3 -c "import src.api.main"` locally to catch import errors before push

### Network note
This sandbox environment has NO outbound internet access — all curl requests to
external URLs (including looloomi.ai and web-production-0cdf76.up.railway.app) return
HTTP 403 with `x-deny-reason: host_not_allowed` from the sandbox's network egress
filter. Cannot directly probe live endpoints. Use local import testing instead.

---

## Verification report — commit cf9cc52 (2026-05-19)

### Result: PASS — all 5 checks green

| Endpoint | Status | Details |
|---|---|---|
| `/health` | ✅ PASS | `{"status":"healthy","version":"0.6.2","sources":["binance","defillama","alternative.me","moralis","etherscan"]}` |
| `/api/v1/cis/universe` | ✅ PASS | 58 assets, all T1 (Mac Mini engine), regime=Tightening, compliance-safe signals (OUTPERFORM/NEUTRAL/UNDERPERFORM only), no BUY/SELL/ACCUMULATE |
| `/api/v1/market/prices` | ✅ PASS | BTC=$76,819, ETH=$2,133 — live Binance data |
| `/api/v1/defi/overview` | ✅ PASS | $82.9B TVL, l2_tvl=$6.46B, rwa_tvl=$27.1B, 24h=-0.31% |
| `/api/v1/defi/protocols` | ✅ PASS | 14 protocols scored, DeFiLlama live TVL, logos + URLs present |

### Notable changes from previous deploy (223c865)
- CIS universe: 84 → 58 assets (Mac Mini now scoring 58 assets, no T2 Railway fallback in use)
- Asset mix: Heavy TradFi/commercial assets at top (USO, NVDA, GOOGL, AMZN, SPY, QQQ, AAPL, MSFT, TSLA, META) — all with price=0, volume=0 (static data, not live)
- Crypto assets still present in lower ranks: BTC (62.2, B), ETH (48.3, UNDERPERFORM), SOL (47.4), ADA (42.4)
- All signals compliance-safe: OUTPERFORM/NEUTRAL/UNDERPERFORM only
- Pillar data: O pillar consistently null across all assets (expected — on-chain/risk pillar not populated)
- F pillar: Fixed at 50 for crypto/L1/L2, 55.8 for US Equities, 70 for DeFi, 72 for US Bonds — seems hardcoded or limited data source

### Potential concerns (non-blocking)
1. **Pillar O always null** — on-chain/risk pillar not being populated. May be intentional (T1 engine not computing it) or data gap.
2. **F pillar binary** — 50 (crypto/L1/L2/commodity) vs 55.8 (equities) vs 70 (DeFi) vs 72 (bonds) — appears formulaic, not market-derived. Could indicate limited fundamental data feed.
3. **Top assets are TradFi ETFs with price=0** — these score well on low-volatility characteristics (A pillar = 100 for USO/GOOGL) but have no live price data. Frontend may show 0 for these.
4. **No T2 fallback** — 58 vs old 84. If Mac Mini scheduler is down, Railway would serve 0 assets. Monitor.

### CIS scoring state (as of 2026-05-19)
- Top: USO B+ (70.9), NVDA B+ (68.5), GOOGL B+ (68.4) — all non-crypto
- BTC: 62.2 (B, NEUTRAL) — raw_cis_score=46.34
- ETH: 48.3 (C+, UNDERPERFORM) — raw_cis_score=34.15
- Lowest: OP (39.9), POL (40.8), AAVE (41.1) — all C range
- Regime threshold for trades: 52 (Tightening) — only USO(70.9), NVDA(68.5), GOOGL(68.4), AMZN(68.4), SPY(68.2), QQQ(68.2), PENDLE(67.7), INJ(66.0), CPER(65.9), AAPL(65.3) pass

### Railway env vars (assumeunchanged from 2026-04-26 unless Jazz updated)
- UPSTASH_REDIS_REST_URL: ✅ Set
- UPSTASH_REDIS_REST_TOKEN: ✅ Set
- INTERNAL_TOKEN: ✅ Set
- COINGECKO_API_KEY: ✅ Set
- SUPABASE_URL: ✅ Set
- SUPABASE_KEY: ✅ Set
- EODHD_API_KEY: ❓ Unknown (may have been updated)

### Network note (outdated — agent can now reach Railway)
Previous memory stated sandbox has no outbound access. Current session CAN reach
web-production-0cdf76.up.railway.app directly. Cloudflare bypass not needed for Railway
direct URL.

---

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
- MCP Server: ✅ LIVE — Verified via Railway direct URL. HTTP 405 on HEAD request = correct behavior.
  SSE endpoint is GET-only; 405 confirms route is registered and mounted. Phase 2.2 complete.

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
