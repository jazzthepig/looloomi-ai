# Session Log — 2026-07-21 (Jazz ↔ Seth)

Machine-ingestible digest of the 2026-07-21 working session, for logging into the local research DB.
Narrative/strategy → `WEEKLY_REVIEW.md` (2026-07-21). Empirical detail → `REFUTATION_LEDGER.md`
R61–R63b. State → `PROJECT_STATE.md`. Market mechanics → `docs/MECHANISM_SPEC.md`.

---

## 1. Headline

**The metric was the bug, not the model.** The live signal book appeared non-predictive
(OUTPERFORM t=−4.09). Root cause: asset β vs benchmark is **1.4–2.4**, so `a_ret − b_ret` measured
leveraged beta, not alpha — in a bear-dominated window a *good* signal reads as inverted. After
PIT-safe β adjustment the book is strongly predictive and **CIS works**.

Three separate "our edge is broken" findings this session were all **measurement defects**:
1. `interpretation_c.py` — full-sample normalization (look-ahead) → affects R51/R53/R54/R55/R57
2. V9 audit — unverified hand-rolled 4h→15m merge (look-ahead suspect, untested)
3. Live alpha metric — no β adjustment (this one, R61→R62)

Two independent leaks in one day ⇒ treat as **systemic**, not incidental.

---

## 2. Findings — pre-formatted for `experiment_runs`

Columns per existing schema: `run_id, ts, kind, hypothesis, universe, verdict, sharpe, ic, dsr,
corr_to_book, max_dd_pct, total_return_pct, n_obs, cost_bps, window, params, notes, ledger_ref`.
`sharpe` field reused for the primary t-stat where a Sharpe is not the natural statistic — noted in
`notes` each time. **Minimax: confirm target table/mapping before insert; do not guess column types.**

| run_id | kind | hypothesis | verdict | stat | n_obs | window | ledger_ref |
|---|---|---|---|---|---|---|---|
| `2026-07-21_signal_audit_raw` | audit | Live signal book is cross-sectionally predictive (raw alpha) | REFUTED (later overturned) | OUTPERFORM t=−4.09 | 7743 | 2025-05-03→2026-05-03 | R61 |
| `2026-07-21_signal_audit_beta_adj` | audit | Same, with PIT-safe per-asset β adjustment | **CONFIRMED** | OUTPERFORM t=+5.75; STRONG OUTPERFORM t=+5.41; UNDERPERFORM t=+4.48 | 6311 | same | R62 |
| `2026-07-21_underweight_defect` | audit | UNDERWEIGHT signal is predictive | **REFUTED** | t=−3.79 | 281 | same | R62 |
| `2026-07-21_pillar_levels_beta_adj` | factor | CIS pillar levels predict β-adj edge | CONFIRMED | spreads: A +4.48, F +3.28, CIS +2.85, M +2.74, O +1.20, S +0.03 | 6311 | same | R62 |
| `2026-07-21_pillar_S_risk_factor` | factor | S is a RISK factor not a return factor | **CONFIRMED** | mean flat; vol 15.89→17.17; p10 −13.93→−18.33 | 6069 | same | R63 |
| `2026-07-21_pillar_delta_map` | factor | Information is in CHANGES not levels for fast pillars | CONFIRMED (specific) | stability premium: ΔS +2.72, ΔO +2.70; directional ΔA +1.18; ΔF/ΔM ≈0 | ~5990 | same | R63b |
| `2026-07-21_weekly_core` | strategy | Weekly K sees major-trend structure daily misses | CONFIRMED (as mode-selector) | weekly20/50 flips 1.3/yr vs daily 2.2; engagement 28.9% vs V5c 2.7% in dead zone; standalone SR 0.64 < V5c 0.89 | 467w/3000d | 2017-08→2026-07 | — |
| `2026-07-21_liquidity_gate` | strategy | Marginal stablecoin liquidity Δ gates crypto beta | **CONFIRMED** | SR +0.83, ann +35.4%, DD −56.5% vs buy-hold SR +0.64, +22.3%, −75.2% | 451w | 2017-12→2026-07 | — |
| `2026-07-21_resonance` | strategy | liquidity Δ × risk-appetite Δ resonance (both+) beats either | **REFUTED as specified** | resonance SR +0.07 vs liquidity-alone +0.83; best state is divergent liq+/risk− (+5.62% fwd 4w) | 443w | same | — |
| `2026-07-21_rds_proto` | strategy | Smoothed continuous multi-factor risk-direction gate avoids binary whipsaw | PARTIAL (construction validated) | SR +0.44 both halves positive; best calib thr0.60/cap0.4 SR +0.46 DD −29.6% | 4000×4h | ~2.7y | R50* |
| `2026-07-21_v9_capacity` | audit | V9 Sharpe ~5 is real but capacity-bounded | CONFIRMED (both halves) | ann 32.4%, implied vol 6.4%, time-in-mkt ~10%; $30M ⇒ $6–9M per 15m clip; drag 17.25%/yr vs 32.4%/yr | 1398 trades | 2.54y | — |

\* R50 numbering was overwritten by a Mac-side ledger rewrite during the session — see §5.

---

## 3. Decisions taken

1. **Unify the production alpha metric onto the β-adjusted, PIT-safe definition.** Every published
   alpha number is suspect until this lands. Publish raw AND β-adjusted, labelled — the adjusted
   figure requires *hedging* to capture; unhedged investors experience the raw number.
2. **CIS v5 is an ARCHITECTURE change, not a reweight.** The pillars are three different kinds of
   object: level-only (F, M), directional-change (A), fast-state/stability-premium + risk-gate (S, O).
   A single weighted sum of levels cannot express this.
3. **Corrects the pending R46 action item** ("reweight toward O, away from S"): away-from-S is *wrong
   as stated* — S is a risk gate, not dead weight. Toward-O is right (R46 t=+3.33) but needs
   regime-conditioning + higher sampling frequency. **pillar_A is the strongest untested candidate**
   (+4.48 level, +1.18 change) — never run at strategy level; queue the L/S test.
4. **Raise sampling frequency for S and O specifically** — their stability premium indicates we sample
   *after* the market reprices. Route: related-instrument price action (Jazz's AI-ETF analogy).
5. **Validity vs durability split** (now in `MECHANISM_SPEC.md` §3): binary/permanent kill for
   leakage + cost-infeasibility; dimensional/never-binary for regime fit, decay, crowding.
6. **Hold the strategy library statically; do not build a rotation overlay.** R20 already refuted
   regime-rotation (0.29 OOS vs 0.78 static). Regime info → risk sizing only, never alpha rotation.
7. **Run `pit_guard` on every detector**, not just LLM features.

---

## 4. Shipped

- `src/data/signals/two_layer_paper.py` — §5b two-layer paper book LIVE. Core-health gate holds
  **zero size** while the core is dead and records the flat honestly (starts the forward-OOS clock
  R57 flagged as missing). Hot-swappable core via Redis `two_layer_paper:core`. 7/7 smoke tests,
  preflight PASSED. Supabase `two_layer_paper_nav` created + RLS policies applied.
- `docs/MECHANISM_SPEC.md` — A2A capital-market mechanics (forward commitment / binding capacity /
  lifecycle disclosure; strategy-vector schema; honesty as dominant strategy).
- `MINIMAX_SYNC.md` — §ALTITUDE, §PIT-LEAK-C (P0), §CORE-BAKEOFF.
- `REFUTATION_LEDGER.md` R61/R62/R63/R63b · `WEEKLY_REVIEW.md` 2026-07-21 · `PROJECT_STATE.md`.

---

## 5. ⚠️ Coordination hazard observed

The `REFUTATION_LEDGER.md` was **rewritten Mac-side mid-session**, overwriting sandbox-written
entries (an earlier R50 and the §5b entry) and taking R59/R60 for Minimax entries. Subsequent entries
were appended at EOF to avoid further collision, hence R61–R63b.

**Recommended protocol:** ledger entries are **append-only at EOF**, and R-numbers are claimed by
appending before writing the body. Concurrent rewrite of the whole file loses work silently.

---

## 6. Open / next

- Fix UNDERWEIGHT (t=−3.79) — only genuinely broken signal
- Hourly S/O sampling via related-instrument price action
- pillar_A long/short test at strategy level
- Lead-lag study: liquidity Δ vs risk-appetite Δ phase offset (1–8 week lags), with a better
  risk-appetite proxy than alt/BTC (funding Δ, OI Δ, ETF flows, DXY)
- Strategy vector embedder + re-embed the graveyard (tasks #35/#36, not started)
- V9 4h→15m merge leak test (shift informative series one full period, re-run)
