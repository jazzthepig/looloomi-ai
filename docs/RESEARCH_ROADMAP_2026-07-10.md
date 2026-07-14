# Research Roadmap — Re-prioritization (2026-07-10)

**Date:** 2026-07-10
**Trigger:** Seth's H-series + DSR + H2a findings this session
**Status:** ACTIONABLE — propose phased research plan

---

## 1. What we KNOW (validated this session)

### Tier 1 — STRONG POSITIVE (ship-ready)
1. **H3.2 conviction-weighted sizing** — +$1.79-$2.25/trade per-trade PnL across 4 runs
   - Caveat: portfolio DD analysis shows it's a **linear lever** (DD/PnL ≈ 1.0), not alpha source
   - Mechanism is real (low-conviction days have lower-quality trades per H3 finding)
   - Cap=1.75 as new default (tunable via `LSV1_H32_SIZE_CAP`)

2. **DSR-certified swing lineage** — V8_Regime (0.999), V7 (0.998), V9_DirAware (0.994),
   V10_FundingAware (0.994), V10_FundingAggressive (0.981) all survive multiple-testing
   correction IN-SAMPLE
   - Caveat: walk-forward OOS still needed (DSR audit was IS only)
   - Sharpe 6.3-9.5 IS, CAGR 32-54%, DD 2-3%, win 66-70% (n≥500)

3. **Causal positioning sleeve** — Sharpe +1.21 IS, +1.02 OOS (chronological), +0.002 corr
   with swing book
   - Survives 10bps costs (+1.0 Sharpe)
   - **Decisive:** corr +0.002 = orthogonal sleeve the diversification math demanded
   - 24 perps, 668 days (2024-01 → 2025-10)

### Tier 2 — STRUCTURAL FINDING (actionable)
4. **H2a benchmark-relative IC** — CRITICAL: **GENUINE REVERSAL** in 3/5 regimes at 7d
   - Stagflation IC_abs=-0.235 → IC_rel=-0.326 (smoking gun — reversal DEEPENS)
   - Risk-On IC_abs=-0.166 → IC_rel=-0.101 (persists at 7d)
   - Risk-Off IC_abs=-0.093 → IC_rel=-0.104 (persists, n=5578 most reliable)
   - Easing: flat at 7d, genuine reversal at 30d
   - Tightening: both positive (only regime CIS-as-ranking works)
   - **Action: per-regime × per-horizon direction table is MANDATORY**

### Tier 3 — INFRASTRUCTURE SHIPPED (waiting on data)
5. **Cause persistence** — schema + persistence + backtest skeleton live
   - Blocked on ≥180 days cause_snapshots_daily (data live only ~3 days)
   - Forced-seller short + squeeze-long + long-liq short plays

### Tier 4 — NEGATIVE RESULTS (don't re-test, lessons learned)
6. **H3.1 gate-multiplier** — knife-edge floor band, trade count ±90%
7. **H2 magnitudes** — OOS 96% Risk-Off, n=1, structurally underpowered
8. **Edge gate continuous (per-regime IC)** — IC below AQR noise floor (~±0.24 at n=70)
9. **A2 falsified edge-map direction** — edge-map DIRECTION hypothesis overfit; pruned

---

## 2. What we DON'T KNOW (open questions)

### Tier A — CRITICAL (blocks production gate design)
1. **Per-regime direction gate A/B (H2b)** — does the H2a direction table actually
   improve PnL when wired into the LS v1 gate?
   - Need: A/B new gate (per-regime direction + REGIME_CIS_FLOOR) vs baseline
   - 2 dirs × 2 windows × 2 variants = 8 runs

2. **Empirical-grid edge gate A/B in LS v1** — production drop-in path (distinct
   from failed continuous one). Reads shrunk alpha per (tier × band) + conviction
   sizing. NEVER tested in LS v1 yet.
   - Need: wire src/research/strategies/edge_gate.py::gate() + size_multiplier()
   - A/B vs REGIME_CIS_FLOOR baseline

3. **Combined gate test** — H2b direction + empirical-grid + H3.2 sizing all wired
   together. Is the combination additive or does one dominate?
   - Need: best-of-each-layer baseline

### Tier B — HIGH-VALUE (production validation)
4. **SwingOverlay walk-forward OOS** — DSR audit was IS only. Need OOS confirmation
   for the 5 certified survivors. Critical for LP conversations.
   - Need: walk-forward (e.g., 4-quarter chunks, holdout last quarter)
   - 5 strategies × 4 quarters = 20 backtests

5. **Causal sleeve expansion** — Jazz requested widening 24 → 60-80 perps
   - Earlier test showed it HURTS (thin perps = noise); the 24 = 40 established is the sweet spot
   - Re-test with proper liquidity gate (CIRC_MCAP > $50M, ADV > $5M)

### Tier C — MEDIUM-VALUE (specific tests)
6. **Forward-supply unlock event study** — historical (not 180d wait) cause backtest
   - For each major unlock event (e.g., ARB/OP/APT), measure 30d post-unlock return
   - Builds the historical evidence base without waiting for live data accumulation
   - 5-10 events × 30d = small sample but INFORMATIVE

7. **H2a re-run with per-asset benchmark** — current benchmark = BTC for all crypto.
   ETH-relative for L2, SOL-relative for SOL ecosystem, etc. may be more precise.
   - Need: per-asset-class benchmark mapping

### Tier D — DEPRIORITIZED (skip)
- Continuous edge gate refinements — already failed, mechanism correct but underpowered
- Per-regime floor magnitude tuning — H2 magnitudes failed, don't re-run
- H2.1 phase 1 (smoothed regime labels) — blocked on Minimax-A; not actionable for Seth

---

## 3. Re-prioritized Research Plan (phased)

### Phase A — APPLY H2a FINDING (1-2 days, BLOCKING)
**Goal:** populate the per-regime × per-horizon direction table from H2a, A/B it in LS v1.

| step | what | output | effort |
|---|---|---|---|
| A1 | Document per-regime direction table (7d + 30d) from H2a | section in `docs/H2_REGIME_GATE_DESIGN_2026-07-06.md` | 1h |
| A2 | Wire `per_regime_direction` into LSv1Config | `src/research/nautilus/ls_v1/strategy.py` | 2h |
| A3 | A/B sweep driver (H2b) — `h2b_regime_direction_ab.py` | 8 runs (2 dirs × 2 windows × 2 variants) | 2h |
| A4 | Run sweep + write report | `reports/H2B_REGIME_DIRECTION_2026-07-10.md` | 2h |

**Success criterion:** H2b direction-aware gate beats REGIME_CIS_FLOOR baseline in
both windows, both dirs (Δ PnL +$100 IS, Δ PnL +$10 OOS minimum).

### Phase B — TEST EMPIRICAL-GRID EDGE GATE (2-3 days)
**Goal:** wire `src/research/strategies/edge_gate.py::gate() + size_multiplier()` into
LS v1, A/B vs baseline. This is the **production drop-in path**, distinct from the
failed continuous edge gate.

| step | what | output | effort |
|---|---|---|---|
| B1 | Export shrunk edge-map grid from `/api/v1/signals/edge-map` | `reports/edge_gate_grid.json` | 30min |
| B2 | Compute (tier, band) snapshots for IS+OOS windows from CIS history + BTC daily | `reports/bands/<dir>/<date>.json` | 2h |
| B3 | Wire `gate()` + `size_multiplier()` into LS v1 (`use_empirical_gate` config) | `strategy.py` | 3h |
| B4 | A/B sweep driver (`empirical_gate_ab.py`) | 8 runs | 2h |
| B5 | Run sweep + write report | `reports/EMPIRICAL_GATE_AB_2026-07-12.md` | 2h |

**Success criterion:** empirical-grid gate beats baseline in Δ $/pos AND Δ Sharpe.

### Phase C — COMBINED GATE (the integration test, 1-2 days)
**Goal:** test the BEST of each layer combined: H2b direction + empirical-grid + H3.2 sizing.

| step | what | output | effort |
|---|---|---|---|
| C1 | Wire combined gate into LS v1 (3 flags: `use_h32_direction`, `use_empirical_gate`, `use_h32_sizing`) | `strategy.py` | 3h |
| C2 | A/B sweep: 4 variants × 2 dirs × 2 windows = 16 runs | sweep output | 2h |
| C3 | Attribution analysis — which layer contributed what? | `reports/COMBINED_GATE_2026-07-13.md` | 2h |

**Success criterion:** combined gate ≥ max(individual layers) — i.e., additive.
If marginal gain < individual layers, identify the dominant layer and skip the rest.

### Phase D — VALIDATE THE MONEY LANES (parallel, 2-3 days)
**Goal:** turn DSR + causal sleeve findings into investor-grade claims.

| step | what | output | effort |
|---|---|---|---|
| D1 | SwingOverlay walk-forward OOS (4 quarters × 5 strategies) | `reports/SWING_WALK_FORWARD_OOS_2026-07-13.md` | 4h |
| D2 | Causal sleeve + DSR swing combined portfolio | `reports/COMBINED_PORTFOLIO_2026-07-13.md` | 3h |
| D3 | Forward-supply unlock event study (5-10 events) | `reports/UNLOCK_EVENT_STUDY_2026-07-13.md` | 4h |

**Success criterion:** walk-forward OOS Sharpe > 2.0 for at least 2 of 5 swing
strategies; combined Sharpe (swing + causal) > max(individual) × √(1-corr²).

### Phase E — DEFERRED (waiting on data or external)
- Cause-driven backtest (B2) — wait for 180d cause data accumulation
- H2a re-run with per-asset benchmark — need OHLCV expansion
- Phase 1 ship — blocked on Minimax-A

---

## 4. Decision matrix — what's in scope for Seth vs others

| Item | Owner | Why |
|---|---|---|
| Phase A (H2b) | Seth | LS v1 territory, gate design |
| Phase B (empirical-grid) | Seth | LS v1 territory, gate design |
| Phase C (combined) | Seth | LS v1 territory, integration test |
| Phase D1 (swing walk-forward) | Minimax-C | freqtrade SwingOverlay territory |
| Phase D2 (combined portfolio) | Seth | LS v1 + causal = Seth's lanes |
| Phase D3 (unlock event study) | Seth | CIS history territory |
| Phase E (cause backtest 180d) | both | Seth built infra, Jazz runs migration |
| Phase E (per-asset benchmark) | Seth | H2a extension, needs OHLCV work |
| Phase E (Phase 1 ship) | Minimax-A | MacroSnapshot fix in `cis_v4_engine.py` |

---

## 5. Stop / continue criteria

### STOP testing these (4 negatives in H-series + 1 prior):
- ❌ Continuous edge gate refinements (already 2 negatives)
- ❌ Per-regime floor magnitude tuning (H2 magnitudes failed)
- ❌ Gate-multiplier prototypes (H3.1 knife-edge failure)
- ❌ Edge-map direction hypothesis (A2 falsified)

### CONTINUE testing these (potential positive lanes):
- ✅ Empirical-grid gate (production drop-in, untested)
- ✅ Per-regime direction (H2a confirms needed)
- ✅ H3.2 sizing (validated as linear lever; tunable)
- ✅ Combined gate integration (additivity test)

### HIGH-PRIORITY (this session + next):
- 🔴 **Phase A: H2b direction A/B** — applies the H2a finding, blocking production decision
- 🔴 **Phase D1: SwingOverlay walk-forward OOS** — turn IS finding into investor-grade claim
- 🟡 **Phase B: empirical-grid A/B** — production drop-in, distinct from failed continuous
- 🟡 **Phase D3: forward-supply unlock event study** — historical evidence without 180d wait
- 🟢 **Phase C: combined gate** — only valuable if A and B individually show promise
- 🟢 **Phase D2: combined portfolio** — only valuable if D1 passes

---

## 6. Honest assessment — what's likely to work

Based on the data so far:

| Lane | Likelihood of positive | Why |
|---|---|---|
| H2b (per-regime direction) | **HIGH** | H2a shows reversal is real + large samples (n=5578 Risk-Off). Implementation is straightforward (map regime → direction, invert the gate). |
| Empirical-grid gate | **MEDIUM** | Shrunk alpha per (tier × band) is data-grounded. But direction handling is needed too (H2a finding). |
| Combined gate | **MEDIUM** | Depends on individual layers; could be additive or one could dominate. |
| SwingOverlay walk-forward OOS | **HIGH** | DSR IS-confirmed, swing lineage hasn #[…] reduced (Sharpe 6-9 IS may not hold OOS, but even Sharpe 2-3 is investor-grade). |
| Causal sleeve expansion | **LOW** | Already tested: thin perps = noise. 24-40 is the right universe. |
| Forward-supply unlock event study | **MEDIUM** | Need real unlock events; small sample but informative. |
| Per-asset benchmark H2a | **MEDIUM** | Could improve precision but unlikely to change the qualitative result. |

---

## 7. Recommended EXECUTION order for next session

1. **Phase A1-A3: H2b direction A/B** (highest priority — applies H2a finding directly)
2. **Phase D1: SwingOverlay walk-forward OOS** (parallel, with Minimax-C handoff)
3. **Phase B: empirical-grid gate A/B** (after Phase A — direction + edge gate stack)
4. **Phase C: combined gate** (only if A + B both positive)
5. **Phase D3: unlock event study** (background, lower priority)

Time budget: ~3-5 days for Phase A + D1 + B in serial; can be done in 1-2 days if parallel.

---

## 8. Single most important thing this week

> **Apply the H2a finding to the production gate.** Per-regime direction is no longer
> optional — it's confirmed necessary by the genuine-reversal result. Phase A is the
> blocker. Everything else (Phase B, C, D) stacks on top.

---

## Citations

- H3.2 prototype: `reports/H32_SIZING_AB_2026-07-09.md`
- H3.2 floor/cap sweep: `reports/H32_SIZING_FLOORCAP_SWEEP_2026-07-10.md`
- H3.2 portfolio DD (corrective): `reports/H32_SIZING_PORTFOLIO_DD_2026-07-10.md`
- H2a relative-IC (critical): `reports/H2A_RELATIVE_IC_2026-07-10.md`
- H2 design (the framework this updates): `docs/H2_REGIME_GATE_DESIGN_2026-07-06.md`
- DSR audit: `reports/STRATEGY_DSR_AUDIT_2026-07-10.md`
- Causal sleeve: `reports/CAUSAL_SLEEVE_2026-07-10.md`
- Strategy upgrade: `reports/STRATEGY_UPGRADE_2026-07-10.md`
- Refutation ledger: `REFUTATION_LEDGER.md`