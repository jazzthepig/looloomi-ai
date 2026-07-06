# Research Proposal — CIS × Macro Regime Interaction (AQR / Millennium Standards)

**Author:** Seth (Austin), 2026-07-06
**Lane:** `src/research/cis_regime_studies/` (new package, joint with Minimax-A's data)
**Trigger:** Nautilus LS v1 +$328.83 OOS but the gate (`REGIME_CIS_FLOOR`) is **hand-tuned** — no empirical calibration. Jazz: "继续就cis评分和regime 交互做进一步研究，用aqr和millennium的标准".
**Status:** 🟡 proposed — awaiting Jazz priority call (see §0)

---

## 0. TL;DR — five testable hypotheses, three tiers

The five hypotheses cover both AQR's **factor-time-discipline** lens and Millennium's
**alpha-diversification + sizing** lens. Tiers reflect implementation cost.

| # | Hypothesis | Standard | Tier | Effort |
|---|-----------|----------|------|--------|
| **H1** | CIS information coefficient (IC) differs materially by regime — and the floor values match (or don't) | **AQR** | T1 | 1 session |
| **H2** | The hand-tuned `REGIME_CIS_FLOOR` is sub-optimal vs a percentile-calibrated floor | **AQR** | T1 | 1 session |
| **H3** | Replacing the hard CIS gate with a continuous conviction-scaled entry (Millennium-style "soft alpha") improves risk-adjusted returns | **Millennium** | T2 | 2 sessions |
| **H4** | Regime transitions produce a vintage effect — first 5 days post-transition is a different distribution | **AQR** | T2 | 2 sessions |
| **H5** | Combining CIS with one orthogonal signal (funding rate, 30d momentum) within each regime diversifies the alpha | **Millennium** | T3 | 3-4 sessions |

**Default execution order (if Jazz wants me to pick):** H1 → H2 → H3 → H4 → H5.
H1+H2 are pure data analysis on the 393-day CIS history + OHLCV (no Nautilus
changes), so they can land fast and inform whether the deeper H3/H4/H5 work
is worth doing. T2/T3 are Nautilus-backtest-driven.

---

## 1. Background — what's already in place (so we don't rebuild)

**Recon 2026-07-06 confirms substantial infrastructure already exists** — the
integration is what's missing.

| Component | Status | Path |
|---|---|---|
| CIS daily history (5 pillars × 84 assets) | ✅ 393 days | `cis_history/cis_YYYY-MM-DD.json` (Shadow mirror) |
| Supabase long-form `cis_scores` | ✅ connected | includes `regime_transition` + `previous_regime` |
| OHLCV (crypto, 52 assets) | ✅ parquets | `/Volumes/CometCloudAI/data/ohlcv/` |
| Regime attribution tool (Sharpe by regime, dependency entropy) | ✅ built | `src/research/regime_attribution.py` |
| Regime-fitness IC table (Pearson IC per pillar × regime) | ✅ built | `scripts/compute_regime_fitness.py` → Supabase `cis_regime_fitness` |
| Regime smoother (window-stability conviction) | ✅ built | `scripts/regime_smoother.py` |
| Walk-forward harness | ✅ built | `src/research/walk_forward.py` |
| Multiple-testing discipline (HOLM) | ✅ built | `src/research/multiple_testing.py` |
| Recent regime-segmented backtest | ⚠️ partial | `reports/ls_v4_2026-06-30.md` — only 4 of 6 regimes in OOS window |

**Critical gap:** no one has **run** the joint analysis. The Simons-style
feedback loop is wired but dormant. Most recent backtest (`ls_v4_2026-06-30.md`)
showed only 4 of 6 regimes (no EASING / STAGFLATION in window — a sample-size
hole for any regime-conditional study). Floor values are **hand-picked**, not
empirically derived.

**Current regime interaction (from `CometCloudLongShortV4.py` + Nautilus LS v1):**

```python
REGIME_CIS_FLOOR = {        # long side — high CIS required
    "Tightening": 52, "Risk-Off": 50, "Stagflation": 50,
    "Neutral": 58, "Easing": 62, "Risk-On": 65, "Goldilocks": 65,
}
# plus REGIME_SIDE_RULES grade allowlist per (regime, side)
# plus REGIME_WEIGHT_ADJUSTMENTS in cis_v4_engine.py (pillar reweighting per regime)
```

Three coupled controls. **The interaction is what's interesting** — none of
the three is empirically calibrated, and they may contradict each other.

---

## 2. Hypothesis 1 — Regime-Conditional IC (AQR)

> **Claim:** The CIS forward-return IC is materially different across regimes,
> and the hand-tuned `REGIME_CIS_FLOOR` values are *directionally* right but
> poorly calibrated.

**AQR reference:** Asness/Frazzini/Israel "Factor Timing" (2017), Ilmanen
"Expected Returns" Ch. 11 on regime-conditional factor premiums.

**Test:**
1. For each (pillar × asset × day), pair `cis_score_t` with `fwd_return_{t+7d}` and
   `fwd_return_{t+30d}` from `data/ohlcv/`.
2. Compute Pearson IC and Spearman rank IC overall.
3. Compute IC broken down by `macro_regime` and `regime_transition` buckets.
4. Apply **HOLM correction** for multiple testing (6 regimes × 5 pillars × 2 horizons = 60 tests).
5. Quantile spread: top-quintile vs bottom-quintile CIS fwd returns per regime.

**Decision rule:**
- ACCEPT if at least 3 of 6 regimes show significant IC (|t-stat| > 2) and the
  spread between best-IC regime and worst-IC regime is > 2× in absolute IC.
- REJECT otherwise — implies regime conditioning has limited signal.

**Output:** `reports/cis_regime_ic_2026-07-06.md` + JSON results
(`cis_regime_ic.json` written to Supabase `cis_regime_fitness` upsert).

**Effort:** 1 session. Pure data analysis, no Nautilus changes.

---

## 3. Hypothesis 2 — Empirical Floor Calibration (AQR)

> **Claim:** `REGIME_CIS_FLOOR` values are sub-optimal. A percentile-based
> floor (e.g. require CIS in the top-30% of its regime-specific historical
> distribution) yields higher OOS Sharpe than the hand-tuned table.

**AQR reference:** Frazzini/Israel/Moskowitz "Trading Costs of Factor Investing"
(2018) — tighter filters don't always beat looser ones after costs.

**Test:**
1. Compute per-regime historical CIS distribution from the 393-day history.
2. For each candidate floor (5 percentile cuts: 30%, 40%, 50%, 60%, 70%, 80%):
   - Walk-forward split: IS = first 70% of days, OOS = last 30%.
   - Re-run Nautilus LS v1 with the candidate floor (env-overridable).
   - Compute OOS Sharpe, Sortino, max DD.
3. Compare each candidate to the hand-tuned baseline (52/50/50/58/62/65/65).
4. **Multiple-testing note:** 6 candidates × 6 regimes = 36 tests → apply
   Romano-Wolf or HOLM step-down correction.

**Decision rule:**
- ACCEPT if best calibrated floor improves OOS Sharpe by ≥ 10% vs baseline
  AND survives multiple-testing correction.
- REJECT otherwise → keep hand-tuned floors (and document why they're "OK").

**Output:** `reports/cis_floor_calibration_2026-07-06.md` + a
`RECOMMENDED_REGIME_CIS_FLOOR` JSON ready to drop into `strategy.py`.

**Effort:** 1 session. 6×6=36 Nautilus runs × ~0.5s each = ~20s of compute.

---

## 4. Hypothesis 3 — Continuous vs Hard Gate (Millennium)

> **Claim:** Replacing the binary CIS gate with a continuous conviction-scaled
> position size (Millennium-style "soft alpha") improves risk-adjusted returns
> by reducing turnover and avoiding cliff effects at the threshold.

**Millennium reference:** Multi-PM platform alpha is **soft** — conviction
scales entry size. Avoids the binary "in or out" cliff where a 49.9 → 50.1
CIS cross flips a 100% position to zero.

**Test (5 Nautilus variants):**
1. **Baseline** (current hard gate)
2. **Linear scaling**: weight = clamp((CIS − floor) / 20, 0, 1)
3. **Sigmoid scaling**: weight = 1 / (1 + exp(−(CIS − floor) / 5))
4. **Rank scaling**: weight = (rank − floor_rank) / (top − floor_rank), clipped [0,1]
5. **Vol-scaled rank**: weight = rank_weight × (1 / realised_vol_30d), normalised

All five run via `run_parity()` with `LSV1_GATE_MODE` env var
(`hard|linear|sigmoid|rank|vol_rank`). Same OOS window, same 3 instruments.

**Decision rule:**
- ACCEPT if any non-baseline variant achieves OOS Sharpe ≥ 15% better AND
  Calmar ≥ baseline AND turnover ≤ 1.5× baseline turnover.
- REJECT otherwise → hard gate is fine.

**Output:** `reports/cis_gate_variant_2026-07-06.md` + Nautilus code change
to `strategy.py` (config switch).

**Effort:** 2 sessions (1 to add gate_mode config + 5 backtest variants, 1 to
analyse). This is a strategy logic change — Seth owns the merge; Jazz signs off.

---

## 5. Hypothesis 4 — Regime Transition Vintage (AQR)

> **Claim:** The first N days after a regime transition is a different
> statistical regime (the "vintage effect") — factor premiums lag, volatility
> is elevated, and the floor values should be tighter during this window.

**AQR reference:** Ilmanen Ch. 11 on regime persistence; Kritzman et al.
"Regime Shifts" (2012) — transition periods have higher vol and lower
Sharpe across most factors.

**Test:**
1. Use Supabase `cis_scores.regime_transition` column to identify
   transition days.
2. Bucket observations by `days_since_transition` ∈ {0-2, 3-7, 8-21, 22+}.
3. Compute per-bucket: IC, vol, turnover, hit rate, P&L.
4. If H4 holds, recommend a **transition penalty** — tighten floor by Δ during
   the first 7 days of a new regime.

**Decision rule:**
- ACCEPT if transition bucket (0-7 days) shows ≥ 30% lower Sharpe than stable
  bucket (22+ days) AND penalty application improves OOS Sharpe.
- REJECT otherwise → regime-conditioning-by-current-regime is sufficient.

**Output:** `reports/regime_transition_vintage_2026-07-06.md`.

**Effort:** 2 sessions. Requires Supabase query + walk-forward validation.

---

## 6. Hypothesis 5 — Signal Diversification per Regime (Millennium)

> **Claim:** Adding one orthogonal signal (funding rate OR 30d momentum)
> combined with CIS per-regime diversifies the alpha — reduces drawdown
> without sacrificing return.

**Millennium reference:** Multi-PM platform diversifies across many
uncorrelated alphas; per-alpha Sharpe matters less than **portfolio Sharpe
of uncorrelated streams**. We have one alpha (CIS); adding a second
orthogonal one is the closest we can get in this scope.

**Test:**
1. Compute funding rate signal (already in freqtrade `-1h-funding_rate.feather`)
   and 30d momentum signal (from OHLCV) for the 3 LS V1 pairs.
2. Per-regime: combine CIS with funding + momentum via:
   - Equal-weight composite score
   - Inverse-vol weighted (Millennium-style)
   - Regime-conditional weights (e.g. in RISK_OFF, weight momentum more)
3. Backtest 3 Nautilus variants and compare to CIS-only baseline.

**Decision rule:**
- ACCEPT if combined-signal variant improves OOS Sharpe by ≥ 20% AND
  correlation between the two alphas is < 0.5 (i.e. they actually add
  diversification, not double-count).
- REJECT otherwise → single CIS alpha is the right scope.

**Output:** `reports/cis_signal_diversification_2026-07-06.md`.

**Effort:** 3-4 sessions. New signal ingestion + Nautilus strategy extension.
This is a **Minimax-A coordinated** task (funding rate data lives on Mac Mini).

---

## 7. Cross-cutting methodology — AQR / Millennium standards checklist

| Discipline | Standard | How we apply it |
|---|---|---|
| **Out-of-sample validation** | AQR | Walk-forward with embargo; IS=70%, OOS=30%, never look at OOS during tuning |
| **Multiple testing** | AQR | HOLM step-down + Romano-Wolf for any sweep > 5 tests |
| **Information Coefficient** | AQR | Pearson + Spearman, reported with t-stats; not just hit rate |
| **Quantile spreads** | AQR | Top-q vs bottom-q fwd returns per regime |
| **Capacity / liquidity** | Millennium | Avg daily $ volume ÷ position notional; reject signals below 5× capacity |
| **Turnover penalty** | Millennium | Net turnover per rebalance; reject variants > 1.5× baseline |
| **Drawdown control** | Millennium | Calmar ratio + max DD days, not just Sharpe |
| **Short-horizon decay** | Millennium | 7d / 30d / 90d fwd return horizons; flag signals that decay in < 5d |
| **Sample-size honesty** | AQR | Per-regime n must be ≥ 30 trades to draw a conclusion; otherwise report "underpowered" |
| **Transaction cost** | AQR | Apply 5 bps slippage + 2 bps fees per side in OOS; report net Sharpe |

---

## 8. Deliverables (final shape)

```
docs/
  RESEARCH_CIS_REGIME_INTERACTION_2026-07-06.md          # this file

src/research/cis_regime_studies/                         # new package
  __init__.py
  h1_regime_ic.py                  # IC + Spearman + quantile spreads per regime
  h2_floor_calibration.py          # walk-forward percentile floor sweep
  h3_continuous_gate.py            # 5 Nautilus gate-mode variants
  h4_transition_vintage.py         # per-vintage bucket study
  h5_signal_diversification.py     # CIS + funding + momentum combo
  common/
    data_loader.py                 # loads CIS history + OHLCV into a unified DataFrame
    regime_history.py              # extracts regime time-series from cis_history/
    metrics.py                     # Sharpe / Sortino / Calmar / IC helpers
    nautilus_runner.py             # thin wrapper over runner.run_parity for variants

reports/
  cis_regime_ic_2026-07-06.md
  cis_floor_calibration_2026-07-06.md
  cis_gate_variant_2026-07-06.md       # if H3 runs
  regime_transition_vintage_2026-07-06.md
  cis_signal_diversification_2026-07-06.md

MINIMAX_SYNC.md                            # updated with research status
```

---

## 9. Dependencies & coordination

- **Data sources:** all read-only — `cis_history/` JSONs (Shadow mirror),
  `data/ohlcv/` parquets (Shadow mirror), Supabase `cis_scores` (Seth's).
- **Minimax-A coordination:** needed only for H5 (funding rate data lives
  on Mac Mini; Seth reads via Shadow mirror).
- **No data writes to Mac Mini** — all analysis lands in Seth's `src/research/`
  and `reports/`.
- **Push gate:** this is a research deliverable, not a deployable feature —
  per CLAUDE.md "Jazz verbal OK" not required for analysis-only work.

---

## 10. What this is NOT

- **Not a re-scoring of the CIS algorithm** (that's Minimax-A's lane; §GRADE-ALIGN
  is still in flight with bigger reconciliation findings from 2026-07-01).
- **Not a Nautilus live-trading change** — only paper/backtest until Jazz signs off.
- **Not a UI change** — research outputs land as `reports/*.md` and
  `cis_regime_fitness` Supabase rows; no dashboard wiring this round.