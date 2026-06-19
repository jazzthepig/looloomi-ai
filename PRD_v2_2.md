# CometCloud AI — Product Requirements Document v2.2

**Document owner:** Jazz
**Date:** 2026-04-07
**Status:** Optimized from v2.1 after founder review

---

## 0. WHAT CHANGED AND WHY

v2.1 misdiagnosed the core problem and over-separated the fund from the intelligence terminal. v2.2 corrects both:

1. **The B/B+ clustering is a feature, not a bug.** CometCloud's inclusion standard has already filtered out the bad assets before they reach the scoring engine. Normal distribution inside a curated universe is exactly what institutional-grade ratings look like. The Morningstar Medalist Rating only applies to funds their analysts cover. Bloomberg ESG scores only apply to companies that meet data completeness thresholds. The *curation itself is the product*. **Phase 0 is no longer "fix score differentiation" — it is "publish the inclusion standard as the headline."**

2. **Fund and Intelligence are one entity, not competing priorities.** The fund is the business. The intelligence terminal is the product. They feed each other: the product earns credibility through public methodology and live data; the business captures value through fee economics and GP partnerships. v2.1 framed them as a sequencing trade-off. That was wrong. They ship on different timelines because they serve different audiences, not because one comes first.

3. **Model stack corrected.** v2.1 referenced Qwen3-32B and older models. The actual stack is Qwen 3.5 35B-A3B (MoE, 3B active, 262K context, released Feb 2026) and Gemma 4 26B-A4B (MoE, 4B active, 256K context, released April 2026). Both are significantly more capable and more efficient than the models v2.1 referenced. The Mac Mini M4 Pro 48GB memory footprint is different, inference speed is different, and the per-asset narrative generation budget is different. §4.4 and §5 have been rewritten accordingly.

4. **Claude Code leak integration is now Phase 1, not Phase 3 evaluation.** The leaked source revealed architectural patterns (KAIROS-style persistent memory via append-only logs, Coordinator mode with XML task notifications, AutoDream memory consolidation, 15-second blocking budget for proactive actions) that directly apply to CometCloud's multi-agent development workflow. These are patterns to *adopt*, not tools to *install*. The leak itself is not open source — it is a reference implementation to study. CometCloud's own agent infrastructure should mirror the patterns that make sense for a solo-founder-plus-AI team.

5. **Competitors are not benchmarks — they are constraint maps.** The PRD should not frame Nansen, Dune, Kaito as things to match. Their structure and management constraints prevent them from doing what CometCloud does. The competitor section is now a structural analysis of *what they cannot do* rather than *what we must copy*.

6. **Ownership is Jazz + AI stack. Period.** All roadmap tasks are owned by Jazz orchestrating MiniMax, Claude, Qwen, and Gemma. No Terry, no Seth. This is a solo founder running a multi-agent team.

---

## 1. EXECUTIVE SUMMARY

CometCloud is a **curated cross-asset intelligence rating system** paired with an institutional Fund-of-Funds business. The rating system publishes its inclusion standard and rejection criteria openly — what makes the cut, what doesn't, and why. The fund is the commercial vehicle that proves the intelligence works. The two share an engine, a macro regime detector, and a public methodology.

The product answer to "what do you sell that I can't build myself?" is: **"We already rejected 95% of the crypto market using a public standard. What remains is scored across 5 pillars with regime-aware weights. You get our judgment about what belongs in an institutional portfolio, expressed as a filter and a ranking."**

The business answer to "why should I allocate?" is: **"Same judgment, wrapped in a fund structure with zero management fee, performance-only economics, and a compliance pathway. The fund is long the same assets our intelligence ranks as overweight. You can verify the signal daily on the public terminal."**

Four personas drive the architecture:
- **Rachel (LP)** — opens the fund page, sees factsheet density, schedules a call
- **Kai (trader)** — opens the intelligence terminal, sees the curated universe, references CIS in his own book
- **Mei (analyst)** — opens the methodology page, references the inclusion standard in her reports
- **Agent-47 (AI agent)** — discovers via MCP server, calls CIS as a tool, receives structured conviction signals

---

## 2. STRATEGIC POSITIONING

### 2.1 Curation as the headline product

The single most important narrative shift from v2.1: **the universe is the product, not the scores inside it.**

Every competitor gives you everything. CoinGecko: 10,000+ tokens. Nansen: every labeled wallet. Dune: every on-chain event. The customer problem is not "I need more data." The customer problem is "I need someone to tell me what is investable and what is not, with standards I can audit."

CometCloud's answer is an inclusion standard that produces a ~50-asset investable universe from the tens of thousands of assets in crypto plus selected TradFi. The standard is public. The rejection list is public. The rationale for each rejection is public. This is what Morningstar built 40 years of trust on — not the star ratings themselves, but the analyst coverage gate that decided which funds got rated at all.

**What the public standard covers:**

- **Liquidity thresholds:** minimum 30-day average volume, minimum market depth, minimum exchange count
- **Data completeness:** minimum on-chain data availability (for crypto), minimum audited financial history (for TradFi ETFs)
- **Custody-grade:** must be custodiable by at least one institutional custodian (Coinbase Custody, BitGo, Fireblocks, etc.)
- **Regulatory status:** not classified as a security in CometCloud's primary jurisdictions, no active enforcement action
- **Token mechanics (crypto only):** circulating/total supply ratio minimum, vesting transparency, no active emission exploits
- **Time in market:** minimum 180 days of trading history
- **Team/protocol integrity:** no rug-pull history, no documented unresolved exploits, no anonymous-team red flags

Assets that fail any single criterion are excluded. The exclusion list is published with specific reasons. Mei can reference "rejected for liquidity" or "rejected for anonymous team with no audit" in her reports. Kai can see exactly what universe CIS operates over. Rachel sees that the fund only invests in what passes the standard.

**The leaderboard showing mostly B-grades is correct.** After the filter, the remaining universe is already above the bar. Normal distribution inside that universe is what calibrated scoring looks like. A leaderboard where every asset was A would mean the filter is too permissive; a leaderboard where every asset was F would mean the scoring is broken. B-centered distribution with a few A and a few C is the signal of a working rating system over a quality universe.

### 2.2 Fund and Intelligence as one entity

The v2.1 framing of "Fund-first, Intelligence-second" was wrong. These are not competing priorities.

**The business layer (Fund):**
- Closes LP conversations
- Captures fee economics
- Runs the actual capital
- Establishes GP partnerships
- Carries the regulatory pathway

**The product layer (Intelligence Terminal):**
- Earns public credibility
- Proves the fund's judgment daily
- Distributes via MCP to agents
- Serves analysts like Mei with referenceable methodology
- Generates inbound conversations for the fund

They ship on different timelines not because one comes first, but because they have different readiness gates. The Fund page can ship as soon as the content is written because it's a factsheet — the data requirements are small. The Intelligence Terminal needs the inclusion standard to be published, the CIS engine verified on real data, and the score history to start accumulating. These are different dependency chains, not different priorities.

**What this means for the build:**

```
Day 0-2:  Phase 0 — Publish the inclusion standard + verify engine
Day 3-7:  Phase 1A — Fund page (content-light, design-heavy)
Day 3-7:  Phase 1B — MCP server + methodology page (parallel track)
Day 8-14: Phase 2 — Intelligence terminal with curated universe
Day 15+:  Phase 3 — Asset deep dives, agent docs, KAIROS-style workflow
```

Phase 1A and 1B run in parallel. Both ship by Day 7. The fund is sharable for Nic. The MCP server is discoverable for agents. The methodology is published for Mei. Phase 2 (Intelligence Terminal) ships a week later when the universe data is mature.

### 2.3 Competitors are constraint maps, not benchmarks

v2.1 treated Nansen, Dune, and Kaito as benchmarks CometCloud had to match. This framing is wrong. Those platforms are structurally prevented from doing what CometCloud does by their business models, their data sources, and their go-to-market positioning. They are not competitors in the "who gets there first" sense — they are adjacent products with different shapes.

**Nansen cannot do what CometCloud does because:**
- Their business is labeled wallet data. Cross-asset scoring is outside their data model (no bonds, no ETFs, no commodities).
- They pivoted to execution (Agentic Trading). Execution and rating are structurally incompatible — you can't rate assets you're also trying to sell through.
- Their $49/month pricing cut signals commoditization of raw on-chain data. The intelligence layer they'd need to build to compete is a different product entirely.

**Dune cannot do what CometCloud does because:**
- Their product is a SQL workspace. Opinion is outside the product contract — users write their own queries.
- The community-dashboard flywheel makes rating-agency neutrality impossible. Every rating would conflict with someone's dashboard.
- They operate on raw data, not curated universes. The inclusion standard concept doesn't fit their model.

**Kaito cannot do what CometCloud does because:**
- Their product is attention and information aggregation. Rating requires judgment, not aggregation.
- The Yaps / $KAITO token model tied them to sentiment mining as the core value proposition.
- Their 2026 pivot to Kaito Studio (selective, tier-based marketing campaigns) confirms they are a marketing InfoFi platform, not a rating agency.

**Morningstar cannot do what CometCloud does because:**
- Their Digital Assets category covers 20-25 ETFs/Trusts. The on-chain universe is structurally outside their analyst coverage model.
- They cannot rate tokens directly without assuming regulatory positions they are not prepared to take.
- Their revenue model (subscription research + index licensing) locks them into a slow-moving institutional buyer segment.

**What this means strategically:** CometCloud does not need to win a feature race with any of these platforms. The structural gaps between them define the whitespace CometCloud occupies. The product and business are built in that gap.

### 2.4 Claude Code leak: architectural patterns to adopt

The March 31 Claude Code source exposure is not an open-source opportunity in the license sense — the leaked code is still Anthropic IP. But the architectural patterns revealed in the leak are directly applicable to CometCloud's multi-agent workflow.

**Four patterns to adopt:**

**Pattern 1 — KAIROS-style persistent memory.** Claude Code uses append-only daily markdown logs at `~/.claude/logs/YYYY/MM/DD.md` to maintain context across sessions. CometCloud should adopt the same pattern for the CIS engine: every scoring run writes an append-only log of what changed, what regime the engine detected, and which assets crossed grade boundaries. This creates an audit trail that Mei can reference and Kai can diff against his own book.

**Pattern 2 — Coordinator mode with XML task notifications.** The leak shows a Coordinator agent spawning Worker agents that communicate via `<task-notification>` XML with explicit fields for status, summary, token usage, and duration. CometCloud's current workflow is Jazz manually handing prompts from Claude to MiniMax. Adopting a coordinator pattern means Jazz writes a single task spec, a coordinator agent (Claude or MiniMax) breaks it into worker subtasks, and workers (Qwen, Gemma, MiniMax) report back through a shared task notification format. This replaces manual handoff with structured delegation.

**Pattern 3 — AutoDream memory consolidation.** Claude Code's AutoDream runs a four-phase (Orient → Gather → Consolidate → Prune) memory compaction during idle time, triggered after 24 hours and 5+ sessions, with each phase on a 15-second blocking budget. CometCloud should adopt this for the daily intelligence cycle: at end-of-day, a consolidation pass reviews all score changes, regime shifts, and event intelligence modifications, producing a single consolidated "what changed today" artifact that feeds the next day's Regime Brief.

**Pattern 4 — 15-second blocking budget for proactive actions.** Any background agent that wants to interrupt the foreground workflow has a 15-second hard budget. This is a direct applicability to Jazz's workflow: local Qwen/Gemma background tasks (event classification, semantic deduplication, narrative generation) should all operate under a 15-second proactive budget so they never block the foreground development work.

**What this is not:** CometCloud is not going to run the leaked Claude Code source. It is not going to install KAIROS. It is going to study the patterns, pick the ones that fit a solo-founder multi-agent workflow, and implement them in its own codebase using its own models (Qwen 3.5 35B-A3B and Gemma 4 26B-A4B).

---

## 3. PERSONAS

Unchanged in substance from v2.1. The key refinement is around the inclusion standard:

- **Rachel (LP Allocator).** What's different in v2.2: she sees the inclusion standard on the /fund page. The factsheet includes a one-line summary like "Universe filtered from 10,000+ assets to 52 investable positions using a public 7-criterion standard." This is more credible than any performance projection.

- **Kai (Institutional Trader).** What's different: he can compare his own watchlist against the CometCloud exclusion list. Any asset he holds that failed a criterion becomes a question he can ask his own risk team. The value is not "show me something new" — it's "tell me where my universe diverges from an independently curated one."

- **Mei (Crypto Analyst).** What's different: she can cite the inclusion standard as a reference point in her reports. "CometCloud excludes X for reason Y" becomes a stable reference she can point to. The methodology page is her landing page, not the terminal.

- **Agent-47 (AI Agent).** What's different: the MCP server exposes both the scored universe AND the rejection list. `get_cis_universe()` returns the scored assets. `get_cis_exclusions()` returns the rejected assets with reasons. This is a unique tool surface no other MCP server offers.

---

## 4. PAGE-BY-PAGE REQUIREMENTS (v2.2 REVISIONS)

### 4.1 Landing Page (/)

**Hierarchy:**
1. (DOMINANT) One-line positioning: "Curated cross-asset intelligence for institutional allocators. 10,000+ assets filtered to 52 investable positions using a public standard."
2. (PRIMARY) Live CIS strip: top 5 assets with grade, signal, and regime badge. Updates every 10 minutes.
3. (PRIMARY) Two buttons: "Schedule a conversation" (→ /fund) and "Explore the universe" (→ /intelligence)
4. (SECONDARY) Three small stats: "52 assets covered · 9,948 assets excluded · Methodology public"
5. (TERTIARY) Footer: /methodology, /api, /vision, LinkedIn, contact

The "9,948 excluded" number is the critical trust signal. It is more important than any score differentiation on the leaderboard.

### 4.2 Fund Page (/fund)

**Hierarchy:**
1. (DOMINANT) Fund header, Brevan Howard factsheet density: fund name, strategy tagline, 6 metrics (Target AUM, Fee Structure, Strategy Types, Jurisdictions, Launch Target, Universe Size)
2. (PRIMARY) Strategy section: 3 channels (Trading Agent, Protocol Yield, Fund-of-Funds) as a row of cards with allocation weights
3. (PRIMARY) **NEW: Inclusion standard summary.** One paragraph: "We invest only in assets that pass our public 7-criterion investment-grade standard. The standard is available at cometcloud.ai/methodology. Current universe: 52 assets from an initial pool of 10,000+." Link to methodology.
4. (PRIMARY) Live CIS proof widget: top 10 assets from the scored universe, labeled "Current Fund Intelligence Output"
5. (SECONDARY) Risk Framework: 6 cards (Regulatory, Technology, Fees, On-Chain, Risk Management, Governance)
6. (SECONDARY) GP Partners: EST Alpha card only. No fictitious names.
7. (PRIMARY) "Schedule a Conversation" form → POST /api/v1/leads/enquiry

**Must-not-include list unchanged from v2.1:** no fictitious GP names, no AUM numbers not reflecting committed capital, no performance projections, no "expected return" language.

### 4.3 Methodology Page (/methodology) — PROMOTED TO P0

v2.1 had this as a Phase 3 reference document. **v2.2 promotes it to Phase 1 centerpiece.** The methodology IS the product. It must ship with the fund page.

**Content structure:**

1. **The Inclusion Standard** (the headline)
   - The 7 criteria, explained in plain language
   - For each criterion: the threshold, the rationale, the data source, and what fails
   - Worked examples: "Example rejection: Token X failed on Criterion 3 (custody) because no institutional custodian supports the asset as of [date]."

2. **The Exclusion List**
   - Top 20 notable rejections with reasons
   - Link to complete exclusion list (downloadable CSV)
   - Updated whenever the universe changes
   - Historical additions and removals logged

3. **The CIS Scoring Framework** (secondary)
   - 5 pillars (Fundamental, Momentum, Risk-Adjusted, Sensitivity, Alpha)
   - Regime-aware weight adjustments across 6 macro regimes
   - Signal generation (OVERWEIGHT / UNDERWEIGHT, no BUY/SELL/HOLD)
   - Grade distribution expected curve

4. **Data Sources**
   - Binance for crypto market data (primary)
   - DeFiLlama for TVL and protocol metrics
   - CoinGecko Pro for cross-chain coverage
   - Alternative.me for fear & greed
   - Local Qwen 3.5 35B-A3B for event classification
   - Local Gemma 4 26B-A4B for narrative generation

5. **Compliance Positioning**
   - Why we output OW/UW signals only
   - What we are not: not a broker-dealer, not an investment advisor, not a custodian
   - What we are: a rating and research platform with a paired fund-of-funds product

6. **Update Cadence**
   - Universe reviewed monthly
   - Scores updated every 30 minutes
   - Exclusions audited quarterly
   - Methodology changes published with version history

**Design:** Bloomberg terminal density. Navigable table of contents. Direct-link anchors for every criterion. Mei should be able to cite "cometcloud.ai/methodology#criterion-3" in a footnote.

### 4.4 Intelligence Terminal (/intelligence)

Structure unchanged from v2.1 §5.2. Changes:

- **Regime Brief** uses Gemma 4 26B-A4B for generation (not Qwen3.5 — see §5 below for the model allocation rationale).
- **Universe display** shows the full 52-asset curated universe by default. A toggle reveals "Why these 52? See methodology →" linking to /methodology.
- **Filter chip above the table:** "Showing 52 of 52 investable assets (10,000+ excluded by inclusion standard)."
- **Score distribution histogram** (small, optional) shows the grade distribution as a calibration proof — this is where the B-centered curve becomes evidence, not a bug.

### 4.5 Asset Deep Dive (/cis/{symbol})

Structure unchanged from v2.1. Changes:

- **Narrative generation** moves from Qwen3-32B to **Gemma 4 26B-A4B** (4B active parameters, MoE, optimized for fast narrative generation with native function calling).
- **Narrative generation budget** reduced: with Gemma 4 26B-A4B at 4B active parameters, per-asset narratives can generate in ~10-15 seconds on the Mac Mini M4 Pro, allowing refresh every 4 hours instead of every 6 hours (52 assets × 6 refreshes/day = 312 narrative generations daily, well within capacity).
- **Fallback hierarchy unchanged:** fresh narrative → stale narrative with timestamp → no narrative slot.

### 4.6 MCP Server

**All tools updated for curation-forward positioning:**

- `get_cis_universe()` — returns the 52-asset investable universe with scores
- `get_cis_exclusions()` — **NEW tool.** Returns the exclusion list with reasons. No other MCP server offers this.
- `get_inclusion_standard()` — **NEW tool.** Returns the 7-criterion standard as structured JSON, machine-readable for agent reasoning.
- `get_cis_asset(symbol)` — returns pillar breakdown for a single asset. If asset is excluded, returns the rejection reason instead.
- `get_cis_history(symbol, days)` — score trajectory
- `get_regime_context()` — current macro regime + weight adjustments

**Tool description example (for `get_cis_exclusions`):**

> "Returns the complete list of assets excluded from CometCloud's investable universe with specific rejection reasons against the 7-criterion public inclusion standard. Covers 9,948+ excluded assets including liquidity failures, custody gaps, regulatory concerns, and integrity issues. Unique institutional-grade exclusion methodology not available from any other data provider. Updated whenever universe composition changes. Actively maintained."

This tool is the differentiator. No competitor's MCP server returns a structured exclusion list. Agents building portfolios will call this tool to avoid assets that fail institutional-grade standards. This is the moment CometCloud becomes the default institutional filter for the agent economy.

---

## 5. MODEL STACK (CORRECTED)

v2.1 referenced Qwen3-32B. The actual stack is different and more powerful.

### 5.1 Qwen 3.5 35B-A3B (released Feb 24, 2026)

- **Architecture:** Mixture of Experts, 35B total parameters, 3B active per token
- **Context:** 262,144 tokens native, extensible to 1M via YaRN
- **Positioning:** Reportedly surpasses Qwen3-235B-A22B-2507 despite being 6x smaller — efficiency gains from architecture and RL training, not parameter count
- **Use case for CometCloud:** Event classification, semantic deduplication, complex multi-step reasoning for CIS methodology edge cases
- **Memory footprint on Mac Mini M4 Pro 48GB:** Q4 quant fits comfortably, leaves headroom for Gemma 4 to run concurrently
- **Inference speed:** ~15 tokens/second on M4 Pro unified memory (community reported)

### 5.2 Gemma 4 26B-A4B (released April 2, 2026)

- **Architecture:** Mixture of Experts, 26B total parameters, 4B active per token
- **Context:** 256K tokens
- **Positioning:** LMArena text score of 1441, ranked #6 among open models, outperforms models 20x its size
- **Use case for CometCloud:** Per-asset narrative generation, Regime Brief generation, fast function calling for tool orchestration
- **Memory footprint on Mac Mini M4 Pro 48GB:** Q4 quant comfortably co-resident with Qwen 3.5 35B-A3B
- **Inference speed:** Runs "almost as fast as a 4B-parameter model" per Google's release notes
- **Native function calling:** Built-in, enabling cleaner MCP tool integration than Qwen

### 5.3 Model allocation for CometCloud workloads

| Workload | Model | Rationale |
|----------|-------|-----------|
| Per-asset narrative generation | Gemma 4 26B-A4B | Fast inference, native function calling, 4B active params |
| Regime Brief generation | Gemma 4 26B-A4B | Speed priority; narrative is customer-facing |
| Event classification (political, FOMC, regulatory) | Qwen 3.5 35B-A3B | Stronger reasoning, complex multi-step event scoring |
| Semantic deduplication (event fingerprinting) | Qwen 3.5 35B-A3B | Embeddings quality matters for dedup accuracy |
| Methodology Q&A (internal tooling) | Qwen 3.5 35B-A3B | Complex reasoning over the full methodology document |
| Quick lookups and tool calls | Gemma 4 26B-A4B | Speed + native function calling |

**Both models run concurrently via LM Studio on the Mac Mini M4 Pro.** Total memory budget with both loaded in Q4: approximately 35-40GB of the 48GB unified memory, leaving ~8GB for Freqtrade, FastAPI sidecars, and macOS. Tight but workable.

### 5.4 Cloud fallback (deferred)

No cloud fallback in Phase 1-2. The Mac Mini is the single source of inference. Phase 4 introduces Groq or Together.ai API as a warm fallback for the 99.9% SLA requirement when institutional clients depend on uptime. Until then, graceful degradation on the frontend (stale narrative badges, "last generated Xh ago" indicators) is the resilience strategy.

---

## 6. PHASED ROADMAP (v2.2)

### Phase 0: Publish the standard (Days 0-2)

**Objective:** The inclusion standard is public. The exclusion list is populated. The engine runs on the curated universe only.

| Task | Owner | Est. | Acceptance |
|------|-------|------|------------|
| Draft the 7-criterion inclusion standard (plain language) | Jazz | 3h | 7 criteria, each with threshold + rationale + data source |
| Run the universe filter against initial asset pool | Jazz + MiniMax | 2h | 52 ± 10 assets pass; exclusion reasons documented |
| Populate exclusion list with top 20 notable rejections + reasons | Jazz + MiniMax | 2h | Publishable list with specific reasons |
| Update CIS engine to only score the curated universe | Jazz + MiniMax | 2h | Leaderboard reflects ~52 assets, not 40 |
| Verify grade distribution on curated universe | Jazz | 1h | Normal distribution B-centered is acceptable |
| Push Supabase SQL + env vars (SUPABASE_URL, SUPABASE_KEY, COINGECKO_API_KEY) | Jazz | 30min | Score history starts accumulating |
| Delete MarketPage.jsx, ProtocolPage.jsx (dead code) | MiniMax | 15min | Cleanup |

**Gate:** Inclusion standard is written. Exclusion list has at least 20 specific rejections. Supabase is writing. CoinGecko Pro is active.

### Phase 1A: Fund page + landing page (Days 3-7)

**Objective:** Nic has a shareable fund page. Landing page routes visitors correctly.

| Task | Owner | Est. |
|------|-------|------|
| Shared Nav component | MiniMax | 4h |
| PageShell component (Turrell palette, responsive) | MiniMax | 2h |
| Landing page (curation-forward with "9,948 excluded" stat) | MiniMax | 1d |
| Fund page hero block (Brevan Howard factsheet density) | MiniMax | 1d |
| Fund page strategy section (3 channels) | Jazz + MiniMax | 4h |
| Fund page inclusion standard summary paragraph | Jazz | 1h |
| Fund page risk framework cards | Jazz + MiniMax | 4h |
| Fund page GP partners section (EST Alpha only) | Jazz + MiniMax | 2h |
| Lead capture form → POST /api/v1/leads/enquiry | MiniMax | 3h |
| First Nic review + revisions | Jazz + Nic | 2h |

### Phase 1B: Methodology page + MCP server (Days 3-7, parallel to 1A)

**Objective:** Methodology is published. MCP server is live and discoverable.

| Task | Owner | Est. |
|------|-------|------|
| /methodology page with 7-criterion standard | Jazz + MiniMax | 1d |
| Exclusion list page with top 20 rejections | Jazz + MiniMax | 4h |
| Downloadable exclusion CSV endpoint | MiniMax | 2h |
| FastMCP wrapper over /api/v1/agent/cis | MiniMax | 4h |
| New MCP tool: `get_cis_exclusions()` | MiniMax | 2h |
| New MCP tool: `get_inclusion_standard()` | MiniMax | 2h |
| Assertive tool descriptions for all 6 tools | Jazz + MiniMax | 2h |
| /.well-known/agent.json + /llms.txt | MiniMax | 1h |
| Submit to MCP Registry + PulseMCP + MCP.SO + LobeHub | Jazz | 2h |
| Deploy MCP server as Railway sidecar | MiniMax | 2h |

**Gate at Day 7:** Fund page shared with Nic. Methodology public. MCP server discoverable on at least 2 registries. External MCP client can successfully call `get_cis_exclusions()`.

### Phase 2: Intelligence terminal (Days 8-14)

**Objective:** Kai and Mei have a working terminal with the curated universe.

| Task | Owner | Est. |
|------|-------|------|
| Intelligence terminal page skeleton | MiniMax | 1d |
| Regime Brief component (Gemma 4 26B-A4B generation) | Jazz + MiniMax | 1d |
| Regime Brief stale-state handling (always show last cached) | MiniMax | 2h |
| CIS Leaderboard dense table with 52-asset universe | MiniMax | 1d |
| "Why these 52?" filter chip linking to /methodology | MiniMax | 2h |
| Score distribution histogram (small, as calibration proof) | MiniMax | 4h |
| Signal Feed top 5 curated | MiniMax | 4h |
| Protocol Intelligence collapsible panel | MiniMax | 2h |
| Asset deep dive basic pillar view | MiniMax | 1d |
| Asset deep dive regime sensitivity table | MiniMax | 3h |
| Gemma 4 narrative generation integration | Jazz + MiniMax | 1d |
| Per-asset narrative cron (4-hour cadence) | Jazz + MiniMax | 4h |

### Phase 3: Workflow upgrades from Claude Code patterns (Days 15-21)

**Objective:** Adopt KAIROS-style persistent memory, Coordinator mode, and AutoDream patterns for the CometCloud multi-agent development workflow.

| Task | Owner | Est. | Pattern adopted |
|------|-------|------|-----------------|
| Append-only daily logs at `~/.cometcloud/logs/YYYY/MM/DD.md` | Jazz + MiniMax | 1d | KAIROS persistent memory |
| CIS engine audit log (what changed, which assets crossed grades) | Jazz + MiniMax | 1d | KAIROS append-only pattern |
| Coordinator task spec format (XML task notifications) | Jazz | 4h | Coordinator mode |
| Worker subtask delegation (Claude coordinates Qwen/Gemma/MiniMax) | Jazz + MiniMax | 2d | Coordinator mode |
| Daily consolidation pass (Orient → Gather → Consolidate → Prune) | Jazz + MiniMax | 1d | AutoDream |
| 15-second blocking budget for all proactive background agents | Jazz + MiniMax | 4h | KAIROS blocking budget |
| /api documentation page | MiniMax | 2d | Serves Agent-47 persona |
| Analytics refinement (lead with inclusion/exclusion stats) | MiniMax | 1d | Evidence for Kai |

### Phase 4: Distribution and iteration (Days 22-30)

Unchanged from v2.1 Phase 4 in substance. LP conversations in flight, first agent developer on the API, compliance advisor engaged, event-driven intelligence layer Phase 1 (whale alerts only).

### April conference readiness checklist

- [ ] Inclusion standard published with 7 criteria
- [ ] Exclusion list with at least 20 specific rejections
- [ ] /methodology page live and linkable
- [ ] Fund page mobile-optimized and shared by Nic
- [ ] Landing page shows "52 investable / 9,948 excluded" stat
- [ ] Intelligence terminal loads with 52-asset curated universe
- [ ] MCP server live with `get_cis_exclusions()` tool (the unique differentiator)
- [ ] Registered on at least 2 MCP registries
- [ ] Asset deep dive pages render with or without Gemma 4 narrative
- [ ] Regime Brief never shows empty state
- [ ] No fictitious GP names anywhere
- [ ] Harvest Fund background and EST Alpha partnership visible as trust signals
- [ ] Lead capture form working and delivering to Jazz's email
- [ ] At least 2 weeks of score history in Supabase

---

## 7. SUCCESS METRICS

### Week 1 (Phase 0 + Phase 1A/1B start)
- Inclusion standard published and linkable
- Exclusion list has 20+ entries with specific reasons
- Fund page live and reviewed by Nic
- MCP server discoverable on 2+ registries with unique `get_cis_exclusions()` tool

### Week 2 (Phase 1 complete, Phase 2 in progress)
- Nic has shared /fund with at least 3 LP contacts
- At least 1 external MCP client successfully calls `get_cis_exclusions()`
- Methodology page has at least 10 external visits (tracked via simple logging)
- Intelligence terminal skeleton in place

### Week 4 (Phase 2-3 complete)
- Full intelligence terminal with 52-asset universe live
- /cis/{symbol} pages live with Gemma 4 narratives
- /api documentation published
- At least 1 LP enquiry captured via /fund form
- KAIROS-style append-only logs running for CIS engine
- At least 1 week of grade migration data visible

### Week 8 (Phase 4 outcomes)
- 3+ LP conversations in pipeline
- 1+ agent developer using the MCP server (specifically the exclusion list)
- CIS backtest running continuously via AutoResearch-style loop
- Coordinator mode workflow replacing manual prompt handoff
- Fund structure reviewed by compliance advisor

---

## 8. OPEN QUESTIONS FOR JAZZ

1. **The 7 criteria:** The draft in §2.1 is a starting point. Which criteria do you want to adjust, add, or remove? This is the most important decision in the entire PRD because it defines the universe.

2. **Universe size target:** Is 52 assets the right number? Morningstar Medalist covers ~1,500 funds. S&P 500 covers 500 equities. Institutional crypto fund universes typically range 20-100. Where does CometCloud want to sit?

3. **Exclusion list depth:** Should the public exclusion list show all 9,948 rejections with reasons, or only the "notable 20" with a downloadable CSV for the rest? More transparency is more credible but more work to maintain.

4. **Methodology update cadence:** Monthly universe review is the default. Quarterly is safer for stability but slower to react to new assets. What's the right cadence for a rating agency?

5. **Model allocation confidence:** Is the Gemma 4 26B-A4B for narratives + Qwen 3.5 35B-A3B for reasoning split right? We could also route everything through one model for simplicity, at the cost of efficiency.

6. **KAIROS pattern adoption priority:** Which of the 4 patterns from §2.4 is most valuable to adopt first — persistent memory, coordinator mode, AutoDream, or blocking budget? Phase 3 schedules all four but we could sequence them.

7. **MCP tool naming:** Should `get_cis_exclusions()` be more assertive — for example, `get_institutional_exclusion_list()` or `get_rejected_assets_with_reasons()`? The name affects agent discoverability.

---

## 9. WHAT THIS PRD DOES NOT COVER

Unchanged from v2.1 §9.

---

*The universe is the product. The standard is the headline. The fund is the business. The intelligence terminal is the proof. Curation is the moat.*
