# CometCloud AI — Product Requirements Document v2.0

**Document owner:** Jazz (product), Seth/Austin (engineering)
**Date:** 2026-04-06
**Status:** Draft — awaiting Jazz review before engineering begins

---

## 1. EXECUTIVE SUMMARY

CometCloud AI is being redesigned from a multi-section scrolling dashboard into a purpose-built institutional intelligence platform with a paired Fund-of-Funds product. The redesign is driven by one observation: the current product tries to serve everyone on one page and ends up serving no one with conviction.

The new architecture separates four distinct user journeys — LP allocator, institutional trader, crypto analyst, and AI agent — into purpose-built experiences, each with a clear entry point, a dominant information hierarchy, and a single call to action.

This PRD covers: who we're building for (§2), what exists today and what's wrong with it (§3), the target information architecture (§4), page-by-page requirements (§5), what we build vs. what we cut (§6), scenario analysis for three strategic paths (§7), and a phased roadmap (§8).

---

## 2. USER PERSONAS

### Persona A: LP Allocator ("Rachel")

**Who:** Managing Director at a Hong Kong family office. $200M AUM. Allocates 5-8% to digital assets. Has a Bloomberg terminal on her desk and a CIO who needs a one-page summary before any allocation.

**Journey:** Nic sends her a link. She opens it on her laptop during a 15-minute break. She needs to understand in 60 seconds: what is this fund, what's the strategy, what's the fee structure, and who's behind it. If she's interested, she wants to schedule a call — not connect a wallet.

**What she needs from CometCloud:**
- Strategy thesis: what the fund invests in, how it selects, why it's differentiated
- Fee structure (zero management fee is a genuine hook)
- Compliance pathway (HK SFC, custody, regulatory status)
- Live proof the intelligence engine works (not a demo — live data)
- A way to reach Jazz or Nic directly

**What she does NOT need:**
- A CIS leaderboard with 70 assets
- A portfolio builder
- Asset prices
- A wallet connect button

**Current product gap:** Rachel lands on app.html and sees a hero about "Navigation Infrastructure for the On-Chain World," a mesh animation, and six nav tabs. Nothing tells her about the fund. She has to scroll past Market, Intelligence, and CIS to reach Vault — which looks like a DeFi protocol page, not an institutional fund factsheet. She closes the tab.

**Competitive comparison:** Grayscale's research site opens with the fund name, AUM, performance, strategy in one screen. Pantera's site opens with thesis + track record. These are the benchmarks for Rachel.

### Persona B: Institutional Trader ("Kai")

**Who:** Crypto PM at a multi-strategy fund (Millennium-style pod). Manages a $50M book. Needs systematic signals to supplement his own research. Already uses Nansen for wallet flows and Artemis for stablecoin data. Looking for a scoring overlay that's regime-aware.

**Journey:** Kai heard about CIS from a colleague. He opens the intelligence platform. He needs to see in 10 seconds: what's the current regime, what's the top conviction, and is this signal additive to what he already has. If it is, he wants API access to pipe it into his own systems within the same session.

**What he needs from CometCloud:**
- Current macro regime front and center (not buried)
- CIS leaderboard: dense, sortable, filterable — Bloomberg-like, not dashboard-like
- Signal feed with explicit reasoning (he evaluates logic, not just direction)
- Pillar breakdown per asset (which dimension is driving the score?)
- API documentation and access
- Compare tool for side-by-side pillar analysis

**What he does NOT need:**
- A hero section or brand pitch
- Asset prices (he has Bloomberg)
- VC funding rounds
- Vault / fund deposit flow
- Portfolio builder (he has his own risk system)

**Current product gap:** Kai lands on app.html and sees the hero. He scrolls past it. Hits "Asset Prices" — a section of price data he already has. Scrolls more. Intelligence section mixes DeFi overview, VC funding, macro events, and protocols in tabs. CIS is section 3 — the thing he came for is below two full-height sections of content he didn't ask for. He finds the leaderboard, but it's wrapped in a methodology banner and embedded inside a section alongside CrossAssetView, Portfolio Builder, and Score Analytics. The signal-to-noise ratio is low.

**Competitive comparison:** Artemis opens directly into the analytics terminal. Token Terminal opens into the metrics grid. No hero, no pitch, no scrolling. Data first.

### Persona C: Crypto Analyst ("Mei")

**Who:** Research analyst at a crypto-native fund or media outlet. Writes reports on market structure, DeFi protocols, and macro trends. Needs data to support narratives. Uses DeFiLlama, Dune, and CoinGecko daily.

**Journey:** Mei discovers CometCloud through a shared signal feed link. She's interested in the CIS methodology — the five-pillar framework is novel. She wants to explore it: how does it score different asset classes? How does regime detection change the rankings? She wants to reference CIS in her next report.

**What she needs:**
- CIS methodology explanation (not in a collapsible banner — a proper page)
- Score Analytics: grade migration, sector rotation, return dispersion by grade
- Protocol Intelligence with CIS overlay
- Compare tool for building narratives ("SOL's M-pillar outperforms ETH's by 15 points because...")
- Embeddable charts or data she can reference

**What she does NOT need:**
- Wallet connect
- Fund deposit flow
- Portfolio builder
- Quant GP section

**Current product gap:** The CIS Methodology doc exists as CIS_METHODOLOGY.md but isn't linked from the frontend. The methodology banner in CISLeaderboard is collapsed by default and gives a one-sentence summary. ScoreAnalytics is now on a separate page but has no narrative context — just charts.

### Persona D: AI Agent ("Agent-47")

**Who:** An autonomous trading agent running on the Solana Agent Skills SDK. Needs structured, machine-readable data to make allocation decisions. Operates 24/7 with no human in the loop.

**Journey:** The agent discovers CometCloud via the /.well-known/agent.json A2A document. It hits the agent API endpoint, retrieves the CIS universe with regime context, evaluates scores against its internal strategy, and executes trades.

**What it needs:**
- Compact JSON API with abbreviated keys (already exists at /api/v1/agent/cis)
- WebSocket for real-time score updates (already exists at /ws/cis)
- Regime-weighted scores (already exists at /api/v1/cis/regime-analysis)
- LAS (Liquidity-Adjusted Score) for position sizing
- Consistent uptime and <500ms response time

**What it does NOT need:**
- Any frontend at all

**Current product gap:** Agent API exists but documentation is in code comments only. No public API docs page. Agent discovery document exists but isn't linked from any user-facing page. The agent story is a differentiator that's completely invisible.

---

## 3. CURRENT STATE AUDIT

### 3.1 Page inventory (what exists)

| Page | URL | Purpose | Lines of JSX | Status |
|------|-----|---------|-------------|--------|
| Landing | index.html | Immersive visual intro, "Explore" CTA | 472 (static HTML) | Ships to vision.html — no clear value prop |
| Vision | vision.html | Extended brand narrative | ~800 (static HTML) | Beautiful but unfocused — philosophy, not product |
| Main App | app.html → App.jsx | 6-section scrolling dashboard | 1,036 | Tries to be everything |
| Market | market.html → MarketPage.jsx | Standalone market data page | 920 | Duplicates App.jsx Section 1 |
| Strategy | strategy.html → StrategyPage.jsx | Investor demo page | 960 | Closest to an LP-focused page, but mixes tech details |
| Quant | quant.html → QuantMonitor.jsx | Quant strategy monitoring | 514 | For Minimax/internal use |
| Share | share.html → ShareCard.jsx | OG image / social sharing | 370 | Utility page |
| Portfolio | portfolio.html → portfolio.jsx | Portfolio Builder + My Portfolio | 230 + 727 + 672 | Just separated from App.jsx |
| Analytics | analytics.html → analytics.jsx | Score Analytics | 201 + 392 | Just separated from App.jsx |

**Total frontend:** ~16,775 lines of JSX across 26 components. 10 HTML entry points. 90+ backend API endpoints across 11 routers.

### 3.2 What's wrong — structural diagnosis

**Problem 1: No clear entry point per persona.**
index.html → vision.html → app.html is a 3-click funnel that loses everyone. Rachel (LP) needs the fund page. Kai (trader) needs the intelligence terminal. Mei (analyst) needs the CIS deep dive. They all land on the same generic hero.

**Problem 2: The main app is a data buffet, not a conviction engine.**
App.jsx renders 6 sections in vertical scroll: Market → Intelligence → CIS → Protocol → Vault → Quant GP. Each section contains 1-3 heavy components. The user scrolls through ~4,000px of content to reach Vault. No section has clear primacy.

**Problem 3: The intelligence engine's best feature is buried.**
The Regime Brief (AI-generated macro narrative from Qwen3) is a MacroBrief widget inside the Intelligence section. It's the single most differentiating feature — no competitor generates regime-aware narrative intelligence — and it's a small card in a tabbed section.

**Problem 4: Market data leads the experience.**
Section 1 is "Asset Prices" — MacroPulse + AssetRadar + SignalFeed. Every competitor (CoinGecko, CoinMarketCap, TradingView) does price data better. Leading with commoditized data signals "we're a tracker, not an intelligence platform."

**Problem 5: The fund product is indistinguishable from DeFi protocol UIs.**
VaultPage.jsx (987 lines) renders GP funds with a DeFi-style deposit modal. For Rachel, this feels like yield farming, not institutional allocation. The zero management fee — the single strongest commercial hook — is not prominently displayed.

**Problem 6: No API documentation for agents/developers.**
90+ endpoints, zero public documentation. The agent API (/api/v1/agent/cis) and WebSocket (/ws/cis) are genuine differentiators for the autonomous agent narrative. They're invisible.

### 3.3 What's working

- **CIS scoring engine** (cis_provider.py): 65+ assets, 5 pillar continuous scoring, 6 macro regimes, regime-weighted pillar adjustments. This is real intellectual property. No competitor has this.
- **Signal feed** (19 signals, 8 types): compliance-safe positioning language, pillar impact attribution, explicit reasoning. This is institutional-grade.
- **Design tokens** (tokens.js): coherent Turrell-inspired dark palette, proper font hierarchy (Space Grotesk / Exo 2 / JetBrains Mono). The visual language is strong.
- **Backend architecture**: 11 routers, clean separation, Redis caching, Supabase persistence, Upstash bridge for Mac Mini → Railway. Solid infrastructure.
- **Mac Mini AI engine**: Qwen3 35B running locally for macro brief generation. This is a genuine edge — narrative intelligence from a local AI, not just API calls.

---

## 4. TARGET INFORMATION ARCHITECTURE

### 4.1 Page map (redesigned)

```
CometCloud AI
│
├── / (index.html)                    ← LANDING: fork to Fund or Platform
│   ├── Live regime badge + one-sentence macro brief
│   ├── Two paths: "Intelligence Platform" | "Fund-of-Funds"
│   └── No hero animation, no scroll. Above the fold, decision in 5 seconds.
│
├── /intelligence (NEW)               ← PRIMARY: institutional intelligence terminal
│   ├── Regime Brief (AI narrative, full width, dominant)
│   ├── CIS Universe (leaderboard, dense, sortable)
│   ├── Signal Feed (top 5 highest-conviction, with logic)
│   └── Protocol Intelligence (DeFi lens)
│
├── /fund (NEW)                       ← LP PRODUCT: institutional fund factsheet
│   ├── Strategy thesis (3 sentences)
│   ├── Allocation methodology (CIS-powered)
│   ├── Fee structure (0% management, performance only)
│   ├── Risk framework
│   ├── Compliance & regulatory status
│   └── CTA: Schedule conversation / Request deck
│
├── /cis/{symbol} (NEW)               ← ASSET DEEP DIVE: single-asset intelligence page
│   ├── 5-pillar radar chart
│   ├── AI-generated narrative (from Qwen3)
│   ├── Regime sensitivity analysis
│   ├── 7-day grade trajectory
│   └── Compare entry point
│
├── /compare (NEW, or modal from CIS) ← COMPARE: side-by-side pillar analysis
│
├── /portfolio                        ← TOOL: portfolio builder + watchlist
│
├── /analytics                        ← TOOL: score history, grade migration, backtest evidence
│
├── /methodology (NEW)                ← REFERENCE: CIS methodology spec for analysts
│
├── /api (NEW)                        ← DEVELOPER: API documentation + agent onboarding
│
├── /strategy                         ← KEEP: simplified, links to /fund for LP conversion
│
└── /vision                           ← KEEP: brand/philosophy (secondary, linked from footer)
```

### 4.2 Current vs. Target comparison

| Dimension | Current | Target | Why |
|-----------|---------|--------|-----|
| Entry point | Generic hero → scroll | Fork: Fund or Intelligence | Different users, different doors |
| First fold | "Navigation Infrastructure" + mesh animation | Live regime + macro brief + top conviction | 3-second value delivery |
| Market data | Section 1, full width | Inline within CIS leaderboard rows | Not a standalone section — commoditized |
| CIS Leaderboard | Section 3 (below 2 full sections) | Page 1 of intelligence terminal | The product IS the leaderboard |
| Regime Brief | Widget inside Intelligence tab | Full-width opening element | Most differentiating feature |
| Signal Feed | Side panel in Market section | Curated top 5, below leaderboard | Quality over quantity |
| Fund / Vault | Section 5, DeFi-style UI | Standalone /fund page, factsheet format | LP-appropriate presentation |
| Portfolio Builder | Inside CIS section | Standalone /portfolio page | Power tool, not core experience |
| Score Analytics | Inside CIS section → own page | Standalone /analytics page | Evidence exhibit for quant diligence |
| API docs | None | Standalone /api page | Agent adoption requires docs |
| Methodology | Collapsible banner in leaderboard | Standalone /methodology page | Analysts need reference material |
| Quant GP | Section 6 in main app | Inside /fund page as strategy breakdown | Not standalone content |
| VC Funding | Tab in Intelligence section | Cut from v2 (low signal, not CometCloud IP) | Doesn't differentiate |
| Macro Events | Tab in Intelligence section | Folded into Regime Brief narrative | AI summarizes, humans don't scan event lists |
| Navigation | 6 scroll-tabs + 2 external links | Direct page links (no scroll-to-section) | Each page has one purpose |

### 4.3 What gets cut

| Component | Lines | Reason |
|-----------|-------|--------|
| Hero section (App.jsx HeroContent) | ~120 | Replaced by live regime brief on intelligence page |
| MarketDashboard / Asset Prices section | ~130 | Prices inline in CIS leaderboard; no standalone section |
| MarketPage.jsx | 920 | Redundant with intelligence page |
| ProtocolPage.jsx | 1,079 | Dead code (hardcoded sample data, superseded by ProtocolIntelligence) |
| VC Funding tab (IntelligencePage) | ~200 | Low signal, not CometCloud IP, available on Messari/Artemis |
| Macro Events tab (IntelligencePage) | ~150 | Folded into Regime Brief narrative |
| Quant GP section (App.jsx) | ~200 | Moves into /fund page as GP partner section |
| IntersectionObserver scroll tracking | ~40 | No longer needed with direct page navigation |
| vision.html parallax JS | ~200 | Keep page but simplify — brand page, not core product |

**Estimated code removed:** ~3,000 lines of JSX (18% of frontend)
**Estimated code added:** ~2,400 lines across new pages (/intelligence, /fund, /cis/[symbol], /methodology, /api)

Net result: fewer lines, more focused product, 4 clear user journeys instead of 1 confused scroll.

---

## 5. PAGE-BY-PAGE REQUIREMENTS

### 5.1 Landing Page (/)

**Purpose:** Route users to the right experience in under 5 seconds.

**Hierarchy:**
1. (DOMINANT) Live regime badge + one-line macro brief — proves the engine is live
2. (PRIMARY) Two cards: "Intelligence Platform" → /intelligence | "Fund-of-Funds" → /fund
3. (SECONDARY) Footer: links to /methodology, /api, /vision, contact

**Data requirements:**
- GET /api/v1/market/macro-pulse (regime, FNG, BTC price)
- GET /api/v1/macro/brief (one-sentence summary, truncated)

**Design constraints:**
- No scroll required. Everything above the fold at 1080p.
- No hero animation. Static layout with live data.
- Mobile: stack the two cards vertically.

**What it replaces:** Current index.html (472-line immersive visual) + app.html hero section

### 5.2 Intelligence Terminal (/intelligence)

**Purpose:** The core product. Regime-aware conviction ranking for institutional traders and analysts.

**Hierarchy:**
1. (DOMINANT) Regime Brief — full width, AI-generated narrative (2-3 sentences), regime label + pillar weights displayed as small chips. Auto-refreshes every 10 minutes.
2. (PRIMARY) CIS Universe leaderboard — dense table, full width. Columns: Rank, Symbol, Name, Class, CIS Score, Grade, Signal, F/M/O/S/A pillar scores, Price, 24h%, 7d Sparkline, Data Tier. Sortable by any column. Filterable by asset class. Click row → /cis/{symbol}.
3. (SECONDARY) Signal Feed — top 5 highest-conviction signals. Each: type badge, direction, affected assets, one-sentence logic, pillar impact bars. "View all signals" expands to full list.
4. (TERTIARY) Protocol Intelligence — collapsible DeFi lens below signal feed.

**Navigation bar:**
- Left: "CometCloud" brand → /
- Center: Page tabs — Intelligence (active), Fund, Portfolio, Analytics
- Right: Regime badge (always visible), API link, Connect Wallet

**Data requirements:**
- GET /api/v1/macro/brief (regime narrative)
- GET /api/v1/cis/universe (full universe with pillars)
- GET /api/v1/cis/history/batch (sparklines for top 20)
- GET /api/v1/signals (signal feed)
- GET /api/v1/market/macro-pulse (regime badge in nav)

**Design principles:**
- Token Terminal density. Monospace numbers. Thin borders. No decorative cards.
- Sparklines render inline in the table row — no separate chart section.
- Regime Brief text uses FONTS.body at 15-16px — readable, editorial, not a widget.
- Table rows alternate between T.surface and transparent (subtle banding).
- Pillar scores as narrow horizontal bars (0-100) with color per pillar.

**What it replaces:** Current App.jsx sections 1-4 (Market + Intelligence + CIS + Protocol) + MacroPulse + AssetRadar + SignalFeed + CISLeaderboard + CrossAssetView

### 5.3 Fund Page (/fund)

**Purpose:** Convert LP interest into a conversation. Institutional factsheet format.

**Hierarchy:**
1. (DOMINANT) Fund name + one-line thesis + key metrics bar: "0% Management Fee · Performance Only · $30M Target AUM · Solana-Native"
2. (PRIMARY) Strategy section: CIS-powered allocation across three channels (Trading Agent, Protocol Yield, Fund-of-Funds). Each channel: one paragraph + allocation weight.
3. (SECONDARY) Risk Framework: 6 cards — Regulatory (HK SFC pathway), Technology (dual-engine architecture), Fees (0% + performance waterfall), On-Chain (Solana transparency), Risk Management (drawdown limits, position sizing), Governance (multisig, audit).
4. (SECONDARY) GP Partners: EST Alpha (Quant GP) card with strategy summary + track record. Room for additional GPs.
5. (TERTIARY) CTA section: "Schedule a Conversation" form (name, email, organization, investment range, message) → POST /api/v1/leads/enquiry

**Navigation bar:** Same as intelligence page but "Fund" tab active.

**Data requirements:**
- GET /api/v1/market/macro-pulse (live regime badge in nav)
- GET /api/v1/cis/universe (top 10 for "Live CIS Performance" widget)
- POST /api/v1/leads/enquiry (lead capture form)

**Design principles:**
- Grayscale research report aesthetic. Clean sections with generous whitespace.
- No DeFi jargon (no "vault deposit," no "connect wallet" as primary CTA).
- Deposit flow accessible but secondary — small "Deposit USDC" button for existing LPs, not the hero.
- Mobile-optimized: Nic will share this link via WeChat.

**What it replaces:** Current VaultPage.jsx (987 lines) + strategy.html + Quant GP section from App.jsx

### 5.4 Asset Deep Dive (/cis/{symbol})

**Purpose:** Single-asset intelligence page. The "stock page" of CometCloud.

**Hierarchy:**
1. (DOMINANT) Asset header: Symbol, Name, CIS Score (large), Grade badge, Signal badge, Price, 24h/7d/30d changes.
2. (PRIMARY) 5-pillar breakdown: radar chart + 5 horizontal bars with universe average ticks. Each pillar: score, percentile rank, and one-sentence explanation of what's driving it.
3. (PRIMARY) AI-generated narrative (from Qwen3): 2-3 paragraphs explaining why this asset is graded where it is, what the regime context means for it, and what pillar shifts would change the signal.
4. (SECONDARY) Regime sensitivity: table showing this asset's regime-weighted score under all 6 regimes.
5. (SECONDARY) 7-day grade trajectory: sparkline + migration heatmap row.
6. (TERTIARY) Compare CTA: "Compare with..." → opens /compare with this asset pre-selected.

**Data requirements:**
- GET /api/v1/cis/asset/{symbol} (pillars, grade, signal)
- GET /api/v1/cis/history/{symbol}?days=7 (trajectory)
- GET /api/v1/cis/regime-analysis (regime sensitivity)
- MCP lmstudio_cis_narrative (AI narrative generation) OR cached from Mac Mini push

**New backend requirement:**
- Per-asset AI narrative: either generated on demand (Qwen3 via LM Studio MCP) or pre-generated and cached during Mac Mini scoring cycle. Add narrative field to CIS push payload.

**Design principles:**
- Analyst report format. Not a trading card.
- The AI narrative is the centerpiece — the thing you can't get from any other platform.
- Pillar explanations should be human-readable: "Fundamental score 72: driven by $18B market cap (top 5% of universe) and 0.95 circulating/total supply ratio."

**What it replaces:** Nothing directly — this is a new page type. Currently clicking an asset in CISLeaderboard opens a sticky side panel with limited data.

### 5.5 Compare (/compare)

**Purpose:** Side-by-side pillar analysis for 2-6 assets.

**Already built:** CISCompare.jsx (680 lines) — needs styling refinement and promotion from a tab within CISLeaderboard to a standalone page or modal.

**Changes needed:**
- Route as /compare?symbols=BTC,ETH,SOL or accessible as overlay from intelligence page.
- Add regime-weighted score comparison (already calculated in backend).
- Add TSV/CSV export (already implemented as clipboard copy).

### 5.6 Portfolio (/portfolio)

**Already built and separated.** Needs refinement:
- Rename "Portfolio Builder" to "Allocation Modeler" (clearer purpose for institutional users)
- Position as due diligence tool: "Model CIS-driven allocations under different risk profiles"
- My Portfolio tab: wallet-gated, localStorage watchlist + P&L tracker

### 5.7 Analytics (/analytics)

**Already built and separated.** Needs refinement:
- Lead with the most compelling chart: return dispersion by CIS grade (if A-grade assets outperform D-grade by 15%, that's the headline)
- Add explanatory text: what each chart proves about the scoring system's predictive power
- Position as "CIS Methodology Evidence" — the page a quant PM reviews during due diligence

### 5.8 Methodology (/methodology)

**Purpose:** Public reference for CIS methodology. For analysts writing reports, quant PMs evaluating the engine, and agents consuming the API.

**Content source:** CIS_METHODOLOGY.md (already written) — render as styled HTML page.

**Sections:**
1. Overview: what CIS is, 5 pillars, 6 regimes
2. Pillar definitions: formula, data sources, scoring curves
3. Regime detection: trigger conditions, pillar weight adjustments
4. Grading: absolute thresholds, LAS calculation
5. Data tiers: T1 (Mac Mini full engine) vs T2 (Railway estimation)
6. Compliance: positioning-only signals, no advisory language

### 5.9 API Documentation (/api)

**Purpose:** Developer onboarding for agents and institutional integrations.

**Content:**
1. Quick start: get CIS universe in 3 API calls
2. Authentication: public endpoints vs. rate-limited agent API vs. WebSocket
3. Endpoint reference: organized by domain (CIS, Market, DeFi, Signals, Macro)
4. Response schemas with examples
5. Agent discovery: /.well-known/agent.json spec
6. WebSocket protocol: auth handshake, message format, heartbeat
7. Rate limits and SLAs

**Implementation:** Static HTML page generated from a structured template. Can be maintained as markdown and rendered at build time.

---

## 6. BUILD VS. CUT MATRIX

### Build (new)

| Item | Effort | Dependency | Priority |
|------|--------|------------|----------|
| Landing page (/ fork) | 1 day | macro-pulse API | P0 |
| Intelligence terminal (/intelligence) | 3-4 days | Regime Brief, CIS universe, Signal Feed | P0 |
| Fund page (/fund) | 2 days | Lead capture API, strategy content | P0 |
| Asset deep dive (/cis/{symbol}) | 2-3 days | Per-asset narrative from Qwen3 | P1 |
| Methodology page (/methodology) | 1 day | CIS_METHODOLOGY.md content | P1 |
| API documentation (/api) | 2 days | Endpoint inventory | P1 |
| Shared nav component | 0.5 day | Token system | P0 |
| Per-asset AI narrative (backend) | 1-2 days | Minimax + Qwen3 | P1 |

### Keep (refine)

| Item | Changes needed | Priority |
|------|---------------|----------|
| /portfolio | Rename to "Allocation Modeler," position as due diligence tool | P2 |
| /analytics | Lead with return dispersion, add explanatory text | P2 |
| /compare | Promote to standalone route or modal from intelligence page | P1 |
| /strategy | Simplify, redirect LP flow to /fund | P2 |
| /vision | Keep as brand page, link from footer only | P3 |
| /share | Keep for OG image generation | P3 |
| /quant | Keep for internal monitoring (Minimax) | P3 |

### Cut

| Item | Lines saved | Reason |
|------|------------|--------|
| App.jsx hero section | ~120 | Replaced by live regime brief |
| App.jsx MarketDashboard section | ~130 | Prices inline in CIS leaderboard |
| App.jsx scroll-to-section architecture | ~100 | Direct page navigation |
| App.jsx CrossAssetView | ~150 | Folded into intelligence terminal as a filter/view |
| App.jsx Quant GP section | ~200 | Moves to /fund |
| App.jsx My Portfolio section | (already moved) | Done |
| MarketPage.jsx | 920 | Redundant |
| ProtocolPage.jsx | 1,079 | Dead code (hardcoded data) |
| IntelligencePage.jsx VC/Macro tabs | ~350 | VC data isn't CometCloud IP; macro events folded into narrative |

---

## 7. SCENARIO ANALYSIS

### Scenario A: "Conviction Engine" (recommended)

**Thesis:** CometCloud is the regime-aware CIS intelligence platform. The fund is the commercial vehicle that proves the engine works. Intelligence leads, fund follows.

**Build order:** Intelligence terminal → Fund page → Asset deep dive → API docs
**Landing page:** Fork to Intelligence or Fund
**Positioning vs. competitors:** "Artemis shows you data. CometCloud shows you conviction."

**Strengths:**
- CIS is the defensible IP; building around it creates compounding value
- Intelligence platform can scale to thousands of users (SaaS model)
- Fund AUM grows as intelligence platform builds trust
- API/agent consumption creates network effects
- Regime-aware scoring is genuinely novel — no competitor does this

**Risks:**
- Intelligence platform alone doesn't generate revenue until API pricing is introduced
- Fund needs track record to convert LPs (chicken-and-egg with Minimax backtest)
- Requires Qwen3 narrative engine to be reliable (currently dependent on Mac Mini uptime)

**Revenue model:**
- Phase 1: Fund performance fees (0% + 20% carry)
- Phase 2: API subscription (Artemis-like $300/mo Pro tier)
- Phase 3: Enterprise data feeds (Kaiko-like institutional contracts)

**Time to first LP conversation:** 2-3 weeks (fund page + strategy page ready)
**Time to API revenue:** 3-6 months (requires user base + documentation)

### Scenario B: "Fund First"

**Thesis:** The fund is the product. The intelligence platform is marketing for the fund. Every page exists to convert LPs.

**Build order:** Fund page → Landing page → Strategy refinement → Intelligence (simplified)
**Landing page:** Fund pitch with CIS proof points
**Positioning:** "AI-curated crypto Fund-of-Funds with zero management fee"

**Strengths:**
- Clear commercial focus — every dollar of development drives toward AUM
- Simpler to build (fewer pages, less frontend complexity)
- Faster time to LP conversations

**Risks:**
- Without a public intelligence platform, there's no discovery engine
- Fund-only positioning looks like every other crypto fund launch
- No moat — intelligence platform is the moat
- Nic's family office contacts need a reason to believe the AI is real (intelligence platform IS the proof)

**Revenue model:** Fund performance fees only
**Time to first LP conversation:** 1-2 weeks
**Time to differentiation:** Unclear — fund performance takes 6+ months to prove

### Scenario C: "Agent Marketplace"

**Thesis:** CometCloud is infrastructure for autonomous agents. The CIS API is the product. The fund is one customer of the API. Human-facing pages are secondary.

**Build order:** API docs → Agent API hardening → WebSocket reliability → Fund page → Intelligence (minimal)
**Landing page:** Developer-oriented "Build with CIS" pitch
**Positioning:** "The intelligence layer for autonomous crypto agents"

**Strengths:**
- Highest long-term optionality (250K+ daily active agents, $2T+ monthly agent stablecoin activity)
- API revenue is recurring and scalable
- Aligns with Solana Agent Skills SDK momentum
- Defensible if CIS becomes the standard scoring layer

**Risks:**
- Agent market is speculative — adoption timelines uncertain
- No immediate revenue (agents don't pay yet; market needs to develop)
- Nic's institutional contacts don't care about agent infrastructure
- Jazz's immediate need ($30M AUM) isn't served by this path

**Revenue model:** API consumption fees (per-request or subscription)
**Time to first LP conversation:** 4-6 weeks (fund page is secondary)
**Time to API adoption:** 3-12 months (depends on agent ecosystem maturation)

### Recommendation: Scenario A with elements of B

Build the intelligence platform AND the fund page in parallel. The intelligence platform is the discovery engine and proof of capability. The fund page is the conversion mechanism. Neither works without the other. API documentation is Phase 2 but architecturally prepared from day 1.

---

## 8. PHASED ROADMAP

### Phase 0: Foundation (Days 1-2)

**Objective:** Shared components and blocked items resolved.

| Task | Owner | Est. | Blocked on |
|------|-------|------|------------|
| Jazz: git push + Supabase SQL + Railway env vars | Jazz | 30min | — |
| Jazz: COINGECKO_API_KEY in Railway | Jazz | 5min | — |
| Minimax: v4.1 alignment + cis_push verify | Minimax | 2h | Jazz push |
| Shared Nav component (brand, page tabs, regime badge, wallet) | Seth | 4h | — |
| Shared PageShell component (ambient orbs, body style, responsive) | Seth | 2h | — |
| Delete MarketPage.jsx, ProtocolPage.jsx (dead code) | Seth | 15min | Jazz push |

### Phase 1: Core Product (Days 3-7)

**Objective:** Intelligence terminal and fund page live.

| Task | Owner | Est. | Depends on |
|------|-------|------|------------|
| Landing page (/ fork: Intelligence or Fund) | Seth | 1d | SharedNav |
| Intelligence terminal (/intelligence) | Seth | 3-4d | SharedNav, macro-brief API, CIS universe |
| — Regime Brief full-width component | Seth | 4h | macro/brief endpoint |
| — CIS leaderboard (dense, sortable, filterable) | Seth | 8h | Refactor from CISLeaderboard.jsx |
| — Signal Feed (top 5, curated) | Seth | 4h | Refactor from SignalFeed.jsx |
| — Protocol Intelligence (collapsible) | Seth | 2h | ProtocolIntelligence.jsx exists |
| Fund page (/fund) | Seth | 2d | Lead capture API, strategy content |
| — Strategy section content | Jazz | 2h | — |
| — Risk framework cards | Seth | 3h | — |
| — GP partner section (EST Alpha) | Seth | 2h | — |
| — Lead capture form | Seth | 2h | leads.py already built |

**Milestone:** Nic can share /fund link with family offices. Kai can use /intelligence daily.

### Phase 2: Depth (Days 8-14)

**Objective:** Asset deep dive, methodology, and API docs.

| Task | Owner | Est. | Depends on |
|------|-------|------|------------|
| Asset deep dive (/cis/{symbol}) | Seth | 2-3d | CIS universe data shape |
| — 5-pillar radar + breakdown | Seth | 4h | — |
| — AI narrative integration | Seth + Minimax | 1d | Qwen3 narrative per asset |
| — Regime sensitivity table | Seth | 3h | regime-analysis endpoint |
| Per-asset narrative (backend) | Minimax | 1-2d | Mac Mini Qwen3 |
| Methodology page (/methodology) | Seth | 1d | CIS_METHODOLOGY.md |
| API documentation page (/api) | Austin | 2d | Endpoint inventory |
| Compare promotion (standalone route) | Seth | 4h | CISCompare.jsx exists |

**Milestone:** Mei can reference CIS in research reports. Agents can onboard via /api.

### Phase 3: Polish + Evidence (Days 15-21)

**Objective:** Analytics evidence, portfolio refinement, mobile, performance.

| Task | Owner | Est. | Depends on |
|------|-------|------|------------|
| Analytics refinement (return dispersion headline) | Seth | 1d | ScoreAnalytics.jsx |
| Portfolio refinement (rename, due diligence framing) | Seth | 1d | portfolio.jsx |
| Mobile optimization for /intelligence and /fund | Seth | 2d | Phase 1 pages |
| Performance audit (Lighthouse, bundle analysis) | Seth | 1d | — |
| Minimax: backtest results (T1 vs T2 alpha) | Minimax | 2d | Freqtrade dry run |
| Strategy.html simplification (redirect to /fund) | Seth | 2h | /fund page |
| OG image update for new pages | Seth | 3h | social.py |

**Milestone:** All four personas served. Mobile-ready. Evidence of CIS predictive power.

### Phase 4: Distribution (Days 22-30)

**Objective:** LP conversations, institutional feedback, iteration.

| Task | Owner | Est. | Depends on |
|------|-------|------|------------|
| /fund walkthrough with Nic | Jazz + Nic | 1h | Phase 1 |
| Identify 3-5 target family offices | Nic | ongoing | /fund reviewed |
| Seed investor deck (complements /fund page) | Jazz + Seth | 2d | Phase 1 |
| /intelligence feedback from 2-3 crypto PMs | Jazz | ongoing | Phase 1 |
| API beta access for 1-2 agent developers | Seth | 1d | Phase 2 |
| HK SFC / compliance advisor engagement | Jazz | ongoing | — |
| OSL stablecoin integration timeline | Jazz | ongoing | — |

---

## 9. SUCCESS METRICS

### Week 2 (Phase 1 complete)

- /intelligence loads in <2s with 50+ assets, regime brief, top 5 signals
- /fund page complete with lead capture form working
- Nic has shared /fund with at least 1 contact
- CIS universe populated via Mac Mini (not Railway fallback)

### Week 4 (Phase 2-3 complete)

- /cis/{symbol} pages live for all 65+ assets with AI narratives
- /methodology and /api pages published
- At least 1 LP enquiry captured via /fund form
- Lighthouse performance score >80 on /intelligence

### Week 8 (Phase 4 outcomes)

- 3+ LP conversations in pipeline
- 1+ agent developer using the API
- CIS backtest showing statistically significant grade-to-return correlation
- Fund structure reviewed by compliance advisor

---

## 10. OPEN QUESTIONS FOR JAZZ

1. **Landing page fork:** Is "Intelligence Platform" | "Fund-of-Funds" the right framing? Or should the landing page be more fund-focused for the current fundraising priority?

2. **Fund page tone:** Institutional factsheet (Grayscale-style) or more narrative (Pantera letter-style)?

3. **API pricing:** When do we introduce paid tiers? Free during beta → Pro at $300/mo (Artemis parity) → Enterprise custom?

4. **Wallet connect placement:** Should it be in the nav on every page, or only on /portfolio and /fund (deposit flow)?

5. **Market data:** Remove entirely from the core experience, or keep as a "Markets" tab on the intelligence page for users who want it?

6. **VC funding data:** Cut entirely, or keep as a low-priority tab for analysts?

7. **Quant GP naming:** Should EST Alpha be named on the fund page now, or "GP Partner" generically until the relationship is formalized?

8. **Mobile priority:** Is /fund mobile-critical (Nic sharing via WeChat) while /intelligence is desktop-primary?

---

*Build things that feel alive. But first, know exactly who they're alive for.*
