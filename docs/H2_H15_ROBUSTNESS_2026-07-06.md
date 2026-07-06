# H2 H1.5 — Regime-Smoother Robustness Check (B.8)

**Author:** Seth / Austin · 2026-07-06 · **Status:** ✅ COMPLETE — Phase 1
(Easing drop) ship recommendation WITHDRAWN; revised path in
`docs/H2_PHASE1_EASING_DROP_2026-07-06.md` §6.
**Builds on:** `docs/H2_REGIME_GATE_DESIGN_2026-07-06.md` (H2 design) ·
Phase 0 modal-window smoother (`scripts/regime_smoother.py` shipped in B.5) ·
H1 raw (`reports/cis_regime_ic_2026-07-05.md`) · H2a relative
(`reports/cis_regime_relative_ic_2026-07-06.md`).

---

## 0. TL;DR

Phase 0 (B.5) replaced the noisy 4-day median regime detector with a
modal-window smoother (median regime length 4.0d → 29.5d, runs 44 → 12).
**H1.5 asks: does the smoothed-H1 conclusion (negative IC in Risk-Off /
Risk-On / Stagflation, flat in Easing) survive different smoother
algorithm choices, or is it an artifact of "modal-recency tie-break"?**

Answer: **the negative IC finding is robust across algorithms, but
"Easing flat" was a 4-day-detector artifact.** All three alternative
smoothers flip Easing to negative IC, and two of three flip it to
"genuine reversal" (relative returns MORE negative than absolute, same
as Risk-Off / Risk-On).

The Phase 1 ship recommendation (drop Easing floor to eligibility-only)
is **WITHDRAWN**. Revised recommendation: keep all `REGIME_CIS_FLOOR`
values; swap the production gate's regime-label source from raw to
smoothed (`cis_history_smoothed/`) so the gate at least tracks a
trustworthy regime context. Magnitude tuning comes in Phase 2.

---

## 1. Three smoothers, one question

The Phase 0 default is **modal-recency**: modal regime over the prior
14 days, tie-broken by most-recent occurrence. H1.5 adds two orthogonal
alternatives in `scripts/regime_smoother.py`:

| Algorithm | Selector | Tie-break | Median regime length |
|---|---|---|---:|
| **raw** (no smoother, baseline) | — | — | 4.0 days |
| **modal_recency** (Phase 0 default) | modal over [d-13, d] | most recent occurrence wins | 29.5 days |
| **modal_majority** | modal over [d-13, d] | first-seen occurrence wins (longest-running regime on ties) | 10.0 days |
| **persistence** | hard min-run-length: new regime must hold N consecutive days to flip | n/a (no modal) | 74.0 days |

All three smoothers are implemented in `scripts/regime_smoother.py` and
selectable via `--smoother {modal_recency,modal_majority,persistence}`.
Each produces a parallel `_data/cis_history_smoothed*/` dir with the
same JSON shape and provenance fields (`macro_regime_raw`,
`macro_regime`, `smoother_algorithm`, `smoother_window_days`,
`smoother_params`).

---

## 2. H1-on-each-smoother — the comparison

H1 (composite CIS, 7d forward-return IC) re-run on each smoothed label
set, n=12,059 obs × 40 assets, unchanged. **Relative-returns column is
the H2a verdict for "BETA artifact vs genuine reversal"**.

| Regime | raw | modal_recency | modal_majority | persistence-14d |
|---|---:|---:|---:|---:|
| **Risk-Off** abs | −0.0925 | **−0.1349** | **−0.1361** | **−0.1334** |
| **Risk-Off** rel | −0.104 | −0.115 | −0.118 | −0.054 |
| | | | | |
| **Easing** abs | **+0.0293** | **−0.1288** | **−0.1252** | **−0.0361** |
| **Easing** rel | +0.016 | **−0.144** | **−0.143** | −0.088 |
| | | | | |
| **Risk-On** abs | −0.1661 | **−0.3577** | **−0.2974** | −0.0922 |
| **Risk-On** rel | −0.101 | −0.287 | −0.229 | −0.099 |
| | | | | |
| **Tightening** abs | +0.1681 | −0.0932 | −0.0932 | absorbed into Risk-Off |
| **Stagflation** abs | −0.2346 | absorbed into Easing | absorbed into Easing | absorbed into Risk-Off/Easing |

(regime cells absorbed when the smoother merges them into other labels;
not a "true zero" — just fewer than 30 obs at the regime-gate level.)

**n per regime per smoother:**

| Regime | raw | modal_recency | modal_majority | persistence-14d |
|---|---:|---:|---:|---:|
| Risk-Off | 5578 | 5776 | 5809 | 5609 |
| Easing | 4304 | 4932 | 4867 | 5039 |
| Risk-On | 1766 | 1279 | 1311 | 1411 |
| Tightening | 216 | 72 | 72 | absorbed |
| Stagflation | 195 | absorbed | absorbed | absorbed |

---

## 3. The headline finding: Easing was an artifact

**Easing 7d IC flips sign under smoothing.** Raw: +0.029 (flat). Modal
variants: −0.13 abs, −0.14 rel — same magnitude as Risk-Off / Risk-On.

The modal_rel column for Easing is **MORE negative than the abs column**
(−0.144 rel vs −0.129 abs, modal_recency). That's the H2a "genuine
reversal (persists)" verdict — high-CIS names underperform MORE on a
benchmark-relative basis in Easing than in absolute terms. Same pattern
as Risk-On and Risk-Off. Not a beta-timing artifact; a real ranking
signal (just negative).

The 30d cross-check (raw detector) was already showing −0.154 abs /
−0.209 rel in Easing. The 30d signal was correct. The 7d smoothed
signal is correct. The 7d raw signal was the artifact.

**Why did raw detector show Easing as flat?** Median regime length 4
days means the "Easing" label flipped on and off rapidly during real
Easing stretches, mixing in Risk-Off / Risk-On days. The IC was being
computed across a mix of negative-IC and "supposed-to-be Easing" days
— the net effect averaged toward zero. Smoothing stops the
4-day-on/4-day-off thrash and gives a stable Easing sample.

---

## 4. Risk-On — robust but variable

| Smoother | Risk-On \|IC\| | n |
|---|---:|---:|
| raw | 0.166 | 1766 |
| modal_recency | **0.358** | 1279 |
| modal_majority | **0.297** | 1311 |
| persistence | 0.092 | 1411 |

Risk-On's negative IC is robust to smoothing, but magnitude varies
(0.09 → 0.36). The modal variants strengthen it because they pull
out cleaner Risk-On stretches (the raw detector's 4-day thrash was
also polluting Risk-On). Persistence weakens it because some Risk-On
days get absorbed into adjacent Risk-Off runs (with 5 regime changes
in 393 days, Risk-On is mostly a small patch inside Risk-Off).

**Ship implication:** Risk-On's negative IC is real, but the magnitude
question (does it persist in production?) is open. Phase 2 magnitude
backtest answers this.

---

## 5. Risk-Off — strongest negative IC, robust to everything

| Smoother | Risk-Off \|IC\| abs | rel |
|---|---:|---:|
| raw | 0.092 | 0.104 |
| modal_recency | **0.135** | 0.115 |
| modal_majority | **0.136** | 0.118 |
| persistence | **0.133** | 0.054 |

Risk-Off is the most robust finding: |IC| > 0.13 on every smoother, abs
and rel both negative, n>5500 everywhere. **This is the safest signal to
act on if we act on any.** Phase 2 magnitude backtest should focus here
first.

---

## 6. Stagflation / Tightening — underpowered; absorbed under smoothing

| Regime | raw n | smoothed n (modal_recency) | smoothed n (persistence) |
|---|---:|---:|---:|
| Stagflation | 195 | absorbed (0) | absorbed (0) |
| Tightening | 216 | 72 | absorbed (0) |

The smoother absorbs the small-sample regimes into their neighbors,
which is the right thing to do — we shouldn't trust 195 obs to define
a regime. These regimes should remain "use the prior floor" until they
re-accumulate sample.

For Tightening: the raw +0.17 (n=216) finding might be real but it's
not robust to smoothing. Don't act on direction; treat as "use prior
floor" with a watch flag in Phase 3.

---

## 7. The decision tree (revised)

```
Phase 0 (regime smoother)             [shipped B.5]
   ↓
Phase 0.5 (H1.5 robustness check)     [shipped B.8 ← this doc]
   ↓
   ├─ Easing "drop floor" candidate   [WITHDRAWN — Easing IC is negative under smoothing]
   ├─ Risk-Off / Risk-On negative IC  [CONFIRMED robust across 3 smoothers]
   └─ Smoothed regime label adoption  [Phase 1 — gate reads from cis_history_smoothed/]
   ↓
Phase 2 (regime-conditional magnitude backtest, smoothed labels)
   ↓
Phase 3 (per-regime magnitude flip where OOS Sharpe improves ≥10% net of costs)
```

**The immediate next step is small and safe:** swap the production
gate's regime-label source from `cis_history/` (raw 4-day detector)
to `cis_history_smoothed/` (modal-14d, median 29.5d). No floor values
change. No direction changes. The gate at least tracks a trustworthy
regime context.

This is the revised Phase 1; see
`docs/H2_PHASE1_EASING_DROP_2026-07-06.md` §6 for details and Seth's
production change spec.

---

## 8. What this is NOT

- **Not a verdict that "CIS is broken."** The H2 reframe (CIS = ranking
  signal, regime = beta timing) is unchanged. What changed is: under a
  trustworthy regime label set, the ranking signal in 4 of 4
  non-Tightening regimes is NEGATIVE. That IS a real ranking signal —
  just pointing the opposite direction of what the current gate assumes.
- **Not a Phase 2 magnitude answer.** This doc confirms the direction
  question; the magnitude question (how strong is the in-production
  effect, after costs, after turnover?) is separate and deferred.
- **Not a "don't ship anything" conclusion.** Phase 1 (revised) is ship-
  ready: swap label source, keep floors. That's a low-risk, high-data-
  trust gain.

---

## 9. Citations

- **H1 raw**: `reports/cis_regime_ic_2026-07-05.md` + `.json` (composite
  CIS, 7d Pearson + Spearman IC tables by regime).
- **H2a raw**: `reports/cis_regime_relative_ic_2026-07-06.md` + `.json`
  (re-runs H1 on `return − BTC/SPY`; 0 BETA artifacts, 3 genuine
  reversals in raw detector).
- **Phase 0 smoother**: `scripts/regime_smoother.py:smoothed_regime_series()`
  + `relabel_cis_history()` (modal-recency default, `--smoother
  modal_recency` on CLI).
- **H1.5 smoothers**: `scripts/regime_smoother.py:smoothed_regime_majority()`
  + `smoothed_regime_persistence()` (added 2026-07-06). Selectable via
  `--smoother {modal_majority,persistence}`.
- **Smoothed label sets**:
  - `cis_history_smoothed/` (modal_recency, 14d window)
  - `cis_history_smoothed_majority/` (modal_majority, 14d window)
  - `cis_history_smoothed_persistence/` (persistence, min 14d)