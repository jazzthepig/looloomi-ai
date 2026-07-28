# Strategy Playbook — Two L/S Strategies for Real Trading

**Seth, 2026-07-26** — Lock spec for Strategy 1 (validated) + honest documentation
of Strategy 2 exploration (deferred pending longer panel).

**UPDATE 2026-07-27 (Minimax-A, M-WO-1)** — Strategy 1 status RELABELED per
§DIRECTIVE 2026-07-27 episode-count gate. R77 fusion cell fails the ≥8-independent-
episode floor (gap>7d gaps-and-islands on the OOS P&L produces only 1 episode —
the book is continuously active across the 220-day OOS). Construction is preserved;
the "unique survivor" claim is corrected. See "Strategy 1 — Status correction"
banner below for the honest framing. Strategy 2 section unchanged.

**UPDATE 2026-07-27 (Minimax-A, M-WO-2 PARTIAL)** — Pillar sign-stability on the
11yr CIS panel delivered as a precondition audit (`reports/m_wo2_pillar_sign_stability_11yr/2026-07-27/`).
Findings: 100% persistence-IC sign-stability across all 5 pillars × 10 years (expected
— pillars are smoothed composites); 0% delta-IC sign-stability across years (mean-reverting
signature, regime-dependent). Pillar-O reversal (R46's underlying mechanism) is the most
regime-dependent (15-29% across cycles) — **this MAPS DIRECTLY to R77's W5 sign-flip
fragility** on the 731-day panel. Full M-WO-2 re-runs of R46/R78/R79/S-78 on the 11yr
panel are BLOCKED on the OHLCV extension (Option A per §DIRECTIVE). The 731-day panel
results stand until 11yr daily OHLCV is on disk. Lesson #66 documented: pillar smoothness
is a structural feature, not an edge. No code change to R77/R46/R78/R79/S-78 today.

**UPDATE 2026-07-28 (Seth, M-WO-7.1 BUILD COMPLETE)** — Per Jazz 2026-07-28 critical
redirection ("简单因子和特征不断重复,而不是利用好我们的vdb做风格辨识和运用"),
first slice of §M-WO-7 "VDB 做多" landed. Regime Fingerprint is a 12-dim per-trade-date
retrieval layer over validated modules (S-78 vol + M-WO-2 EXT pillar IC + R75 S/O
+ R62 detector + R76 funding + asset_embeddings centroid). Once verified on
Mac-side (SQL migration applied + 11yr backfill + first match query), the
`match_regime_fingerprints(target=today, k=50)` RPC directly satisfies the §DIRECTIVE
M-WO-1 ≥8-OOS-cluster episode-count floor for the R77 forward-commit deck — the
"alternative path" PROJECT_STATE §M-WO-1 lists alongside the 11yr long-panel re-run.
**Implication for Strategy 1 forward-commit**: when M-WO-7.1 verification completes,
the R77 frozen cell (`w_R46=0.25/w_R62=0.75/w_R76=0.30`) does NOT change, but the
forward-commit deck's evidence path can be reframed on VDB analog outcomes rather
than relitigating the M-WO-1 episode-count surface. Spec at `docs/REGIME_FINGERPRINT_SPEC.md`.

This is the "Strategy 1 ready + Strategy 2 deferred" close-out. Every line is
reproducible from the modules cited. The graveyard (R82 / R83 / R85 / R86) is
the asset — every REFUTED is a documented reason WHY this panel cannot host
a second L/S, and the data-align structural finding is preserved for the day
the panel gets longer / more balanced.

---

## Strategy 1 — R77 fusion cell (RELABELED 2026-07-27 per §DIRECTIVE M-WO-1)

**Validated 2026-07-23 (R77), paper-deployed 2026-07-21 (R65), monitored (R66/R71).**

### Status correction (2026-07-27, M-WO-1 episode-count audit)

Per §DIRECTIVE 2026-07-27 (Jazz + Seth → Minimax) M-WO-1 acceptance criteria
(`n_episodes ≥ 8 AND majority_positive AND episode_t > 2`), R77 fusion cell is
**🔴 REFUTED on the episode-count floor** (`reports/m_wo1_r77_episode_count_audit/2026-07-27/`).

- **Primary methodology (gap>7d, per §DIRECTIVE)**: 1 episode on the 220-day OOS
  window. R77 is daily-rebalanced and continuously active → the "gaps-and-islands"
  discipline finds zero breaks. Below the ≥8 floor.
- **Supplementary diagnostics** (informational, NOT changing the verdict):
  - Same-sign clustering: 30 sign-runs (20 positive / 10 negative) — the book
    DOES flip sign internally.
  - Quarterly partition: 3/3 quarters positive (last 2026Q2 = +65.6%, t=+2.58).
  - Monthly partition: 8/8 months positive — would clear the ≥8 floor under a
    calendar partition, but the directive's gap>7d is the binding criterion.
- **Honest framing**: R77 is a **regime-specific candidate**, NOT a unique
  survivor. The day-level OOS_t=+3.61 is real, but it is one 220-day continuous
  structural-alpha run on the bear-dominated 731-day panel — not 8 independent
  edges. Forward commit to live production is DEFERRED pending either (a) panel
  extension (M-WO-2 re-runs on the 11yr deep panel) OR (b) M-WO-7-style VDB-derived
  episode structure that yields ≥8 independent OOS clusters under the same gap>7d
  discipline.

### Construction (unchanged — module is still valid)

### Construction
- **Leg 1 (25%)**: R46 pillar_O 5d rebal, 5bps cost.
  - Score: pillar_O LEVEL (PIT-safe ffill, 1-day lag).
  - k=3 terciles; long top, short bottom.
- **Leg 2 (75%)**: R62 fragility-gated fade-the-crowd 21d rebal, 0bps cost.
  - Score: −funding_z (long uncrowded / short crowded), gated by detector.
  - Detector: KS-table fragile/playable split, z_threshold=2.0, min_features=3.
- **Leg 3 (30%)**: R76 funding residual 5d rebal, 0bps cost.
  - Score: funding[t, a] − mean_a(funding[t, a]) (cross-sectional demean).
  - k=3; long high-funding-residual / short low.

### Frozen weights
```
w_R46 = 0.25
w_R62 = 0.75   (= 1 - w_R46 for the 2-component base)
w_R76 = 0.30   (R77's optimal 3rd-leg contribution)
```

### Universe
- 28 assets (strict funding ∩ CIS ∩ OHLCV intersection).
- 731-day panel (2024-06-07 → 2026-06-07).
- 6-window partition for R62 detector.

### Performance (validated, R77 cell)
- gross_t=+3.10
- OOS_t=+3.61
- maxDD = −8.91%
- Sharpe = +2.06

### Live spec
- **Capacity**: $5M declared (R77 paper book).
- **Settlement**: daily NAV, T+1 mark.
- **Risk limits**:
  - Max position concentration: 10% per asset.
  - Max gross leverage: 1.0×.
  - Daily VaR cap: 2% of NAV.
- **Kill switches**:
  - Live Sharpe < 0.5× paper Sharpe over 30-day window → halt.
  - maxDD > 15% (paper was −8.91%) → halt and review.
  - Live-gross_5bps_t < 1.5 → halt (paper was +3.10).

### Files
- `src/research/validation/r77_r76_as_fusion_contribution.py` — main module
- `src/research/validation/r63_fusion_validation.py` — R46/R62 leg builders
- `src/research/validation/r76_funding_residual_ls.py` — R76 leg builder
- `src/research/validation/r61_pillar_o_detector_gated.py` — R62 detector infra
- Reports: `reports/r77_r76_as_fusion_contribution/<date>/`

### Monitoring
- **R66** — track-record updater (Railway T2 → investor dashboard).
- **R71** — NAV/days/Sharpe/mDD live tracker. Endpoint:
  `GET /api/v1/signals/fusion-paper` (currently `no_data` per R71 — pending
  Minimax-side marks push, see §OUTCOMES-STALE).

### Pre-flight
- 11/11 R77 smoke tests pass; preflight green.

---

## Strategy 2 — R89 Perp-Spot Basis Sleeve — 🔴 REFUTED (taker-fee illusion)

**Validated then REFUTED 2026-07-26 (R89).** R89 clears the 3-check gauntlet **at
5bps** (gross_t=+5.51, 5bps_t=+3.62, OOS_t=+4.75, all 6 windows positive) — but a
cost-tier check (mandatory for basis/carry trades per the repo's own R32 finding)
shows the entire edge lives in the 5→10bps gap. **R89 is NOT tradeable.**

### Why it was initially (wrongly) locked
The first pass validated at 5bps and saw a clean 3/3 with no W5 sign-flip — the
structural fragility that killed R46/R77/R87/R88. That looked like the survivor.

### Why it is actually REFUTED — the R32 taker-fee illusion
R89 is a **daily-rebalanced two-leg (spot + perp) basis flip**. Every rebal pays
taker on BOTH legs (perp-taker ~4.5bps + spot-taker ~10bps + slippage). Realistic
round-trip is 15–30bps, not 5. Cost-tier sweep on the locked cell:

| cost | cost_t | OOS_t | OOS_ann% | clears |
|---|---|---|---|---|
| 5bps | +3.62 | +4.75 | +33.9% | 3/3 ✅ (the ONLY surviving tier) |
| **10bps** | **−0.69** | **+0.34** | **+1.9%** | **1/3 — already dead** |
| 20bps | −8.42 | −6.89 | −62.3% | 1/3 |
| 30bps | −8.91 | −7.80 | −126.4% | 1/3 |

**No cell survives at 10bps** across the full threshold × cadence × lookback grid.
This is the identical failure mode to commit `1af76e5` (R32 cash_carry — "+2.42
Sharpe is a taker-fee illusion").

### Files (kept as research artifact + the lesson)
- `src/research/validation/r89_perp_spot_basis_sleeve.py` — now reports cost-tier
  sweep + gates verdict on ≥10bps survival
- `src/research/validation/tests/test_r89_perp_spot_basis_smoke.py` — 8/8 pass
- Reports: `reports/r89_perp_spot_basis/2026-07-26/verdict.json`
  (`survives_realistic_10bps: false`)

### The lesson (mandatory going forward)
**Any basis/carry/two-leg trade MUST pass a ≥10bps cost-tier gate before it can be
called tradeable.** The 3-check gauntlet at 5bps is necessary but NOT sufficient for
high-turnover multi-leg strategies. R32 established this; R89 forgot it; the gate is
now baked into the R89 module's verdict logic.

---

## Strategy 2 — STILL OPEN (R82/R83/R85/R86/R87/R88 REFUTED on panel; R89 = fee-illusion)

**Historical context**: 7 distinct strategies tested. 6 failed the 3-check gauntlet
on the 731-day panel; R89 passed at 5bps but is a taker-fee illusion (dies at ≥10bps).
**No tradeable Strategy 2 exists yet.** The structural reasons are documented below.

### Strategy 2 candidates tested (graveyard is the asset)

| R# | Hypothesis | Verdict | Why it failed |
|---|---|---|---|
| **R82** | pillar_A regime-gated L/S (bullish regimes + L1/L2/Infra only) | 🟡 PARTIAL | Sign correct (matched-cell diff +5.46 high_a_long), magnitude too thin (gross_t=+1.45 < 1.96) |
| **R83** | Vol risk-premia L/S (long low-vol / short high-vol) | 🔴 REFUTED | gross_t=+0.36, 5bps_t=+0.27; W1-W6 inconsistent (W1=−68.7%, W4=+56%) |
| **R85** | R77 fusion + regime-gate at fusion level | 🔴 REFUTED | gross_t=−0.26, OOS_t=+0.50; **double-counts R62's detector** (regime-gate payload already in R77) |
| **R86** | R46 5d/5bps on 11yr aligned pillar + 50% OOS cut | 🔴 REFUTED | All cadences {5,7,14,21,30} × {30%, 50% OOS} fail; best OOS_t=+0.52 < 1.96 |
| **R87** | Directional LONG top-K quality + regime-gated gross | 🔴 REFUTED | 71% of panel has reduced/zero gross (RISK_OFF 35% + TIGHTENING 24%); alpha FLAT across all 4 measured regimes |
| **R88** | Pair-trading (within-pair quality spread, dollar-neutral) | 🔴 REFUTED | gross_t=+1.30, 5bps_t=+1.03, OOS_t=+0.48; W3 + W5 sign-flip (4/6 positive windows but t-stats too thin) |
| **R89** | Perp-spot basis sleeve (long spot / short perp on wide basis) | 🔴 REFUTED | Clears 3/3 at 5bps (gross_t=+5.51) but **taker-fee illusion** — dies at ≥10bps (cost_t=−0.69), no cell survives realistic cost. Same as R32 cash_carry |

### Structural finding (the lesson)

**The 731-day panel (2024-06-07 → 2026-06-07) is too bear-dominated for ANY
single-leg factor to clear the 3-check gauntlet.**

Evidence:
- R46 pillar_O 5d/5bps (the strongest single pillar): gross_t=+2.68 ✓, 5bps_t=+2.49 ✓, OOS_t=−0.39 ✗
- R62 fade-the-crowd: clears internally but the "fragility detector" reveals the OOS is gated by regime
- R76 funding residual 5d/0bps: gross_t=+2.11 ✓, but at 5bps degrades to gross_t=+1.73 ✗
- R77 fusion of all three: clears 3-check (gross_t=+3.10, OOS_t=+3.61) — the only one

**Mechanism**: R77's three legs cover different SIGNAL TYPES (quality, crowding,
funding). Each has its own regime-protection mechanism (R62's detector, R76's
perp-market-maker carry, R46's quality-vs-BTC correlation). Single-leg strategies
lack this diversification and depend on the panel not being bear-dominated.

**S-82 (2026-07-24) confirmed the same mechanism**: R77 + regime-gross-scaling
REFUTED because R77's alpha is FLAT across BTC-trend bands (deep_off/off/neutral/
on/deep_on all +0.2% to +0.9%) — genuinely regime-INVARIANT, not regime-DEPENDENT.
Lesson #44: "regime-gross-scaling is a CATEGORY match not a universal upgrade —
it needs a book whose alpha is regime-DEPENDENT (directional sleeve), NOT a
market-neutral factor book."

### Path forward for Strategy 2

**Option A (deferred — preferred)**: wait for a longer / more balanced panel.
- OHLCV is the binding constraint (only 731 days available).
- Once Minimax extends the OHLCV back to 2015-2023 (per data-align), re-run
  R86-style cadence × OOS sweeps on 11yr price data.
- If 11yr panel clears, the same R46 / R82 / R83 / R86 candidates will surface
  a valid Strategy 2.

**Option B (out of scope, requires Minimax)**: build a Strategy 2 on a
DIFFERENT signal source. Candidates that have NOT been tested on the 11yr panel:
- Cross-asset basis (perp-spot residual)
- Informativeness-WEIGHTED funding
- Cross-frequency 4h signals aggregated to daily
- Structural-break detection (volatility regime change)
- Cluster-rotation L/S (long underperformer within cluster, short outperformer)
None of these are small additions — they require new data feeds.

**Option C (NOT recommended)**: accept R77 as the only L/S strategy and ship
as a single-strategy book. Lower diversification, but production-ready today.

### What to do NOW

Strategy 1 is locked. The §STRATEGY-2-DEFERRED path is the honest answer.
Add `STRATEGY_2_DEFERRED.md` to the graveyard ledger; commit the R82/R83/R85/R86
verdicts as a single batched R/S-86 entry once the user signs off.

---

## Cross-strategy production checklist (Strategy 1 only, for now)

- [x] R77 module (`r77_r76_as_fusion_contribution.py`)
- [x] R63 module (R46/R62 leg builders)
- [x] R76 module (R76 leg builder)
- [x] R71 monitoring module (`/api/v1/signals/fusion-paper`)
- [x] 11/11 R77 smoke tests pass
- [x] Preflight green
- [x] Live spec written (this doc)
- [ ] R65 paper marks flowing (currently `no_data` — pending Minimax §OUTCOMES-STALE)
- [ ] Live Sharpe at paper-par after n_days ≥ 60
- [ ] User sign-off on live deployment

---

## References

- **R77 module**: `src/research/validation/r77_r76_as_fusion_contribution.py`
- **R77 verdict**: `reports/r77_r76_as_fusion_contribution/2026-07-23/verdict.json`
- **R62 fragility detector**: `src/research/validation/r62_fragility_gated_funding.py`
- **R76 funding residual**: `src/research/validation/r76_funding_residual_ls.py`
- **§DATA-ALIGN pipeline**: `src/research/data_align/`
- **§TRADER_TOM_DOCTRINE**: `docs/TRADER_TOM_DOCTRINE.md`
- **Refutation ledger**: `REFUTATION_LEDGER.md`
- **S-82 lesson (regime-gross-scaling REFUTED)**: `r82-s82-regime-gross-overlay-refuted.md`
- **R85 lesson (R77 + regime-gate double-count)**: `r85-r77-regime-gate-double-count.md`
- **Data-align IC mining**: `reports/data_align/pillar_ic_mining_summary.md`
