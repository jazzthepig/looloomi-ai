# Weekly Strategy Review — CometCloud AI

One hour per week. Builder mode off, strategist mode on.
Ad hoc reviews called by Jazz any time.

---

## 2026-05-25 | Week 12 | Lens: LP (family office) + Honest product audit

**Context:** Supabase migration fully fixed and applied via MCP (all 11 tables, idempotent). signal_journal live with 0 rows — track record clock started today. PerformanceDashboard.jsx deployed. Freqtrade v3 dry run live (PID=99388, Reversal mode, 20 pairs, PENDLE+UNI as candidates). HKUST co-founder candidate in discussion. T1 now 58 assets (was 25 in April).

### Core audit finding (this week's starting point)

The product audit done today surfaces an uncomfortable truth: **the intelligence engine is real but the product is not yet promotable in the way the PRD intended.** Specifically:

- signal_journal has 0 rows. The buy-side dashboard shows nothing. Sharpe = null.
- The methodology page — which PRD §4.3 calls *"the Phase 1 centerpiece"* — does not exist as a web page. It's a .md file.
- The "curation is the headline" positioning (10,000+ filtered to 71 investable) appears nowhere on the live site.
- Asset deep dive pages (/cis/{symbol}) do not exist.
- MacroBrief LLM pipeline is still NULL.
- The self-serve API key UI exists (Week 10) but no developer has used it.

What IS real and promotable: the CIS scoring engine (71 assets, T1/T2, 5 pillars), the MCP server (7 tools live at /mcp/sse), the signal feed, protocol intelligence, and the inclusion standard (documented in INCLUSION_STANDARD.md and accessible via MCP). The infrastructure is sound. The narrative surface is thin.

The honest answer to "what are we promoting?": right now, the intelligence terminal to technical audiences (traders, developers, agents). The fund to Nic's LP network is premature until there's a methodology page and at least 2 weeks of signal track record.

### Adversarial reads

**LP (family office, introduced by Nic):**
Opens strategy.html. Sees the fund page. Clicks "Explore Platform." Lands on the intelligence terminal. The leaderboard shows B-grade assets with no explanation of why those 71 and not others. There is no methodology link. There is no track record. The "Signal Performance" tab shows nothing (0 signals). She closes the tab. This is the current user journey and it does not convert.

What she needs to see: (1) a published standard she can verify — "we only include assets that pass 7 criteria, here they are, here's the exclusion list" — and (2) some evidence the scoring produces actionable signals over time. Two weeks of signal_journal data would be enough to show the pattern. Zero rows is not.

**HKUST professor (incoming technical co-founder):**
Will evaluate the AI stack directly. He built production GenAI inside WeBank. He'll call the MCP server, read the CIS methodology, ask what's powering the narratives. MacroBrief being NULL is a visible gap — the LLM pipeline is broken, and the fallback template reads like a fallback. The research paper angle (Simons IC feedback loop as a publishable framework) is the strongest hook. That requires formalizing the IC loop: pillar fitness → dynamic weight adjustment → closed-loop score correction. The math is already in the engine; it needs to be written up.

**Government grant evaluator (InnoHK / HKSAR ITC):**
Academic co-founder is the unlock. The grant framing — "AI-driven systematic asset allocation with multi-agent financial intelligence in a regulated Hong Kong entity" — fits multiple categories. The application requires a corporate entity, a research agenda, and an academic partner. Entity + HKUST affiliation = eligible. Timeline: applications run on 6-month cycles. If the entity is formed in June, the first application window is Q4 2026.

### Infrastructure debt — updated

| Fix | Effort | Impact | Owner | Status |
|-----|--------|--------|-------|--------|
| Methodology web page (/methodology) | 1d | Critical — LP funnel | Seth | ❌ |
| "Curation stat" chip on leaderboard | 2h | Critical — narrative | Seth | ❌ |
| MacroBrief LLM pipeline recovery | 1d | High — visible gap | Minimax | 🔴 |
| First Freqtrade trade confirmed | — | P0 — moat activation | Minimax | 🟡 waiting |
| Signal track record (14 day minimum) | — | P0 — promotable | Auto | ⏳ started today |
| Asset deep dive (/cis/{symbol}) | 2d | P1 — Mei persona | Seth | ❌ |
| Seed investor deck | 1d | P0 — angel round | Jazz + Seth | ❌ |
| HK entity formation | Legal | Critical — grants + fund | Jazz + partner | ❌ |
| Research paper draft (Simons IC) | 2w | P1 — HKUST hook | Jazz + professor | ❌ |
| Partnership structure (HKUST) | — | P0 — before any ext. call | Jazz | 🟡 in discussion |

### This week's task split

**Seth — build (3 things, in order):**

1. `/methodology` page (1 day). Static HTML page, same design system as strategy.html. Sections: 7-criterion inclusion standard (pull from INCLUSION_STANDARD.md), top 20 exclusions (pull from EXCLUSION_LIST.md), CIS 5-pillar framework summary, data sources, compliance positioning. Direct-link anchors on each section. No dynamic data needed — fully static, deploys with next push.

2. Curation stat on leaderboard (2 hours). One chip above the CIS table: *"Showing {n} of 10,000+ assets · Inclusion standard →"* linked to /methodology. One line of JSX in CISLeaderboard.jsx.

3. `/cis/{symbol}` asset deep dive pages (2 days). Route pattern already exists conceptually. Per-asset view: pillar breakdown radar, 30-day score trend (from cis_scores Supabase history), current grade + signal + regime sensitivity. No narrative generation needed — just data. MacroBrief fallback template can serve as the text block until LLM is live.

**Minimax — Mac Mini (2 things):**

1. MacroBrief LLM pipeline — LM Studio (Gemma4-26b) crash recovery. This has been NULL for 6+ weeks. Either fix the crash loop or document the failure mode so Seth can build a proper fallback UI. The template fallback exists but it reads like a fallback.

2. Confirm first Freqtrade trade entry or explain why no entry after 7 days with PENDLE CIS=73 and UNI CIS=64 as reversal candidates. If the 4h candle conditions haven't triggered, report what conditions ARE required.

**Jazz — company layer (2 things):**

1. Finalize partnership structure with HKUST professor before any external conversation. Equity split, roles, which entity (Looloomi for the tech/research arm makes more sense than CometCloud), IP assignment. Nothing else can happen until this is clear.

2. Begin seed investor deck. Positioning: CometCloud as the institutional intelligence layer for the agent economy — not a quant fund, not a data vendor, but the rating agency that sits between raw crypto markets and institutional capital allocation, now with AI agent distribution. One slide that doesn't exist yet: "The track record clock started [date]. Here's what the first 2 weeks of signals look like." That slide needs signal_journal data.

### One strategic priority

**Make the product legible in 60 seconds.**

Right now a cold visitor lands on the intelligence terminal and sees a leaderboard. They don't know why those assets. They don't know what CIS is. They don't know there's a methodology they can verify. They don't know there's a fund behind it.

The methodology page + the curation stat chip solves this. Combined build time: ~1 day. Return: the product goes from "a crypto leaderboard" to "a rating agency with a public standard." That's the difference between Nic forwarding a link and a family office scheduling a call.

Everything else this week — Freqtrade, signal_journal, HKUST — depends on external actors or time. The methodology page depends only on Seth.

### Key insight

Three months of building has produced a real scoring engine with real data. What's missing is not features — it's the narrative surface that explains why the product exists. A family office doesn't evaluate a leaderboard. They evaluate a methodology. The methodology exists in a markdown file no one outside this team has ever read. That's the gap.

---

*Next review: week of June 1. Suggested lens: First external investor (seed round framing) + Competitor (Kaito's composite score velocity — how fast can they ship a CIS equivalent?)*

---

## 2026-05-12 | Week 10 addendum — shipped since May 10

**Commits since review:** 4 commits — `22738ea`, `902f9bd`, `c72ef9d`, `81601aa` (+ 2 staged, pending push)

**Status update on debt table:**

| Item | Status → Now |
|------|-------------|
| Self-serve API key UI | ❌ → ✅ **ApiKeysPage.jsx complete** — form + instant key delivery + copy to clipboard |
| Score-change webhooks | ❌ → ✅ **webhooks.py complete** — subscribe/unsubscribe/list/test/events + delivery via BackgroundTasks |
| 3 critical webhook bugs | N/A → ✅ **Fixed**: (1) `event="grade_change"` → correct `GRADE_UPGRADE`/`GRADE_DOWNGRADE` split; (2) `"fire_count + 1"` string PATCH → RPC atomic increment; (3) `signal` missing from Supabase SELECT |
| keys.py `request_count` | N/A → ✅ **Fixed**: same SQL expression bug — now uses `increment_api_key_usage()` RPC |
| Supabase migration idempotency | N/A → ✅ `DROP POLICY IF EXISTS` before every `CREATE POLICY` — safe to re-run |
| Analytics tracking | N/A → ✅ `analytics_events` table live, `track()` wired in frontend |
| Privacy policy page | ❌ → ✅ `/privacy.html` deployed |
| og:image share card | N/A → ✅ `GET /api/v1/share/og-image` — 1200×630 PNG, meta tags in all HTML pages |
| MacroBrief auto-fallback | 🔴 → 🟡 Template generator added — auto-generates from macro-pulse data when LLM offline |
| Historical scores REST | ❌ → ✅ `GET /api/v1/cis/history/{symbol}` live |
| Gate mock Solana endpoints | ❌ → ✅ `SOLANA_READY` env flag gates read endpoints; writes gated by `INTERNAL_TOKEN` |
| PostHog analytics | ❌ → ✅ Self-hosted via Supabase `analytics_events` (no third-party) |
| agent.json | Outdated → ✅ Rewritten: correct URL, 84 assets, 23 tools, webhooks documented |
| glama.json | Outdated → ✅ Rewritten: all 23 tools, Gemma4-26b, correct install commands |
| llms.txt | 22 tools → ✅ Updated: 23 tools |

**Still pending Minimax:**
- Freqtrade dry run (CISEnhancedStrategy) — moat activation event
- MacroBrief LLM pipeline — LM Studio (Gemma4-26b) crash recovery
- Wallet connect E2E re-run after Python 3.14 fix

**Git push blocked by virtiofs lock:** Jazz must run `rm -f ~/Projects/looloomi-ai/.git/HEAD.lock && git push origin main` from Mac terminal to deploy latest 2 commits.

**Supabase migration re-run required:** Paste `scripts/supabase_migration_week10.sql` in SQL Editor to add `increment_api_key_usage()` RPC (fixes request_count tracking on api_keys table).

---

## 2026-05-10 | Week 10 | Lens: Developer (first-time friction) + Competitor (copy speed)

**Context:** Jazz sick week 9, returned with a new institutional partner. 7 commits since last review — stability fixes, CoinGecko Pro v4.3, rate limiting hardened, RaaS section live on strategy page. Supabase schema extended (P0.2 ✅). Freqtrade dry run and MacroBrief still pending Minimax.

### Adversarial reads

**Developer (first-time MCP setup friction):**

Discovery is clean — llms.txt, glama.json, agent.json live, SSE endpoint mounted, one-line install. First tool call (`cometcloud_get_cis_universe`) returns 84 assets with grades, no auth. That part works.

The wall hits at step 3. MacroBrief returns null when Mac Mini's LM Studio isn't running — no signal in the API response distinguishing "service degraded" from "you're doing it wrong." T1 vs T2 data tier has no degradation notice surfaced to developers. And the deeper problem: there is no self-serve path to a Pro key. The RaaS section says "contact jazz@cometcloud.ai." For a developer, that's a closed tab. The rate limiting infrastructure is live, key lookup is wired — but there's no UI, no form, no endpoint a developer can reach without emailing. The funnel has no bottom.

**Competitor (copy speed — Kaito / Nansen / Glassnode):**

Nansen owns indexed wallet history — different market, no B2D threat. Glassnode is on-chain granularity for researchers — not signal synthesis for agents.

Kaito is the real risk. AI-native, developer-friendly, shipping at speed. They have YAP scores and CT distribution. A CIS-equivalent composite score with an MCP endpoint is 2–3 weeks for them. If they ship it, "AI crypto intelligence via MCP" becomes their narrative by volume even with a weaker methodology.

What they can't copy fast: Jazz's §4A exclusion curation (the *decision* about what not to include is harder than the scoring), the regime-aware weight system, and live Freqtrade performance data. A composite score with no live trading record is just another index. A composite score with a verified P&L is a different product.

**Implication:** The Freqtrade dry run is not a feature. It's the moat activation event. Every week it doesn't start is a week Kaito can close the gap.

### Infrastructure debt check

| Item | Status |
|------|--------|
| Rate limiting + API keys (infra) | ✅ Live — no self-serve UI yet |
| Dashboard self-throttle (429 fix) | ✅ Fixed |
| EconomicIndicators always renders | ✅ Static scaffold live |
| CoinGecko Pro utilization | ✅ Sparkline in M pillar, supply/tickers endpoints |
| Supabase schema (time-series) | ✅ P0.2 done May 10 |
| PostHog analytics | ❌ Not done |
| Gate mock Solana endpoints | ❌ Not done |
| Privacy policy page | ❌ Blocks Anthropic registry listing |
| Historical scores REST endpoint | ❌ View exists in Supabase, no API |
| Score-change webhooks | ❌ Not started |
| Freqtrade dry run | 🔴 Blocked on Minimax |
| MacroBrief LLM pipeline | 🔴 Still null — LM Studio unstable |
| Self-serve API key UI | 🔴 New critical gap — funnel has no bottom |

New debt: Mac Mini is single point of failure for T1 data and MacroBrief. No failover, no alerting, no LM Studio crash recovery.

### One strategic priority

**Ship a self-serve API key page — 10 minutes from landing to first authenticated call.**

New institutional partner + Nic's network means warm intros are arriving. When they hit "Get API Access" on strategy.html, they reach a mailto. Fine for an LP, fatal for a technical partner. A single-page form (email → tier → key delivered instantly) converts interest into a measurable funnel event, makes RaaS real, and delivers the first revenue data point. The backend already exists — `/api/v1/keys/create`, Supabase wired, rate tiers enforced. This is a frontend + email-delivery problem. One day of work.

### Key insight

Jazz came back from illness with a new partner. Distribution is becoming real before the product is closeable. The risk isn't competitors copying CometCloud — it's the first institutional contact who asks for API access and gets a mailto link, and reads that as immaturity. Self-serve is how the product looks as serious as the team building it.

---

*Next review: week of May 17. Suggested lens: Institutional LP (would a family office commit $1M to this?) + Operations (what breaks when Jazz is sick for a week and Minimax is offline?).*

---

## 2026-04-27 | Week 8 | Lens: Trader Agent + VC

**Context:** MCP live, llms.txt live, glama.json deployed, A2A Phase 2.3 complete.
Product Hunt launches Monday Apr 28. Zero real users in Supabase yet.

### Adversarial reads

**Trader agent perspective:**
- Would use CometCloud for pre-trade screening and regime context. The three-call workflow
  (macro_pulse → cis_universe → regime_allocation) is genuinely clean. No comparable
  free alternative assembles these signals with compliance-safe language built in.
- Would NOT use for: event-driven trading (no webhooks — polling only), historical
  backtesting (no `/cis/history` endpoint despite 3,877 rows in Supabase), Solana execution
  (7 endpoints silently returning mock data), position sizing (no confidence intervals).
- Current market condition: zero actionable signals in Tightening regime. Technically
  correct, but means the platform has near-zero actionability at launch timing.

**VC perspective:**
- Moat is unclear. CIS methodology is documented and reproducible from public data.
  The moat candidates — exclusion list curation, Jazz's institutional network, Qwen3
  pipeline quality, brand trust — none are established yet.
- Two businesses in parallel (B2D developer tool + B2I institutional capital) without
  a declared wedge. The logic (B2D invocations → B2I LP credibility) is sound but
  needs to be explicit.
- No revenue model. Free MCP + free API means "1,000 daily invocations" is traffic,
  not traction. Path from usage → dollar is undocumented.
- Single point of failure: Mac Mini hosts all T1 intelligence. No VC wants one machine
  between them and the core product claim.

### Infrastructure debt surfaced

| Fix | Effort | Impact | Status |
|-----|--------|--------|--------|
| PostHog MCP analytics | 3h | 9/10 | → P0 this week |
| Gate mock Solana endpoints | 1h | 7/10 | → P0 this week |
| Privacy policy page | 2h | 8/10 | → P0 (blocks Anthropic registry) |
| Historical scores API | 4h | 9/10 | → P1 this week |
| API key + rate limiting | 8h | 8/10 | → P1 (first revenue model) |
| Score-change webhooks | 12h | 9/10 | → P2 (moat moment) |

### One strategic priority this week

**Prove the B2D → B2I flywheel with one real data point.**
One institutional contact discovering CometCloud through a developer channel (MCP registry,
Product Hunt, GitHub) — not through Nic — would validate the entire distribution thesis.
Everything else (registry submissions, content, Discord) is infrastructure for that moment.

### Key insight

The weekly review exists because builder mode and strategist mode don't coexist.
Proximity blindness is the default state of any founding team. The adversarial lens
isn't pessimism — it's the fastest path to finding what actually needs to be fixed
before a real user finds it for you.

---

*Next review: week of May 4. Suggested lens: Developer (first-time MCP setup friction)
+ Competitor (what Nansen / Kaito / Glassnode could copy and how fast).*

---

## 2026-05-19 | Week 11 | Lens: Institutional Co-founder

**Context:** Railway back up after market.py crash. Mac Mini scheduler live again — T1 scores
flowing. Simons feedback loop fully closed (IC → pillar weights, end-to-end). Freqtrade
dry run starting. Most importantly: Jazz has identified a co-founder candidate — former
Generative & Voice AI lead at WeBank, now HKUST professor. No formal structure yet.
Everything is still shapeable.

### What changed this week that matters

The HKUST partnership is the most significant development since the company started.
Not because of what it adds to the codebase — it adds nothing yet. Because of what it
changes about the company's identity and fundable surface area:

- **Category shift:** Jazz + quant fund → founding team with deep AI research credibility
  inside regulated finance + on-chain infrastructure. That's a different story.
- **Capital access:** HK government actively deploys into academic-industry AI/Web3
  partnerships. HKUST has mandate and existing relationships. Angel networks in APAC
  treat university affiliation as first-order trust signal.
- **Regulatory narrative:** WeBank is a regulated digital bank. Someone who built
  production GenAI inside that environment already understands the compliance
  constraints CometCloud is building around. This closes the "who validates the AI?"
  question for institutional LPs.
- **Looloomi vs CometCloud split:** His affiliation likely fits Looloomi (AI research,
  technology arm) more than the fund vehicle. This actually strengthens the two-entity
  structure rather than complicating it.

### Adversarial reads

**HKUST professor perspective (incoming):**
- Will evaluate whether the AI is real or dressed up. The CIS methodology, the Simons
  feedback loop, the regime-aware scoring — these are genuinely defensible. The
  narrative needs to match the depth.
- Will ask: what's the research angle? There's a publishable paper in the Simons IC
  framework (pillar fitness → dynamic weight adjustment in multi-factor scoring).
  That paper, authored jointly, is a legitimizing asset.
- Will ask: who are the LPs? Right now: nobody. The honest answer is we're pre-LP
  and using the dry run period to build the performance track record.

**Angel investor perspective:**
- HK angels in the Web3/AI space want: technical credibility ✓, regulatory clarity
  (SFC Type 9 roadmap needed), proof of performance (Freqtrade dry run → live), and
  a team that won't dissolve in 6 months.
- The zero management fee model is a strong narrative hook but requires AUM to cover
  ops costs. Be ready to explain the bridge.

**Government grant perspective:**
- InnoHK, HKSAR Innovation & Technology Commission, HKUST research grants — all
  active. Academic co-founder is the unlock. Research framing (AI-driven systematic
  asset allocation, multi-agent financial intelligence) fits multiple grant categories.
- Timeline: grant cycles are 6-12 months. Start the applications before you have
  everything perfect, not after.

### Infrastructure debt — updated priority

| Fix | Effort | Impact | Status |
|-----|--------|--------|--------|
| HK corporate entity setup | Legal | Critical | Jazz + partner |
| Freqtrade dry run live | Minimax | P0 | Starting now |
| Seed investor deck | 1 day | P0 | Jazz + Seth |
| Trading Agent P&L dashboard | 4h | P1 | After first trade |
| Research paper draft (Simons IC) | 2 weeks | P1 | Looloomi/HKUST |
| Privacy policy page | 2h | P1 | Blocks registries |
| API key + rate limiting | 8h | P2 | First revenue model |
| Score-change webhooks | 12h | P2 | Moat moment |

### One strategic priority this week

**Structure the partnership before any external conversation happens.**
Equity, roles, entity (Looloomi vs CometCloud), IP ownership. This conversation
with the HKUST partner is the most important one of 2026. Everything downstream —
grants, angels, LPs — depends on having a clean, agreed structure in place first.
The codebase is ready enough. The company structure is not yet.

---

*Next review: week of May 26. Suggested lens: LP (what a family office needs to see
before committing capital) + Government (grant application framing).*
