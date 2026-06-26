# METHODOLOGY CORE — v0.1 (draft, 2026-06-19)

*The condensed law beneath CIS, the Risk Meter, the index, and capacity. Written
to be benchmarked against IOSCO Principles for Financial Benchmarks + GIPS-grade
honesty. v0.1 ships the structure; load-bearing unknowns are flagged **OPEN** and
will be resolved with data + research, not hand-waved.*

---

## 0. Discipline (the gene this doc must not corrupt)

- **Descriptive first, predictive earned.** Below, the static decomposition is an
  identity (safe, not unique). The dynamic law is a *hypothesis* — it earns the word
  "law" only after out-of-sample validation (§5). Until then we say "heuristic."
- **No claim without proof.** Anything unvalidated is marked OPEN.
- **Measure honesty, not signals.** What we standardize/sell is the *measurement*
  (capacity, stage, fragility) — non-rival, appreciates with adoption — not a tradable
  signal, which crowding self-destructs (§4).

---

## 1. Static decomposition (identity — descriptive only)

Price as a product of a fair-value anchor and dimensionless deviations; natural in
log space (returns additive), the standard factor structure:

```
P = V · L · E
log P = log V + log L + log E
```

- **V** — fair-value anchor. **OPEN**: heterogeneous per class (crypto: no clean
  intrinsic value; tokenized equity: underlying spot; RWA: NAV). Define per class.
- **L** — liquidity-adjusted premium (microstructure depth term).
- **E** — expectation/positioning (sentiment folded in — see §3, it is a *vector*).

This is an accounting identity: it fits any price ex-post. It predicts nothing on its
own. It is the skeleton, not the edge.

## 2. Dynamic law (hypothesis — the edge lives here)

Price is made at the **margin**. Grounded in established microstructure
(order-flow imbalance / Kyle's λ):

```
dP/P  ≈  β · r_market  +  γ(stage) · Φ_cause  −  c_liquidity
```

- **dP/P** — forward return over horizon Δt (Δt must be specified per use, §6).
- **β · r_market** — market beta (the part everyone has; not our edge).
- **Φ_cause** — propagation of upstream decisions into V and E (the kernel).
  **OPEN**: today we measure its *shadow* (holder diffusion, flows), not the upstream
  Entity/Decision itself. Honest status: **we are still at the reflection layer,
  measuring it more finely** — not yet at the cause. Do not market as "we reach the cause."
- **γ(stage)** — sign/strength gated by propagation stage (§3). **Sign flips**: + when
  consensus is concentrated upstream (early), − when consensus has diffused out-of-circle.
- **c_liquidity** — cost/impact drag (scales with levered footprint, §6 capacity).

Net direction is dominated by the **sign of net marginal flow** (not capital stock);
magnitude is only needed for capacity, not for direction.

## 3. The state variable (the one primitive)

Crowding, sentiment, and cause-proximity are **three projections of one thing: where a
consensus sits on the propagation cascade**, and who provides the marginal flow.

```
S = stage of consensus on the diffusion curve  ∈  [small-circle/upstream … out-of-circle/mass]
```

- **Small-circle high consensus = safe / alpha** (early, upstream, before the crowd).
- **Out-of-circle high consensus = danger** (mass/retail arrived → exit liquidity →
  trampling). Examples: global retail all buying gold / one hot single stock / all-in memecoin.
- **Sentiment is a vector, not a scalar**: the *same* sentiment level means opposite
  things at the two ends. Its sign on forward return flips with stage. This is what
  upgrades the CIS **S pillar** from scalar → directional.

Marginal-flow decomposition by participant identity:
- **Smart/upstream flow** — conviction-based, stable, low vol-sensitivity.
- **Retail flow** — procyclical & fragile: buys momentum, flees on volatility.
  - **First retail-momentum leg is rideable ⟺ smart money is still net in** (handoff
    not yet done). If smart is already distributing as retail enters, there is no safe leg.
- **Fragility = retail share of marginal flow × realized volatility** → proximity to a
  "撤一波" shakeout. High fragility = high risk regardless of CIS level → feeds Risk Meter.

**OPEN #1 + #3 — partially resolved (2026-06-19):** Nansen API exposes point-in-time
historical smart-money data marketed as no-look-ahead (Historical Holdings, 4yr lookback,
~$49/mo) ⇒ the γ/stage edge is **likely backtestable** — we are NOT forced to downgrade to
a heuristic. Two checks remain before we call it a law: (a) verify smart-money *membership
at date t* uses only pre-t information (not today's PnL applied backward — the subtle
circularity an endpoint alone doesn't rule out); (b) build a transparent self-computed
smart-set from raw on-chain (Dune/Flipside, as-of-date realized PnL) so the published
standard does not rest on a vendor black box.

**ALIGN 2026-06-25 — Nansen DEFERRED; do not wire it now.** Per the source policy
(`DATA_CAPTURE_SPEC.md`): CoinGecko Pro is primary, Dune is the one extra source (D3
holders), Nansen (D2 wallet-level smart/retail) waits until CoinGecko is exhausted. Until
then the γ/stage edge runs on D3 (holder dispersion, Dune) + D4 (attention diffusion,
CoinGecko) and is published as a **declared heuristic**, not a proven law. The old "DC0
Nansen PIT check" task is DROPPED.

## 4. Crowding / capacity decay (why alpha and capacity die together)

Alpha decays as capital crowds the same edge:

```
γ_effective = γ₀ · (1 − crowding)
```

General law (same in VC sectors, mutual funds, crypto): return ≈ f(opportunity growth −
capital-inflow growth), modulated by moat / staying-power. Capital inflow >> demand
growth ⇒ alpha → 0 for all without a structural edge; "expert"/consultant FOMO
*accelerates* the crowding (credentialed trend-following); convergence ⇒ nobody earns
alpha ⇒ correlated unwind / mutual trampling in crises.

**Capacity is dynamic, not static:**

```
Capacity = f( liquidity↓ , crowding↑ , leverage , stress-exit )   — shrinks on every axis
Deployable capital NOW = level where marginal alpha (after crowding decay)
                          still > impact cost + fees
```

- **Capacity is post-leverage** (market absorbs gross levered footprint, not equity) and
  **stress-exitable** (bounded by what can be *liquidated in a vol spike*, not accumulated).
- **Retail-provided depth = false capacity** — it evaporates in the shakeout.
- **OPEN #7:** capacity algorithm (stress scenario, exit window, slippage function, ADV cap)
  not yet specified.

**Reflexivity guardrail:** standardizing a *signal* + wide adoption ⇒ we crowd our own
edge to death. Therefore standardize the *measurement* (honest capacity, stage, fragility,
GIPS-grade performance), which is non-rival.

## 5. Falsification protocol (stub — to specify, OPEN #8)

No term is "an edge" until it passes: out-of-sample holdout + walk-forward + purged/
embargoed CV (López de Prado) + multiple-testing correction + **net-of-cost** vs explicit
benchmark (BTC-hold / equal-weight). To define: target horizon, IC threshold, windows.
Result so far (`scripts/backtest_strategies.py`): daily cross-sectional CIS rank-IC ≈ +0.03
(t≈1.0, not significant); momentum L/S market-neutral +26%/Sharpe 1.2 in-sample;
CIS-as-filter *hurt* momentum. ⇒ engine = momentum/trend; CIS = weak factor, not a gate.

## 6. Levels & horizons (to pin, OPEN #6)

Per-asset → portfolio/index → sleeve/FoF: define how the per-asset law aggregates.
Δt per variable: marginal flow (hours–days), stage (weeks–months), capacity (quarters).

## 7. Cross-asset transfer (OPEN #4, load-bearing)

On-chain holder/flow decomposition is a crypto-native edge. For tokenized equities / RWA,
holders are largely off-chain ⇒ the out-of-circle detector likely **degrades or fails**.
The convergence-index thesis depends on cross-asset — so this gap must be closed (or the
index scoped to where the data exists) before claiming cross-asset coverage.

---

## What completes CIS / Risk Meter (the payoff)

- **S pillar → vector** (stage-aware, sign-flipping at 出圈).
- **+ Stage/crowding component** (data-driven cause-proximity axis).
- **+ Fragility component** (retail-share × vol) → Risk Meter measures *quality of
  support*, not just asset quality.
- **+ Honest capacity** as a first-class per-asset output (post-leverage, stress-, stage-adjusted).

These four are exactly the IOSCO/GIPS-grade differentiators: we publish stage + fragility +
honest dynamic capacity, on-chain-verifiable — the *measurement honesty*, not the signal.

*Companion: `DATA_CAPTURE_SPEC.md` (what to collect, from where, who owns it).*
