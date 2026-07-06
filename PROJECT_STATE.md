# PROJECT_STATE.md — the living single source of truth

**Read this FIRST every session. Update it LAST.** It's the navigation layer over the detailed
docs. If it's stale, fix it. (Behavioral discipline this doc can't enforce but must remind:
before describing any "pending push", run `git status` / `git rev-list origin/main..HEAD` — do
NOT trust memory of what's committed. That error happened 2026-07-02.)

**Last updated:** 2026-07-02 (Seth)

---

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
- ⬜ next safe self-contained: run H2a Mac-side → decide direction; regime-lens UI badge; optionally
  wire posture.gross_scale into Risk Meter gross (opt-in, after Jazz nod).
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

**D3-DUNE ✅ (Seth, 2026-07-06):** authored + saved Dune query `D3_holder_concentration` = **query_id
7891077** (params token/start_date/end_date → day/n_holders/hhi/top10; free `erc20_ethereum.evt_Transfer`
reconstruction; enterprise balances table confirmed gated). Minimax-A: set `DUNE_QUERY_ID_HOLDERS=7891077`
+ run `fetch_holder_concentration.py` → D3 holder tier goes live end-to-end. ETH ERC-20 only, weekly. See MINIMAX_SYNC.
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
