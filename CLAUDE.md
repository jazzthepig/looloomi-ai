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

## Skills (`.claude/skills/`)

Domain knowledge is structured as skills for progressive disclosure. Load the
relevant skill when working in that domain — don't rely solely on CLAUDE.md.

| Skill | Path | When to load |
|---|---|---|
| `compliance-language` | `.claude/skills/compliance-language/SKILL.md` | ANY user-facing output — signals, API, frontend, docs, decks, emails |
| `cis-methodology` | `.claude/skills/cis-methodology/SKILL.md` | CIS scoring, grading, LAS, pillars, data tiers, regime detection |

## Compliance rules

1. **No buy/sell language in signals.** CometCloud does not hold an investment advisory
   (投顾) license. All CIS signals MUST use positioning language only:
   `STRONG OUTPERFORM` / `OUTPERFORM` / `NEUTRAL` / `UNDERPERFORM` / `UNDERWEIGHT`.
   NEVER use `BUY`, `SELL`, `STRONG BUY`, `ACCUMULATE`, `AVOID`, `REDUCE` in any
   user-facing output — backend, frontend, API responses, or documentation.
   See `CIS_METHODOLOGY.md` §5 and §8.
   **Full rules + substitution tables:** `.claude/skills/compliance-language/`

2. **Shadow folder is READ-ONLY.** Never `git add` or commit Shadow/ files. Shadow is
   a local reference for Claude Cowork. All Mac Mini code changes go to
   `/Volumes/CometCloudAI/cometcloud-local/` directly. This has been stated multiple
   times — treat as a hard rule.

3. **No internal implementation details in investor-facing pages.** strategy.html and
   other investor-facing content must not mention specific tech stack (FastAPI, Railway,
   Ollama, Qwen3, etc.), hardware specs, or internal architecture.

4. **Mac Mini ↔ Railway interface contract.** All schema changes to the CIS push
   interface (`/internal/cis-scores` POST body) MUST be documented in
   `MINIMAX_SYNC.md` BEFORE code changes. This includes: field names, grade/signal
   enumerations, pillar keys, asset_class values, timestamp format. No unilateral
   changes — both sides must confirm.

5. **Ownership boundaries.** Seth/Austin only modify `src/`, `dashboard/`, docs.
   Minimax only modifies `/Volumes/CometCloudAI/cometcloud-local/`. Shadow/ is
   read-only reference — never committed. When in doubt about who owns a change,
   check `MINIMAX_SYNC.md` §1.

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

## CIS v4.1 scoring

- **5 pillars**: F (Fundamental), M (Momentum), O (On-chain/Risk-Adjusted), S (Sentiment), A (Alpha)
- **Scoring**: Continuous log/linear functions (v4.1) — no more discrete tier step functions
- **Grading**: Unified absolute thresholds (A+≥85, A≥75, B+≥65, B≥55, C+≥45, C≥35, D≥25, F<25)
  — percentile rank is metadata only, does NOT override grades
- **Signals** (compliance-safe): STRONG OUTPERFORM / OUTPERFORM / NEUTRAL / UNDERPERFORM / UNDERWEIGHT
- **LAS** (Liquidity-Adjusted Score): CIS × liquidity_multiplier × confidence — for agent consumption
- **Data Tiers**: T1 (Mac Mini full engine) / T2 (Railway market estimation)
- **S pillar**: Crypto baseline = FNG × 0.4; TradFi = VIX inverse; per-asset divergence vs category
  median; volatility regime modifier (breakout/capitulation/accumulation/stagnation)
- **A pillar**: Crypto uses BTC 30d divergence; TradFi uses SPY 30d divergence (bonds inverted);
  continuous linear scoring
- **Local engine adds**: 8 asset classes, per-asset benchmarks, 6 macro regimes (RISK_ON, RISK_OFF,
  TIGHTENING, EASING, STAGFLATION, GOLDILOCKS), regime-aware pillar weight adjustments,
  real DeFiLlama TVL for F pillar, `recommended_weight`, `class_rank`, `global_rank`
- **Full spec**: See `CIS_METHODOLOGY.md`

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

## Current focus (as of 2026-04-19)

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

**Done (Week 3 cont. — Mar 23):**
- CIS v4.1 continuous scoring: `_log_score()` + `_linear_interp()` replacing discrete
  tier step functions — genuine differentiation across all 5 pillars
- Unified absolute grading: A+≥85 → F<25 (both engines identical)
- LAS (Liquidity-Adjusted Score): CIS × liquidity_multiplier × spread_penalty × confidence
- Compliance sweep: all buy/sell signals → positioning-only language across 12+ files
- AssetRadar expanded: 14 → 30 assets, 10 categories (L1/L2/DeFi/Infra/RWA/Meme/Gaming/AI/TradFi/Commodity)
- Frontend: T1/T2 data tier badges, LAS column, confidence dots, signal text
- `fetch_cg_markets()` fix: explicit coin IDs instead of top-250 (fixes MKR/POLYX no-data)
- yfinance parallelization: 20 serial → 5 concurrent (asyncio.Semaphore)
- Cache key hash fix in `data_layer.py` (md5-based, no truncation collision)
- MKR reclassified DeFi → RWA in backend (matches frontend)
- `CIS_METHODOLOGY.md` — complete index methodology spec for investors & agents

**Done (Week 3 cont. — Mar 24–29):**
- Vault GP "HumbleBee Capital" partner integration: `/api/v1/vault/deposit-memo`, Drift vault
  deposit flow, Solana memo encoding, partner attribution from referral links
- Lead capture API: `/api/v1/leads/capture` + `/api/v1/leads/list` (Supabase-backed)
- Wallet auth backend: `/api/v1/auth/nonce` + `/api/v1/auth/verify` (Solana Sign-In)
- Share card component + ShareCard.jsx (og:image-style card generation)
- @solana/web3.js lazy-loaded: main bundle 502KB → 250KB (Solana chunk 264KB on demand)
- ScoreAnalytics component (lazy-loaded, 401KB recharts chunk):
  - Grade Migration Heatmap — 7-day per-asset grade grid, color-coded
  - Sector Rotation Chart — avg CIS per asset class over 7 days (recharts LineChart)
  - Grade Distribution Bar — current universe breakdown
  - `normalizeAsset()` handles T1/T2 field shape differences (cis_score/score, asset_id/symbol)
  - Prop-wired to parent `cisUniverse` (no duplicate /api/v1/cis/universe fetch)
- PortfolioAllocation: CSV export button (filename = strategy + risk profile)
- AssetRadar: LAS column tooltip (formula breakdown: CIS × liquidity × confidence),
  mobile filter bar horizontal scroll (no wrap), dotted underline with cursor:help
- Backend: `calculate_cis_universe` import hoisted to module level (was per-request)
- Backend: `/internal/cis-scores` now forwards `macro_regime` from Mac Mini to Redis cache
  (was silently dropped — agent API + signal feed always got "Unknown")
- vision.html parallax JS completion (file was truncated mid-template-literal)
- `scripts/supabase_all_tables.sql` — single-shot schema for all 5 tables:
  `cis_scores`, `macro_briefs`, `wallet_profiles`, `leads`, `vault_deposit_intents`
- email-validator added to `requirements.txt` (fixes Railway crash on pydantic EmailStr)
- Final dist build: `main-29EOrMLX.js` (252KB), `ScoreAnalytics-DERPRYzc.js` (401KB lazy)

**Done (Week 4 — Apr 2):**
- MCP `cometcloud_get_cis_universe`: fixed key mismatch (`universe` not `assets`), timeout 20s→60s
- MCP `cometcloud_get_macro_pulse`: added nested fallback parsing (returns real data now)
- MCP `cometcloud_get_signal_feed`: fixed field names (`description`/`logic`/`affected_assets`)
- `data_layer.py` `get_macro_pulse()`: added flat fields for MCP agent compat
- `Shadow/cometcloud-local/data_fetcher.py`: 8 bug fixes (EODHD date, key exposure, symbol case, RateLimitError, yfinance hang)
- `Shadow/cometcloud-local/config.py`: v4.1 grade thresholds + compliance signals
- `Shadow/freqtrade/`: T1 strategy + backtest config + runner + validation doc
- `MINIMAX_SYNC.md`: created — file-based protocol for Seth ↔ Minimax coordination
- `MULTI_AGENT_PROTOCOL.md` §10: updated with current assignments

**Done (Week 5 — Apr 18–19):**
- CIS v4.2 scoring corrections (`13668fc`): dual score display (raw_cis_score + regime-adjusted),
  S pillar recovery bonus for rebounding assets, vol/mcap threshold 0.3%→0.05%, A pillar
  correlation floor raised in Risk-Off, divergence dampener in extreme fear (FNG<25)
- `cis.py` T1 merge: preserves `raw_cis_score` from Mac Mini; computes from pillars if missing
- Sidebar sub-pages: Intelligence children (Signal Feed / Macro / Events & VC) + CIS children
  (Leaderboard / Asset Radar) — expandable nav, visited-set lazy mount, scroll-to-top on nav
- `IntelligencePage` `view` prop: `"all" | "macro" | "events"` gates block rendering without
  splitting data fetching; section header + inline stats strip both reflect view context
- CIS redirect: `navigate("cis")` → `"cis.leaderboard"` prevents double CISContent mount
- Vault null-safe fixes: sort crash on null scores, null YTD performance cell, orphan Macro
  Events section header when `macroEvents.length === 0`
- Full Chrome QA pass of `looloomi.ai/app`: Signal Feed, Macro, Events & VC, CIS Leaderboard,
  Asset Radar, Protocol Intelligence, Vault, Quant GP, Portfolio — all sections verified
- **Bug fix** `SignalFeed.jsx` `formatRelativeTime()`: short date strings like `"Apr 18"` (no year)
  now append current year — was showing "9131d ago" on all macro signals
- **Bug fix** `IntelligencePage.jsx` Macro Events: `stripHtml()` strips raw `<p>/<img>` HTML
  from CoinTelegraph article descriptions — applied in compact preview and standalone section
- **Design fix** `index.css` card system: `lm-card` / `lm-card-inner` / `lm-stat-card` changed
  from saturated navy overlay (`rgba(7,26,74,0.55)`) to near-void dark surfaces
  (`rgba(5,7,22,0.88)`) with faint cyan borders — Turrell × ONDO void-black design language
- `data_layer.py`: macro-pulse reads nested `cis:local_scores.macro.regime` (was reading flat
  key, silently missing Mac Mini's nested format); EODHD sets error flag on total failure
- `intelligence.py`: vc/funding-rounds returns `data_status` field for empty-vs-loading distinction
- Shadow/ removed from git tracking (`.gitignore`) — contained config files with API keys
- Minimax applied: CoinGecko null handler (POLYX/PEPE price=0 root cause), confidence=0 filter
  skips zero-data assets, macro_regime confirmed in cis_push.py payload
- 13 §4A excluded assets removed from Mac Mini ASSET_UNIVERSE and symbol mappings:
  POLYX, PEPE, WIF, BONK, SAND, MANA, AXS, CRV, SUSHI, SNX, ICP, BCH, FTM

**Done (Week 6 — Apr 21–24):**
- Shadow sync complete: 4 files synced to Mac Mini local engine (§7 MINIMAX_SYNC.md)
  - Cache key fixes: `fundamental→coingecko`, `fundamental→tvl` in data_fetcher.py
  - Symbol mapping fixes: STX `stacks→blockstack`, ONDO `ondo→ondo-finance`
- cis_scheduler.py running (PID 33143) — pushing every 30min; clean universe post-§4A removal
- 84 assets live on Railway: T1=25 (Mac Mini full engine) + T2=59 (Railway estimation)
- macro_regime=Tightening flowing through from Mac Mini (nested key path fixed)
- Agent harness Phase A–F complete and deployed (commit `31194ae`):
  - Phase A: 6 skills (compliance-language, cis-methodology, mac-mini-coordination,
    deploy-workflow, design-system, tech-stack)
  - Phase B: Compliance hook (`.claude/hooks/compliance_check.py`, dry-run mode)
  - Phase C: 5 subagents (compliance-auditor, cis-validator, deploy-verifier,
    code-frontend-reviewer, local-data-coordinator)
  - Phase D: Session handoff + agent memory (`.claude/session-handoff/`)
  - Phase E: Plugin structure (`cometcloud-intelligence/` — manifest + 5 skills + 2 commands
    + 1 agent + MCP config pointing to `src/mcp/cometcloud_mcp.py`)
  - Phase F: GitHub Agentic Workflows (`.github/workflows/` — compliance-pr-check,
    post-deploy-verify, weekly-cis-audit)
- A2A agent card: `dashboard/public/.well-known/agent.json` + `dashboard/dist/.well-known/agent.json`
  — ROADMAP_A2A Phase 2.1 ✅
- Supabase env vars confirmed set in Railway — score history writes active
- MCP config corrected: `cometcloud-intelligence/mcp/cometcloud.json` now stdio → actual
  `src/mcp/cometcloud_mcp.py` (2072-line server); `remote_when_deployed` section for Phase 2.2

**Done (Week 7 — Apr 24–25):**
- CIS scoring fixes (3 bugs found and fixed):
  1. Mac Mini `FundamentalScorer.score()`: `_score_crypto()` only called for `AssetClass.CRYPTO`
     (BTC/LTC/BCH). All L1/L2/DeFi/RWA/INFRA/MEME/GAMING fell through to `_score_generic()` → F=50 always.
     Fixed: expanded check to include all crypto subclasses. MKR/UNI/AAVE/PENDLE now F=70.
  2. Mac Mini `data_fetcher.py`: `SYMBOL_TO_COINGECKO_ID["POL"]` was `"polygon"` (404) → fixed to
     `"polygon-ecosystem-token"`.
  3. Railway `cis_provider.py`: CG Pro `/coins/markets` returns `circ_supply=0` for rebranded tokens
     (MKR/AAVE/UNI). Added `price×total_supply` as secondary mcap fallback before FDV/volume×20.
- cis_scheduler.py subprocess path: venv Python used for child `cis_push.py` process
  (was using system Python → CG Pro key not loaded → Supabase writes always failed). Fixed.
- Supabase score history: now writing successfully (`history_written: true`), 10+ rows accumulating
- CIS score state: T1 top = MKR B (CIS=56.8), T2 F pillar normal (LTC=66.3, BCH=69.6),
  but no B+ assets yet — S and A pillars systematically low, blocking freqtrade trades

**Done (Week 8 — Apr 26):**
- ROADMAP_A2A Phase 2.2 complete: MCP server mounted at /mcp/sse (SSE transport)
  - `src/api/main.py`: `app.mount("/mcp", mcp.sse_app())` with fail-safe try/except
  - `src/api/main.py`: SPA fallback now excludes "mcp/" prefix
  - `requirements.txt`: mcp[cli]>=1.6.0, cachetools, tenacity
  - `cometcloud-intelligence/mcp/cometcloud.json`: remote.url = https://looloomi.ai/mcp/sse
  - ROADMAP_A2A.md Phase 2.2 marked ✅
- Chrome QA UI fixes: CISWidget epoch timestamp, MACRO REGIME field name, StrategyPage CTA contrast
- Auth code review: full flow verified correct (AuthContext → WalletConnect → backend sign-in)
  - `scripts/test_auth_e2e.py`: 11-test backend E2E suite (Mac Mini must run after push)
- COMMIT_READY.md prepared — Mac Mini runs 5-step sequence to deploy
- ROADMAP_A2A Phase 2.3 complete: A2A Task Queue endpoint
  - `src/api/routers/agent.py`: async task queue (portfolio_analysis / cis_snapshot / regime_briefing)
  - `src/api/main.py`: agent_router registered
  - `dashboard/public/.well-known/agent.json` + `dist/`: a2a_tasks live endpoint spec
  - `ROADMAP_A2A.md`: Phase 2.3 marked ✅

**Pending — waiting on Minimax:**
- Rotate EODHD + Finnhub API keys (exposed in old git history via Shadow)
- Start Freqtrade dry run: `start_dry_run.sh`
- Run T1 backtest (`run_t1_backtest.sh`) → report PF/WR/MaxDD
- Add LAS calculation to local engine output (match Railway schema)
- MacroBrief pipeline stability — LM Studio (Qwen3 35B) crash recovery

## Production health (as of 2026-04-26)

- Railway: **ACTIVE** — HEAD = `f7f5bc0` ✅
- CIS universe: **LIVE** — 84 assets (T1=25 Mac Mini + T2=59 Railway). COINGECKO_API_KEY set ✅
- Mac Mini scheduler: **RUNNING** — cis_scheduler.py PID 33143, pushing every ~30min ✅
- macro_regime: **Tightening** — flowing through correctly ✅
- DeFi overview: **LIVE** — DeFiLlama TVL, 25 protocols scored ✅
- Macro Pulse: **LIVE** ✅ — BTC $77,995, F&G, dominance all live
- Signal Feed: **LIVE** ✅ — correct timestamps, compliance-safe language
- Macro Events: **LIVE** ✅ — HTML stripped from descriptions
- Supabase: **CONNECTED** ✅ — score history writing (history_written: true) ✅
- ScoreAnalytics: **LIVE** ✅ — heatmap populating with score history rows
- MacroBrief: **NULL** — Mac Mini LM Studio pipeline not connected / not pushing
- Economic Indicators: **EMPTY** — EODHD key missing/expired. All cells show "—".
- Quant Monitor (Freqtrade): **DRY RUN PENDING** 🟡 — Direction locked: TrendStrategy (PF=1.46, 169 trades,
  MACD 4h, TP=10% SL=4%) + live CIS gate. `CISEnhancedStrategy.py` created on Mac Mini by Minimax.
  Backtest PF<1 was methodology issue (2026 CIS scores filtering 2024 signals, time mismatch — not a strategy bug).
  Next: Minimax confirms file, modifies CometCloudStrategy, starts dry run. See MINIMAX_SYNC.md §4A.
- Agent harness: **DEPLOYED** ✅ — Phase A–F complete, all skills + plugin + workflows live
- A2A discovery: **LIVE** ✅ — `/.well-known/agent.json` served from Railway
- MCP server: **LIVE** ✅ — Phase 2.2 verified via Railway direct URL. HTTP 405 on HEAD = correct
  (SSE endpoint is GET-only; 405 confirms route exists and is mounted)
- A2A Task Queue: **LIVE** ✅ — Phase 2.3 confirmed working (2026-04-27). POST→pending, GET→completed in seconds.
  84 assets returned, all C+/C grade NEUTRAL/UNDERPERFORM = correct Tightening regime behavior.
- **CIS scoring (Tightening regime)**: No B+ assets (CIS≥65) is correct behavior — in Tightening
  with alts down 15-30% vs BTC, S and A correctly suppress. S=12-23 (vol_regime negative, alts
  underperform BTC), A=30-55 (benchmark divergence negative for large-caps). Not a bug.
  Freqtrade regime-aware threshold = 52 (Tightening) → MKR (56.8) passes. ✅
- **Beta calc fix** (2026-04-27): `calculate_asset_betas` min_len bug fixed — partial yfinance
  failures (TNX) no longer kill the entire beta calculation; DXY+VIX compute independently.
  T2 assets now correctly use rolling betas instead of CG proxy fallback.

## Codebase metrics

- Backend: ~5,200 lines across 12 routers (`src/api/routers/`) + main
- Frontend: 26 components (`dashboard/src/components/`), 1,175 lines in `App.jsx`
- CIS provider: `cis_provider.py` calculates scores for 65+ assets (13 §4A assets excluded)
- Shadow/: removed from git tracking (read-only local reference, never commit)

## Task matrix — Week 8 (Apr 26+)

### Seth (Seth / Austin)

| Priority | Task | Est. | Status |
|----------|------|------|-------|
| P1 | ~~Phase 2.2 MCP sidecar — deploy `src/mcp/cometcloud_mcp.py`~~ | ~~1d~~ | ✅ DONE |
| P1 | ~~Wallet connect auth review + E2E test script~~ | ~~1d~~ | ✅ DONE |
| P1 | ~~Beta calc fix (calculate_asset_betas min_len bug)~~ | ~~2h~~ | ✅ DONE — 2026-04-27 |
| P1 | Wallet connect live E2E run (Mac Mini) → re-run after Python 3.14 fix | 0.5d | T17 fix staged |
| P2 | ~~Phase 2.3: A2A Task endpoint `/api/v1/agent/tasks`~~ | ~~4h~~ | ✅ DONE — 2026-04-27 |
| P2 | Trading Agent P&L dashboard — Freqtrade metrics → strategy page | 2d | Blocked on Freqtrade (Seth不参与策略模块) |
| P2 | Share card: og:image endpoint for Twitter/WeChat link previews | 1d | — |
| P2 | My Portfolio view — after wallet connect | 3d | — |
| P2 | Verify ScoreAnalytics heatmap populates | 0.5d | Supabase ✅ + scheduler ✅ |

### Minimax (Mac Mini)

| Priority | Task | Est. | Status |
|----------|------|------|------|
| P0 | Rotate EODHD + Finnhub API keys (exposed in old git history) | 30min | 🔴 |
| P1 | ~~Add LAS calculation to local engine output~~ | ~~2h~~ | ✅ Done |
| P1 | ~~Run T1 backtest → report results~~ | ~~2h~~ | ✅ Done — PF<1 → methodology issue, not strategy |
| P1 | Re-run auth E2E after Seth's Python 3.14 fix | 15min | 🟡 After push |
| P1 | Macro Brief pipeline stability — LM Studio (Qwen3 35B) crash recovery | 1d | 🟡 |
| P1 | **CISEnhancedStrategy dry run (T20)** — confirm file path → modify CometCloudStrategy.py → start dry run | 2h | 🔴 Ready to execute |
| P2 | DeFiLlama TVL refresh: 30min → 15min for F pillar freshness | 0.5h | 🟡 |

### Jazz + Nic (distribution)

| Priority | Task | Owner |
|----------|------|-------|
| P0 | Strategy.html walkthrough with Nic — collect institutional feedback | Jazz + Nic |
| P1 | Wallet connect scope decision: Phantom only vs multi-wallet, custodial? | Jazz |
| P1 | Identify 3-5 target family offices / HNW for soft intro | Nic |
| P1 | Seed investor deck draft — positioning, fee, AUM targets | Jazz + Seth |
| P2 | OSL stablecoin integration timeline — issuer API availability | Jazz |
| P2 | HK SFC Type 9 license / compliance advisor engagement | Jazz |
| P2 | IB association conference mapping (Q2 2026) | Nic |

## Critical path

```
CIS universe ✅ + Supabase ✅ + Mac Mini scheduler ✅
  ├─→ Seth: verify ScoreAnalytics heatmap (24h data accumulation)
  │     └─→ Seth: Freqtrade integration → Trading Agent P&L dashboard
  ├─→ Minimax: Freqtrade dry run → Seth: Trading Agent P&L dashboard
  ├─→ Seth: wallet connect E2E (1d) → My Portfolio view (3d)
  │     └─→ Share card og:image (1d)
  ├─→ Seth: Phase 2.2 MCP sidecar → agent ecosystem (ROADMAP_A2A)
  └─→ Jazz + Nic: strategy.html review → seed investor deck
        └─→ Family office soft intros
```

---

*Build things that feel alive.*
