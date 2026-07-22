# Vector Schema Spec — Asset (CIS) v2 & Strategy v1

*Shared contract. Drafted 2026-07-21 (Seth). Companion to `docs/MECHANISM_SPEC.md` §3.*

Two vector spaces, one set of invariants. This document exists so Seth and Minimax implement
**against a spec instead of against each other** — on 2026-07-21 both independently built a strategy
embedder in one afternoon (30-dim in `src/data/vector/`, 21-dim in `src/research/`). Prose
assignments caused that. This is the contract.

---

## 0. Invariants — apply to BOTH spaces, non-negotiable

**I1 — Unmeasured is NaN, never 0.** Imputing 0 for an unmeasured dimension asserts the object is
*average* on an axis nobody tested. With sparse coverage (our sleeves carry 11–18 of 21 dims) that
fabricates most of the map. Similarity must skip NaN dims and **refuse to answer** below 4 shared
dimensions rather than return a confident number from noise.

**I2 — Point-in-time or it doesn't ship.** Every dimension at time *t* uses only data ≤ *t*. Rolling
windows, expanding stats, no full-sample percentiles or z-scores. Two look-ahead leaks were found on
2026-07-21 (`interpretation_c.py` full-sample normalization; the V9 4h→15m merge). Run `pit_guard`
on every dimension, not just LLM features.

**I3 — Beta is separated, not embedded.** Any performance dimension is **β-adjusted** (R62: asset β
is 1.4–2.4; raw `a_ret − b_ret` is leveraged beta and inverted the sign of a working signal). β
itself is a *coordinate*, never silently folded into a return number.

**I4 — Validity is binary; durability is dimensional.** Look-ahead leakage and cost-infeasibility at
declared capacity **disqualify**, regardless of how good the coordinates look. Regime fit, decay,
crowding, correlation are **coordinates only** — never a kill. Without the floor, "different
lifecycle phase" explains every bad result and nothing is falsifiable; without the dimensional half,
we delete the library chasing an all-weather hero that does not exist.

**I5 — Distributions, not point estimates.** Where an outcome is encoded, encode **mean, dispersion
and left tail**. R63: high sentiment leaves the mean unchanged (+2.77 vs +2.70) while widening vol
(15.89→17.17) and deepening the p10 tail (−13.93→−18.33). A mean-only schema is blind to the exact
thing that loses money.

**I6 — Version and never silently redefine.** Bump `SCHEMA_VERSION` on any dim change; keep old
fields alongside new ones. Redefining a live field makes historical vectors incomparable.

---

## 1. Asset vector (CIS) — v1 → v2

### What v1 got wrong

v1 (18 dims, live) is **entirely levels and instantaneous state**:

```
F/100 M/100 O/100 S/100 A/100 CIS/100 | log_mcap chg_24h chg_7d chg_30d
vol_mcap funding_rate oi_mcap_ratio ath_proximity | las confidence class_enc regime_alignment
```

2026-07-21 proved this is structurally insufficient (R62, R63, R63b):

1. **No beta** — the dominant contaminant of every performance comparison.
2. **No pillar deltas.** `chg_24h/7d/30d` are *price* changes, not *pillar* changes — a different
   object. ΔS and ΔO carry a **stability premium of +2.72 / +2.70** that levels cannot express.
3. **No risk moments.** S is a *risk* factor, not a return factor; v1 has nowhere to say so.
4. **Treats five pillars as one kind of thing.** They are three kinds (§1.2).

### 1.1 v2 additions (14 new dims → 32)

| block | dims | why |
|---|---|---|
| **Beta** | `beta_pit`, `beta_stability` | I3. β vs the asset's benchmark, PIT-estimated, plus how stable that β is (unstable β ⇒ adjusted numbers are themselves noisy) |
| **Pillar deltas** | `d_F`, `d_M`, `d_O`, `d_S`, `d_A` | R63b. Information levels cannot carry |
| **Stability** | `stability_O`, `stability_S` | Distance from the Q3 sweet spot where edge peaks (t=+8.19). Large moves in either direction = we are sampling *after* the market repriced |
| **Risk moments** | `edge_vol`, `edge_p10` | I5. Where S actually lives |
| **Freshness** | `obs_age_hours`, `sample_frequency` | S/O reprice fast; a stale S is a *different object* from a fresh one and must not be compared as equal |
| **Capacity** | `adv_usd_log` | Tradeable size, so allocation never exceeds liquidity |

### 1.2 The three factor kinds — encode the kind, not just the value

The single most important structural finding of 2026-07-21. CIS is a weighted sum of level scores; it
**cannot express** that its pillars behave in three different ways:

| kind | pillars | evidence | how it must be used |
|---|---|---|---|
| **Level** | F, M | level spreads +3.28 / +2.74; Δ ≈ 0 | return factor, level-scored |
| **Directional change** | A | Δ spread +1.18 (rising ⇒ better edge); strongest level too (+4.48) | return factor, **change**-scored |
| **Fast-state / risk** | S, O | stability premium +2.72 / +2.70; S: mean-flat, vol +8%, tail −32% | **risk gate + change**-scored, needs high-frequency sampling |

⇒ **CIS v5 is an architecture change, not a reweight.** Concretely: a return score from {F, M levels;
A change} and a **separate risk score** from {S level → sizing; S/O stability → confidence}, rather
than one weighted sum. This corrects the pending R46 action item — "away from S" is wrong as stated;
S is a risk gate, not dead weight. `pillar_A` is the strongest untested candidate and has never been
run at strategy level.

---

## 2. Strategy vector — v1

Six blocks (`MECHANISM_SPEC` §3). Reference implementations exist; **converge on the
`src/data/vector/` stack** (Minimax, 30-dim, has schema + embedder + store + backfill) and port in
from `src/research/strategy_vector.py`: NaN-honesty (I1), the binary validity floor (I4),
`coverage_gaps()` and `redundancy()`. Then delete the duplicate.

| block | dims | source |
|---|---|---|
| Regime domain | calm, stormy, risk_on, risk_off, trend, chop | `regime_robustness` — **repurposed from kill-gate to coordinates** |
| Factor exposure | β market / momentum / carry / quality, residual α t | `factor_absorption` |
| Mechanics | holding period, turnover, time-in-market, directionality | backtest + live |
| Capacity | declared USD capacity, ADV fraction | declaration (P2) + fill attribution |
| Lifecycle | age, performance slope, crowding | live record (P3) |
| Cost sensitivity | slope of performance vs bps | cost sweep — **the slope, not one number** |

### 2.1 The two outputs that make it operational

Without these it is a filing cabinet, not an instrument:

- **`coverage_gaps()`** — which regimes the library does *not* cover. Must **exclude disqualified
  sleeves** (a cost-infeasible sleeve cannot cover a regime it cannot trade). First run, 8 sleeves:
  **calm n=0, stormy n=0, chop best=0.16.** Everything we own is directional. That is the build list.
- **`redundancy()`** — near-duplicate pairs: breadth we think we have but don't. R20 measured
  effective breadth at **6.74 of 17 strategies**; correlated sleeves are one sleeve under several names.

---

## 3. Why two spaces, and how they meet

**Asset space** answers *what to hold*. **Strategy space** answers *how to hold it*. They meet at
allocation: a sleeve's regime coordinates say when it is live; the asset vectors say what it trades
inside that regime; capacity on both sides caps the size.

Under `MECHANISM_SPEC`, the strategy vector is also the **agent-facing contract** — an allocating
agent needs regime domain, capacity ceiling, decay state and factor exposure to decide anything. And
per §1.2 the sellable asset-side artifact is a **conditional distribution** (mean / vol / p10) given
pillar state and recent deltas — not a score. The free CIS score is the shopfront; the paid product
is this mapping. A competitor publishing a number cannot express it.

---

## 4. Build order

1. `beta_pit` into the asset pipeline — I3 blocks every performance dimension in both spaces
   (module + Supabase columns done; live writer is Minimax's, see §BETA-METRIC)
2. Pillar deltas + stability dims — cheap, already computable from `signal_outcomes`
3. Converge the strategy stacks; port I1/I4 + `coverage_gaps`/`redundancy`; delete the duplicate
4. Risk moments (`edge_vol`, `edge_p10`) — needs the β-adjusted history backfilled first
5. High-frequency S/O sampling — the ΔS/ΔO stability premium says we currently arrive after the
   market. Route: related-instrument price action (the AI-ETF analogy)
6. CIS v5 architecture per §1.2 — **last**, because it depends on 1–5 being measured

Do not start 6 before 1. Rebuilding CIS on a yardstick that still counts leveraged beta as alpha
would bake today's bug into the new architecture.
