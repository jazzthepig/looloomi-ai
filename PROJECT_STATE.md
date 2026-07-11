# PROJECT_STATE.md — the living single source of truth

**Read this FIRST every session. Update it LAST.** It's the navigation layer over the detailed
docs. If it's stale, fix it. (Behavioral discipline this doc can't enforce but must remind:
before describing any "pending push", run `git status` / `git rev-list origin/main..HEAD` — do
NOT trust memory of what's committed. That error happened 2026-07-02.)

**Last updated:** 2026-07-10 (Seth + Minimax-C)

---

## Building log (terse; NOT more md — this replaces scattered docs)
- **2026-07-10 PREDICTION RESOLVER — "resolve EVERY prediction" (closes the 88:4 read-back gap).** Built
  `src/data/signals/prediction_resolver.py` — generalizes outcome_tracker (signals only) to ALL 5 sources
  (signal, positioning, forward_supply, conviction, narrative). Each source's directional claim → resolved
  through the SAME alpha engine (price@date+horizon, BTC/SPY-relative alpha, hit=sign(alpha)==direction) →
  `prediction_outcomes` table (`scripts/supabase_prediction_outcomes.sql`). Per-source read-back
  {n, hit_rate, avg_directional_alpha} = the value-mining query (which sources are actually predictive → feeds
  per-source conviction weighting). Wired: daily `_prediction_resolver_loop` in main.py + `GET
  /internal/prediction-track-record`. Smoke-tested engine against REAL Binance prices ✅. This is the LOOP
  automation fix — turns write-only logs (cause_snapshots/conviction_verdicts/narrative) into measured track
  records. **DEPLOYED 2026-07-10 via Supabase connector** ✅ — 5 tables live on project soupjamxlfsmgmmtoeok:
  cause_snapshots_daily, conviction_verdicts_daily, cause_outcomes, experiment_runs (seeded w/ certified swing
  run), prediction_outcomes. Write verified. ⚠️ SECURITY: connector flagged `signal_outcomes` has RLS DISABLED
  (7743 rows exposed to anon key) — matches SECURITY_REVIEW HIGH finding; needs policy decision (Minimax/Jazz),
  not auto-fixed.
- **2026-07-10 LOOP INDUSTRIALIZATION shipped — experiment recorder + FreqAI assignment.** Built
  `src/research/validation/experiment_recorder.py` (Qlib-style per-run memory; Supabase `experiment_runs` +
  JSONL fallback; the positive-results twin of REFUTATION_LEDGER) + `scripts/supabase_experiment_runs.sql`.
  Seeded with this session's real runs → capital shortlist auto-surfaces the DSR-certified swing lineage;
  refuted runs logged with ledger_ref. Assigned Minimax-C (MINIMAX_SYNC §LOOP-INDUSTRIALIZATION): turn on
  FreqAI adaptive retrain on the certified swing set with CIS+causes+NMA as base indicators (not price-only),
  historic_predictions + Tensorboard, A/B vs frozen REGIME_CIS_FLOOR on OOS → cut if it loses. Seth owns:
  recorder (done), generalizing outcome_tracker to resolve ALL predictions, one-definition feature parity.
  Principle: borrow the field's plumbing, keep our signal. Report: `reports/LOOP_VS_OSS_2026-07-10.md`.
- **2026-07-10 LOOP vs OSS benchmark (Qlib / FreqAI / MLOps).** Reviewed our loop vs the field. Verdict: we're
  AHEAD on WHAT we compute (upstream causal signal; curated Refutation Ledger) and BEHIND on HOW we operationalize
  (no experiment recorder, manual learning, ad-hoc feature store, backtest↔live parity). Cheap adoptions, mostly
  from tools we already run: (1) turn on FreqAI adaptive retrain + historic_predictions + Tensorboard for the swing
  lineage (Minimax-C) → closes "manual learning" for free; (2) Qlib-style Recorder → Supabase `experiment_runs`
  (positive-results twin of the Refutation Ledger); (3) generalize outcome_tracker to "resolve every prediction"
  (causes/conviction/narrative, not just signals); (4) one-definition feature-store parity (Redis live + Supabase
  history, same code path) → kills the R9/R10 "wired≠working / drift" bug class; (5) evaluate Qlib as research
  backbone, not a rewrite. Do NOT copy their alpha source (price/feature ML = our R5 graveyard). Report:
  `reports/LOOP_VS_OSS_2026-07-10.md`.
- **2026-07-10 REFUTATION_LEDGER.md — failures made first-class (Jazz: "failures are more important than
  successes").** Durable graveyard of every falsified/null/false-alarm hypothesis (R1-R10 so far), each with
  the number that killed it + the generalizing lesson. Rule: grep before proposing a new test — if it's here,
  don't re-run it. Aggregate lessons: (1) cleverness overfits, simple survives; (2) edge = orthogonality not
  more-of-same; (3) "wired" ≠ "working" — verify the number+schema; (4) the loop's job is to kill our ideas
  cheaply (9/10 died pre-capital). This is the LEARN-memory the loop was missing.
- **2026-07-10 NMA trend source fixed + causal sleeve expansion TESTED (negative, kept simple).** (1) DATA FIX:
  replaced dead Google-Trends/pytrends (429→flat 50) trend source with real Binance volume+price-momentum
  attention score (`get_google_trend_score` rewritten). NMA now fully repaired — all 3 inputs real; produces
  differentiated signals incl. HYPE=NARRATIVE_FADE (35.8). Three NMA data errors all fixed this session
  (orderflow spot→fapi, social dead-endpoint→Pro-key+live dev/sentiment, trend pytrends→vol/price momentum).
  (2) STRATEGY: tested expanding causal_positioning 24→50 perps — **HURTS** (Sharpe +1.34→+0.12, DD 10→30%):
  funding-crowding is a LARGE-CAP signal, thin/new names = noise. Established-40 holds +1.07 (capacity option,
  small Sharpe cost). Second signal (funding acceleration) also degraded it → rejected. Codified DEFAULT_UNIVERSE
  (24) + ESTABLISHED_UNIVERSE (40, capacity-only) + liquidity-gate lesson in `causal_positioning.py`. Discipline
  win: 2 plausible enhancements tested, both failed OOS-style, kept the simple version. Data cached
  outputs/causal_data.json (50 assets). Report: `reports/CAUSAL_SLEEVE_2026-07-10.md`.
- **2026-07-10 LOOP HEALTH — verified flowing end-to-end + standing instrument.** Jazz: "make sure the system
  is working, all parts flowing." Built `src/api/loop_health.py` + `GET /internal/loop-health` — probes every
  stage (ingest→compute→store→measure→feedback). Live result: **FLOWING (all green)** — CIS universe 58 assets,
  Mac Mini push fresh, causes flowing, conviction feedback learned (STRONG OUTPERFORM 1.265×), NMA differentiated.
  **CORRECTED FALSE ALARM**: my earlier "causes empty on Railway" (logged P1 to Minimax) was a measurement bug —
  I checked flat `forward_supply_risk` but the data is NESTED under `forward_supply`/`positioning`; causes ARE
  live (ONDO fs_risk=0.702, pos=-0.405 on all 24 crypto assets). Fixed the probe + retracted the false alarm in
  MINIMAX_SYNC + LOOP_ENGINEERING. Real loop finding stands: ONE arc closes (signal→30d outcome→conviction→weight,
  proven live); rest is write-heavy/read-light (88 inserts, ~1 auto read-back) — value-mining deferred/manual.
  Doc: `LOOP_ENGINEERING.md`.
- **2026-07-10 NARRATIVE ELEVATION — diagnosis + repair (Jazz: "we have narrative structure but you downplay it,
  frontend doesn't show it" — correct).** Found: NMA pipeline (social+orderflow+trend→nma_score→S-pillar) EXISTS
  with 2 live endpoints (`/api/v1/market/narrative[/{sym}]`) but is ORPHANED — (a) `apply_narrative_to_s_pillar`
  never called → NMA doesn't actually feed CIS; (b) frontend `asset.narrative` = CIS description TEXT, NOT the
  NMA signal → nma_score shown nowhere; (c) DATA SOURCES BROKEN: CG killed `community_data` (404 → social=35
  fallback), orderflow used Binance SPOT (`data-api.binance.vision`) which 400s on perp-only tokens (HYPE) +
  faked funding from spot price. Net: NMA outputs degenerate ~44 NEUTRAL for everything → that's why it's
  dormant. FIXED: orderflow_collector → fapi.binance.com (real depth+funding history+OI, works for HYPE now);
  __init__ defensive imports. Built the working narrative layer: `src/data/narrative/moat_map.py` (L1 structural
  moat ontology) + `catalyst_detector.py` (L2 event→moat→on-chain-activation; validated: HYPE 2026-01-27 fires
  at activation z=9.63, $30.79 → ran to $65). STILL TODO to fully elevate: replace CG-community social source,
  fix/verify trend_score, then wire NMA+catalyst into CIS universe payload + S-pillar + SURFACE in frontend
  (Mac build). Discipline: do NOT wire half-broken NMA into live CIS until social+trend repaired.
- **2026-07-10 CONVICTION METHODOLOGY — catching the next HYPE (沉淀).** New durable methodology doc
  `CONVICTION_METHODOLOGY.md` (companion to ARCHITECTURE + CIS_METHODOLOGY). Thesis: biggest winners come from
  NARRATIVE inflection revealing durable STRUCTURAL VALUE → reflexive cash flow → re-rating; trend/momentum is
  the reflection, narrative-becoming-cashflow is the cause (we trade the cause). Worked example HYPE 2026: the
  spark was a real-world event (Trump weekend war → TradFi commodity markets closed → only Hyperliquid could
  trade the shock 24/7 on-chain w/ leverage → proved the moat live) → 99%-fee buyback loop + 70% perp share +
  $840M rev run-rate → institutional re-rating; price confirmed LAST (chopped down H2'25 46→25, re-accelerated
  25→65 H1'26). Data findings: naive trend on majors weak (Sharpe ~0.2, huge DD); trend on HYPE UNDERPERFORMED
  buy&hold (+37% vs +110% — stop chops you out of the winner) → alpha is SELECTION + CONVICTION HOLD, not the
  indicator. 4-layer stack: L1 structural moat / L2 narrative catalyst (the missing organ to build — event→
  structural-value detector) / L3 fundamental momentum (CIS F+O as rate-of-change + reflexive-loop flag) / L4
  trend confirmation (timing only). Execution: convex sizing (pyramid on confirmation), let right tail run,
  exit on THESIS break not volatility, catastrophe stop only, concentrated. This is the 3rd bet (right-tail/
  beta-plus) alongside swing (mean-rev) + causal (market-neutral). It's the moat because it's judgment-led
  (human+AI), not a commodity bot.
- **2026-07-10 CAUSAL POSITIONING SLEEVE — built + validated + orthogonal (the upgrade delivered).** New
  market-neutral cross-sectional sleeve trading the positioning cause (fade funding crowding: short
  high-funding/crowded-longs, long negative-funding/crowded-shorts). Built on REAL Binance-perp data (24
  assets, 668 days, 2024-01→2025-10) via `src/research/strategies/causal_positioning.py`. Results: full-sample
  ann Sharpe +1.21 (Kwin7,5bps), +41%, 10% maxDD; survives 10bps (+1.0); Kwin monotone (not a lucky peak);
  **chronological OOS Sharpe +1.02 — holds sign/magnitude (unlike the falsified edge gate)**. DECISIVE:
  **correlation to swing book = +0.002** → the orthogonal sleeve the diversification math demanded; ENB
  2.16→2.85. Honest: at swing's inflated in-sample Sharpe ~5 the optimal weight is ~5% (modest uplift), but
  its value GROWS as swing deflates to realistic OOS (√(2²+1.2²)≈2.33 vs 2.0) + carries when swing fails +
  it's the moat. Data reachable from research infra (Binance/Bybit/OKX funding+klines all 200). Cached:
  outputs/causal_data.json. NEXT (Jazz: expand to other assets): widen 24→60–80 perps, stack forward-supply
  cause in same frame, liquidity/capacity filter. Report: `reports/CAUSAL_SLEEVE_2026-07-10.md`.
- **2026-07-10 THE UPGRADE — orthogonality finding + combiner.** Stress-tested the obvious upgrades on real
  data: (1) price/TA meta-labeling on V7 (logistic, IS-train/OOS-test) = NULL (SR/trade 0.272→0.274, just cuts
  trades) → swing is price-efficient; (2) naive equal/inverse-vol ensemble = WORSE than best single (dilution).
  Real diagnosis: the 5 DSR-certified survivors are **0.67 mutually correlated (V8/V9/V10 = 0.95–1.0), ENB=2.16
  → ~1.5 ideas in 5 costumes**. Diversification math (V7 ann Sharpe 5.6): marginal book Sharpe is driven by
  CORRELATION not the new sleeve's own Sharpe — orthogonal(SR2.0,corr0)→5.96 vs great-but-correlated(SR2.8,
  corr0.3)→5.73; another swing variant (corr0.95)→~nothing. **The upgrade = ONE uncorrelated sleeve, not a
  sixth swing.** Uniquely-ours orthogonal candidates: (a) causal forced-flow (forward_supply/positioning — moat),
  (b) delta-neutral funding_carry (shipped, market-neutral). Built `src/research/validation/portfolio_combiner.py`
  (corr-de-duplicated inv-variance + effective-number-of-bets X-ray; honest −1.39 uplift on the lineage proves
  no internal blend beats V7). Report: `reports/STRATEGY_UPGRADE_2026-07-10.md`.
- **2026-07-10 DSR factory audit — built the instrument + certified the swing lineage.** Full arsenal is
  ~50 freqtrade strategies (Swing V6→V10, CoreBasketV6, MetaV4, SMC, SmartMM, LiqAware, MVRV, Crowd,
  AutoResearch pipeline, + signal tools: SMC/funding/polymarket/factor-miner/correlation). Built
  `src/research/validation/deflated_sharpe.py` (Bailey-LdP Deflated Sharpe Ratio + expected-max-Sharpe,
  pure-numpy, self-test passes: real edge DSR 0.9997 vs best-of-40 noise 0.078). Ran over live backtests:
  full 35-way search → 0 survive DSR@0.95 (undisciplined search certifies nothing); **disciplined candidate
  set (positive SR, ≥50 trades, N=9) → 5 SURVIVORS, all SwingOverlay lineage** (V8_Regime 0.999, V7 0.998,
  V9_DirAware 0.994, V10_FundingAware 0.994, V10_FundingAggressive 0.981). Investor-grade claim: our swing
  lineage survives multiple-testing correction in-sample. NEXT (real research to strengthen): DSR on
  walk-forward OOS (certify for capital), retire ~25 negative-SR trials, meta-labeling on swing primaries,
  regime-ensemble across the 5 survivors, wire DSR as a standing promotion gate. Report:
  `reports/STRATEGY_DSR_AUDIT_2026-07-10.md`.
- **2026-07-10 V10 BUILD (Minimax-C) — MTF + Funding-Aware + Vol-Target; operational layer for THE UPGRADE
  finding.** Built the next swing iteration layering P1 ground-truth (regime-conditional funding gate) +
  MetaV4's vol-target sizing onto V9. Two files: `SwingOverlayV10_MTF_FundingAware_VolTarget.py` (5-pair,
  815L) + `_ETH.py` (1-pair, 2.5× stakes, 783L) at
  `/Volumes/CometCloudAI/cometcloud-local/user_data/strategies/`. V10 added two pieces: **(1) per-row
  regime-conditional funding gate** (V9's old `FUNDING_BPS_SKIP_LONG` global flag was too coarse; P1
  parity 2026-07-09 found funding sign MIXED 5/12 — negative funding bullish 4/4, positive bearish
  only in bear markets). New logic: `bull & fr>3bps → block long`; `bear & fr<-3bps → block short`
  (per-row mask, defence-in-depth also in `confirm_trade_entry`). **(2) Vol-target sizing**
  (`stake × clip(VOL_TARGET_PCT/atr_pct, 0.5, 1.0)`) applied after naked-short mult — **calibration
  finding**: MetaV4's `VOL_TARGET_PCT=0.04` is a no-op at 15min timescale (BTC 15min ATR% p50=0.31%, so
  the clip pins at 1.0 always); recalibrating to `0.005` actually fires the scaler. Walk-forward 3
  windows (TRAIN 2024 bull / VALIDATE 2025 chop / HOLD-OUT 2026 recovery):
  **V10 = +2,572.7 USDT vs V9 +3,169.8 USDT (-18.8% P&L), trades 1,207 vs 1,297 (-7.0%), MDD
  3.18% vs 2.72% in 2025 chop (+0.46pp), TRAIN avg stake 678→595 USDT (-12.3% — confirms vol-target
  activation)**. Funding-gate LOGIC verified by unit test (`/tmp/v10_unit_test.py`, 4/4 cases pass)
  but **does NOT fire in backtest** — CIS funding cache returns 0 in backtest mode (no per-bar funding
  wired into the loader); per-bar funding = **V11 work** (extend CIS loader to read `CIS_HISTORY_DIR`).
  V10-ETH ≈ V9-ETH (no gates fire at 2.5× scale on ETH-only; benign reversion = expected safety property
  when no signal is present). **Verdict:** V9 retained as production, V10 retained for archival.
  **Aligns with Seth's same-day work on three counts:** (a) **V10_FundingAware (DSR 0.994) already in DSR
  audit survivors** above — audit pre-confirmed the lineage before walk-forward; (b) **THE UPGRADE
  finding (orthogonality math) predicts another swing variant is dilutive** (5 DSR survivors 0.67
  mutually correlated, V8/V9/V10=0.95-1.0) — V10 walk-forward confirms it (-18.8%); (c) **Causal
  Positioning Sleeve** (ann Sharpe +1.21, corr +0.002 to swing, ENB 2.16→2.85) is the orthogonal
  answer V10 isn't. Incremental value = the **vol-target calibration finding** (15min vs daily ATR%
  timescale is transferable to any vol-target implementation) + a documented **regime-conditional
  funding-gate pattern** (template for orthogonal causal-gated swing attempts in V11+). **V10 report
  status = NEUTRAL per compliance language** ("more conservative but does not improve P&L"); no
  signal-grade language used. Reports: `_data/research/V10_MTF_FundingAware_VolTarget_2026-07-09.md`,
  `parity_w5/P1_PARITY_ASSESSMENT_2026-07-09.md`. Configs: `/tmp/config_swing_v10{,_eth}.json`. Walk-
  forward logs: `/tmp/v10{,_eth}_{train_2024,validate_2025,holdout_2026}.txt`.
- **2026-07-10 Strategy competitiveness review (CORRECTED).** First pass benchmarked against the GRAVEYARD
  (dead LS_V4 −6.59%, META_V4 −5.47%, falsified edge gate) and wrongly concluded "no profitable strategies"
  — a research miss: never opened `Shadow/freqtrade/user_data/backtest_results/`. REAL state: the
  **SwingOverlay V6→V10 family** (MTF regime + funding-aware gates + vol-target + circuit breaker) + CoreBasketV6
  are PROFITABLE — credible n≥500 runs: Sharpe ~6.3–9.5, CAGR ~32–54%, PF 1.9–2.6, DD 2–3%, win 66–70%
  (small-n variants show Sharpe 10–14 = overfit-suspect). Corrected verdict: we ARE competitive on directional
  swing, build quality above public median; the gating question is OOS/walk-forward robustness (high Sharpes +
  window variance = overfit signature — same discipline that caught the edge gate). Only structural moat still
  = forward-supply/unlock cause (unblock via historical unlock event study, not 180-day wait). `funding_carry.py`
  (shipped) repositioned honestly as an OPTIONAL market-neutral sleeve, NOT a missing lane. Report:
  `reports/STRATEGY_COMPETITIVENESS_2026-07-10.md`. NEXT: put SwingOverlay through walk-forward OOS + cost model;
  headline only OOS-surviving numbers for LP use.
- **2026-07-06 ⚠️ FALSIFIED — edge gate CUT** (Minimax-A A2 harness, audit commit 0e868a7): OOS proved the
  empirical edge-map-DIRECTION hypothesis overfits — edge gate took 4 straight longs into a falling BTC
  (−$479) while the frozen CIS baseline (`REGIME_CIS_FLOOR`) MADE money (+0.59 Sharpe, PF 1.38). p=0.867,
  no rejection of null. **Propagation:** `conviction`/`conviction_book` anchor direction on the SAME edge-map
  signal → presumed overfit. **Seth pruned own build:** paper sleeve reverted to risk-meter; `conviction_book`
  gated OFF (`CONVICTION_BOOK_ENABLED`, research-only) until it passes the harness. The causes (forward_supply,
  positioning) are ALSO unvalidated — same trap — must pass B2 before any claim. VALIDATED core = the CIS
  quality gate. The clever cause-timing = hypothesis, not fact. This is the loop earning the word.
- **2026-07-06 FRONT DOOR = Diagnose** (App.jsx): default landing is now `DiagnoseHome` (embedded) +
  Risk Meter — "your book, read upstream of price" — per ARCHITECTURE §iPod (Diagnose = Fusion #1, the
  lovable front). Demoted the commodity breadth (VC/signal-feed leading). De-claimed the losing signal
  page from green "LIVE" → "PAPER · UNVALIDATED" (doc: must not claim unproven). Needs Mac-side build
  (FUSE deny-unlink blocks local vite; binaries wrong-arch). Full convergence (fold provenance, demote
  rest) still to do.
- **2026-07-06 RISK LIMIT: per-name cap** (`conviction._capped_weights`, `_MAX_NAME_FRAC=0.22`): closes
  assessment W3 — no single name > 22% of its side's gross; thin breadth → under-deploy, never over-
  concentrate. Verified: the 77.9%-single-name case now caps at 22%. Pre-capital blocker cleared.
- **2026-07-06 ASSIGNMENTS distributed** to Minimax-A/B/C (MINIMAX_SYNC §ASSIGNMENTS) — all oriented to
  VALIDATION (turn "correct"→"proven"); A2 (OOS harness vs frozen baseline) is the load-bearing one.
- **2026-07-06 UPSTREAM CAUSE #1 = forward supply** (`src/data/cis/forward_supply.py`): forced-seller
  overhang from CoinGecko circ/total/max supply (free; DeFiLlama unlock API now paywalled). Wired into
  the conviction KERNEL as a BEARISH directional cause (`_FS_WEIGHT`), attached in cis.py, 6h loop in main.py.
  Verified: it OVERRIDES the reflection — ONDO (70% overhang) flips +1.7% edge long → short. Mirror of 出圈
  (demand-exhaustion) on the supply side. This is the first factor that is a CAUSE, not a price reflection.

- **2026-07-06 UPSTREAM CAUSE #2 = positioning** (`src/data/cis/positioning.py`): reflexive leverage —
  OI-weighted funding from free CG /derivatives → signed pressure (+ crowded-short squeeze / − crowded-long
  liquidation). Wired into conviction (`_POS_WEIGHT`, signed), attached cis.py, 30min loop. Verified live:
  BTC/HYPE/UNI overleveraged-long (bearish), APT/AVAX/ONDO crowded-short (bullish). The kernel now nets
  reflection + demand-cause (出圈) + supply-cause + leverage-cause + executability into ONE conviction; when
  causes conflict (ONDO: supply-bear vs squeeze-bull) conviction honestly stays low. The kernel is no longer
  reflection-all-the-way-down.

- **2026-07-06 KERNEL → ACT** (`conviction.conviction_book` + `trading._run_paper_rebalance`):
  the paper sleeve now trades the CONVICTION KERNEL's signed book (reflection + 出圈 + forward-supply
  + positioning + executability), not the narrow risk-meter weights. The forced-seller short & squeeze-
  long plays fall out of it; illiquid names dropped; shorts regime-gated; gross regime-scaled. Verified:
  neutral tape → 5 liquid high-conviction longs (honest — few clear the bar); shorts appear when permitted.
  This closes Sense→Judge→ACT in paper. Real capital = the one open arc, and it's Jazz's (per the plan).

## North star (1 line)
We are the **judgment substrate** — hard-to-verify upstream intelligence (influence → quality
propagation, 出圈/proximity-to-cause) that we verify ourselves and hand over with provenance so
other agents can trust it. Full autonomy is the partner's game, not ours. Soul: `ARCHITECTURE.md`.

## What we're building (the PRD-lite)
1. **CometCloud fund** — AI-curated crypto FoF, Hong Kong regulated, performance-only.
2. **The intelligence substrate** (the moat + a sellable product):
   - **CIS** — 5-pillar quality score, per asset class, regime-neutral grade + regime as a
     separate exposure axis (GRADE-ALIGN Option B).
   - **cause_proximity / 出圈** — how far a consensus has diffused (fragility).
   - **Risk Meter** — turns grade + fragility + conviction into position sizing.
   - **Edge map** — the Glassnode-tier product: expected 30d benchmark-relative alpha per
     signal tier × risk gradient, every cell a real outcome with sample size.
   - **Provenance + track record** — so a consuming agent can *defend* a decision.
3. **The self-tuning loop** — Sense → Synthesize → Judge → Act → Learn → back into Judge,
   recalibrating conviction daily from our own outcomes.

## Core validated findings (from our own data — don't re-derive, cite these)
- Signal is **monotonic** in 30d benchmark-relative alpha: STRONG OUTPERFORM +3.3% → OUTPERFORM
  −0.4% → UNDERWEIGHT −1.2% → UNDERPERFORM −1.8%. It ranks correctly. (`TRACK_RECORD_2026-07-01.md`)
- Edge is **regime/gradient-conditional**: long top tier in risk-ON (deep-on +10.5% / 100d,
  +26.8% / 11yr backtest); short bottom tier in risk-OFF (+6% deep-off). Neutral tape → shrinks.
- **11-year backtest (our OHLCV) confirms** the long-leaders-in-risk-on structure across cycles.
- Long edge **concentrates per asset**: ETH (46 signals, +13.8%), LINK, ARB, LDO. HYPE too new.
- Discipline (大象无形): ranking stable, tradeable *direction* is regime-conditional; N-gate
  everything; never trade a frozen factor.

## Architecture snapshot
- **Serving** = Supabase (lean; what API/agents read). **Warehouse** = local drive
  `/Volumes/CometCloudAI/cometcloud-local/_data/` (heavy: 11yr OHLCV, CIS-historical, backtests),
  mirrored to `Shadow/` so Seth can READ it. Seth writes Supabase only; Minimax owns the drive.
  (`MINIMAX_SYNC.md §WAREHOUSE`)
- Ownership: Seth = `src/` + Railway + Supabase serving. Minimax-A = Mac data/ops + drive.
  Minimax-B = NautilusTrader. Minimax-C = freqtrade. Jazz = decisions + push + capital.

## Where we are — in-flight & blocked (by owner)
**Seth (me):**
- ✅ done: cause_proximity, Risk Meter, conviction tilt (self-tuning), provenance, benchmark-
  relative outcomes, outcome tracker on own-data, track record + edge map (tables+endpoints+MCP),
  P0/P1 fixes, T2 base-weight alignment.
- ✅ HOLD RELEASED (2026-07-05): `cis_provider.py` T2 weights — Minimax-A shipped T1 #5 (17/17
  classes canonical, MD5-identical Live↔Shadow). Seth step-2 verified: T2 `_BASE_WEIGHTS` byte-
  identical to CIS_BASE_WEIGHTS.md AND T2 grades on regime-neutral raw = Σ base×pillar (Option B);
  L1 test vector → raw 67.0 matches T1 acceptance. **Now URGENT to deploy** — T1 is live/next-tick
  canonical while Railway T2 still runs the OLD table → live divergence until `cis_provider.py` ships.
  Jazz commits it in the same push as the sleeve fix (no longer needs to be separate).
- ✅ COMMITTED, needs push: edge-map batch (signals/store/mcp + HANDOFF) — **HEAD is 2 commits
  ahead of origin/main.** Jazz runs `git push origin main`. (Verified via git rev-list 2026-07-05,
  NOT memory — the summary wrongly said "staged/blocked".)
- 🟡 uncommitted (2026-07-05, Loop Watch fix) — BLOCKED by sandbox `.git/index.lock` (can't unlink,
  OS perms); Jazz clears lock + commits `trading.py` + `risk_meter.py` + `CLAUDE.md` + `PROJECT_STATE.md`:
  - `trading.py`: (a) bogus tp/sl flag guard (stop_loss/take_profit=0 made `price>=0` fire
    tp_triggered on every METER_REBAL position → false "exits stalled" alarm); (b) **risk
    circuit-breaker** `REBAL_MAX_ADVERSE_PCT=-20%`, NOT churn-gated; (c) regime-no-short breaker.
  - `risk_meter.py`: **regime-gated shorts** (`_SHORT_OK={Risk-Off,Stagflation}`, `shorts_allowed`
    threaded through build_risk_meter) — shorts only in true falling-market regimes. Self-test extended.
  - EXCLUDE from this commit: `cis_provider.py` (held for T1 #5), `requirements.txt` + `src/research/nautilus/` (Minimax's).
- 🟡 uncommitted (2026-07-06): `cause_proximity.py` — **season lifecycle consumed** (Jazz money
  insight + Minimax §BOARD #5): `momentum` season DEPRESSES out-of-circle risk ×0.55 (ride the
  出圈 wealth-creation window), `stale` ELEVATES to floor 0.72 (window closed). Flows into sizing
  via Risk Meter (verified: momentum name +19% weight vs stale). Dormant until D3 data lands
  (query_id 7891077). No-cost strategy win. Ready to commit + push (Mac-side).

**Strategy direction (no new cost — Jazz 2026-07-06 "先赚到钱再加"):**
- **H1 finding (research lane):** composite CIS 7d forward-return IC is NEGATIVE in Risk-Off/Risk-On/
  Stagflation, POSITIVE only in Tightening, flat in Easing → the CIS gate is directionally INVERTED
  in 3/6 regimes; it works as a RISK FILTER, not a return predictor. Validates regime-conditioning
  (edge map + regime-gated shorts + season already do this). **H2 = per-regime gate direction+magnitude.**
  ⚠️ Do NOT unilaterally invert the production Risk Meter on H1 alone — wait for H2's confirmed
  direction table (research lane in-flight); premature inversion risks the live book.
- **H2 design DONE** (`docs/H2_REGIME_GATE_DESIGN_2026-07-06.md`): reframe = separate CIS-as-ranking
  from regime-as-beta-timing; do NOT invert CIS in prod. Blocked on Phase 0 = fix the noisy regime
  detector (Minimax-A). Immediate-safe changes: drop CIS floor→eligibility in Easing (flat IC),
  shrink gross in low-confidence regimes.
- **H2a script DONE** (`src/research/cis_regime_studies/h2a_relative_ic.py`) — benchmark-relative IC
  test (is the sign-flip beta artifact or real reversal). Runs Mac-side (needs OHLCV panel + scipy).
- **season lifecycle EXTENDED** (`cause_proximity.py`): full pre-出圈 accumulation stages
  (capitulation/dry_up/spring_test/early_markup) + momentum/stale, cold→hot risk curve verified
  (dry_up lowest 0.168 → stale highest 0.720). Season vocab contract handed to Minimax (§MINIMAX_SYNC).
- **current-band read + posture DONE** (`signals.py` + `main.py` + MCP): `/api/v1/signals/current-band`
  computes today's risk-gradient band (BTC 30d) → per-tier expected alpha NOW → actionable **posture**
  (net_bias + gross_scale + confirmation), sample-size-guarded (thin cell → dampen + flag). Persisted
  daily to Supabase `regime_band_log` (created; cols incl net_bias/gross_scale) via `_band_log_loop`
  → flows to Mac warehouse (Minimax adds it to the drive mirror). MCP tool `cometcloud_get_current_band`.
  Posture is ADVISORY (positioning language) — not wired to force live sizing (that needs Jazz nod).
- **Conviction Fusion #1 DONE** (`src/data/cis/conviction.py` + `/api/v1/cis/conviction` +
  `cometcloud_get_conviction` MCP): the single per-asset verdict fusing regime-neutral QUALITY ×
  cause-proximity (in-circle vs 出圈 + season) × edge-map expected alpha (tier × TODAY's band, real
  outcomes) × EXECUTABILITY. Ranked by signed edge; sample-size gated; illiquid names discounted
  (a B+ you can't size ≠ a core overweight). Verified on live universe. **Flagship Diagnose enriched**
  to consume it — per-holding conviction/direction/action + book `illiquid_pct` + verdict note
  ("X% in illiquid names — can't build/exit size"). This is the actionable output of all the mining.
- 🟡 Moralis D3: key works live, but holder map empty → likely `/erc20/{addr}/owners` is a premium
  Moralis endpoint on this plan (or field mismatch). Added `/api/v1/signals/holder-map` diagnostic
  (uncommitted) — push it, hit it, read `probe_error` to decide (upgrade Moralis vs Helius/Bitquery).
- **Edge-map SHRINKAGE DONE** (`src/data/signals/edge_shrinkage.py`) — the hard statistical problem:
  100 days = wildly uneven cells (n=1..1672); a raw thin cell is pure noise (OUTPERFORM/deep-off
  −64% on n=3). Empirical-Bayes shrinkage: two-way ADDITIVE prior (tier+band, captures the monotonic
  "rises with risk-on" structure) + James-Stein weight `n/(n+K)`, K by ROBUST (median) MoM. Result:
  well-sampled cells keep 76–90% own value, thin/noisy cells collapse to the structural prior, grid
  becomes monotonic + denoised (K≈184). Wired into `compute_current_band` (posture/conviction now read
  the SHRUNK alpha) + conviction's hard n-gate relaxed (n → confidence, not discard) + edge-map endpoint
  exposes raw/shrunk/weight/prior. This is AQR/Millennium-grade rigor making the surface honest on thin data.
- **H3 edge-map BACKFILL DONE** (`h3_edge_map_backfill.py`) — the root-cause fix for "only 100 days"
  (Jazz: don't use it as an excuse). Applies CURRENT signal logic across `cis_history` (393d × 40) ×
  OHLCV → ~12k historical signal→30d-alpha pairs → backfills `signal_outcomes` (before live, no clobber)
  → existing refresh rebuilds a robust edge map (thin cells n=1..3 → hundreds). Runs Mac-side (`--write`).
  Phase-2 (Minimax): extend `cis_history` to 11yr OHLCV via CIS reconstruction → h3 auto-covers it.
- **EDGE GATE bridge DONE** (`src/research/strategies/edge_gate.py` + `scripts/export_edge_gate_grid.py`)
  — the intelligence→execution connection Jazz asked for (reference Minimax-B/C strategies). Replaces the
  hand-tuned `REGIME_CIS_FLOOR` (H1: wrong in 3/6 regimes) with `gate(grid, tier, band, side)` reading the
  SHRUNK edge map → allow/block + conviction-scaled size, direction from DATA (short-weak allowed only where
  it empirically pays). Pure module (no pandas/scipy) so it runs inside Nautilus/freqtrade. Grid live at the
  edge-map endpoint (shrinkage confirmed live, K=184). Integration recipe for Minimax-B/C in MINIMAX_SYNC.
- **NOTE: shrinkage is LIVE** (deployed via a Minimax push) — verified on `/api/v1/signals/edge-map`.
- **2026-07-09 EDGE GATE A/B (continuous, per-regime IC) — NEGATIVE for ship**
  (`src/research/nautilus/ls_v1/edge_gate.py`, `src/research/cis_regime_studies/edge_gate_ab.py`,
  `reports/EDGE_GATE_AB_2026-07-09.md`). The continuous `edge = side × IC_regime × z × sigma × sqrt(h) − cost`
  gate (alternative to the empirical grid edge gate above) is wired into LS v1 with `use_edge_gate=True` and
  A/B'd across 4 smoothed dirs × {IS, OOS} × {baseline, edge_gate} = 16 runs. **Edge gate loses in both
  windows across all dirs** (ΔIS PnL −$316 to −$503, ΔOOS PnL −$23). Per-regime IC magnitudes (−0.09 to
  −0.36 smoothed) sit below the AQR noise floor (~±0.24 at n=70); the regime-conditional reversal is
  structurally correct but empirically underpowered. **3 negative results in a row** on per-regime gate
  refinement (H3, H2 magnitudes, this). Keep `REGIME_CIS_FLOOR` as production gate. Phase 1 ship
  (smoothed regime labels, no floor changes) is the correct next move. Pivot edge-gate formula to H3.2
  sizing-multiplier when ≥6mo OOS data accumulates.
- **2026-07-09 H3.2 conviction-weighted SIZING A/B — POSITIVE for ship as opt-in**
  (`src/research/nautilus/ls_v1/strategy.py` `use_h32_sizing` config +
  `_h32_sizing_multiplier()` + `create_order_qty` applies multiplier;
  `src/research/cis_regime_studies/h32_sizing_ab.py`;
  `reports/H32_SIZING_AB_2026-07-09.md`). Per H3: "conviction is a sizing signal,
  not a gating signal." H3.1 (gate-multiplier) lost because the floor band is a
  knife-edge. H3.2 sidesteps that by leaving the gate at `REGIME_CIS_FLOOR` unchanged
  and scaling POSITION SIZE by today's conviction: `trade_size × (floor + (cap−floor) × c)`.
  A/B'd across raw + modal_recency dirs × {IS, OOS} × {baseline, h32_sizing} = 8 runs.
  **H3.2 wins per-trade PnL in ALL 4 runs** (Δ IS $/pos +$1.79 to +$2.14, Δ OOS $/pos
  +$0.10 to +$2.25). Trade count unchanged (gate unmodified). **First POSITIVE result
  in the H-series** (H3 prototype / H2 magnitudes / edge gate all lost). Mechanism =
  Millennium soft-sizing: let the signal through, weight by confidence. Ship as opt-in
  via `LSV1_USE_H32_SIZING=1` (floor/cap configurable via env).
- **2026-07-10 H3.2 sizing FLOOR/CAP SWEEP — REFINED positive; bump default cap 1.5 → 1.75**
  (`src/research/cis_regime_studies/h32_sizing_sweep.py`,
  `src/research/nautilus/ls_v1/strategy.py` `LSv1Config.h32_size_cap` default bumped 1.5→1.75,
  `reports/H32_SIZING_FLOORCAP_SWEEP_2026-07-10.md`). The `[0.5, 1.5]` default was ad-hoc.
  Swept 6 (floor, cap) variants × raw + modal_recency × {IS, OOS} = 24 Nautilus runs.
  **Key insight:** IS Sharpe is INVARIANT to (floor, cap) at this sample size — both
  per-trade mean AND per-trade std scale linearly with size, so E[X]/SD[X] is invariant.
  The differentiating metric is **per-trade PnL**, which scales monotonically with cap:
  cap 1.25→1.5→1.75→2.0 gives raw IS $/pos $+5.74→$+6.85→$+8.02→$+9.01.
  `cvx` (linear through origin) is the WORSE outcome — zero size on low-conv days removes
  the protective trades. `d0.25` matters little (median conviction ≈ 0.93, floor rarely bites).
  **Pareto decision:** bump production default cap 1.5 → **1.75**. Captures +37% PnL
  on IS (n=58 reliable) with no Sharpe penalty. Cap=2.0 is research ceiling (diminishing
  returns + Sharpe decay in modal_recency 0.066→0.061). Cap=1.25 too tight. **Re-verify
  after ≥6mo OOS data accumulates.**
- **2026-07-10 H3.2 PORTFOLIO-LEVEL MaxDD analysis — CORRECTIVE FINDING (linear lever, not alpha)**
  (`src/research/cis_regime_studies/h32_sizing_portfolio_dd.py`,
  `reports/H32_SIZING_PORTFOLIO_DD_2026-07-10.md`). Aggregated per-trade PnL from
  the 24 sweep runs into portfolio equity curves. **Critical finding:** ALL variants
  have DD/PnL ≈ 0.96-1.00 — capturing 1× the PnL costs ~1× the Max DD. This is the
  expected math when only position size changes (trade list is identical across variants).
  Per-day Sharpe is essentially flat (0.0766-0.0779 raw/IS, within noise at n=58).
  **Revised framing:** H3.2 is a **linear sizing controller**, not an alpha source.
  The "Pareto-balanced" framing in the previous report was misleading — the choice
  between cap=1.0 and cap=1.75 is a **leverage decision**, not a quality decision.
  One mitigating finding: t1.75 has the BEST per-day Sharpe (+0.0008 over def) — within
  noise but consistent with the H3 finding. **Revised recommendation:** keep cap=1.75
  as default but document it as a leverage bump (already shipped to strategy.py).
  Env-var override (`LSV1_H32_SIZE_CAP`) keeps the choice tunable per deployment.
  Corrective addendum added to `reports/H32_SIZING_FLOORCAP_SWEEP_2026-07-10.md`.
- **2026-07-10 H2a benchmark-relative IC test — CRITICAL FINDING (genuine reversal in 3/5 regimes)**
  (`src/research/cis_regime_studies/h2a_relative_ic.py` ran successfully today;
  `reports/H2A_RELATIVE_IC_2026-07-10.md`, raw output `reports/cis_regime_relative_ic_2026-07-06.{md,json}`).
  Tests if H1's sign-flips are BETA artifact (vanish under BTC-relative returns) or genuine
  reversal (persist). **Verdict: GENUINE REVERSAL in 3/5 regimes at 7d** — Stagflation IC_abs=-0.235
  → IC_rel=-0.326 (gets WORSE), Risk-On IC_abs=-0.166 → IC_rel=-0.101, Risk-Off IC_abs=-0.093
  → IC_rel=-0.104. Only Tightening is consistent (both positive, n=216 small). At 30d:
  Easing becomes genuine reversal (was flat at 7d); Risk-On becomes beta artifact (recovers
  to flat under relative). **H2 direction-by-regime is now CONFIRMED necessary, not just
  hypothesized.** Action items: (a) H2 design must populate per-regime × per-horizon direction
  table, (b) H3.2 sizing remains valid as a sizing LAYER (independent of gate direction),
  (c) Phase 1 ship (smoothed regime labels) still valid, (d) empirical-grid edge gate A/B
  should consider per-regime direction. Honest caveats: Stagflation n=195 and Tightening n=216
  small; OHLCV ends 2026-06-07; benchmark = BTC for all crypto (no per-asset benchmark).
- **2026-07-09 CAUSE-DRIVEN BACKTEST infrastructure (B2) — SHIPPED, run BLOCKED on data**
  (`scripts/supabase_migration_cause_history.sql`, `src/data/cis/cause_persistence.py`,
  `src/research/cis_regime_studies/cause_backtest.py`, `reports/CAUSE_BACKTEST_2026-07-09.md`).
  First real test of whether ARCHITECTURE.md "causes predict" (forced-seller short + squeeze-long
  + long-liq short). Cause data has only been live ~3 days — no historical record exists.
  Built the rig (schema + persistence + backtest skeleton + smoke test) but the actual backtest
  needs ≥180 days cause_snapshots_daily + OHLCV panel landing (Minimax-A P1, not started). Live
  snapshot today: 5 forced_seller_short candidates (HYPE/APT/SUI/ONDO/OP), 0 squeeze_longs.
  Discipline: we built the experiment; we cannot shortcut the 6-month waiting.
- ⬜ next: A/B the empirical grid edge gate (separate approach) in Nautilus LS v1; run H3+H2a Mac-side;
  conviction UI; Phase 1 ship (smoothed regime labels); cause-history accumulation (180d).
- 🟡 uncommitted (2026-07-06, GRADE-ALIGN Option B frontend/read switch) — BLOCKED by git lock;
  Jazz commits `cis.py` + `cis_provider.py`:
  - `cis.py` merge: normalizes the WHOLE universe (T1+T2) onto raw quality — `grade = get_grade(raw)`,
    `cis_score = raw`, `regime_adjusted_score` = old adjusted (regime lens preserved), sort on raw.
    Single Railway-side change, NO T1 cis_v4_engine lockstep (both tiers already carry raw_cis_score).
  - `cis_provider.py`: T2 emits the same shape natively (grade on raw, cis_score=raw, +regime_adjusted_score).
  - Verified against live universe: grade==g(cis_score) for ALL assets; 16 grades shift vs regime-baked;
    leaderboard now quality-ranked (PENDLE B+ quality, regime tilt → signal/regime_adjusted).
  - PRODUCT-FACING (grades move, cis_score semantics change) → needs Jazz green-light to push.
  - Minimax note: Railway now overrides T1's pushed `grade` (re-grades on raw at merge, idempotent);
    T1 can later grade on raw natively — identical result, no rush. SCHEMA note in §GRADE-ALIGN.
- ⬜ next: regime-lens UI badge (surface regime_adjusted_score as the visible separate axis) ·
  regime-aware conviction (reads edge map, N-gated) · live "current band" on edge-map · win.html surfacing.

**Loop Watch finding (2026-07-05):** METER_REBAL "rotation stall" was NOT a broken exit path.
Book is stable in flat Tightening regime (target≈held, `reason=none`). Real issue: sleeve holds
shorts on benchmark-underperformers (ADA/ETH still UNDERPERFORM = thesis intact) but trades
ABSOLUTE price while the signal predicts only benchmark-RELATIVE alpha → shorts bleed beta when
tape isn't risk-off (edge-map: shorts only pay deep-off). 12-vs-5 trade_results gap = historical
pre-fix closes, writer healthy. **DECISION FOR JAZZ:** regime-gate shorts (only open shorts when
risk gradient is risk-off) vs keep the −20% breaker as the only guard. Breaker shipped as safety net.

**D3 LIVE = Moralis-on-Railway ✅ (Seth, 2026-07-06):** Jazz connected Moralis; I wired the on-chain
holder tier on Railway — `src/data/cis/holder_provider.py` (registry symbol→contract → Moralis owners →
top10 share + HHI → `stage`; multi-chain incl Solana Phase-2), `_holder_refresh_loop` → Redis `cis:holder_map`,
attached into `cause_proximity` (cis.py). Activates on deploy with `MORALIS_API_KEY` (already set). Verified:
concentrated→stage 0.08→risk down, dispersed→0.79→risk up, confidence 0.85. Covers ONDO/PENDLE/UNI/AAVE/MKR/
LINK/LDO/ARB, graceful D4 for rest. **This SUPERSEDES the Dune path** (query 7891077 → optional Phase-2 history
only; NO Dune purchase needed — the cost question is resolved). Phase-2 = dynamic season/chuquan from Moralis
holder-timeseries (Minimax Wyckoff lane; season contract unchanged).
**Minimax-A:** T1 #5 (per-class weights, patch in §GRADE-ALIGN) · restore drive→Shadow sync · stand up local warehouse + CG/EODHD top-ups
(dominance, mcap, VIX) + 11yr CIS-historical reconstruction · macro brief model (gemma-4-31b-qat +
API thinking-off).
**Minimax-B/C:** backtest the validated hypothesis (regime-conditional long-STRONG / short-UNDER, gradient-scaled).
**Jazz:** bless canonical `CIS_BASE_WEIGHTS.md` · greenlight the edge-map commit + coordinated
GRADE-ALIGN deploy · rotate shared `INTERNAL_TOKEN`.

## Key decisions log (pointers)
- GRADE-ALIGN Option B + canonical base weights → `CIS_BASE_WEIGHTS.md`, `MINIMAX_SYNC §GRADE-ALIGN`.
- Two-tier data landing → `MINIMAX_SYNC §WAREHOUSE`.
- Historical reconstruction from CG Pro + EODHD (FNG synthesized, on-chain proxied by volume) → `HANDOFF_2026-07-02.md §3`.
- Substrate positioning / vectors & movement → `ARCHITECTURE.md`.
- Full session comms → `HANDOFF_2026-07-02.md`.

## Detailed docs index
`ARCHITECTURE.md` (soul) · `MINIMAX_SYNC.md` (coordination, gitignored) · `CIS_BASE_WEIGHTS.md`
(canonical) · `TRACK_RECORD_2026-07-01.md` · `AUDIT_financial_engineer_2026-06-30.md` ·
`ADR-001_loop_architecture_completeness.md` · `HANDOFF_2026-07-02.md` · `scripts/track_record.sql` ·
`scripts/loop_health.py` (daily watch).
