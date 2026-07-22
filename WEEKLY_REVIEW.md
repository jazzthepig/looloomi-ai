# Weekly Strategy Review — CometCloud AI

One hour per week. Builder mode off, strategist mode on.
Ad hoc reviews called by Jazz any time.

---

## 2026-07-21 | Week ~21 | Ad hoc review (Jazz) | Lens: Business model + Epistemology

*The most decision-shaping session the project has had. Two threads ran in parallel and converged:
a **business-model thread** (what we are actually building and who pays) and an **epistemology
thread** (how we decide what is true). They met at the same conclusion from opposite ends.*

### 1. The empirical spine — the metric was the bug, not the model

Full chain in `REFUTATION_LEDGER.md` R61 → R62 → R63/R63b. Short version: the live signal book
looked non-predictive (OUTPERFORM t=−4.09). It wasn't. Asset β vs benchmark is **1.4–2.4**, so
`a_ret − b_ret` was never alpha — it was leveraged beta, and in a bear-dominated window a *good*
signal reads as inverted. PIT-safe β adjustment flips it: **OUTPERFORM +2.86 t=+5.75, STRONG
OUTPERFORM +8.06 t=+5.41**, every CIS pillar correctly signed. **CIS works.** UNDERWEIGHT
(t=−3.79) is the one genuine defect. Independently corroborated by R46's market-neutral L/S, which
removes β *by construction* — two methods, same answer.

**Meta-lesson #21 — audit the METRIC before the MODEL.** All three "our edge is broken" findings
this session were measurement defects (this, plus two look-ahead leaks: full-sample normalization in
`interpretation_c.py`, and an unverified 4h→15m merge in the V9 audit). Two leaks in one day in
independent code paths ⇒ treat as systemic. A contaminated target makes good models look broken and
bad models look good.

**Meta-lesson #22 — a factor can fail as a mean-return predictor and still be information.** Jazz's
correction: S "hurting" is normal — peak hype is peak volatility, where people lose big. True: mean
edge is flat across S, but **vol 15.89→17.17 and left tail −13.93→−18.33**. We nearly deleted a
working *risk* factor because we only tested it as a *return* factor. Generalized (R63b): the five
pillars are **three different kinds of object** — stability-premium (S, O), directional-change (A),
level-only (F, M). ⇒ **CIS v5 is an architecture question, not a reweight.**

### 2. The epistemology thread — binary standards are wrong for a non-stationary world

Jazz: classify strategies into a vector database; don't binary-judge. "If you use binary standards
no good strategy exists anywhere — reality keeps changing. Anything 100% working generally stops
working in ~3 months; market-wide capacity fills, then new strategies prevail."

This **indicted our own gauntlet.** Its `regime_robustness` gate *kills* anything that works in some
regimes and not others — which is exactly what killed vol carry ("CALM-REGIME"), the crowding book
("MECHANISM REAL, F1 regime flip"), R33 ("β on a friendly window"), V5c. Every one of those is a
**sleeve with a domain**, not a failure. Our doctrine says `library beats hero`; our validation
practice was enforcing *hero*. That contradiction is the bug.

**Resolution adopted:** binary for **validity** (look-ahead/PIT leakage, cost-infeasibility at
declared capacity — a leaky backtest is wrong, not "in a phase"); dimensional for **durability**
(regime fit, decay, crowding, correlation). Without the floor, "different lifecycle phase" explains
every bad result and nothing is falsifiable. Without the dimensional half, we discard the library.

**But rotation ≠ library.** Jazz proposed rotating allocation by style cycle. We already tested that
(**R20**, logged as "Jazz's direction"): static 0.78 = momentum-rotation 0.78, **regime-rotation
0.29** — much worse OOS. The style cycle is real in-sample but not profitably timeable (per-regime
Sharpe estimated on few episodes; regime label lags; Asness confirmed on our data). **Synthesis: hold
the library statically — that harvests regime specialization without paying the timing tax.** Regime
info → risk sizing (scale gross down), never → alpha rotation. R20's own lesson, now load-bearing.

### 3. The business-model thread — vault over FoF, and who actually pays

- **FoF is structurally late.** Underlying-manager liquidity is monthly/quarterly with 30–90d notice
  ⇒ 3–6 month round trip to rotate. If edges decay in ~3 months, a FoF is *guaranteed* to hold
  yesterday's strategy. It reproduces the "arrives late" pathology one level up and adds a fee layer.
  A vault rotates in blocks. **Fee structure is load-bearing, not incidental:** management fees pay
  you to stay deployed; performance-only makes honest flatness affordable. (Today's core-health gate,
  holding zero and *recording* the flat, is behaviour a FoF structurally cannot offer.)
- **Institutional selection is late by construction** — 5-year record, top-decile, scale, then 3–6
  months observation, then committee, then 3–6 months terms. This is Goyal–Wahal: sponsors hire after
  strong performance and those managers then underperform. **Sharpened diagnosis:** it is not
  bureaucracy-for-its-own-sake — that process is highly optimized, just for the *allocator's career
  risk*, not the client's return. Every requirement is a defensibility artifact. ⇒ the winning move is
  making the unconventional choice **defensible**, not merely correct.
- **Agents don't have the agency problem.** No committee, no career risk ⇒ an agent can allocate on
  actual expected value. **The agent side is the natural buyer of precisely the product human
  institutions structurally cannot accept.** That makes agent-first sequencing necessary, not trendy.
- **Structure:** a three-sided marketplace (strategies × GPs × agents) with the vault as settlement.
  Sequencing: agents first (cheapest to serve, only side that can accept our framing) → our own
  strategies as bootstrap inventory → GPs last (slowest, follow AUM; Nic's network is the channel).
- **Product boundary (Jazz):** CIS score is the **free** shopfront proving we built real
  infrastructure. The **paid** value is explaining pillar *changes* × price behaviour, applied in
  strategies. Caution logged: raw pillars are commodity (agents can difference them); the defensible
  asset is the **mapping** — which deltas matter, at what frequency, with what β treatment, in which
  regime. And **the paid artifact should be a conditional distribution (mean/vol/tail), not a score** —
  R63 proves the tail is where S lives, and an agent sizing a position needs the distribution. A
  competitor publishing a number cannot express that.

**⇒ `docs/MECHANISM_SPEC.md` written** (new): the A2A capital-market mechanics — forward commitment,
binding capacity declaration, mandatory lifecycle disclosure; the strategy-vector schema as the
machine-readable contract; why honesty is made the profit-maximizing move. Core thesis: **in an A2A
market the scarce resource is not capital but verifiable forward track record — so our validation
apparatus IS the product.**

### 4. Hypotheses tested against Jazz's intuitions (honest scorecard)

| Jazz's claim | Verdict |
|---|---|
| Weekly K needed to see major-trend structure; freqtrade can't express it | ✅ weekly 20/50 flips 1.3×/yr vs daily 2.2×; **28.9% engagement in R57's dead zone vs V5c's 2.7%**. Freqtrade limit is architectural (~130 weekly bars in a 2.5y backtest). But weekly is a *mode selector*, not an entry trigger (exits 2.5 months late; standalone SR 0.64 < V5c 0.89) |
| Marginal liquidity × marginal risk appetite resonate on weekly (共振) | 🟡 **liquidity half confirmed** — stablecoin-supply Δ gate: SR 0.83 / ann +35.4% / DD −56.5% vs buy-hold 0.64 / +22.3% / −75.2%. **Resonance as specified refuted** (both-positive → SR 0.07). Best state is *divergent* liq+/risk− (+5.62% fwd) ⇒ it's **phase/lead-lag**, not simultaneity. My alt/BTC risk proxy is the weak link |
| High-CIS = crowded = 庄家 distributes | 🔴 refuted — after β adjustment every pillar is correctly signed; they were high-β, not crowded |
| Peak sentiment = high vol = where people lose big | ✅ confirmed (vol +8%, left tail −32% deeper at high S) |
| Not just ΔO — ΔS behaves similarly | ✅ confirmed, and specific: ΔS +2.72 / ΔO +2.70 stability premium, ΔF/ΔM ≈ 0 |
| V9's Sharpe 5 is achievable, but wouldn't last at scale | ✅ both halves right. SR 5 is arithmetically coherent (32.4%/yr, 6.4% vol, ~10% time-in-market). **Capacity is the killer** — $30M ⇒ $6–9M per 15m clip; modeled drag already 17.25%/yr vs 32.4%/yr return. Inverts in the low single-digit millions |

### 5. Shipped

§5b two-layer paper book **live in production** (`two_layer_paper.py` + daily loop + endpoint + 7/7
tests + preflight; Supabase table & RLS policies applied) — deliberately holds **zero size** while
the core is dead and records the flat honestly, starting the forward-OOS clock R57 said we lacked.
`MECHANISM_SPEC.md`. §ALTITUDE / §PIT-LEAK-C / §CORE-BAKEOFF to Minimax.

### THE ONE STRATEGIC PRIORITY

**Unify the production alpha metric onto the β-adjusted, PIT-safe definition — then rebuild CIS as
three factor *kinds* rather than five weighted levels.** Everything else this session is downstream:
the paid agent product is the pillar-change → conditional-distribution mapping, and that mapping is
meaningless while the yardstick underneath it still measures leveraged beta as alpha. We spent weeks
believing our edges were weak because of a measurement defect. Fix the instrument first.

*(Standing caution, from §ALTITUDE: ambition raises the evidence bar, it does not lower it. A Sharpe
of 5 gets more scrutiny, not a victory lap.)*

---

## 2026-07-19 | Week ~20 | Lens: Institutional LP + Competitor (the "do we have an edge yet?" audit)

*(Review cadence lapsed May 25 → July 19 while in deep build. Resuming. This entry covers the
alpha-validation arc of the last ~2 weeks — the biggest methodological jump the project has made.)*

**What actually changed (the improvement over the prior 2 weeks).** Two weeks ago we were testing
strategy ideas one at a time and refuting them ad hoc (R18–R28: unlocks, miner-cost, conviction
sizing, vol sleeve v1 — each a one-off kill). This week we built the thing that was missing: a
**systematic institutional filter** — the `signal_gauntlet`: significance → deflated-Sharpe (multiple
testing) → PBO (overfit prob) → **factor-absorption** → **regime-robustness** → **cross-asset
replication** → **point-in-time leakage**. Two of those gates were borrowed directly from outside
rigor (the Google/academia LLM-factor study's *absorption* filter; Tom Wellington / Two Sigma's
*temporal-leakage* guard). The shift is from "test one idea" to "an industrial funnel every idea must
survive." That is the single most valuable structural change since the CIS engine itself.

**It's already earning its keep.** The gauntlet killed four plausible-looking things before any
capital: the Crowd Clock (momentum in a costume, R24), the +1.97-Sharpe composite (a beta mirage on a
friendly regime — R33, caught *before* it reached an LP deck), naive funding-crowding (R34), and the
BTC vol-carry that looked like a ★-survivor until the *same-day* ETH check killed it (R39). Each kill
is honest and logged. The graveyard (R1–R39) is now a real asset.

### Adversarial reads

- **Institutional LP (family office):** They would respect the *process* more than any Sharpe — the
  gauntlet + the graveyard say "we won't lose your money on a mirage," which is exactly what a
  sophisticated allocator wants to hear from a zero-fee, performance-only fund. **But the honest gap is
  stark: we have ZERO credited alpha.** The one signal that cleared the full gauntlet (vol carry) failed
  cross-asset replication the same day. An LP's fair verdict: "elite discipline, no demonstrated edge —
  come back when one signal clears cross-asset." Our defensible story today is *risk* (−3–5% MaxDD) and
  *rigor*, not returns.
- **Competitor (copy speed):** A well-resourced quant desk copies the gauntlet in a week — it's standard
  once articulated. Our moat is NOT the filter. It's (a) the **crypto-native orthogonal seams** the
  equity factor zoo doesn't contain (funding-crowding, vol-risk-premium, on-chain structure), and (b) the
  accumulated causal ontology + refutation ledger. Lean into those, not into more filter.
- **Trader agent:** The MCP is back up (19 tools) and signals are compliance-safe positioning language —
  but with no credited edge, an agent uses us for context/screening, not execution. And CIS data was
  silently stale (cron down) until fixed to honestly flag `stale` — integrity restored.

### Infrastructure debt check
- ✅ Fixed this week: Railway trading-loop 500; CIS **fake-freshness** (served 22h-old scores stamped
  "now" → now honest `stale`/`data_age_s`); crowd-clock null inputs; local MCP revived + hardened;
  CLAUDE.md trimmed under the 40k limit; gauntlet cross-asset blind spot closed.
- 🔴 Open (Minimax lane): cron daemon stuck (no CIS pushes); Supabase DNS/URL.
- 🟡 Small: frontend CIS badge should consume the new `stale` flag (green→amber when old).

### The one strategic priority

**We have the field's-best machine for KILLING ideas and too few ideas to feed it.** Per Wellington and
the Google paper, the scarce input is the *original orthogonal question*, not the filter — and we've run
maybe 5 causal ideas through the gauntlet for 0 credited survivors (their funnel was 280 → 9). The risk
is becoming a beautiful refutation engine that never ships an edge. **So the priority is to shift effort
from filter-building to orthogonal-candidate GENERATION** — more shots on goal in the non-momentum,
non-factor-zoo space (cross-CLASS crowding breadth on Hyperliquid; on-chain supply/holder structure;
cross-venue basis; a cross-asset-robust vol construction). We need ~10 orthogonal candidates entering the
gauntlet to expect 1 to clear it cross-asset. That one credited edge is the difference between "an
institutional-grade filter" and "a fund an LP can actually back."

*Next review: week of July 26. Suggested lens: Trader Agent (would it execute?) once a first edge clears
cross-asset, or Competitor if still in candidate-generation.*

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
