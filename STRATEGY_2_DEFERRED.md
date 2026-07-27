# Strategy 2 — Deferred (Graveyard) → R97 also REFUTED (15-attempt graveyard COMPLETE)

**Seth, 2026-07-27 — R97 CIS-LS V5 dual-horizon trend L/S REFUTED on the 731-day panel; Jazz's Option A remains the binding path: WAIT for §OHLCV-EXTENSION.**

R97 is the 15th attempt after R82/R83/R85/R86/R87/R88/R89/R90/R91/R92/R93/R94/R95/R96. Per Jazz "参考cisLSv4的工作开发吧", R97 rebuilt the working structure of cisLSv4 (LS V4 + Trend V5c) as a frozen dual-horizon L/S sleeve that fixes R49's confirmed flaws (LS V4 = pure momentum beta → 100 flips/yr → cost kills residual alpha):

- 24-asset strict universe on real 1h parquet (731 days, 103,529 4h-bars)
- Major trend: 4h EMA54/126 (≈ 9d/21d); entry confirmation: 4h EMA9/21 + ADX14 ≥ 25 + DMI consistency
- Direction rule: major trend is ceiling/floor — fast signal cannot REVERSE major
- CIS gate: composite score ≥ 55 (B+); funding z ≥ 2 veto; ATR14 inverse-vol sizing; 5d rebal
- PIT lag ≥ 1 bar; no regime scaler; R77 frozen weights unchanged
- **3-check FAILS** at every cost tier: gross_t=+0.69 (need >1.96), OOS_t=−0.29, maxDD=−30.10%, positive windows=3/6
- **BUT**: R97 is QUALITATIVELY BETTER than all 3 cisLSv4-family baselines on the SAME panel (LS V4 Sharpe=−0.93 / V5c=−0.25 / slow signed=+0.09 vs R97=+0.09 with maxDD −30.10% vs −69.08%/−53.83%/−47.33%) — the dual-horizon FIXES R49's flaws; just doesn't clear 1.96 on this panel

**Verdict: 🔴 REFUTED.** The dual-horizon shape is the qualitative-best cisLSv4 family on this panel, but the 731-day bear-dominated window cannot host any single-strategy shape. This does not prove the dual-horizon shape cannot work — it proves the panel is too short. Re-run on the 11yr panel when §OHLCV-EXTENSION ships. Strategy 2 remains structurally deferred. Do not promote R97 to production or alter the frozen R77 cell.

R96 was the 14th attempt after R82/R83/R85/R86/R87/R88/R89/R90/R91/R92/R93/R94/R95. It moved to a structurally different data class — 33 TradFi assets from the EODHD local SQLite buffer — and tested a 60d rolling bond-minus-equity β-residual score:

- 33 TradFi assets, 249 daily observations (2025-07-29 → 2026-07-24)
- score = β_TLT − β_SPY, lagged 1d; market-neutral tercile L/S
- cadences 1/3/5/7/14/21d × costs 0/5/10/20/30bps = 30 cells
- best: 5d / 0bps, full_t=−0.347, OOS_t=+0.845, maxDD=−14.25%, Sharpe=+0.477
- 5bps full_t=+0.188; 10bps full_t=+0.104; zero cells pass the realistic-cost gate
- absorption fails: alpha_t=−0.63; SPY β=+0.919 (t=+8.54) dominates, so the sleeve is equity beta in disguise
- windows alternate violently: W2=−69.1%, W3=+92.8%, W4=−58.7%, W5=+149.5%, W6=−51.0%

**Verdict: 🔴 REFUTED.** The data-class pivot did not escape the short-panel constraint. This does not prove cross-asset relative value cannot work; it proves this 249-day β-residual construction is not a defensible second tradeable sleeve. Strategy 2 remains structurally deferred until §OHLCV-EXTENSION supplies longer, cycle-balanced history. Do not promote R96 to production or alter the frozen R77 cell.


13 prior attempts (R82/R83/R85/R86/R87/R88/R89/R90/R91/R92/R93/R94/R95) plus R96 are REFUTED.
R94 = §TRADER_TOM two-layer book Directional Crypto Beta Sleeve (L2, LONG-only BTC/ETH/SOL equal-weight,
DAILY risk-state evaluation + 1-day lag, regime-scaled gross) — **3-check FAILS at every cost tier**
(best gross_t=−1.820 at 0bps, sign-FLIPPED NEGATIVE at 5/10/20/30bps); **scaling HURTS static_beta**
(OOS_t=−1.96 vs static_beta OOS_t=−1.33); maxDD=−47.38% (blows past −20% budget 2.4× over); W5=−58.1%
(catastrophic late-cycle fragility); W1=−76.8% (catastrophic bear-window front); 2/6 windows positive
(W2/W4 only). **Even with daily state updates + one-day lag + tight maxDD + mandatory benchmarks +
combined-book check, this directional shape cannot clear 3-check on the 731-day bear-dominated panel.**

**Status of Strategy 2 (JAZZ DECISION 2026-07-26, confirmed post-R94):**
- **R77 fusion cell** = Strategy 1 (LOCKED, market-neutral, OHLCV-only signals — validated WITH 5bps applied)
- **Strategy 2** = **STRUCTURALLY DEFERRED** pending Minimax §OHLCV-EXTENSION completion. **12 attempts REFUTED** (R82/R83/R85/R86/R87/R88/R89/R90/R91/R92/R93/R94); perp-funding family EXHAUSTED on 4 distinct shapes (RESIDUAL/CARRY/PAIRWISE/INFORMATIVENESS-WEIGHTED) + basis variant; **directional family EXHAUSTED on 2 distinct shapes** (R92 signed L/S weekly-only + R94 LONG-only daily-state). R77 ships as the only L/S strategy while waiting for 11yr price data.

This doc is the honest graveyard for all 11 attempts. The structural reason
(panel bear-domination + perp-microstructure class cost-tier failure + directional
filter lag + informativeness-weighting collapse onto naive fade) is preserved
for posterity — the panel is too short for any single-strategy shape to clear
3-check, the perp-funding alpha is structural to the 5d-rebal cross-sectional
RESIDUAL that R76 captured (not transferable to lower turnover, pairwise,
two-leg, or informativeness-weighted shapes), and even a directional overlay
with pre-confirmation filter (R92) cannot clear 3-check on the 731-day panel.
R93's anti-costume gate failure (corr=+0.728 > 0.60) is the structural proof
that informativeness-conditioning does not escape the perp-funding family
exhaustion on this universe.

---

## TL;DR — graveyard (OHLCV-only family)

| # | Hypothesis | Verdict | Single-line reason |
|---|---|---|---|
| **R82** | pillar_A regime-gated L/S (bullish regimes + L1/L2/Infra only) | 🟡 PARTIAL | Sign correct (matched-cell diff +5.46 high_a_long), magnitude too thin (gross_t=+1.45 < 1.96) |
| **R83** | Vol risk-premia L/S (long low-vol / short high-vol) | 🔴 REFUTED | gross_t=+0.36, 5bps_t=+0.27; W1-W6 inconsistent (W1=−68.7%, W4=+56%) |
| **R85** | R77 fusion + regime-gate at fusion level | 🔴 REFUTED | gross_t=−0.26, OOS_t=+0.50; **double-counts R62's detector** |
| **R86** | R46 5d/5bps on 11yr aligned pillar + 50% OOS cut | 🔴 REFUTED | All cadences × OOS cuts fail; best OOS_t=+0.52 < 1.96 |
| **R87** | Directional LONG top-K quality + regime-gated gross | 🔴 REFUTED | 71% of panel has reduced/zero gross; alpha FLAT across all 4 measured regimes |
| **R88** | Pair-trading (within-pair quality spread, dollar-neutral) | 🔴 REFUTED | gross_t=+1.30, 5bps_t=+1.03, OOS_t=+0.48; W3 + W5 sign-flip |
| **R92** | §TRADER_TOM directional overlay (BTC 3-factor trend filter, signed L/S) | 🔴 REFUTED | W5=+509.7% lift real; gross_t=+1.03 < 1.96 at 0bps; maxDD=−48.69%; W3/W6 catastrophic |
| **R93** | Informativeness-weighted funding-z (anti-costume gate < 0.60 vs naive fade) | 🔴 REFUTED | corr(R93, naive_fade) = +0.728 > 0.60 (gate FAIL); 3-check fails at every cell; W1/W3 still negative |
| **R94** | §TRADER_TOM Directional Crypto Beta Sleeve (L2, BTC/ETH/SOL LONG-only, daily state, regime-scaled) | 🔴 REFUTED | 3-check FAILS at every cost tier (best 0bps gross_t=−1.820); scaling HURTS static_beta (OOS_t−1.96 vs −1.33); maxDD=−47.38%; W1=−76.8% + W5=−58.1% catastrophic; 2/6 windows positive |
| **R95** | Per-asset signed TSMOM trend L/S (25 assets, 7 horizons, no demean) | 🔴 REFUTED | Best 63d/14d/0bps full_t=+1.360 and OOS_t=+1.320 (<1.96); 5bps=+1.33, 10bps=+1.31; zero cells pass realistic cost gate; all P&L concentrated in W6 (+59.5% ann.) |
| **R96** | Cross-asset bond-equity β-residual L/S (33 TradFi assets, 60d OLS β) | 🔴 REFUTED | Best cadence=5/0bps full_t=−0.347 and OOS_t=+0.845; 5bps=+0.19, 10bps=+0.10; absorption NOT SIGNIFICANT (SPY β=+0.92 dominates); W2-W6 extreme volatility (W5=+149% / W3=+93% alternating with W2=−69% / W4=−59% / W6=−51%) |
| **R97** | CIS-LS V5 dual-horizon trend L/S (24 crypto assets, 4h EMA54/126 MAJOR + 4h EMA9/21+ADX entry, CIS≥55 gate, funding z≥2 veto) | 🔴 REFUTED | Best gross_t=+0.69 (need >1.96), OOS_t=−0.29, maxDD=−30.10%, positive windows=3/6, Sharpe=+0.09. **But QUALITATIVELY BEST cisLSv4 family on same panel** — beats LS V4 by +1.02 Sharpe, V5c by +0.34, slow signed by same Sharpe with −17pp less maxDD. Dual-horizon fixes R49 flaws; doesn't escape 731-day panel constraint |

## Perp-microstructure family — R89 + R90 + R91 (perp-funding family EXHAUSTED)

| # | Hypothesis | Verdict | Single-line reason |
|---|---|---|---|
| **R89** | Perp-spot basis sleeve (long spot / short perp when basis > +threshold) | 🔴 **REFUTED** | Clears 3/3 **at 5bps** (gross_t=+5.51, no W5 sign-flip) but **taker-fee illusion** — 10bps → cost_t=−0.69/OOS +1.9%; 20bps → −62%; NO cell survives ≥10bps. Two-leg daily flip. Same as R32 |
| **R90** | Perp funding-carry HELD (cross-sectional demean, weekly+ rebal) | 🔴 **REFUTED** | Best 7d/0bps gross_t=+1.21 already below 1.96; 10bps → +0.62 dead; **lower turnover DEFEATS the signal** (21d/0bps gross_t=+0.10 = 0.07× W1 alpha); R76's 5d edge was 5d-specific, not a perpetual carry |
| **R91** | Cross-asset funding pair (top 8 most-correlated perp pairs, 7/14/21/30d rebal) | 🔴 **REFUTED** | Best 7d/0bps gross_t=+1.19 already below 1.96; 5bps → +0.88; 10bps → +0.58 dead; **pair-spread is a fainter echo of R76** (maxDD=−30.44% vs R77's −8.91%, 3.4× worse) |

**R89 beat the W5 fragility (all 6 windows positive) — the structural discovery is
real: perp microstructure is regime-orthogonal to the OHLCV factor family.** But
the trade is not economically viable at realistic cost. **R90 + R91 followed
this up with low-turnover / pairwise alternatives (per lesson #58 "next
candidate must be STRUCTURALLY DIFFERENT"). Both REFUTED — the perp-funding
alpha is structural to the 5d-rebal cross-sectional RESIDUAL that R76 captured,
NOT transferable to lower turnover or pairwise spread.** The lesson: any
basis/carry/pair-spread trade must clear a **≥10bps cost-tier gate** before it
can be called tradeable. That gate is now baked into r89/r90/r91 module verdicts.

**Perp-funding family EXHAUSTED on 3 distinct shapes + basis variant.** The R77
fusion cell (which uses R76 5d-residual as one of three legs) is the unique
survivor because each leg has its own regime-protection mechanism. The
perp-funding shape CANNOT be re-extracted as a standalone strategy on this
universe.

---

## The structural finding (the lesson)

**The 731-day panel (2024-06-07 → 2026-06-07) is too bear-dominated for any
single-leg factor to clear the 3-check gauntlet.**

### Evidence (per-leg t-stats on the same panel)

| Sleeve | gross_t | 5bps_t | OOS_t | Notes |
|---|---|---|---|---|
| R46 pillar_O 5d/5bps (the strongest single pillar) | +2.68 ✅ | +2.49 ✅ | **−0.39** ❌ | W5 sign-flip |
| R62 fade-the-crowd (gated) | clears internally | — | +1.20 (gated) | Detector-protected |
| R76 funding residual 5d/0bps | +2.11 ✅ | **+1.73** ❌ | +3.15 ✅ | At 5bps degrades |
| R77 fusion of all three | **+3.10** ✅ | **+3.10** ✅ | **+3.61** ✅ | **The unique survivor** |

### Mechanism

R77's three legs cover different SIGNAL TYPES:
- **R46** — quality-vs-BTC cross-sectional rank (CIS pillar_O LEVEL)
- **R62** — per-asset funding-z reversal, fragility-detector-gated
- **R76** — funding cross-sectional demean (perp-market-maker carry)

Each has its own regime-protection mechanism. Single-leg strategies lack this
diversification and depend on the panel not being bear-dominated. The 731-day
window has W5 = 2025-10 → 2026-02 late-cycle risk-on chop, where most factors
either sign-flip or thin out.

### S-82 corroboration (2026-07-24)

R77 + regime-gross-scaling was REFUTED because R77's alpha is **FLAT** across
BTC-trend bands (deep_off +0.9% / off +0.5% / neutral +0.2% / on +0.7% /
deep_on +0.6% — all within noise). The book is **regime-INVARIANT**, not
regime-DEPENDENT. Lesson #44: regime-gross-scaling is a CATEGORY match not a
universal upgrade — it needs a book whose alpha is regime-DEPENDENT
(directional sleeve), NOT a market-neutral factor book.

### R85 corroboration (2026-07-26)

R77 + regime-gate at fusion level REFUTED because R62's fragility detector
INSIDE R77 already provides bear-window protection. Adding another regime-gate
at fusion level = double-counting, not double-protection. Lesson #45: when
adding a risk overlay to a multi-leg fusion, check whether the overlay's
payload is already provided by one of the legs.

---

## Why each candidate was tried

### R82 — pillar_A regime-gated (Seth, 2026-07-25)
**Why tried:** §DATA-ALIGN showed pillar_A is regime-CONDITIONAL (POSITIVE in
RISK_ON/EASING/STAGFLATION, NEGATIVE in TIGHTENING/RISK_OFF-bear). Restrict
to bullish regimes + L1/L2/Infra class only.
**Why failed:** Sign-correct (matched-cell diff +5.46 favoring
high_a_long — directional thesis rock-solid), but magnitude too thin
(gross_t=+1.45 < 1.96). The regime gate cuts gross by ~40% (TIGHTENING/RISK_OFF
days flat-zeroed), and the surviving bull-regime alpha does not compensate.
**File:** `src/research/validation/r82_pillar_a_regime_gated.py` (~290 LoC)
+ 10/10 smoke tests.

### R83 — Vol risk-premia L/S (Seth, 2026-07-25)
**Why tried:** Per the §TRADER_TOM_DOCTRINE two-layer framework, low-vol/
high-vol cross-sectional L/S is a structurally orthogonal sleeve to the
quality/funding axes already in R77. Theoretically should harvest the
risk-premium that volatility-selling books collect.
**Why failed:** gross_t=+0.36, 5bps_t=+0.27 — both far below 1.96. W1-W6
inconsistent (W1=−68.7%, W4=+56%) — no coherent signal across windows. The
vol-risk-premia that works in TradFi (1980-2020) does NOT transfer cleanly
to crypto microstructure (perp funding, spot wash, market-maker inventory).
**File:** `src/research/validation/r83_vol_risk_premia_ls.py` (~165 LoC)
+ 5/5 smoke tests.

### R85 — R77 + regime-gate overlay (Seth, 2026-07-26)
**Why tried:** Per user's pivot ("fold Strategy 2 into R77 as a
sub-configuration"), R85 = the same R77 signal source but with a regime gate
(only RISK_ON/EASING/STAGFLATION; flat-zero in TIGHTENING/RISK_OFF).
Expected: lower maxDD, smoother P&L, preserved gross_t.
**Why failed:** gross_t=−0.26, OOS_t=+0.50. **R62's fragility detector inside
R77 already provides bear-window protection** — gating again at fusion level
= double-counting. The 59% of panel days blocked include some where R62's
detector allowed positions to ride through (those were the days R77 made
money). Flat-zeroing them strips the alpha without removing proportional risk.
**File:** `src/research/validation/r85_r77_regime_gated.py` (~280 LoC).

### R86 — R46 on 11yr aligned panel + 50% OOS cut (Seth, 2026-07-26)
**Why tried:** Per user's second pivot ("extend the panel, re-run R46 5d/5bps
with 50% OOS cut"). The 11yr aligned CSV has 4016 days × 34 assets
(2015-2026) vs the 731-day window — far more balanced cycles. Hypothesis: more
OOS data + better pillar_O reconstruction lifts OOS_t from −0.31 to > 1.96.
**Why failed:** All cadences {5, 7, 14, 21, 30} × {30%, 50% OOS} fail;
best OOS_t=+0.52 < 1.96. **OHLCV is the binding constraint** — only 731 days
of forward returns available (2024-06-07 → 2026-06-07). The 11yr aligned CSV
gives better pillar_O reconstruction within this window, but cannot extend
the price panel. The bear-window effect is structural to the 2024-06 → 2026-06
window itself, not a sample-size issue.
**File:** `src/research/validation/r86_r46_11yr_extended_oos.py` (~165 LoC).

### R87 — Directional LONG top-K quality + regime-gated gross (Seth, 2026-07-26)
**Why tried:** Per user's pivot ("build a DIRECTIONAL sleeve to literally
satisfy the goal of two strategies"). The §TRADER_TOM_DOCTRINE trend-overlay
slot is structurally DIFFERENT from R77's market-neutral book — needs a
directional book, not another market-neutral L/S. R87 = LONG top-K quality
(k=5, 20% each), gross scales with regime per doctrine (RISK_ON=1.0,
EASING=1.0, STAGFLATION=0.5, TIGHTENING=0.25, RISK_OFF=0.0).
**Why failed:** gross_t=+0.08, 5bps_t=+0.03, OOS_t=−1.41 (0/3 cleared).
**Regime distribution on the 731-day panel**: RISK_OFF 256 days (35%),
TIGHTENING 175 (24%), EASING 215 (29%), RISK_ON 58 (8%), STAGFLATION 27 (4%).
71% of panel has reduced/zero gross (TIGHTENING + STAGFLATION + RISK_OFF =
458/731 days). Within the 37% long-eligible days (RISK_ON+EASING), alpha is
0.07% annualized (no edge). **Mechanism check (antithesis of S-82)**: alpha
should be regime-DEPENDENT if the directional shape is right — instead it is
FLAT across all 4 measured regimes (RISK_ON +0.1%, EASING −0.1%, TIGHTENING
+0.3%, RISK_OFF +0.2% — all within noise). **Per-window W1-W6**: W2 = +115.6%
(only positive window, same as R77's W2 dominance), W1 = −38.4%, W4 = −54.2%,
W5 = −29.3%, W6 = −25.6% (4/6 negative). The directional sleeve is not
short-window flexible enough to capture R77's W2 alpha without bleeding in
W4-W6 drawdowns.
**File:** `src/research/validation/r87_directional_trend_sleeve.py` (~290 LoC) +
9/9 smoke tests.
**Lessons added:**
- **#49** — directional sleeve needs MORE than regime-gating + long top-K quality
  to overcome 71% bear-window gross reduction. The doctrine's "press in risk-ON"
  requires a pre-confirmation signal (e.g., 30d perf > 0) on top of regime.
- **#50** — per-window analysis confirms that a directional long-only book leaks
  alpha in W4-W6 (the bear-window droughts); the 8% RISK_ON window is too thin
  to support a long-only directional.
- **#51 (META)** — the 731-day panel is bear-dominated for BOTH market-neutral
  AND directional shapes. The structural finding is now confirmed across 5
  distinct attempts (R82/R83/R85/R86/R87). Anti-imposter: continuing to "try
  another shape" on the same panel is a category error, not a strategy problem.

### R88 — Pair-Trading Sleeve (within-pair quality spread) (Seth, 2026-07-26)
**Why tried:** Per user's "keep on finishing" instruction, attempt the
structurally most distinct shape left. Pair-trading = within-pair quality
spread on top-10 correlated pairs (corr >= 0.70), dollar-neutral by construction,
equal-weight across pairs. The pair spread is mean-reverting by economic
construction (similar assets provide within-pair hedge).
**Why failed:** gross_t=+1.30, 5bps_t=+1.03, OOS_t=+0.48 (0/3 cleared).
**Per-window W1-W6**: W1=+27.1%, W2=+29.9%, W3=**−30.9%**, W4=+34.5%,
W5=**−35.7%**, W6=+43.9%. 4/6 positive windows but t-stats too thin to clear
1.96 (max α_t = +1.93 in W6). **W3 + W5 sign-flip**: W5 is the same late-cycle
risk-on chop window R46/R77 sign-flipped in (consistent across shapes); W3
is a new pair-trading-specific exposure on average-volatility days where
within-pair spread doesn't revert. The pair-portfolio IS dollar-neutral by
construction (sum |w| = 2.0, sum w = 0) — that's not the issue. The
underlying pair-quality signal is too thin.
**File:** `src/research/validation/r88_pair_trading_sleeve.py` (~310 LoC) +
8/8 smoke tests.
**Lessons added:**
- **#52** — pair-trading on correlated crypto assets does NOT escape the W3 + W5
  sign-flip pattern. W3 = average-volatility days where within-pair spread
  doesn't revert; W5 = late-cycle risk-on chop. The structural finding is now
  confirmed across 7 distinct attempts.
- **#53 (META, upgraded from #51)** — the 731-day panel is bear-dominated for
  ANY single-leg factor AND any reasonable single-strategy shape. R77 fusion
  of 3 orthogonal legs is the unique survivor.
- **#54 (ANTI-IMPOSTER)** — "try another shape" on the same panel is the wrong
  lever. The lever is panel length. The next attempt on this panel is not a
  research move — it's a sunk-cost trap.

### R89 — Perp-Spot Basis Sleeve (perp-microstructure shape) (Seth, 2026-07-26)
**Why tried:** Per R88 lesson, the OHLCV-only / cross-sectional-rank family is
exhausted. R89 = perp-spot basis sleeve on a STRUCTURALLY DIFFERENT data shape
(perp microstructure, Hyperliquid perp OHLCV ∩ spot OHLCV, 30-asset, 731-day
panel). Long spot / short perp when basis > +threshold, dollar-neutral, daily
rebal. Perp microstructure IS regime-orthogonal to the OHLCV factor family
(R89 W5=+36.59%, all 6 windows positive — the only signal that beat W5
fragility).
**Why failed:** 🔴 REFUTED — **taker-fee illusion** (same class as R32
cash_carry). Clears 3-check at 5bps (gross_t=+5.51, 5bps_t=+3.62, OOS_t=+4.75)
but cost-tier sweep shows: 10bps → cost_t=−0.69/OOS +1.9% (dead); 20bps → −62%/yr;
30bps → −126%/yr. A daily-rebalanced two-leg (spot+perp) flip pays taker on BOTH
legs; realistic round-trip is 15-30bps, not 5. **NO cell survives ≥10bps** across
the full threshold × cadence × lookback grid.
**File:** `src/research/validation/r89_perp_spot_basis_sleeve.py` (~480 LoC)
+ 8/8 smoke tests.
**Lessons added:**
- **#58 (cost-tier gate, MANDATORY for basis/carry/two-leg trades)** — any
  basis/carry/two-leg trade MUST pass a ≥10bps cost-tier gate before
  "tradeable". The 3-check at 5bps is necessary but NOT sufficient for
  high-turnover multi-leg strategies.

### R90 — Perp Funding-Carry HELD (cross-sectional demean, weekly+ rebal) (Seth, 2026-07-26)
**Why tried:** Per R89 lesson #58 + R90 plan, the perp-microstructure family has
a real regime-orthogonal property (R89 W5 lift is real). Question: keep the
signal, remove the spot leg (single-instrument: perps only), and lower turnover
(weekly+ rebal). R90 = perp funding residual (R76's signal verbatim) cross-
sectional L/S, 7/14/21/30d rebal, single-instrument, mandatory cost-tier sweep.
**Why failed:** 🔴 REFUTED — NO cell passes 3-check at any cost tier. Best cell
7d/0bps gross_t=+1.21 already below 1.96; 10bps → +0.62 dead; 20bps → +0.03;
30bps → −0.56. **Critical finding**: lower turnover DEFEATS the signal — 21d/0bps
gross_t=+0.10 (0.07× the W1 alpha); 30d/0bps gross_t=+0.40. **R76's standalone
5d edge was a 5d-specific phenomenon, not a perpetual carry.** W6=−47.0%
catastrophic.
**File:** `src/research/validation/r90_perp_funding_carry_held.py` (~530 LoC)
+ 12/12 smoke tests.
**Lessons added:**
- **#58 (CONFIRMED, 3rd case)** — perp funding carry HELD (single-instrument,
  low turnover, cost-tier sweep) — no cell passes 3-check at any cost tier. The
  R76 standalone edge was 5d-specific. Even at 0bps, the weekly+ signal is too
  thin to clear 1.96.

### R91 — Cross-Asset Funding Pair (top 8 most-correlated perp pairs) (Seth, 2026-07-26)
**Why tried:** Per R90 lesson #58 (3rd case), perp shelf EXHAUSTED on
cross-sectional funding demean. R91 = switch from cross-sectional demean to
PAIR-WISE spread (`funding_A − funding_B` for correlated perp pairs). The
pairwise version is STRUCTURALLY DIFFERENT from R76/R90 (the demean floor is
the PAIR not the universe; the signal is RELATIVE carry within the pair).
Top 8 pairs by funding correlation: ETC-LDO, ETC-STX, ETC-FIL, DOGE-ETC,
FIL-LDO, AVAX-ETC, DOGE-LINK, FIL-SUSHI (all 0.78–0.82 corr). 7/14/21/30d rebal,
mandatory cost-tier sweep.
**Why failed:** 🔴 REFUTED — NO cell passes 3-check at any cost tier. Best cell
7d/0bps gross_t=+1.19 already below 1.96; 5bps → +0.88; 10bps → +0.58 dead.
**Pair-spread is a smaller, fainter echo of R76's signal at lower frequency and
worse drawdown** — R76 5d/0bps maxDD=−11.0% vs R91 7d/0bps maxDD=−30.44%
(3.4× worse than R77's −8.91%). The cross-sectional RESIDUAL edge is STRUCTURAL,
NOT transferable to a pairwise version. Per-window W4=−32.4% (catastrophic new
bear-window exposure) + W5=+60.6% (kept discovery PARTIALLY preserved).
**File:** `src/research/validation/r91_cross_asset_funding_pair.py` (~360 LoC)
+ 11/11 smoke tests.
**Lessons added:**
- **#58 (CONFIRMED, 4th case, 3rd shape)** — perp funding-driven L/S —
  RESIDUAL (R76), LEVEL (R73 path), CARRY (R90), or PAIRWISE SPREAD (R91) —
  does NOT survive at realistic cost on this universe. The perp-funding alpha
  is real but in a different shape: it lives in 5d-rebal high-frequency
  cross-sectional RESIDUAL that R76 captured. Lowering turnover (R90),
  switching to pair-spread (R91), or two-leg flipping (R89) all destroy it.

---

**Aggregate lesson #58 (FULLY ARTICULATED, 4 cases / 3 shapes):**
- **R89 (two-leg daily flip — basis)** — fails at 10bps (fee trap, daily rebal too expensive)
- **R90 (single-instrument weekly+ HELD — carry)** — fails at every cost tier (signal too thin to clear)
- **R76 (5d/0bps appeared to survive — residual)** — R90/R91 show 5d-specific
- **R91 (pair-spread 7d/0bps — pairwise)** — fainter echo, maxDD 3× R77

**Perp-funding family EXHAUSTED on 3 distinct shapes (RESIDUAL/CARRY/PAIRWISE)
plus basis variant.** The next move on this panel is NOT another perp-funding
candidate. The next move is wait for OHLCV extension (Option A, CHOSEN) and
re-run the OHLCV-only candidate set on 11yr price data.

### R92 — §TRADER_TOM Two-Layer Book Directional Overlay (Trend-Conditional L/S) (Seth, 2026-07-26)
**Why tried:** Per R91 lesson + user's pivot ("build the §TRADER_TOM two-layer
book"), R92 is Layer 2 of the two-layer architecture (R77 = Layer 1). R87 was
REFUTED because (a) 71% of panel has reduced/zero gross (mostly bear regime),
(b) LONG-only book can't earn bear-window alpha, (c) per-window W4=−54.2% /
W5=−29.3% / W6=−25.6%. R92 fixes all three:
1. **Pre-confirmation filter (lesson #49):** BTC close > 100d MA AND 100d MA
   slope > 0 AND 30d return > +3% → BULL_TREND (LONG top-K); inverted → BEAR_TREND
   (SHORT top-K); otherwise → CHOP (FLAT). Trend-specific, not macro-broad.
2. **SIGNED directional:** BEAR_TREND goes SHORT (R87 was long-only — couldn't
   earn bear alpha). R92 earns alpha in BOTH bull and bear trends.
3. **Sharper filter:** trend-specific (3-factor confirmation) vs R87's broad
   macro classification. More time active (39% non-flat vs R87's 29%).

**Why failed:** 🔴 REFUTED — NO cell passes 3-check at any cost tier. Best cell
7d/0bps gross_t=+1.03 already below 1.96 (no escape from the 1.96 ceiling at
any cost). Per-window W5=+509.7% (kept discovery — directional overlay DOES
capture the late-cycle bull), W3=−46.8% (catastrophic chop-bear), W6=−4.6%
(chop). maxDD=−48.69% (over 30% budget). **Lesson #55**: directional sleeves can
have REAL alpha in some windows (W5=+509.7% beats R77's per-window lift) but
3-check requires CONSISTENT alpha across all windows. **Lesson #56 FINAL**:
the 731-day panel is bear-dominated for any single-strategy shape — even
directional with pre-confirmation filter. The trend filter works on a few
windows but the OOS window is in a regime the filter doesn't anticipate.

**File:** `src/research/validation/r92_two_layer_directional_overlay.py` (~430 LoC)
+ 13/13 smoke tests.

### R93 — Informativeness-Weighted Funding L/S (perp-only, per-asset conditioning) (Seth, 2026-07-26)
**Why tried:** Per R92 lesson #56 + user's pivot ("换全新结构轴" = switch to a
structurally-new axis), R93 is the SECOND structural-shape attempt (after
cross-sectional demean). Informativeness-conditioned funding-z = fade_sign ×
funding_z × ι[i,t] where ι captures how informative each asset's funding reading
is (persistent positioning → ι high; noisy chatter → ι low). Aggregate lesson
#14 ("fade the crowd is only right when the crowd is wrong") motivates:
downweight noisy funding readings so we only fade persistently-positioned crowd.
3 informativeness methods (sign_consistency [default], abs_autocorr, snr);
3 windows (14, 30, 60d); k=3 tercile L/S; perp-only single-instrument.

**Why failed:** 🔴 REFUTED — three independent failures:
1. **Anti-costume gate FAILED**: corr(R93_leg, naive_fade_leg) = +0.728 (gate
   < 0.60). Informativeness-weighting did NOT meaningfully diverge from naive
   per-asset-z fade. The cross-sectional signal is dominated by underlying
   funding-z; ι is too small a perturbation to move tercile assignments on this
   universe. **R93 collapses onto R60** (the refuted naive fade) with 73% correlation.
2. **3-check fails at every cell**: best cell 7d/iwin=60/5bps gross_t=+0.11,
   well below 1.96. ALL 120 cells fail 3-check. Cost-tier sweep confirms edge
   sign-flips from gross +0.47 (0bps) to gross −1.70 (30bps) — informativeness
   loses to naive fade at every realistic cost.
3. **Falsifiable mechanistic claim disproven**: R60 failed in W1 (−37.4%) and
   W3 (−22.5%). R93 was supposed to suppress those via ι. **R93 W1=−26.1%
   (still negative, less bad) and W3=−31.8% (STILL NEGATIVE, slightly WORSE).**
   Informativeness conditioning made W1 slightly less bad but did NOT turn it
   positive, and W3 actually got worse. Mechanism hypothesis disproven on this data.

**File:** `src/research/validation/r93_informativeness_weighted_funding.py`
(~520 LoC) + 10/10 smoke tests.

**Lesson #43 v5 (CONFIRMED, 8th case):** cross-sectional-demean family +
informativeness-conditioned family = BOTH exhausted on funding. The perp
panel's funding-as-edge has now been tested in **11 forms** (R47/R60/R62/
R76/R77/R89/R90/R91/R92/R93 plus R77's R76 leg). All REFUTED or structurally
subsumed. Informativeness-conditioning joins the graveyard as the second
structural shape (after cross-sectional demean) that fails.

**Lesson #56 v2 (FINAL, 11-attempt graveyard):** on the perp panel, neither
cross-sectional demean (R76) nor informativeness weighting (R93) nor regime-
gating (R62) nor perp-only carry (R90) nor perp-spot basis (R89) nor cross-
asset pair (R91) nor directional overlay (R92) can clear 3-check. The
cross-sectional funding-as-edge is dead on this panel. R77 multi-leg fusion
of regime-protected legs is the unique survivor. **The lever is panel length
(Minimax §OHLCV-EXTENSION), not strategy shape.** R93's W5=+59.5% lift is real
(same kept discovery as R90/R92) but the panel still doesn't have enough W1/
W3-class windows for the L/S to clear 3-check in aggregate.

**Why R93's anti-costume gate FAILED (structural reason):** on the perp
panel, the funding-z signal is highly cross-sectionally correlated (all 47
perps sample similar funding regimes). ι normalizes per-asset time-series
persistence, which is largely independent of the cross-sectional ranking. So
the top/bottom tercile picks are similar with or without ι → corr ~0.73.
**Informativeness weighting adds information on the ASSET dimension but the
cross-section L/S ignores that dimension.** This is the structural reason R93
fails as R60 in disguise.

---

## Path forward — JAZZ DECISION 2026-07-26

**✅ OPTION A CHOSEN** — wait for OHLCV extension (RECOMMENDED per analysis,
now formally adopted).

### Option A — DEFERRED, wait for longer panel (CHOSEN)

OHLCV is the binding constraint. Once Minimax extends the OHLCV back to
2015-2023 (per §OHLCV-EXTENSION), re-run R46 / R62 / R76 / R82 / R83 / R86
cadence × OOS sweeps on 11yr price data. The 11yr panel may surface a
2nd survivor that the bear-dominated 731-day window cannot.

**Why this is the right choice:**
- 9 attempts on the current 731-day panel have ALL failed at realistic cost
- The perp-funding family is exhausted on 3 distinct shapes + basis variant
- The OHLCV binding constraint is the lever (panel length), not strategy shape
- R77 ships as the only L/S strategy in the interim (production-ready today,
  maxDD=−8.91%, Sharpe=+2.06)

**Timeline:** depends on Minimax's §OHLCV-EXTENSION work. Not in scope for
Seth lane; flagged in MINIMAX_SYNC. Once 11yr data is available, re-run the
same R46/R62/R76/R82/R83/R86 candidate set on the extended panel and
re-evaluate the Strategy 2 slot.

### Option C — Accept single-strategy book (DEFERRED, not chosen)

If §OHLCV-EXTENSION takes too long and the question of "one vs two
strategies" becomes operationally urgent, ship R77 as the only L/S strategy.
Lower diversification, but production-ready today. Risk concentration is real
but bounded by R77's low maxDD (−8.91%) and high Sharpe (+2.06).

### Option D — Structurally different data class (DEFERRED, not chosen)

Build a Strategy 2 on a STRUCTURALLY DIFFERENT data source. Candidates that
have NOT been tested on the 11yr panel:
- Cross-asset bond-equity L/S (TradFi-RV)
- Structural-break vol (R75 maturity-dependent — only valid after 720h
  density gate)
- Cluster-rotation L/S — long underperformer within cluster, short outperformer
- Directional L/S with positive skew (not market-neutral) — §TRADER_TOM
  trend-overlay on a directional beta sleeve

**None of these are small additions** — they require new data feeds or
architecture changes (directional book = different risk profile).

---

## What this tells us about the doctrine

§TRADER_TOM_DOCTRINE calls for a two-layer book:
1. **Durable fundamental core** — never sold on short-term volatility
2. **Tactical trend-riding overlay** — gross scales with regime

R77 fusion cell is the durable core. The tactical overlay requires a
**directional** sleeve (long-beta, short-beta, or pair-spread), not a
market-neutral L/S. The four Strategy 2 candidates were all attempts at a
*second* market-neutral L/S — the wrong shape for the trend-overlay slot.

**Architectural insight:** the two-layer book needs orthogonal SHAPES (one
market-neutral factor book + one directional trend book), not two factor
books. Strategy 2 should be a DIRECTIONAL sleeve (long crypto in confirmed
risk-on trend, short or flat otherwise), not another cross-sectional L/S.

**R82 candidate → R88 directional sleeve (proposed):**
- LONG top-K quality + positive momentum in confirmed RISK_ON regime
- SHORT or FLAT in TIGHTENING / RISK_OFF / pre-confirmation
- Gross scales with regime band (per §TRADER_TOM)
- This is structurally different from any R77 leg AND matches the doctrine's
  trend-overlay description

**Out of scope for this round** (would need new architecture + new paper
book infra, not a 1-day validation). Defer to post-§OHLCV-EXTENSION.

---

## Files (all untracked, ready for Mac-side staging)

```
src/research/validation/r82_pillar_a_regime_gated.py              (NEW, ~290 LoC)
src/research/validation/r83_vol_risk_premia_ls.py                 (NEW, ~165 LoC)
src/research/validation/r85_r77_regime_gated.py                   (NEW, ~280 LoC)
src/research/validation/r86_r46_11yr_extended_oos.py              (NEW, ~165 LoC)
src/research/validation/r87_directional_trend_sleeve.py           (NEW, ~290 LoC)
src/research/validation/r88_pair_trading_sleeve.py                (NEW, ~310 LoC)
src/research/validation/r89_perp_spot_basis_sleeve.py             (NEW, ~480 LoC)
src/research/validation/r90_perp_funding_carry_held.py            (NEW, ~530 LoC)
src/research/validation/r91_cross_asset_funding_pair.py           (NEW, ~360 LoC)
src/research/validation/r92_two_layer_directional_overlay.py      (NEW, ~430 LoC)
src/research/validation/r93_informativeness_weighted_funding.py   (NEW, ~520 LoC)
src/research/validation/tests/test_r82_pillar_a_regime_gated_smoke.py   (NEW, 10/10)
src/research/validation/tests/test_r83_vol_risk_premia_ls_smoke.py      (NEW, 5/5)
src/research/validation/tests/test_r85_r77_regime_gated_smoke.py        (NEW, 10/10)
src/research/validation/tests/test_r86_r46_11yr_extended_oos_smoke.py   (NEW, 5/5)
src/research/validation/tests/test_r87_directional_trend_sleeve_smoke.py (NEW, 9/9)
src/research/validation/tests/test_r88_pair_trading_sleeve_smoke.py    (NEW, 8/8)
src/research/validation/tests/test_r89_perp_spot_basis_sleeve_smoke.py  (NEW, 8/8)
src/research/validation/tests/test_r90_perp_funding_carry_held_smoke.py (NEW, 12/12)
src/research/validation/tests/test_r91_cross_asset_funding_pair_smoke.py (NEW, 11/11)
src/research/validation/tests/test_r92_two_layer_directional_overlay_smoke.py (NEW, 13/13)
src/research/validation/tests/test_r93_informativeness_weighted_funding_smoke.py (NEW, 10/10)
src/research/validation/r95_panel.py                                  (NEW)
src/research/validation/r95_per_asset_tsmom.py                        (NEW)
src/research/validation/tests/test_r95_per_asset_tsmom_smoke.py       (NEW, 15/15)
src/research/validation/r96_panel.py                                  (NEW)
src/research/validation/r96_cross_asset_bond_equity.py                (NEW)
src/research/validation/tests/test_r96_cross_asset_bond_equity_smoke.py (NEW, 14/14)
```

(R84 was blocked by auto-mode classifier before being run; the file exists
but never produced a verdict.)

---

## References

- **R82 module**: `src/research/validation/r82_pillar_a_regime_gated.py`
- **R83 module**: `src/research/validation/r83_vol_risk_premia_ls.py`
- **R85 module**: `src/research/validation/r85_r77_regime_gated.py`
- **R86 module**: `src/research/validation/r86_r46_11yr_extended_oos.py`
- **R87 module**: `src/research/validation/r87_directional_trend_sleeve.py`
- **R88 module**: `src/research/validation/r88_pair_trading_sleeve.py`
- **R89 module**: `src/research/validation/r89_perp_spot_basis_sleeve.py`
- **R90 module**: `src/research/validation/r90_perp_funding_carry_held.py`
- **R91 module**: `src/research/validation/r91_cross_asset_funding_pair.py`
- **R92 module**: `src/research/validation/r92_two_layer_directional_overlay.py`
- **R93 module**: `src/research/validation/r93_informativeness_weighted_funding.py`
- **R96 module**: `src/research/validation/r96_cross_asset_bond_equity.py`
- **Strategy 1 spec**: `STRATEGY_PLAYBOOK.md`
- **§DATA-ALIGN pipeline**: `src/research/data_align/`
- **§TRADER_TOM_DOCTRINE**: `docs/TRADER_TOM_DOCTRINE.md`
- **R85 lesson (regime-gate double-count)**: `r85-r77-regime-gate-double-count.md`
- **S-82 lesson (regime-gross-scaling refuted)**: `r82-s82-regime-gross-overlay-refuted.md`
- **R92 lesson (directional overlay t-thin)**: `r92-two-layer-directional-overlay-refuted.md`
- **R93 lesson (informativeness collapse onto naive fade)**: `r93-informativeness-weighted-refuted.md`
- **§DATA-ALIGN pillar_A finding**: `reports/data_align/pillar_ic_mining_summary.md`

*Honest graveyard. The four REFUTED are the asset — they tell us exactly what
this panel cannot host, so the day the panel extends we know where to look.*