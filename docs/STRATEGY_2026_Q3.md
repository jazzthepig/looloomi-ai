# CometCloud Strategy 2026-Q3 — behavioral edge, two-layer book, kernel-bound

*Synthesis doc. Built on the foundation of `ARCHITECTURE.md` + `docs/TRADER_TOM_DOCTRINE.md`
+ `STRATEGY_VALIDATION.md` + the offline research of July 2026. Binding instruction, not a
to-do list.*

---

## The thesis (one line)

We harvest **non-decaying behavioral edges** (recurring human crowd behavior — fear,
greed, capitulation, forced selling, FOMO) deployed in a **two-layer book** (durable
fundamental core never sold on short-term volatility + tactical overlay whose gross
scales with confirmed regime), and we win by being **EARLY/upstream of the cause**, not
by predicting the next price level.

---

## Operating principles (binding)

1. **Behavioral > statistical.** Fear/greed recur forever; indicator fits decay. Every edge
   we ship must trace to a behavior, not a backtest. Sole exception: the smoothed regime
   *detector* uses structural signals (variance, funding, OI) — those reflect *real*
   market stress, not crowd mood.
2. **Asymmetry > win-rate.** Win big when right, small when wrong. A 70% book with 2:1
   loses to a 35% book with 5:1. The asymmetry law: **if you can't win big when beta is
   positive, you can't win bigger when the tape is thin**. Capture uptrends aggressively.
3. **Cause > setup.** Two agents can see the same chart; one is closer to the cause.
   Beta+ comes from cause-proximity, not pattern execution. Cause is upstream; price is
   downstream.
4. **Breadth > hero.** IR = IC × √breadth. Many small correct bets beat one big correct
   bet. Library beats hero every time. *This is why we ship many sleeves, not one.*
5. **Add to winners, never losers.** Averaging into hope is the negative-skew amateur
   trap; averaging into confirmation reinforces correct behavior.
6. **Assume wrong until proven.** Position as if wrong; only scale when the cause
   confirms direction. Structural, not discipline-of-mind.
7. **Sell only when the cause breaks** — never on short-term volatility. (Two-layer
   separation below.)
8. **Expectancy, not win-rate.** E = Σ p · payoff, right-tail dominated. Hit-rate
   chasing is the loser-curve game.

---

## The book — two-layer per asset

```
┌─────────────────────────────────────────────────────────────────┐
│  DURABLE CORE (always-on when cause is live)                    │
│  ─ Per-asset behavioral invariant:                              │
│    BTC: macro-cycle EMA + on-chain accumulation                 │
│    ETH: TVL flow + validator-economics health                   │
│    SOL: ecosystem-funding trajectory                            │
│  ─ Sized by cause proximity (tight cause → tight size)          │
│  ─ Sold ONLY when cause structurally breaks                     │
│    (token mechanics / regulatory / exploit / monetary)          │
│  ─ NEVER sold on a single drawdown                              │
└─────────────────────────────────────────────────────────────────┘
                            ↓  scaled by ↓
┌─────────────────────────────────────────────────────────────────┐
│  TACTICAL OVERLAY (gross ∈ [0.3×, 1.5×] core, regime-gated)      │
│  ─ Smoothed engine-side regime detector                         │
│    (variance + funding + OI — real market stress, not crowd)    │
│  ─ Defend in risk-OFF: small, hedged, cut fast                  │
│  ─ Press in risk-ON + confirmed long-term trend:                 │
│    add to *confirmed* winners, never hope-losers                │
│  ─ Strict gate: regime filter > calibrated overlay              │
│    (R53 Pareto cell: long_thresh=-0.20, penalty=2.0)            │
└─────────────────────────────────────────────────────────────────┘
                            ↓  per-asset ↓
┌─────────────────────────────────────────────────────────────────┐
│  PER-ASSET SLEEVES (asymmetric, dictated by cause per asset)    │
│  ─ BTC: Architecture D 60% + Architecture H 40%                 │
│  ─ ETH: overlay-only (BTC-derived regime)                       │
│  ─ SOL: overlay-only (BTC-derived regime)                       │
│  ─ Each sleeve has its own cause, not a shared one              │
└─────────────────────────────────────────────────────────────────┘
```

The overlay's regime filter is the **discipline mechanism**; the core's cause is
the **duration mechanism**. Two jobs, two layers, two failure modes that cancel.

---

## Kernel integration — Diagnose(Portfolio) is Fusion #1

The behavioral-edge doctrine + the two-layer book architecture is the **brain** of
the kernel. The Diagnose(Portfolio) front is the **face**.

```
input: portfolio (positions + risk + cash)
       │
       ▼
┌──────────────────────────────────────────────────┐
│  Diagnose(Portfolio)  — primitive fused          │
│  ─ regime context per holding                     │
│  ─ cause-proximity score per holding              │
│  ─ suggested repositioning (with sizing math)     │
│  ─ posture signal (defend / press / stand-down)   │
└──────────────────────────────────────────────────┘
       │
       ▼
output: {regime, cause, suggested_action, sizer}
```

Mass-market because it's a single API call a family office can make.
Deep because the underlying detection is the same architecture that builds the book.
Primitive fused (per `ARCHITECTURE.md`): cause-proximity is the **primitive**, the
positioning is the **fusion**.

**Anti-imposter**: ONE upstream thing, deeply proven, freely fusable. Not breadth-as-
a-claim. The same kernel shows up in:
- internal paper trading book
- agent API (autonomous AI agents acting on LP portfolios)
- broker-dealer dashboard (family office wealth-management)
- Citadel-of-Influence telemetry (institutional flow tracking)

If the kernel proves out in one surface, it propagates cleanly to the others.
That's the leverage. That's why we don't sell breadth.

---

## Current state (post-July 2026 offline research)

### Shipped (commit-touched, in `docs/`)
- `ARCHITECTURE.md` — kernel insight (influence-propagation, fusion primitive).
- `docs/TRADER_TOM_DOCTRINE.md` — behavioral-edge foundation.
- `STRATEGY_VALIDATION.md` — 10-gate checklist for live deployment.

### Validated offline (working knowledge, not in git)
- Smoothed regime detector — engine-side beats macro-side; literal H1-recovery is
  over-determined (R51).
- Pareto-frontier calibration — single-gate cannot clear both H1+H2; (-0.20, 2.0) is
  Pareto-optimal (R53).
- 15m execution validation — strict-gate +0.20 wins; 2×ATR(20) trailing stop
  uniformly HARMFUL on 15m bars (R54).
- Two-layer book architecture — Architecture D (0.5/0.5 split) and Architecture H
  (regime-multiple ×3) both clear H1+H2 simultaneously (R55).
- Cross-asset replication — BTC uses D+H; ETH/SOL use overlay-only because alt-coin
  slow-trend core is too noisy for layering to add value (R55-ext).
- OOS forward validation — architecture discipline HOLDS (overlay-only defended in
  bear-regime OOS; D's DD-bounding is structural not IS-fit) (R57).

### STRUCTURAL GAP (the agenda's binding constraint)
- 🚨 **V5c durable core (EMA54 > EMA126) HAS BEEN IN A DEAD ZONE SINCE 2025-11.**
  Last 270 days: 7/262 long (2.7%). Architecture validated but deployment gated.
  Lesson #15 round 3: **CORE SELECTION BINDING.** When the core is structurally
  broken, the layered book sits idle indefinitely.

---

## Agenda — three next moves, in order

### Move 1: R57+ — core replacement research (BINDING)

Pick one durable-core family and test on the recent dead-zone window:

| Option | Family | Hypothesis | Effort |
|---|---|---|---|
| **A** | Faster trend (EMA20/50) | Faster trend captures regime shifts earlier | Small (re-runs V5c) |
| **B** | **Funding-burst** (sustained > +0.05%/8h for 3d+) | Non-trend signal bypasses slow-trend dead zone | Medium |
| **C** | OI-confirmed momentum | Institutional-flow signature on price breakout | Medium |
| **D** | Per-asset regime-conditioned trend | Addresses cross-asset finding holistically | Large |

**Recommendation: start with (B) — funding-burst core.** Non-trend family is structurally
different from the dead slow-trend family. If slow-trends are dead in the current regime,
attacking them with faster slow-trends is category error. Build a core that *lives* in
the current regime.

Success criterion: core fires ≥30% of recent 60d window (vs V5c 0%) AND its Sharpe
in-sample at 5bps survives 3-check gauntlet (gross t > 1.96, cost-t > 1.96, OOS t > 1.96).

### Move 2: Two-layer book live paper deployment (gated on Move 1)

Once a live core exists:
- BTC sleeve: 60% Architecture D + 40% Architecture H (per R55).
- ETH/SOL sleeves: 100% V5c × C@+0.20 overlay-only (per R55-ext-cross-asset).
- Cost: 5 bps. Frequency: daily. Holding horizon: 3-7 days.
- Fail-safe: regime-detector OFF = stand down (no core = no positions).

### Move 3: Diagnose(Portfolio) front-end build (unbounded by Moves 1-2)

Turn the kernel into the user-facing API call. Single endpoint, mass-market front,
deep kernel behind. This is the product, not just the internal architecture. Fusable
to: agent API, broker-dealer dashboard, institutional flow telemetry, paper-trade
posture signals. The breadth comes from the kernel's composability, not from us
claiming to do everything.

---

## Reading order (one pass)

1. `ARCHITECTURE.md` — the kernel (north star).
2. `docs/TRADER_TOM_DOCTRINE.md` — behavioral-edge foundation.
3. `STRATEGY_VALIDATION.md` — 10-gate checklist before live.
4. This doc — the synthesis + agenda.

For the live architecture standup, see `MINIMAX_SYNC.md` (gitignored, local
coordination). For user-facing framing, see `dashboard/strategy.html`.

---

*Last update 2026-07-21. Updated when: (a) any R in the ledger flips, (b) any agenda
move ships or refutes, (c) Jazz changes a binding principle.*
