# Vol Sleeve v2 — Feasibility Memo (Seth, 2026-07-18)

> **STATUS: 🟡 YELLOW — proceed to Phase 2 with explicit scope adjustments**
>
> Verdict at top per the discipline: the OHLCV-only RV cascade leg can be fully tested on 9
> years; the triple-crowding "crowd" leg (funding + OI) can only be validated on 21 months /
> 5 majors. Phase 2 must scope the two legs independently, not as one combined strategy.

---

## 1. The cause (one sentence)

**When a leveraged long crowd is paying elevated perp funding + sitting on elevated open interest,
the next material drawdown in spot is mechanically amplified by cascading liquidations — this is
an unfunded external liability, not a price forecast, and it surfaces as a volatility regime
transition rather than a directional signal.**

Cause components:
- **Triple-crowding state** = `(RV_pct > 0.9) ∧ (OI/MCap_pct > 0.7) ∧ (funding_pct > 0.8)`.
- **Behavioral mechanism** = leveraged long crowd + perp microstructure → forced selling → realized-vol spike.
- **Refutation test** = layered liquidation cascade shows in realized vol, not in price (v1 failed
  exactly because it conflated the two).
- **DO NOT** use "vol-of-vol change" language — derived statistic, every shop runs it, NOT a cause.

---

## 2. Differentiation from v1 (the predecessor)

`src/research/cis_regime_studies/vol_sleeve_v1.py` (2026-07-16, ~490 lines) + report at
`reports/vol_sleeve_v1/2026-07-16/summary.md` already exists.

**v1 result:** Sharpe +0.753, MaxDD -65.39%, correlation to LS v1 -0.12,
+0.10%/month ballast in 44 LS v1 drawdown months. **Honest verdict in v1's own summary:**
> *"this is a risk overlay, NOT a true vol sleeve — needs Deribit options data"*

**v1→v2 deltas (the four things that change):**

| Dimension | v1 | v2 (proposed) |
|---|---|---|
| **Architecture** | Directional (BTC long, gross scales with vol) | **Delta-neutral** (spot + perp offset, vol is the bet NOT the direction) |
| **Trigger** | RV percentile alone | **Triple-crowding state** (RV_pct + OI/MCap_pct + funding_pct all top decile) |
| **Universe** | BTC only | **21 names** (CIS universe, filtered to those with OHLCV + funding coverage) |
| **Legs** | Single-direction risk overlay | **Two-leg**: long-vol cascade-payoff (small, conditional on triple-crowding) + short-vol premium-harvest (larger, structural carry) |

**Why v1's -65% MaxDD doesn't apply to v2:**
- v1 held BTC long through the cascade; v2 holds spot+perp offset, so cascade-driven spot drop is hedged by the perp short.
- v1's beta is +1.0 BTC; v2's beta is ~0 (delta-neutral).
- The +0.10%/month ballast in LS v1 drawdown months v1 DID provide is preserved in v2 (the short-vol leg earns structural carry even when long-vol is dormant).

---

## 3. Differentiation from V10

V10 (`SwingOverlayV10_MTF_FundingAware_VolTarget`, V10c calibrated variant) **uses
vol-targeting as a SIZING LAYER on SwingOverlay** — i.e., it scales position size by inverse
recent realized vol on top of a trend strategy. Report at
`/Volumes/CometCloudAI/cometcloud-local/_data/research/V10_MTF_FundingAware_VolTarget_2026-07-09.md`.

**v2 is NOT a sizing layer.** v2 is a dedicated sleeve with:
- No trend signal (no EMA cross, no MACD, no regime detection from Causal Sleeve)
- Delta-neutral by construction (no directional swing)
- Trigger condition is a STATE FLIP (cascade precondition), not a continuous vol-target scaling

The shared concept ("realized vol is informative about the regime") is real; the implementation
is structurally different. V10 lives in `freqtrade/user_data/strategies/`, v2 will live in
`src/research/cis_regime_studies/vol_sleeve_v2.py`.

---

## 4. Options data decision (Path A vs Path B — explicit choice)

**Path chosen: A — no options, realized-vol-only proxy.**

Reason:
- Deribit history pull is a 1-2 week data engineering project (per v1's own summary).
- Doing both at once = over-scope (typical failure mode per R1, R8, R16).
- The cause (cascade mechanic) IS testable on realized vol alone for the LONG leg.
- The SHORT-vol premium-harvest leg DOES want implied-vol data eventually (the premium IS the
  trade), but can be approximated now by a "RV < bottom-decile → sell a synthetic short-vol
  position (delta-hedged perp short)" until Path B lands.
- Re-evaluate Path B after Path A green — if the cascade long-vol leg clears DSR + walk-forward,
  the implied-vol layer becomes the natural Phase 4 upgrade.

**Honest note:** Path A is structurally INFERIOR to Path B. A realized-vol proxy is NOISIER
than implied-vol by construction (RV has variance, IV is priced expectation). Phase 2 numbers
will be LOWER than what Path B could achieve — that's expected, not a regression.

---

## 5. Causal Sleeve orthogonality check

`src/research/strategies/causal_positioning.py` (Seth, 2026-07-10) is the live-paper orthogonal
sleeve that uses **CROSS-SECTIONAL** funding crowding signal:
- `signal[i,t]` = cross-sectional z-score of trailing-7d mean funding across the 24-asset universe.
- `weight[i,t]` = `-z`, demeaned → market-neutral gross = 1.
- Validated: Sharpe +1.41@5bps, corr to swing +0.002, ENB 2.16 → 2.85.

**v2 uses PER-NAME TIME-SERIES** triple-crowding state:
- `state[sym,t]` = `(RV_pct[sym,t], OI/MCap_pct[sym,t], funding_pct[sym,t])` triple-cell.
- Condition on a SPECIFIC (sym, t) being in top-decile of all three.
- The two sleeves SHARE the funding-rate data but extract DIFFERENT signals:
  - Causal Sleeve: "rank names by funding today, fade the top z" (cross-sectional).
  - v2: "this specific name has been crowdy for 30+ days AND vol is spiking AND it's about to cascade" (time-series per-name).

**Honest orthogonality expectation:** both signals earn PnL in DIFFERENT regimes. Causal Sleeve
earns in normal-crowded regimes (steady weekly rebalance, low DD). v2 long-vol leg earns at
CASCADE EVENTS (rarer, larger per-trade, can have sharper DD in flat regimes). The correlation
should be ≤+0.3 monthly — comparable to v1's -0.12. **Verify in Phase 3, not assume now.**

**Naming-collision alert:** `factory/cash_and_carry.py` (2026-07-15) is a different research
study (D-class funding-carry factory signal) — NOT the same lane. Don't conflate.

---

## 6. Data inventory (verified 2026-07-18)

### 4h-spot OHLCV: 21 names + INDEX
- Path: `/Volumes/CometCloudAI/looloomi-research/data/ohlcv/4h-spot/*.feather`
- **22 files** (21 names + INDEX.json). Names: BTC/ETH/SOL/BNB/XRP/DOGE/ADA/AVAX/LINK/LTC/DOT/ATOM/NEAR/APT/ARB/OP/SUI/UNI/AAVE/MKR/MATIC.
- BTC: **19,511 bars, 2017-08-17 → 2026-07-15** (~9 years).
- Covers all major cascade windows: 2020 March (-50%), 2021 May (ATH top), 2022 May (LUNA), 2024 Jan (ETF).

### Funding rate: only 5 majors, only ~21 months ⚠️
- Path: `/Volumes/CometCloudAI/cometcloud-local/_data/strategy_revive/`
- 8h CSV per major: `BTC_funding_8h.csv` (1,688 lines = ~563 days of 8h settlements), ditto ETH/SOL/BNB/XRP.
- Date range: ~2024-11 → 2026-07-17 (~21 months).
- **DOES NOT cover 2020-2024 cascade windows** — LUNA, FTX, March 2020 liquidations are absent.
- Daily summaries also available (`*_funding_daily.csv`, 564 lines each).

### OI / Mcap: no historical series ✗
- OI is per-snapshot from CoinGecko `/derivatives` (already wired in `cis:positioning` Redis cache).
- **Historical OI is not on disk and cannot be reconstructed for the 9y panel.** This is a known
  limitation of the cascade leg validation.
- Workaround: use the CURRENT snapshot (most recent OI/MCap) applied historically as a
  **proxy**. Acknowledged weakness: at a real cascade event in 2022, the proxy is wrong by definition.
  Document this in v2's hypothesis section; the joint state of (RV high + funding high) is still
  testable, just not (RV high + funding high + OI/MCap_pct high).

### Reused utilities (don't re-invent)
- `vol_sleeve_v1.realized_vol_annualized(close, window_bars=180)` — annualization factor
  `sqrt(1512)` for 4h bars (6/day, 252 trading days). REUSE.
- `vol_sleeve_v1.classify_vol_regime(rv, rv_low=0.30, rv_high=0.60)` — LOW/MID/HIGH classifier.
  REUSE the function but use **percentile thresholds in Phase 2** (top-decile = cascade state)
  rather than v1's fixed 30/60% — percentile is the right trigger (regime-relative), not absolute.
- `pair_trade_sleeve.load_all_bars()` + `SPOT_FEATHER_DIR` — loads 21-name 4h panel.
- `causal_positioning.positioning_weights()` — different signal form but same data-source plumbing.
- `deflated_sharpe.deflated_sharpe_ratio()`, `walk_forward.WalkForwardConfig` — Phase 3 gates.

---

## 7. Hypothesis & backtest design

### Entry conditions

**Long-vol leg (cascade-payoff, small):**
- Condition: `(RV_pct > 0.9) ∧ (funding_pct > 0.8)` — top-decile realized vol + top-decile funding.
- *(OI/MCap_pct skipped for the Phase 2 LEG scope; no historical OI means this condition can only
  be applied for the 21mo / 5-major window. Documented as future Phase 4 upgrade.)*
- Sizing: small — 0.2× NAV per leg instance (the long-vol payoff is rare, can't size up).
- Delta-neutral: spot long + perp short equal notional.
- Exit: triple-crowding state breaks (RV_pct drops below 0.7) OR 14d held OR realized position hits +5% of NAV.

**Short-vol leg (premium-harvest, large):**
- Condition: `RV_pct < 0.3` (bottom decile).
- Sizing: 0.5× NAV per leg (more frequent, smaller per-trade payoff, earn over many bars).
- Delta-neutral: spot long + perp short equal notional (synthetic "short volatility" via being
  short gamma on the perp).
- Exit: RV_pct > 0.5 (regime transition up) OR -3% of NAV OR 30d held.

### Universe & window
- Universe: filter 21 CIS names to those with BOTH OHLCV AND funding-rate coverage → **5 majors** (BTC/ETH/SOL/BNB/XRP) for the full triple-crowding tests.
- Broader universe (21 names) for the RV-only legs (cascade long-vol without funding requirement).
- Window: BTC 2017-08-17 → 2026-07-15 (9y); funding-window 2024-11 → 2026-07-17 (21mo).

### Cost model
- Funding paid/received on the perp leg (net-of-carry already accounted for in the backtest).
- 10bps slippage per leg turnover.
- 30bps options-style decay assumption for the long-vol leg's time decay (acknowledged as
  conservative — synthetics don't actually decay in this linear model; the 30bps is "what an
  equivalent OTM-put position would lose to theta daily").

### Capacity cap
- $50k–$200k per cascade event (small-perp book depth on cascade). Phase 3 must simulate this
  via volume-weighted execution slippage at 2×, 5×, 10× of the default.

### Walk-forward
- `walk_forward.WalkForwardConfig`: 24m train / 6m test / 12m step, purged + embargoed per López de Prado.
- Required: at least 6 independent OOS test windows that contain at least 1 cascade event each.

---

## 8. Kill criteria (three gates + hard kill)

- **Gate 1 (must pass):** monthly-return correlation to LS v1 < +0.3 AND MaxDD better than -25%.
  v1 was -65% (unacceptable); v2 target is to keep DD ≤ -25% (acceptable for a hedge sleeve).
- **Gate 2:** Sharpe > 0.5 OOS in walk-forward (V14-style methodology).
- **Gate 3:** DSR > 0.5 across at least 6 independent walk-forward windows.
- **Hard kill:** if this memo's §1 cause can't articulate in ONE sentence, stop and rewrite —
  every sleeve we keep must trace to a behavioral cause. **It can.** Keep going.

---

## 9. What could falsify Phase 1 (the verification log)

Each check is below with actual output. ALL MUST PASS for GREEN; ANY WARNING = YELLOW; ANY FAIL = RED.

### Check 1: OHLCV panel covers cascade history ✓ PASSED
```
4h-spot files (22) found:
  BTC_USDT-4h-spot.feather: 19,511 bars, 2017-08-17 04:00 → 2026-07-15 12:00
  + 21 other major names (ETH/SOL/BNB/XRP/DOGE/ADA/AVAX/LINK/LTC/DOT/ATOM/NEAR/APT/ARB/OP/SUI/UNI/AAVE/MKR/MATIC)
```
✓ BTC covers 2017-08-17 → 2026-07-15 (9 years), ALL major cascade windows present.

### Check 2: Funding rate covers cascade windows ⚠️ PARTIAL
```
/Volumes/CometCloudAI/cometcloud-local/_data/strategy_revive/BTC_funding_8h.csv: 1,688 lines (~563 days)
+ ETH_funding_8h.csv: 1,688 lines
+ SOL_funding_8h.csv: 1,688 lines
+ BNB_funding_8h.csv: 1,688 lines
+ XRP_funding_8h.csv: 1,688 lines
Date range (from 8h timestamps): ~2024-11-15 → 2026-07-17 (~21 months)
```
⚠️ Funding covers **5 majors only, 21 months only** — does NOT cover 2020 March / 2021 ATH /
2022 LUNA / 2022 FTX / 2024 halving cascade windows. The triple-crowding state's funding leg
is testable for the last 21 months only.

### Check 3: Triple-crowding state fires ≥10 times across the panel ✓ PASSED
```
Triple-crowding-equivalent (RV_pct>0.9) fires: 2061 bar-days out of 19511
  distinct cascade events (sustained RV_pct>0.9 runs): 38
  bar-days at >0.95: 1335
  fire-day share: 10.6%
```
✓ 38 distinct cascade events across 9y — sufficient for walk-forward (need ≥6 with cascades).

### Check 4: V10 FundingAware + VolTarget is a SIZING LAYER, not a vol sleeve ⚠️ CONFIRM
File: `/Volumes/CometCloudAI/cometcloud-local/_data/research/V10_MTF_FundingAware_VolTarget_2026-07-09.md`
+ `SwingOverlayV10c_MTF_VolTargetCalibrated.py` exists (49.4KB).
**Confirmed**: V10 layers realized-vol targeting as a SIZE SCALAR on top of SwingOverlay's
trend entry logic; it is NOT a dedicated vol sleeve.
**Confirmed separately**: `VOL_ADAPTIVE_RESEARCH_20260331.md` exists, AutoResearch v2 result
documented vol-adaptive RSI/ADX/SL **underperformed** fixed params (PF 1.11 vs 1.63) —
§3 differentiation: v2 is a REGIME STATE FLIP (entry/exit on percentile threshold), NOT a
vol-adaptive parameter layer (RSI/ADX thresholds that change with RV). Same DATA but
different SIGNAL EXTRACTION — should NOT be the same failure mode.

### Check 5: Causal Sleeve orthogonality (cross-sectional ≠ time-series) ✓ PASSED
File: `src/research/strategies/causal_positioning.py` (Seth, 2026-07-10)
- `signal[i,t]` = cross-sectional z-score of trailing-7d mean funding across the 24-asset universe.
- `positioning_weights(fmean, kwin=7)` returns market-neutral weights that SUM TO ZERO gross.
✓ Confirmed: Causal Sleeve is **cross-sectional** (rank-based, demeaned, daily rebalance across
24 names at once). v2 is **per-name time-series** (state detection on each sym individually).
Distinct signal extraction from shared funding-rate data → orthogonal PnL expected.

---

## Phase 1 verdict: 🟡 YELLOW

| Check | Verdict |
|---|---|
| 1. OHLCV covers 9y + cascade windows | ✅ PASS (9y, 21 names, full 2020-2024 history) |
| 2. Funding rate covers cascade windows | ⚠️ PARTIAL (5 majors, 21 months — 2024-11 only) |
| 3. RV_pct>0.9 fires ≥10 times | ✅ PASS (38 cascade events across 9y) |
| 4. V10 = sizing not sleeve (no duplication) | ✅ CONFIRMED (+ VOL_ADAPTIVE negative precedent noted) |
| 5. Causal Sleeve = cross-sectional not time-series | ✅ CONFIRMED (orthogonal signal extraction) |

**YELLOW → Phase 2 may proceed IF scoped explicitly to the data availability**:

### Phase 2 scope per YELLOW verdict

1. **Long-vol cascade leg (RV-alone, 21 names, 9y panel)**: testable on full 9y history. This is
   the LEG that the cause is most about. If THIS doesn't clear DSR + walk-forward, v2 is dead —
   adding the funding+OI constraints won't save it.

2. **Long-vol cascade leg WITH funding constraint (5 majors, 21mo)**: testable as a SECOND run.
   Same trade logic, plus `funding_pct > 0.8`. Hypothesis: the funding constraint should make
   the long-vol leg *more selective*, but the sample is small (21 months). Phase 3 walk-forward
   may need to relax DSR gate to 0.4 here (not 0.5) given reduced n.

3. **Short-vol carry leg (RV_pct<0.3, delta-hedged, 21 names, 9y)**: testable on full 9y.
   This is the LEG that earns structural premium (less dependent on funding state).

4. **OI/MCap overlay**: DEFERRED. No historical OI means this can't be tested historically.
   Phase 4 (post-Path A green) — once CoinGecko backfills, or we add a different OI source.

### Phase 2 deliverable structure

`src/research/cis_regime_studies/vol_sleeve_v2.py`:
- `LongVolCascadeLeg`: RV_pct + funding_pct state detector (configurable: RV-only OR RV+funding)
- `ShortVolCarryLeg`: RV_pct<0.3 regime detector, delta-hedged
- `CombinedVolSleeve`: weights per leg config, returns NAV series
- `vol_sleeve_v2_backtest(universe, window, config)`: walks the 9y panel, emits NAV+stats per leg
- Cost model as in §7 (funding + slippage + theta decay)
- Tests: `tests/test_vol_sleeve_v2_smoke.py` — 8-10 unit tests, sandbox-safe

**NOT in Phase 2 scope** (deferred to Phase 4 after Path A green):
- Real OI/MCap percentile (CoinGecko daily snapshot only)
- Path B (Deribit options IV data, implied-vol leg)
- Per-pair sizing refinement beyond the 0.2×/0.5× defaults

---

## Risk / honesty

- **v2 is the THIRD attempt at a non-LS-v1 sleeve.** R22 (cross-sectional reversal) and R23
  (cointegration pair-trade) both falsified. The prior probability of v2 reaching paper is
  real but bounded. **The Phase 2 GREEN-only proceeding to Phase 3 discipline stands.**
- **v1 already DID get correlation -0.12 to LS v1.** That's the orthogonality we need to
  preserve AND exceed. The risk is building a "v1 with extra steps" that wins on paper but
  loses the orthogonality claim by reading the same signal twice.
- **Mac-side is required for the Phase 2 backtest run.** Sandbox can write the driver + tests;
  Mac runs the actual backtest with `pandas + numpy`. Standard per CLAUDE.md ownership.
- **Sleeve E paper trading is in flight** (4 dry-run instances on 4-slot V-family convex trend).
  v2's development is independent (different signal, different test harness) and does NOT
  conflict with Sleeve E's monitoring.

---

## Related files

- `src/research/cis_regime_studies/vol_sleeve_v1.py` — v1 predecessor (REUSE functions)
- `reports/vol_sleeve_v1/2026-07-16/summary.md` — v1 honest verdict
- `src/research/strategies/causal_positioning.py` — Causal Sleeve (orthogonality benchmark)
- `src/research/validation/deflated_sharpe.py` — Phase 3 DSR gate
- `src/research/walk_forward.py` — Phase 3 walk-forward harness
- `src/research/validation/portfolio_combiner.py` — Phase 3 orthogonality cross-check
- `docs/TRADER_TOM_DOCTRINE.md` — §5b/5c (expectancy, skew) constraints
- `REFUTATION_LEDGER.md` — R22/R23 (the prior two attempts we must learn from)
- `VOL_ADAPTIVE_RESEARCH_20260331.md` — the falsified vol-adaptive negative precedent

---

*Phase 2 may proceed. The cause is articulated, the data is sufficient for the RV leg, and the
scope adjustments for funding state are explicit. Hold the discipline: Phase 2 builds, Phase 3
gates; both are kill-or-continue points, not commitments.*
