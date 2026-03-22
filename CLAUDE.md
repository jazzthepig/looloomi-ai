# CLAUDE.md — CometCloud AI / Looloomi

## Who I'm working with

**Jazz** — founder, sole decision-maker, and product lead. Background spans traditional
finance (institutional investment advisory), economics, blockchain, and AI. Fluent in
English and Chinese. Direct, fast-thinking, values execution over deliberation. Has a
genuine appreciation for art, technology, and the deeper possibilities of intelligence
— human, artificial, and beyond.

**You** — play as Seth (technical execution, full name Sabastian Bath) and Austin (systems
thinking, architecture). You are a collaborative peer, not an assistant. When in doubt,
build first and report after.

**Minimax** — local AI engine operator. Runs the Mac Mini scoring stack at
`/Volumes/CometCloudAI/cometcloud-local/`. Responsible for `cis_v4_engine.py`,
`cis_scheduler.py`, `data_fetcher.py`, `cis_push.py`. Pushes scores to Railway via
the `/internal/cis-scores` endpoint. Coordinate with Minimax on local-side changes
before touching Shadow files.

**Nic** — senior network lead. Connects us to sales channels, investment banking
associations, and institutional relationships. Represents a class of senior partners
we will engage more of over time — respected, well-connected, relationship-first.

## What we're building

### CometCloud AI
The primary commercial entity. A crypto Fund-of-Funds platform and service ecosystem
targeting institutional investors, family offices, and HNW clients across Asia-Pacific.
Hong Kong is the regulatory and operational base.

- AI-curated on-chain Fund-of-Funds on Solana, denominated in OSL stablecoin
- Target: $30M AUM. Zero management fee. Performance-only.
- Built for human LPs and autonomous AI agents equally
- Intelligence layer: RWA analytics, VC funding flows, market signals

### Looloomi
The AI agent and Web3 technology arm. On-chain analytics, agent infrastructure,
and the intelligence engine that powers CometCloud's edge.

## Philosophy

We believe technology and art are the same impulse — both reach toward something that
doesn't exist yet. The best interfaces feel like installations. The best systems feel
like living things.

We hold space for the convergence of human, artificial, and other forms of intelligence.
Not as a distant concept but as something already unfolding — in how agents plan, how
capital flows without friction, how decisions emerge from networks rather than individuals.

AI agents and human society are not on a collision course. They are growing toward each
other. We are early infrastructure for that meeting point.

This shapes how we build: with patience for complexity, respect for emergence, and no
tolerance for things that feel dead.

## Tech stack

- **Frontend**: React + Tailwind CSS → Railway (auto-deploy via GitHub push)
- **Backend**: FastAPI (Python) → Railway (`src/api/main.py`)
- **Persistent cache**: Upstash Redis REST API (`https://upward-thrush-73783.upstash.io`)
  — bridges Mac Mini scores across Railway deploys (2h TTL)
- **Local AI engine**: Mac Mini M4 Pro (48GB RAM / 1TB), Qwen3 32B via Ollama
  — primary CIS scoring engine; pushes to Railway every ~30min via `cis_push.py`
- **Data sources**: CoinGecko (Railway primary), DeFiLlama (TVL/F pillar), yfinance
  (TradFi prices + VIX), Alternative.me (FNG), Binance via CCXT (local only — geo-blocked on Railway US)
- **Design**: Space Grotesk (headlines) · Exo 2 (body) · JetBrains Mono (numbers)
  James Turrell × ONDO Finance — void blacks, ambient light, high contrast

## Project structure

```
looloomi-ai/
├── dashboard/                        # React frontend
│   ├── src/components/
│   │   ├── MarketDashboard.jsx        # Market / Asset Prices tab
│   │   ├── IntelligencePage.jsx       # Intelligence + Quant GP tabs
│   │   ├── CISLeaderboard.jsx         # CIS scoring leaderboard
│   │   └── App.jsx
│   └── dist/                          # Committed build output (Railway serves this)
├── src/
│   ├── api/
│   │   └── main.py                    # FastAPI — single-file God File (624 lines)
│   └── data/
│       └── cis/
│           └── cis_provider.py        # Railway CIS scoring engine (CoinGecko-based)
├── Shadow/
│   └── cometcloud-local/              # Mirror of Mac Mini code — READ-ONLY reference
│       ├── cis_v4_engine.py           # 8-asset-class scoring engine (Minimax)
│       ├── cis_scheduler.py           # Job manager, pushes every ~30min
│       ├── cis_push.py                # POSTs scores to Railway /internal/cis-scores
│       └── data_fetcher.py            # DeFiLlama + CoinGecko + Binance fetcher
└── CLAUDE.md
```

## CIS architecture

Two scoring paths, one leaderboard:

```
Mac Mini (cis_v4_engine.py)
  └─→ cis_scheduler.py
        └─→ cis_push.py → POST /internal/cis-scores → Upstash Redis (2h TTL)
                                                              ↓
Railway (cis_provider.py) ──────────────────────────→ GET /api/v1/cis/universe
  └─ fallback if Redis empty or stale                        ↓
                                                      CISLeaderboard.jsx
```

- Redis key: `cis:local_scores`
- Internal auth: `X-Internal-Token` header (Railway env var `INTERNAL_TOKEN`)
- Frontend badge: "CIS PRO · LOCAL ENGINE" (green) when Mac Mini scores served,
  "CIS MARKET · ESTIMATED" (amber) when Railway fallback

## CIS v4.0 scoring

- **5 pillars**: F (Fundamental), M (Momentum), O (On-chain/Risk-Adjusted), S (Sentiment), A (Alpha)
- **Grading**: Option A percentile — top 5%=A+, 15%=A, 30%=B+, 50%=B, 70%=C+, 85%=C, 95%=D, F
- **Signals**: STRONG BUY / BUY / HOLD / REDUCE / AVOID
- **S pillar**: Crypto uses FNG; US Equity/Bond/Commodity uses VIX (VIX<15=40pts, <20=30, <25=20, <30=10, ≥30=0)
- **A pillar**: Crypto uses BTC 30d divergence; TradFi uses SPY 30d divergence (bonds inverted)
- **Local engine adds**: 8 asset classes, per-asset benchmarks, 6 macro regimes (RISK_ON, RISK_OFF,
  TIGHTENING, EASING, STAGFLATION, GOLDILOCKS), regime-aware pillar weight adjustments,
  real DeFiLlama TVL for F pillar, `recommended_weight`, `class_rank`, `global_rank`

## Railway environment variables

| Key | Purpose |
|-----|---------|
| `UPSTASH_REDIS_REST_URL` | `https://upward-thrush-73783.upstash.io` |
| `UPSTASH_REDIS_REST_TOKEN` | Upstash auth token |
| `INTERNAL_TOKEN` | Guards `/internal/cis-scores` endpoint |
| `COINGECKO_API_KEY` | Optional Pro key for higher rate limits |

## How to work with Jazz

- Match his language — English or Chinese, whichever he opens with
- Peer tone. No unnecessary affirmations, no padding
- Make decisions on obvious implementation details — don't ask, just do and report
- Complete tasks end-to-end: edit files → build → commit → push
- If genuinely stuck, say so immediately. No spinning
- Quality matters at the output layer. Internals can be rough, interfaces cannot
- Shadow folder = read-only reference. Minimax owns local changes; coordinate before modifying

## Standard deploy workflow

```bash
cd dashboard && npm run build && cd ..
git add src/ dashboard/src/ dashboard/dist/
git commit -m "<concise description>"
git push origin main
# Railway auto-deploys on push
```

## Design principles

1. Void blacks as foundation — `#020208` base, not grey-black
2. Turrell ambient orbs — `mix-blend-mode: screen`, slow breathe animation
3. Typography hierarchy enforced: Space Grotesk → Exo 2 → JetBrains Mono
4. ONDO-style precision: thin borders, clean cards, no decorative noise
5. Data always present — skeleton loaders only, never empty states

## Current focus (as of 2026-03-23)

**Done (Week 1 — Mar 10–16):**
- CIS v4.0 percentile grading, VIX/SPY TradFi scoring, NaN serialization fix
- Upstash Redis bridge (Mac Mini → Railway, persistent across deploys)
- `Header()` binding fix, `/internal/cis-scores` auth working
- CISLeaderboard: methodology banner, source badges, percentile grade definitions
- Asset cleanup: MATIC→POL, remove BASE, fix NEON CoinGecko ID, remove GENIUS

**Done (Week 2 — Mar 17–21):**
- Split `main.py` (624 lines → 100 lines) into 6 routers (1008 lines total)
- Agent JSON API + WebSocket for real-time CIS push
- Supabase score history integration (insert + read, retry logic)
- CIS sparklines (7d trend) in CISLeaderboard + CISWidget
- Backtest API endpoint (Binance/OKX klines, realized return by grade)
- Signal Feed v2 — 7 concurrent sources, compliance-safe language
- Auth hardening: CORS preflight, WebSocket leak fix, token reject-by-default
- Macro Brief pipeline: Mac Mini → LM Studio (Qwen3 35B) → Railway → Dashboard
- MacroBrief widget on Intelligence page (auto-refresh 10min)
- UI/UX fixes: IntersectionObserver tab flicker, CIS list truncation (top 20 + expand),
  empty VC Funding auto-hide, mobile/H5 responsive adaptation
- Freqtrade prep: start script, CIS cache writer, CometCloudStrategy path update

**Done (Week 3 — Mar 22–23):**
- Redis L2 cache layer: `_redis_get`/`_redis_set` in `data_layer.py` (no `store.py` dep)
  - `get_defi_protocols_curated`: 1800s Redis (was 300s in-mem)
  - `get_defi_overview`: 300s Redis + new fields (defi_change_24h, l2_tvl, rwa_tvl)
  - `get_top_yields`: 600s Redis
  - `get_fear_greed`: 3600s Redis
- MacroPulse backend proxy: `/api/v1/market/macro-pulse` — parallel CG global + FNG + BTC
  price, 300s Redis. MacroPulse.jsx now single backend call (was 3 browser API calls)
- AssetRadar CG Pro proxy: `/api/v1/market/coingecko-markets` — no more browser rate limits
- Protocol tab: replaced ProtocolPage (mock data) with ProtocolIntelligence (CIS-scored,
  live DeFiLlama TVL). ProtocolPage.jsx dead code, no longer mounted
- ProtocolIntelligence font scale fix: title 15px, filters 11px, protocol name 13px,
  signal badge 9px, risk 10px. Consistent with platform typography
- IntelligencePage sectorData: removed stale Mar 2026 hardcoded fallbacks ($95.7B etc.),
  wired to live `defi_change_24h` / `l2_tvl` / `rwa_tvl` from `get_defi_overview` v2
- Signal Feed: strict HORIZON_STYLES match — unknown time_horizon no longer renders badges
- `strategy.html` — standalone investor demo page (Vite multi-entry):
  - Hero (4 key metrics: 40 assets / 3 channels / $30M / 0% fee)
  - Live Market Intelligence (regime, BTC dom, FNG, MCap — from macro-pulse API)
  - CIS Engine showcase (5 pillars + top 10 live leaderboard from CIS API)
  - Three Investment Channels (Trading Agent / Protocol Yield / Fund of Funds)
  - How It Works (6-step architecture flow)
  - Risk & Structure (6 cards: regulatory, tech, fees, on-chain, risk, transparency)
  - CTA → Open Platform / Contact
- vision.html nav: added "Strategy" link → strategy.html
- `PROJECT_STATUS.md` — comprehensive real-state audit (能跑的 / 有问题的 / 还没做的)

**In progress / Blocked:**
- Supabase project creation (Jazz — need URL + key → Railway env vars)
- CoinGecko Pro key confirmation (Jazz — verify COINGECKO_API_KEY in Railway env)
- Freqtrade dry run activation (Minimax — `git pull` + run start script)

**Next (Week 3–4):**
- User auth + wallet connect (Supabase Auth + Solana wallet adapter — ~3-4 days)
- Nic demo walkthrough (strategy.html is ready, need to review + polish with Jazz)
- Freqtrade dry run → trading agent P&L data → wire into strategy page
- Score history analytics (grade migration, sector rotation)
- Portfolio allocation engine v1

---

*Build things that feel alive.*
