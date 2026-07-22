# CometCloud — Mechanism Spec for the A2A Capital Market

*Living document. Companion to `ARCHITECTURE.md`. Drafted 2026-07-21 (Seth), for Jazz to edit.*

`ARCHITECTURE.md` carries the philosophy — influence propagation, the kernel, the iPod→OS path.
This document carries the **mechanics**: how capital actually gets allocated between agents, what
claims can be made, how they're verified, and why telling the truth is the profit-maximizing move.
It is deliberately implementable — every primitive maps to something we have or can build.

**Scope discipline (Jazz, 2026-07-21):** this specifies the **capital side only** — vault, strategy
providers, allocating agents. The agent-workflow verticals (finance/insurance ops, sales-agent IP,
client acquisition) and the commerce/flexible-supply-chain track are **deliberately out of scope**.
Standardizing those now would be skipping steps. They get their own spec when demand is proven.

---

## 1. The problem this solves

Human capital allocation runs on a social layer: pedigree, relationships, a GP's five-year record,
an investment committee. None of that transfers to a counterparty with no social layer. An agent
deciding whether to move its own wallet cannot check your references.

So in an A2A capital market, **the scarce resource is not capital — it is verifiable forward
track record.** Capital is abundant and perfectly mobile. What's scarce is a claim about future
performance that a machine can check and price.

This inverts what a fund normally optimizes. The asset is not the edge; the asset is the
**apparatus that makes claims about the edge checkable.** Our refutation ledger, PIT guards,
gauntlet, and honest flat-recording are not internal hygiene — they are the product surface.

**Design consequence:** a system that reports `book_state: core_dead` and holds zero size, rather
than manufacturing exposure to look busy, is *more* valuable to an allocating agent than one that
always shows activity. Unflattering truthfulness is what makes the flattering claims priceable.

---

## 2. The three primitives

Everything else is plumbing. These three make the market self-policing, which is the only way it
scales to many providers without manual diligence on each.

### P1 — Forward commitment

**Rule:** a claim must be registered *before* the outcome window opens, and resolves automatically
against pre-declared criteria. Retroactive claims have no standing and earn no allocation.

- Registered: strategy id, positioning stance, horizon, benchmark, capacity claimed, cost assumption.
- Resolution: automatic at horizon end. No discretionary restatement, no quiet withdrawal.
- Unresolved or withdrawn commitments are recorded as such — silence is not free.

*Status: largely built.* `prediction_outcomes`, `experiment_runs`, `signal_track_record`, and the
predict→resolve→record loop are exactly a commitment scheme. They were built as research tooling
and simply aren't framed as market infrastructure yet.

### P2 — Binding capacity declaration

**Rule:** a provider declares the capacity at which its claim holds. Declaring capacity means
**accepting allocation up to it.** Realized slippage is measured against the declaration.

This is the primitive that makes V9-class results honest rather than misleading. A sleeve that is
genuinely excellent at $2M and inverts at $30M is a *good sleeve with a stated ceiling* — not a
fraud, and not a flagship. The mechanism forces the ceiling to be stated up front, priced in, and
enforced by allocation.

Overclaiming is self-punishing: you receive flow you cannot fill, realized slippage is measured
against your own number, your capacity score degrades, future allocation shrinks.

*Status: not built.* Requires a capacity field in the strategy record plus slippage attribution
at fill time.

### P3 — Mandatory lifecycle disclosure

**Rule:** every strategy publishes its lifecycle position — age since discovery, rolling-performance
slope, crowding proxy, and measured decay — as a first-class field, continuously.

Edges decay and capacity saturates; a market that pretends otherwise misprices everything. Making
decay a *disclosed field* rather than a hidden defect turns the ~3-month half-life from an
embarrassment into a market norm. Providers compete on honest lifecycle reporting, and allocating
agents can discount accordingly instead of guessing.

*Status: not built, and we don't yet know our own number.* See §5.

---

## 3. The strategy vector — the machine-readable contract

One schema serves three consumers: internal research, provider onboarding, and the agent-facing
API. Build it once. Extends `src/data/vector/embedder.py` (today an 18-dim *asset* embedding) to
strategies as first-class objects.

| Block | Fields | Source |
|---|---|---|
| **Regime domain** | Sharpe conditional on calm/stormy vol, risk-on/off, trend/chop | `regime_robustness` — repurposed from kill-gate to coordinates |
| **Factor exposure** | market / momentum / carry / quality β + residual α, with t-stats | `factor_absorption` |
| **Mechanics** | holding period, turnover, time-in-market, directionality | backtest + live |
| **Capacity** | ADV fraction, per-clip notional ceiling, declared capacity (P2) | declaration + fill attribution |
| **Lifecycle** | age, rolling-performance slope, crowding proxy, decay estimate (P3) | live track record |
| **Cost sensitivity** | performance across 0/2/5/10bps — the *slope*, not one number | cost sweep |

**The critical design choice: binary for validity, dimensional for durability.**

- **Binary, permanently disqualifying:** look-ahead/PIT leakage; cost-infeasibility at declared
  capacity. A leaky backtest is not "in a different lifecycle phase" — it is wrong. Capacity is a
  fact, not a season.
- **Dimensional, never binary:** regime fit, decay, crowding, correlation. These are coordinates.
  A strategy that works in one regime is not a failure; it is a located sleeve.

Without that floor, "it's just in a different phase" explains every bad result and the system loses
the ability to tell itself bad news. Without the dimensional half, we throw away the entire library
in pursuit of a nonexistent all-weather hero.

**Binary-permanent kill register (this architecture, this universe/window):**

| Architecture variant | Status | Evidence | Lesson |
|---|---|---|---|
| **Cross-sectional L/S, unconditional** | 🔴 BINARY-PERMANENT KILL | R64 (unconditional pillar_A L/S, REFUTED), R65 (cross-pillar sweep 15 cells, UNIFIED REFUTATION), R67 (R46 audit on upgraded data, REFUTED — 0/120 cells pass ship-gate, ★ SURVIVOR was snapshot artifact), R68b (directional long-only, REFUTED — 0/32 cells positive fwd β-adj) | Aggregate lesson #14.2: **the cross-sectional dispersion ranking itself is the structural problem in F3/F4 BTC-downtrend regimes**, not just the short leg. Long-only is +0.537 better than L/S on the load-bearing metric (R68b vs R64) but **both are still negative on forward β-adj**. The "high pillar_A" assets are exactly the smaller-cap DeFi/L2 that fall MORE than L1 in BTC-downtrend regimes; the ranking systematically buys the wrong side of dispersion. 6-deep refutation lineage (R15/R17/R38/R45/R47/R48/R64/R65/R67/R68b) closes the unconditional family. |
| **Cross-sectional L/S, regime-gated with cross-sectional median cis_score (R66 proxy)** | 🔴 BINARY-PERMANENT KILL | R66 (12 cells, REFUTED — best +1.783 was F3/F4 regime-window artifact; full walk-forward 2/4 folds positive) | Aggregate lesson #14.3: a regime proxy derived from the same cross-sectional dispersion that is the structural problem **cannot rescue** the strategy. The proxy's quality is dominated by the very dispersion signal being ranked. |

**What DOES survive the binary kill (architectural alternatives for CIS-driven alpha):**

| Architecture variant | Status | Evidence | Notes |
|---|---|---|---|
| **Per-asset CIS overlay on per-asset swing core (V9)** | 🟡 MARGINAL POSITIVE | R68 (144 cells, 22 improve V9 baseline; best pillar_A default str=0.3 cad=1d, fwd β-adj SR +5.562 vs V9 +5.412, Δ = +0.150 = +2.8%) | Per-asset conviction multiplier on V9's already-realized P&L; NO cross-sectional dispersion ranking. Overlay preserves V9 quality (0/144 cells degrade) and adds modest incremental α. Production-candidate. |
| **Cross-sectional L/S, regime-gated with macro_regime tag (R47 proxy)** | 🟢 PARTIAL SURVIVE | R47 (18 cells = 2 pillars × 3 skip variants × 3 cadences; **14/18 cells clear +0.5 strategy-credit threshold**, 8/18 cells have 4/4 walk-forward folds positive AND positive fwd β-adj; best cell `R47_pillar_A_skip_all_bear_cad5` @ fwd β-adj SR **+1.183**, 4/4 folds positive, 5/6 sub-periods positive) | Aggregate lesson #14.4: **regime proxy quality is load-bearing**. The macro_regime tag from the CIS JSON is a direct, hand-curated macro label (EASING / RISK_ON / RISK_OFF / TIGHTENING / STAGFLATION) that breaks the cross-sectional feedback loop. Where the cross-sectional median cis_score proxy failed (R66), the macro_regime tag succeeds — opening a sub-family of regime-gated L/S that the architectural kill does NOT cover. Best cell is ship-gate-ready for production-paper candidacy pending OOS isolation (R69 follow-up). |

The cross-sectional L/S family kill is **conditional, not universal**. It applies to: (a) unconditional cross-sectional L/S, AND (b) regime-gated L/S where the regime proxy is itself derived from the same cross-sectional dispersion being ranked. The kill does NOT apply to regime-gated L/S where the regime proxy is an **external macro label** (macro_regime tag) that breaks the cross-sectional feedback loop. Future CIS-driven alpha work in the unconditional and cross-sectionally-derived-proxy paths must avoid the cross-sectional dispersion ranking entirely; the macro_regime-tag path is open for further R-number exploration (R69 proposed).

---

## 4. Why honesty is the dominant strategy

The mechanism must make truthfulness profitable, not virtuous. Under P1–P3:

| Behaviour | Consequence |
|---|---|
| Overclaim capacity | Receive unfillable flow → realized slippage measured vs. your declaration → capacity score falls → allocation shrinks |
| Hide decay | Forward commitments resolve against you publicly → track record degrades on the record |
| Make no commitments | No verifiable record → no allocation. Silence is not a safe harbour |
| Correctly sit flat in a dead regime | **Rewarded** — a declined trade that avoids a loss scores as a correct forward call |
| Churn to look active | Costs are charged against the record; activity without expectancy degrades the score |

**Scoring must be on expectancy × capacity, not hit rate.** Otherwise providers optimize for many
small safe claims. This is the same discipline as `docs/TRADER_TOM_DOCTRINE.md` — expectancy, not
win-rate — applied at the market layer rather than the trade layer.

The flat-reward rule in row four is the mechanism's signature. Every conventional structure punishes
sitting flat: management fees pay you to stay deployed, and an allocator cannot defend a manager who
holds cash. Performance-only fees plus a vault that can hold zero instantly make honest flatness
*affordable*, and P1 makes it *scoreable*. That combination is not available to a FoF at all.

---

## 5. What exists, what doesn't

Honest inventory — no credit for intent.

| Component | Status |
|---|---|
| Forward-commitment loop (P1) | ✅ Built as research tooling (`prediction_outcomes`, `experiment_runs`) — needs market framing |
| Validity floor (PIT, absorption, cost sweep) | ✅ Built (`pit_guard`, `factor_absorption`, `signal_gauntlet`) |
| Honest flat-recording | ✅ Built today (`two_layer_paper.py` core-health gate) |
| Asset vector store | ✅ Built (`src/data/vector/embedder.py`, 18-dim) |
| Vault settlement surface | 🟡 Partial (`/api/v1/vault/funds`, `deposit-intent`, `partner-vaults`) |
| Agent surface | 🟡 Partial (`/api/v1/agent/tasks`, MCP server, API keys) |
| **Strategy vector (§3)** | ❌ Not built — the near-term build |
| **Binding capacity (P2)** | ❌ Not built |
| **Lifecycle/decay (P3)** | ❌ Not built — *and we have never measured our own decay half-life* |

**The measurement we owe ourselves first.** We have dated ledger entries back to R1 and live NAV on
four paper books. We can compute our *actual* decay half-life instead of assuming three months. That
number sets the operating cadence of the whole firm: how fast the pipeline must produce, how long a
validation stays trustworthy, when to force re-audit. If the half-life really is ~3 months, then a
validation cycle taking three weeks consumes a quarter of the edge's life — which changes how we
work more than any single strategy would.

---

## 6. Open questions — deliberately unresolved

1. **Unit of account.** Do agents hold vault shares, or per-strategy allocations? Shares are simpler
   and let us rotate underneath; per-strategy is more transparent and more agent-legible. Unresolved.
2. **Provider onboarding standard.** External GPs mean inheriting their validation problem at scale.
   Our apparatus is the moat here — we can characterize a provider in an afternoon versus a 6-month
   observation pool — but the onboarding contract isn't written.
3. **Counterparty reality.** Most "agents" today are human-directed, with a human approving anything
   that moves real money. The mechanism should work **with humans in the loop from day one** rather
   than assuming full autonomy, or we build for a counterparty that doesn't exist yet.
4. **Regulatory shape.** Agents allocating via stablecoins into third-party strategies from a HK base.
   Belongs in sequencing, not bolted on afterward.

---

## 7. Compliance

All provider-facing and agent-facing output uses **positioning language only** — `STRONG OUTPERFORM`
/ `OUTPERFORM` / `NEUTRAL` / `UNDERPERFORM` / `UNDERWEIGHT`. Never `BUY`/`SELL`/`ACCUMULATE`/`AVOID`.
Forward commitments (P1) are positioning claims resolved against a benchmark, **not** investment
advice or a recommendation to any person. CometCloud does not hold an investment advisory (投顾)
license. See `.claude/skills/compliance-language/`.

---

*The mechanism is the product. The strategies are inventory.*
