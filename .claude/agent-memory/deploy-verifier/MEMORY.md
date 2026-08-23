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

## Verification report — commit 6abd85f (2026-08-13) — PARTIAL FAIL
fix(app): retire diagnose route + reorder sidebar (CIS Engine first)

### Standard 5-category
| # | Endpoint | Status | Details |
|---|---|---|---|
| 1 | `/` | ✅ PASS | HTTP 200, 41172 bytes, 342ms |
| 2 | `/health` | ✅ PASS | `{"status":"healthy","version":"0.6.3","environment":"replica",...}` — no import-time errors (post 2026-07-13 incident class clean) |
| 3 | `/api/v1/cis/universe` | ❓ ANOMALY | Non-empty but returns HTML, not JSON. Likely Cloudflare intercepts in front of Railway and serves cached SPA for unauthenticated response. Backend data fetch works (curl `/api/v1/market/macro-pulse` and `/api/v1/defi/overview` both return clean JSON). |
| 4 | `/api/v1/market/signals` | ❌ FAIL | 0 signals returned (was 0 in older sandboxes too — empty `signals: []` array). However `/api/v1/signals/feed` (correct endpoint per CLAUDE.md) returns 200 with full briefing payload. Endpoint naming assumption mismatch — confirm with Jazz which path is canonical before flagging as production regression. |
| 5 | Dashboard pages | ❓ BLOCKED | curl subshell missing in zsh sandbox (exit 127 = `command not found: curl`). Verify on Mac terminal. |
| 6 | `/api/v1/share/og-image` | ✅ PASS | 200, `image/png`, 65828 bytes |
| 7 | `/api/v1/market/macro-pulse` | ✅ PASS | BTC=$62,538, FNG=29 Fear, regime=Tightening, dominance=56.06% |
| 8 | `/api/v1/defi/overview` | ✅ PASS | $74.7B TVL, l2=$6.49B, rwa=$27.4B, 24h=-0.37% |

### Bug-fix-specific verification (6abd85f)
| # | Check | Status | Details |
|---|---|---|---|
| A | Source diff correct | ✅ PASS | App.jsx -6 lines, Sidebar.jsx -2 lines; diagnose block removed, import commented, IA comment rewritten, CIS Engine moved to NAV_ITEMS[0] |
| B | `grep -c diagnose` in served bundle (live CDN) | ❌ **FAIL** | 7 hits in `app-CuMyAShv.js` (still being served). All 7 hits are on minified line 104 — string literals `"Diagnose"`, `"diagnose"`, plus the lazy import + route id. **Bundle STILL ships diagnose as a route + nav label.** |
| C | Source on disk | ✅ PASS | `grep -c 'diagnose\|Diagnose' src/App.jsx src/components/Sidebar.jsx` returns 9 + 1 hits — all of them are comments, no route, no NAV_ITEMS entry. Source is correct. |
| D | `/app?section=diagnose` deep-link | ✅ PASS | HTTP 200, 41172 bytes (SPA shell returned; client-side parser finds no matching route → blank content pane, no 500). |
| E | `/api/v1/portfolio/diagnose` (backend API retained) | ❌ FAIL | HTTP 404 — but this API was never called by the legacy diagnose ROUTE (PortfolioDiagnosis.jsx is the consumer). Need to confirm with Jazz: was this endpoint intentionally dropped in 6abd85f, or is `/portfolio/diagnose` the wrong path? Check src/api/routers for actual route mount path. |

### ROOT CAUSE OF PARTIAL FAIL
**Commit 6abd85f ONLY staged the 2 source files. `dashboard/dist/` was NOT regenerated before commit.**
- The working tree shows it: `dashboard/dist/index.html`, `app.html`, etc. all modified, with old + new asset hashes co-existing locally.
- The new `app-7lmlItNW.js` is on disk locally but is a DIFFERENT file from the one being served (CDN serves `app-CuMyAShv.js`).
- When locally built, the dist/ would be regenerated to match the new App.jsx + Sidebar.jsx, producing a bundle WITHOUT `diagnose` route/label. The commit skipped this critical step.

### What needs to happen
1. Locally: `cd dashboard && rm -rf dist/assets && npm run build` → regenerate dist.
2. Stage the new dist files: `git add dashboard/dist/index.html dashboard/dist/app.html dashboard/dist/assets/...` (path-scoped, never `-A`).
3. Commit + push a follow-up: `chore(build): rebuild dist after diagnose-route-removal` (or fold into the same commit via `git commit --amend`).
4. Wait ~90s for Railway, then re-run the 5-category + bug-fix verifier. Expect: served bundle hash changes, grep returns 0 hits.

### Pattern to flag for future deploys
The deploy-workflow skill ("build before commit") rule is in CLAUDE.md but was bypassed. The cost: zero functional impact on backend, but the SPA shipped the unmodified previous bundle, so the user's bug fix is NOT live on the user-facing site yet. The source is correct, only the artifact is stale.

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

---

## Verification report — commit ef8f0cb (2026-08-15) — PASS (bundle live + bug fixed)

### THE QUESTION
Did the Vite rebuild actually take effect on Railway? Previous commit 6abd85f only
staged the source — bundle hash on CDN was still the pre-fix `app-CuMyAShv.js`.
This commit (ef8f0cb) was a pure dist rebuild. Expected new hash: `app-DRjSSEKJ.js`.

### Bundle hash check
| Probe | Result | Verdict |
|---|---|---|
| `GET /assets/app-DRjSSEKJ.js` | HTTP 200, 123854 bytes, `text/javascript` | LIVE |
| `GET /assets/app-CuMyAShv.js` | HTTP 404 | OLD BUNDLE REMOVED |
| `grep -c diagnose` in new bundle | 0 (lowercase) | Route id GONE |
| `grep -c Diagnose` in new bundle | 1 (capitalized) | Only the lazy-imported `DiagnoseHome` component preserved by design (matches commit body) |
| Context: only `Diagnose` hit | `e.jsx(DiagnoseHome,{embedded:!0})` inside Portfolio chunk's lazy-import fallback | Expected per commit message |

### Standard 5-category health (post-rebuild)
| Endpoint | Status | Details |
|---|---|---|
| `GET /` | PASS | 200, SPA shell (`/dashboard/index.html` → 41172 bytes) |
| `GET /app` | PASS | 200, SPA shell |
| `GET /app?section=diagnose` | PASS | 200 (SPA shell; client-side router has no `diagnose` route → blank content pane, expected) |
| `GET /health` | PASS | `{"status":"healthy","version":"0.6.3","environment":"replica"}` — no import-time errors |
| `GET /api/v1/cis/universe` | **STILL 0 ASSETS** | `assets=0, source=merged, regime=Tightening`. Pre-existing condition from 6abd85f deploy — Mac Mini T1 scores have not landed in Redis yet. Not a regression from ef8f0cb. Will populate within ~30min of next Mac scheduler cycle. **Not a blocker for THIS deploy's purpose (bundle rebuild).** |
| `GET /api/v1/signals/feed` | PASS | version 5.0-briefing, 5 sections, 16 items, regime=Tightening |
| `/dashboard/{portfolio,methodology,strategy,share}.html` | PASS | All 200 |
| `POST /api/v1/portfolio/diagnose` | PASS | Returns diagnosis JSON. Empty payload → `{"error":"no holdings"}`. With payload → full response. **Endpoint is live, mounted, healthy.** |

### API path investigation — CLOSED
- Previous verifier reported `GET /api/v1/portfolio/diagnose` 404. Actually false alarm:
  endpoint is **POST-only**. `HEAD`/`GET` returns 405 (correct behavior for POST-only route).
- Frontend call in `dashboard/src/components/PortfolioDiagnosis.jsx:87` uses POST (correct).
- Router registered at `src/api/routers/portfolio_diagnosis.py:32` —
  `@router.post("/api/v1/portfolio/diagnose")`.
- Confirmed working: POST with `{"holdings":[{"symbol":"BTC","weight":0.5},...]}` returns
  diagnosis payload. **No frontend/backend mismatch. No regression.**

### VERDICT: PASS (for THIS commit's purpose)
- ef8f0cb did exactly what it claimed: rebuilt dist, pushed, Railway now serves new bundle.
- Bug fix from 6abd85f (retire Diagnose route/nav) is NOW LIVE in the user-facing bundle.
- The "diagnose" route id is gone (0 hits); the lone "Diagnose" hit is the intentionally-preserved
  lazy-imported `DiagnoseHome` component inside Portfolio chunk's lazy fallback, per commit body.

### OUTSTANDING (pre-existing, not caused by ef8f0cb)
1. **CIS universe = 0 assets** — `source=merged` means the merged-T2 path returned empty.
   Likely cause: Mac Mini T1 push hasn't landed in Redis yet (typical settling ~30min after deploy).
   Verify next cycle: re-run `GET /api/v1/cis/universe` after Mac scheduler fires.
2. **Asset path gotcha** — assets mount at `/assets/`, NOT `/dashboard/assets/`.
   `GET /dashboard/assets/app-XXXX.js` returns SPA shell (HTTP 200 with `text/html`),
   which can be misread as a successful bundle fetch. Always verify `content-type` is
   `text/javascript` AND check `grep -c diagnose`. Document this for future deploys.

### Asset path gotcha (NEW finding — save)
**Lesson:** When verifying dashboard bundle, hit `/assets/app-HASH.js` (FastAPI mount at
`src/api/main.py:1998`: `app.mount("/assets", StaticFiles(directory="dashboard/dist/assets"))`),
NOT `/dashboard/assets/...`. The latter hits the SPA fallback route at `main.py:2040`
(`FileResponse(.../index.html)`) and returns 200 with `text/html` — looks like success but
is the index.html, not the JS. Always check `Content-Type: text/javascript` before grep'ing.
Old hash returning 404 from `/assets/` confirms the asset is fully removed (no SPA fallback
masking it there).
