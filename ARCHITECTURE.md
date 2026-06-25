# CometCloud — Architecture toward an A2A-era Intelligence OS

*Living document. The north star, not the current build. Updated 2026-06-08.*

## The kernel insight

Markets and momentum are **downstream reflections**. The upstream cause is the
**marginal decisions of a small set of super-influential entities** — large
capital, institutions, protocol founders, policy, key allocators. The memecoin
illusion (you "grasped luck with your own skill") is really: you stood downstream
of someone's decision.

So the deepest object in our ontology is **not the Asset** — it is the
**Influencer** and the **Decision**, and the **propagation** of that decision into
asset quality and price. CIS (quality) and momentum are reflections; **beta+ comes
from being closer to the cause.**

This is our ONE deep know-how — and the line between us and "we-can-do-anything"
operators who have no insight in any domain: **we do not sell breadth. We model one
upstream cause deeply (influence → quality propagation) and prove it with outcomes.**

## Strategy first principle — 大象无形 (the great form is formless)

*Weighs above all strategy code. It regressed once — diluted by build/agent churn in
2026 — and must not be diluted again. Any "strategy" that is a static mechanical
factor or a grid search violates this principle.*

**The edge has no fixed form.** Mechanical rule-based systematic (Turtle-style) and
long-window static-factor backtests are market-falsified or wash out: across long
horizons regimes turn over countless times, edges decay and reverse (non-stationarity).
A fixed factor averaged across all of that nets to nothing. autoresearch grid search is
the same falsified mechanical turtle in new clothes — it finds spurious winners that die
live. **We do not look for the edge as a frozen factor.**

**Market structure forbids beating an index by trading it.** In equities >80% of the
gain accrues *overnight* — you cannot out-trade the index intraday. Therefore:
**beta = HOLD** (passive capture — the formless way; this is the upgraded-index / FoF
core), and **alpha = niche** — specific inefficiencies the market is *currently*
price-discovering, not generic momentum on a basket.

**The real edge is formless and adaptive:** tracking liquidity + momentum + the
price-discovery of quality assets, **in the current regime**, validated **per-instance by
human + AI together** — never a factor machine. *Every time is different*, so it requires
independent analysis and validation each time. CIS / our intelligence is this **formless
price-discovery tracker (human + AI)**, not a static factor.

**Role of the backtest (corrected):** to *validate a specific, currently-hypothesized
niche edge* in its relevant regime, plus cost/capacity sanity — NOT to *discover* a
universal static factor (which non-stationarity + overnight structure guarantee will
disappoint, as the 2026-06-25 crypto-momentum-vs-ETF test proved: the same template that
worked in crypto lost money on liquid multi-asset ETFs over 11y).

## Not an app — an OS (four composable layers)

1. **Kernel — the influence-propagation ontology.**
   Objects: `Entity` (influential node), `Decision`, `Asset`, `Quality` (CIS /
   pillars), `Regime`, `Outcome`. Edges: `Entity → Decision → propagates-to →
   Asset`; `Asset → has → Quality`; `Decision → resolves-to → Outcome`.
   *Today we model Asset + Quality + Regime + Outcome. The frontier is the
   Entity / Decision / propagation layer — going upstream from reflection to cause.*

2. **Primitives — the OS verbs.**
   Composable `Actions` over the kernel, with **one uniform signature for humans
   and agents** (exposed via MCP / A2A): `Diagnose(Portfolio)`, `Screen(Asset)→Rejection`,
   `TrackInfluence(Entity)`, `Allocate(Fund)`, `Resolve(Signal)→Outcome`,
   `Subscribe(Operator)`. Reads AND writes. A primitive has preconditions + effects.

3. **Operators — humans AND agents, first-class and symmetric.**
   An LP, a trading agent, a developer, a partner company's agent — all invoke the
   same primitives through the same interface. "Built for humans and agents equally"
   is literally this: same verbs, same ontology.

4. **Fusion — operators compose primitives into their own thing.**
   We ship ONE thing (the kernel), **freely fusable**. The diagnosis is Fusion #1
   (`Portfolio` + `Screen` + `Quality`). Extensibility is native, not bolted on:
   every capability is a primitive with a clean contract, so composition is the
   default mode.

## Logistics / harness as an OS service

Today's harness — contract integrity, observability (heartbeat), deploy verify,
learning (outcome→IC), coordination (MINIMAX_SYNC) — is the **metabolism of our
current form**. In the OS, these become **services any operator can instantiate
over their own fusion**: every operator gets their own health, learning, and
coordination loops. The harness is not hardcoded to our self-image; it is a
primitive of the OS.

## Organizational-form innovation

An A2A-era organization is **not a company doing many things**. It is a deep kernel
exposed as a **protocol / OS, operated by a network of humans + agents** (internal
and external). The team already includes agents (Seth, Minimax; tomorrow, external
operators). **Value accrues to the kernel** (know-how + proven outcomes) **and to
the fusion network on top** — never to breadth of features.

## Anti-imposter discipline (the guardrail)

- We do **ONE thing**: model influence → quality propagation, prove it with 30-day
  outcomes.
- **Composability is a property of that one thing** — never a claim to "do everything."
- The moat is **know-how + proof**, not surface area. Every new capability must
  reduce to a primitive grounded in the kernel, or it does not belong.

## Path: iPod → OS

- **iPod (now):** `Diagnose(Portfolio)` — one lovable fusion, simple enough for the
  mass market, secretly Primitive + Fusion #1. It lets users *imagine* the bigger thing.
- **iPhone (north star):** the OS — any operator (human/agent) composes primitives
  over the influence kernel; decisions and capital flow over the ontology; the org
  is the network.
- **Discipline:** each step ships a simple fusion, but every primitive is built
  clean so fusions compound.

## Mapping today's pieces onto the model

| Built | Layer |
|---|---|
| CIS engine, contract normalizer, narrative, executability | Kernel (Asset/Quality) |
| `Diagnose(Portfolio)` | Fusion #1 / Primitive |
| MCP server, Agent API, A2A card | OS interface for agent-operators |
| Outcome tracker | Proof loop (`Resolve→Outcome`), feeds Learning |
| build-state, heartbeat, deploy gate, MINIMAX_SYNC | Logistics (→ become OS services) |
| exclusion standard | `Screen→Rejection` primitive |

**The frontier / next depth:** the `Entity` / `Decision` / influence-propagation
layer — modeling *who* moves things and how their marginal decisions propagate, so
the kernel reaches the cause, not just the reflection.
