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

