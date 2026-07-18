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
