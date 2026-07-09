# PROJECT_STATE.md — the living single source of truth

**Read this FIRST every session. Update it LAST.** It's the navigation layer over the detailed
docs. If it's stale, fix it. (Behavioral discipline this doc can't enforce but must remind:
before describing any "pending push", run `git status` / `git rev-list origin/main..HEAD` — do
NOT trust memory of what's committed. That error happened 2026-07-02.)

**Last updated:** 2026-07-02 (Seth)

---

## Building log (terse; NOT more md — this replaces scattered docs)
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
