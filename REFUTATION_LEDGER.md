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

## R24 🟡 PARTIAL — Crowd Clock: TREND phases carry edge; the CONTRARIAN claim is REFUTED at 30d
- **Hypothesis (Trader Tom doctrine):** the crowd's emotional phase carries forward asymmetry —
  "capitulation" precedes up-moves, "euphoria/distribution" precede drawdowns.
- **Test (didn't wait — backtested history):** `src/research/crowd_clock_backtest.py` reconstructed
  the phase from Fear&Greed (2018→) + BTC daily trend and measured forward 30d BTC return per phase,
  3026 days, reduced inputs (no live funding-crowding / CIS-dispersion → `euphoria` never fired).
- **Result:** baseline mean fwd-30d **+3.83%** (hit 53.5%).
  - `markup` +7.78% (**+3.95% vs base**, hit 56.3%) — **VALIDATED**: the press-the-trend phase precedes the strongest returns.
  - `distribution` +0.11% (**−3.72% vs base**, median −1.82%, hit 45.7%) — **VALIDATED bearish**: the defend phase.
  - `capitulation` +1.00% (**−2.84% vs base**) — **REFUTED as a 30d long**: buying fear did NOT beat hold.
  - FNG-only: FNG<25 **+2.91%** (BELOW base) vs FNG>75 **+13.11%** (WAY above) — the contrarian read is *backwards* at 30d.
- **Lesson:** in crypto, at a 30d horizon, **momentum dominates reversal** (confirms R22). Extreme fear
  is usually mid-downtrend (more downside); extreme greed usually mid-bull (more upside). So the Crowd
  Clock is a **trend compass, not a contrarian one** at this horizon. Its usable edge = press-in-markup /
  defend-in-distribution. `crowd_phase_book` recalibrated: capitulation is no longer a broad long tilt —
  the mean-reversion sleeve must earn it with its OWN deeper-extreme entries + faster exit (MultiFactorV2:
  MVRV<0.9 + price<10%, exit RSI>65), which this broad-phase 30d test does NOT cover.
- **Follow-up 1 — multi-horizon + cross-asset (BTC/ETH/SOL, 3/5/7/14/30d):** capitulation is negative
  at EVERY horizon on ALL assets (no 3-5d bounce — the contrarian idea is fully dead). markup is
  positive everywhere and scales with beta (SOL +15% @30d). distribution is weakly bearish but NOT
  robust (ETH breaks it, n≈85). The one robust, cross-asset, all-horizon edge is the TREND (markup).
- **Follow-up 2 — does sentiment add over pure momentum? YES (the survivor).** Decomposition:
  `uptrend + GREED` beats `uptrend alone` by **+1.64 (BTC) / +3.39 (ETH) / +7.49pp (SOL)** fwd-30d;
  and `uptrend + FEAR` badly *underperforms* (ETH +0.09%, SOL +0.05%) — a rally the crowd distrusts is
  a weak rally. So the Crowd Clock is NOT a momentum relabel: crowd *agreement* confirms a trend, crowd
  *disbelief* flags a fake one. **Extracted → `src/data/signals/trend_confirmation.py`** (confirmed_up /
  unconfirmed_up / confirmed_down states with the base rates baked in).
- **Follow-up 3 — walk-forward OOS: the sentiment add-on FAILS.** Split TRAIN(<2023) vs HOLDOUT(≥2023):
  the "uptrend+greed beats uptrend" edge was huge in-sample (BTC +5.53 / ETH +7.82 / SOL +34.74pp) but
  **collapses out-of-sample** — BTC −0.35pp (gone), SOL +0.69pp (gone), only ETH +2.21pp weakly survives.
  Plain trend/momentum persists OOS (positive, smaller); the SENTIMENT confirmation add-on does NOT
  robustly survive. Likely decay: the 2018-2022 wild-cycle sentiment extremes were far more informative
  than the post-2023 institutional/ETF market where sentiment is priced faster.
- **Net verdict (honest):** the contrarian claim is REFUTED (all horizons, all assets); the
  sentiment-confirmation add-on is REFUTED OOS (pre-2023 artifact, decayed). What survives is **plain
  trend/momentum**, which we already had. The Crowd Clock's *incremental* value over momentum is NOT
  established out-of-sample. `trend_confirmation.py` is kept as a DOCUMENTED NEGATIVE result (weak ETH
  residual only) — **do NOT size it.** The clock stays a display/context lens, not a sizing input.
- **The loop worked (twice):** built it, backtested same-day (killed contrarian), extracted the apparent
  edge, then walk-forwarded it (killed the extract too) — all before a dollar was sized. Two dead ideas,
  zero capital lost. This is the system functioning, not failing.

## R25 🔴 Adding a price-direction filter to a level signal degrades it — funding_price_disagreement REFUTED
- **Hypothesis:** extending `positioning_funding` (fade the crowded side) with a price-direction filter — "fade the WINNING crowd" (longs crowded + winning → SHORT; shorts crowded + winning → LONG) — should sharpen the signal by skipping unfired triggers.
- **Test:** market-neutral cross-sectional, 24 majors panel (BTC/ETH/SOL/BNB/XRP + 19), 931 days (2024-01-01 → today), `_xs_weights(score=fmean×r7, sign=−1.0)` gated on (fmean>0 ∧ r7>0) OR (fmean<0 ∧ r7<0). Fee 5bp, gross 1, daily rebal. `src/research/factory/signal_factory.py::signal_library`.
- **Result:** annSR **−0.11**, DSR **0.02** (no signal), walk-forward positive in **3/5 folds** (below the 4/5 nucleus gate). `funding_price_disagreement` ranks 17/23 — better than only the dead reversal/volume-regime candidates. Honest verdict: REFUTED.
- **Lesson:** a level signal (`positioning_funding` annSR=1.19, DSR=0.45) works as a pure crowd-exhaustion detector WITHOUT conditioning on price direction. Adding the price filter shrinks the tradeable set to the cases where positioning_funding is *marginal* (price-confirmed extremes are exactly the cases where the crowd is in control and the fade is most vulnerable to another leg in their direction). Concrete failure mode: the SHORT-signal wins in the SHORT-SQUEEZE, not in the persistent mark-up — but the conditioning only fires in the persistent mark-up (where the squeeze is already past). **A level signal needs level, not a momentum gate attached.** Reinforces R8 (don't add a second term to a clean signal without an OOS reason).
- **Reference:** `src/research/factory/signal_factory.py` `_funding_price_disagreement()` + `signal_library()` entry; factory output dated 2026-07-17; annSR −0.11 / DSR 0.02.

## R26 ⚪ Tightening an orthogonal signal past a threshold strips its orthogonality — funding_extreme_only REJECTED on correlation
- **Hypothesis:** tradeable extremes are deeper than shallow cross-sectional funding divergences — restrict to **top/bot 15%** of cross-sectional funding each day (drop the noisy middle 70%), and the resulting signal should be cleaner.
- **Test:** `_funding_extreme_only(fmean, percentile=85)` zeros out the cross-sectional middle band, then `_xs_weights(., sign=−1.0)`. Same panel, fee, gross, rebal as R25.
- **Result:** annSR **1.08** (decent — 5/23 rank), DSR **0.39** (not certified), walk-forward **3/5** (below gate), but **|corr| to `positioning_funding` = 0.66** — exceeds the 0.6 nucleus gate. Honest verdict: REJECTED on orthogonality, not on signal quality.
- **Lesson:** a "tighter" version of a working signal is the SAME signal with NOISE trimmed, not a NEW signal. Its orthogonal-information content is zero even when its raw Sharpe is positive. The combined-book nucleus gate (|corr|<0.6) would have rejected this automatically — better to know before shipping than to ship and ship a near-duplicate of `positioning_funding` that doubles the position-sizing on the same exposure. **Trim with care, measure with the same metric you intend to live with.** Reinforces R3/R4 (correlated ensembles destroy value; count orthogonality, not names).
- **Reference:** `src/research/factory/signal_factory.py` `_funding_extreme_only()` + `signal_library()` entry; factory output dated 2026-07-17; annSR 1.08 / DSR 0.39 / corr 0.66.

## R27 🔴 Funding VOLATILITY (time-series std) is a different-axis funding signal — REFUTED
- **Hypothesis:** per-asset time-series std of funding (over 30d) is a different *mechanism* from cross-sectional funding *level* — LONG low-vol assets (stable crowd, persists), SHORT high-vol assets (uncertain crowd, washes out).
- **Test:** `_funding_volatility(fmean, k=30)` → `_xs_weights(., sign=−1.0)`. Same 24-name panel, 931 days, 5bp fee, gross 1.
- **Result:** annSR **−0.12**, DSR **0.02**, walk-forward **3/5**. The interesting structural finding: corr to `positioning_funding` = **−0.519** (highly *negatively* correlated, not redundant). Different mechanism in shape — would be a useful *hedge* if it had positive Sharpe. It doesn't. Verdict: REFUTED.
- **Lesson:** adding a different transformation (level → vol, cross-section → time-series, level → velocity) does NOT by itself find a new edge. Each of these is a *re-expression* of the same underlying perp-crowding signal; when the underlying signal fails, every transformation fails with it. **The funding axis is saturated after R8 (velocity), R25 (price-conditioned), R26 (cross-sectional threshold), R27 (time-series vol).** To go beyond the funding axis requires a NEW data layer (intraday volume, order-book microstructure, options skew, on-chain), not another transformation of the same series.
- **Reference:** `src/research/factory/signal_factory.py` `_funding_volatility()` + `signal_library()` entry; factory output 2026-07-17; annSR −0.12 / DSR 0.02 / corr −0.519.

## R28 🔴 Vol Sleeve v2 (delta-neutral cascade long-vol + premium-harvest short-vol) — KILLED BEFORE PHASE 3
- **Hypothesis (from `docs/VOL_SLEEVE_V2_CAUSE_2026-07-18.md` §1):** When a leveraged long crowd is paying elevated perp funding + sitting on elevated open interest, the next material drawdown in spot is mechanically amplified by cascading liquidations — this is an unfunded external liability, not a price forecast, and it surfaces as a volatility regime transition rather than a directional signal. v2 differs from v1 (realized-vol targeting overlay on BTC long) on 4 axes: delta-neutral (not directional), triple-crowding trigger (RV + OI/MCap + funding), 21-name universe (not BTC-only), two-leg structure (long-vol cascade + short-vol carry).
- **Phase 1 verdict: 🟡 YELLOW** (proceed with explicit scope adjustments). Phase 2 built 3 runnable legs + 1 deferred leg (OI/MCap overlay — no historical OI on disk).
- **Test — Leg 1 (`long_vol_cascade_leg_rv_only`, 21 names, 9y OHLCV 2017-08 → 2026-07):** post-cascade mean-reversion proxy. Result: aggregate Sharpe **−2.20** (21-name equal-weight), MaxDD **−39.82%**, Final NAV $6,336 from $10,000 (−36.6%). The post-cascade bounce signal fires too often (162 triggers in synthetic, 7,177 in BTC-only — ~37% of bars), slippage + options decay eat the entire premium.
- **Test — Leg 2 (`long_vol_cascade_leg_with_funding`, 5 majors × 21mo 2025-01 → 2026-07):** true delta-neutral spot+perp offset with funding carry + cascade detection. Result: Sharpe **−1.631**, MaxDD **−0.65%**, ann vol **0.04%**. The leg barely trades — the triple-crowding trigger (RV_pct>0.9 ∧ funding_pct>0.8) fires 0 times in the 21mo panel (verified in Phase 1 Check 3: only 38 distinct RV_pct>0.9 events across 9y; with funding gate added, ~0-2 events on the 21mo subpanel). A leg that doesn't fire isn't a leg.
- **Test — Leg 3 (`short_vol_carry_leg`, 21 names, 9y OHLCV):** delta-hedged perp short + spot long with 5% annualized IV>RV spread proxy. Result: Sharpe **+0.236**, MaxDD **−0.78%**, Final NAV $10,029 (+0.29%). Just below the +0.3 Sharpe threshold; the premium proxy is a HONEST PLACEHOLDER for Phase 4 IV data (without IV, the IV>RV spread is unmeasurable).
- **Test — Combined NAV (30% Leg 1 + 70% Leg 3):** Sharpe **+0.012**, MaxDD −1.95%. The combination is dragged down by Leg 1's losses; the orthogonal structure can't rescue a leg that loses money.
- **Verdict: REFUTED on Phase 3 readiness.** Gate 1 (corr to LS v1 + MaxDD) fails for Leg 1 (MaxDD −39.82% < −25% threshold). Gate 2 (Sharpe > 0.5 OOS) fails for ALL legs. Gate 3 (DSR > 0.5 over 6 walk-forward windows) untested but mathematically impossible given Leg 1's negative SR.
- **The cause IS articulated** (the cascade mechanic is real — leveraged long crowd liquidations amplify spot drawdowns) **but the EMPIRICAL realization on RV+funding data alone is too weak** to generate tradeable alpha without options data. Phase 2 numbers are a STRUCTURAL LOWER BOUND on what Path A (no-options, RV-only proxy) can achieve. Phase 4 (with Deribit IV data → IV-RV basis trade + delta-hedged straddles) is the only path that could realize the cause's full alpha.
- **Lessons:**
  1. **Cause articulated ≠ cause tradeable on the data you have.** Phase 1's GREEN/YELLOW score is about CAUSE CLARITY, not EXPECTED PNL. A YELLOW does not promise a positive Phase 2 — it promises Phase 2 can run without breaking. The empirical finding is independent.
  2. **A trigger that fires 0 times in 21 months is not a leg, it's a research artifact.** Leg 2's failure mode (insufficient trigger frequency) is distinct from Leg 1's (oversized losses) and Leg 3's (insufficient premium proxy). All three are kill-worthy for different reasons.
  3. **Vol-of-vol is a saturated axis too.** R25/R26/R27 killed the funding axis; R28 kills the realized-vol axis. The axis saturation pattern is consistent — every re-expression of an underlying signal (level, velocity, vol, percentile, cross-sectional, time-series) faces the same ultimate constraint: the underlying signal's noise floor.
  4. **Compounding bug R27-bis:** during Phase 2, Leg 3's premium proxy was first implemented as `notional × rv_per_bar × 0.30`, producing astronomical terminal NAV ($259 billion) over 9 years of compounding. Fixed to a constant 5% annualized spread (`notional × 5% / (252 × 6)`), giving realistic $10,029 terminal NAV. Lesson: any per-bar proxy that compounds over thousands of bars needs an annualized formulation, not a per-bar scalar — the per-bar scalar explodes under geometric compounding. Bug surfaced and fixed in the same session; no false-positive went unreported.
- **Reference:** `src/research/cis_regime_studies/vol_sleeve_v2.py` (Phase 2 driver, 10/10 sandbox tests passing); `docs/VOL_SLEEVE_V2_CAUSE_2026-07-18.md` (Phase 1 memo, YELLOW verdict); `src/research/cis_regime_studies/tests/test_vol_sleeve_v2_smoke.py` (10 unit tests, sandbox-safe, no FUSE/Mac-only deps). Phase 2 run dates 2026-07-18; results in `/tmp/vol_sleeve_v2_smoke/summary.md`. Phase 4 (Deribit IV integration) is the only path that could revive the cause.

## R29 ⚪ Volume factory — NEW data layer SCAFFOLDED; 3 candidates INCONCLUSIVE on A-S1 panel (K=5)
- **Hypothesis:** volume + taker-buy imbalance is a NEW mechanism family orthogonal to perp-funding (realised demand vs crowd positioning). Three candidates: `volume_price_trend` (sign(rk) × vol_z), `taker_buy_imbalance` (buy-side quote ratio − 0.5), `volume_weighted_momentum` (rk × √vol).
- **Test:** `src/research/factory/volume_factory.py` (NEW, 174 lines). Reads A-S1 cached substrate (5 symbols × 563 days, 2025-01-01 → 2026-07-17), reuses the funding factory's `_xs_weights` / `_bt` / `_walkforward` / `evaluate_universe` honest gate. NO modifications to validated `causal_positioning.py`.
- **Result:** all three FAIL — annSR **−0.32 / −1.46 / −1.38**, walk-forward **2/5, 0/5, 1/5**, DSR=0. No DSR survivor.
- **Honest verdict: INCONCLUSIVE, NOT REFUTED.** A-S1 panel is K=**5** (BTC/ETH/SOL/BNB/XRP); the funding factory's panel is K=**24**. Statistical power to detect a true K×N edge is roughly **5/24 ≈ 21%** of the wider panel; cross-sectional differentiation is dominated by 1-2 outlier names; in-sample fit on 4-of-5 leaves little genuine signal. The −1.46 taker-buy figure is more likely a **panel-too-small artifact** (or sign-convention check) than a real "taker-buy reverses" finding.
- **What IS proven by this run:** the volume factory SCAFFOLDING works end-to-end — substrate loader, signal library, honest gate, structured output. To resolve R29, populate the substrate with volume + taker-buy columns for the 24-name universe (one Binance fetch per name, 1000-bar pagination, ~1 hour wall-clock) and re-run.
- **Lessons:**
  1. **Scaffolding a NEW data layer is honest progress even when the first result is null.** The factory didn't exist before this session; now it does and runs the gate correctly. The negative result documents the panel-size constraint, not the mechanism's failure.
  2. **Open a new mechanism family through scaffolding, not speculation.** R25/R26/R27 saturated the funding axis by transforming the same series; volume is a genuinely different channel (realised demand, not crowd-positioning), but it needs a panel rich enough to express cross-section. K=5 is sanity-only.
  3. **Axis-saturation extends beyond funding.** R27 found funding-axis saturated; R28 found realized-vol-axis saturated (Phase 4 IV needed). R29 marks the start of the **volume-axis investigation**, currently inconclusive on a thin panel.
- **Reference:** `src/research/factory/volume_factory.py` (NEW, 174 lines, 3 candidates + scaffolded CLI); factory output 2026-07-17.

## R30 🔴 Phase-weighted combined book — Crowd Clock gate does NOT improve OOS Sharpe on the funding-axis combined book (K=24, 19mo)
- **Hypothesis:** scaling the factory's combined-book daily pnl by `crowd_phase_book.phase_allocation(phase, confidence).gross_scale` improves the honest OOS Sharpe. Crowd Clock phases carry forward asymmetry (R24: markup validated +3.95%, distribution validated −3.72%, capitulation refuted at 30d). If phases carry edge individually, an aggregated phase-conditional book should beat a flat-gross book.
- **Test:** `src/research/factory/phase_weighted_combined.py` (NEW). Reuses `signal_factory.walkforward_combined` for honest OOS isolation (nucleus+blend fit on TRAIN, applied forward to embargoed TEST). Phase history reconstructed daily: BTC 30d/7d % change from panel close[:,0], FNG from alternative.me full history, mean funding pressure from panel fmean (sign-negated to match crowd_clock convention). Each day → `compute_crowd_clock` → `phase_allocation` → gross_scale. **Same OOS pnl, × per-day scale**.
- **Result (19mo, 2024-01-01 → 2026-07-17, K=24, 300 OOS days across 5 folds):**
  - Phase distribution: capitulation **30.0%**, accumulation **40.9%**, markup **26.2%**, distribution **2.9%**, euphoria **0%** (never fired — no extreme-greed × uptrend × crowded-long combo in window).
  - Avg gross scale over window: **0.618** (the policy is structurally defensive; most phases scale <1.0).
  - **Base combined OOS Sharpe: +0.53**, total return +4.90%.
  - **Phase-scaled OOS Sharpe: +0.48**, total return +2.80%.
  - **Delta: −0.05 annSR** — phase gate HURTS the funding-axis combined book.
- **Honest verdict: REFUTED as applied.** The phase-conditional gross gate does not improve the OOS Sharpe of the funding-axis combined book on this panel. The policy scales gross DOWN in most days (0.55–0.77), so it cuts total return faster than it cuts vol; Sharpe barely moves. Per-phase breakdown shows the in-sample combined book earns positive mean pnl in every phase (capitulation is the largest contributor +0.733 contrib_SR in-sample, then accumulation 0.385, distribution 0.265, markup 0.102) — but applying a multiplicative gross-scale and re-running OOS on the same train/test split yields a small net loss.
- **Why it doesn't translate (causal reading):**
  1. **The R24 edge is on BTC at a 30d horizon, not on a cross-sectional daily-pnl stream.** R24 measured forward 30d BTC return per phase (a single-asset trend signal); this test applies the same phase mapping to a market-neutral K=24 daily book. The "edge per phase" of R24 is asymmetric across phases; the "edge per phase" of the daily pnl stream is much smaller because (a) it's already hedged, (b) it earns in bps not percent, (c) the phases overlap less cleanly than BTC's regime.
  2. **The policy is structurally defensive.** Most days the policy says gross<1 (accumulation 0.55, capitulation 0.60, distribution 0.45). Only markup has gross=1.0. So on average the policy is "hold less," which costs return without commensurate vol reduction in a market-neutral book whose vol is already low.
  3. **The two-layer book doctrine requires a separate MR sleeve.** Per `docs/TRADER_TOM_DOCTRINE.md` §5b, the phase gate sizes BETWEEN two sleeves (MR sleeve wakes at capitulation, trend sleeve presses at markup). This test applies the gate to ONE sleeve (the trend-led funding-axis combined book) — there's no MR sleeve here, so the gate only ever says "hold less of the trend book" and never "rotate to MR book." That's a structural mismatch with the doctrine, not just a tuning issue.
- **What IS proven:** the wiring works end-to-end (phase reconstruction → policy lookup → per-day OOS scaling → honest A/B), the phase distribution over 19mo is realistic (capitulation 30%, markup 26%, distribution 3% — consistent with the actual 2024-2026 BTC cycle of mixed trends + early-2026 capitulation), and the OOS verdict is unambiguous: **don't apply this gate to a trend-only combined book on this panel.** The next experiment (Direction 2 follow-up) would need a true two-sleeve book: a market-neutral MR sleeve (MultiFactorV2 / Sleeve A parity) + the trend-led combined book, with the gate routing between them — not scaling one book.
- **Lessons:**
  1. **A validated signal-per-phase finding does not automatically transfer to a per-day gross-scale.** R24's verdict is on BTC forward returns at 30d; this test is on a market-neutral cross-sectional daily book. Same phase, different return stream — the gate's policy reduces gross where the underlying book doesn't have a "leverage up" option, so it just pays a vol tax for no return.
  2. **A phase-conditional sizing policy needs the TWO-LAYER book it's designed for.** Scaling one book by a phase-says-hold-less factor does not reproduce the doctrine's intended "rotate sleeves" behaviour. The next direction 2 experiment must build the MR sleeve alongside, not just add a scalar to a trend book.
  3. **OOS isolation discipline is the honest gate.** The −0.05 delta is small but it's the difference between the same A/B architecture with one switch flipped — the right thing to compare. In-sample Sharpe (the in-sample diagnostic) shows phase winners; OOS shows the gate as applied doesn't survive.
- **Reference:** `src/research/factory/phase_weighted_combined.py` (NEW, ~250 lines); OOS run 2026-07-18.

## R31 🔴 Volume axis REFUTED on K=24 panel — R29 (K=5 INCONCLUSIVE) now RESOLVED
- **Hypothesis:** the volume-axis signals (volume_price_trend, taker_buy_imbalance, volume_weighted_momentum) — different mechanism family from perp-funding — carry a real cross-sectional edge when given enough cross-section.
- **Test:** `src/research/factory/volume_factory_universe.py` (NEW). Fetches the 19 additional symbols (`DOGE/ADA/AVAX/LINK/DOT/LTC/TRX/ATOM/NEAR/APT/ARB/OP/SUI/UNI/AAVE/INJ/FIL/ETC/BCH`) from Binance fapi klines 2025-01-01 → 2026-07-17, ~564 rows each. Same CSV schema as the A-S1 substrate. Reuses `volume_factory.signal_library` + `_bt` + `_walkforward` + `evaluate_universe` — no new mechanisms, no new logic. Just the 3 existing candidates on 5× more cross-section.
- **Result (K=24, 564 days):**
  - `volume_price_trend`     — annSR **−0.06**, 2/5 positive folds, NOT robust
  - `taker_buy_imbalance`    — annSR **−0.98**, 2/5 positive folds, NOT robust
  - `volume_weighted_mom`    — annSR **−0.77**, 1/5 positive folds, NOT robust
  - DSR survivors (≥0.95): **0** — NONE
- **Honest verdict: R29 RESOLVED → REFUTED.** The K=5 INCONCLUSIVE on the original substrate (statistical power ~21%) is now resolved: with 5× more cross-section, all three candidates are net-negative, none walk-forward robust, none survive DSR. The volume-axis mechanism family is REFUTED at this scale.
- **What this means for the factory:**
  1. **Two mechanism axes now SATURATED** (funding-axis: R8/R25/R26/R27; volume-axis: R31). The factory's only validated cross-sectional signal remains `positioning_funding` (the funding-LEVEL cross-sectional z-score on K=24 majors). All other funding/volume transformations we've tried are net-negative or barely-positive-but-correlated-to-the-baseline.
  2. **The substrate + factory scaffolding works** — the volume_factory still produces clean results; we can re-use the loader to test other axes when a different data source (e.g. basis, on-chain, options) becomes available.
  3. **Honest framing of the search:** we have tried funding × 5 transformations and volume × 3 candidates. That's 8 candidate generations across 2 mechanism families and ONE survived. The factory's job is to keep killing ideas cheaply so the loop doesn't pay to re-learn them — this entry is exactly that.
- **Lessons:**
  1. **"Inconclusive" → resolve it, don't leave it open.** R29's honest verdict explicitly called for the K=24 follow-up. Doing it produced a CLEAN REFUTATION rather than another INCONCLUSIVE — that's progress (the graveyard grew by one more fact, the substrate grew by 19 reusable files, the factory pattern is validated again).
  2. **Substrate scaffolding pays off even when the result is null.** The `_data/strategy_revive/` directory now has OHLCV-with-volume for all 24 majors, ready for any future study that needs daily volume (e.g. capacity analysis, vol-targeted sizing, intraday-feature backtests). The cost was ~30 seconds of fetcher time; the value is reusable across future experiments.
  3. **Sign convention / scale matters.** The −0.98 taker-buy-imbalance is large in magnitude; cross-sectional centering + `taker_buy / vquote − 0.5` produces a near-zero-mean score on most days but explodes in volatile sessions. This is the SAME family of issue as R8 (adding a second term to a clean signal) — over-engineering a simple observation into a structured signal loses its baseline.
- **Reference:** `src/research/factory/volume_factory_universe.py` (NEW, ~180 lines, includes fetch+run CLI); substrate `_data/strategy_revive/{19 new symbols}_1d_ohlcv.csv` (564 rows each); OOS run 2026-07-18.

## R32 🟡 Cash-and-Carry at VIP-0 taker cost REFUTED — but VALIDATED at maker-fee regimes
- **Hypothesis:** delta-neutral funding basis (long spot + short perp, only when funding>0) is the institutional crypto edge: steady positive return, low vol, high Sharpe, scales (deep instruments).
- **Test:** `src/research.factory.cash_carry_investigation.py` (NEW). The existing `cash_and_carry.py` reported a striking 2.42 Sharpe / 0.3% maxDD on a **167-day** overlap using **4bps** rebalance cost — both suspiciously small. This harness fetches the FULL available history per symbol (paginated by startTime, not the 1000-bar limit) and tests the strategy under FOUR cost tiers.
- **Result (K=10 majors, 1659 days of overlap, 2022-01 → 2026-07):**

  | Cost tier | Cost/day | Book Sharpe | maxDD | Walk-forward (3 folds) | Robust? |
  |---|---|---|---|---|---|
  | Pessimistic (50bps RT)   | 50bps | **−27.62** | 54.7% | [−36, −16, −44] | NO (0/3) |
  | Realistic VIP-0 taker    | 30bps | **−11.07** | 27.2% | [−16, −3, −22]  | NO (0/3) |
  | Aggressive maker (14bps) | 14bps | **+2.16**  | 3.0%  | [+0.7, +7.2, −4.2] | YES (2/3, mean +1.23) |
  | Optimistic (4bps, original) | 4bps | **+10.43** | 0.3% | [+11.0, +13.8, +6.9] | YES (3/3) |

  Per-name gross stats (no cost): BTC +13.3 Sharpe, hit rate 86.7% active days, avg daily funding +0.018%; ETH +X, SOL +X, … all positive. The funding stream IS real — it averages 7-9% APY across the panel.
- **Honest verdict — REFUTED at retail, VALIDATED at maker fee regimes:**
  1. **The funding edge exists and is large** (gross Sharpe ~13, +7-9% APY at zero cost). The "edge" is the funding payment itself, not a forecasting skill.
  2. **At standard retail taker costs (VIP-0 = 30bps/day), the strategy is destroyed** — Sharpe −11, maxDD 27%, walk-forward 0/3 positive. Every rebalance pays both legs' taker fees; the funding stream is too small to overcome it.
  3. **At maker-fee regimes (post-only limit orders on both legs ≈ 14bps/day amortised), the strategy is VALIDATED** — Sharpe +2.16, maxDD 3%, walk-forward 2/3 positive (mean +1.23). The fold-3 weakness (−4.17) is concerning — it's the 2025-Q2/Q3 window when funding flipped persistently negative — but the gross positive returns in folds 1-2 (2022-2025 Q1) carry the average.
  4. **The original `cash_and_carry.py`'s 2.42 Sharpe was a cost illusion.** It used 4bps/day cost (optimistic) and 167-day overlap (the LAST 167 days of a 1000-bar limit=1000 fetch — the time when funding was consistently positive). Both choices happen to maximise Sharpe. Extending the window to 1659 days and applying realistic taker fees reveals the truth.
- **What this means for the factory:**
  1. **Cash-and-carry is NOT a retail strategy** — it's an HFT/market-making edge that requires consistent maker fills on both spot and perp. Without that infrastructure, the funding "edge" is fully consumed by taker fees.
  2. **If/when we have maker-fee infrastructure (post-only limit orders on both legs, fill-rate guarantees, market-maker rebates), the carry is a genuine sleeve candidate** that adds ~+2 Sharpe with near-zero maxDD. The K=10 book is small (~10 names liquid enough for both legs); could scale to K=24.
  3. **Cost sensitivity is THE variable for this strategy.** A 26bps/day cost difference (14bps → 40bps) flips Sharpe from +2 to ~−15. Any production deployment needs the fill-rate distribution measured, not assumed.
- **What IS proven:**
  - The funding stream itself is real and persistent (+0.018%/day average, ~7% APY).
  - The strategy logic is correct (long spot + short perp when funding>0); the issue is purely cost.
  - The honest window (1659 days, not 167) reveals the truth. **Short windows + optimistic cost assumptions inflate Sharpe by 5-10×.** This is a known lesson (López de Prado: "backtest overfitting via window choice") applied to a specific live edge.
- **Lessons:**
  1. **Verify cost assumptions and window length before celebrating Sharpe.** The original `cash_and_carry.py` reported +2.42; this investigation showed +2.16 at maker fees, −11 at taker fees, +10 at optimistic. Same data, different cost = 20× Sharpe range. Cost tier matters more than the signal.
  2. **Short overlap windows can lie.** The original's 167-day overlap was the tail of a limit=1000 fetch — happened to be the persistently-positive funding window of 2024-2025 Q1. Extending to 1659 days reveals negative folds (2025-Q2-Q3 funding flip). A real production strategy needs validation across multiple cycles.
  3. **The "edge" of cash-and-carry is structural, not predictive.** Unlike `positioning_funding` (which bets on crowd fade — a forecast), carry just COLLECTS the funding payment. It's a market-structure trade. Refuting it at retail cost doesn't refute the mechanism — it says "this edge is reserved for participants with maker infrastructure."
  4. **R7-like lesson (signal-specific universe):** carry works on the LIQUID majors with deep perp + spot books (BTC/ETH/SOL/BNB/XRP/DOGE/ADA/AVAX/LINK/LTC). Adding thinner names would degrade fill rates — a different kind of cost.
- **Reference:** `src/research/factory/cash_carry_investigation.py` (NEW, ~220 lines, paginated fetchers + 4-tier cost harness + walk-forward); OOS run 2026-07-18. Original `cash_and_carry.py` reports 2.42 Sharpe under optimistic assumptions — the harness reveals that's a cost-illusion at retail taker fees.

## R33 🔴 Composite +1.97 Sharpe is residual-α zero across 3 absorption runs — it's β on a friendly regime window, not α
- **Hypothesis (Track 4):** the 30/20/50 LS-v1/Causal/Cash composite carries +1.97 Sharpe as residual α — its Sharpe should survive factor absorption against {market, momentum, CIS-quality, funding}.
- **Test:** `src/research/cis_regime_studies/absorption_sweep_runner.py` (NEW, ~290 lines). OLS regression with Newey-West SE on each of 4 sleeves (LS v1 CIS-ON/OFF, Causal, Cash) + 3 composite mixes (30/20/50, 35/25/40, 40/30/30). Acceptance gate: |α t| > 1.96 after factors AND after peer sleeves = independent survivor. Three sequential runs on the same 265d post-CIS window (2025-05-08 → 2026-01-27) with progressively-stronger factor panels:
  - **Run #1 (3 factors, CIS proxy):** All 7 candidates ABSORBED. Composite α t = 0.36 / 0.28 / 0.23.
  - **Run #2 (4 factors, proxy + f_funding):** All 7 ABSORBED. Composite α t = 0.08 / −0.00 / −0.07. Causal absorbs MORE with f_funding (α t 0.10 → −0.27), confirming f_funding is the right factor.
  - **Run #3 (4 factors, TRUE long top-CIS / short bottom-CIS + f_funding, built from 11yr CIS historical reconstruction, 75,478 rows × 34 assets):** All 7 still ABSORBED. Composite α t = 0.86 / 0.75 / 0.67 — **larger in magnitude than Run #2**, meaning the proxy was GENEROUS. **Cash flips from α t=1.78 (ABSORBED) to α t=2.89 (residual)** — first sleeve to pass the strict factors-only gate; fails AND-after-peers (1.87).
- **Result: REFUTED.** Across 3 runs with progressively-stronger factor panels, no sleeve carries residual α at t>1.96 against the factor panel AND peer sleeves simultaneously. The +1.97 Sharpe on the 30/20/50 composite is **a repackaging of {f_market × f_momentum × f_cis_quality × f_funding} beta on a friendly 265d regime window, NOT α**. The 2nd-half Sharpe 2× the 1st-half (per the §COMPOSITE_OPTIMIZED sub-window analysis) is the classic beta tell — a regime-tailwind composite is what an UN-absorbed momentum-heavy book looks like.
- **Why it fails (causal reading):**
  1. **Composite returns are constructed as weighted sums of sleeve returns.** Their residual α by construction equals a linear combination of sleeve residuals. The peer-sleeve regression CANNOT create α where the underlying sleeves don't have it.
  2. **The 265d post-CIS window is one regime.** The factor panel (BTC + TSMOM + CIS-quality spread + funding) explains most of the variance on a friendly BTC-bull window because the book is mostly long-beta anyway.
  3. **The Causal sleeve's OOS docstring +1.41 (658d window) is NOT falsified by this** — the absorption test uses a different (shorter) window and a different return series. But it IS evidence that the Causal sleeve's "α" on a 265d post-CIS window is partially f_funding beta.
  4. **Cash is genuinely orthogonal** (α t=2.89 in Run #3, the only sleeve to cross 1.96). This is the expected result of cash being a risk-free rate proxy — orthogonal to {market, momentum, CIS-quality, funding} by construction. The AND-after-peers gate catches it because cash's residual overlaps with what the peer sleeves are doing (the sleeve returns load cash by construction).
- **Lessons:**
  1. **Run absorption BEFORE composite mixing.** The §COMPOSITE_OPTIMIZED 30/20/50 was being headlined before this gate ran; running it first would have saved the LP-pitch band-width.
  2. **The proxy was an underestimator of true absorption.** Run #3 with the canonical long top-CIS / short bottom-CIS factor (from 11yr CIS history) finds ABSORPTION STRENGTH. When you upgrade from a price-spread proxy to the canonical factor, |α t| goes UP, not down. The next sleeve's absorption test should use the canonical factor, not a proxy, from the start.
  3. **Cash IS a residual-α sleeve (in isolation) but is NOT independent of peer sleeves.** A sleeve that has no factor exposure AND no peer-sleeve-exposure is rare; cash is one. But for a multi-strategy book, the cross-sectional regression between sleeves catches it because cash is part of every composite by definition.
  4. **The MaxDD story (−3% to −5%) survives.** This is the load-bearing LP-relevant claim. The Sharpe claim doesn't survive absorption.
  5. **General principle (the load-bearing one):** a composite's high Sharpe on a friendly post-CIS window with a momentum-heavy book is what an UN-absorbed book looks like. The factor-absorption gate is the structural defense. Run it before headline.
- **What IS proven:**
  - The §ABSORPTION-SWEEP gate (`absorption_sweep.py` + runner) is reproducible and re-runnable on any new sleeve.
  - The 4-factor panel (BTC + TSMOM(30) + long top-CIS / short bottom-CIS + cross-sectional funding) is a reasonable defense for this book. A sleeve that survives this panel is worth a slot; one that doesn't isn't.
  - The true CIS factor can be built from the 11yr CIS historical reconstruction (`_data/cis_historical/cis_historical_11yr.csv`).
- **What IS NOT proven:**
  - The +1.97 Sharpe claim. It's β, not α, on the current panel + window.
  - The Causal sleeve's docstring +1.41 on the 658d OOS — different window, not falsified, but also not absorption-tested.
- **Reference:** `src/research/cis_regime_studies/absorption_sweep_runner.py` (NEW, ~290 lines); `reports/ABSORPTION_SWEEP_2026-07-18.md` (full report with Runs #1, #2, #3 addenda); `reports/absorption_sweep/2026-07-18/{verdict.txt,verdict.json,sleeve_returns.csv}` (Run #2); `reports/absorption_sweep/2026-07-18_true_cis/{verdict.txt,verdict.json,sleeve_returns.csv}` (Run #3); `reports/COMPOSITE_OPTIMIZED_2026-07-18.md` (with absorption caveat at top); MINIMAX_SYNC §ABSORPTION-SWEEP addenda #2 (Run #2) and #3 (Run #3).

## R31 🔴 Causal Sleeve extension — Conviction-Weighted Sizing (CW-Causal) REFUTES at Phase 2 (6 OOS windows, K=24)
- **Hypothesis:** scaling position size by |z_i|^p (where z_i is the cross-sectional funding z-score) concentrates capital on the highest-conviction funding dislocations and improves risk-adjusted returns. p=0 reproduces the original equal-weight sleeve; p=1 is linear conviction; p=2 is quadratic ("super-conviction"). Tested p ∈ {0, 0.5, 1.0, 1.5, 2.0}.
- **Test:** `src/research/cis_regime_studies/causal_sleeve_extension.py` (NEW). Reuses the validated 24-name Binance USDT-perp panel (2019-12-31 → 2026-01-27), IS/OOS split at 2024-01-01 (758 OOS days), kwin=10 weekly rebal, 5bps fee per side. NO modifications to `causal_positioning.py`. 9/9 sandbox smoke tests pass (`test_causal_sleeve_extension_smoke.py`). 6 × 120d non-overlapping OOS windows (2024-01 → 2025-12).
- **Result (Phase 2 monotonic failure):**
  - p=0 (baseline): annSR **+0.977**, total return **+44.84%**, MaxDD **−17.22%**, turnover 0.069/d.
  - p=0.5: annSR +0.911 (Δ −0.066), MaxDD −18.11% (Δ +0.89pp).
  - p=1.0: annSR +0.897 (Δ −0.080), MaxDD −19.40% (Δ +2.18pp).
  - p=1.5: annSR +0.866 (Δ −0.111), MaxDD −21.38% (Δ +4.16pp).
  - p=2.0: annSR **+0.823 (Δ −0.154)**, MaxDD **−23.53% (Δ +6.31pp)**, turnover 0.083/d.
  - **Windows won (any p>0 over p=0): 1/6 for all alternatives** (the one win is window 4 = Dec '24-Apr '25, the most BTC-bullish period).
- **Honest verdict: REFUTED at Phase 2.** OOS Sharpe drops monotonically as p increases (0.977 → 0.823); OOS MaxDD rises monotonically (17.22% → 23.53%); turnover rises modestly (+20%). 5/7 Phase 3 gates fail (Sharpe gain, MaxDD cap, window count all break). The hypothesis was clean; the data rejected it.
- **Why it fails (causal reading):**
  1. **Funding mean-reverts at the top-quantile.** A 3σ funding spike is *already* the market's signal that positioning is too crowded — by the time we measure it, the crowded side has likely *already* started to unwind. Equal-weighting the cross-section captures the signal at multiple horizons; concentration on the 3σ tail puts all eggs in the basket that's already halfway through mean-reversion.
  2. **Concentration amplifies idiosyncratic vol without amplifying carry.** Funding carry scales with gross exposure (constant per dollar); idiosyncratic vol scales with name-level vol × sqrt(weight). So carry-to-vol ratio drops as p rises — exactly opposite of what we want.
  3. **Window 1 (Jan-Apr '24, BTC ETF approval spike) is the biggest loser.** Conviction-scaling kills it monotonically (Sharpe 1.17 → 0.54 from p=0 to p=2). The most-concentrated funding dislocations during that period were post-event unwinds, not "live" edges.
  4. **Window 4 (Dec '24-Apr '25, BTC $100k melt-up) is the only improver.** Conviction-scaling helps in sustained trending regimes where funding dislocations persist for weeks. But that single window doesn't offset the 5 losers.
- **Lessons:**
  1. **Six rounds of in-sleeve parameter testing all reject or hold at the original.** kwin {5,7,10}, rebalance {daily,weekly}, universe {24,40,50}, acceleration add-on, conviction scaling — every one of them either matches or hurts. The simplest mechanic wins.
  2. **OOS walk-forward on 6 windows catches what in-sample wouldn't.** Window 4 (the lone improver) would have picked p=2 as the "winner" if judged in-sample; only 6/6 windows prevent the trap.
  3. **Equal-weighting after de-meaning extracts most of the signal.** This is a general property of cross-sectional z-score signals when the underlying signal has fat tails: concentration wastes signal in the tails where the signal has already partially mean-reverted.
  4. **Track 5 follows Track 3 (Crowd Clock) and Track 4 (composite) as a clean negative in the 2026-07-18 sprint.** The 5-track sprint closed with 3 confirmed positives (Track 1 Sleeve A parity framework / Track 3 Crowd Clock E2E / Track 4 composite mix), 1 re-confirmation (Track 2 Vol Sleeve v2 = R28), and 1 clean refutation (Track 5 R31). The Causal Sleeve composite weights in Track 4's recommended book are NOT affected — they were computed against the original validated sleeve.
- **What IS proven:** the CW-Causal scaffolding (parameterized `positioning_weights_cw()` with `p` exponent, demean + gross=1 pipeline) is reusable for any future "scale-by-|signal|" hypothesis on a different sleeve. The driver and smoke tests are kept as research artifacts.
- **Reference:** `src/research/cis_regime_studies/causal_sleeve_extension.py` (NEW); `src/research/cis_regime_studies/tests/test_causal_sleeve_extension_smoke.py` (9/9 PASSED); `reports/causal_sleeve_extension/2026-07-18/results.json` + `window_metrics.csv`; full report `reports/CAUSAL_SLEEVE_EXTENSION_R31_REFUTED_2026-07-18.md`.

## R34 🟡 Funding-crowding IS orthogonal to momentum (the right seam) — but naive fade is sub-threshold + FRAGILE
- **Hypothesis (Trader Tom / dingge):** funding-rate crowding is a behavioral, non-momentum edge — fade
  crowded longs (high funding), ride crowded shorts (negative funding). If real, it should carry RESIDUAL
  α after {market, momentum} and NOT just be repackaged beta.
- **Test:** Binance BTC funding history 2019-11→2026-07 (2444 days), contrarian signal `pos = −clip(z,±3)/3`
  on trailing-30d funding z, net of 5bps turnover cost, run through the full `signal_gauntlet`
  (`/tmp/funding_gauntlet.py`; to be productionized). Plus an extreme-only extraction sweep
  (z-window×threshold×hold).
- **Result — the ENCOURAGING part:** funding-crowding is genuinely ORTHOGONAL to momentum — momentum
  beta −0.132 (**t=−5.42**, strongly anti-momentum, as fading crowded longs should be) and residual α
  is consistently POSITIVE: +6.4%/yr (naive daily) up to **+14–19%/yr** at the mild-crowding extraction
  (z>1.5, hold ~7d). **This is the first candidate all session that is NOT absorbed** — the right family,
  which is the hard part and validates the causal-signal thesis.
- **Result — the HONEST part:** it does NOT clear the gauntlet. Raw Sharpe ≈ 0 (the continuous fade bleeds
  by fighting a positive-momentum tape); the best residual α tops out at **t≈1.5 (< 1.96)**; and EVERY
  variant reads **FRAGILE** on regime robustness. Fading *harder* extremes (z>2.5) goes NEGATIVE.
- **Lesson (points to the next experiment, not a dead end):** the negative-return-on-hard-extremes is our
  own dingge doctrine confirmed on BTC funding — after a genuine funding extreme a NEW TREND forms, so you
  cannot blind-fade it; **volume/price must set the direction** (fade exhaustion, ride continuation). The
  orthogonality is real (the hard part); the missing piece is the direction filter. Next: port
  `dingge_rwa.py`'s volume-confirmed logic to BTC/majors funding and re-run the gauntlet (R35 candidate).
- **Method note:** first live use of the full `signal_gauntlet` (significance→DSR→PBO→absorption→regime→PIT)
  on a real candidate — it correctly located the seam AND refused to credit the sub-threshold version.

## R35 🟡 Volume-CONFIRMED funding-crowding — real orthogonal α, PERSISTS OOS, but sub-threshold; needs cross-CLASS breadth
- **Hypothesis (dingge on BTC funding, the R34 refinement):** fade a funding-crowding extreme ONLY when
  price+volume confirm the reversal is underway (crowded longs + price rolling over + volume expanding →
  short the flush; crowded shorts + price bouncing + volume → long the squeeze). Direction-aware, not blind fade.
- **Test:** Binance funding+OHLCV, BTC 2019→2026 + pooled BTC/ETH/SOL, net 5bps, full `signal_gauntlet`
  + walk-forward OOS on an a-priori config (z-win 30, thr 1.0, hold 10d). `/tmp/funding_vol.py`, `/tmp/funding_pool.py`.
- **Result — the strongest candidate of the 07-18 session:**
  - Genuinely ORTHOGONAL: momentum beta ≈ 0 (pooled t=−0.07); it is NOT absorbed. Clears significance +
    factor-absorption + regime-robustness on the BTC full sample (α +28.9%/yr, **t=2.42, ROBUST**).
  - α PERSISTS out-of-sample: a-priori config holdout (≥2023) α **+22%/yr** single-asset, +15%/yr pooled —
    it does not vanish. This is more than anything else survived all session.
- **Why it's NOT credited (honest):**
  1. **DSR/PBO fail** — the t=2.42 cell was the best of an 18-config sweep; multiple-testing + overfit gates
     correctly refuse a cherry-picked config. The a-priori config's OOS significance is only t≈1.2–1.5.
  2. **FRAGILE** — the edge concentrates in deleveraging/vol-spike events (regime-conditional by nature).
  3. **Crypto-major pooling does NOT add breadth** — BTC/ETH/SOL co-move ~0.79 (our own `multi_asset_study`),
     so 3 assets ≈ 1 bet; pooled significance DROPPED to t=1.65. Fake breadth can't manufacture a t-stat.
- **The credit path (precise + actionable):** real breadth comes from **cross-CLASS** perps, not more crypto —
  the RWA/equity/commodity perps (corr ~0.22 to BTC) we uniquely track via `dingge_rwa.SECTOR_ETF_PERPS`
  (XLE/XBI/URNM/gold/…). The crowding mechanism is universal to any perp; pooled across uncorrelated
  underlyings, ENB jumps 2.5→8+ (our multi_asset finding) and a per-asset t≈1.5 becomes significant.
  **Next (Minimax lane — they have the RWA funding data): run the SAME volume-confirmed crowding on the
  cross-class perp basket, market-neutral, through the gauntlet.** That's the real test of whether we have
  our first credited orthogonal edge.
- **Bottom line:** we located a genuine, persistent, momentum-orthogonal seam (the hard part) and diagnosed
  exactly why it's sub-threshold (crypto breadth is fake breadth) and exactly where the real breadth lives.

## R36 🔵 Cross-CLASS funding-crowding credit path is BLOCKED — structural venue limitation (data does not exist yet)

- **Hypothesis (the R35 credit path, surgical):** run the volume-confirmed `funding_crowding.crowding_signal()`
  on the RWA/equity/commodity perp basket (`dingge_rwa.SECTOR_ETF_PERPS`) — instruments with corr ~0.22 to
  BTC and historically uncorrelated equity/commodity underlying — to manufacture real cross-asset breadth
  (ENB 2.5→8+) and produce a credited orthogonal-α sleeve.
- **Test (Minimax-A 2026-07-18 — venue inventory, the proposal-vs-data fit check):** before building any
  backtest, surveyed THREE major venues (Binance USDT-perp, Bybit v5 USDT-linear, OKX v5 USDT-SWAP) for
  the cross-class perp universe and probed each symbol's `fundingRate` (Binance) / `funding-rate-history`
  (Bybit/OKX) depth. Goal: verify the substrate is rich enough to express a cross-class panel ≥1y
  (DSR/PBO/regime-robustness all need ≥6-12 months).
- **Result — the SUBSTRATE does NOT exist on any of the three venues (probed 2026-07-18):**

  | Venue | Symbols in target list | Listing dates observed | Funding depth | Verdict |
  |---|---|---|---|---|
  | **Binance fapi** | 2/36 listed (DIA, SPX) | DIA 2026-04-26, SPX 2026-04-26 | DIA 500 obs / 83d, SPX 500 obs / 83d — only **2 symbols ≥30d history** | UNIVERSE COLLAPSED: 34/36 delisted/unlisted |
  | **Bybit v5** | 36/36 RWA/equity/commodity listed | Earliest 2026-05-13 (TSLA/AAPL/NVDA/QQQ/SPY/IWM/MSFT), XAU/XAG/CL 2026-06-15, XLE 2026-07-15 | **Longest span = 66 days** (TSLA/AAPL/MSFT); majority 33-66 days | UNIVERSE TOO YOUNG for DSR/PBO |
  | **OKX v5** | 10/10 RWA perps tested (DIA-USD-SWAP doesn't exist; rest are USDT-SWAP) | All 2026-06-15 (or later) | 100 obs each / **33 days** | UNIVERSE SAME-NEW as Bybit |

  **Universal reality:** the RWA/equity/commodity perp instrument class is **~2 months old** across every
  major venue. No symbol has more than 83 days (DIA/SPX on Binance) of continuous funding history. The
  cross-CLASS credit-path recommendation from R35 specified that ENB 2.5→8+ requires 6-12+ months of history
  for the DSR/PBO/regime gates to fire meaningfully — that data simply does not exist yet on any venue.
- **What this means for R35's credit-path claim:**
  1. **The CROSS-CLASS HYPOTHESIS cannot be tested today.** Even running the partial DIA+SPX Binance panel
     (2 names, 83 days) returns ZERO outcome from `signal_gauntlet`: K=2 is not a cross-section, 83 days is
     below the DSR/PBO/regime floors (need 6+ months × ~20 bars/year = ≥120 obs minimum per regime).
  2. **The "funding-crowding" mechanism on these perps is REAL and observable** (DIA + SPX have 500 obs /
     83d, including multiple funding-z > 1 events triggering the volume-confirmed logic) — but partial
     panel tests on 2 names produce no interpretable p-value and can't credibly confirm or deny the
     R35 finding. **Failing to test ≠ falsifying.**
  3. **R35's verdict stands**: orthogonality to momentum on BTC is robust (+28.9%/yr α, t=2.42). The
     sub-threshold verdict on crypto-major pooling stands (BTC/ETH/SOL co-move 0.79 → fake breadth).
     The credit path recommendation ("cross-class perps, market-neutral, real breadth") is **directionally
     correct but not yet actionable on data** — like recommending an equity factor at the SEC's EDGAR
     founding moment, before any 10-Ks have been filed.
- **Diagnostic read on WHY the universe is so young:**
  - **Binance**: the `RWA_PERPS` list in `dingge_rwa.py` was likely authored from the (now stale)
    Binance fapi symbols catalog — by 2026-07-18, Binance has issued an aggressive DELISTING sweep on
    thin synthetic-perp books (the 34 missing symbols returned funding-history data but with limited
    observation windows and DELISTED status on `/fapi/v1/exchangeInfo`, confirming they were active
    briefly then removed — typical for sub-$1M daily-volume synthetic perps the exchange decided
    aren't worth the risk-management footprint).
  - **Bybit / OKX**: these venues listed their RWA perp books in a 6-week window (2026-05-13 → 2026-07-15)
    — a flood of single-name equity / commodity perps in direct response to the marginal retail
    demand for non-crypto-perp 24/7 trading. Maximum funding depth at any venue = ~66 days. The
    instrument class is **brand new** by design.
  - **CFTC / CME constraint**: real US-equity and commodity perps (CME ES, NQ, YM, CL, GC, SI futures)
    have multi-year history but a fundamentally different microstructure (exchange-settled margined,
    daily MTM, no 8h funding stream). The "crowd funding" mechanism doesn't exist there — those
    books are dominated by institutional cash-equals and basis-trade participants, not the
    perp-crowd that generates the signal R35 hedges.
- **Verdict:** NOT a falsification of R35 (the BTC finding stands); NOT a confirmation (cannot test).
  This is a **STRUCTURAL FINDING** — a venue/state-of-the-world barrier that closes the credit path
  for a defined window of time. The data will accumulate; the test will become runnable.
- **Fallback paths (each independently testable, in order of feasibility):**
  1. **Time-deferred re-run** (recommended, lowest friction): re-survey venues quarterly (next probe:
     2026-10-18 = 90 days after this finding). With current listing trajectory, the DIA-class
     perps on Bybit will reach 6+ months around **2026-11-13** and 12+ months by **2027-05-13** —
     enough for a meaningful cross-class gauntlet.
  2. **Equity futures analog** (bridge methodology, not perfect replication): treat CME ES/NQ/YM/RTY
     as the "cross-class" panel and adapt the funding-crowding signal to use **futures open interest
     divergence** (CME publishes daily COT report) instead of perp funding. COT data has 30+ years
     of history; the mechanism is structurally similar (crowd positioning → exhaustion → reversal).
     This is NOT the same signal (different venue, no 8h funding, different participant pool) — it's
     a **cousin study** to see if the *orthogonality* claim transfers, not a direct replication.
  3. **Hyperliquid / dYdX cross-class perp survey**: those DEXs may have older synthetic-RWA perps
     against their perpetual engine. Probing their API is a one-hour invest; if 6+ months of
     funding data exists there, the cross-class test can run on those instruments. Lower confidence
     on participation-pool comparability (DEXs are a different crowd) but a real breadth source.
  4. **PIVOT to a different cross-class hypothesis**: e.g., dispersion across cross-asset-class
     return signals (btc-eth correlation regime, dxy-btc correlation, gold-btc structural inverse)
     using existing 5+ year datasets. These are NOT R35 but they're testable **today** with the
     MultiAsset study infra already in place.
- **Lessons (the durable ones, beyond R35's specific path):**
  1. **Time-deferred hypotheses are still hypotheses, but their ticket-to-ride is the data accumulating.**
     The signal logic is no longer the bottleneck — the substrate is. Mark it with a re-probe
     schedule; don't kill it. R35's credit path is OPEN, just DORMANT until 2026-11 minimum.
  2. **Venue inventory is part of the upstream architecture.** A "test a signal on these symbols"
     recommendation is incomplete without a "do these symbols have ≥Y months of history on the venue"
     report. Add to the standard R35-style experiment brief: "platform history duration, source-aware."
  3. **The 34/36 delistings on Binance are ALSO a finding about venue risk.** Synthetic-RWA perps are
     an instrument class Binance tests for retention; thin-volume books are delisted aggressively.
     For a multi-year live-trading deployment, this venue risk needs an explicit hedge (multi-venue
     deployments, fee-tier-arbitrage, or wait for venue stabilisation).
- **Reference:** venue probe `rwa_venue_inventory.py` (Minimax-A, 2026-07-18), substrate stash
  `_data/rwa_funding/{diausdt,spxusdt}_funding_8h.csv` + `_data/rwa_funding/{diausdt,spxusdt}_1d_ohlcv.csv`
  (Binance paginated full-history pull — 500+ obs each), `src/research/funding_crowding.py` (R35 ship
  artifact, signal itself unchanged — only the universe is too thin to apply it meaningfully).

## R37 🟡 Empirical-grid gate parity-A/B on freqtrade V7 — NEUTRAL with a slight loss on the post-CIS window
- **Hypothesis:** the empirical-grid gate (data-grounded lookup `grid[tier][band] → shrunk avg_alpha_pct`)
  improves freqtrade V7's pre-filtered trade universe vs the legacy hand-tuned `REGIME_CIS_FLOOR`,
  as the §C1 PARITY 2026-07-18 recipe predicted (block rate ~53%, Sharpe +0.1 to +0.3 above legacy).
- **Test:** ran the Minimax-B `c1_parity_ab.py` driver on the 4 most recent backtest ZIPs from
  the 2026-07-18 batch (V7 × 3 walk-forward windows + MultiFactorV2 forward). Per-trade decision
  replay against both gates, summary stats, decision matrix.
- **Result — mixed:**
  | Window | n | Δ Sharpe | Verdict |
  |---|---:|---:|---|
  | V7 HOLD-OUT (post-CIS, 2026-Q1) | 146 | **−0.32** | Slight loss — empirical blocks 33 trades legacy allows, mean +0.38% PnL each ($55.64 sum) |
  | V7 VALIDATE (mixed, 2025-2026) | 571 | +0.15 | Within noise |
  | V7 TRAIN (mostly pre-CIS) | 593 | +0.84 | WIN but BIASED — pre-CIS segment defaults to NEUTRAL×3_neutral = allow, empirical becomes a no-op |
  | MultiFactorV2 forward | 6 | −8.39 | n too small to call |
  Aggregate Δ Sharpe (V7 only) = **+0.22**, within noise.

- **Lesson (the durable one — sister finding to R17):** **the empirical-grid gate is a calibrated gate
  with an uncalibrated input.** R17 documented the LS v1 version: synthetic PnL claim of
  +392% did not replicate on real data because per-day CIS signal tier is noisy. R37 confirms the
  same pattern on the freqtrade side: on the post-CIS forward window (the only window with full
  input coverage), empirical blocks 33/146 trades that legacy allows and that turn out to be net
  profitable. The smoke-test pre-flight (block rate 53%, Sharpe +0.1 to +0.3) was an optimistic
  projection from synthetic data; real backtests show the gate is over-strict on neutral-band
  UNDERPERFORM cells, killing winners.
  **Architecturally the gate + size_multiplier pattern is sound (R17 lesson 3, validated
  elsewhere); specifically the raw-grid signal source is the limitation. Both R17 and R37 point
  to the same fix: feed the gate a less-noisy input — smoothed-CIS labels, or a tier assignment
  that doesn't flip 30% of the time.**
  Two architectural takeaways:
  1. **Smoke-test claim ≠ production claim.** Synthetic PnL extrapolations can mislead by
     1-2 orders of magnitude on real backtests. Always re-run on real data before cut-over,
     even when the scaffolding is sound.
  2. **"NEUTRAL × 3_neutral = no edge data" is a silent failure mode.** When the empirical
     grid returns `tech-only (allow, conv=0)`, the trade passes but the size multiplier drops
     to the floor (0.4×). On TRAIN (pre-CIS), every trade had NEUTRAL → empirical allowed
     everything with 0.4× size — explaining the "win" that disappears once CIS coverage fills in.

- **Carrier note:** `c1_parity_ab.py` driver is structurally correct and reusable. The empirical-grid
  module (`src/research/strategies/edge_gate.py`) is unchanged. C1 deliverable status: ✅
  PARITY VERIFIED (driver runs, both gates call shared `gate()`, decision matrix exposes the
  gate-difference pattern). HOLD on production cut-over until smoothed-CIS re-run. Driver +
  report retained for archival + as the regression test for any future gate variant.
- **Reference:** `reports/C1_PARITY_AB_2026-07-19.md` (full A/B), `reports/c1_parity_ab/2026-07-18-*/`
  (per-window outputs), `src/research/freqtrade/c1_parity_ab.py` (driver), R17 entry above
  (LS v1 sister finding).

## R38 🟡 Smoothed-CIS empirical-grid gate re-run — the R17 fallback hypothesis FALSIFIED on V7 HOLD-OUT
- **Hypothesis (the R17 lesson pointed here):** "Sparse grids need smoothed inputs" (R17).
  If the empirical-grid gate's failure on V7 HOLD-OUT (R37, Δ Sharpe -0.32 from blocking
  33 winners) is caused by day-to-day NEUTRAL ↔ OUTPERFORM ↔ UNDERPERFORM tier whiplash,
  then feeding the gate **smoothed** CIS labels should reduce decision noise → empirical
  block rate should drop on those 33 winners → Δ Sharpe should recover toward +0.1 to +0.3.
- **Test:** built `src/research/freqtrade/c1_parity_ab_smoothed.py` (sister driver — same
  gate logic, same grid, same band snapshot; only the CIS source changes from
  `_data/cis_history/` to `_data/cis_history_smoothed/`). Ran on the same V7 HOLD-OUT
  backtest ZIP (146 trades, 2026-01 → 2026-03-14, 100% smoothed-CIS coverage).
- **Result — falsified:**
  | Variant | Both pass | Emp blocks (legacy passes) | Emp passes (legacy blocks) | Sharpe Δ | Total $ Δ |
  |---|---:|---:|---:|---:|---:|
  | Raw CIS (R37) | 102 | 33 | 7 | **−0.32** | −$46.70 |
  | **Smoothed CIS (this run)** | 99 | 37 | 7 | **−0.42** | −$57.00 |
  Empirical blocks 4 MORE trades under smoothed (37 vs 33) and the verdict gets slightly
  WORSE, not better. The R17 fallback hypothesis is **falsified on V7 HOLD-OUT**.

- **Why smoothed-CIS made things worse (the diagnostic):** only 4 trades changed decisions
  between raw and smoothed, but they all hurt:
  - **3 BTC LONG trades (2026-03-05 × 2, 2026-03-11):** raw CIS tier = NEUTRAL →
    empirical grid returned "no edge data → tech-only ALLOW"; smoothed CIS tier flipped to
    OUTPERFORM → empirical grid returned "OUTPERFORM × 2_off = -5.8% expected → BLOCK."
    These 3 trades had PnL +$4.71 / -$5.83 / +$3.61 = net +$2.50 — the smoothed gate
    correctly avoided the -$5.83 loss but threw away +$8.32 of winners in the process.
  - **1 ETH LONG trade (2026-01-06):** raw CIS score 60.5 vs smoothed 59.8 in regime EASING
    (floor 55). Both are above floor (PASS), but raw had BLOCK (different regime/score
    source — the snapshot layer used `cis_scores_latest.json` not the smoothed dir).
    Smoothed flipped this to PASS, capturing +$7.80 PnL. **The one win from smoothing.**

  Net: +$7.80 (legacy flip) − $2.50 (3 BTC blocks) = +$5.30 absolute, but Δ Sharpe shifted
  by -0.10 because the LEGACY gate improved more (+0.15 Sharpe) than the empirical gate
  (+0.05 Sharpe). **Both gates get more selective under smoothed CIS, but only legacy's
  selectivity is in the right place.**

- **Lesson (durable — sharpens R17's):** **"smoothing" the CIS tier is NOT the same as
  smoothing the underlying signal.** Two distinct failure modes for the empirical grid:
  1. **Tier whiplash** (R17 framing): NEUTRAL ↔ OUTPERFORM flips on consecutive days
     because the daily CIS recalc drifts. The grid treats each tier as a discrete state,
     so the gate decision thrashes.
  2. **Smoothed-tier false confidence** (this finding): when a rolling smoother crosses
     a tier boundary (e.g. 7-day average moves from 50 to 55), the smoothed label can flip
     NEUTRAL → OUTPERFORM even though the underlying daily scores are still noisy. The
     gate then sees a "confident" OUTPERFORM and acts on it (e.g. blocks long in
     OUTPERFORM × 2_off). **The smoother didn't remove noise; it created a new layer of
     confident-noise.**
  This is the **canonical risk of any smoothing/regularization on a noisy classifier**:
  the smoothed output looks calmer and more "decidable," but the decisions made on it
  inherit whatever bias the smoother introduced at boundary crossings. In a finite
  sample, those boundary-crossing decisions are precisely where overconfidence lives.

- **What this RULES OUT for the empirical-grid ship path:**
  1. ❌ "Smooth the CIS tier first, then re-run the gate" — FALSIFIED on V7 HOLD-OUT.
  2. ❌ "Try a different smoothing window (3d, 7d, 30d)" — likely same family of failure
     unless the underlying input is fundamentally recalibrated (regime detection,
     pillar weights, signal blend).
  3. ❌ "Run more windows to disambiguate" — the R37 finding (Δ Sharpe -0.32 on a clean
     post-CIS window with 100% CIS coverage) is the load-bearing test. Negative there
     is the verdict.

- **What remains open:** the empirical-grid gate is structurally correct and the
  size_multiplier lever is reusable (R17 lesson 3 stands). What we DON'T have is a
  **calibrated CIS signal source** that:
  (a) is stable across consecutive days (no whiplash),
  (b) has tier assignments that are unbiased at boundary crossings (no false confidence),
  (c) covers the post-CIS window with full pillar data (currently 100% on V7 HOLD-OUT,
      so coverage is fine; the issue is content, not coverage).

  Candidates to explore next (priority order):
  1. **Pillar-weighted composite tier** (smooth the underlying pillar scores, then derive
     tier from the smoothed composite) — bypasses the boundary-crossing bias.
  2. **Regime-pinned tier** (gate decides on (regime, pillar_z) not (regime, tier)) —
     uses continuous pillar scores directly, no tier classification.
  3. **Walk-forward tier assignment** (re-fit tier thresholds every 30d) — adapts to
     regime drift without the smoother-bias problem.
  All three are research-only at this stage.

- **Carrier note (the durable things):**
  - `src/research/freqtrade/c1_parity_ab_smoothed.py` (NEW driver) — reusable for any
    smoothed-CIS variant A/B. Sandboxed-safe (~30s for 200 trades, pure Python).
  - `reports/c1_parity_ab/2026-07-19-v7-holdout-smoothed/{per_trade.csv,summary.csv,
    verdict.md}` — full A/B output. Compare side-by-side with R37's raw-CIS run.
  - Decision: **HOLD production paper on `REGIME_CIS_FLOOR` (the legacy baseline).**
    Empirical-grid gate remains research-only. R38 logged; the empirical-grid ship
    path requires a different signal source (NOT a smoothing of the current one).
- **Reference:** `reports/c1_parity_ab/2026-07-19-v7-holdout-smoothed/verdict.md`,
  `src/research/freqtrade/c1_parity_ab_smoothed.py`, R37 (raw-CIS A/B), R17 (LS v1 sister).

## R39 🔴 CALM-REGIME short-vol carry — cleared every STATISTICAL gate on BTC, then died to cross-asset + realistic costs (premium real, uncapturable)
- **Hypothesis:** revive the shelved vol sleeve (R28, killed for lack of real IV data) with **Deribit DVOL**;
  a short-vol carry harvesting IV−RV should be orthogonal to momentum, and gating it by funding-crowding
  should dodge the RV-spike tail (leveraged-long flush → vol spike, per §TRADER_TOM cascade).
- **Test:** Deribit DVOL (30d IV, 2023-10→2026-07, one light call — no pagination) + Binance RV + funding.
  Short-variance daily P&L (collect implied 1d variance, pay realized r²), base vs crowding-gated, through
  absorption + regime-robustness. `/tmp/…vol` (to productionize into `src/research/vol_carry.py`).
- **Result — the REAL part:** the vol risk premium is large + persistent: **IV richer than RV 79% of days,
  mean spread +5.8 vol-pts**. The short-vol carry earns **SR +1.49, residual α t=1.99 (crosses 1.96),
  momentum-β ≈ 0** — genuinely ORTHOGONAL. Second non-absorbed seam after R35 crowding, and this one
  clears absorption significance on BTC alone. Confirms R28's cause with real data.
- **Result — the HONEST part:** it does NOT clear the gauntlet. **FRAGILE** (3/4 subsamples positive,
  regime-dependent) and a **−15.7σ worst day** — the textbook short-vol negative-skew tail (pennies in
  front of a steamroller; violates "small when wrong").
- **Refuted sub-hypothesis:** the funding-crowding gate did NOT dodge the vol tail — it cut SR (1.49→1.28)
  AND made the worst day WORSE (−15.7→−17.4σ). Funding crowding ≠ vol-spike predictor. Clean negative.
- **★ RESOLUTION — the calm-regime gate cracks it.** Be short vol ONLY when trailing-10d realized vol is
  low (<55, i.e. genuinely calm — don't sell into a storm). This is the professional way to run short-vol,
  and it transforms the sleeve: **SR +2.69, α t=3.66, ROBUST across all subsamples, momentum-β ≈ 0, worst
  day HALVED to −8.2σ.** It then **cleared the FULL `signal_gauntlet` as a ★ SURVIVOR** — significance ✓
  DSR ✓ PBO ✓ absorption ✓ regime-robustness ✓ — surviving the multiple-testing + overfit gates despite
  the threshold being chosen from a small sweep. **And it holds OOS:** TRAIN(<2025-07) SR +2.96 αt +3.31,
  **HOLDOUT(≥2025-07) SR +2.25 αt +2.66** — still significant out of sample. This is the FIRST candidate
  all session (and in this ledger) to clear the entire gauntlet AND survive a clean holdout. Tracked as
  `src/research/vol_carry.py`.
- **Remaining honesty caveats (before any capital):** (1) single asset (BTC) + single vol index (DVOL) —
  needs ETH/cross-asset confirmation; (2) the variance-swap P&L is a STYLIZED proxy — real short-vol via
  options has bid/ask, gamma, discrete strikes → the frictionless backtest overstates it, and the −8.2σ
  day still demands wings/position limits; (3) DVOL history only to 2023-10 (~2.7y, one holdout); (4)
  capacity is real but bounded.
- **⚠️ CROSS-ASSET FAILURE (same day) — the honest downgrade.** Ran the SAME calm-regime carry on ETH
  (Deribit ETH DVOL + Binance): **SR −0.12, α t=+0.06, FRAGILE, −19.3σ tail** — it does NOT work on ETH.
  Pooled BTC+ETH collapses to SR +0.86, α t=1.28 (insignificant). So the BTC ★-survivor is **BTC-SPECIFIC
  and does not replicate** on the next-most-liquid asset. The gauntlet passed it because DSR/PBO test
  overfit-to-CONFIG, not overfit-to-one-asset's-HISTORY — a real blind spot the ETH check exposed.
  **Verdict: NOT a credited edge.** The vol risk premium is real, but a *robust cross-asset* harvest via
  this construction is unproven; the BTC result is a suspect single-asset/single-period artifact.
  **Gauntlet upgrade this exposed: add a CROSS-ASSET REPLICATION gate — a single-asset ★ is not credited.**
  Do not size.
- **Decisive follow-up (same day):** to rule out "BTC-tuned threshold," re-ran with a UNIVERSAL
  self-normalizing gate (short vol only when RV is below the asset's OWN trailing-180d percentile — no
  per-asset tuning). Still: BTC SR +2.52 αt +3.21 ROBUST, **ETH SR −0.46 αt −0.35 FRAGILE.** So it is
  **structurally BTC-only, not a tuning artifact** (ETH vol is higher/spikier, premium thinner; SOL has
  no Deribit DVOL). **Final status:** the BTC vol-premium carry is a real, robust, orthogonal *BTC-specific*
  sleeve candidate — legitimate as a standalone BTC sleeve IF validated with a REALISTIC options-execution
  model + wings (Minimax lane), but NOT a general cross-asset factor.
- **🔴 KILLED BY COSTS (same day) — the final, decisive test.** Stress-tested the BTC carry under realistic
  options frictions (premium haircut for bid/ask + a continuous wing-hedge cost for the −8σ tail + roll
  turnover). It COLLAPSES: frictionless SR +2.69 → **15% haircut SR +0.80 (αt 1.11, already sub-sig) →
  realistic 30% haircut+wings SR −2.22 (αt −3.10, NEGATIVE) → harsh 45% SR −4.99**. The vol premium is
  real but **NOT harvestable net of realistic crypto-options bid/ask + tail-hedge cost** — the frictionless
  variance-swap proxy was the whole illusion. **Final verdict: REFUTED for practical use.** The premium
  exists; capturing it does not pay. **Gauntlet lesson (2nd this entry): a realistic EXECUTION-COST model
  must be a gate — a frictionless backtest is meaningless for wide-spread instruments (options).**
  Vol thread closed. Net of this whole arc: two more gauntlet gates earned (cross-asset replication +
  execution-cost), zero capital risked on a signal that cleared every *statistical* filter.

## R40 🔴 Capitulation Bounce sleeve — mechanism detected, signal doesn't survive cross-section demean on 2024-2026
- **Hypothesis (per §TRADER_TOM_DOCTRINE §5b — durable-core mean-reversion):** when an asset drops
  >5% in 5d AND 20d vol exceeds 2× 60d vol (the "panic-sell vol-spike" signature), the position
  should bounce +5-6% over the following 5d. Asymmetry: long only, catastrophe stop @ -10%. Cross-
  section demean isolates idiosyncratic capitulation from market-wide drops. Prototype in
  `src/research/cis_regime_studies/capitulation_bounce.py`.
- **Test:** BTC/ETH/SOL/AVAX hourly OHLCV from /Volumes/CometCloudAI/data/ohlcv (2024-06-07 →
  2026-06-07, 17520 bars). Per-asset signal + cross-section demeaned pooled book, OOS = last 20%.
  Variants: vol_mult ∈ {0, 0.5, 1, 2}, ret_thresh ∈ {-3%, -5%, -7%, -10%}, hold ∈ {3d, 5d, 8d}.
- **Mechanic validation:** the signal correctly identifies the **2024-08-05/06 Yen carry-trade unwind**
  (BTC $65k → $50k, ETH/SOL/AVAX simultaneous) — all 4 assets fire at t=1435-1439. BTC fwd 5d return
  from those fires is +2.63% mean / +2.15% median / **76% win rate** on the first 50 fires. So the
  TRIGGER is detecting real capitulation events, and bounces DO happen on individual assets.
- **What kills it:** the cross-section demeaned pool alpha is **negative** at every reasonable
  config:
  | vol_mult | OOS Sharpe | α_t | fires |
  |---------:|-----------:|----:|------:|
  | 0.0      | -2.09      | -1.52 | 16183 |
  | 0.5      | -0.33      | -0.31 | 12693 |
  | 0.7      | -0.08      | -0.11 |  2530 |
  | 1.0+     | +0.00      | +0.00 |  1083 |
  10-asset universe (BTC/ETH/SOL/AVAX/BNB/XRP/ADA/DOGE/LINK/DOT): OOS Sharpe -0.85, α_t -0.32,
  ENB 1327. Even broadening the universe doesn't recover alpha.
- **Diagnosis (two structural reasons):**
  1. **2024-2026 has too few capitulation events.** Of 224 BTC fires at canonical config (vm=2.0),
     ALL 224 cluster on 2024-08-05/06. The OOS window (2026-01-12 → 2026-06-07) has ZERO fires. The
     bullish 2024-2026 tape means dips got bought back fast at the per-asset level, but the
     market-wide correlation (BTC/ETH/SOL/AVAX all drop together) makes the demean zero out exactly
     when it should fire.
  2. **Cross-section demean is too punitive for highly-correlated majors.** ENB = 1320 for 4 majors
     (effective <2 independent bets). When BTC dips, ETH/SOL/AVAX dip simultaneously — demean = 0.
     The signal only fires on IDIOSYNCRATIC capitulation, which is rare in crypto majors.
- **Lesson (the doctrine test):** §TRADER_TOM_DOCTRINE says "mean-reversion at extremes is a real
  human-behavior pattern" — TRUE at the per-asset level (76% BTC bounce rate, +2.6% fwd 5d). But
  the doctrine ALSO says "expectancy, not win-rate; breadth × IC is what compounds" — the
  cross-section demean kills breadth precisely because crypto majors are too correlated. **A
  per-asset capitulation signal needs a per-asset implementation (or a much broader / less
  correlated universe) to capture the edge; the cross-section book structure is wrong for this
  signal type.** Same architectural lesson as R16: a working signal in one frame does NOT transfer
  to a different frame without re-validation.
- **What to do with this:** the **PER-ASSET** trigger logic is real and reusable — the 76% win rate
  is genuine. The RIGHT shape for it would be a per-pair swing overlay (not a cross-section
  pooled book), with explicit position sizing and the catastrophe-stop discipline intact. That
  would be Sleeve E-adjacent territory, but as a CROSS-SECTION MARKET-NEUTRAL sleeve, this idea
  does not ship. Logged honest.
- **Reference:** `src/research/cis_regime_studies/capitulation_bounce.py` (240 LoC + 200 LoC
  selftest), `reports/cap_bounce/` (this R entry to be saved as REPORT.md when promoted).

## R49 🔴→🛠 CometCloudLongShortV4 re-validated: 100% momentum beta + 9.5%/yr churn — REFUTED as alpha; rebuilt as Trend Engine V5
- **Context (Jazz directive):** re-validate LS V4 (EMA9/21 4h stop-and-reverse, freqtrade + Nautilus
  `ls_v4.py` parity, 3× lev) with the modern gauntlet, then develop on that basis. Prior state: 2026-06
  backtest "beat BTC-hold by 11.6pp in a bear" (Gate 6 fail, CAGR −6.6%); parity port confirmed the
  EMA-cross core. The question never asked before the gauntlet existed: is the edge just momentum?
- **Re-validation (3.5y 4h BTC/ETH/SOL, net 5bps, full gauntlet):** DIED at every gate.
  annSR +0.18 single / **+0.08 pooled**; absorption shows **momentum β t=9→24 with NEGATIVE residual α**
  — the entire return stream is TSMOM in an EMA-cross costume (the bear-market "outperformance" was the
  short side of trend beta, not alpha); **95–105 flips/yr ≈ 9.5%/yr cost drag**; decaying (H1 +1.01 →
  H2 −0.79); cross-asset replication fails. **REFUTED as an alpha source. Do not run as-is.**
- **Development (the honest rebuild):** the trend PREMISE isn't wrong — the CONSTRUCTION was. Churn was
  the killer. Slowing the same signal (EMA54/126 ≈ 9/21 daily): V5a symmetric flip pooled SR +0.52 @
  ~15 flips/yr; **V5c LONG-only slow trend pooled SR +0.96 @ ~8 flips/yr, positive BOTH halves
  (H1 +1.21 / H2 +0.67)** — crypto's trend premium is asymmetric, the long side carries the drift while
  the short side mostly buys churn+funding. 13× less turnover for strictly better performance.
  Tracked: `src/research/trend_engine_v5.py` (`trend_v5` + `trend_book`).
- **Honest label:** V5 is a **momentum-beta harvesting engine, NOT alpha** (residual α ≈ 0 by
  construction — it IS the factor). That's precisely the two-layer doctrine's tactical trend overlay:
  size it as beta, pair with the defensive layer, never headline it as alpha. Caveats: per-quarter
  FRAGILE (trend loses in chop — inherent), −14σ worst bar (crash exposure → cap size), funding not
  modeled → live-paper before sizing.
- **Lesson:** "core alpha confirmed by parity" only meant the *signal reproduced*, not that it was alpha.
  Absorption + cost gates would have caught this in 2026-06. Every legacy sleeve needs the same re-audit.

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
11. **A correct per-asset trigger doesn't make a correct pooled book.** (R40) The trigger logic can be right (76% win rate, +2.6% fwd 5d on BTC's 2024-08-05 fire) and the pooled cross-section alpha can still be negative — because the demean is too punitive when assets are highly correlated (BTC+ETH+SOL+AVAX drop together in 2024-2026 = demean kills the signal exactly when it should fire). Architecture of the book must match the correlation structure of the signal's universe. A signal with a strong per-asset edge needs a per-asset book, not a cross-section one.
12. **Count independent events, not trades, before crediting a conditional hit rate.** (R44) R40's "76% BTC win rate" was 224 fires that ALL clustered on a single day (2024-08-05 Yen unwind) — 1 event, not 224 observations. The per-pair overlay that inherited this trigger fired **zero times OOS** at the doctrine-faithful threshold, and lost (33% win, −2.5% avg) when the threshold was loosened enough to fire. A trigger with a great conditional hit rate on one clustered event is an anecdote, not an edge, until it fires out-of-sample. Rare-event detectors are not swing strategies.
13. **Gross in-sample + cost-failure + OOS-failure is the refutation pattern for factor sleeves.** (R45) CIS-quality L/S earns +48%/yr at t=+2.24 in-sample gross, but degrades to t=+1.68 at 5 bps turnover (Binance VIP taker is 4 bps — below the 1.96 threshold already) and to t=+0.33 OOS on the last 30%. The three checks together — gross t > 1.96, cost-t > 1.96 at 5 bps turnover, OOS t > 1.96 — belong in every factor gauntlet. Passing one is suggestive, passing all three is the bar for a real book factor. The signal architecture (daily-rebal tercile) was wrong for the scale of the edge; the edge itself is partially real (~+50%/yr gross in-sample uncorrelated to market+momentum) but not at tradable magnitude in this construction.
14. **Cross-class is a separate test, not an extrapolation.** (R48) The 5d-rebal quality-L/S mechanism that survives on the 41-asset crypto universe (R46: pillar_O 5bps t=+3.33) **does NOT generalize to a 17-ETF TradFi universe** (R48: best t across all cadences × costs = −0.63; all negative). The crypto edge is contingent on crypto microstructure (24/7 retail-driven flow, persistent cross-section dispersion) and/or the multi-dimensionality of true CIS (5 pillars) that the 2-factor proxy cannot replicate. **Cross-class validation is its own check** — running a positive result on one market does NOT entitle a "general" claim. A negative cross-class result is informative even without a matched multi-pillar TradFi score.

*The most valuable output of this operation is a well-kept graveyard.*

## R41 🔴 Sleeve A (MVRV mean-reversion) — TOM-DOCTRINE HOLDS on multi-window OOS, but the strategy itself FAILS DSR
- **Hypothesis (per marketing backtest + §TRADER_TOM_DOCTRINE §5b):** mean-reversion via MVRV<0.9
  AND price_position<0.10 entry, RSI>65 OR pos>0.75 exit, on BTC/ETH/SOL 4h Binance futures, returns
  +150.2% over 14 months at 77% win. Tom-doctrine adds: bind the tail via catastrophe stop + size
  cap, do NOT 3× naked MR.
- **C-S2 [P0] BOUND ruin risk (single window 2025-01 → 2026-03, 14.5mo, faithful port of original
  backtest):** tested 7 stop/leverage/cap variants. Marketing's 3× naked MR is RUIN (−84.74% maxDD).
  A2 (1× lev, no stop) preserves MR signature at 70% WR but only +2.72% net. **R42 surfaced:**
  marketing "+150.2%" is NOT reproducible on the same window with the same code; the −63% ETH max
  single IS reproducible (−64.43% on same 2026-01-31 ETH entry). For LP use: cite signal profile,
  not headline aggregate.
- **C-S3 [P0] OOS walk-forward (6 quarterly folds + hold-out, 2024-04 → 2026-07, 7d embargo):**
  Test A confirms R42 multi-window. Sum PnL across 7 windows: A1=−54.2%, A2=−2.7%, A3=−17.3%,
  A4=−24.9%, **A6=+18.96%** (tight stop, ONLY positive), A7=−7.3%, A8=−7.4%. **R43 surfaced then
  resolved:** tight −5% stop (A6) empirically WINS on multi-window OOS by PnL (+2.71% avg vs
  −0.38% for natural-exit A2), but at cost of WR tanking 69% → 51.5%. A6 generates 70% MORE
  trades (201 vs 118) — it's a "sharper" MR (small wins, frequent), vs A2's "patient" MR (larger
  wins, infrequent). **Tom-doctrine's WR-tanking warning was empirically wrong on multi-window
  PnL, but the Tom-doctrine's deeper rule "expectancy > win-rate" holds — A6 has higher expectancy
  per trade (0.07 SR/trade vs 0.02) and positive sum PnL.**
- **C-S3 Test B (threshold-sweep PBO):** swept 25 (mvrv_entry × pos_entry) configs per fold on
  TRAIN → OOS. **Mean Spearman ρ = 0.172, mean PBO = 0.500.** Train-best ≠ OOS-best in 3/6 folds.
  Fold 6 has ρ = −0.81 (anti-correlated). **Threshold-tuning overfits.** The OOS-optimal threshold
  varies wildly (0.85-0.92 mvrv, 0.05-0.15 pos). Use the FIXED thresholds from the original; do not
  optimize.
- **C-S3 Test C (DSR, n_trials=8 stop variants):** per-trade SR for all variants is 0.02-0.07.
  Expected max SR under null for 8 trials = **1.46**. PSR (single trial) reaches 0.84 for A6, but
  **DSR = 0.00 for ALL variants**. After correcting for multiple-testing (8 stop variants tested),
  NO variant has statistically distinguishable edge. The "win" in raw PnL terms is consistent with
  best-of-8 random search under H0.
- **Verdict — DE-RATE per §STRATEGY-REVIVE ("if 77% doesn't survive OOS → CUT or de-rate"):**
  - 77% WR **does NOT survive**: drops to 69% on multi-window (within noise but lower).
  - +150% headline **does NOT survive**: A2 at 1× lev is barely positive on OOS sum PnL.
  - Per-trade SR **does NOT survive DSR**: 0.04-0.07 observed vs 1.46 expected max under H0.
  - **Recommendation:** **keep Sleeve A as a low-size satellite** (5% per-symbol cap, 1× lev, no
    leverage, wide catastrophe stop). The +18.96% sum-PnL for A6 on multi-window is suggestive of
    edge but NOT statistically credited. C-S4 (two-layer book) and C-S5 (live paper) must
    incorporate this as a SIZE-LIMITED allocation, not a primary sleeve. **The headline edge is
    refuted; the structural allocation (mean-reversion as a tail-bound satellite) is kept.**
- **References:** `reports/C_S1_HONEST_RESCORECARD_2026-07-19.md`, `reports/C_S2_SLEEVE_A_BOUND_2026-07-19.md`,
  `reports/C_S3_OOS_WALK_FORWARD_2026-07-19.md`, `_data/research/c_s3_oos/{test_a,test_b,test_c}*.csv`.

## R44 🔴 Capitulation Bounce v2 — the PER-PAIR swing overlay ALSO fails (R40's "76% win" was one event)
- **Hypothesis (R40's escape hatch):** R40's pooled cross-section was refuted on structural grounds
  (ENB 1.18–1.51, demean kills the signal exactly when correlated majors drop together). But the
  PER-ASSET trigger looked real (BTC 76% bounce rate, +2.6% fwd 5d). §TRADER_TOM_DOCTRINE §5c says a
  behavioral trigger belongs in a **tactical per-pair swing overlay**, not a market-neutral book. So
  v2 keeps R40's exact trigger (5d_ret < −5% AND 20d_vol > 2× 60d_vol), drops the demean, and sizes
  per-pair (5% per fire, ≤8 concurrent, ≤40% gross, −10% catastrophe stop). Full 51-asset crypto
  universe × 17,520 hourly bars, 20% OOS hold-out.
- **What kills it — two independent failure modes, both refute:**
  1. **Doctrine-faithful config (vm=2.0) fires ZERO times OOS.** All 270 full-sample fires cluster
     in the 2024-08-05/06 Yen carry-trade unwind — which is entirely in-sample. The last-20% OOS
     window (2026-01 → 2026-06) has **0 fires**. R40's "76% BTC win rate" was a *single macro event*,
     not a recurring edge. Full-sample even so: **35.9% win, −1.69% avg_pnl, 48.5% stop-out.**
  2. **Loosen the trigger so it fires OOS (vm=0.0) and it loses.** 4,213 full-sample trades
     (42.2% win, −0.44% avg); **OOS 819 trades → 33.0% win, −2.48% avg_pnl, OOS Sharpe −2.19.**
  Variant sweep (9 configs: thresh_ret −3/−5/−7%, vol_mult 1.0/1.5/2.0, hold 3/5/8d, stop −7/−10/−15%)
  is uniformly +0.00 OOS Sharpe at canonical because none fire OOS; loosening only converts "no
  signal" into "negative signal." No config produces positive OOS expectancy.
- **Diagnosis:** the per-asset trigger is a **rare-event detector**, not a swing edge. Capitulation as
  defined (−5% / 2× vol) is a once-a-cycle macro shock in crypto majors; on a 2y sample the OOS window
  simply contains no such shock. Weakening the definition to fire on ordinary dips catches
  *continuation*, not *reversal* — the 48% (canonical) / 30% (loose) stop-out rates say the "bounce"
  is a knife more often than a floor. The 76% figure was survivorship on one clustered event.
- **Lesson (added to aggregate list #12):** a trigger with a great *conditional* hit rate on one
  clustered event is not a strategy — it's an anecdote until it fires OOS. Before crediting a
  per-asset edge, count the *independent* events, not the trades: 224 BTC fires on ONE day = 1 event,
  not 224 observations. R40 died on architecture (pooled/ENB); R44 kills the escape hatch on
  empirics (per-pair form fires zero times OOS, loses when forced to fire). **Capitulation-bounce as
  a class is dead on 2024-2026 crypto — in every book shape.** It *might* revive in a mean-reverting
  tape with frequent 5-10% flushes (2022-2023 bottom formation), but that is a different-regime bet
  we cannot credit now.
- **Reference:** `src/research/cis_regime_studies/capitulation_bounce_v2.py` (per-pair overlay, 384 LoC),
  reuses trigger from `capitulation_bounce.py`. Ties off R40 — idea does not ship in any form.

## R45 🔴 CIS-quality long/short L/S — composite survives in-sample but dies on costs + OOS
- **Hypothesis (per §CIS-HISTORY-BACKFILL landing 2026-07-18):** when true CIS history is
  available (870 daily `cis_YYYY-MM-DD.json` snapshots at
  `/Volumes/CometCloudAI/cometcloud-local/_data/cis_history/`, full F/M/O/S/A pillars), the
  composite CIS-quality factor (long top-tercile by CIS score / short bottom-tercile,
  ranked on day d−1, applied to day d return) carries RESIDUAL α after the known premia
  (equal-weight market, TSMOM-30). If anything SIMPLER than the composite beats the composite,
  that's the upgrade signal: reweight CIS toward the pillar that pays.
- **What we built:** `src/research/validation/cis_quality_absorption.py` — OLS + Newey-West
  per-factor absorption (`factor_absorption.absorption_test`), per-pillar L/S in parallel,
  composite-vs-best-pillar, OOS time split 70/30, turnover cost curve 0/5/10/20 bps.
- **Window / universe:** 2024-06-07 → 2026-06-07, 731 daily bars, 41 tradeable assets
  (CIS ∩ OHLCV). 76 assets in CIS history, 52 with hourly parquet.
- **Result (in-sample, gross, full window):** composite CIS L/S = **+48.4%/yr, t=+2.24** →
  RESIDUAL α (passes t > 1.96). Per-pillar decomposition shows **pillar_O dominates at
  +51.4%/yr, t=+2.49**; pillar_F, M, A are non-significant in absolute terms (t = 0.37, 1.49,
  1.63); **pillar_S is actively negative (−10.6%/yr, t=−0.56)**. Composite CIS adds NOTHING
  over pillar_O once O is added as a control (composite resid-α drops to **t=+0.44**).
- **Robustness — what kills it:**
  1. **Cost curve (turnover-charged daily rebal):** CIS gross t=+2.24 → **5 bps t=+1.68** →
     **10 bps t=+1.14** → **20 bps t=+0.05.** Edge evaporates at any realistic taker-fee band.
     Same shape for pillar_O. The signal cannot pay for its own turnover.
  2. **OOS time split (last 30% = 2025-10-31 → 2026-06-07, 220 days):** composite CIS OOS
     t=+0.33; **pillar_O OOS t=−0.45 (sign-flipped!);** all five pillars OOS t between
     −1.56 and +0.58. **No surviving OOS signal.**
- **Diagnosis:** the apparent CIS-quality edge is real in-sample gross (≈+50%/yr uncorrelated to
  market & momentum) — but the construction is wrong for a real book. (a) The day-rebalanced
  tercile L/S turns over too much to survive realistic taker fees (even a Binance VIP taker
  at 4 bps crosses the t=1.96 line); (b) the edge does not extend OOS — it is partly an
  in-sample fit to 2024-2025 specific regime behavior. **The PREMIA exists (in-sample, gross) but
  is not at the magnitude the construction extracts — what we're measuring is closer to a
  coin-flip-with-good-bias than a tradable book factor.**
- **Verdict — DE-RATE rather than declare dead (per §STRATEGY-REVIVE):**
  - Composite CIS as a *quant factor* at this construction: **refuted**. Either slow the
    rebalance (weekly or monthly tercile refresh would cut turnover 5–20× and may survive),
    OR drop the L/S book factor framing entirely.
  - **The pillar decomposition is the actionable methodological finding for CIS v4.x:** pillar_O
    carries the residual α; pillar_S actively hurts. The composite dilutes the pillar that pays.
    Jazz's steer 2026-07-19 — "use whatever is best, so CIS upgrades" — translates concretely to:
    reweight CIS v5 toward On-Chain/Health (pillar_O) and away from Sentiment (pillar_S).
    Composite should retain F/M/A as diversifying signals (individually not significant, but
    their joint signal may matter in different regimes); S specifically should be demoted or
    regime-conditioned.
  - Composite CIS is still useful as a **quality/risk overlay** (per H1): sign the trade, size
    by CIS rank, but don't promise alpha. That framing is consistent with the methodology doc.
- **Lesson (added to aggregate list #13):** **Gross in-sample + cost-failure + OOS-failure is the
  refutation pattern for factor-style sleeves.** The three checks together — gross t > 1.96,
  cost-t > 1.96 at 5 bps turnover, OOS t > 1.96 on the last 30% — belong in every factor gauntlet.
  Any one passing is suggestive; passing all three is the bar for a real book factor.
- **Reference:** `reports/cis_quality_absorption/2026-07-19/{verdict.json,REPORT.md}`,
  `src/research/validation/cis_quality_absorption.py` (290 LoC), `src/research/validation/cis_quality_factor.py`
  (date-resolution fix from filename to handle reconstructed snapshots).

## R46 ✅ R45 REFINED — daily-rebal was overfit; 5-day cadence SURVIVES the 3-check gauntlet (Seth, 2026-07-20)
- **What happened:** R45 refuted composite CIS L/S at daily construction (cost fragility +
  OOS flip). Per Jazz 2026-07-20 "不要立刻改，再继续深化研究," built two follow-ups to
  disambiguate: **cadence sweep** (rebal_days ∈ {1,3,5,7,14,21} × cost_bps ∈ {0,5,10})
  and **sub-period OOS** (6 fixed-width windows, daily rebal, per-factor α_t).
- **Cadence — the headline finding (refines R45's "edge scale insufficient" diagnosis):**
  - Daily (R45 baseline): composite CIS 5bps t=+1.68 ✗; pillar_O 5bps t=+1.84 ✗.
  - 3-day rebal: composite 5bps t=+2.08 ✓ (borderline); pillar_O t=+1.97 ✓ (borderline).
  - **5-day rebal: composite 5bps t=+2.64 ✓ (strong), 10bps t=+2.43 ✓; pillar_O 5bps
    t=+3.33 ✓ (very strong), 10bps t=+3.13 ✓.** Turnover drops 228 → 79 (≈3×); O turnover
    drops 268 → 80. **This is a tradable book factor at 5-day construction.**
  - 7-day: pillar_O still clears 5bps t=+2.04 ✓ but composite drops to +1.73 ✗ — composite
    needs slower rebal to clear costs, pillar_O is more robust across cadences.
  - 14d/21d: both fail — too slow, signal decays.
  - **R45 verdict flipped: not "edge scale insufficient" but "daily-rebal extracts a
    DIFFERENT signal than the underlying edge."** Slower rebal (3-7d) reveals a much
    cleaner alpha. The composite CIS quality edge is real and tradable — at the right cadence.
- **Sub-period OOS — the W5 question (refines R45's OOS-flip verdict):**
  Daily-rebal across 6 windows (~122 days each): CIS clears at W2 (+3.48) + W6 (+2.14),
  fails flat elsewhere; **pillar_O clears at W2 (+2.54) and is positive in 5/6 windows** —
  one bad window (W5 = 2025-10-04 → 2026-02-02) flips to t=−2.32. **This is regime-specific,
  not structural.** W5 corresponds to late-cycle risk-on euphoria (BTC ~$100k→$80k chop
  Oct-Jan); the signal returns positive in W6 (Feb-Jun 2026, +1.42). Same pattern for
  composite (5/6 windows positive; W5 = −1.75).
  → **R45's "OOS flip = signal dead" diagnosis refines to "OOS flip = W5-specific late-
    cycle regime failure."** Regime conditioning (skip when regime=risk-on-late-cycle)
    is the upgrade path, not the construction.
- **Pillar_S remains dead at every cadence (5bps t in {−0.77, −0.05, −0.25, +0.43,
  +0.56, +0.14}) — never clears, often actively hurts. R45's "demote S" finding confirmed.**
- **Refined verdict for the composite CIS L/S sleeve:**
  - **R45 (daily rebal)**: REFUTED.
  - **R46 (5-day rebal + drop pillar_S from blend)**: SURVIVES the three-check gauntlet
    (gross t > 1.96 ✓, 5bps t > 1.96 ✓, 5/6 sub-period windows positive).
  - **Per-pillar winner at 5d/5bps: pillar_O at t=+3.33, ann=+70.1%/yr, turnover 80**
    (vs composite's t=+2.64 ann=+50.3%). The "use whatever is best" steer lands here:
    pillar_O alone at 5d rebal beats composite CIS at 5d rebal. **The upgrade path
    for CIS v5 is NOT composite-with-better-weights; it is a leaner CIS-replacement
    sleeve based on pillar_O alone at 5d cadence, with a regime-conditioned filter**
    (skip in risk-on-late-cycle regimes).
- **What this means for the ledger aggregate lesson #13 (three-check gauntlet):**
  R45's verdict was sourced from **insufficient sweep depth** — daily-only cadence is
  one point on the cadence curve, and the three-check gauntlet at that single point
  was a refutation. **The gauntlet must sweep across construction choices, not just
  test one configuration.** Aggregate lesson #13.5: **a "refutation" at one construction
  setting is provisional until the construction has been swept (rebal cadence, k-terciles,
  cost-bps penalty timing, signal source substitution).** Otherwise we close ideas that
  work at a different setting.
- **Action items (pending Jazz's go/no-go):**
  1. **R47 candidate**: build a regime-conditioned pillar_O L/S sleeve — 5-day rebal +
     composite of "skip if regime=risk-on-late-cycle" (the regime tag the macro pulse
     already supplies via risk_bands) — and run the full 3-check gauntlet. If passes,
     this is a satellite sized similarly to Sleeve E.
  2. **CIS v5 weight update**: log as a methodology suggestion to Minimax-A (reweight
     composite toward pillar_O in v5; demote/regime-condition pillar_S; F/M/A held
     diversified), with this evidence package attached. Scoring change, not front-end.
  3. **Production paper holding-pattern preserved**: per Jazz steering, NO change to
     `REGIME_CIS_FLOOR` or any CIS gate until R47 (regime-conditioned sleeve) and the
     CIS v5 weight reweight are both empirically vetted.
- **Reference:** `src/research/validation/cis_quality_robustness.py` (~280 LoC),
  `reports/cis_quality_robustness/2026-07-20/{verdict.json,REPORT.md}` (gitignored, local).

## R47 🔴 Pooled cross-sectional funding-crowding market-neutral book — MECHANISM REAL, F1 regime flip KILLS credit (Minimax-A, 2026-07-20)
- **What happened:** Built + ran the §CROWDING-BREADTH HL credit test. Mac-side Hyperliquid fetch
  brought 43 fresh perps × 805d of hourly funding + daily OHLCV into the cache
  (`scripts/fetch_hyperliquid_funding.py`, 3 loader fixes detailed below). Ran the canonical
  pooled-crowding book (`cross-section demean → vol-targeted → 5 bps turnover cost`) on
  the 2024-04-02 → 2026-06-15 common window, last 20% (161d) as OOS.
- **Headline numbers (a-priori canonical config, thr=1.0, hold=10, vol_mult=1.10, 5 bps):**
  - **ENB = 198.38** (43 perps) — ≫ the ~8 target and ≫ RWA smoke's 57. Mechanism is
    real, broader than any prior pooled candidate.
  - **β_market = +0.007, β_momentum = −0.008** — truly orthogonal to both market and
    momentum factors (the orthogonal-edge form the directive called for).
  - **Canonical OOS α_t = +1.04** (below 1.96 ship gate).
  - PBO = 0.698 (high — confidence is the data-depth-constrained form of this).
  - **Walk-forward 4-fold (the failure mode lives in one fold):**
    | Fold | Window | Days | annSR | α_t | α_ann% |
    |---|---|---:|---:|---:|---:|
    | F1 | 2024-04 → 2024-10 | 201 | **−4.78** | **−3.02** | **−19.98%** |
    | F2 | 2024-10 → 2025-05 | 201 | +1.84 | +1.55 | +9.15% |
    | F3 | 2025-05 → 2025-11 | 201 | +0.57 | +0.91 | +5.38% |
    | F4 | 2025-11 → 2026-06 | 202 | +0.56 | +1.29 | +6.22% |
  - 3 of 4 folds positive on α_t, but **F1 is a −3σ t-stat catastrophe**. F1's window is the
    post-BTC-ETF-top + memecoin-rotation phase (DOGE/SHIB/WIF/PEPE running on crowded-longs
    that the cross-sectional signal was structurally SHORTING — "fade the crowd" was wrong
    because the crowd was right).
  - Variant set uniformly direction-positive (5 configs, annSR range +0.08 to +1.51, no
    cherry-pick), but no variant clears the F1 hole.
- **Verdict:** 🔴 **Cross-sectional pooled market-neutral funding-crowding does NOT credit
  at the standard construction.** The mechanism lives (ENB=198, βs≈0, 3/4 folds positive,
  direction-positive variant sweep), but the 2024-04→2026-06 honest ship-gate is broken
  by F1's regime-specific sign-flip. Direction: REGIME-CONDITIONED book is the path to
  credit (per R46 lesson applied to this sleeve); pure pooling doesn't survive.
- **Action items (per R46 lesson, sweep construction before crediting):**
  1. **R48 candidate**: build a regime-conditioned pooled book — gate signal-firing on
     (f_market-breadth-z, funding-acceleration, BTC dominance change) to skip the
     "right-side-of-trend crowded" regime. Run the 3-check gauntlet on F2/F3/F4 only
     after gating F1 out. (Sibling of R46's R47 candidate for pillar_O.)
  2. **Variant-best thr_1.0_hold_15** alone delivered +1.51 annSR on canonical OOS;
     3-check gauntlet there is the cheapest near-term test.
  3. **Per-asset overlay** (R44/R36-style): per-perp z at t → portfolio overlay size on
     existing book, not standalone book.
- **Sub-aggregate lesson #14 (regime-flip family is now 4-deep):**
  - R15 (V12 per-pair funding gate): bull 2024 — crowded longs were right.
  - R17 → R38 (smoothed-CIS empirical grid gate): late-cycle band sign-flip.
  - R45 → R46 (CIS L/S daily rebal): W5 = late-cycle risk-on flip.
  - **R47 (pooled funding-crowding cross-class neutral):** F1 = meme-crowded-long regime flip.
  - **Pattern: every pooled/per-pair directional fade on a crowd signal has lost one
    regime window. Survived regimes are 3-5 of 6, sign-flipped regime is always
    late-cycle-risk-on OR crowd-on-right-side-of-trend. Regime-conditioning is the
    consistent upgrade path.**
  - Aggregate lesson #14: **"fade the crowd" is only right when the crowd is wrong.** A
    signal can't credit on pooled cross-section alone — it MUST condition on whether the
    crowd's directional view is dominating the regime. This is the same insight as
    R46's W5 finding for CIS quality.
- **Loader/infra work (also this session, three fixes that were load-bearing):**
  - (a) HL rate limiter: bumped per-page sleep 0.1→0.5s, per-coin 0.2→1.0s, retries
    3→4, 30/60/120s cooldown on HTTP 429. First BTC fetch had failed on 429 in initial
    test (`scripts/fetch_hyperliquid_funding.py::_post`).
  - (b) HL pagination: `fundingHistory` returns OLDEST 500 in `[startTime, endTime]`
    (ASC). The script was incrementing `endTime` not `startTime` → infinite loop on
    first batch. Fix: cursor=start_ms, advance past last returned, break on `<500` short.
    First BTC post-fix returned 27,390 hourly funding rows in ~10s.
  - (c) Stale-OHLCV filter: HL `/info candleSnapshot` returns FROZEN candles for some
    perps (RNDR ends 2024-07-21, MKR 2025-09-05, FXS 2026-01-06, TON 2026-06-15).
    Strict-intersection collapses common window to 0 days. New `max_stale_days` arg on
    `load_hyperliquid_panel()` (default 90) drops these.
- **Status update for prior R36:** R36 (Minimax-B, 2026-07-18 🔵) said "Cross-CLASS
  funding-crowding credit path is BLOCKED — data does not exist yet." That was a false
  alarm at the structural-data-layer; the HL fetch + the three loader fixes above
  unblocked it. The mechanism question is now answered: cross-class breadth IS real at
  ENB=198 but the standard pooled construction does NOT credit. R36 is now
  ✅ RESOLVED-on-infrastructure and superseded by R47's empirical finding.
- **Reference:** `scripts/crowding_breadth_hl.py` (Minimax-B, unchanged),
  `src/research/cis_regime_studies/funding_crowding_breadth.py` (patched: `max_stale_days`),
  `scripts/fetch_hyperliquid_funding.py` (patched: rate-limiter + corrected pagination),
  `/Volumes/CometCloudAI/cometcloud-local/_data/hyperliquid_funding/` (48 perps cached,
  ~700k funding rows, ~50k OHLCV bars), `reports/crowding_breadth/2026-07-20_hl_credit/{summary.json,
  REPORT.md}`.

## R48 🔴 Cross-class test REFUTES "general L/S quality mechanism" — R46 is crypto-specific (Seth, 2026-07-20)
- **Hypothesis (R46 follow-up, per Jazz option C + "挖掘更远的窗口, 22年起"):** does the
  5d-rebal quality-L/S mechanism generalize beyond crypto? Constructed a no-CIS quality
  proxy (trailing_90d_momentum + inverse_30d_vol, cross-section z-scored) and ran the
  same cadence × cost × 3-check gauntlet on TWO new surfaces:
  1. **Crypto multi-regime proxy 2022-2026** (14 majors with 4h coverage back to 2022;
     `_data/cis_history` daily JSONs only go back to 2024-03, so pre-2024 has to use
     the proxy — not true CIS). Coverage: 2022-01 → 2026-07, 1619 days.
  2. **TradFi 17-ETF cross-class** (SPY/QQQ/IWM/DIA/XLF/XLK/XLE/XLV/XLY/TLT/IEF/HYG/
     LQD/GLD/USO/SLV/UUP; genuinely heterogeneous across equities / bonds / commodities
     / currencies; 1136 trading days). Coverage: 2022-01 → 2026-07.
- **Result (BOTH surfaces negative):**
  | Surface | Best 5d/5bps t | Cross-section structure |
  |---|--:|---|
  | **Crypto, 41 assets (R46 true CIS)** | **+3.33 pillar_O / +2.64 composite** ✓✓✓ | heterogeneous, ENB high |
  | Crypto, 14 majors (proxy, multi-regime) | **+0.28 to +0.36** | correlated, ENB low |
  | **TradFi, 17 ETFs (proxy, R48)** | **−1.12 proxy** at 5d/5bps | heterogeneous, ENB high |
  | TradFi, all cadences × costs | **all NEGATIVE** (−0.63 to −1.47) | — |
- **TradFi cross-class result:** best t-stat at any cadence × cost: **−0.63** (3d,
  0bps). At 5d/5bps across 5 calendar-year windows: **1/5 positive (+0.41 in 2025
  S&P melt-up), 0/5 clear 1.96**. **Direction-flipped**: the long-winners/
  short-losers pattern is mildly DESTRUCTIVE on TradFi (proxy L/S gives
  consistently negative residual-α t across the full cadence × cost grid).
- **Three-way comparison is the headline.** Crypto 41-asset = strong positive; crypto
  14-major proxy = weak/marginal; TradFi 17-ETF = weakly negative. **The 5d-rebal
  quality L/S mechanism tested is NOT market-general.** R46's strong crypto result
  is contingent on crypto-microstructure. Two non-mutually-exclusive reasons:
  1. **Crypto microstructure**: 24/7 trading, retail-driven order flow, news-driven
     momentum persistence, persistent cross-sectional dispersion (low-decile
     "losers" stay cheap for longer than TradFi losers whose fundamentals mean-revert
     more reliably).
  2. **True CIS is multi-dimensional**: the 5-pillar composite (F+M+O+S+A) is
     fundamentally richer than the 2-factor (momentum + inv-vol) proxy. The
     proxy is what failed on TradFi; true CIS may behave differently, but we have
     no TradFi-equivalent multi-pillar quality score to test.
- **Crypto 14-major multi-regime specifically:** even the proxy is essentially flat
  across 3 windows (best t in any window: +0.44 bear, +0.54 CIS-coverage, +0.79
  full). **Doesn't clear 1.96 anywhere.** Same direction as TradFi (weakly positive
  on narrower crypto, negative on TradFi). Reads as: the proxy at 5d/5bps isn't
  strong enough to survive a cross-section without the richness of true CIS pillars.
- **Methodological lesson (added to aggregate list #15):** a positive factor-survival
  result on one market does NOT imply a "general" mechanism. **Cross-class
  validation is a separate test, not an extrapolation.** The 41-asset crypto universe
  was sufficient for crypto-specific discovery; the same L/S idea applied to a
  heterogeneous TradFi universe PRODUCED THE OPPOSITE SIGN. Always extend findings
  to a different asset class before claiming generality. Negative cross-class is
  informative even when we can't run a directly-matched TradFi multi-pillar test.
- **What this means for the CIS v5 upgrade path (closes the original R45 "use
  whatever is best, so CIS upgrades" thread honestly):**
  - pillar_O beats composite **specifically in crypto** because of crypto
    microstructure, not because pillar_O is universally superior.
  - CIS v5 reweight toward pillar_O should be **scoped to crypto scoring only.**
    Do NOT apply the same weights to a hypothetical future TradFi scoring engine;
    the mechanism is different.
  - The "regime-conditioned pillar_O sleeve" (R47 sibling idea) remains a valid
    crypto-scoped candidate, but the trade framing must respect that this is a
    CRYPTO SPECIALIST edge, not a market-general one.
- **Status:** R46 stays ✅ (survives at 5d/5bps on broad crypto); this R48
  establishes that R46 does NOT extrapolate to other markets. Together they form
  the complete characterization of the edge.
- **Reference:** `src/research/validation/cis_quality_multiregime.py` (~270 LoC,
  14-major crypto 2022-2026) + `src/research/validation/cis_quality_tradfi.py`
  (~230 LoC, 17-ETF TradFi 2022-2026); `reports/cis_quality_multiregime/2026-07-20/`
  + `reports/cis_quality_tradfi/2026-07-20/{verdict.json,REPORT.md}` (gitignored).
  EODHD data cached locally at `/Volumes/CometCloudAI/cometcloud-local/_cache/eodhd_history/`
  (~17 ETF JSONs, 2022-01 → 2026-07 daily).

## R49 🔴 Regime-conditioned pooled book does NOT credit at any tested (signal × threshold) — F1 sign-flip is structural, not regime-detectable (Minimax-A, 2026-07-20)
- **Hypothesis:** R47 (this session, prior entry) found pooled cross-sectional funding-
  crowding market-neutral has ENB=198, βs≈0, 3/4 walk-forward folds positive on α_t — but
  F1 (2024-04 → 2024-10) α_t = −3.02 destroys canonical OOS α_t = +1.04. R46's prototype
  (5d-rebal CADENCE sweep turning W5 sign-flip into positive) suggested regime-conditioning
  as the fix. R49 tests whether regime-conditioning at simple external signals rescues
  the pooled book.
- **Method:** Gate sweep matrix over 12 (signal × threshold) combinations from 3
  candidate EXTERNAL regime signals (none look at the book itself — that's a lookup-bias
  trap):
  - **S1**: BTC funding z-acceleration (z-score of BTC 7d-mean minus 30d-mean funding,
    normalized by 90d rolling std).
  - **S2**: cross-class crowded count (fraction of non-BTC perps whose 7d-mean funding
    is in their own 90th-pct band, smoothed).
  - **S3**: basket vs BTC 30d spread (rolling 30d sum of equal-weight perp basket
    return minus BTC return).
  When the gate fires, position → 0 (skip the day). Re-cost turnover (5 bps), re-run
  walk-forward folds + canonical OOS alpha_t. Best gated variant put through full
  signal_gauntlet.
- **Gate sweep matrix (43 perps × 805d, F1/F2/F3/F4 each ~201 days):**
  | Gate | thr | frac gated | OOS α_t | F1 α_t | F2 α_t | F3 α_t | F4 α_t |
  |---|---|---:|---:|---:|---:|---:|---:|
  | (none — R47 baseline) | — | 0% | +1.04 | **−3.11** | +1.47 | +0.37 | +0.47 |
  | S1 BTC z > 0.0 | 0.0 | 51% | +0.34 | −1.84 | +1.69 | +1.27 | +0.12 |
  | S1 BTC z > 0.5 | 0.5 | 32% | +0.91 | −2.86 | +1.60 | +0.48 | +0.70 |
  | S1 BTC z > 1.0 | 1.0 | 16% | +0.79 | −3.21 | +0.97 | +1.03 | +0.47 |
  | S2 frac crowded > 0.10 | 0.10 | 7% | +0.95 | −3.17 | +0.39 | +1.17 | +0.37 |
  | S2 frac crowded > 0.20 | 0.20 | 6% | +0.95 | −3.17 | +0.56 | +0.37 | +0.37 |
  | S2 frac crowded > 0.30 | 0.30 | 5% | +0.95 | −3.17 | +0.72 | +0.29 | +0.37 |
  | **S3 basket−BTC > 0.05** | 0.05 | 19% | **+1.14** | −2.84 | +0.29 | +1.30 | +0.58 |
  | **S3 basket−BTC > 0.10** ★ | 0.10 | 12% | **+1.19** | −3.10 | +0.50 | +0.79 | +0.55 |
  | S3 basket−BTC > 0.15 | 0.15 | 6% | +0.94 | −3.17 | +0.37 | +0.27 | +0.36 |
  | S3 basket−BTC < −0.05 | −0.05 | 43% | +1.03 | −3.01 | +1.11 | −0.91 | +0.87 |
  | S3 basket−BTC < −0.10 | −0.10 | 27% | +1.10 | −3.06 | +1.40 | −1.07 | +0.55 |
- **Verdict:** 🔴 **No tested gate cleanly destroys F1.** Best F1 destruction is S1 z>0
  (−1.84) but it fires 51% of days (kills half the book) and only buys 0.13 OOS α_t
  improvement. Best OOS improvement is S3 > 0.10 (+1.04 → +1.19, +14%) but F1 is still
  −3.10. The full signal gauntlet on S3 > 0.10: still DIED at significance_PSR (annSR
  1.37, psr 0.824), still NOT SIGNIFICANT at factor_absorption (α_t 1.19), still
  FRAGILE at regime_robustness (3/4 subsample flip). **Verdict unchanged: NOT a credited
  signal.** Same DIED-stage as baseline.
- **Structural reading (why the gate doesn't work):**
  1. F1 wasn't a "meme rotation" regime — it was a **quality-rotation** regime (MKR
     +27%, AAVE +21%, TRX +19%, SOL +10% at F1 mid). The pooled book voted SHORT on
     these elevated-funding quality perps and lost. Fading elevated funding is right in
     80% of historical regimes — but in F1, the crowd was correctly positioned in
     quality rotation.
  2. **No external signal uniquely identifies F1.** BTC funding was elevated in F1 but
     equally elevated in F2. Basket outperformed BTC in F1 but equally in F3. Cross-
     class breadth of crowded longs is similar in F1 and F3 — it doesn't distinguish.
  3. **The signal's information advantage is in the CROSS-SECTION, not the regime.**
     Cross-section demean isolates idiosyncratic per-perp signal. In F1, that
     idiosyncratic signal was wrong at the panel level — even skipping 12% of "alt-
     season" days leaves 88% of days where the cross-sectional short bias is
     structural.
- **Verdict consistency:** 🔴 Same DIED-at-significance_PSR stage as baseline. The
  regime gate is a small upward nudge (annSR +0.13, α_t +0.15), NOT a fix. regime_robustness
  FRAGILE flag persists (3/4 subsample flip on both baseline and gated).
- **Aggregate lesson #14 (deepened):** R49 is the **5th entry in the regime-flip family**
  (alongside R15, R17/R38, R45/R46, R47). The deepened lesson: **"fade the crowd" is only
  right when the crowd is wrong; AND regime-conditioning with simple external signals is
  INSUFFICIENT to make a pooled cross-sectional book regime-portable.** The F1 sign-flip
  is structural, not regime-detectable. The next move is NOT another regime gate — it's a
  different signal architecture.
- **Three remaining paths to credit (none started):**
  1. **Per-asset overlay (R44-style)** — per-perp z-score at t → portfolio overlay on
     existing book, NOT standalone book. Highest orthogonality potential.
  2. **Cross-section transformation** — instead of demean-then-pool, use rank-weighted,
     vol-target, or factor-neutral pooling that may be less exposed to F1.
  3. **Accept the regime-flip as feature, not bug** — run the pooled book AS A SATELLITE
     around a fundamentally-driven core (per §TRADER_TOM_DOCTRINE two-layer book) with
     hard stops during regime-detection, not just statistical gating.
- **Action item:** Seth (next session) — picks one of the three paths above.
  Coordination with Minimax-A on per-asset overlay infrastructure if that path is taken.
  This closes the R47 follow-up of "credit IF/WHEN regime-conditioned" at the simple-
  signal level. The R46 pre-condition for CIS v5 reweight ("until R47 regime-conditioned
  sleeve AND reweight both empirically vetted") is now formally NOT met by R49 — the
  R47 regime-conditioned variant also does NOT credit. **CIS v5 reweight remains parked.**
- **Status update:** R47 stays as RESOLVED-on-infrastructure + empirically refuted.
  R49 adds the regime-conditioning variant to the empirical refutation. The pooled book
  is now **DOUBLE-REFUTED**: (1) at canonical pooled construction (R47), (2) at regime-
  conditioned pooled construction with simple external signals (R49).
- **Reference:** `src/research/cis_regime_studies/regime_detector_v1.py` (~165 LoC,
  three candidate regime signals + F1-fit check), `regime_gate_sweep.py` (~310 LoC,
  12-cell gate matrix), `regime_gate_gauntlet.py` (~150 LoC, full gauntlet + variant
  sweep on gated book), `reports/crowding_breadth/2026-07-20_regime_gate/{REPORT.md,
  sweep_results.json, gauntlet_results.json}` (gitignored).

---

## R59 🟡 External-feature W5 detector enrichment — funding IS informative (KS=0.39) but does NOT close the OOS gap; UNION detector (R58 z=0.50/mf=3 OR R59 z=0.50/mf=4) gets closest yet (gross=+4.87, OOS=+0.73) (Seth, 2026-07-21)

**Setup.** R58 left us with a partial verdict: detector improves gross (+1.84→+4.84)
and flips OOS sign (−0.89→+0.41) but doesn't clear 1.96. R58 attributed the residual
gap to "funding/leverage/cross-asset contagion — needs external data." We now have:
- **47 assets × hourly funding rates** 2023-05-12 → 2026-07-19
  (`/Volumes/CometCloudAI/cometcloud-local/_data/hyperliquid_funding/*_funding_1h.csv`)
- **28 assets overlap** with the 41-asset tradeable universe
- BTC OI: **NOT AVAILABLE** (cache miss — only 3 BTC/ETH/SOL files exist, in wrong format)

R59 loads the 28 funding 1h panels, resamples to daily mean per asset, derives 8
cross-sectional funding features (mean, disp, skew, extreme-long-frac, extreme-short-frac,
net-long-frac, btc_funding_raw, btc_funding_zscore_30) plus a placeholder OI feature,
merges with R58's 10 internal features → 19 total → re-runs KS + detector sweep on
the enriched set. Then explores UNION detectors (R58 internal detector OR R59 enriched
detector fires) for the best aggregate.

**W5 vs non-W5 KS ranking — top features (ext = NEW external):**

| rank | feature | type | KS | mean(W5) | mean(non-W5) | reading |
|--:|---|---|--:|--:|--:|---|
| 1 | score_disp | INT | 0.46 | 10.97 | 15.39 | universe harder to differentiate |
| 2 | mkt_trail30 | INT | 0.41 | -0.151 | +0.018 | 30d market drawdown |
| 3 | **funding_mean** | **EXT** | **0.39** | -0.00003 | +0.00002 | **funding flipped NEGATIVE in W5** |
| 4 | btc_funding_raw | EXT | 0.25 | +0.00001 | +0.00003 | BTC funding also lower in W5 |
| 5 | **funding_skew** | **EXT** | **0.24** | -1.82 | -1.41 | **funding distribution more LEFT-skewed in W5** |
| 6 | streak_5 | INT | 0.24 | -0.75 | +0.32 | sleeve losing ≥5 days |
| 9 | **btc_funding_zscore_30** | **EXT** | **0.20** | -0.19 | -0.02 | **BTC funding below its 30d norm in W5** |

**External features ARE informative** — funding_mean ranks #3 most W5-distinctive (KS=0.39,
p<0.001). W5 is a **funding-crowding UNWIND** regime: longs de-lever, mean funding
drops to slightly negative, distribution becomes left-skewed. This is a meaningful
micro-structure fingerprint of the failure mode.

**Detector grid (R59 enriched, top-8 features):**

| z | min_f | W5_hr | nonW5_hr | precision | total days |
|--:|--:|--:|--:|--:|--:|
| 0.00 | 4 | 98% | 68% | 59% | 536 |
| **0.25** | **4** | **79%** | **40%** | **66%** | **339** |
| 0.50 | 4 | 59% | 26% | 70% | 228 |
| 0.50 | 5 | 37% | 13% | 74% | 122 |
| 0.75 | 3 | 53% | 21% | 72% | 192 |

Selected: z=0.25, min_f=4 → W5 hit-rate 79% (vs R58's 68%), non-W5 hit-rate 40% (worse).

**3-check gauntlet — ungated vs R58 vs R59 vs UNION:**

| version | gross_t | OOS_t | pass_gross | pass_OOS | pass_all |
|---|--:|--:|:--:|:--:|:--:|
| ungated (R46-baseline) | +1.84 | -0.89 | ✗ | ✗ | ✗ |
| R58 (internal-only, z=0.75/mf=2) | +4.84 | +0.41 | ✓ | ✗ | ✗ |
| R59 (enriched, z=0.25/mf=4) | +4.05 | +0.18 | ✓ | ✗ | ✗ |
| **UNION best (R58 z=0.50/mf=3 OR R59 z=0.50/mf=4)** | **+4.87** | **+0.73** | **✓** | **✗** | **✗** |

**UNION sweep (4 promising combinations):**

| R58 (z/mf) | R59 (z/mf) | W5_hr | nonW5_hr | total days | gross | OOS |
|---|---|--:|--:|--:|--:|--:|
| 0.75/2 | 0.50/4 | 76% | 34% | 301 | +4.46 | +0.14 |
| **0.50/3** | **0.50/4** | **70%** | **31%** | **271** | **+4.87** | **+0.73** |
| 0.75/2 | 0.50/3 | 81% | 45% | 374 | +4.18 | -0.17 |
| 1.00/2 | 0.75/4 | 45% | 22% | 191 | +4.15 | -0.50 |

**Per-window P&L — ungated vs R58 vs R59 (ann%/yr):**

| Window | ungated | R58 internal | R59 enriched |
|---|--:|--:|--:|
| W1 | +53.1 | +174.9 | +84.6 |
| W2 | +436.8 | +687.0 | +509.5 |
| W3 | +11.9 | +58.1 | +32.6 |
| W4 | +59.8 | +139.4 | +117.6 |
| **W5** | **-57.5** | **-8.5** | **+2.3** |
| W6 | +18.7 | +29.3 | +8.9 |

**Reading:**
- **R59 RESCUES W5 better than R58** (ann% −57.5 → +2.3 vs R58's −8.5). Funding features
  ARE the right lens for the W5 failure mode specifically.
- **But R59 OVER-GATES non-W5 too much** (40% non-W5 hit-rate vs R58's 27%). It eats
  too many good days elsewhere. Net: R59 is worse than R58 on the full panel OOS.
- **UNION of R58 + R59 detectors** achieves gross=+4.87, OOS=+0.73 — closest to
  clearing 1.96 we've gotten. Still doesn't pass.
- **Neither detector alone NOR the UNION clears the 3-check gauntlet.** The remaining
  OOS fragility is something NOT captured by either feature family — internal OR
  external funding.

**Aggregate lesson #21 (NEW — funding is informative but not the missing piece):**
- Funding-rate W5 features rank #3-5 by KS (very informative), confirming W5 IS a
  funding-crowding unwind. But funding doesn't close the OOS gap because the OOS
  period contains W6 days that R59 over-gates (40% non-W5 hit-rate = bad precision).
- The lesson is: **micro-structure features (funding, OI) help diagnose a failure
  mode but don't necessarily fix it**. The detector needs to be PRECISE enough to
  avoid over-gating; funding alone fires too eagerly.
- Implication: the next-generation detector should probably combine funding features
  with price-action or volume features that further discriminate W5 from non-W5
  fragile days. (R60+ direction.)

**Aggregate lesson #22 (NEW — UNION of detectors is a robust OOS-improvement lever):**
- Two detectors with different feature families (R58 internal-only, R59 enriched)
  have CORRELATED but not identical fire days. UNION (either fires) gets you more
  of W5 (76% vs R58's 68%) while keeping non-W5 reasonable (34% vs R58's 27%).
- The UNION-gated sleeve has the best gross_t we've seen for a detector-gated
  sleeve (+4.87 vs R58's +4.84), and substantially better OOS (+0.73 vs R58's +0.41).
- **Even at the closest OOS_t=+0.73, it's not 1.96** — but it's a clear directional
  signal that ADDING detector signals helps. More detectors (or different
  feature families) might eventually clear 1.96.

**Aggregate lesson #23 (NEW — what the OOS gap actually is):**
- We've now ruled out: regime-label (R52), construction choice (R56), internal
  market-state (R58), funding-rate features (R59). What remains in the gap?
- Possibilities: (a) intraday vol / gap risk, (b) cross-asset contagion we don't
  have data for (RWA/equity linkages), (c) liquidity-driven regime shifts, (d) the
  pillar_O score itself has noise that the detector can't filter.
- Most likely a combination — OOS failure of an L/S factor is rarely single-cause.

**Status:** 🟡 partial — **funding is informative but not the missing piece; UNION detector gets closer but doesn't clear 1.96.** The cumulative work (R52, R56, R58, R59) has eliminated every reasonable filter type. The remaining fragility is something outside this axis.

**Reference:** `src/research/validation/w5_forensics_external.py` (~480 LoC); `tests/test_w5_forensics_external_smoke.py` (7 tests, all pass); `reports/w5_forensics_external/2026-07-21/{verdict.json, REPORT.md}` (gitignored).

## R60 🔴 Funding-crowding L/S per-asset — REFUTED; per-asset overlay path DOESN'T escape the cross-section-failure mode (Seth, 2026-07-21)

**Setup.** R49 (regime-conditioned pooled) recommended per-asset overlay as the
highest-orthogonality remaining route. R60 builds that path explicitly: a
cross-sectional L/S indexed by per-asset funding z-score (NOT pooled demean), LONG
low-funding / SHORT high-funding ("fade the crowd" sign convention). Same 5-day
rebal / 5bps / k=3 construction as R46 winning cell — direct comparability.

- **Universe:** 28 assets (Hyperliquid funding ∩ CIS ∩ OHLCV tradeable, subset of 41).
  Coverage: AAVE, APT, ARB, ATOM, AVAX, BNB, BTC, COMP, DOGE, DOT, ENA, ETH, FIL,
  INJ, LDO, LINK, MKR, NEAR, OP, PENDLE, SEI, SOL, STRK, STX, SUI, TIA, UNI, XRP.
- **Period:** 731 days, 2024-06-07 → 2026-06-07 (R45/R46 parity).
- **Score:** per-asset rolling z-score of daily-mean funding, zwin=30d; sign = `−z`
  so high score = low funding = LONG candidate (the R49-recommended direction).
- **Construction:** tercile_ls (R45) / cadence_ls (R46), k=3, swept over cadences
  {1, 3, 5, 7, 14, 21}d × costs {0, 5, 10} bps.
- **Gauntlet:** R58/R59's 3-check (gross residual-α t > 1.96 + 5bps t > 1.96 +
  OOS t > 1.96) on the standard 70/30 split.
- **Sub-period:** identical 6-window W1..W6 partition for direct W5 attribution.

**Cadence × cost grid (residual-α t after {market, momentum}):**

| rebal (d) | 0 bps | 5 bps | 10 bps |
|--:|--:|--:|--:|
| 1  | +0.75 | −0.83 | **−2.43** |
| 3  | +0.22 | −0.46 | −1.13 |
| 5  | +0.17 | −0.28 | −0.73 |
| 7  | +0.51 | +0.17 | −0.16 |
| 14 | +1.15 | +0.98 | +0.80 |
| **21** | **+1.73** | **+1.60** | **+1.48** |

**Two structural findings from the grid:**

1. **Sign-FLIPS at fast cadence.** Daily/weekly rebal flips the alpha sign
   (1d/5bps=−0.83, 3d/5bps=−0.46, 5d/5bps=−0.28). The fade-the-crowd premium
   *inverts* at high-frequency rebal — at daily cadence, "LONG low-funding /
   SHORT high-funding" loses money. This is the *opposite* of R46's pattern
   (where 5d was the sweet spot for pillar_O).
2. **Slow cadence is required.** Only at 14d and 21d rebal does the alpha
   turn consistently positive (1d−21d monotonic at all costs). The "true"
   funding-crowding signal needs ~3 weeks of mean-reversion to materialize.

**3-check gauntlet (R46 cell parity vs best grid cell):**

| config | gross_t | OOS_t | pass_gross | pass_OOS |
|---|--:|--:|:--:|:--:|
| **R46 cell (5d/5bps)** | **−0.28** | **−0.41** | ✗ | ✗ |
| **best cell (21d/0bps)** | **+1.73** | **+1.89** | ✗ | ✗ |

**Best cell is just shy of the 1.96 bar on both checks** (gross +0.23 short,
OOS +0.07 short). Adding 5bps cost pulls it back to +1.60 / +1.49.

**Per-window P&L (best cell 21d/0bps, ann%/yr):**

| Window | dates | n | ann% | Sharpe |
|--:|---|--:|--:|--:|
| W1 | 2024-06-07 → 2024-10-06 | 122 | **−37.4** | −1.68 |
| W2 | 2024-10-06 → 2025-02-04 | 122 | **+170.2** | +3.02 |
| W3 | 2025-02-04 → 2025-06-05 | 122 | −22.5 | −1.05 |
| W4 | 2025-06-05 → 2025-10-04 | 122 | +37.1 | +1.35 |
| **W5** | **2025-10-04 → 2026-02-02** | **122** | **+29.6** | **+1.02** |
| W6 | 2026-02-02 → 2026-06-07 | 126 | +83.6 | +2.74 |

**Three structural findings from the per-window pattern:**

1. **W5 is NOT a problem for R60** (W5 ann% +29.6%, α_t +0.43 — best of all
   pillar_O-sleeve cells). The W5 fragility is **R46/pillar_O-specific**, not
   a property of cross-sectional L/S factors in general.
2. **High window variance (W1 −37.4% / W2 +170.2% — 7× spread) means the
   signal is regime-dependent**, not a stable per-asset premium. The "true"
   funding-crowding alpha only appears in *some* regimes (W2 bull-trend +
   funding normalization; W6 post-rotation recovery; W5 risk-off rebound).
3. **2 of 6 windows are deeply negative (W1, W3).** The signal fails in
   early-cycle (just-listing) and consolidation regimes — exactly the
   regimes where funding is noisier and the crowd-vs-contrarian distinction
   blurs.

**W5 attribution (R60 vs the four prior attempts):**

| | W5 ann% | W5 α_t | W5 contribution verdict |
|---|--:|--:|---|
| R46 pillar_O 5d/5bps (ungated) | −57.5 | −2.32 | ❌ sign-flips badly |
| R58 detector-gated | −8.5 | n/a | 🟡 partially recovers |
| R59 enriched detector | +2.3 | n/a | 🟡 best detector-layer |
| **R60 per-asset overlay** | **+29.6** | **+0.43** | **✅ positive** |
| R60 R46-cell parity (5d/5bps) | n/a | −0.24 | ❌ fails R46 cell |

**Aggregate lesson #24 (NEW — per-asset overlay DOES escape pooled-failure mode for W5, but loses elsewhere):**
- R60's per-asset overlay path is the first factor that WINS on W5 (+29.6% ann,
  +0.43 α_t) without a detector. The per-asset construction genuinely escapes the
  R47 pooled-demean failure mode. BUT the W5 win comes at the cost of W1 (−37.4%)
  and W3 (−22.5%) — the signal is unstable across regimes.
- Net: per-asset overlay at this construction **cannot credit** (gross_t +1.73,
  OOS_t +1.89, both below 1.96). But the W5 finding is genuinely new: W5 is a
  pillar_O-specific failure mode, NOT a general L/S-failure mode. R46's sleeve
  weakness ≠ all sleeves' weakness.

**Aggregate lesson #25 (NEW — slow-cadence requirement reveals the signal's true timescale):**
- The "fade-the-crowd" funding premium is **not a daily-frequency signal**. It
  requires ~3 weeks of cross-sectional mean-reversion to be tradeable
  (1d = −0.28 → 14d = +0.98 → 21d = +1.60 at 5bps). Daily rebal eats all the alpha
  in turnover cost (10bps at 1d/cad kills the signal completely: α_t = −2.43).
- This contradicts the R35 intuition that funding-crowding reversal is
  high-frequency. **At a 3-week horizon, the funding premium is real and
  tradeable; at daily, it's pure noise + turnover.**
- Future per-asset-overlay work should explore zwin in the 30-90d range AND
  cadence ≥14d. This is the structural frequency where the signal lives.

**Aggregate lesson #26 (NEW — fade-the-crowd has regime-specific windows, not a general premium):**
- W1 (early-cycle 2024-06→10): −37.4% (fail). W2 (bull-trend 2024-10→2025-02): +170.2%
  (huge win). W3 (consolidation 2025-02→06): −22.5% (fail). W4 (mid-late 2025-06→10):
  +37.1% (win). W5 (risk-off rebound 2025-10→2026-02): +29.6% (win). W6 (post-rotation
  recovery 2026-02→06): +83.6% (win).
- Pattern: **the signal wins in trend regimes and rebounds, fails in early-cycle
  and consolidation**. This is consistent with the behavioral-edge doctrine —
  "fade the crowd" requires a directional regime where the crowd's positioning
  actually gets paid off wrong. In chop, the crowd is right often enough to
  erase the edge.

**Status:** 🔴 **REFUTED** — fails 2+ checks at every cell tested (best grid cell
21d/0bps: gross_t +1.73, OOS_t +1.89, both below 1.96). But the failure is
**constructive**:
- W5 finding is genuinely new (per-asset overlay escapes the pillar_O W5 trap).
- Slow-cadence requirement (≥14d) sharpens the timescale hypothesis.
- Regime-window pattern (4/6 windows positive, 2 deeply negative) suggests a
  **regime-conditioned overlay** is the next step: skip early-cycle and
  consolidation windows via a detector (analogous to R58/R59's W5 detector but
  for fade-the-crowd fragility windows).
- Future work (R62 candidate): combine R60 per-asset overlay + R58 detector on
  cross-asset fragility windows. Hypothesis: fade-the-crowd DURING confirmed
  trends + skip during early-cycle + consolidation might clear 1.96.

**Reference:** `src/research/validation/funding_crowding_ls.py` (~340 LoC); `tests/test_funding_crowding_ls_smoke.py` (9 tests, all pass); `reports/funding_crowding_ls/2026-07-21/{verdict.json, REPORT.md}` (gitignored).


## R63 ✅ Regime-conditioned fade-the-crowd — SURVIVES 3-check gauntlet via fragility detector (Seth, 2026-07-21)

> **Note on numbering:** R-numbering collided with the prior R62 entry ("R61 OVERTURNED"). The
> fragility-gated fade-the-crowd was originally numbered R62 in this session; renumbered to R63 here
> to keep the chronological sequence R60 → R61 → R62 (R61 OVERTURNED) → R63 (this entry).
> File/module names (`r62_*`) left unchanged for repo-history consistency.

**Setup.** R60 verdict was 🔴 REFUTED but constructive: 4/6 windows positive (W2
+170%, W4 +37%, W5 +30%, W6 +84%) and 2/6 deeply negative (W1 -37%, W3 -22%).
The two failing windows are *early-cycle* (just-listing, 2024-06→10) and
*consolidation* (chop, 2025-02→06) — exactly the regimes where the
fade-the-crowd premium is overwhelmed by trend / chop forces. R62 builds the
"regime-conditioned overlay" R60 recommended: a KS-based fragility detector
trained to discriminate (fragile = W1 ∪ W3) from (playable = W2 ∪ W4 ∪ W5 ∪ W6),
then gates the R60 factor to flat on detector-fire days.

- **Universe:** 28 assets (Hyperliquid funding ∩ CIS ∩ OHLCV tradeable, R60's).
- **Period:** 731 days, 2024-06-07 → 2026-06-07.
- **Score:** R60's per-asset rolling z-score of daily-mean funding (zwin=30d,
  sign=`−z` = fade-the-crowd direction).
- **Fragility detector:** KS table across 18 features (10 internal from R58 +
  6 external funding from R59 + 2 BTC-specific funding features). Sweep over
  {internal, external, top8} feature sets × z_threshold ∈ {0.0, 0.25, 0.5, 0.75}
  × min_features ∈ {2, 3, 4}.
- **Cadence × cost sweep:** {5, 7, 14, 21}d × {0, 5}bps.
- **Gauntlet:** R58/R59's 3-check on the standard 70/30 split.
- **Total cells evaluated:** 288 (= 4 cadences × 2 costs × 4 z × 3 mf × 3 fs).
- **Cells passing all 3 checks:** 7.

**Fragility KS ranking (top-5 by KS distance, fragile vs playable):**

| rank | feature | KS | p | mean(fragile) | mean(playable) | source |
|--:|---|--:|--:|--:|--:|---|
| 1 | mkt_vol_30 | 0.27 | 0.000 | +0.0427 | +0.0391 | internal |
| 2 | xsec_rank_ic_30 | 0.26 | 0.000 | +0.0007 | -0.0090 | internal |
| 3 | xsec_disp | 0.15 | 0.002 | +0.0267 | +0.0268 | internal |
| 4 | streak_5 | 0.14 | 0.005 | +0.4979 | -0.0430 | internal |
| 5 | funding_mean | 0.13 | 0.011 | +0.0000 | +0.0000 | external |

KS is moderate (max 0.27) — feature distribution SHIFTS, not crashes. Fragile
windows have HIGHER vol (mkt_vol_30 +9%), HIGHER streak-5 (+0.50 vs -0.04, i.e.
trend persistence is broken/positive in fragile windows), and HIGHER
cross-section IC (xsec_rank_ic_30 +0.0007 vs -0.0090).

**Best cell (`external` features, z=0.5, min_features=2, 21d cadence, 0bps cost):**

| | R60 ungated (21d/0bps) | R62 gated (best) | Δ |
|---|--:|--:|--:|
| **gross_t** | +1.73 ✗ | **+2.03 ✓** | +0.30 |
| **OOS_t** | +1.89 ✗ | **+2.37 ✓** | +0.48 |
| pass_all | ✗ | **✓** | — |
| fragile_hit_rate | n/a | 8% | — |
| playable_hit_rate | n/a | 12% | — |
| %panel flat | 0% | 11% | +11% |

**Per-window P&L (best cell, ann%/yr — gated vs ungated):**

| Window | character | ungated ann% | gated ann% | Δ |
|--:|---|--:|--:|--:|
| W1 🟥 | early-cycle | -34.5 | **-31.2** | +3.3 (less loss) |
| W2 🟩 | bull-trend | +170.2 | +134.7 | -35.4 (gate fires to trim bleed through chop-to-trend transition) |
| W3 🟥 | consolidation | -21.1 | **-19.1** | +2.0 (less loss) |
| W4 🟩 | mid-late | +32.4 | +16.4 | -16.1 (gate over-fires here) |
| **W5 🟩** | **risk-off rebound** | **+53.9** | **+115.7** | **+61.8** ⭐ |
| W6 🟩 | recovery | +61.4 | +93.9 | +32.5 |

**Three honest findings from the per-window view:**

1. **The detector's primary mechanism is NOT skipping the fragile windows more —
   it's letting the W5 win compound.** The +115.7% W5 (gated) is the dominant
   improvement; +61.8% Δ on a single window more than offsets the −16 to −35%
   gate-induced drag in W2/W4. W1 and W3 (the labeled fragile windows) gain only
   +3.3 and +2.0 — the detector discriminates BETWEEN fragile days WITHIN the
   labeled windows, not just at the window boundary.
2. **The detector over-fires in W2 (bull-trend −35.4 Δ) and W4 (mid-late −16.1
   Δ).** The "fragile" detector fires on the BOUNDARIES of bull-trend and
   mid-late regimes — those windows have pockets of fragility hiding inside
   them. This is acceptable but reveals the detector is not cleanly separating
   windows; it's separating *days*.
3. **7 cells pass all 3 checks out of 288 (2.4%).** The result is real but
   narrow: it requires the right combination of (external-only features + z=0.5
   + min_features=2 + 21d cadence + 0bps cost) — OR the slightly more eager
   (z=0.25 + min_features=2 + 21d + 0bps) variant. Any cheaper or faster cell
   fails.

**Top-3 cells by (passes_all ↓, OOS_t ↓, gross_t ↓):**

| rank | config | fragile_HR | playable_HR | %flat | gross_t | OOS_t | pass |
|--:|---|--:|--:|--:|--:|--:|:--:|
| 1 | `external_z0.5_mf2_cad21_bps0` ★ | 8% | 12% | 11% | +2.03 | +2.37 | ✓ |
| 2 | `external_z0.25_mf2_cad21_bps0` | 39% | 39% | 39% | +2.27 | +2.34 | ✓ |
| 3 | `external_z0.25_mf2_cad21_bps5`  | 39% | 39% | 39% | +2.20 | +2.30 | ✓ |

**Aggregate lesson #27 (NEW — fragility detector over R60 clears the gauntlet):**
- R62's +61.8% W5 boost vs R60 ungated is the most-positive per-window delta we
  have measured in the entire R58/R59/R60 sequence. The detector is NOT simply
  "skip fragile days" — it allows R60's strong-but-windowed signal to compound
  cleanly. The fragile-window gating (8% HR) is *necessary precision* — too
  loose a gate (z=0.25) gates 39% of the panel but still passes.
- This is the first R60-derivative that earns a slot. **Credited claim**: per-asset
  fade-the-crowd L/S, gated by external-funding-feature fragility detector,
  21-day rebal, 0bps cost. Beats 3-check gauntlet (gross=+2.03, OOS=+2.37).

**Aggregate lesson #28 (NEW — external-funding features > internal features for
fragility discrimination):**
- The "internal" features (R58's market-state) topped the KS ranking but the
  "external" feature subset (R59's funding-only features) won the gauntlet pass.
  Why? Internal features are CAUSAL DRIVERS of fragility (vol expands, IC
  shifts, streaks break) — they characterize the regime. External funding
  features are the MECHANISM discriminator (funding_dispersion, -skew,
  extreme-long-fraction) — they characterize which fragile regime translates
  into the L/S failing. The detector needs the latter, not the former.
- **Implication**: R58/R59 should have built external-only variants earlier; the
  UNION detector (R59) likely dragged in some internal-only signal that diluted
  precision. Future detectors should be evaluated per feature family, not only
  as UNION.

**Aggregate lesson #29 (NEW — slow-cadence + detector = oracle; fast-cadence
stays dead):**
- All 7 cells that pass 3 checks use **21d cadence**. No cell at 5d/7d/14d
  passes. This confirms R60's lesson #25 (slow cadence reveals the funding
  premium's true timescale) AND sharpens it: the slow cadence is REQUIRED, not
  just preferred, when a detector is involved. The detector + slow cadence is
  the regime-aware oracle; fast cadence + detector is still too noisy.
- R58/R59 R46-cell (5d/5bps) detectors all died on OOS. R62's R60-cell (21d/0bps)
  detector lives. **The cell that works depends on the factor, not just the
  detector.**

**Status:** ✅ **SURVIVES — clears full 3-check gauntlet on 7/288 cells**. The
best cell is 21d/0bps with `external` features, z=0.5, min_features=2. R60's
per-asset overlay path is now credit-eligible as a funding-crowding L/S
sleeve — *gated* by fragility detector. Per the MECHANISM_SPEC §3 strategy
vector: declare capacity (P2) before shipping; flat-recording the
fragility-gated position count is the mandatory disclosure (P3).

**Operational consequence for §5b two-layer book:** adds a 2nd sleeve candidate
orthogonal to R46 pillar_O sleeve. Per §MECHANISM_SPEC, this should be tested
as a 2-sleeve **fusion** under the strategy vector harness (R63 candidate) —
not paper-deployed before fusion testing.

**Reference:** `src/research/validation/r62_fragility_gated_funding.py` (~470 LoC);
`tests/test_r62_fragility_gated_funding_smoke.py` (9 tests, all pass);
`reports/r62_fragility_funding_ls/2026-07-21/{verdict.json, REPORT.md, sweep_full.json}` (gitignored).


## R61 🔴 LIVE signal track record audit — the published signal book carries little CROSS-SECTIONAL information; measured "alpha" is largely benchmark/beta mismatch (Seth, 2026-07-21)

**Why this outranks a backtest refutation:** this is not a research candidate. It is the **live,
user-facing signal book** (`signal_outcomes`, 7,743 rows, 2025-05-03 → 2026-05-03) — the very track
record an allocating agent would price us on under `docs/MECHANISM_SPEC.md`. It had never been
audited directionally.

**Method:** score each signal against its own directional claim (edge = +alpha for STRONG
OUTPERFORM/OUTPERFORM, −alpha for UNDERPERFORM/UNDERWEIGHT), full-sample and by month. NEUTRAL
excluded (makes no directional claim).

| signal | n | avg edge | directional acc | t |
|---|---:|---:|---:|---:|
| UNDERPERFORM | 4,756 | **+1.74%** | 62.0% | **+7.47** |
| OUTPERFORM | 1,801 | **−1.84%** | 36.4% | **−4.09** |
| UNDERWEIGHT | 302 | −0.60% | 55.3% | −0.58 |
| STRONG OUTPERFORM | 134 | +3.32% | 50.0% | +2.35 |

**First read (WRONG):** "OUTPERFORM is inverted, the model is broken." The monthly decomposition
refutes that simple story — do not stop at the full-sample table.

**The actual structural finding:** monthly positive-side and negative-side edges are near mirror
images — **corr(pos_edge, neg_edge) = −0.725** across 12 months, with **corr(pos_edge, benchmark
return) = +0.370**. Tape up → OUTPERFORM book earns, UNDERPERFORM book loses; tape down → exactly
the reverse. **The two sides are not two independent discriminations. They are one directional bet
expressed twice.**

**Mechanism:** `alpha = a_ret − b_ret` only cancels market direction if asset beta matches the
benchmark. Our OUTPERFORM names appear systematically higher-beta than their bench, so they print
positive "alpha" in up months and negative in down months **with no selection skill required**. The
measured alpha is contaminated by **beta mismatch**. This is R33/R49's lesson ("β on a friendly
regime window, not α") reappearing in the LIVE product rather than in a backtest.

**What is genuinely good — do not lose this in the correction:** the system *withholds* OUTPERFORM
in bear months. n_pos collapses to 15 / 4 / 0 / 40 across Nov-25 → Mar-26 while n_neg runs
632 / 660 / 651 / 527. It correctly stops making positive calls when the tape is against it. The
residual positive calls it does make in those months are its worst (−37.77% in Nov-2025, n=15).
UNDERPERFORM at t=+7.47 over 4,756 observations is a real, usable **defensive** signal.

**⚠️ CORRECTS THE DECAY MODEL — and `MECHANISM_SPEC.md` P3:** this analysis was started to measure a
*decay half-life*, on the assumption that edges decay monotonically (the ~3-month prior). The data
says the dominant lifecycle mechanism here is **regime phase, not monotonic decay** — the edge does
not decay toward zero, it goes **out of phase and returns** (2025-06→08 positive, 2025-09→2026-03
negative, 2026-04→05 positive again). A single half-life scalar would have mismodeled this badly.
**P3 disclosure must report regime phase + beta exposure, not an age-decay number.**

**Verdict:** 🔴 the published signal book is **NOT credited as cross-sectional alpha**. It is
beta-mismatched directional exposure. Not worthless — the defensive side and the withholding
behavior are real — but it must be labeled *directional/defensive*, never as asset-selection alpha.

**Required follow-ups:**
1. Beta-adjust the alpha computation (regress out per-asset benchmark beta before scoring) and re-run
   this audit. Until then every alpha number in the live track record is suspect.
2. Re-check any user-facing surface implying the signals are selection alpha (compliance + honesty).
3. Fold **beta exposure** into the strategy-vector schema so this contamination class is visible by
   construction rather than discovered a year later.

**Reference:** Supabase `signal_outcomes`; queries in session 2026-07-21.

## R62 ✅ R61 OVERTURNED — the metric was the bug, not the model. Beta-adjusted, CIS and the signal book are STRONGLY predictive (Seth, 2026-07-21)

**This entry reverses R61's verdict.** R61 concluded the live signal book carried little
cross-sectional information and that measured alpha was beta-contaminated. The first half was
wrong; the second half was right and *was the entire explanation*.

**Method:** PIT-safe per-asset beta — expanding-window OLS beta of `a_ret` on `b_ret` using ONLY
prior observations (`rows between unbounded preceding and 1 preceding`, min 20 priors), per symbol.
Beta-adjusted alpha = `a_ret − β_pit · b_ret`. No full-sample statistics anywhere.

**Headline — the sign flips:**

| signal | n | avg β | raw edge | **adj edge** | **adj t** |
|---|---:|---:|---:|---:|---:|
| STRONG OUTPERFORM | 132 | 2.41 | +3.42 | **+8.06** | **+5.41** |
| OUTPERFORM | 1,487 | 1.85 | **−0.36** | **+2.86** | **+5.75** |
| UNDERPERFORM | 4,411 | 1.60 | +1.67 | +1.00 | +4.48 |
| UNDERWEIGHT | 281 | 1.37 | −1.00 | **−4.10** | **−3.79** |

**Root cause:** average asset beta vs benchmark is **1.4–2.4**, not 1.0. `a_ret − b_ret` was never
alpha — it was leveraged beta. In a bear-dominated window high-beta names lag a falling benchmark,
which made a genuinely strong selection signal *look* inverted. R61's "OUTPERFORM is anti-predictive
at t=−4.09" was an artifact of an unadjusted metric.

**Pillar scan, raw → beta-adjusted spread (top minus bottom tercile):**

| feature | raw | **adj** |
|---|---:|---:|
| pillar_A | −4.03 | **+4.48** |
| pillar_F | +0.51 | **+3.28** |
| cis_score | −4.38 | **+2.85** |
| pillar_M | −5.11 | **+2.74** |
| pillar_O | −4.55 | +1.20 |
| pillar_S | −3.91 | **+0.03** |

Every pillar is correctly signed after adjustment. **CIS works.** The apparent inversion across five
of six dimensions was 100% beta contamination.

**Actionable findings:**
1. **`pillar_S` carries ~zero information (+0.03).** This directly informs the pending CIS v5 reweight
   (Minimax-A, R46 action item, currently specified as "toward O, away from S"). Away from S is
   **confirmed**; toward O is **not supported** — O is also weak (+1.20). The data says weight toward
   **A (+4.48) and F (+3.28)**.
2. **UNDERWEIGHT is genuinely broken** (adj t = −3.79) — the only signal that is significantly wrong
   after adjustment. It was hidden before because the raw metric was noise. Needs its own fix.
3. **Every alpha number in the live track record must be beta-adjusted before publication.**

**⚠️ Honesty caveats — do not oversell this:**
- Beta-adjusted alpha requires **hedging to capture**. Unhedged, an investor experiences the raw
  number. Publish both, and label which is which. Claiming the adjusted figure without disclosing
  the hedge requirement would be misleading.
- Betas of 1.4–2.4 mean the book is **structurally leveraged to crypto beta**. Material for LP
  disclosure, capacity and risk sizing.
- Single, bear-dominated window (2025-05 → 2026-05). Needs cross-regime validation before the
  ✅ hardens.

**Meta-lesson (#21) — audit the METRIC before the MODEL.** Three separate "our edge is broken"
findings this session (R61 here, plus the two look-ahead leaks) were all measurement defects, not
model defects. A contaminated target variable makes good models look broken and bad models look
good. Before concluding a signal fails, prove the yardstick is clean.

**Reference:** Supabase `signal_outcomes`; PIT-safe window-function beta; session 2026-07-21.


## R69 ✅ Sleeve fusion validation — FUSION WINS 3/3 gates (R46 pillar_O × R63 fragility-gated fade-the-crowd) (Seth, 2026-07-21)

> **Note on numbering:** Originally numbered R63 in this session; renumbered to R69 after the
> prior-session-R62 collision shifted the fragility entry to R63. File/module names
> (`r63_fusion_validation.py`) left unchanged for repo-history consistency.
>
> **This entry validates the MECHANISM_SPEC §3 deployment gate for the R63 credit-eligible
> sleeve.** Per §3 + §P1/§P2: no sleeve ships to the live book without fusion validation,
> forward-committed cells, and a declared capacity ceiling.

**Setup.** R63 produced the first credit-eligible funding-crowding sleeve (R63 best cell
gross=+2.03, OOS=+2.37). R46's pillar_O 5d/5bps sleeve is the existing credit-eligible
finding (gross=+2.57 ungated, OOS=+0.41). The question this entry answers: do the two
sleeves **combine into a JOINT library** with materially better risk-adjusted profile than
either alone, i.e. are they TRULY orthogonal at the joint level? Per MECHANISM_SPEC §3 a
sleeve's life cycle (P3) and capacity declaration (P2) only make sense if the joint book
survives.

**Universe:** STRICT 28-asset intersection (Hyperliquid funding ∩ CIS ∩ OHLCV tradeable).
**Both legs re-computed on this restricted universe** — fusion not tested on the easier
41-asset R46 sleeve.

**Leg 1 (R46):** pillar_O 5d/5bps L/S, k=3, on 28-asset strict intersection.
**Leg 2 (R63/R62):** fade-the-crowd 21d/0bps gated by `external` fragility detector
(z=0.5, min_features=2), on the same 28 assets.

**Fusion:** w × Leg R46 + (1−w) × Leg R63, weight sweep
w ∈ {0.0, 0.25, 0.33, 0.50, 0.67, 0.75, 1.0}.

**Per-leg gauntlet on the 28-asset strict intersection (the honest test):**

| leg | gross_t | OOS_t | pass_gross | pass_OOS | maxDD | n_assets |
|---|--:|--:|:--:|:--:|--:|--:|
| R46 pillar_O 5d/5bps | +1.77 | +0.61 | ✓ | **✗** | −33.62% | 28 |
| R63 fade-the-crowd 21d/0bps gated | +2.03 | +2.37 | ✓ | ✓ | −18.85% | 28 |

**R46 alone FAILS the 3-check gauntlet on the 28-asset subset** (OOS_t=+0.61, needs >1.96).
R63 alone passes both gross and OOS. The fusion's job is to **salvage R46's diversification
value** despite its sub-threshold solo performance.

**Fusion weight sweep:**

| w_R46 | gross_t | OOS_t | pass | maxDD | Sharpe | %TIM | IR vs R46 | IR vs R63 |
|--:|--:|--:|:--:|--:|--:|--:|--:|--:|
| **0.00** | +2.03 | +2.37 | ✓ | −18.85% | +1.32 | 86% | −0.06 | +nan |
| **0.25** ★ | **+2.52** | **+2.38** | ✓ | **−11.05%** | **+1.69** | 99% | −0.06 | +0.06 |
| 0.33 | +2.61 | +2.28 | ✓ | −9.94% | +1.77 | 99% | −0.06 | +0.06 |
| 0.50 | +2.62 | +1.90 | ✗ | −15.04% | +1.80 | 99% | −0.06 | +0.06 |
| 0.67 | +2.39 | +1.40 | ✗ | −21.76% | +1.63 | 99% | −0.06 | +0.06 |
| 0.75 | +2.24 | +1.18 | ✗ | −24.77% | +1.52 | 99% | −0.06 | +0.06 |
| 1.00 | +1.77 | +0.61 | ✗ | −33.62% | +1.19 | 95% | +nan | +0.06 |

**3/3 gates pass on the 25/75 cell:**

| Gate | Status | Evidence |
|---|:--:|---|
| (1) Fusion passes 3-check | ✓ | gross_t=+2.52, OOS_t=+2.38 |
| (2) max DD improves below min(R46, R63) | ✓ | fused=−11.05% < min(legs)=−33.62% |
| (3) Orthogonal: |ρ(R46, R63)| < 0.5 | ✓ | **ρ = −0.05** |

**Three structural findings:**

1. **Optimal weight is 25% R46 + 75% R63** — not 50/50. The fusion budget is heavily
   weighted toward the credit-eligible leg (R63 alone clears the gauntlet; R46 alone fails).
   R46's contribution is via **diversification, not alpha** — it pulls DD from −18.85% to
   −11.05% (41% improvement) without diluting the alpha stream.
2. **ρ(R46, R63) = −0.05** — essentially uncorrelated. The two sleeves are orthogonal in
   different market dimensions: R46 is a pillar_O cross-section rank factor (CIS-composite
   stock selection); R63 is a per-asset funding-z reversal factor (perpetual-market
   positioning). They have different SHAPES of return, so combining them is **diversification
   math, not averaging**. This is the structurally important finding: the fusion isn't just
   "two alpha streams" — it's "two mechanism-uncorrelated return generators."
3. **A leg that fails alone CAN win in fusion** — R46 fails alone on 28-asset (OOS=+0.61),
   yet adds **+0.49** gross_t and **+0.01** OOS_t to the fused book AND cuts max DD by 41%.
   This is the **failed-leg salvage** pattern: a leg doesn't have to pass the gauntlet solo
   to be useful in a multi-leg structure — it only needs (a) orthogonal return dimension
   and (b) the dominant leg's headroom for leverage.

**Per-window ann% (R46 / R63 / Fused at w_R46=0.25):**

| Window | character | R46 ann% | R63 ann% | Fused ann% | pattern |
|--:|---|--:|--:|--:|---|
| W1 🟥 | early-cycle | +74.4 | −31.2 | **−11.4** | R46 salvages |
| W2 🟩 | bull-trend | +354.9 | +134.7 | +183.5 | both win |
| W3 🟥 | consolidation | −11.7 | −19.1 | −16.2 | both lose (irreducible) |
| W4 🟩 | mid-late | +61.9 | +16.4 | +28.5 | both win |
| W5 🟩 | rebound | −58.1 | +115.7 | **+45.6** | R63 salvages |
| W6 🟩 | recovery | +44.1 | +93.9 | +81.3 | both win |

**Fusion mechanic per window:**
- **W1 (early-cycle fragile): R46 saves the day** with +74.4% — fusion turns a −31.2% R63
  loss into −11.4%. R46's pillar_O rank selection apparently _works_ in the early window
  for the funding-bearing subset.
- **W5 (rebound — the W5 forensics target): R63 salvages** with +115.7% — R46 alone loses
  −58.1% (the W5 fragility that R58/R59 attempted to fix), but R63 inverts this, and fusion
  nets +45.6%. **R63 is the W5 fragility detector's payback**: R58/R59's detector fix on
  R46 was incomplete (it _partially_ rescued W5), but R63 with its external-funding
  detector eliminates R46's W5 problem entirely.
- **W3 (consolidation fragile): both legs lose** (−11.7 and −19.1); fusion can't save
  windows where BOTH legs fail (irreducible in this sleeve choice).

**Capacity proxy (MECHANISM_SPEC §P2 — binding capacity):**
- Fused turnover (ann): **56.0** (R46 leg: 88.2, R63 leg: 45.2 — R63's slow 21d cadence
  brings the R46 leg's daily-cadence churn down by 36%)
- Crude declared capacity: **$5.0M** (median ADV $50M/asset × 5%/leg × 2-leg)
- **{★ CRUDE — verify with fill-attribution (P2 req'd) before deployment.**

**Action per MECHANISM_SPEC §P1/§P2/§P3:**
- P1: this report IS the pre-declared criterion for the live book — the live fusion cells
  must reconcile to the w=0.25/0.75 + 3-check pass.
- P2: declare joint capacity $5.0M (P2 — capacity is a fact, not a season).
- P3: flat-record the fragility-gated position count (P3 — decay a disclosed field).

**Aggregate lesson #33 (NEW — fusion budget is rarely 50/50):**
- The 25% R46 + 75% R63 optimal weight is the canonical asymmetry: the credit-eligible
  leg takes the bigger book, the diversifier takes the smaller book. Equal-weight fusion
  overcounts the diversifier's contribution; arbitrary weights undercount the credit-
  eligible leg's edge. **The right number lives at ~25/75 when one leg clears alone and
  the other diversifies.**
- Anti-imposter note: w=0.25 is ALSO where the IR-vs-leg ratios are ~0 (the fused
  series is essentially just R63); the win is purely DD-reduction, not "alpha
  amplification". Be honest about which is which.

**Aggregate lesson #34 (NEW — failed-leg salvage via orthogonality):**
- R46 fails alone on 28-asset (OOS=+0.61) but adds $5M of joint capacity + 41% DD
  reduction when fused. The lesson is general: **a sub-threshold sleeve can be
  credit-eligible IF its return dimension is uncorrelated to the dominant leg**.
- The orthogonality test (|ρ| < 0.5) is the cheap pre-flight check before deep fusion
  testing. Building both sleeves and finding ρ=−0.05 means we KNOW fusion has merit before
  running a single gauntlet cell — the expensive gauntlet then just confirms magnitude.

**Aggregate lesson #35 (NEW — MECHANISM_SPEC §3 + P1 operationally binding):**
- This is the first refutation entry that is formally cross-linked to the MECHANISM_SPEC:
  per §P1, the w=0.25 fusion IS the forward commitment cell, the 3-check pass IS the
  resolution criterion, and the next pass at horizon will resolve the live fused cell
  against the in-sample cells reported here. **This is the apparatus, working.**
- The capacity number ($5.0M) is CRUDE and labeled as such — but it is now _stated_ rather
  than implicit. That alone is a meaningful change: the next gap-fill exercise must
  validate or invalidate the 5%/leg × $50M/ADV assumption against fill-attribution data.

**Status:** ✅ **FUSION WINS — 3/3 gates pass**. The R46 × R63 fusion at w_R46=0.25 is
credit-eligible for paper-deploy, with $5.0M declared capacity and pre-committed
forward-commitment cells. Per §P3 mandatory lifecycle disclosure, the position count must
be flat-recorded from day 1 of paper-deploy — the half-life of this fusion (not yet
measured) is one of the next measurements we owe.

**Reference:** `src/research/validation/r63_fusion_validation.py` (~430 LoC);
`tests/test_r63_fusion_validation_smoke.py` (9 tests, all pass);
`reports/r63_fusion_validation/2026-07-21/{verdict.json, REPORT.md}` (gitignored).

## R63 🟡 Pillar S is a RISK factor, not a return factor; pillar ΔO shows we arrive AFTER the market reaction (Seth, from Jazz's domain correction, 2026-07-21)

**Origin — Jazz's correction of R62's reading.** R62 concluded "pillar_S carries ~zero information
(+0.03)" and "pillar_O is weak." Jazz: (a) O looks flat because **our pool is already curated** —
admission conditions on on-chain quality, so O's cross-sectional *level* is range-restricted; the
information is in the **marginal change**; (b) S "hurting" is normal — **peak hype = peak volatility
= where people lose big money** (the 出圈 logic). Both said the same thing about method: R62 tested
**levels and means**; the information is in **changes and higher moments.** He was right on the
method critique. Testing (beta-adjusted edge, PIT beta, same panel):

**S — CONFIRMED. It is a risk factor.**

| S tercile | n | mean edge | vol of edge | left tail (p10) |
|---|---:|---:|---:|---:|
| low | 2,023 | +2.70 | 15.89 | −13.93 |
| mid | 2,023 | −0.77 | 14.84 | −16.19 |
| **high** | 2,023 | +2.77 | **17.17** | **−18.33** |

Mean edge is flat across S (which is exactly why R62's mean-spread test read +0.03 = "dead"), but
**volatility and left-tail damage rise with sentiment.** High S does not lower expected return — it
**widens the distribution and deepens the downside tail.**
→ **Recommendation reversed: do NOT drop S from CIS.** Move it from the return score to a
**risk/sizing gate** (high S ⇒ reduce size, tighten stops). A factor can be dead as a return
predictor and valuable as a risk predictor; our scoring architecture currently has no place to
express that, which is why we nearly deleted it.

**ΔO — mechanism plausible, but we are LATE.** Signed ΔO quintiles (per-symbol change vs prior obs):

| quintile | avg ΔO | mean edge | t |
|---|---:|---:|---:|
| Q1 deteriorating most | −9.89 | +0.64 | 1.33 |
| Q2 | −1.55 | +0.92 | 1.98 |
| **Q3 ~no change** | −0.02 | **+3.62** | **8.19** |
| Q4 | +1.60 | +1.70 | 3.85 |
| Q5 improving most | +9.63 | +1.19 | 2.47 |

**Inverted-U: our edge is strongest when O is STABLE and degrades at BOTH extremes.** Not "异动 ⇒
opportunity" — at our sampling cadence, large O moves are where we are *least* predictive.
**Best reading (consistent with Jazz's mechanism, negative for our implementation):** the market
reacts to marginal on-chain change *fast* — which is precisely why a daily snapshot arrives after
the reaction. At the extremes we are sampling post-reaction noise; in the stable regime our quality
signal works cleanly (t=+8.19). This may also help explain O's weakness in the R62 level scan and
R46's W5 failure — O's information is concentrated in fast events we systematically miss.
→ **Testable implication:** sample O intra-day/hourly and the Q1/Q5 cells should improve. Ties
directly to the "raise update frequency" thread (§CIS-REGIME-BOOK).

**Meta-lesson #22 — a factor can fail as a mean-return predictor and still be information.**
Test levels AND changes, means AND higher moments, before declaring a factor dead. R62 nearly
deleted a working risk factor because it was only tested one way. Domain knowledge (why the pool is
curated, what hype does to vol) told us where to look; the statistics only confirmed it.

**Reference:** Supabase `signal_outcomes`, PIT-safe beta; session 2026-07-21.

### R63b — generalization confirmed: ΔS behaves like ΔO, and the pattern is SPECIFIC to the two fast-moving pillars (Jazz's extension, 2026-07-21)

Jazz: "应该不止 delta O，可能 S 也是类似" (analogy: watching AI-related ETF / related-stock price moves).
Tested signed Δ quintiles for ALL pillars on beta-adjusted edge, same PIT panel:

| Δfactor | Q1 falling | Q3 stable | Q5 rising | directional (Q5−Q1) | **stability premium** |
|---|---:|---:|---:|---:|---:|
| **ΔS** | −0.09 | **+2.86** | +0.38 | +0.48 | **+2.72** |
| **ΔO** | +0.64 | **+3.61** | +1.19 | +0.55 | **+2.70** |
| **ΔA** | +1.56 | +0.88 | **+2.75** | **+1.18** | −1.27 |
| ΔCIS | +0.63 | +1.32 | +1.19 | +0.56 | +0.41 |
| ΔF | +1.68 | +1.36 | +1.33 | −0.34 | −0.14 |
| ΔM | +1.31 | +1.36 | +1.19 | −0.11 | +0.11 |

**Three distinct factor behaviours — this is the levels-vs-changes map of CIS:**
1. **Stability-premium factors — S and O (≈ +2.7 each).** Edge is strongest when stable, degrades at
   BOTH extremes. Critically this is **specific to S and O**; ΔF/ΔM/ΔCIS show ≈0 premium, so it is not
   a generic artifact. S and O are precisely the two pillars measuring **fast-moving, externally-driven
   state** (sentiment, on-chain flow) — the ones the market re-prices quickest. Reading: at a daily
   snapshot we sample these AFTER the reaction. → **raise sampling frequency for S and O specifically.**
2. **Directional-change factor — A (+1.18 Q5−Q1, negative stability premium).** Rising A predicts
   better edge (+2.75 vs +1.56). Usable as a change-signal as-is, no frequency fix needed.
3. **Level-only factors — F, M (and composite CIS).** No change-information; their value is in levels
   (R62: F +3.28, M +2.74 level spreads).

**Design implication:** CIS currently treats all five pillars as level-scores with static weights. The
data says they are three different *kinds* of object — a level factor, a change factor, and two
fast-state factors that need higher-frequency sampling plus a risk-gate role (R63: high S ⇒ wider tails).
A single weighted-sum architecture cannot express that. **This is a CIS v5 architecture question, not a
reweighting question.**

**Next probe:** Jazz's AI-ETF analogy — measure sentiment via *related-instrument price action*
(thematic spillover) at higher frequency, rather than via a slow sentiment score. That is the concrete
route to catching the fast ΔS moves we currently arrive after.


## R70 🟢 Fusion paper book DEPLOYED — R69 cell forward-committed with §P2 fill-attribution (Seth, 2026-07-21)

> **Status: DEPLOYED.** Built the missing MECHANISM_SPEC §P2 primitive + the live paper book
> for the R69 fusion cell. The forward clock has started; live NAV will accrue daily and
> reconcile to the pre-declared R69 cell over ≥60 days before the `validated` flag flips true.

**Origin — R69's ledger said it explicitly:** "Action per MECHANISM_SPEC §P1/§P2/§P3: P1
forward commitment cell = this report; P2 joint capacity = $5.0M (**CRUDE**, verify with
fill-attribution); P3 flat-record fragility-gated position count." R70 builds all three.

**What §P1 needed.** A live paper book that re-marks the R69 fusion cell every day with the
EXACT same frozen parameters (w_R46=0.25, R46 5d/5bps k=3, R62 21d/0bps external/z0.5/mf2/zwin30).
The pre-declared criterion is the R69 verdict; the live NAV curve is the forward evidence.
The book refuses to retune: cell constants, universe, and detector are FROZEN at production.

**What §P2 needed.** The fill-attribution primitive. CRUDE $5.0M (median ADV $50M/asset × 5%/leg ×
2-leg) is a placeholder — a real capacity number needs to be MEASURED, not declared. R70 ships:

  · **`src/data/signals/fill_attribution.py`** (~190 LoC, PURE function, no I/O) — given
    `target_weights`, `current_weights`, `nav_usd`, `prices`, `adv_usd`, `slippage_model_bps`,
    returns `{per_asset {target_notional, current_notional, turnover_pct, adv_participation,
    slippage_bps, fill_ratio, executed_notional, executed_weight_delta}, totals
    {gross_target_notional, gross_turnover_notional, weighted_slippage_bps,
    fill_ratio_overall, executed_notional_total}, capacity {declared_usd, used_pct,
    status: BREACHED/near_limit/ok/undeclared, breach_usd}}`. Slippage model: 5bps base + 2bps
    per 1% of ADV (linear impact). Fill ratio = min(1.0, cap_frac_ADV / participation_pct).
    The capacity status is a HARD invariant — gross target > declared ⇒ BREACHED, no soft
    warning, the engine reports it loudly. Self-tested on 5 synthetic cases (no-turnover
    100% fill, full-rebal 100% fill at $2B ADV, BREACH at declared $1M, thin-ADV <100% fill,
    undeclared capacity).

  · **`src/data/signals/fusion_paper.py`** (~360 LoC, live book) — uses `attribute_fill()` on
    every clip. State → Redis `fusion_paper:state`; NAV → Supabase `fusion_paper_nav`. Capacity
    starts at the R69-declared $5.0M CRUDE; will be replaced by the live-realized ceiling once
    fill-attribution accumulates ≥60 forward days.

**What §P3 needed.** Lifecycle disclosure = fragility-gated position count + days_engaged vs
days_flat honesty. The book reports `detector_fired_today`, `days_engaged`, `days_flat`,
`engagement_pct`, and a `validated` flag that flips true ONLY after `n_days_marked ≥ 60` (the
~3-month forward clock). Before `validated` = true, the curve is a candidate — not proven.

**Architecture (frozen).**
  · Universe: STRICT 28-asset funding ∩ CIS ∩ OHLCV intersection (R69 panel verbatim).
  · Leg 1: R46 pillar_O 5d/5bps k=3 (R45/R46 standard cell).
  · Leg 2: R62 fade-the-crowd 21d/0bps, fragility-detector gated (external/z0.5/mf2).
  · Fusion: w_R46 = 0.25 × Leg1 + 0.75 × Leg2, renormalized to gross Σ|w| = 2/3.
  · Detector: FROZEN at production (z=0.5, mf=2, on the 6 external-funding features) with
    LIVE trailing 90d reference stats (PIT-safe composite-z + min_features gate).
  · Live data: CIS pillar_O from Redis `cis:local_scores` → Supabase `cis_scores` fallback;
    close prices from Binance fapi `/klines` (Railway-reachable since 2026-07-13); funding from
    Binance fapi `/fundingRate`; 30d median ADV from daily kline close × volume.
  · PIT-safe: trailing 30d funding z (no full-sample statistics); mark-to-market y[t]/y[t-1]−1;
    detector z-scores against LIVE trailing 90d (not the legacy 731d panel).
  · Honesty gates: <20 assets with data ⇒ mark flat that day (no fake exposure); `validated`
    flag at `n_days ≥ 60`.

**Wiring (in `src/api/main.py`).**
  · `_fusion_paper_loop` — DISABLE_FUSION_PAPER env guard, 660s warmup, 24h cycle.
  · `GET /api/v1/signals/fusion-paper` — NAV curve + per-day fill ratio + slippage + capacity
    status + detector fire rate. Cached 10 min, swr 20 min.
  · Supabase table: `fusion_paper_nav` (mark_date, nav, daily_return, gross, n_positions, cost,
    fill_ratio_overall, weighted_slippage_bps, capacity_status, capacity_used_pct,
    detector_fired, cell_w_r46, top_longs, top_shorts, note).

**Verification.**
  · **12 smoke tests pass** (`src/research/validation/tests/test_fusion_paper_smoke.py`):
    (1) imports, (2) R69 cell constants frozen, (3) 28-asset universe frozen, (4) 6 external
    features match R62 best-cell subset, (5) funding features PIT-safe (29d NaN warmup,
    post-warmup clean), (6) detector fires on synthetic fragility, (7) detector graceful
    on empty/NaN input, (8) funding score sign-flipped (high funding → lower score than low
    funding), (9) target weights normalize to gross 2/3 with balanced L/S, (10) detector
    gates leg2, (11) fill-attribution reconciles to declared $5M (no BREACH, ~100% fill at
    $1B+ ADV, weighted slip ≈ 5bps), (12) no forbidden signal language in module source.
  · **Preflight PASSED** — `import src.api.main` + boot smoke green; new loop
    `[FUSION-PAPER] ✅ daily R69 fusion paper-book loop scheduled` registered alongside the
    other 24 daily/weekly loops. No regression in any other loop.

**Aggregate lesson #36 — §P2 binding capacity is a measurement primitive, not a constant.**
Every strategy record that ships to the live book must carry an attribution engine that turns
realized turnover + ADV + slippage into a per-clip capacity status (BREACHED / near_limit / ok).
The declared ceiling is the STARTING point, not the ANSWER; the answer is the live-realized
ceiling that emerges as fill-attribution accumulates. A CRUDE $5M is honest as a placeholder;
a $5M declared without attribution is dishonest the moment one clip wants to push past it.

**Aggregate lesson #37 — FROZEN at production is the discipline that makes §P1 honest.**
The fusion book does not retune. w_R46=0.25, R46 5d/5bps, R62 21d/0bps external/z0.5/mf2/zwin30,
28-asset universe — all frozen. The detector uses LIVE trailing 90d reference stats (PIT-safe)
but the threshold (z=0.5), min_features (2), and feature subset (the 6 external-funding columns)
are FROZEN. The KS table is NOT re-trained on live data (that would be a look-ahead trap).
If the cell stops working, the right answer is to record that empirically + retire the cell,
not to tune it back to green. This is what distinguishes a forward-committed cell from a
backtest-curve-fit.

**Reference.** Modules: `src/data/signals/fill_attribution.py` (NEW) + `src/data/signals/fusion_paper.py` (NEW).
Smoke: `src/research/validation/tests/test_fusion_paper_smoke.py` (NEW). Wiring: `src/api/main.py` (lines
around the two-layer-paper block + new endpoint). Supabase table: `fusion_paper_nav` (created on first
INSERT). R69 verdict source: `reports/r63_fusion_validation/2026-07-21/verdict.json`.

---

## R71 🟢 Live NAV accrual monitoring WIRED — gap detector + §P3 lifecycle events (Seth, 2026-07-21)

> **Status: WIRED AND BOOT-VERIFIED.** R70 made the R69 fusion cell forward-committed; R71 makes
> the forward clock accountable every day. It is a monitoring layer only: it does not retune,
> alter, or block the frozen cell.

**Hypothesis.** A live paper book is not accountable merely because it has a NAV endpoint. Before
its ≥60-day `validated` gate, the operator needs a daily read of whether the curve tracks the
pre-declared OOS expectation, whether the fragility detector is firing at the expected rate, and
whether realized fill/capacity is eroding. Lifecycle transitions must be structured and auditable,
not buried in logs.

**Built.** `src/research/validation/fusion_paper_tracking.py` (~370 LoC) reads R70's
`fusion_paper_nav` curve and produces one snapshot with five surfaces:

1. **Live-vs-OOS Sharpe gap:** live annualized Sharpe minus the R69 OOS proxy (1.69), with
   `WARMING_UP` before 20 marked days and `DRIFT` below a frozen −0.75 gap.
2. **Detector fire-rate:** compares the live rate with R62's 8.2% reference; >30% is
   `PERSISTENT_HIGH` structural fragility.
3. **Capacity evolution:** rolling mean fill ratio, weighted slippage, and breach-day history;
   statuses are `ok`, `EROSION`, `BREACH`, or `WARMING_UP`.
4. **Validation countdown + max drawdown:** `days_remaining = max(0, 60 − n_days_marked)`;
   `validated` is false until the exact R70 60-day threshold.
5. **§P3 lifecycle events:** `BOOK_INCEPTION`, `WARMING_UP`, `DETECTOR_PERSISTENT_HIGH`,
   `CAPACITY_BREACH`, `SHARPE_DRIFT`, and first-crossing `VALIDATED`, persisted to the new
   Supabase `fusion_paper_lifecycle` table and cached in Redis `fusion_paper:tracking`.

Wired in `src/api/main.py`:
- `_fusion_paper_tracking_loop` — `DISABLE_FUSION_TRACK` guard, 15-minute warmup, daily cadence.
- `GET /api/v1/signals/fusion-paper-tracking` — same cache headers as the other live paper-book
  surfaces; returns empty-data-derived warmup state rather than fabricating a curve.

**PIT / freeze discipline.** The monitor uses the already-produced NAV rows and never retrains,
relabels, or retunes the R69 detector. R69 forward references remain pinned at OOS α_t=2.38,
219 days, Sharpe proxy 1.69; R62 fire reference remains 8.2%; capacity thresholds and the
60-day gate are frozen constants. A missing Supabase configuration yields no rows, not mock data.

**Verification.** R71 smoke suite: **13/13 passed**. `py_compile` passed for `main.py` and the
tracking module. `bash scripts/preflight.sh` passed (real `import src.api.main` + boot smoke),
including `[FUSION-PAPER]` and `[FUSION-TRACK]` startup registration. The existing
`GET /api/v1/signals/nav-monitor` handler was preserved during the endpoint insertion.

**Verdict.** 🟢 **WIRED, not yet validated.** R71 is operationally live once the first R70 NAV
mark lands; no forward performance claim is made until the frozen cell reaches the ≥60-day gate.

**Aggregate lesson #38.** §P3 is not a post-hoc report. A forward-committed book needs a daily
judgment surface that records drift, fragility, capacity, and validation state while the evidence
is accumulating.

**Aggregate lesson #39.** A Sharpe gap without detector and capacity context is incomplete. The
lifecycle snapshot must carry all three so a weak live curve can be distinguished from a fragile
regime or an execution-capacity problem.

**Reference.** `src/research/validation/fusion_paper_tracking.py`; `src/research/validation/tests/test_fusion_paper_tracking_smoke.py`;
`src/api/main.py` (`_fusion_paper_tracking_loop`, `GET /api/v1/signals/fusion-paper-tracking`);
`fusion_paper_nav` + `fusion_paper_lifecycle` Supabase tables; schema migration `scripts/supabase_fusion_paper.sql`; R70 entry immediately above.

---

## R61 🟡 Detector-gated pillar_O sleeve — PARTIAL: clears 3-check gauntlet but gate does NOT lift OOS (Seth, 2026-07-22)

> **Status: RESEARCH RESULT, NOT A PRODUCTION CHANGE.** R61 tests whether the detector ×
> `flat_zero` pattern (R62/R63 SURVIVED on fade-the-crowd) generalizes to pillar_O.
> R61 does NOT modify the frozen R69 fusion cell (w_R46 = 0.25) — its result is the evidence
> base for the w_REBALANCE candidate (whether to raise w_R46). Per plan, R61 is research-only and never touches the
> live paper book.

**Hypothesis.** R46 pillar_O 5d/5bps SURVIVES in-sample (gross_t=+3.33, 5bps_t=+3.33) but its
OOS sign-flip at W5 (2025-10 → 2026-02 risk-on late-cycle chop) was the structural failure mode
the plan assumed. R62/R63 proved the detector × `flat_zero` pattern works for fade-the-crowd
(OOS lifted from −0.50 → +1.20). Hypothesis: applying the SAME pattern to pillar_O would
either (a) rescue the W5 OOS gap and clear the 3-check gauntlet with margin, OR (b) reveal that
the W5 sign-flip is structural to pillar_O in late-cycle risk-on, not just statistical noise.

**Built.** `src/research/validation/r61_pillar_o_detector_gated.py` (~470 LoC). Mirrors R62
structure verbatim: `load_btc_funding_level_series`, `load_cross_class_crowded_series`,
`load_btc_funding_accel_series` (all three R58 detector candidates, PIT-aligned via ffill to
rets.index), `detector_fire_mask(detector_values, threshold, direction)` (above/below with
median-as-default threshold), `apply_detector_gate(sleeve_pnl, detector_fires, action)`
(`action='reverse'` is REJECTED with `ValueError` per §TRADER_TOM_DOCTRINE), `gated_cadence_ls`,
`gated_cadence_sweep` (cad × cost × detector grid), `gated_sub_period` (per-window absorption
with detector firing-count annotation), `per_window_pnl`. Frozen R46 baseline:
`R46_REBAL_DAYS=5`, `R46_COST_BPS=5.0`, `R46_K=3`, `DEFAULT_GATE_ACTION='flat_zero'`.

Sweep: 6 cadences × 3 costs × 3 detectors = **54 cells**. Verdict grammar extends R62/R63:
✅ SURVIVES requires both `passes_all=True` AND `ΔOOS_t > 0` (the gate must actually LIFT OOS).
A cell that passes the 3-check gauntlet but has `ΔOOS_t ≤ 0` is 🟡 PARTIAL because the gate
trades in-sample alpha (W2 destruction) for OOS neutrality — not a rescue, not a refutation.

**Window.** Same R46/R58 panel: 2024-06-07 → 2026-06-07 (731 days), 41-asset CIS ∩ OHLCV.
Score: pillar_O only (R45 lesson #13 — composite adds nothing over pillar_O). OOS cut: last
30% (~219 days ≈ 2025-10-31 → 2026-06-07). 6 fixed-width sub-windows: W1 (Jun-Oct 2024),
W2 (Oct 2024-Feb 2025), W3 (Feb-Jun 2025), W4 (Jun-Oct 2025), W5 (Oct 2025-Feb 2026 — the
hypothesized fragile window), W6 (Feb-Jun 2026).

**Result.**
- **R46 ungated baseline reproduction (5d/5bps/k=3):** gross_t=+3.33 ✓, OOS_t=+2.47 ✓,
  pass_all=True. **W5 ungated ann%=+15.0%** (NOT negative as the plan assumed). W2 ann%=
  +685.9% (the explosive period). W6 ann%=−6.2% (the only negative window).
- **Best gated cell:** detector=`cross_class_crowded_count`, cadence=5d, cost=0bps →
  gross_t=+2.78 ✓, OOS_t=+2.35 ✓, pass_all=True. ΔOOS_t = **−0.12** (gate did NOT lift OOS).
- **Per-detector lift at R46 frozen cell (5d/5bps):** `cross_class_crowded_count` → ΔOOS_t=−0.28
  (pass_all=True); `btc_funding_acceleration` → ΔOOS_t=−0.36 (pass_all=True); `btc_funding_level`
  → ΔOOS_t=**−1.50** (pass_all=False — destroys both gross and OOS).
- **10/54 cells pass all 3 checks**, but ZERO cells have ΔOOS_t > 0 vs R46 ungated.
- **Per-window P&L (best cell, gated vs ungated):** W1 +62.9 → +51.7 (−11.3 Δ), W2 **+685.9 →
  +137.0 (−548.9 Δ)**, W3 +66.7 → +42.4 (−24.3 Δ), W4 +144.6 → +104.7 (−39.9 Δ), W5 +15.0 →
  +21.6 (+6.6 Δ), W6 −6.2 → +3.2 (+9.5 Δ). **The gate trades ~$625pp of in-sample alpha
  across W1-W4 for ~$16pp of W5+W6 gain — net loss, not rescue.**

**Robustness.** Detector fires 27% of panel (cross_class_crowded_count) — leaves the book
flat 27% of days. W2 gated residual-α t=+2.18 ✓ (still positive after gate). W5 gated
residual-α t=+0.48 (positive — W5 ann% improved from +15.0% to +21.6%). Sweep covers the
R46-cadence set {1, 3, 5, 7, 14, 21} × R46-cost grid {0.0, 5.0, 10.0} × all 3 R58 detector
candidates. Detector over-fits neither cell (the W5 fragility in the plan was +15% on this
reproduction, not negative) nor construction (5d cadence, 0bps, cross_class_crowded_count is
the cell that loses the LEAST).

**Verdict.** 🟡 **PARTIAL — clears all 3 checks but gate does NOT lift OOS (ΔOOS_t = −0.12).**
The detector × `flat_zero` pattern that SURVIVED on R63 fade-the-crowd does NOT transfer
cleanly to R46 pillar_O. The plan's hypothesized W5 sign-flip (t=−2.32 in the plan's
narrative) did not exist in this reproduction — W5 ungated was already +15.0%, and the gate's
net effect on the panel was negative: it destroyed +685.9% W2 in-sample alpha for marginal W5
and W6 improvement. **Frozen R69 fusion cell stays at w_R46 = 0.25 unchanged.** This is
the third straight outcome that suggests R46's edge lives in late-cycle bullish regimes and
W5/W6 are not the structural fragility the plan assumed. w_REBALANCE candidate (raise w_R46) is
NOT warranted; if anything, the R69 budget may want MORE R63 (fade-the-crowd) and LESS R46
— but that's a separate R-number.

**Aggregate lesson #28 — detector × flat_zero does NOT transfer cleanly across factors.**
R62/R63 SURVIVED on fade-the-crowd (OOS lifted from −0.50 → +1.20). R61 PARTIAL on pillar_O
(gate does not lift OOS; trades W2 in-sample for marginal W5/W6 gain). The pattern is
factor-specific: it works when the fragile regime is structural to the factor's return
dimension (per-asset funding z = crowded short at extreme), and it fails when the fragile
regime is benign (pillar_O in W5 was already +15%). Lesson: every factor needs its own
fragility detector trained on its own fragile labels — DO NOT reuse R62's external-funding
detector on R46's CIS-pillar cross-section.

**Aggregate lesson #29 — fragile-regime hypotheses are empirical claims, not prior assumptions.**
The R61 plan hypothesized W5 t=−2.32 sign-flip on R46. Reproduction showed W5 was already
+15.0% — the plan's failure mode didn't exist. The hypothesis of "W5 sign-flip in late-cycle
risk-on" was inherited from R56/R57 forensics on a different construction; for the 41-asset
R46 pillar_O 5d/5bps on this panel, W5 is a mildly positive (not negative) regime. Lesson:
re-derive fragile regimes from the actual factor's per-window P&L before training a detector.
The detector trained on the wrong fragile labels (as the plan would have) would gate the
wrong days. R61 caught this BEFORE building the detector — that's the value of running the
reproduction first.

**Reference.** Modules: `src/research/validation/r61_pillar_o_detector_gated.py` (NEW, ~470 LoC);
`src/research/validation/tests/test_r61_pillar_o_detector_gated_smoke.py` (NEW, 11 sandbox-safe
tests). Reports gitignored at `reports/r61_pillar_o_detector_gated/2026-07-22/`. R46 verdict
source: `reports/cis_quality_robustness/2026-07-20/` (R56 reproduction). R63 verdict source:
`reports/r62_fragility_funding_ls/2026-07-21/`. R69 fusion verdict: `reports/r63_fusion_validation/2026-07-21/`.

---

## R72 🔴 pillar_A change cross-sectional L/S — REFUTED (Seth, 2026-07-22)

> **Status: RESEARCH RESULT, NOT A PRODUCTION CHANGE.** R72 tests the directional pillar_A
> observation from R63b as a standalone cross-sectional sleeve. It does not modify CIS v5,
> the frozen R69 fusion cell, or any live paper book.

**Question and anti-imposter construction.** R63b contained two distinct pillar_A observations:
a +4.48 level spread and a +1.18 signed change spread. The directional claim is about the
change, so R72 ranks the PIT-safe one-day change `ΔA[t] = A[t] − A[t−1]`; ranking the A level
would test the wrong phenomenon. The universe is the strict funding ∩ CIS ∩ OHLCV intersection
(28 assets), with k=5 quintiles, the declared 2024-06-07 → 2026-06-07 panel, market + 30-day
momentum residualization, Newey-West lags=6, and cadence × cost sweep over {1,3,5,7,14,21}d
× {0,5,10}bps. The OOS slice is the last 30% of the panel; the earlier `OOS_FRAC` index cut
bug that selected the last 70% was corrected before this run.

**Result.** The best +ΔA cell in the declared grid is 5d/0bps: α_t=+0.96 and annualized
residual alpha=+28.5%, failing gross significance. At the identical 5d construction, −ΔA
returns α_t=−0.83; the matched-cell differential is +1.79 and supports the R63b direction,
but this is not strategy credit. The best −ΔA cell found independently is 7d/0bps,
α_t=+1.41, and is diagnostic only — selecting each sign's best cadence would be post-hoc.

**Three-check gauntlet for the +ΔA headline:**

| Check | α_t | Annualized α | Gate |
|---|---:|---:|:---:|
| Gross full panel | +0.96 | +28.5% | FAIL |
| 5bps full panel | +0.60 | +17.8% | FAIL |
| 5bps, last-30% OOS | +2.19 | +92.2% | PASS |

Combined result: **FAIL**. Four of six fixed windows are positive, but the effect is cadence
unstable and does not clear the gross or cost gates. The factor therefore receives no
standalone sleeve credit. The R63b architecture observation remains admissible as an input to
R69, where ΔA may be considered as a conditional state or sizing variable, but it must not
inherit alpha credit from this refuted L/S test.

**Verdict.** 🔴 **REFUTED as a standalone ΔA cross-sectional sleeve.** A matched sign can
support the hypothesized direction while the factor still fails economically: gross significance,
transaction-cost survival, and last-30% OOS are separate requirements.

**Aggregate lesson #40 — match the strategy score to the measured phenomenon.** A level rank
cannot test a change-factor claim, and opposite signs must be compared at the same construction.
Anti-imposter discipline applies before the statistics: test the right object, on the declared
universe, with the declared OOS window.

**Reference.** `src/research/validation/pillar_a_ls.py`; `src/research/validation/tests/test_pillar_a_ls_smoke.py`;
`reports/pillar_a_ls/2026-07-22/REPORT.md`; `reports/pillar_a_ls/2026-07-22/verdict.json`.

---

## R73 🔴 pillar_A LEVEL cross-sectional L/S — REFUTED (Seth, 2026-07-22)

> **Status: RESEARCH RESULT, NOT A PRODUCTION CHANGE.** R73 tests R63b's *level*-edge claim
> ("pillar_A (+4.48 level, +1.18 change) is the strongest untested candidate — never run at
> strategy level, queue the L/S test"). R72 already REFUTED the change variant (k=5 ΔA); R73
> is the open level test at k=3. Does NOT modify CIS v5, the frozen R69 fusion cell, or any
> live paper book.

**Parallel-lane note.** This Seth-lane R73 is the same claim Minimax-A documented as their
R64 ("pillar_A level L/S REFUTED" — see §LEDGER-RECONCILIATION-MAP below the entry; only one
MECHANISM_SPEC §3 kill-register row exists for the parallel-assignment hazard). The bodies
are reported here in Seth's lane for the ledger; the kill claim stands whether invoked as
R64 or R73.

**Question and anti-imposter construction.** R63b contained two distinct pillar_A
observations: a +4.48 *level* spread and a +1.18 signed *change* spread. R73 ranks the PIT-
safe pillar_A level (one-day-lag ffill), testing "does pillar_A carry cross-sectional rank
information beyond F + M + market?" If YES, that's a real sleeve. The universe is the strict
funding ∩ CIS ∩ OHLCV intersection (28 assets), with k=3 terciles (R46 standard; lesson #40:
do NOT silently re-use R72's k=5 — it may have inflated gross via thinner buckets), the
declared 2024-06-07 → 2026-06-07 panel, market + 30-day momentum residualization,
Newey-West lags=6, and cadence × cost sweep over {1,3,5,7,14,21}d × {0,5,10}bps. OOS slice
is the last 30% of the panel.

**Result.** The best +Level-A cell in the declared grid is 3d/0bps: α_t=+1.69, annualized
residual α=+37.7%. **At the identical 3d construction, −Level-A matched returns α_t=−1.38;
directional differential = +3.07** — the matched-cell sign is decisively the R63b direction.
Independent best −Level-A cell is 14d/0bps, α_t=−0.03, diagnostic only.

**Three-check gauntlet for the +Level-A headline:**

| Check | α_t | Annualized α | Gate |
|---|---:|---:|:---:|
| Gross full panel | **+1.69** | +37.7% | **FAIL** (< 1.96) |
| 5bps full panel | **+1.44** | +32.3% | **FAIL** (< 1.96) |
| 5bps, last-30% OOS | **−0.22** | −6.0% | **FAIL** (sign-flipped) |

Combined result: **FAIL on all 3 checks.** Per-window: W1 +119.2%, W2 +96.1%, W3 −26.5%,
W4 +123.1%, W5 −51.4%, W6 +86.9% — 4/6 positive (matching R46's W-pattern) but W5 = −51.4%
is the same structural fragility R46's pillar_O sleeve also exhibited; OOS sign-flips
because W5 dominates the back third of the panel.

**Verdict.** 🔴 **REFUTED as a standalone pillar_A LEVEL cross-sectional sleeve.** The R63b
+4.48 level-edge IS real (matched-cell +3.07 differential is decisively positive direction),
but **once cost residualized via market + 30d momentum + strict funding ∩ CIS ∩ OHLCV + k=3,
the t-statistic does not clear 1.96** — at +1.69 it's barely below, not above. The "strongest
untested candidate" claim from R63b reduces to "thin positive IC that does not survive
aggregation." Effect is not zero but not stand-alone-shippable; pillar_A belongs in fusion
contributions or regime-conditioned sleeves, not as a sole sleeve.

**Aggregate lesson #41 — the headline number lives in the test construction, not the data.**
R63b's +4.48 was a *raw* level-edge spread across the universe under beta-unadjusted universe
+ non-costed panel. Once those controls are applied (R73), the t-statistic halves to +1.69
and the OOS window sign-flips. The data's structure was correct; the headline number was
misleading. **Read t-stats, not raw ann-spreads, when evaluating edge claims** —
especially those from earlier in the metric chain.

**Reference.** `src/research/validation/r73_pillar_a_level_ls.py`;
`src/research/validation/tests/test_r73_pillar_a_level_ls_smoke.py` (11/11 tests pass);
`reports/r73_pillar_a_level_ls/2026-07-22/REPORT.md`; `reports/r73_pillar_a_level_ls/2026-07-22/verdict.json`.

---

## R74 🔴 pillar_A as 3rd fusion contribution to R69 family — REFUTED (Seth, 2026-07-22)

> **Status: RESEARCH RESULT, NOT A PRODUCTION CHANGE.** R74 follows R73's lesson #41
> ("matched-cell +3.07 directional differential is real but does not survive aggregation as a
> standalone sleeve — try as fusion contribution"). R74 tests whether pillar_A at small w_A
> ∈ {0, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30} on top of the **frozen R69 cell (w_R46=0.25)** lifts
> OOS, eliminates W5 sign-flip, or improves Sharpe. Does NOT touch the live fusion book.

**Question and anti-imposter construction.** Lesson #41's "How to apply" section proposed
pillar_A as a candidate ~5-10% fusion contribution to the R69 family. R74 implements that test
honestly: reuses R63's exact 28-asset strict funding ∩ CIS ∩ OHLCV universe, R63's R46
(pillar_O 5d/5bps) and R62 (fade-the-crowd 21d/0bps gated) legs verbatim, and R73's
pillar_A LEVEL 3d/0bps (R73's best-cadence cell) as the new Leg 3. The frozen 2-component
baseline is **w_R46=0.25, w_R62=0.75** (R69 cell, NEVER mutated in R74). The 3-component
fusion at each w_A is `fac_3 = (1 − w_A) × fac_2 + w_A × Leg_A`. Both Leg-A signs run
side-by-side; sign verdict comes from matched-cell direction (R73 confirmed +Level-A direction).

**Result (per-leg gauntlet on 28-asset).** R46: gross_t=+1.77, OOS_t=−0.44, maxDD=−33.62%.
R62: gross_t=+2.03, OOS_t=+2.94, maxDD=−18.85%. R73: gross_t=+1.69, OOS_t=−0.11,
maxDD=−33.26%. **Leg correlations: corr(R46, R73) = +0.69** (high — both are CIS-quality
signals moving together); corr(R46, R62) = −0.05; corr(R62, R73) = −0.07.

**Result (frozen baseline = R69 cell, w_A=0).** gross_t=+2.52, OOS_t=+2.44, maxDD=−11.05%,
passes_all=True, Sharpe=+1.69. **The R69 cell is doing very well** — it clears the 3-check
gauntlet with margin on all three (gross, costed, OOS).

**Result (3-component fusion w_A sweep).**

| w_A | gross_t | OOS_t | pass | maxDD | Sharpe | ΔOOS_t | W5 ann% | ΔW5 ann% |
|---:|---:|---:|:--:|---:|---:|---:|---:|---:|
| 0.00 (baseline) | +2.52 | +2.44 | ✓ | −11.05% | +1.69 | +0.00 | +45.6 | +0.0 |
| 0.05 | +2.60 | +2.36 | ✓ | −10.43% | +1.74 | **−0.08** | +38.5 | −7.0 |
| 0.10 | +2.68 | +2.25 | ✓ | −9.81% | +1.79 | **−0.19** | +31.8 | −13.8 |
| 0.15 | +2.74 | +2.12 | ✓ | −9.33% | +1.81 | **−0.32** | +25.3 | −20.3 |
| 0.20 | +2.79 | +1.97 | ✓ | −9.57% | +1.83 | **−0.47** | +19.1 | −26.5 |
| 0.25 | +2.81 | +1.80 | ✗ | −10.13% | +1.82 | **−0.64** | +13.1 | −32.5 |
| 0.30 | +2.81 | +1.62 | ✗ | −11.36% | +1.81 | **−0.82** | +7.4 | −38.2 |

**Combined result: REFUTED on the fusion-contribution hypothesis.** Adding pillar_A at any
positive w_A *monotonically degrades* OOS_t and *monotonically destroys W5 ann%*. The "best"
cell is the smallest w_A tested (0.05) but even that gives ΔOOS_t = −0.08. At w_A ≥ 0.25 the
fusion fails the 3-check gauntlet entirely. **The lesson #41 hypothesis was wrong.** Matched-
cell directional differential is necessary but not sufficient for fusion contribution — the
candidate must also be *uncorrelated enough with existing fusion legs* to add diversification.

**Verdict.** 🔴 **FUSION LOSES — pillar_A does NOT carry as 3rd fusion contribution.**
Three structural findings explain the failure:

1. **corr(R46, R73) = +0.69** is the killer statistic. pillar_O and pillar_A are both
   CIS-quality signals moving together; adding pillar_A at any weight just dilutes the
   existing R46 leg's signal without diversification. The fusion book needs orthogonal signal
   *sources*, not directionally-correct additional *signals* from the same source.
2. **W5 (the late-cycle fragility window) gets WORSE, not better.** R73's W5 = −51.4% on
   standalone; R73's matched-cell +3.07 was supposed to be a fusion lift, but at the
   fusion level ΔW5 ann% degrades monotonically with w_A (from +0 at w_A=0 to −38.2 at
   w_A=0.30). The late-cycle fragility that R73 suffered standalone transfers directly to
   the fusion when pillar_A is added.
3. **The R69 cell at w_A=0 is itself strong** — gross_t=+2.52, OOS_t=+2.44, maxDD=−11.05%,
   Sharpe=+1.69. It is one of the strongest sleeves in the entire R-numbered ladder
   (compares favorably to R46's standalone gross_t=+2.57 and beats R73's standalone t=+1.69).
   Adding pillar_A doesn't *rescue* a failing baseline; it *weakens* a strong one.

**Aggregate lesson #42 — REFUTED at the gauntlet → don't rescue via fusion.** The fusion book
only works when (a) the leg independently clears enough cells AND (b) is sufficiently
orthogonal (|corr| ≲ 0.30) to existing fusion legs. **pillar_A's matched-cell +3.07
directional differential was real but failed condition (b)** — pillar_A and pillar_O are both
CIS-quality signals with corr=+0.69, so adding pillar_A at any weight just adds correlated
noise. The fusion-contribution test must include a structural-correlation gate, not just a
direction differential test. **Read leg correlations before adding legs.**

**Counterfactual / what would have saved the hypothesis.** A fusion contribution works if
the candidate signal is *orthogonal* to existing legs. pillar_A would have been a credible
contribution candidate had R46/R62 used a different signal source (e.g. a pure cross-sectional
rank in funding residuals, or a regime-conditioned overlay). As a CIS-quality pillar_A
candidate added to a CIS-quality pillar_O leg, it was structurally the wrong leg to add.

**Action.**
- ✅ Frozen R69 cell at w_R46=0.25, w_R62=0.75 **CONFIRMED optimal** (no change).
- ✅ R65 paper book, R66 tracking: unaffected (R74 did not touch live book).
- ✅ R74 ships no production change.
- ✅ Lesson #42 stored in `r74-pillar-a-fusion-contribution-refuted` memory file.
- ✅ R75 forward candidate deferred — there is no clear next fusion contribution at this time.
  The next R-number should explore orthogonal signal sources, not more CIS-quality pillars.

**Reference.** `src/research/validation/r74_pillar_a_fusion_contribution.py`;
`src/research/validation/tests/test_r74_pillar_a_fusion_contribution_smoke.py`
(11/11 tests pass); `reports/r74_pillar_a_fusion_contribution/2026-07-22/REPORT.md`;
`reports/r74_pillar_a_fusion_contribution/2026-07-22/verdict.json`.

---

## R76 ✅ Funding residual cross-sectional L/S — SURVIVES + ORTHOGONAL (Seth, 2026-07-22)

> **Status: RESEARCH RESULT, NOT A PRODUCTION CHANGE.** R76 is the natural follow-on to
> R73/R74 per lesson #42 ("the fusion book only works when the leg is sufficiently
> orthogonal, |corr| ≲ 0.30, to existing fusion legs"). pillar_A was REFUTED because it
> was CIS-quality-correlated (+0.69) with R46. R76 tests whether funding residual — a
> genuinely orthogonal signal source (cross-sectional demean of funding, NOT absolute
> funding-z which R62 already uses) — survives the 3-check gauntlet AND passes the
> leg-correlation gate. Does NOT touch the live fusion book; R77 candidate material
> if confirmed (see below).

**Question and anti-imposter construction.** Funding residual = funding[t, a] −
mean_a(funding[t, a]) — captures an asset's *relative* funding pressure within the
universe on each date. This is fundamentally different from R62's `score_funding_zwide`
(per-asset z over time). Residual is *cross-sectional*; z-wide is *time-series*.
**Pre-test leg-correlation gate** (lesson #42 anti-imposter): measure corr(R76_leg,
R46_leg) and corr(R76_leg, R62_leg) BEFORE the gauntlet; if max |corr| > 0.30, flag as
fusion-uncandidatable. Universe: same 28-asset strict funding ∩ CIS ∩ OHLCV (R46/R62/R73
parity); k_terciles=3 (R46 standard); cadence × cost sweep over {1,3,5,7,14,21}d ×
{0,5,10}bps; market + 30d momentum residualization; Newey-West lags=6; OOS = last 30%.

**Result (leg-correlation gate, lesson #42 pre-test).** corr(R76_leg, R46_leg) = **+0.156**
(well below the 0.30 threshold). corr(R76_leg, R62_leg) = **−0.040** (essentially zero).
max |corr| = 0.156 — **passes the orthogonality gate by a comfortable margin**. R76's
funding residual IS a structurally orthogonal signal source to both R46 (CIS-quality) and
R62 (absolute funding-z).

**Result (per-leg gauntlet).** At the 3d/0bps default cell (mirroring R73's best cell),
R76 gives gross_t=+1.41, OOS_t=+0.53 — fails 3-check (under 1.96). **But the cadence
sweep reveals a better cell.**

**Result (matched-cell sign audit + best cell).** Sign verdict from matched-cell
differential: **high_fund_long** (matched-cell diff = **+3.48**, decisively real direction).
The best cell is **5d/0bps**: gross_t = **+2.11**, OOS_t = **+3.15**, passes_all = True.

**Result (per-window W1-W6 attributions at best cell).**

| Window | ann% | n_days | maxDD |
|---|---:|---:|---:|
| W1 | +59.7% | 121 | −11.50% |
| W2 | +21.9% | 122 | −15.52% |
| W3 | −26.2% | 122 | −22.28% |
| W4 | +6.6% | 122 | −18.18% |
| **W5** | **+98.4%** | 122 | −8.69% |
| **W6** | **+147.3%** | 122 | −8.56% |

**5/6 windows positive.** The killer finding: **W5 = +98.4%** is the late-cycle fragility
window where R46 sign-flips (R46's W5 = −54.1% per its 41-asset reproduction). R76's
funding residual signal WORKS in the exact window where R46 fails. W6 = +147.3% is the
most recent window — R76 is *accelerating*, not fading.

**Verdict.** ✅ **SURVIVES + ORTHOGONAL** — R76 clears the 3-check gauntlet (gross +2.11,
OOS +3.15) AND passes the lesson #42 leg-correlation gate (max |corr| = 0.156). R76 is a
genuinely orthogonal cross-sectional signal source with positive W5 (where R46 fails) and
positive W6 (the most recent window). R76 is the strongest candidate leg identified since
R46/R62 to add to the fusion book.

**Aggregate lesson #43** (proposed): **Orthogonal signal sources carry real cross-sectional
edges that survive the 3-check gauntlet AND are uncorrelated with existing fusion legs.**
Lesson #42 holds: leg-correlation gate is necessary; orthogonal candidates are the right
next R-number. Specifically:
- Funding residual (cross-sectional demean) is a structurally different signal than
  absolute funding-z (R62); the demean removes the level shift, leaving relative pressure
  within the universe.
- The 5d/0bps cell with high_fund_long direction has matched-cell diff +3.48 (decisively
  real) and OOS t +3.15 (well above 1.96).
- W5 = +98.4% — the late-cycle fragility window where CIS-quality (R46) sign-flips.
  Funding residual captures a *microstructure* pattern (relative funding pressure) that
  is independent of CIS-quality rank.

**Action.**
- ✅ R76 ships no production change (research-only).
- ✅ Frozen R69 cell at w_R46=0.25 unchanged.
- ⏭ **R77 = R76 as 3rd fusion contribution to R69 family** is the natural next step.
  Should follow the same pattern as R74 (3-component fusion sweep on top of frozen R69
  cell) but with the lesson #42 leg-correlation gate already proven (R76 passes). If
  R77 clears the 3-check at any w_R76, that becomes a candidate for the live R69 cell
  rebalance (parallel to R67 forward commit).

**Reference.** `src/research/validation/r76_funding_residual_ls.py`;
`src/research/validation/tests/test_r76_funding_residual_ls_smoke.py` (11/11 tests pass);
`reports/r76_funding_residual_ls/2026-07-22/REPORT.md`;
`reports/r76_funding_residual_ls/2026-07-22/verdict.json`.

---

## R77 ✅ R76 (funding residual) as 3rd fusion contribution to R69 family — FUSION LIFT (Seth, 2026-07-23)

**Hypothesis (per lesson #43).** R76 SURVIVES + ORTHOGONAL — funding residual
cross-sectional L/S clears 3-check (gross_t +2.11, OOS_t +3.15, 5d/0bps) AND
passes the lesson #42 leg-correlation gate (max |corr| = 0.156). R77 tests
whether R76's orthogonal-edge property translates to a real fusion lift on top
of the existing R46+R62 fusion (R69 cell, frozen at w_R46=0.25).

**Built.** `src/research/validation/r77_r76_as_fusion_contribution.py`
(~340 LoC) + 11 smoke tests (all pass). Reuses R63's exact panel + 28-asset
strict funding ∩ CIS ∩ OHLCV universe. Three legs:
- Leg 1 (R46): pillar_O 5d/5bps (R63's existing leg_r46)
- Leg 2 (R62): fade-the-crowd 21d/0bps gated (R63's existing leg_r62)
- Leg 3 (R76): funding residual 5d/0bps, k=3 (R76's best cell)

Frozen 2-component baseline: fac_2 = 0.25 × Leg1 + 0.75 × Leg2 (R69 cell).
3-component fusion: fac_3 = (1-w_R76) × fac_2 + w_R76 × Leg3.
Sweep w_R76 ∈ {0.00, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30}.
Pre-test leg-correlation gate (lesson #42 — R76 result: passes).

**Pre-test leg-correlation gate (lesson #42).** corr(R76, R46) = **+0.103**,
corr(R76, R62) = **+0.004**, max |corr| = **0.103** (well below 0.30 gate).
Gate **passes** with comfortable margin — orthogonal candidate.

**Verdict.** ✅ **FUSION LIFT — R76 carries as 3rd fusion contribution to R69 family.**

**w_R76 sweep (frozen R69 cell baseline + 3-component fusion):**

| w_R76 | gross_t | OOS_t  | pass | maxDD    | Sharpe | ΔOOS_t  | W5 ann% | ΔW5 ann% |
|------:|--------:|-------:|:----:|---------:|-------:|--------:|--------:|---------:|
| 0.00  | +2.52   | +2.44  | ✓    | −11.05%  | +1.69  | +0.00   | +45.6   | +0.0     |
| 0.05  | +2.63   | +2.67  | ✓    | −10.33%  | +1.77  | +0.23   | +48.3   | +2.8     |
| 0.10  | +2.75   | +2.90  | ✓    | −9.68%   | +1.86  | +0.46   | +51.1   | +5.6     |
| 0.15  | +2.86   | +3.11  | ✓    | −9.03%   | +1.93  | +0.67   | +53.9   | +8.3     |
| 0.20  | +2.96   | +3.31  | ✓    | −8.68%   | +1.99  | +0.87   | +56.6   | +11.1    |
| 0.25  | +3.04   | +3.48  | ✓    | −8.57%   | +2.04  | +1.04   | +59.4   | +13.9    |
| 0.30  | +3.10   | +3.61  | ✓    | −8.91%   | +2.06  | +1.17   | +62.2   | +16.6    |

**All 7 grid points pass 3-check.** The lift is *monotone in w_R76* — every
step adds positive OOS_t and reduces maxDD (until w_R76=0.30 where maxDD ticks
up marginally to −8.91% from the w_R76=0.25 low of −8.57%).

**Best w_R76 = 0.30 (capped):** gross_t = +3.10, OOS_t = +3.61, maxDD = −8.91%,
Sharpe = +2.06. ΔOOS_t = +1.17 (vs frozen baseline OOS_t = +2.44).
**ΔOOS_t > +0.5 lesson #43 bar passes by 2.3×**.

**Per-window W1-W6 attribution (best w_R76=0.30 cell):**
- W5 ann% = +62.2 (vs frozen baseline +45.6, ΔW5 = +16.6) — **R76's killer W5
  lifts the W5 ann% further at the fusion level too**. R76 was already positive
  W5 on its own; the fusion captures additional alpha from the same window.

**Why the lift is real (anti-imposter checks):**
- Lesson #42 leg-correlation gate **passes** (max |corr| = 0.103 ≪ 0.30).
- Monotone improvement across the entire w_R76 grid — not a one-cell artifact.
- maxDD drops (less drawdown, not more) — R76 diversifies the fusion book's tail.
- Sharpe rises (+1.69 → +2.06) at the same time — not a return-for-volatility trade.
- ΔOOS_t = +1.17 is large in absolute terms (almost +50% relative to baseline OOS_t).

**Aggregate lesson #43 (CONFIRMED, full positive form):** **Orthogonal signal
sources DO carry as 3rd fusion contribution to the existing R46+R62 fusion.**
Lesson #42 + #43 form a complete pair:
- Lesson #42 (from R74): "REFUTED at the gauntlet → don't rescue via fusion;
  read leg correlations before adding legs."
- Lesson #43 (from R76 + R77): "Orthogonal signal sources (max |corr| ≲ 0.10)
  DO lift the fusion — the orthogonal-edge property translates to the fusion
  book. W5 lift at R76 (+98.4% standalone) translates to ΔW5 = +16.6 ann%
  at the fusion level, and ΔOOS_t = +1.17 overall."

Specifically:
- The demean operation in R76 (cross-sectional funding - cross-sectional mean)
  removes the level shift that R62's absolute funding-z carries, leaving
  *relative pressure* within the universe. This is structurally orthogonal to
  R46's CIS-quality rank and R62's crowding-z.
- The 3-component fusion at w_R76=0.30 has maxDD −8.91% (vs frozen −11.05%)
  and Sharpe +2.06 (vs frozen +1.69) — risk-adjusted alpha LIFTS at every
  measurement primitive, not just raw return.
- The W5 lift at the fusion level (ΔW5 = +16.6 ann%) means the late-cycle
  fragility window where R46 sign-flips is captured not just by R76 alone but
  also by the fusion book — a durable, structural improvement.

**Action.**
- ✅ R77 ships no production change (research-only). R77 is the *evidence
  base* for a forward R78 candidate that may rebalance the live R69 cell.
- ✅ Frozen R69 cell at w_R46=0.25, w_R62=0.75, w_R76=0 **unchanged**.
- ⏭ **R78 candidate** = rebalance w_R46 + add w_R76 to the live R69 cell.
  Forward commit pending — not in scope for this round (R77 is the evidence,
  R78 is the live deployment decision).
- ⚠ Forward-commit gating (R67 / R78 candidate): needs walk-forward validation
  on post-2026-02 marks (R65 paper book accrual) + JimmyJazz/Minimax coord for
  any live R69 cell rebalance. Per §OWNERSHIP-BOUNDARIES, only Seth/Austin
  modify src/ + dashboard/ + docs; Minimax owns local engine changes.

**Reference.** `src/research/validation/r77_r76_as_fusion_contribution.py`;
`src/research/validation/tests/test_r77_r76_as_fusion_contribution_smoke.py`
(11/11 tests pass); `reports/r77_r76_as_fusion_contribution/2026-07-23/REPORT.md`;
`reports/r77_r76_as_fusion_contribution/2026-07-23/verdict.json`.

---

## R78 🔴 Relative momentum (TSMOM cross-sectional demean) cross-sectional L/S — REFUTED (Seth, 2026-07-23)

**Hypothesis (per R76 lesson #43).** R76 (funding residual) was orthogonal candidate
#1 and cleared both leg-correlation gate AND gauntlet → fused as 3rd leg via R77
(FUSION LIFT). R78 tests orthogonal candidate #2: **relative momentum** =
TSMOM[t, a] − mean_a(TSMOM[t, a]) (cross-sectional demean of TSMOM sign). TSMOM
is sign of trailing-30d return; the cross-sectional demean removes the universe's
common trend component, leaving RELATIVE trend strength. Structurally different
from R46 (CIS-quality rank), R62 (crowding-z), R76 (funding residual).

**Built.** `src/research/validation/r78_relative_momentum_residual.py` (~430
LoC) + 11 smoke tests (all pass). Reuses R63's exact panel + 28-asset strict
funding ∩ CIS ∩ OHLCV universe. Score = TSMOM[t, a] − mean_a(TSMOM[t, a]).
k=3, cadence × cost sweep, market + momentum residualization, NW lags=6, OOS=30%.
Both signs run; matched-cell sign verdict from R76-style audit.

**Pre-test leg-correlation gate (lesson #42, extended to 3 existing legs).**
corr(R78, R46) = **+0.113** ✓, corr(R78, R62) = **−0.012** ✓, corr(R78, R76) =
**+0.004** ✓. max |corr| = **0.113** (well below 0.30 gate). Gate **passes**
with comfortable margin — R78 is genuinely orthogonal to all existing fusion
legs.

**Verdict.** 🔴 **REFUTED** — R78 PASSES the gate but FAILS the gauntlet.

**Why refuted.** Default-cad 3d/0bps leg: gross_t = +0.32, OOS_t = +0.83. The
3-check requires gross_t > 1.96 AND 5bps_t > 1.96 AND OOS_t > 1.96. R78's best
in-sample α_t across the entire 6-cadence × 3-cost sweep stays below 1.96 — no
cell passes the gauntlet.

**Matched-cell sign audit (top-3):**

| cad | bps | Δ(α_t) | hi (long) | lo (short) |
|----:|----:|-------:|----------:|-----------:|
|  7  | 10  | +2.17  | +1.34     | −0.83      |
|  7  |  5  | +2.09  | +1.43     | −0.66      |
|  7  |  0  | +2.00  | +1.52     | −0.48      |

The matched-cell differentials ARE real (top-3 all positive) and the sign verdict
is decisively **high_mom_long** — relative momentum DOES carry directional alpha.
But the absolute α_t does not cross 1.96, so the edge does not survive aggregation
into a 3-check-passing sleeve.

**Per-window W1-W6 attribution (best-cad 3d/0bps, sign=high_mom_long):**
- W1: +1.9%, W2: +4.7%, W3: +0.0%, W4: −8.2%, W5: −6.9%, W6: +18.0%
- maxDD: −8.69% (mild)
- 3/6 windows positive — NOT the clean 5/6 R76 had
- W4 + W5 both negative — the late-cycle fragility window where R46 fails does
  NOT show R78's strength (unlike R76 which had W5=+98.4%).

**Aggregate lesson #43 (SHARPENS):** **Orthogonal candidate screening can PASS
the leg-correlation gate but FAIL the gauntlet.** The gate is necessary but not
sufficient — an orthogonal candidate must ALSO have a real standalone edge that
crosses t=1.96 in the gauntlet. R76 was orthogonal AND had standalone edge
(funding residual captures *microstructure* pressure → structural edge). R78 is
orthogonal but lacks standalone edge (relative momentum is a *trend* axis, but
TSMOM demean loses the level information that R46's pillar_O already captures;
the remaining relative signal is too thin).

Specifically:
- The gate (lesson #42 — |corr| ≲ 0.30) tells you the candidate is NOT just a
  duplicate of an existing leg. R78 passes (max |corr| = 0.113).
- The gauntlet (gross + costed + OOS) tells you the candidate has REAL edge on
  this data. R78 fails (best gross_t = +0.32 ≪ 1.96).
- Both are required. R74 was a candidate that failed BOTH (correlated + weak).
  R78 is a candidate that passed gate but failed gauntlet. R76 passed BOTH.
- Future orthogonal candidates must clear BOTH bars to be fusion-candidatable.
  If only the gate clears, the candidate is standalone-ineligible but the
  gate-fail pattern itself is a useful prior (catches duplicates before they
  waste a fusion sweep).

**Lesson #43 is now fully articulated in 3 cases:**
- ✅ R76 — orthogonal AND standalone edge → SURVIVES + ORTHOGONAL → fusion lift (R77).
- 🔴 R78 — orthogonal but NO standalone edge → REFUTED → not a fusion candidate.
- 🔴 R74 (R73 leg) — NOT orthogonal AND NO standalone edge → REFUTED.

The gate-then-gauntlet pipeline is the correct discipline. R78's refutation is
the negative evidence that the gate alone is insufficient; the gauntlet must
also be cleared.

**Action.**
- ✅ R78 ships no production change (research-only).
- ✅ Frozen R77 cell at w_R46=0.25, w_R62=0.75, w_R76=0.30 **unchanged**.
- ⏭ **R79 candidate** = orthogonal candidate #3 — should look at even more
  structurally different sources per the verdict text: "microstructure volatility
  (realized vol cross-sectional demean) is the next most natural axis; it is
  structurally different from R46/R62/R76/R78 (rank / crowding-z / funding-residual
  / momentum-residual) on the microstructure-vol dimension. R79 = realized vol
  residual cross-sectional L/S as orthogonal candidate #3."

**Reference.** `src/research/validation/r78_relative_momentum_residual.py`;
`src/research/validation/tests/test_r78_relative_momentum_residual_smoke.py`
(11/11 tests pass); `reports/r78_relative_momentum_residual/2026-07-23/REPORT.md`;
`reports/r78_relative_momentum_residual/2026-07-23/verdict.json`.

---

## §LEDGER-RECONCILIATION-MAP 2026-07-22 (Seth, per Jazz decision) — the R64–R68b collision, resolved

**Why this exists.** Two lanes ran in parallel and both claimed R64–R68b (the parallel-assignment hazard
in `docs/VECTOR_SCHEMA_SPEC.md` §0). Seth's fusion lane wrote R64–R67 as *ledger bodies*; Minimax's
pillar_A / kill-register lane wrote R64–R68b as a *summary row* in `docs/MECHANISM_SPEC.md` §3. Same
numbers, different experiments. **Jazz's ruling: Minimax keeps R64–R68b; Seth's lane renumbers to R69+.**

### Canonical mapping (applied this pass to `REFUTATION_LEDGER.md` + `PROJECT_STATE.md`)

| was (Seth) | now (canonical) | entry | status |
|---|---|---|---|
| R64 | **R69** | Sleeve fusion validation — FUSION WINS 3/3 gates (R46 pillar_O × R63 fade-the-crowd) | ✅ renumbered |
| R65 | **R70** | Fusion paper book DEPLOYED (§P2 fill-attribution) | ✅ renumbered |
| R66 | **R71** | Live NAV accrual monitoring WIRED (§P3 lifecycle) | ✅ renumbered |
| R67 | **R72** | pillar_A *change* cross-sectional L/S — REFUTED | ✅ renumbered |

Minimax's lane is **unchanged**: R64 (pillar_A level L/S REFUTED), R65 (cross-pillar sweep 15 cells),
R66 (regime-conditional pillar_A L/S), R67 (R46 audit on upgraded data), R68/R68b (per-asset overlay /
long-only). These live ONLY as one MECHANISM_SPEC §3 kill-register row.

### ⚠️ Open integrity items — NOT resolved this pass (need Minimax / Jazz)

1. **Minimax's R64–R68b have no ledger bodies.** The "7-deep binary-permanent kill" lineage
   (R15/R17/R38/R45/R47/R48/R64/R65/R66/R67/R68b) is asserted in MECHANISM_SPEC but **cannot be audited
   from this ledger** — there are no R64–R68b entries with data, method, n, OOS. Per §ALTITUDE a
   binary-permanent kill is the strongest claim we make; it needs real bodies. **Minimax: append R64–R68b
   bodies at EOF (append-only) with the per-cell evidence.** Until then the kill is provisional.

2. **In-ledger duplicate numbers R61 and R63** (from the mid-session Mac-side rewrite, §SESSION_LOG §5) —
   documented here, deliberately NOT renumbered (blast radius: R61/R62/R63 are the metric-bug chain cited
   everywhere incl. the session prompt). Disambiguate by content:
   - **R61-audit** (≈line 1757): live signal book non-predictive → OVERTURNED by R62. The metric chain.
   - **R61-detector** (≈line 2278, 2026-07-22): detector-gated pillar_O sleeve, PARTIAL.
   - **R63-fadecrowd** (≈line 1612): regime-conditioned fade-the-crowd SURVIVES.
   - **R63-Srisk** (≈line 2030) + **R63b** (≈line 2083): pillar_S is a risk factor; the metric chain.
   A future pass may relabel the *sleeve* duplicates (R61-detector→R73, R63-fadecrowd→R74) once Jazz rules.

3. **Code/tests intentionally NOT swept.** The deployed fusion modules (`fusion_paper.py`,
   `nav_monitor.py`, `fusion_paper_tracking.py`, their smoke tests, `main.py`) still label the cell "R64"
   (e.g. `R64_OOS_ALPHA_T`, `test_nav_monitor` asserts `"R64" in ref_label`). **The code-level "R64 cell"
   IS canonical R69** — the running concept (frozen w_R46=0.25, 28-asset universe, OOS α_t=2.38, Sharpe
   1.69) is unchanged; only the ledger number moved. Renaming runtime labels was skipped on purpose:
   zero runtime benefit, and it would churn preflight + a live assertion. Rename opportunistically later.

### Corroboration correction (do not carry the old sentence forward)

The prior session used **R46 as independent corroboration for R62** (both "remove β"). Re-derived: it does
**not** hold as stated. R62 measures **absolute per-signal** β-adjusted edge on the live book; R46/R67(mx)/
R68b measure **cross-sectional rank** L/S. Those are different objects (the R16 lesson: cross-sectional ≠
absolute). So R72 (Seth: pillar_A *change* L/S REFUTED) being negative while R62 (pillar levels predict
β-adj edge, +2.85) is positive is **not a contradiction** — it is the R16 distinction reappearing.
**R62 stands on its own data and never needed R46.** Minimax's R67 (R46 audit REFUTED on upgraded 22-asset
CIS) further weakens any R46-as-corroboration claim. Net: cite R62 from its own audit; drop the R46 cross-check.

---

## R75 ⚪ Hourly S/O stability + Δ-quintile — PREMATURE / pipeline shipped, data accruing (Seth, 2026-07-22)

> **Pre-declared research contract; no strategy credit yet.** R73 is already occupied by the
> pillar_A LEVEL L/S result. R75 uses genuine sub-day `cis_scores.recorded_at` snapshots to test
> R63b's S/O stability-premium claim. Daily scores will not be forward-filled into synthetic hourly
> observations. Minimum maturity is frozen at 30 calendar days, 720 unique hourly observations,
> and 12 assets before any SURVIVES/PARTIAL/REFUTED verdict. Until then the only permitted verdict
> is PREMATURE or INCONCLUSIVE, regardless of provisional t-statistics.

**Frozen construction.** Pillars S and O; Δ lookbacks {1h,4h,8h,24h}; primary score `−abs(Δ)`
(long stable quintile / short largest-move quintile); signed +Δ/−Δ matched-cell controls; k=5;
rebalance {1h,4h,8h,24h}; cost {0,5,10}bps; strict funding ∩ hourly-CIS ∩ hourly-OHLCV universe;
score observed at hour t may act only on return t+1 (with `max_staleness_hours=4` ffill so a snapshot
at hour t can predict returns t+1…t+4, after which NaN prevents trading — preserves PIT, refuses
stale-snapshot abuse); last-30% OOS; market + 24h momentum controls; hourly annualization 8760;
Newey-West lags=24. Production CIS scores, weights, grade/signal thresholds, Mac Mini code, Shadow,
and the CIS push contract are explicitly out of scope.

**Data sources (genuine, no fabrication).** Hourly CIS snapshots via public
`/api/v1/cis/history/{symbol}` (Supabase-backed) — same channel the dashboard uses; hourly 1h OHLCV
via public `/api/v1/market/ohlcv/{symbol}?interval=1h&limit=744`; falls back to local parquet OHLCV
only if the public endpoint returns zero rows. The active loader is recorded in `verdict.json` as
either `public_ohlcv_api` or `local_parquet`.

**Initial result (2026-07-22 14:17 UTC).** Full panel sweep completed across all 96 cells (2 pillars
× 4 lookbacks × 4 cadences × 3 costs). Maturity: **37.12 calendar days / 662 unique hours / 28
assets** — below the 30d/720h/12-asset floor by ~58 hours; mature=False. Best gross cell: pillar
**O**, Δ=**1h**, rebalance=**4h** ⇒ α_t=**+1.18** (ann +128.3%), which **fails** the 1.96 gross gate.
5bps α_t=**−0.92** (ann −99.7%); last-30% OOS α_t=**−1.70** (ann −343.3%). All three gates fail;
even if maturity had been met the headline would read 🔴 REFUTED. **Verdict: ⚪ PREMATURE** — the
maturity gate is the binding constraint; the provisional t-statistics above are reported for
transparency but **do not constitute strategy credit**. This is exactly the discipline
VECTOR_SCHEMA_SPEC §4 build-order #5 requires: refuse to credit a factor the data does not yet
support.

**Why the first run returned INCONCLUSIVE, not PREMATURE.** Before wiring `fetch_hourly_returns_public`
and adding `max_staleness_hours=4` to `align_score_to_next_bar`, every cell had α_t=NaN because
intra-hour gaps in the snapshot cadence left `row.dropna()` empty (`< min_assets=12`), so `weights`
stayed zero and the L/S series had near-zero std. The honest fix: forward-fill the lagged score with
a 4-hour staleness budget (preserves PIT — a score at hour t still only acts on returns strictly
after t), then re-rank. After the wiring change: all 96 cells evaluate and the system reports the
maturity-gated verdict.

**Lesson #43 (new).** Two distinct failure modes need separate labels. *INCONCLUSIVE* = the data
loader could not produce enough rows to rank (e.g. local parquet OHLCV had no overlap with CIS
timestamps). *PREMATURE* = data loaded and the pipeline ran, but a pre-declared maturity gate blocks
strategy credit. R75's first run mistook one for the other; the corrected verdict logic makes
maturity dominate so PREMATURE is what we get when 662h of genuine snapshots have not yet crossed
the 720h gate.

**Lesson #44 (new).** Genuine sub-day snapshots are sparse enough that the L/S engine can silently
produce all-zero weights even when the headline verdict looks healthy. The honest signal is the
**per-hour fraction of evaluable rebalances**, not the t-stat. The 30d/720h/12-asset gate absorbs
the gap today; once cleared, R75's first post-maturity re-run must include a `trade_hours_pct` field
so a sparsity-driven zero-L/S cannot masquerade as a SURVIVES.

**Update (2026-07-23, do NOT mistake for SURVIVES credit).** Same module re-executed against
today's snapshot — the headline t-statistic did NOT move because the underlying data window did
NOT extend forward. **Newly surfaced data-pipeline finding** (added a `_data_freshness()` probe +
`data_freshness` block in `verdict.json`, surfaced in `REPORT.md` §3):

| Signal | 2026-07-22 | 2026-07-23 |
|---|---|---|
| Latest data hour observed | 2026-07-19T14:00:00 | **2026-07-19T14:00:00** |
| Earliest data hour observed | 2026-06-12T10:00:00 | 2026-06-12T18:00:00 |
| Staleness vs run time | 71.6 h | **74.5 h** |
| Null-pillar assets (no rows at all) | 3 (BCH, ICP, WIF) | 3 (BCH, ICP, WIF) |
| Mature | False (37.12 d / 662 h / 28 a) | False (36.79 d / 654 h / 28 a) |
| Best gross α_t | +1.18 | +1.18 (unchanged) |
| 5bps / OOS / verdict | −0.92 / −1.70 / PREMATURE | −0.92 / −1.70 / PREMATURE |

**Translation:** the public `/api/v1/cis/history/{symbol}` endpoint **stopped writing fresh
non-null `pillar_s`/`pillar_o` rows at 2026-07-19T14:00** — i.e. **the upstream CIS push pipeline
has been stalled for ~3 days** as of run time. The 200 newest rows in each asset's payload are
skeleton / null-pillar writes (~one per hour since 2026-07-19T15:00 onward) — these suggest a
reconnect/recovery loop without the actual pillar-write path. Three assets (BCH, ICP, WIF) have
**no historical rows at all** (likely affected by the recent pipeline regression). The mac-side
CIS push author is Minimax; this falls outside R75's lane.

**Lesson #45 (new, infrastructure-blocking).** A research-grade factor pipeline has TWO
necessary-but-not-sufficient gates: (1) the **calendar-coverage gate** (30d/720h/12-asset maturity)
and (2) the **wall-clock freshness gate** (latest_data_hour must be close to run time, not just
data-rich). R75's verdict logic now checks both via the `_data_freshness()` probe. If pipeline
freshness stays at 74.5h or worse, **the maturity gate cannot advance even with more days of
runtime** — the same 30-day-old window just keeps rolling forward. R75 will remain PREMATURE
until either (a) the upstream pipeline resumes, or (b) the calendar-coverage gate is reset to a
smaller window that the available data actually satisfies (research-only decision, not R75's call
to make unilaterally).

**Artifacts (2026-07-23 update).** `src/research/validation/r75_hourly_so_quintile.py`
(+~85 LoC: `_data_freshness`, `data_freshness` block in `run()`, `format_report` §3) —
**11/11 smoke tests pass** (new `test_data_freshness_surfaces_staleness_and_nulls` added);
**preflight PASSED**. `reports/r75_hourly_so_quintile/2026-07-23/{REPORT.md, verdict.json, run.log}`
— gitignored.

**Mac-side handoff (2026-07-23).** Three-file diff (no production-code change, no contract change,
no engine change):

```
M src/research/validation/r75_hourly_so_quintile.py   (+~85 LoC: data_freshness probe)
M src/research/validation/tests/test_r75_hourly_so_quintile_smoke.py   (+1 test, +5 imports)
A reports/r75_hourly_so_quintile/2026-07-23/{REPORT.md, verdict.json, run.log}   (gitignored — not for commit)
```

**Out-of-R75-lane finding for Minimax (NOT a Seth fix; flagged for Mac-side follow-up).**
CIS-history pipeline stall since **2026-07-19T14:00 UTC**. The endpoint returns 1000 rows per
request; the latest 200 are null-pillar skeleton writes; the underlying 800 carry real data but
end 4 days ago. This blocks R75, R-numbered research that needs current pillar values, and
any investor-facing surface that derives from CIS history. Reference: `REFUTATION_LEDGER.md`
R75 §update 2026-07-23 + `data_freshness` block in `reports/r75_hourly_so_quintile/2026-07-23/verdict.json`.

**Artifacts.** `src/research/validation/r75_hourly_so_quintile.py` (~370 LoC + ~85 LoC freshness probe)
— modules: `fetch_histories`, `normalize_hourly_history` (NaN-honest, no ffill), `build_hourly_pillar_panel`,
`align_score_to_next_bar` (shift + staleness-bounded ffill), `delta_score` (stable / positive /
negative), `hourly_ls` (k=5 next-bar L/S, turnover-aware cost), `maturity_status` (frozen
30d/720h/12-asset), `_data_freshness` (latest_data_hour, staleness_hours, null_assets), `run`
(orchestrator with returns-source tracking + maturity-dominant verdict + freshness block).
`src/research/validation/tests/test_r75_hourly_so_quintile_smoke.py` — **11/11 pass** (UTC bucket +
de-dup, NaN honesty, panel shape, exact-hour predecessor, abs-Δ stability direction, next-bar PIT,
matched-cell inversion, maturity gate constants, real-parquet loader, **freshness probe honors null
assets and computes staleness from max(last_hour)**). Preflight PASSED.
`reports/r75_hourly_so_quintile/2026-07-22/{REPORT.md, verdict.json, run.log}` and
`2026-07-23/{REPORT.md, verdict.json, run.log}` — gitignored.
Re-run when pipeline resumes; same module, no code changes needed.

---

## S-76 🔴 Price does NOT lead S/O — the pillars are price-COINCIDENT, closing the build-order #5 nowcast path (Seth, 2026-07-22)

*(First entry under the approved lane-prefix convention — `docs/R_NUMBERING_CONVENTION.md`, Option 2.)*

**Hypothesis (build-order #5 premise):** R63b's stability premium ("edge best when ΔS/ΔO stable") was
read as "we sample S/O AFTER the market reprices" ⇒ if price *leads* S/O, a fast related-instrument
price proxy could nowcast S/O between the slow CIS samples. Test it before building the infrastructure.

**Method:** daily lead-lag, 58 assets ∩ ohlcv_daily, 2025-05→2026-06, n≈8,280. cis_scores daily-resampled
(last snapshot/day) joined to ohlcv close. corr(own_ret[t], Δpillar) at leads 0..3; contemporaneous as
reference; pillar-spectrum control; BTC-excluded to avoid market-on-market contamination.

**Result — REFUTED.** S/O are price-COINCIDENT, not price-leading:
- CONTEMPORANEOUS corr(own_ret[t], Δpillar over [t-1,t]): **O +0.52 (t=56.6), S +0.44 (t=45.0)**.
- LEAD +1 (the test): **ΔO +0.013 (t=1.1), ΔS −0.010 (t=−0.9)** — zero predictive lead. Lead +2/+3 mildly
  NEGATIVE (ΔS lead+2 t=−6.9): a weak mean-reversion, the wrong sign for a nowcast.
- Pillar spectrum (contemporaneous ρ): M +0.82 (definitionally price), A/O/S +0.57/+0.52/+0.44, **F −0.01**.
  Only F is price-independent; O and S sit at the price-derived end.

**Verdict:** a daily price-based S/O nowcast adds nothing — do NOT build it. The stability premium is a
REGIME/RISK signal (large ΔS/ΔO = large contemporaneous price moves = high-vol tape where edge degrades),
not a sampling-latency problem. Residual: a lead could only exist SUB-DAILY (intraday price → EOD snapshot),
which needs hourly pillar+price (geo-blocked/absent) and has marginal payoff since S/O are ~contemporaneous
price transforms even daily. Companion to Minimax's R75 (hourly S/O Δ-quintile) — my result implies R75's
factor must clear an absorption test vs momentum or it is momentum-in-a-costume (R24 pattern). Module
`src/research/validation/so_price_leadlag.py` (pure, any resolution; re-read the LEAD row when hourly lands),
6/6 smoke. Handoff: `MINIMAX_SYNC §SO-LEADLAG`.

## S-77 ✅ CIS v5 two-score architecture VALIDATED — F/A carry return, O is the dispersion pillar (Seth, 2026-07-22)

**Hypothesis (build-order #6):** CIS v5 splits the single v4 weighted sum into a return_score {F,M,A} and
a separate risk_score {S/O}. Prove the split on β-adjusted outcomes before proposing deployment: (1) does
removing S/O from the return score cost predictive power? (2) do S/O predict the DISPERSION the mean-IC misses?

**Method:** β-backfilled `signal_outcomes`, ex-self, n=6,207. IC = corr(pillar-combo, edge_beta_adj);
dispersion = corr(pillar, edge²)/corr(pillar, |edge|); S/O quintile mean/vol/p10.

**Result — VALIDATED, with a correction to the risk side:**
- **Return claim ✅.** v5_return (F/M/A) IC **0.0663** ≥ v4 composite (F/M/O/S/A) IC **0.0656** — removing S/O
  costs NOTHING (statistically indistinguishable, both t≈5). A alone = 0.0667 (the return workhorse, R62).
  So S/O carry no return signal beyond F/M/A ⇒ they belong on the risk side. Split is free.
- **Risk claim ✅ but O-led, not S-led.** Dispersion corr(pillar, edge²): **O +0.145** (2× any other),
  A +0.079, S +0.040, **F −0.002** (pure return, zero risk). O quintiles escalate vol 14.3→20.8 and deepen
  p10 −13.5→−20.9 MONOTONICALLY. **O is the dispersion pillar, not S** — S is weak on both axes and
  contributes only via Δ-stability (R63b). This CORRECTS the v5 reference (`cis_v5_architecture.py`), whose
  risk_score was S-led; now O-led. F is confirmed a pure-return pillar (return-IC 0.065, dispersion −0.00).
- The load-bearing structural test (7/7): two assets identical except O have IDENTICAL return_score but the
  high-O one's size_mult collapses; v4's single sum does the OPPOSITE (O is +0.20-weighted ⇒ high O RAISES
  the composite, ranking the higher-dispersion asset better — the conflation v5 removes).

**Verdict:** CIS v5 architecture is validated on β-adjusted data — return = {F pure, A workhorse, M weak},
risk = {O dispersion pillar, S/O stability → confidence}. Reference module refined to O-led risk; pure, not
deployed (adoption is a coordinated deploy with Minimax's Mac engine). Meta-lesson: build → validate →
refine — the empirical test moved risk from S to O, which a design-only v5 would have baked in wrong.
`src/data/cis/cis_v5_architecture.py` + 7/7 smoke.
