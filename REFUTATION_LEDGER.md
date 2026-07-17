# Refutation Ledger — what we've disproven, and what it taught

> *Failures are more important than successes. A refuted hypothesis is permanent
> knowledge: it maps where not to dig and stops us paying to re-learn it. This is the
> graveyard, kept on purpose — the accumulated negative space that a real research loop
> compounds. Every killed idea gets an entry. Nothing is deleted; superseded entries are
> marked, not removed.*

**Rules:** an entry is added the moment a hypothesis is falsified, nulled, or found to be
a measurement error. Each carries the *number* that killed it (not a vibe) and the lesson
that generalizes. Before proposing a new test, grep this file — if it's here, don't re-run it.

Legend: 🔴 falsified · ⚪ null (no edge) · 🟡 conditional (works only under a constraint) · 🔵 false alarm

---

## R1 🔴 Empirical edge-map direction generalizes (the "edge gate")
- **Hypothesis:** the tier×band alpha grid's IC-derived *direction* predicts forward returns OOS.
- **Test:** walk-forward OOS, BH-FDR, net of costs (Minimax-A A2, commit 0e868a7).
- **Result:** loses in BOTH windows across ALL 4 dirs; 4 straight longs into a falling BTC (−$479) while the frozen `REGIME_CIS_FLOOR` baseline made money (+0.59 Sharpe, PF 1.38). p=0.867 — null not rejected.
- **Lesson:** an in-sample IC grid is a description, not a predictor. Cleverness overfit; the humble quality gate survived. Anything anchoring on this direction is presumed overfit until it passes the same harness.
- **Fallout:** `conviction_book` (same anchor) quarantined; paper sleeve reverted to risk-meter.

## R2 ⚪ Price/TA meta-labeling lifts the swing lineage
- **Hypothesis:** a secondary model on entry features (direction, leverage, hour, weekday, pair) improves SwingOverlayV7's trade selection.
- **Test:** logistic meta-label, IS-train / OOS-measure, chronological split.
- **Result:** null — OOS Sharpe/trade 0.272 → 0.274; it just cut 37% of trades for no per-trade gain.
- **Lesson:** the swing system is already efficient on price data. You cannot squeeze more alpha from the same MACD/RSI/ATR signal — improvement must come from an *orthogonal* input, not re-labeling the same one.

## R3 ⚪ Naive ensembling beats the best single strategy
- **Hypothesis:** equal-weight / inverse-vol blending the positive strategies raises risk-adjusted return.
- **Test:** blend vs best single on daily returns.
- **Result:** worse — blended ann Sharpe 2.8 vs V7 alone 4.0. Dilution by weak sleeves.
- **Lesson:** blending correlated/uneven strategies destroys value. Combination only helps with *orthogonality*, and weighting must respect it (→ R4).

## R4 🟡 More strategies = more diversification
- **Hypothesis:** our 5 DSR-certified strategies are 5 independent bets.
- **Test:** correlation matrix + effective number of bets (ENB).
- **Result:** mean mutual corr 0.67 (V8/V9/V10 = 0.95–1.00); ENB = 2.16. Five strategies ≈ ~1.5 ideas.
- **Lesson:** the certified arsenal is one idea in five costumes. The next unit of Sharpe comes from ONE uncorrelated sleeve, not a sixth swing variant. Conditional truth: diversification is real only when correlation is measured, not counted.

## R5 🔴 Directional CIS momentum bots beat buy-and-hold
- **Hypothesis:** LS_V4 / META_V4 (CIS-gated directional) are deployable alpha.
- **Test:** freqtrade backtest vs BTC-hold.
- **Result:** CAGR −6.59% / −5.47% vs BTC-hold +24–26%. Lose.
- **Lesson:** the crowded directional lane is ~zero-edge for everyone; don't tune the losers. Keep one representative (`REGIME_CIS_FLOOR`) as a filter, not as alpha.

## R6 🔴 Trend-following captures the parabolic winner (HYPE)
- **Hypothesis:** a mechanical trend rule rides the HYPE-type move.
- **Test:** trend rule on HYPE vs buy-and-hold.
- **Result:** +37% vs buy-and-hold +110% — the stop chopped us out of the exact asset we most wanted to hold.
- **Lesson:** on a genuine value/narrative winner, the alpha is *selection + conviction hold*, not trend micro-management. Trend times entry and avoids catastrophe; it must not dictate exit on a thesis-intact winner. (→ CONVICTION_METHODOLOGY.md)

## R7 🟡 Expanding the causal sleeve's universe adds edge
- **Hypothesis:** widening funding-crowding from 24 → 50 perps improves it (more breadth = finer signal).
- **Test:** re-run backtest, 24 vs established-40 vs all-50, masked for listing dates.
- **Result:** 24 majors +1.34 Sharpe / 10% DD; established-40 +1.07 / 16%; all-50 **+0.12 / 30%**.
- **Lesson:** funding-crowding is a LARGE-CAP phenomenon — on thin/new names funding is noise and swamps the signal. Expand for capacity behind a liquidity gate, never indiscriminately. (Signal-specific: the conviction/right-tail sleeve is the opposite — it lives in the small/new names.)

## R8 ⚪ Funding acceleration improves the positioning sleeve
- **Hypothesis:** adding funding *acceleration* to funding *level* sharpens the crowd-fade.
- **Test:** blended signal, accel weight 0 → 1.0, on the 24 majors.
- **Result:** monotonic degradation — 1.34 → 1.23 → 1.09 → 0.76.
- **Lesson:** the level IS the signal; acceleration is noise. Don't add a second term to a clean signal without an OOS reason.

## R9 🔵 "Upstream causes are empty on Railway" (false alarm)
- **Hypothesis (mine, wrong):** the cause caches weren't populating in prod (fs/pos = 0 for all assets).
- **Test:** re-probed the live universe payload, correct fields.
- **Result:** false alarm — the causes ARE live; the data is NESTED (`forward_supply:{...}`), I'd read a flat field. ONDO fs_risk=0.702, pos=−0.405.
- **Lesson:** verify the *schema* before declaring a break; a measurement bug in the checker looks identical to a system break. Built `/internal/loop-health` (reading correct fields) so this class of error can't recur silently. Retracted the P1 I'd filed to Minimax.

## R10 🔵 "The narrative engine is wired and working"
- **Hypothesis (implicit):** NMA was a live, functioning signal.
- **Test:** actually ran `compute_narrative_signal`.
- **Result:** it output a degenerate ~44 NEUTRAL for everything — CG killed `community_data` (social=35 fallback), orderflow hit spot endpoints that 400 on perps, trend was pytrends-429-flat. Orphaned: never fed the S-pillar, never surfaced.
- **Lesson:** "referenced in the code" ≠ "flowing." An endpoint can return fallback constants for months and look alive. Now repaired (all 3 sources real) + the loop-health probe guards it.

## R11 🔵 "The narrative trend/orderflow fix works" (worked in sandbox, flat in prod)
- **Hypothesis (mine):** rerouting NMA trend + orderflow to Binance (fapi) repaired them.
- **Test:** post-push live check of `/api/v1/market/narrative`.
- **Result:** flat 50 in prod (social differentiated, trend+orderflow not) — Binance is GEO-BLOCKED on Railway US; the fix worked only in the sandbox's egress. Rerouted both to CoinGecko (Railway-safe) → differentiated.
- **Lesson:** "works in sandbox" ≠ "works on Railway" for ANY Binance-sourced signal. Verify data-source reachability in the TARGET environment, not just locally. CoinGecko is the Railway-safe primary. Same family as R9/R10 — the check is the product.
- **Update 2026-07-13:** The specific Binance geo-block instance is **RESOLVED** — sandbox curl `https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT&limit=2` returns HTTP 200 in 0.44s (verified by Seth); Mac SG has always been reachable. NMA pipeline **stays CG-primary, Binance-fallback** (do NOT revert the post-push reroute — the disciplined choice is keeping the redundancy; flipping primary mid-stream risks reintroducing the original failure mode). 顶格 RWA monitor (commit 41dec72) now uses live Binance data successfully. V12 per-bar funding work unblocked — pulls fapi /fundingRate directly. **The lesson generalizes permanently even though this specific instance closed**: every new data source still needs a TARGET-environment reachability test before claim.

## R12 🔴 Price-based sector valuation-rotation works in crypto (the naive 韭圈儿 port)
- **Hypothesis:** 韭圈儿's sector value-rotation (overweight cold / underweight hot by valuation percentile) ports to crypto using a price-vs-trailing-mean temperature.
- **Test:** 8 crypto sectors, weekly rotation, net of costs.
- **Result:** fails — long-short Sharpe +0.04, long-only cold-tilt −0.16 / −25% / 109% DD (cheap kept falling).
- **Lesson:** A-share value-rotation works because EARNINGS anchor price (PE/PB mean-revert). Crypto has no earnings floor, so a price-cheap signal is momentum-reversion = value trap. The template needs a REAL fundamental temperature (MVRV-Z / mcap-TVL / mcap-fees) AND catalyst+trend gating (CONVICTION L2/L4) — value alone is a trap (see R6). Report: `reports/SECTOR_VALUATION_2026-07-11.md`.

## R13 🔴 H3.2 conviction-sizing transfers from Nautilus LS v1 to swing overlay
- **Hypothesis:** the H3.2 sizing pattern (`trade_size × (0.5 + c) ∈ [0.5, 1.5]×`, c ∈ [0,1] conviction) — winner on LS v1 (+$1.79 to +$2.14 per-trade IS, +$0.10 to +$2.25 OOS across all 8 A/B runs) — adds edge when applied to swing overlay entries (V11: per-pair trailing-7-day funding z-score → direction-aware sizing multiplier).
- **Test:** V11 = clean A/B on V9 (only positioning sizing added). Walk-forward 3 windows (TRAIN 2024 bull / VALIDATE 2025 chop / HOLD-OUT 2026 recovery) × 2 variants (5-pair + ETH-only) = 6 backtests.
- **Result:** loses. V11 5-pair +2,774.6 USDT vs V9 +3,169.8 (-12.5% P&L), trades 1,211 vs 1,297 (-6.6%). V11-ETH +1,311.1 vs V9-ETH +1,421.2 (-7.7%), trades flat. Three forces: (1) avg-stake effect (-5% to -7% stake × similar trades = mechanical loss); (2) z-score distribution biased by market microstructure (crypto funding is structurally positive → longs μ_z ≈ +1.27-1.41, shorts μ_z ≈ -2.20-2.27, BOTH sides get shrunk on average; "fade the crowd" becomes permanent downsize); (3) **mechanism mismatch** — H3.2 works in CROSS-SECTIONAL books where conviction = which name to overweight; in PER-PAIR swing entries, conviction = how much to size, and swing's regime-stake (900/600/400) + naked-short (×1.5) system already does similar work, so the two conviction layers stack non-additively.
- **Lesson:** **NOT a falsification of H3.2** — H3.2 still wins on LS v1 (its native habitat) and was bumped cap 1.5→1.75 same-day. It IS a **boundary finding**: an LS-v1-native pattern doesn't necessarily transfer to directional swing. A proven pattern on one strategy family is not portable to another without its native data shape (cross-sectional, not per-pair) and without checking what the target family already does for conviction. Builds on R4 (orthogonality math): another swing variant, even with an orthogonal signal, doesn't beat V9 because swing's existing sizing absorbs the new signal. V12 direction = CROSS-SECTIONAL positioning z (Causal Sleeve native form) — the right port of the signal to test next. **Carrier note:** V11 retained for archival + as documented counter-example. Report: `_data/research/V11_CausalSized_2026-07-10.md`.

## R14 🔴 "Gated fee-value is validated" (single-split artifact — walk-forward refuted)
- **Hypothesis:** gating fee-value by momentum (value+catalyst) beats value alone OOS — I claimed it validated on a single 60/40 split (gated OOS +0.75 vs value +0.31).
- **Test:** 7 rolling 180-day walk-forward folds.
- **Result:** gated positive only 3/7 folds, mean +0.24, FULL +0.06 — *worse* than value-alone +0.56. The single-split win was a lucky 2025–26 cut.
- **Lesson:** ONE OOS split is NOT validation — walk-forward across multiple folds is the bar. Same failure mode as R1 (edge gate): I got enthusiastic about a number; the loop caught it. Also: value+catalyst is NOT proven by this fee-value implementation (still a hypothesis). Report/data: fee_value_gated_momentum_20260711 (experiment_runs).

## R15 🔴 Funding gate adds edge when it fires — IT DOESN'T (per-pair on swing)
- **Hypothesis:** P1 ground-truth (funding sign MIXED 5/12 in regime-conditional way — positive funding bearish ONLY in bull, negative bullish in bear) implies the regime-conditional funding gate (`bull & fr>3bps → block long`; `bear & fr<-3bps → block short`) filters anti-edge trades. V10's gate was unit-tested but INERT in backtest (CIS funding cache returns 0); V12 = V10 + per-bar funding table — finally tests the gate's actual effect.
- **Test:** V12 = V10 clone with `dataframe["_fr_bps"]` column (vectorised per-bar lookup) + `_v12_fr_for(symbol, current_time)` per-call helper. Walk-forward 3 windows × 2 variants (5-pair + ETH) = 6 backtests. Funding table: 4,260 obs × 5 pairs from fapi /fundingRate.
- **Result:** the gate fires ~29 times over 3 windows × 5 pairs (almost all bull + fr>3bps on BTC/SOL/ETH/XRP longs). V12 5-pair = +2,554.2 vs V9 +3,169.8 (-19.4% P&L). **Clean A/B V12 vs V10 (gate inert): -0.7% P&L on -2.4% trades** — the gate filters net-profitable trades. ETH-only shows the gate essentially never fires (ETH rarely in pure bull/bear + ETH funding rarely crosses ±3bps at daily-mean level), so V12-ETH ≈ V9-ETH.
- **Lesson:** P1 ground-truth was correct as a *descriptive* finding (funding sign IS regime-conditional in a 5/12 MIXED sense) but it is NOT a *trading* signal. Crowded longs in a bull market are still on the right side of the trend — funding elevated ≠ trade anti-edge. **The gate's trades are on average net profitable because they coincide with bull-regime RSI<35 pullbacks, which historically work**. Three falsifying findings in a row on per-pair overlays: (R13 H3.2 conviction-sizing, R15 funding gate, plus V10's vol-target from the previous report) — all per-pair signal layers on swing net negative. The Causal Sleeve remains the orthogonal answer because its signal is CROSS-SECTIONAL (fade the crowd across the universe), not per-pair. **Build rule for swing overlays: don't propose per-pair filters without explicit cross-validation.** Report: `_data/research/V12_FundingGateWired_2026-07-13.md`.

## R16 🔴 H2a direction table applied to LS v1 absolute-direction gate — STRONG NEGATIVE (cross-sectional ≠ absolute)
- **Hypothesis:** H2a (genuine reversal in 3/5 regimes at 7d, IC_rel = −0.10 to −0.33 — `reports/H2A_RELATIVE_IC_2026-07-10.md`) implies the LS v1 Nautilus gate should flip per-regime direction: Risk-Off / Risk-On / Stagflation → `inverted` (require CIS ≤ floor) so we trade the reversal. The H2b driver (`src/research/cis_regime_studies/h2b_regime_direction_ab.py`) wired this via `LSV1_USE_H2_DIRECTION=1` + `DEFAULT_PER_REGIME_DIRECTION_H2A` and ran the full A/B.
- **Test:** 4 variants × {IS 2025-05-03→2025-12-31, OOS 2026-01-01→2026-03-12} × 3 instruments (BTC/ETH/SOL) = 8 unique Nautilus backtests via `common/nautilus_runner.run_with_config`. Walk-forward windows mirror the freqtrade LS V4 baseline + H2 sweep.
- **Result (per-variant summary, `reports/h2b_regime_direction/2026-07-13/comparison.json`):**

  | variant | H2a dir | H3.2 sizing | IS PnL | OOS PnL | OOS orders |
  |---|:---:|:---:|---:|---:|---:|
  | `A_baseline` (current prod) | · | · | **+$293.50** | **+$39.92** | 13 |
  | `B_h2a_direction` | ✓ | · | **−$663.11** | **−$489.54** | 105 |
  | `C_baseline + H3.2 sizing` | · | ✓ | +$510.31 | +$69.44 | 13 |
  | `D_h2a + H3.2` | ✓ | ✓ | −$1,153.88 | −$851.72 | 105 |

  Δ B vs A: **−$957 IS / −$529 OOS** (−1326% OOS). Δ D vs A: −$1,447 IS / −$892 OOS. H2a + H3.2 **stacks NEGATIVELY** (H3.2 sizes up the falling-asset trades). H3.2 alone (Variant C) is +$217 IS / +$30 OOS — ship as opt-in. **STOP RULE TRIGGERED** (Direction flip hurts OOS by > 25% on reversal regimes → revert, don't ship).

- **Mechanism (why the flip fails):** H2a's IC is **cross-sectional** (BTC-relative Spearman: "high-CIS names have *worse* BTC-relative returns in Risk-Off/Risk-On/Stagflation"). LS v1's `_cis_passes` is an **absolute-direction eligibility filter** — it gates BOTH long AND short entries with the same CIS threshold. With `direction=inverted` in Risk-Off (the dominant OOS regime), the gate lets through ETH/SOL (CIS often < 50) and the EMA cross + ADX then opens positions on these FALLING assets. Trade count: 13 → 105 (8× more activity). PnL: +$40 → −$490 (12× worse per dollar of activity). The H2a *relative* signal is real; inverting the *absolute* eligibility does not invert the trade direction, so the strategy enters against the prevailing trend.

- **Lesson:** **Signal type must match the gate's role.** Cross-sectional reversal signals (rank X above Y in this regime) need cross-sectional implementations: (a) market-neutral pair-trade (long X / short Y), (b) two-floor ranking (lower long-floor, raise short-floor), or (c) cross-sectional gross scale. They do NOT invert a single-floor absolute-direction eligibility gate on a per-pair directional strategy. LS v1's gate is the third row (eligibility for either side); H2a maps cleanly to the second row (V4's long + short floor tables). **The architecture matters as much as the alpha.** Apply H2a to SwingOverlay (V4, Minimax-C Phase D1), the causal-positioning sleeve (already shipped 2026-07-10, OOS Sharpe +1.0), or a future pair-trade sleeve — NOT to LS v1's gate.

- **Fallout:**
  1. ❌ Do NOT ship `use_h2_direction` to LS v1 production. The flag + `DEFAULT_PER_REGIME_DIRECTION_H2A` table stay in `src/research/nautilus/ls_v1/strategy.py` (lines 98–116, 220–222, 561–601) for future V4-style reuse, but the env var `LSV1_USE_H2_DIRECTION` defaults to `0`.
  2. ✅ H3.2 sizing alone (Variant C) is POSITIVE — +$510 IS / +$69 OOS / no Sharpe penalty. Ship as opt-in via `LSV1_USE_H32_SIZING=1` (already shipped 2026-07-10, cap bumped 1.5→1.75 same-day per `H32_SIZING_FLOORCAP_SWEEP_2026-07-10.md`).
  3. 📍 Phase A (H2b direction A/B) → CLOSED. Pivot to **Phase B (empirical-grid edge gate)** which is data-grounded and does NOT depend on H2a direction.
  4. 📍 Elevate **Phase D1 (V4 SwingOverlay walk-forward OOS)** — V4's two-floor architecture is the natural H2a home. Minimax-C's lane.

- **Carrier note:** Strategy.py retains the H2a wiring as dormant config (cheap to keep; useful when V4-style rank-then-flip is needed). H2b driver + report retained for archival + as the canonical cross-sectional-vs-absolute counter-example. Full data: `reports/H2B_REGIME_DIRECTION_2026-07-13.md` + `reports/h2b_regime_direction/2026-07-13/{summary.json,comparison.json,full_results.json,raw/}`.

---

## R17 🟡 Empirical-grid edge gate + size_multiplier — MIXED (hold for smoothed-CIS re-run)
- **Hypothesis:** the empirical-Bayes shrunk-alpha grid (K=184.5, 4 tiers × 5 risk bands = 19 cells, exported from a 40-asset backfill) is a data-grounded replacement for `REGIME_CIS_FLOOR`. The direction falls out of the data (LONG allowed when grid edge ≥ +1%, SHORT when ≤ -1%; otherwise blocked). A size_multiplier scales `trade_size` by per-cell conviction ∈ [0.4, 1.3]. Phase B sweep wired this into LS v1 and ran a 3-variant A/B (`src/research/cis_regime_studies/empirical_grid_gate_ab.py`).
- **Test:** 3 variants × {IS 2025-05-03→2025-12-31, OOS 2026-01-01→2026-03-12} × 3 instruments = 6 Nautilus backtests. Variants:
  - A_baseline (REGIME_CIS_FLOOR, current prod)
  - B_grid_gate_only (grid gate, no size scaling)
  - C_grid_gate_plus_size (grid gate + size_multiplier — the ship target)
- **Result (`reports/empirical_grid_gate/2026-07-15/comparison.json`):**

  | variant | grid gate | grid size | IS PnL | OOS PnL | OOS orders |
  |---|:---:|:---:|---:|---:|---:|
  | `A_baseline` | · | · | **+$293.50** | +$39.92 | 13 |
  | `B_grid_gate_only` | ✓ | · | -$151.53 | +$15.96 | 62 |
  | `C_grid_gate_plus_size` | ✓ | ✓ | -$60.43 | **+$54.14** | 62 |

  Δ C vs A: **IS -$354, OOS +$14 (+35.6%)**. Δ C vs B (size multiplier marginal): IS +$91 (+60.1%), OOS +$38 (+239.2%). Per-trade: trade count same (62 OOS for B & C), but `size_multiplier` shrinks avg_loss from -$25.40 → -$22.01 OOS and avg_win $49.44 → $48.61 OOS, PF 1.05 → 1.19. **The size_multiplier is a real architectural win; the grid as a signal source is too sparse for current CIS noise.**

- **Why MIXED, not green-light:**
  1. IS regression -$354 too large to ship (pass criterion: Δ ≥ +$100).
  2. OOS wins +$14 / +35.6% — real but small.
  3. Stop rules NOT triggered: OOS improvement is real, PF improves, no instrument-level flip > -50%.
  4. BTC IS crashes -$440 (B) or -$346 (C) — gate fires more entries in Risk-Off bands where grid says edge is large (positive or negative), exposing BTC to noise the smooth-floor regime table didn't.

- **Mechanism (what's working, what's not):**
  - ✅ `size_multiplier` lever validates: shrinks weak-edge entries (e.g. NEUTRAL × 3_neutral → 0.4× size) and concentrates capital on strong-edge entries (OUTPERFORM × 5_deep_on → 1.088×). This is Millennium soft sizing with a different signal source.
  - ✅ Grid direction falls out of data: `OUTPERFORM × 5_deep_on` → LONG allowed, SHORT blocked; `OUTPERFORM × 1_deep_off` → LONG blocked, SHORT allowed.
  - ❌ Grid is sparse (19 cells, all K=184.5-shrunk toward -2.962% mean); no cell has >10 raw observations. One bad cell vetoes many trades.
  - ❌ CIS history smoothing (Phase 1 ship, Minimax's queue) is pending — currently the gate uses raw labels, which flip OUTPERFORM↔NEUTRAL day-to-day.

- **Lesson:** **Sparse grids need smoothed inputs.** A K=184.5 shrinkage buys us calibration against noise but not against a noisy per-day tier assignment. When the input is noisy enough that NEUTRAL flips 30% of the time, even a correctly shrunk grid has 30% of its cells in the "no data" fall-through (conv=0.0, size=floor=0.4). Re-run with smoothed CIS labels — that's the experiment that decides ship/no-ship. **The architectural pattern (gate + size_multiplier) is validated; the specific signal source (raw grid) is not.** This is the inverse of R16's lesson: R16 said *cross-sectional needs a cross-sectional implementation*; R17 says *a calibrated gate needs a calibrated input*.

- **Fallout:**
  1. ❌ Do NOT ship Variant B (grid gate only) — IS -$445, OOS -$24.
  2. ❌ Do NOT ship Variant C in its current form — wait for smoothed-CIS re-run.
  3. ✅ Ship H3.2 sizing instead (already shipped 2026-07-10, R16 fallout item 2) — same architectural pattern, different signal source, cleaner data.
  4. 📍 Phase B → **HOLD.** Re-run with `--cis-history-dir /Volumes/CometCloudAI/cometcloud-local/_data/cis_history_smoothed/` once Phase 1 ship lands.
  5. 📍 Phase C (B + H3.2 stacked) → **DEPRECATED.** Variant C IS the size_multiplier over the grid — stacking H3.2 on top would be redundant.
  6. 📍 Elevate **Phase D1 (V4 SwingOverlay walk-forward OOS)** — V4's two-floor ranking is the natural home for cross-sectional H2a + the empirical grid's directional signal.

- **Carrier note:** Strategy.py retains the empirical-grid wire-up (`use_empirical_grid_gate`, `use_grid_size_multiplier`, `grid_path`, `band_snapshot_path`, `grid_size_floor`, `grid_size_cap`) — all default OFF. The empirical-grid module (`src/research/strategies/edge_gate.py`) is structurally correct and the size_multiplier lever is reusable for any future signal source we plug in. R17 driver + report retained for archival. Full data: `reports/PHASE_B_EMPIRICAL_GRID_GATE_2026-07-14.md` + `reports/empirical_grid_gate/2026-07-15/{summary.md,comparison.json,full_results.json,raw/}`.

---

## R18 🔴 Forward-supply is a tradeable EDGE at the unlock event — IT'S PRICED IN (scheduled cause)
- **Hypothesis:** the forced-seller cause (`forward_supply.py`, traded as bearish; moat claim = "beta+ from proximity to the cause") is tradeable at its cleanest instance — a large token cliff-unlock. H: token underperforms BTC in the 30d AFTER the unlock.
- **Test:** event study, 11 curated 2024–25 cliff unlocks (TIA 82%, ENA 66%, ALT 42%, STRK 8.8%, + moderate ARB/APT/STRK/MANTA), real Binance daily prices, 30d benchmark-relative alpha, **controlled** by each token's own non-event window (t−60→t−30). `src/research/cis_regime_studies/unlock_event_study.py`; report `reports/UNLOCK_EVENT_STUDY_2026-07-15.md`.
- **Result:** raw event α = −9.75% mean / 82% negative (looks confirmed) but **confounded** — these alts bleed vs BTC in adjacent windows too. **Control-adjusted effect = +15.8% mean, 9/10 positive, sign-test p=0.021**: unlock windows are *significantly better* than baseline. Runs the wrong way with magnitude — the biggest unlocks show the biggest relief (TIA 82%→+34.7%, ENA 66%→effect +46%). Textbook "sell the rumor, buy the news."
- **Lesson:** a **scheduled, publicly-known cause is priced in; proximity to it is not an edge.** The forced-supply mark-down happens *before* the calendar date; the post-event window carries a relief bid. If forward-supply has tradeable alpha it lives in the *surprise* (emergency/foundation sells, unexpected supply), never the schedule. **Survives** only as a descriptor / quality-risk filter (high-overhang names are weak vs BTC in general — how CIS already uses it), NOT as event-timing alpha. Directly weakens the strongest moat claim; sharpens it: trade the surprise, not the schedule.

## R19 🔴 Mining-cost / miner-economics is a tradeable forward-return edge — DECAYED OOS (published cost-basis)
- **Hypothesis (Jazz's anchor):** production economics are an upstream cause — miner stress (low Puell Multiple, or price near difficulty-implied production cost) predicts elevated forward returns (capitulation → bottom).
- **Test:** BTC 2017–2026 (3,255 days), real Binance + blockchain.com difficulty. Puell = issuance-USD / 365d MA; difficulty cost proxy = price/(difficulty/reward) trend-normalised. Spearman IC + quintile buckets + IS(pre-2022)/OOS(2022+) split. `src/research/cis_regime_studies/mining_cost_study.py`; report `reports/MINING_COST_STUDY_2026-07-15.md`.
- **Result:** Puell 180d **in-sample** is textbook (low-Puell Q1 +89.8%/80% win → high-Puell Q5 +6.3%/43% win, IC_IS −0.58) but **OOS IC = −0.02 (gone)**; 90d flips sign IS→OOS. Difficulty proxy IC is *positive* (momentum), and price-near-cost is the WORST short-term bucket (−3.6%) — refutes "buy near mining cost."
- **Lesson:** a **published cost-basis indicator is a cycle *descriptor*, not a live edge.** Two failure modes stacked: (1) it's consensus → priced in (R1/R18 again); (2) its in-sample IC rides on only ~2–3 independent cycle bottoms in all of BTC history (huge daily n, tiny effective-n) → not certifiable. **Survives** only as a slow gross-scale context ("where are we in the miner cycle"), never as timing or cross-sectional alpha. Tradeable production-economics alpha would need the *surprise* (unabsorbed hashrate/cost shock), not the published multiple. Cheap-to-produce keeps getting cheaper without a catalyst (R6/R12).

## R20 🔴 Style/factor rotation beats a static multi-strategy blend — IT DOESN'T (static wins OOS)
- **Hypothesis (Jazz's direction):** rotating strategy weights across the style cycle (风格周期) — factor momentum and/or regime-conditional tilts — beats a static diversified blend.
- **Test:** 17 factory signals × 24 majors, 748d, walk-forward OOS. `src/research/factory/style_rotation_study.py`; report `reports/ROTATION_STUDY_2026-07-15.md`.
- **Result:** static 0.78 = momentum-rotation 0.78 (dead tie) ; regime-rotation **0.29** (much worse OOS). The style cycle is REAL in-sample (BAB/defensive own calm+stormy, positioning-funding peaks mid-vol, factor-momentum IC +0.076) but not profitably timeable — per-regime Sharpe is estimated on a handful of episodes and the regime label lags. Asness et al. "Contrarian Factor Timing is Deceptively Difficult" confirmed on our data; the "smarter" regime version is the more dangerous one.
- **Also found (structural):** effective breadth — assets 4.74 of 24 (all correlate to BTC), strategies 6.74 of 17. **In crypto the diversification is on the STRATEGY axis, not the asset axis.**
- **Lesson:** don't build a rotation overlay (felt sophisticated, loses money) — static diversification IS the edge (= the combined_book, OOS 1.05). Push breadth via more independent STRATEGIES, not more correlated assets. The regime map's only honest use is RISK (scale gross down in stormy), never rotating for alpha.

## R21 🔴 LS v1 baseline is stable as a $10M FoF — IT ISN'T (9-year rolling OOS proves fragility)
- **Hypothesis (the unspoken assumption behind Phase B):** the LS v1 tech-only baseline (EMA9/21 cross + ADX25 + ATR bracket, CIS gate disabled) earns a stable enough return stream to carry a single-strategy fund. The Phase B empirical-grid gate was being tested as an *improvement* on top of an already-acceptable foundation.
- **Test:** rolling walk-forward OOS, **43 windows × 70 days each**, IS=240d / OOS=70d, 9-year Binance spot 4h bars (BTC/ETH: 2017-08 → 2026-07; SOL: 2020-08 → 2026-07), tech-only baseline (`LSV1_ENABLE_CIS_GATE=0`, all gates "high"). Driver: `src/research/cis_regime_studies/multi_window_baseline.py`; sweep outputs `reports/multi_window_baseline_spot_cis_off/2026-07-16/`. Full report `reports/MULTIWINDOW_BASELINE_2026-07-16.md`.
- **Result:** *symmetric distribution with fat tails, not a positive-bias Sharpe stream.*
  - Win rate **55.8%** (24/43), median P&L **+$54.81**, mean **+$77.90**, **stdev $527.96**, CV **6.78**.
  - Best window **+$1,252.70**, worst **−$1,213.71** (single-window DD matches 1.5 months of median earnings).
  - Per-regime: 2025 mega-trend +$4,919 (5 windows × ~$1k), 2022 LUNA −$2,957 (5 windows × ~$−590), 2021 ATH → correction −$1,606 (2 windows).
  - **Net +$2,965 over 9 years on $10k starting = +3.3%/year.** Works as a *sleeve*, cannot carry a $10M FoF on its own.
- **Adjacent-window correlation = regime persistence.** Bad regimes cluster 4–6 consecutive windows (~1–1.5 years). A single 90-day OOS samples ~5% of a regime cycle; the Phase B 70-day OOS that motivated the empirical-grid gate was *one slice of one regime* — entirely consistent with the noise it reported.
- **Lesson:** **a Phase B-style "improve the gate within LS v1" path is fixing the wrong layer.** EMA-cross + ADX is structurally vulnerable to BTC top/reversal regimes (2021 ATH, 2022 LUNA, 2024 halving chop). Adding a 19-cell gate on top of a fragile trend signal doesn't fix the trend signal — it adds *another* overfit surface (the grid was already K=184.5-shrunk toward the mean). The fragility is in the *direction* (long/short bias), not the *gate* (which entries to take). The right fix is **multi-strategy composition**: a regime-orthogonal sleeve (pair-trade / market-neutral mean-reversion, vol sleeve, cash/RWA) that earns in the chop regimes where LS v1 bleeds, so the *aggregate* stream is stable even when individual sleeves are not.
- **Fallout:**
  1. ❌ **DEPRIORITIZE Phase B as currently designed** (improve LS v1's gate). Holds for smoothed-CIS re-run but is no longer the critical path.
  2. 📍 **ELEVATE multi-strategy composition** — pair-trade sleeve, vol sleeve, cash/RWA sleeve, each regime-orthogonal to LS v1. 9-year data is in place to backtest all of them.
  3. ✅ **VALIDATE 9-year data pipeline** (`scripts/fetch_extended_history.py` + `scripts/build_spot_catalog.py`) — works, reproducible, fast (~22s pull, ~30s catalog, ~50s sweep).
  4. ✅ **VALIDATE rolling OOS harness** (`multi_window_baseline.py`) — extensible to all future variant tests.
  5. 📍 **Define the strategy grid** (Task #7) — multi-asset × multi-strategy × multi-band, with explicit regime-orthogonality expectations per cell.
- **Carrier note:** The 9-year baseline stays the reference for all future LS v1 variants (Phase B re-run, H3.2 sweep, etc.). CIS-on variant (`reports/multi_window_baseline_spot/2026-07-16/summary.md`) is structurally useless for 9-year comparison because CIS pipeline started 2024-06-07 — pre-2024 windows had 0 trades; not a fair comparison.

## R22 🔴 Cross-sectional reversal is a viable pair-trade signal on crypto — IT ISN'T (losers keep losing)
- **Hypothesis (the implicit assumption behind the strategy grid's pair-trade sleeve):** cross-sectional 30d return reversal — long the bottom decile, short the top decile, weekly rebalance — is a documented factor (Jegadeesh/Titman 1993 for tradfi equities) that should work on a crypto universe. This was the first concrete pair-trade sleeve implementation; `reports/STRATEGY_GRID_2026-07-16.md` §7 specified it as the chosen signal.
- **Test:** vectorized pandas backtest on 21 Binance spot 4h instruments (BTC/ETH/SOL + 18 majors/L2/DeFi), 2017-08-17 → 2026-07-16, varying lookback (10/20/30/60/90 bars) × decile (5/10/20/30%). Driver: `src/research/cis_regime_studies/pair_trade_sleeve.py`. ~290k bars total, ~650 rebalances over 9 years.
- **Result (parameter sweep):**
  | lookback | decile | PnL ($) | Sharpe | AnnRet | MaxDD |
  |---:|---:|---:|---:|---:|---:|
  | 10 bars (1.7d) | 10% | -9,999.82 | -1.195 | -91.8% | -100.0% |
  | 20 bars (3.3d) | 10% | -9,997.25 | -0.652 | -54.9% | -100.0% |
  | 30 bars (5.0d) | 10% | -9,999.99 | **-1.435** | -121.4% | -100.0% |
  | 60 bars (10d) | 10% | -9,996.30 | -0.608 | -51.0% | -100.0% |
  | 90 bars (15d) | 10% | -9,999.49 | -0.916 | -75.0% | -100.0% |
  | 30 bars | 5% | -10,000.00 | -1.415 | -125.5% | -100.0% |
  | 30 bars | 20% | -9,983.03 | -1.230 | -59.5% | -99.9% |
  | 30 bars | 30% | -9,903.79 | -1.242 | -45.3% | -99.2% |

  **Reversal is robustly negative across ALL parameter combinations.** Not a tuning problem; structural failure.

- **What the signal was doing (the diagnosis):** at each rebalance, the bottom decile was names like MATIC (-23% in 30d before POL rebrand Sep 2024), LINK (-16% in a single 30d window mid-2023), BNB (-13.7%). These names were "losers" because they were structurally declining (deprecation, narrative rotation, drawdown in flight) — NOT transient mean-reversion candidates. Going long the worst-performing names systematically bets against the structural trend. Short the winners (BTC, ETH at ATH moments) fights the persistence.

- **Momentum contrast (the same universe, flipped signal direction):**
  | lookback | decile | Sharpe | AnnRet | MaxDD |
  |---:|---:|---:|---:|---:|
  | 10 bars | 10% | +1.025 | +80.1% | -82.9% |
  | 30 bars | 10% | **+1.334** | +120.0% | -75.5% |
  | 60 bars | 10% | +0.582 | +51.8% | -91.5% |
  | 90 bars | 10% | +0.897 | +77.7% | -89.7% |

  **Momentum dominates reversal by ~3 Sharpe points.** Equal-weight basket (no signal, long all 21 names) is +0.876 Sharpe — momentum adds 0.5 Sharpe over passive. Confirms the documented crypto factor pattern: trend/persistence > mean-reversion in crypto because structurally broken names stay broken (R6, R12 patterns).

- **Lesson:** **cross-sectional reversal does not transfer from tradfi equities to crypto.** The Jegadeesh/Titman reversal factor assumes the universe is roughly stationary — names oscillate around stable fundamentals. In crypto, "losers" are often *structurally* declining (deprecation, broken projects, dilution, post-ICO decay), and the reversal signal can't distinguish "transient drawdown" from "permanent decline." This is a portable tradfi → crypto failure, not a parameter-tuning problem. **The right pair-trade signal for crypto is cointegration-based** (stationary spread between two specific cointegrated assets, e.g. ETH/BTC ratio, sector-pairs L2/DeFi), not cross-sectional ranking of relative returns.
- **Fallout:**
  1. ❌ **DEPRIORITIZE cross-sectional reversal as a pair-trade sleeve** — directly falsified on this universe.
  2. 📍 **PIVOT pair-trade sleeve to cointegration-based implementation** — find pairs with stationary spread (Engle-Granger / Johansen), trade z-score of spread, target z > 2σ entry / 0.5σ exit.
  3. 📍 **Validate orthogonality** — even if cointegration pairs work, verify they don't correlate with LS v1 (>0.3 = no orthogonality gain).
  4. 📍 **Strategy grid revision** — `reports/STRATEGY_GRID_2026-07-16.md` §7 needs the cross-sectional reversal sketch replaced with cointegration sketch; the structural logic (regime-orthogonal complement to LS v1) still holds, the implementation needs to change.
- **Carrier note:** The pair-trade driver (`pair_trade_sleeve.py`) stays as the reusable harness; only the signal function needs replacement. The data extension (3 → 21 instruments, 9y history) is permanent and useful for any future cross-sectional or cointegration work.

## R23 🔴 Cointegration pair-trade is a viable crypto sleeve — IT IS MARGINAL (best Sharpe +0.49)
- **Hypothesis (the second attempt at pair-trade, post-R22):** if cross-sectional reversal fails because losers are structurally declining, then the right pair-trade signal is **cointegration-based**: find pairs (i, j) whose log-price spread is stationary (Engle-Granger test), trade the z-score of the rolling spread. This is the textbook "pairs trading" (Gatev, Goetzmann, Rouwenhorst 2006) approach — should work regardless of cross-sectional momentum/reversal dynamics.
- **Test 1 — static β (full-window OLS):** test 15 hand-picked candidate pairs (ETH/BTC, LTC/BTC, BNB/ETH, AVAX/SOL, NEAR/AVAX, ARB/OP, AAVE/UNI, LINK/ETH, DOT/ATOM, MATIC/ETH, DOGE/BTC, XRP/ETH, AAVE/ETH, MKR/ETH, APT/SUI) for cointegration, backtest spread-z-score on top cointegrated. Driver: `src/research/cis_regime_studies/cointegration_pairs.py`.
- **Test 2 — rolling β (540-bar = 90d window):** re-fit hedge ratio daily, see if regime-adaptive β improves results.
- **Result 1 (cointegration test, full 9y):**
  - 3 strongly cointegrated (p < 0.05): BNB/ETH (p=0.014), NEAR/AVAX (p=0.015), LTC/BTC (p=0.016)
  - 1 borderline (p < 0.10): ARB/OP (p=0.085)
  - 11 not cointegrated, including the canonical ETH/BTC (p=0.31)
- **Result 2 (static-β backtest, entry z=2.0σ, exit 0.5σ, stop 4.0σ, 5bps/leg cost):**

  | pair | coint p | Sharpe | AnnRet | MaxDD | Trades | WinRate |
  |---|---:|---:|---:|---:|---:|---:|
  | BNB/ETH | 0.014 | **+0.41** | +29% | **-93%** | 118 | 47.5% |
  | ARB/OP | 0.085 | +0.36 | +13% | -38% | 41 | **61.0%** |
  | NEAR/AVAX | 0.015 | +0.01 | +0.5% | -95% | 91 | 45.1% |
  | LTC/BTC | 0.016 | -0.43 | -27% | -99% | 113 | 46.0% |

- **Result 3 (rolling-β backtest, β window 540 bars):**

  | pair | Sharpe | MaxDD | PnL |
  |---|---:|---:|---:|
  | ARB/OP | **+0.49** | -53% | +$4,358 |
  | BNB/ETH | +0.31 | -91% | -$40 |
  | LTC/BTC | -0.36 | -96% | -$9,508 |
  | NEAR/AVAX | -0.41 | -98% | -$9,691 |

  Rolling β doesn't materially improve; sometimes worse (NEAR/AVAX flips from +0.01 to -0.41).

- **Diagnosis:** the pairs that are cointegrated are *barely* cointegrated — p-values of 0.014-0.016 mean the spread has a unit-root-ish tendency that occasionally mean-reverts but with frequent large divergences. The 2σ entry threshold catches the divergences but the 4σ stop-loss fires often (mean -93% drawdown on BNB/ETH), wiping out the gains. ARB/OP has a tighter profile (only -38% to -53% DD) but its data window is shorter (2023-03 → 2026-07, ~3.4y) — we have less than half a cycle of evidence.
- **Lesson:** **cointegration is necessary but not sufficient for a tradeable pair.** Statistical cointegration (Engle-Granger p < 0.05) doesn't guarantee the *speed of mean-reversion* is fast enough to overcome transaction costs and stop-loss damage. The crypto pairs we tested have cointegration but slow / fragile mean-reversion — divergences are large, exits are rare, and stop-losses dominate. **ARB/OP is the only candidate with a clean profile** but its 3.4y history is too short to certify; needs more cycles. Pair-trade as a class is **marginal at best** on this 9y crypto universe.
- **Fallout:**
  1. ❌ **DEPRIORITIZE pair-trade sleeve as the next priority** — both cross-sectional (R22) and cointegration-based (R23) signal classes are marginal on this universe.
  2. 📍 **PIVOT to vol sleeve** — crash-axis hedge, fundamentally different from trend (LS v1) and mean-reversion (pair-trade). Should have low correlation to both and high payoff in crash regimes where LS v1 bleeds (R21).
  3. 📍 **Carry pair-trade as a secondary sleeve only** — if ARB/OP is the cleanest pair and it stays cointegrated for 2+ more years, it could be a 5-10% allocation in the composite. Not a primary sleeve.
  4. 📍 **Strategy grid revision** — pair-trade is demoted from "next sleeve" to "secondary sleeve (ARB/OP only if validated over more cycles)"; vol sleeve elevated to next priority.

## R21 🔴 Conviction beta-plus reduces to a systematic revenue-momentum factor — IT DOESN'T (judgment-led)
- **Hypothesis:** the conviction/HYPE playbook can be systematized as "long tokens with accelerating fee revenue" (fundamental momentum → re-rating).
- **Test:** 13 liquid revenue-generating tokens (AAVE/UNI/LDO/MKR/CRV/GMX/PENDLE/HYPE/JUP/RAY/ENA/AERO/CAKE/DYDX), real DeFiLlama daily revenue + Binance price, 414d, IC(30d-revenue-accel → fwd 30d return) + long-top-vs-bottom. `src/research/factory/conviction_selection.py`; experiment_runs `conviction_selection_20260715`.
- **Result:** IC **−0.05** (mildly INVERSE); accelerating-revenue top-half returned −6.9% vs decelerating bottom-half −4.8% (top−bottom **−2.1%**), selection hit-rate 39% (< coin flip). Everything −5 to −7% (broad DeFi bear window).
- **Lesson:** fundamental momentum alone does NOT mechanically predict crypto re-rating — it's priced in / swamped by beta, and the real conviction alpha is a SPECIFIC narrative catalyst proving a moat (HYPE: Trump-weekend-war → 24/7 on-chain moat proven), which a revenue screen can't time. Consistent with CONVICTION_METHODOLOGY's own claim: this lane is **judgment-led (moat + catalyst + reflexivity), not a systematic factor** — it's the moat *because* it can't be reduced to a commodity bot. Build it as an AI-augmented candidate-SURFACING tool for discretionary conviction, not a backtested systematic sleeve.

## What the graveyard says, in aggregate

1. **Cleverness overfits; simple survives.** (R1, R2, R8) Every added degree of freedom lost OOS. The winners are the humble ones (REGIME_CIS_FLOOR, funding-level).
2. **Edge is orthogonality, not more of the same.** (R3, R4, R6, R7, R13) Directional breadth, correlated blends, and thin-name expansion all destroyed value; even an orthogonal signal doesn't transfer when the *frame* doesn't match (cross-sectional LS conviction ≠ per-pair swing sizing). The one thing that helped was an *uncorrelated* sleeve in its native frame.
3. **"Wired" is not "working."** (R9, R10) Two of our biggest gaps were things that *looked* connected. Verify the number and the schema, not the reference.
4. **Portability of patterns has limits.** (R13, R15) H3.2 won on LS v1; the funding gate was descriptive-true but trading-false. A proven pattern's home is its data shape (cross-sectional vs per-pair) AND its role on the target family (swing already has its own conviction layer; the gate's blocked trades are exactly the high-probability entries the system already captures). Test portability, don't assume it.
5. **Signal type must match the gate's role.** (R16) A cross-sectional reversal signal does NOT invert an absolute-direction eligibility filter — it needs a cross-sectional implementation (market-neutral pair, two-floor ranking, gross-scale). The architecture matters as much as the alpha. The same H2a finding, applied to the right shape (V4's two-floor model), is alive; applied to LS v1's single-floor eligibility, it was destructive.
6. **Sparse grids need smoothed inputs.** (R17) A K=184.5 shrinkage buys us calibration against noise but not against a noisy per-day tier assignment. When the input is noisy enough that NEUTRAL flips 30% of the time, even a correctly shrunk grid has 30% of its cells in the "no data" fall-through. **The architectural pattern (gate + size_multiplier) validated; the specific signal source (raw grid) not.** Inverse of R16's lesson: R16 said cross-sectional needs a cross-sectional implementation; R17 says a calibrated gate needs a calibrated input.
7. **A single sleeve cannot carry a multi-regime portfolio.** (R21) Trend-following earns well in trending regimes and bleeds in chop/reversal. A 70-day OOS samples ~5% of a regime cycle. The fix is NOT a smarter gate within the same strategy — it's regime-orthogonal multi-strategy composition, where the *aggregate* stream is stable even when individual sleeves are not.
8. **Tradfi factor signals don't always transfer to crypto.** (R22) Cross-sectional reversal (Jegadeesh/Titman 1993, documented in tradfi equities) loses money robustly on a 21-name crypto universe. Reversal assumes losers oscillate around stable fundamentals; in crypto, "losers" are often *structurally* declining (deprecation, broken projects, dilution) and the signal fights the structural trend. Cross-sectional **momentum** dominates reversal by ~3 Sharpe points on the same universe — confirming the crypto factor literature (trend/persistence > mean-reversion). **Portable patterns from tradfi must be re-validated on the target market's microstructure.**
9. **Cointegration ≠ tradeable pair.** (R23) Engle-Granger p < 0.05 says the spread is stationary, not that the mean-reversion is fast enough to overcome costs and stop-loss damage. Crypto pairs have slow, fragile mean-reversion — divergences are large, exits rare, stops dominate. Pair-trade as a class is marginal on this universe.
10. **The loop's job is to kill our ideas cheaply.** Nine of ten here died before a dollar was at risk. That is the system working, not failing.

*The most valuable output of this operation is a well-kept graveyard.*
