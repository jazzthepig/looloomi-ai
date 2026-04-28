# Weekly Strategy Review — CometCloud AI

One hour per week. Builder mode off, strategist mode on.
Ad hoc reviews called by Jazz any time.

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
