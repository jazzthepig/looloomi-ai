---
name: tech-stack
description: CometCloud/Looloomi full technology stack reference. Use this skill when working with backend routes, frontend build, data sources, infrastructure, environment variables, or debugging connectivity between components. Triggers include "stack", "FastAPI", "React", "Upstash", "Redis", "CoinGecko", "DeFiLlama", "yfinance", "EODHD", "Gemma4-26b", "Railway", "Supabase", "Binance", "CCXT", "Vite", "Tailwind", "requirements.txt", "env var", "API key", "endpoint", "router". Every connectivity question and "why is X empty" question should load this skill first.
---

# CometCloud Tech Stack — Complete Reference

## Architecture overview

```
Browser / Agent
    │
    ▼
Railway (FastAPI backend + React static)
    ├── /api/v1/*    ← FastAPI routers (src/api/routers/)
    ├── /ws/cis      ← WebSocket (live CIS broadcast)
    └── /            ← React SPA (dashboard/dist/)
         │
         ├── Upstash Redis (read cis:local_scores from Mac Mini)
         ├── CoinGecko API (T2 CIS scoring, market data)
         ├── DeFiLlama (TVL/F pillar)
         ├── Alternative.me (Fear & Greed Index)
         └── yfinance (TradFi prices, VIX, SPY)

Mac Mini M4 Pro (Minimax local engine)
    ├── cis_v4_engine.py    → full 5-pillar scoring
    ├── cis_scheduler.py    → schedules pushes every ~30 min
    ├── cis_push.py         → POST /internal/cis-scores → Upstash Redis
    ├── LM Studio (Gemma4-26b) → Macro Brief narrative
    └── Binance via CCXT    → market data (geo-accessible from Mac Mini)
```

---

## Backend (FastAPI)

**Entry point:** `src/api/main.py` (~100 lines)

**Routers** (`src/api/routers/`):

| File | Prefix | Responsibility |
|------|--------|----------------|
| `cis.py` | `/api/v1/cis` | CIS universe, top assets, compare, debug |
| `market.py` | `/api/v1/market` | Macro pulse, signals, DeFi overview, CoinGecko proxy |
| `intelligence.py` | `/api/v1/intelligence` | Macro brief, VC funding, events |
| `vault.py` | `/api/v1/vault` | Fund channels, deposit memo, portfolio allocation |
| `auth.py` | `/api/v1/auth` | Solana wallet sign-in (nonce + verify) |
| `leads.py` | `/api/v1/leads` | Lead capture + list (Supabase) |
| `share.py` | `/api/v1/share` | OG image generation (Pillow) |
| `internal.py` | `/internal` | `/cis-scores` (Mac Mini push, auth-gated) |
| `agent.py` | `/api/v1/agent` | Agent API (CIS + WebSocket for external agents) |

**CIS data layer:** `src/data/cis/cis_provider.py`
- `calculate_cis_universe()` — computes T2 scores for 85 assets
- `calculate_cis_score()` — single asset 5-pillar scoring
- Uses: CoinGecko (market data), DeFiLlama (TVL), yfinance (TradFi), Alternative.me (FNG)

**Shared data layer:** `src/data/data_layer.py`
- `get_macro_pulse()` — BTC price + FNG + BTC dominance (Redis-cached 300s)
- `get_defi_overview()` — DeFiLlama TVL + L2 + RWA (Redis-cached 300s)
- `get_fear_greed()` — FNG only (Redis-cached 3600s)
- `get_top_yields()` — DeFiLlama yield pools (Redis-cached 600s)

---

## Frontend (React + Tailwind → Vite)

**Root:** `dashboard/`
**Source:** `dashboard/src/`
**Build output:** `dashboard/dist/` ← committed to git, served by Railway

**Key components** (`dashboard/src/components/`):

| Component | Purpose |
|-----------|---------|
| `App.jsx` | Root — sidebar nav, routing (1175 lines) |
| `CISLeaderboard.jsx` | CIS scoring table with grade/signal/LAS |
| `MarketDashboard.jsx` | Asset prices, market overview |
| `IntelligencePage.jsx` | Signal feed, macro brief, VC events |
| `ScoreAnalytics.jsx` | Grade heatmap, sector rotation (lazy-loaded) |
| `PortfolioAllocation.jsx` | Vault strategy + allocation CSV export |
| `ProtocolIntelligence.jsx` | DeFiLlama protocols, CIS-scored |

**Build command:**
```bash
cd dashboard && rm -rf dist/assets && npm run build
```

**Multi-entry (Vite config):** `index.html`, `app.html`, `strategy.html`, `vision.html` are separate entry points.

---

## Data sources

### CoinGecko (primary crypto market data)
- **Used by:** T2 CIS scoring (`cis_provider.py`), MacroPulse, AssetRadar proxy
- **Endpoint:** `https://api.coingecko.com/api/v3/`
- **Auth:** `COINGECKO_API_KEY` header (optional free tier; Pro tier needed for >10 req/min)
- **Rate limits:** 10 req/min free, 500 req/min Pro
- **Key Railway env var:** `COINGECKO_API_KEY` — **if missing, CIS universe returns 0 assets**
- **Binance CCXT:** geo-blocked from Railway US. Mac Mini uses it via CCXT directly.

### DeFiLlama (TVL, protocol data)
- **Used by:** F pillar (TVL), Protocol Intelligence tab, DeFi Overview
- **Endpoint:** `https://api.llama.fi/`, `https://yields.llama.fi/`
- **Auth:** None (public API)
- **Rate limits:** Generous; Redis-cached to be respectful

### Alternative.me (Fear & Greed Index)
- **Used by:** S pillar sentiment, MacroPulse
- **Endpoint:** `https://api.alternative.me/fng/`
- **Auth:** None
- **Note:** May be geo-blocked from Railway US. If null, falls back to 50 (neutral).

### yfinance (TradFi prices + VIX)
- **Used by:** US Equity, US Bond, Commodity, FX, Real Estate, EM Equity scoring
- **Tickers:** SPY, QQQ, BND, GLD, SLV, DJP, UUP, FXE, FXY, FXI, VNQ, IYR, VNQI, EEM, VWO, INDA, EWZ, AAPL, NVDA, MSFT, AMZN, TSLA, VIX
- **Auth:** None (Yahoo Finance)
- **Parallelization:** 5 concurrent requests (asyncio.Semaphore)

### EODHD (TradFi fundamentals)
- **Used by:** Earnings calendar, economic indicators
- **Auth:** `EODHD_API_KEY` — **missing/expired; all cells show "—"**
- **Status:** Offline as of Apr 2026. Key needs rotation.
- **Fallback:** FRED (Federal Reserve) for economic indicators

### Upstash Redis
- **URL:** `https://upward-thrush-73783.upstash.io`
- **Used by:** Mac Mini → Railway bridge, all L2 caches
- **Auth:** `UPSTASH_REDIS_REST_URL` + `UPSTASH_REDIS_REST_TOKEN`
- **Key:** `cis:local_scores` — Minimax writes, Railway reads

### Supabase
- **Project:** `soupjamxlfsmgmmtoeok`
- **Tables:** `cis_scores`, `macro_briefs`, `wallet_profiles`, `leads`, `vault_deposit_intents`
- **Auth:** `SUPABASE_URL` + `SUPABASE_KEY` (service_role)
- **Status:** **env vars missing from Railway; no inserts happening**

---

## Infrastructure

### Railway (production)
- **URL:** `https://web-production-0cdf76.up.railway.app` / `https://looloomi.ai`
- **Deploy trigger:** Push to `main` branch → auto-deploy (~90 seconds)
- **Build command:** `pip install -r requirements.txt`
- **Start command:** `uvicorn src.api.main:app --host 0.0.0.0 --port $PORT`
- **Static files:** `dashboard/dist/` served by FastAPI `StaticFiles` mount

### Mac Mini M4 Pro
- **Specs:** Apple M4 Pro, 48GB unified memory, 1TB SSD
- **AI:** Gemma4-26b via LM Studio (Macro Brief narrative generation, Mac Mini only)
- **Scheduling:** `cis_scheduler.py` cron — runs every 30 min, pushes CIS to Railway
- **Freqtrade:** dry run not yet started (as of Apr 2026)

---

## Railway environment variables

| Variable | Purpose | Status (Apr 2026) |
|----------|---------|-------------------|
| `UPSTASH_REDIS_REST_URL` | Redis bridge | ✅ Set |
| `UPSTASH_REDIS_REST_TOKEN` | Redis auth | ✅ Set |
| `INTERNAL_TOKEN` | Guards `/internal/cis-scores` | ✅ Set |
| `COINGECKO_API_KEY` | CIS T2 scoring | ❌ MISSING — CIS universe empty |
| `SUPABASE_URL` | Score history + leads | ❌ MISSING |
| `SUPABASE_KEY` | Supabase service_role | ❌ MISSING |
| `EODHD_API_KEY` | TradFi prices/fundamentals | ❌ MISSING/EXPIRED |

---

## API surface (public endpoints)

```
GET /api/v1/cis/universe                 → Full CIS leaderboard (all assets)
GET /api/v1/cis/top?limit=N              → Top N assets by CIS score
GET /api/v1/cis/compare?symbols=BTC,ETH  → Side-by-side comparison
GET /api/v1/cis/debug/datasources        → Diagnose T2 data availability
GET /api/v1/market/macro-pulse           → BTC + FNG + dominance + regime
GET /api/v1/market/signals               → Signal feed (7 concurrent sources)
GET /api/v1/market/defi-overview         → DeFiLlama TVL breakdown
GET /api/v1/intelligence/macro-brief     → Latest macro narrative (LM Studio)
GET /api/v1/intelligence/vc-funding      → VC funding rounds (DeFiLlama)
GET /api/v1/vault/funds                  → Fund channel info
POST /api/v1/leads/capture               → Lead capture form
GET /api/v1/agent/cis                    → Agent API (CIS + LAS + metadata)
WS  /ws/cis                              → Real-time CIS broadcast
GET /.well-known/agent.json              → A2A discovery card
```

---

## Common debugging

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `CIS universe: 0 assets` | `COINGECKO_API_KEY` missing from Railway | Add key in Railway → Variables |
| `btc_price: null` in macro-pulse | CoinGecko rate limit hit | Check Redis cache; key helps |
| `fear_greed_value: null` | Alternative.me geo-blocked | Falls back to 50 automatically |
| T1 badge missing (showing T2) | Mac Mini scheduler not running | Check `cis_scheduler.py` on Mac Mini |
| Economic indicators all "—" | EODHD key missing/expired | Minimax to rotate EODHD key |
| Supabase inserts failing | Env vars not set in Railway | Jazz to add SUPABASE_URL + SUPABASE_KEY |
| `UnboundLocalError: fng_value` | Old bug (fixed in 11dd71c) | Deploy latest main |
