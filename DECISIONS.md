# CometCloud AI — Product Decisions Log

Engineering reference. Decisions made by Jazz, logged here to prevent re-asking.

---

## Session: 2026-04-09

### Q1 — Landing page framing
**Decision:** Build both variants (intelligence-first AND fund-first) and A/B test with real users/clients for their review. Do not choose before testing.

**Engineering implication:**
- Two landing page components: `LandingA.jsx` (intelligence-first) and `LandingB.jsx` (fund-first)
- A/B routing: cookie or URL param (`?v=a` / `?v=b`) splits traffic
- Both variants share the same Nav, fonts, design tokens
- Simple analytics logging on CTA click (which variant converted) — write to Supabase `ab_events` table
- Decide winner after minimum 50 data points per variant

---

### Q2 — Fund page tone
**Decision:** Variable — decided by user's preference. The fund page should offer a tone toggle or detect context from user behavior.

**Engineering implication:**
- Two display modes on `/fund`: "Institutional" (conservative factsheet density, Brevan Howard style) and "Performance" (aggressive metrics, returns-forward, Citadel style)
- Toggle persists in localStorage per user
- Default mode: Institutional (safer first impression, user can switch)
- Both modes show the same data — only presentation hierarchy changes (performance metrics front vs buried)
- Mobile always shows Institutional mode (no toggle on mobile — too much friction)

---

### Q3 — API pricing
**Decision:** Deferred. Introduce paid tiers only after demonstrating real comparative advantage in 1–2 specific features.

**Engineering implication:**
- No API key gating in current build
- All `/api/v1/` endpoints remain open except internal endpoints (already gated by `INTERNAL_TOKEN`)
- When introducing pricing: the likely paid features are `get_cis_exclusions()` (unique data) and `get_cis_history()` (time series requiring Supabase)
- Free tier would keep: `get_cis_universe()`, `get_macro_pulse()`, `get_signal_feed()`
- Build the usage logging hooks now (log every external API call with timestamp + endpoint) even though pricing is deferred — this creates the data needed to make the pricing decision

---

### Q4 — Wallet connect flow
**Decision:** Wallet connect unlocks portfolio management tools. Full flow:

1. User connects wallet (Phantom or compatible Solana wallet)
2. Platform reads on-chain holdings and assesses portfolio composition
3. Provides personalized CIS-based optimization advice (which positions align with current signals, which don't)
4. If user wants to enable auto-trading: they leave a message/request via a form
5. CometCloud reviews and grants a **21-day free trial** for the auto-trading service
6. Auto-trading = CometCloud's Freqtrade/agent strategy executing on their behalf

**Engineering implication:**
- Wallet connect remains in current codebase (already built)
- Portfolio page (`/portfolio.html`) is the post-connect destination
- New component needed: `AutoTradingWaitlist.jsx` — a simple form (message + contact) that POSTs to `/api/v1/leads/auto-trading-request`
- New backend endpoint: `/api/v1/leads/auto-trading-request` — stores in Supabase `leads` table with `type: "auto_trading_trial"`
- The 21-day trial grant is a manual review step (Jazz reviews → sends approval email). No automation needed in Phase 1.
- Portfolio advice is CIS-signal-based: compare user holdings against OUTPERFORM/UNDERPERFORM signals, surface mismatches

---

### Q5 — Market data tab
**Decision:** CUT. Removing market tab reduces infrastructure costs meaningfully.

**Engineering implication — files to delete:**
```
dashboard/src/components/MarketPage.jsx      ← cut
dashboard/src/components/MarketDashboard.jsx ← cut  
dashboard/src/market.jsx                     ← cut
dashboard/market.html                        ← cut
```

**Vite config:** Remove `market: resolve(__dirname, 'market.html')` from rollupOptions.input.

**Backend impact:** The `/api/v1/market/coingecko-markets` proxy endpoint was primarily built to serve MarketDashboard. Without the market tab, this endpoint can be deprecated. The `get_prices()` function is still used by other components — don't remove the underlying price data, just the market page UI layer.

**Infra savings:** Fewer Vite entry points = smaller build. The CoinGecko market API calls from the browser side stop. Estimated API call reduction: ~200 calls/day from the market page's auto-refresh.

**Nav change:** Remove any nav links pointing to `/market.html`.

**Jazz to run from Mac Mini (FUSE limitation):**
```bash
rm dashboard/src/components/MarketPage.jsx
rm dashboard/src/components/MarketDashboard.jsx
rm dashboard/src/market.jsx
rm dashboard/market.html
```

---

### Q6 — VC funding data → RWA capital flows intelligence
**Decision:** Keep and significantly expand. Reframe from "VC Funding" to "Institutional Capital Flows" with RWA as the primary lens.

**What to cover (expanded scope):**
- RWA tokenization launches (BlackRock BUIDL, Franklin OnChain, Ondo, Superstate, etc.)
- Institutional capital entering on-chain RWA products (AUM milestones, new issuances)
- Regulatory approvals enabling RWA: SFC Hong Kong tokenization licensing, SEC no-action letters, EU MiCA RWA framework updates
- Tokenized treasury/bond product launches and volume milestones
- TradFi → DeFi institutional bridge events (bank custody announcements, prime broker integrations)
- Traditional VC rounds in crypto infrastructure (keep, but secondary to RWA)

**Engineering implication:**
- Rename `vc_funding` → `institutional_capital` in signal feed classification
- Add RWA-specific data source: fetch from RWA.xyz API (public), Dune RWA dashboards
- Backend: update signal classification in signal router to include `rwa_launch`, `rwa_milestone`, `regulatory_approval`, `institutional_bridge` as event types alongside `vc_funding`
- Frontend: rename "VC Funding" label → "Institutional Flows" in IntelligencePage and SignalFeed

---

### Q7 — GP partner name
**Decision:** Public. Correct name is **"HumbleBee Capital"** (not BumbleBee).

**Engineering implication:**
- All `BumbleBee` / `bumblebee` references replaced with `HumbleBee Capital` / `humblebee` — DONE (2026-04-09)
- Files updated: `VaultPage.jsx`, `ShareCard.jsx`, `solanaVault.js`, `leads.py`, `vault.py`, `CLAUDE.md`
- Dist files will reflect the change on next build

---

### Q8 — Mobile priority
**Decision:** Responsive from day 1. Mobile shows condensed and selective data — not all data, the right data.

**Mobile data hierarchy (condensed):**
- Intelligence page mobile: Regime badge + top 5 CIS assets (not full leaderboard) + latest Regime Brief summary
- Fund page mobile: Fund metrics strip (6 numbers) + Schedule Call CTA + strategy cards (vertical stack, no side-by-side)
- CIS leaderboard mobile: Symbol + Grade + Signal only (hide pillar breakdowns, LAS, sparklines)
- Signal Feed mobile: Show 3 signals max, "load more" below the fold
- Portfolio mobile: Holdings summary + top recommendation only

**Engineering implication:**
- Use Tailwind responsive prefixes (`md:`, `lg:`) consistently
- Mobile breakpoint: <768px = mobile layout
- `useMediaQuery` hook for programmatic conditional rendering where CSS classes are insufficient
- Never hide critical CTAs on mobile
- Font sizes: mobile minimum 13px body, 11px labels, no smaller

---

## Inclusion Standard Recalibration (2026-04-09)

**Decision:** v1.0 was too strict — alpha-killing. Recalibrated to v1.1.

**Key changes:**
- Criterion 6: 180-day minimum → 90-day standard, 45-day fast-track for strong new assets
- Criterion 7: Added remediation pathway (12+ months clean operation + audit + compensation)
- Design principle added: alpha-preserving filter, not risk-elimination filter

**Assets affected:**
- **HYPER (Hyperliquid):** Reinstated. Passes v1.1 criteria. Confidence 0.85× until 180-day mark.
- **RUNE (Thorchain):** Moved to borderline (remediation review). 3+ years clean operation. Jazz decides.

**One remaining Jazz call:** RUNE — include with "remediated" tag, or hold?

---

*Updated: 2026-04-09*
