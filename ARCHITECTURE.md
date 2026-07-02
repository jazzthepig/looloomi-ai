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

## Vectors & movement — the mechanics as a flow, not a still life

*(2026-07-01) The kernel above is easy to read as a static ontology — a list of nouns
(Entity, Decision, Quality, Price). It is not a list. It is a **field in motion**. The
mechanics are vectors and flows; the objects are just where we sample the current.*

- **Influence is a vector, not a label.** An influential decision is a *force*: it has a
  **direction** (which assets/regimes it pushes) and a **magnitude** (how much capital /
  authority / conviction is behind it), applied at a **point** (the entity) and radiating
  outward. Two entities with the same "influence score" but opposite direction cancel; our
  job is to read the *resultant* vector, not count influencers.
- **Propagation is a wavefront with velocity and lag.** decision → quality → price is a
  wave moving downstream. `beta+` is a **temporal vector**: standing *upstream in time*,
  closer to the source before the wavefront arrives at price. CIS/momentum are the wave
  *after* it has already passed — reflections with a lag. The edge is the lag.
- **Consensus moves along a diffusion curve; 出圈 is its velocity.** A consensus is not
  "concentrated" or "dispersed" — it is *travelling* from the informed few toward the mass.
  `cause_proximity.stage` samples **position** on that curve; `dispersion-acceleration`
  samples **velocity**; the 出圈 alarm fires on high **d(dispersion)/dt** — the wavefront
  hitting the crowd. Danger is not a state, it is a *speed*.
- **The moving quantities are flows.** Marginal capital flow (D1) and attention diffusion
  (D4) are the actual currents — signed vectors (in/out) with magnitude and **acceleration**
  (γ crowding decays as the flow saturates). Price is not a number we read; it is the
  *integral of marginal flows over the diffusion field*, and `∂(consensus)/∂t` is the
  fragility term. (This is the dynamic form of the "price = liquidity × current value ×
  future-expectation × sentiment-vector" sketch — expressed as derivatives, not a static product.)
- **The loop is circulation, not a pipeline.** Sense → Judge → Act → Learn is a *current*
  that must keep moving; the system is a metabolism. `loop_health` measures whether the
  current still flows; `provenance` is the **damping** that keeps it stable — verification
  is the friction that stops the loop from oscillating into noise.

**Match to Karpathy's loop:** his agentic loop is generate → **verify** → act, on an
*autonomy slider*, with the thesis that **verification is the bottleneck** and you "keep
the AI on a leash." Our loop is congruent — Sense/Act/Learn = perceive/act/observe; our
Judge + validation-gates + provenance = his generation-verification loop; our human-at-deploy
gate = his autonomy slider. The distinction is **position**: in his LLM-OS we are not the
cognition loop — we are a **peripheral + the verification substrate** that other agents'
loops call. Provenance is precisely "verification-ready output for someone else's loop." We
sell the friction that makes *their* leash cheap to hold. That is the substrate role, stated
in his own mechanics.

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

## Our role — judgment substrate, not the executor (positioning, 2026-06-29)

Full autonomy is **not our goal** — that is the executor's game (our partner / 友商 builds
the autonomous agent). **We are the layer that makes other agents able to judge** — the
intelligence substrate that helps *them* close *their* loop. KPI = agent-consumability and
proximity-to-cause, **not** our own autonomy score.

**The moat is what other agents can't think of and can't conveniently verify.** Anything
an agent can self-serve cheaply (price, basic momentum, FNG) is table-stakes, not a wall —
that is the commodity "AI-application" direction. Our wall is the **hard-to-compute,
hard-to-verify upstream judgment**: influence → quality propagation, holder-concentration
出圈 stage, proximity-to-cause. Hard is the point — hard is why they need us.

But hard-to-verify cuts both ways: **hard to verify also means hard for the consumer to
trust.** So the product shape is: *we take the hard-to-verify signal, verify it ourselves
by closing our own loop end-to-end, and hand over the verification (provenance + confidence
+ source + 30-day outcome) so the consumer trusts without redoing the hard work.* Closing
our own loop is therefore not a detour into being an executor — it is how we earn the right
to teach user/agent how to use us. **A signal we have not run through our own loop is one we
must not claim. Claiming it unproven is self-deception, and self-deception cannot teach.**

**Prioritization filter (every task, ours and Minimax's, passes this):**
1. Can an external agent easily fetch/compute this itself? → If yes, it's table-stakes, not moat. Minimal effort.
2. Is it hard to verify? → If yes, it's worth building — hard is why they need us.
3. Can we close our own loop on it and emit provenance + outcome? → If not, build that first; do **not** claim it externally until we can.

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
