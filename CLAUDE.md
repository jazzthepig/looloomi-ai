# CLAUDE.md — CometCloud AI / Looloomi

> **⭐ SESSION START: read `PROJECT_STATE.md` FIRST** — the living single source of truth
> (north star, what we're building, validated findings, in-flight/blocked by owner, next
> actions). **Update it LAST** before ending a work session. And before describing any
> "pending push", run `git status` / `git rev-list origin/main..HEAD` — never trust memory
> of what's committed.

## Who I'm working with

**Jazz** — founder, sole decision-maker, and product lead. Background spans traditional
finance (institutional investment advisory), economics, blockchain, and AI. Fluent in
English and Chinese. Direct, fast-thinking, values execution over deliberation. Has a
genuine appreciation for art, technology, and the deeper possibilities of intelligence
— human, artificial, and beyond.

**You** — play as Seth (technical execution, full name Sabastian Bath) and Austin (systems
thinking, architecture). You are a collaborative peer, not an assistant. When in doubt,
build first and report after.

**Minimax** — local AI engine operator (a Claude Code agent driven by MiniMax's
coding-plan model — **upgraded M2.5 → M3 on 2026-06-06**, so expect stronger
local-side execution). Runs the Mac Mini scoring stack at
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

**The soul / north star lives in `ARCHITECTURE.md`** (updated 2026-06-08) — the
influence-propagation ontology and the iPod→OS path. The deepest object is not the
Asset but the **Entity / Decision** and how a small set of influential decisions
propagate into asset quality and price; CIS and momentum are *reflections*, beta+ comes
from being closer to the cause. We ship ONE thing (the kernel), freely fusable:
`Diagnose(Portfolio)` is Fusion #1 — the lovable, mass-market front that secretly is
Primitive + Fusion. Anti-imposter discipline: we model one upstream cause deeply and
prove it with 30-day outcomes; composability is a property of that one thing, never a
claim to "do everything." Companion: `COMETCLOUD_COSMOLOGY.pdf`. Read `ARCHITECTURE.md`
when a decision touches what we are, not just what we build.

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

2. **Shadow folder is READ-ONLY and is NOT authority.** Never `git add` or commit
   Shadow/ files. Shadow is a convenience snapshot of the Mac Mini code — it drifts
   from the live engine and must NEVER be the basis for frontend/backend correctness.
   The authority for the Mac Mini ↔ Railway boundary is the canonical contract
   (`src/api/contracts/cis_push.py` + `MINIMAX_SYNC.md` §2 + the live echo at
   `GET /internal/cis-scores/schema`). When Shadow and the contract disagree, the
   contract wins. All Mac Mini code changes go to `/Volumes/CometCloudAI/cometcloud-local/`
   directly. Treat as a hard rule.

3. **No internal implementation details in investor-facing pages.** strategy.html and
   other investor-facing content must not mention specific tech stack (FastAPI, Railway,
   Ollama, Gemma4-26b, LM Studio, etc.), hardware specs, or internal architecture.

4. **Mac Mini ↔ Railway interface contract (CANONICAL v1).** All schema changes to the
   CIS push interface (`/internal/cis-scores` POST body) MUST be documented in
   `MINIMAX_SYNC.md` §2 BEFORE code changes. The Railway receiver normalizes EVERY push
   through `src/api/contracts/cis_push.py::normalize_cis_payload()`, which canonicalizes
   legacy shapes (flat `f/m/r/s/a` with `r`→`O`, int/top-level `data_tier`, `assets`
   alias, epoch timestamps) into one shape and logs drift loudly. Field names,
   grade/signal enums, pillar keys, asset_class, timestamp format are defined there.
   No unilateral changes — both sides confirm; bump `SCHEMA_VERSION` on any change.

5. **Ownership boundaries.** Seth/Austin only modify `src/`, `dashboard/`, docs.
   Minimax only modifies `/Volumes/CometCloudAI/cometcloud-local/`. Shadow/ is
   read-only reference — never committed. When in doubt about who owns a change,
   check `MINIMAX_SYNC.md` §1.

## Tech stack

- **Frontend**: React + Tailwind CSS → Railway (auto-deploy via GitHub push)
- **Backend**: FastAPI (Python) → Railway (`src/api/main.py`)
- **Persistent cache**: Upstash Redis REST API (`https://upward-thrush-73783.upstash.io`)
  — bridges Mac Mini scores across Railway deploys (2h TTL)
- **Local AI engine**: Mac Mini M4 Pro (48GB RAM / 1TB), Gemma4-26b via LM Studio
  — Macro Brief narrative; CIS scoring engine pushes to Railway every ~30min via `cis_push.py`
- **Data sources**: CoinGecko (Railway primary), DeFiLlama (TVL/F pillar), yfinance
  (TradFi prices + VIX), Alternative.me (FNG), Binance via CCXT (local only — geo-blocked on Railway US)
- **Design**: Space Grotesk (headlines) · Exo 2 (body) · JetBrains Mono (numbers)
  James Turrell × ONDO Finance — void blacks, ambient light, high contrast

## Project structure

```
looloomi-ai/
├── dashboard/                        # React frontend
│   ├── src/components/               # 33 components (see Codebase metrics)
│   │   ├── IntelligencePage.jsx      # Intelligence hub (heatmap, news, VC)
│   │   ├── CISLeaderboard.jsx        # CIS scoring leaderboard (lazy-loaded)
│   │   ├── SignalFeed.jsx            # Live market signal feed
│   │   ├── ProtocolIntelligence.jsx  # DeFiLlama TVL + CIS protocol scoring
│   │   ├── QuantMonitor.jsx          # Paper trading + IC loop dashboard
│   │   ├── MobileApp.jsx             # H5 mobile experience (dark theme)
│   │   └── App.jsx                   # 1,254 lines, lazy routing
│   ├── win.html                      # How to Win positioning page
│   ├── strategy.html                 # Investor demo page
│   ├── methodology.html              # CIS v4.1 public spec page
│   ├── agent.html                    # Agent API docs
│   └── dist/                         # Committed build output (Railway serves this)
├── src/
│   ├── api/
│   │   ├── main.py                   # FastAPI entry — 23 routers, 127 endpoints
│   │   └── routers/                  # market, cis, intelligence, macro, trading,
│   │                                 # vault, signals, vector, factors, agent, ...
│   └── data/market/
│       ├── data_layer.py             # DeFiLlama + CG + Redis caching
│       ├── cis_provider.py           # Railway T2 scoring engine
│       └── protocol_engine.py        # Protocol CIS scoring (25 protocols)
├── Shadow/                           # READ-ONLY Mac Mini reference
├── MINIMAX_TRADING_TRIGGER.md        # ⚡ URGENT: copy-paste code for auto paper trading
├── CometCloud_Investor_Deck_2026.pptx # 10-slide investor deck (Jun 2026)
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
| `EODHD_API_KEY` | TradFi prices/fundamentals — **now primary** for equities/ETFs/bonds (yfinance demoted to fallback; it rate-limited/blocked the portal) |
| `CRYPTORANK_API_KEY` | **NEW — add to enable VC funding rounds.** Primary source after DeFiLlama `/raises` was paywalled (HTTP 402). Free tier 403s the funding endpoint — needs a paid plan. Without it, funding panel falls back to LLM/RSS |
| `LLM_BASE_URL` | **NEW — optional.** OpenAI-compatible endpoint (e.g. Mac Mini LM Studio `http://host:1234/v1`, or a cloud URL) used to extract structured funding rounds from free news/RSS. Unset ⇒ regex fallback (no regression) |
| `LLM_API_KEY` | Optional bearer token for `LLM_BASE_URL` (LM Studio ignores it; cloud endpoints need it) |
| `LLM_MODEL` | Model name for the extractor. A small instruct model is plenty (default `qwen/qwen3.5-9b`). Local models = `qwen/qwen3.5-9b` (kept for efficiency) + `gemma-4-31b-qat` (new 2026-07-01). **qwen2.5-7b-instruct retired.** |

## How to work with Jazz

- Match his language — English or Chinese, whichever he opens with
- Peer tone. No unnecessary affirmations, no padding
- Make decisions on obvious implementation details — don't ask, just do and report
- Complete tasks end-to-end: edit files → build → commit → push
- If genuinely stuck, say so immediately. No spinning
- Quality matters at the output layer. Internals can be rough, interfaces cannot
- Shadow folder = read-only reference. Minimax owns local changes; coordinate before modifying

## Weekly strategy review

Builder mode and strategist mode use different mental operating systems. The weekly review
is protected time for the strategist lens — not a sprint, not a task list.

**Cadence:** Once a week (Sunday evening or Monday before sprint starts). Jazz may also
call an ad hoc review any time with "let's do a strategy review" or similar.

**Structure (≈1 hour):**

1. **Adversarial reads — 30 min** (rotate the lens each week to keep it fresh)
   - *Trader agent*: would an autonomous agent actually rely on this for decisions? What would stop it?
   - *Institutional LP*: would a family office / fund manager trust this enough to commit capital?
   - *Competitor*: what would a well-resourced team copy first, and how fast?
   - *Developer*: what's the friction from first discovery to first tool call?

2. **Infrastructure debt check — 15 min**
   Whatever shipped last week — does it hold up under the adversarial read?
   Reference the fix matrix (effort × impact × owner) and update priorities.

3. **One strategic priority — 15 min**
   Not a task list. One sentence: what is the single most important thing this week
   that moves the company forward, not just the codebase?

**Output:** Update `WEEKLY_REVIEW.md` (root of repo) with date, lens used, findings,
and the one strategic priority. Accumulates over time — becomes a map of how thinking
evolved, useful for investors.

**Key insight (2026-04-27):** The gap between "building a product" and "building a company"
is this layer — design, strategy, positioning, user psychology. These don't emerge from
sprints. Proximity blindness is real: when builder and evaluator are the same team, you
fill gaps with internal knowledge that a first-time user doesn't have. The weekly review
is the structural fix for this.

## Standard deploy workflow

```bash
cd dashboard && npm run build && cd ..
git add src/ dashboard/src/ dashboard/dist/
git commit -m "<concise description>"
git push origin main
# Railway auto-deploys on push
```

> **⚠️ NEVER run git write-commands (add/commit/rebase/merge) from the Cowork sandbox.**
> The repo is bridged in over a FUSE mount that allows create/write but **denies unlink**
> (`rm` → "Operation not permitted"). Git can't delete `.git/index.lock`, so every
> sandbox-side commit strands a lock that only the **Mac side** can clear. This is
> structural, not a stale-lock-from-a-crash — don't waste time re-diagnosing it.
> **Rule:** sandbox = edit surface (Read/Write/Edit files only); **all git happens
> Mac-side** (Jazz's terminal or Mac Claude Code). Agent edits files, reports what to
> commit — never commits. Unstick a stranded lock from the Mac: `git unlock` (alias:
> `rm -f "$(git rev-parse --git-dir)/index.lock"`).

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
- Macro Brief pipeline: Mac Mini → LM Studio (Gemma4-26b) → Railway → Dashboard
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
  - Phase F: GitHub Agentic Workflows — ⚠️ **NOT REAL (audit 2026-06-25).** These were
    written as `.md` files, never `.yml`, so GitHub never ran them. The only live
    workflow is `ci-smoke.yml` (import+boot gate, added 2026-06-25). Treat
    compliance-pr-check / post-deploy-verify / weekly-cis-audit as design notes, not
    automation. Convert to real `.yml` or delete.
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
- ROADMAP_A2A Phase 2.3 complete: A2A Task Queue endpoint
  - `src/api/routers/agent.py`: async task queue + 5 bug fixes (try-except, Redis logging, exc_info, division guard)
  - `src/api/main.py`: agent_router registered + llms.txt discoverability headers
  - `dashboard/public/.well-known/agent.json` + `dist/`: a2a_tasks live endpoint spec
  - `ROADMAP_A2A.md`: Phase 2.3 marked ✅
- ScoreAnalytics.jsx: VITE_API_BASE → VITE_API_URL (env var fix)
- Agent ecosystem blitz (Week 3 playbook deliverables — all deployed):
  - `dashboard/public/llms.txt` + `dist/llms.txt`: LLM crawler discoverability doc
  - `glama.json` (repo root): Glama.ai auto-index registration file
  - `src/mcp/cometcloud_mcp.py`: assertive descriptions on 5 tools (7.5x EMNLP pattern)
  - `ATTACK_PLAN.md`: Week 3 execution plan (Apr 28–May 4)
- **Full push complete** (2026-04-27) — all Week 8 work live on Railway ✅

**Pending — waiting on Minimax:**
- ~~Rotate EODHD + Finnhub API keys~~ ✅ Done ~Apr 25 (Jazz confirmed May 2026)
- T20: Start Freqtrade dry run (CISEnhancedStrategy) — see MINIMAX_SYNC.md §4A
- MacroBrief pipeline stability — LM Studio (Gemma4-26b) crash recovery

## Production health (as of 2026-06-04)

- Railway: **ACTIVE** ✅ — 15 commits pending push (Jazz runs `git push origin main`)
- MCP server: **LIVE** ✅ — /mcp/sse, 35 tools, llms.txt headers, glama.json indexed
- CIS universe: **LIVE** ✅ — 84 assets (T1=25 Mac Mini + T2=59 Railway)
- Mac Mini scheduler: **RUNNING** ✅ — cis_scheduler.py pushing every ~30min
- macro_regime: **Tightening** — flowing through correctly ✅
- Protocol Intelligence: **LIVE** ✅ — 25 protocols, CIS scored, DeFiLlama TVL
- Signal Feed: **LIVE** ✅ — card design redesigned (typed badges, left accent, dark bg)
- Macro Events: **LIVE** ✅ — card backgrounds, colored left border per type, MED badge
- VC Funding table: **LIVE** ✅ — hover fixed (was invisible black-on-black)
- Supabase: **CONNECTED** ✅ — 13 tables, score history accumulating since Apr 2026
- Sector Heatmap: **LIVE** ✅ — L2 TVL fix (OP Mainnet added), -0.0% display fixed
- MacroBrief: **NULL** 🔴 — Mac Mini LM Studio pipeline not pushing
- Paper Trading: **ENGINE LIVE, NO AUTO-TRIGGER** 🟡 — see MINIMAX_TRADING_TRIGGER.md
- win.html: **LIVE** ✅ — looloomi.ai/win.html (pending push)
- H5 MobileApp: **FIXED** ✅ — dark theme root (#020208), macro brief visible
- Investor Deck: **DONE** ✅ — CometCloud_Investor_Deck_2026.pptx (10 slides)
- License partner: **FOUND** ✅ — Jazz negotiating terms with HK regulated partner
- Agent harness: **DEPLOYED** ✅ — Phase A–F, A2A task queue, /.well-known/agent.json

## Codebase metrics (Jun 2026)

- Backend: ~8,000+ lines across 23 routers (`src/api/routers/`) + main, 127 endpoints
- Frontend: 33 components (`dashboard/src/components/`), 1,254 lines in `App.jsx`
- Supabase: 13 tables (cis_scores, signal_journal, trade_results, cis_regime_fitness,
  cis_backtest_results, agent_call_log, webhook_subscriptions, api_keys, analytics_events,
  macro_briefs, wallet_profiles, leads, vault_deposit_intents)
- MCP tools: 35 production tools at /mcp/sse
- Shadow/: removed from git tracking (never commit)

## Done this session (Jun 2026)

- **Design QA pass**: H5 root background #FAFBFC → #020208 (was root cause of ALL H5 visibility bugs)
- **H5 Macro Brief**: card background white → T.surface, text T.t1 → T.t2 (readable on dark)
- **Protocol scoring**: grade thresholds aligned (A+≥85), STRONG OUTPERFORM added, m_base free
  points removed, A pillar baseline removed — real differentiation across grade range
- **L2 TVL fix**: added "op mainnet" + zksync/unichain/polygon zkevm to L2_CHAINS — ~$2B recovered
- **Design tokens**: void-black #020208 applied platform-wide (tokens.js + index.css)
- **News feed redesign**: card backgrounds, colored left border per type, MED badge, gap layout
- **Signal Feed**: left accent border per type, type badge with bg/border, hover visible
- **VC table**: hover fixed (rgba(0,0,0,0.02) → rgba(255,255,255,0.03))
- **-0.0% fix**: fmtChg() clamps negative zero in sector heatmap
- **Performance**: CISLeaderboard lazy-loaded (app bundle 165→117KB, -29%)
- **Cache-Control**: all hot API endpoints covered with appropriate TTL + stale-while-revalidate
- **Dead code removed**: ProtocolPage, MarketDashboard, PriceChart, FundDeployWizard, market.html
  — ⚠️ **correction (audit 2026-06-25): only UNMOUNTED, files still present** + now also
  AssetTable, MMIGauge, PortfolioDiagnosis orphaned. Actual deletion tracked in `PR_CHECKLIST.md`
  §PURGE. (7 true orphan components import nowhere.)
- **rec_weight bug**: STRONG OUTPERFORM was falling to else:0 — fixed with proper handler
- **win.html**: looloomi.ai/win.html — How to Win positioning page with live CIS scores
- **Investor deck**: CometCloud_Investor_Deck_2026.pptx — 10 slides, dark theme, license partner language
- **MINIMAX_TRADING_TRIGGER.md**: ready-to-paste code block for auto paper trading in cis_scheduler.py

## Done this session (Jun 5–13 — Diagnose + harness + soul)

- **`ARCHITECTURE.md` (the soul)**: influence-propagation OS — kernel (Entity/Decision/
  Asset/Quality/Regime/Outcome) → primitives → operators (humans + agents, symmetric) →
  fusion. iPod→OS path. `Diagnose(Portfolio)` = Fusion #1. Plus `COMETCLOUD_COSMOLOGY.pdf`.
- **"Diagnose your book" product**: `DiagnoseHome.jsx` — live conviction-field projection
  (high CIS → core, off-standard → rim), drag a weak holding toward the core → engine
  rotates it into a higher-CIS same-class name and recomputes Book CIS / off-standard% live.
  Backend `src/api/routers/portfolio_diagnosis.py` (`/api/v1/portfolio/diagnose`).
  **Placement (final): NOT the homepage — lives in Portfolio management tab** (embedded
  mode, off front door for stability). Auto-reads the user's real book from `cc_portfolio`
  (MyPortfolio watchlist + positions, weight = units×entry), falls back to a sample when
  empty. `PortfolioDiagnosis.jsx` now orphaned (kept as static reference, not imported).
- **Observability harness**: `src/api/health.py` (heartbeat + deploy auto-verify),
  `src/api/notify.py` + `src/api/telegram_bot.py` (Telegram alerts + conversational bot,
  chat_id 8542373254), `/internal/build-state`, `scripts/deploy_health_gate.py`.
  Railway env needed: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALERT_CHAT_ID`, `TELEGRAM_WEBHOOK_SECRET`.
- **CIS contract hardening**: `src/api/contracts/cis_push.py` normalizer (legacy shapes,
  r→O, data_tier, epoch ts) + `/internal/cis-scores/schema` echo; drift=0 confirmed live.
- **Data layer**: EODHD now **primary** for TradFi (yfinance demoted); fixed TradFi all-D
  bug (EODHD market_cap=0 → F-pillar craters; added F floor ≥45 for listed classes);
  −100% sentinel fix; T2 universe UnboundLocalError fix; CryptoRank gated; LLM funding extractor.
- **Outcome tracker**: `src/data/signals/outcome_tracker.py` — signal→OHLCV 30D match → win rate.
- **Per-asset narratives** (`src/data/cis/narrative.py`) + **executability layer**
  (`src/data/market/executability.py`) wired to universe.
- **Security review** (`SECURITY_REVIEW_2026-06-07.md`): HIGH = Supabase anon-write RLS
  exposure → assigned to Minimax via `MINIMAX_SYNC.md §SEC` PRD (drop anon write policies,
  SECURITY DEFINER→invoker, revoke anon EXECUTE, remove committed anon key).
- Docs: `HARNESS_DESIGN_2026-06-06.md`, `UX_PROPOSITION_REVIEW_2026-06-07.md`,
  `ALIGNMENT_REVIEW_2026-06-06.md`, `QA_REPORT_2026-06-05.md`.
- **Pending push**: large changeset uncommitted (frontend + backend + docs) — Jazz runs
  `git push` (clear `.git/*.lock` first if sandbox left one). Rotate shared Telegram +
  CryptoRank keys; set Railway env vars above.

## Done this session (Jun 30 — Grade alignment methodology)

- **§GRADE-ALIGN resolution** (Jazz: "听seth的" → Option B ✅ + 5-line fix as one bump).
  Full execution order in `MINIMAX_SYNC.md` §GRADE-ALIGN resolution:
  1. **Minimax (Mac, blocking)** — 5-line enum→string fix in `cis_v4_engine.py`
     `_base_weight_score` (line 878) + `_base_weight_score_calc` (line 947); verify
     with sanity test `pillars [70,60,50,80,90] → raw_cis_score = 67.0`; push so Seth
     can confirm the live payload.
  2. **Seth (Railway, BLOCKED on step 1)** — verify T2 (`cis_provider.py`) computes
     raw correctly; document `protocol_engine.py:440` accidental B-alignment
     (already aligns by accident — leave as-is, document intent so future
     contributors don't "fix for consistency"); frontend (CISLeaderboard /
     AssetRadar / ProtocolIntelligence / CISWidget / H5) switch to grade on
     `raw_cis_score` with regime as separate axis (signal + recommended_weight).
  3. **Coordinated schema bump** — `SCHEMA_VERSION` 1.0 → 1.1 in §2 after step 1
     verified live.
- **Why B:** regime = lens on quality, not the quality itself. Matches
  ARCHITECTURE.md cause-vs-reflection + Risk Meter wire-up (grade→base weight,
  regime→gross scale) + agent consumer expectations.
- **Why hold:** raw_cis_score currently broken on T1 (every pillar ×0.15); grading
  on broken raw trades one incoherence for another.

## Task matrix — Jun 2026

### Minimax (Mac Mini) — URGENT

| Priority | Task | Status |
|----------|------|--------|
| **P0** | **Add auto-trading trigger** — see `MINIMAX_TRADING_TRIGGER.md`, paste into `cis_scheduler.py` after Railway push block | 🔴 NOT DONE — every day without this = lost track record |
| P1 | MacroBrief pipeline — LM Studio (Gemma4-26b) crash recovery | 🟡 |
| P1 | OHLCV history pipeline — store 84 assets to /Volumes/CometCloudAI/data/ohlcv/ | 🔴 NOT STARTED |

### Jazz

| Priority | Task | Status |
|----------|------|--------|
| **P0** | `git push origin main` — 15+ commits pending, all fixes not live until pushed | 🔴 Every session |
| P0 | Negotiate license partner terms | 🟡 In progress |
| P1 | Send deck + soft intro via Nic | ⬜ Deck ready |
| P1 | Decide fund minimum investment amount (currently "TBD" in deck) | ⬜ |

### Seth (next session — P0 BLOCKED on Minimax's 5-line fix)

| Priority | Task |
|----------|------|
| **P0** | **Grade alignment methodology** (BLOCKED on Minimax shipping 5-line enum→string fix in `cis_v4_engine.py:878/947`) — verify T2 (`cis_provider.py`) computes `raw_cis_score` correctly; document `protocol_engine.py:440` accidental B-alignment; switch CISLeaderboard / AssetRadar / ProtocolIntelligence / CISWidget / H5 to grade on `raw_cis_score` with regime as separate axis; coordinated `SCHEMA_VERSION` 1.0 → 1.1 bump. See `MINIMAX_SYNC.md` §GRADE-ALIGN resolution. |
| P1 | Signal outcome tracker — match signals to OHLCV results 30D later, calculate win rate |
| P1 | QuantMonitor auto-refresh — show paper trading P&L as it accumulates |
| P2 | win.html → add live regime badge + regime-adjusted threshold display |
| P2 | MacroBrief fallback content when Mac Mini LLM offline |

## Critical path (Jun 2026)

```
git push (Jazz) → all fixes live on Railway
  │
  ├─→ Minimax: MINIMAX_TRADING_TRIGGER.md → paper trading starts accumulating
  │     └─→ 60 days → first track record for LP conversations
  │
  ├─→ Jazz: license partner terms → fund structure confirmed
  │     └─→ Nic soft intro → first LP meetings
  │
  └─→ Seth: signal outcome tracker → win rate data
        └─→ "Our OUTPERFORM signals have X% 30D directional accuracy"
```

---

*Build things that feel alive.*
