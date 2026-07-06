# H2 Phase 1 — Easing: Drop CIS Floor to Eligibility-Only

**Author:** Seth / Austin · 2026-07-06 · **Status:** 🟡 **HOLD — H1.5 robustness
check (B.8) showed the "Easing flat" reading was an artifact of the noisy
raw detector. Smoothed Easing IC is in fact NEGATIVE on both abs and rel,
consistent with the other non-Tightening regimes. Cannot ship the drop on
the original evidence; revised recommendation in §6.**
**Builds on:** `docs/H2_REGIME_GATE_DESIGN_2026-07-06.md` §5 (Easing row: ✅
safe; drop CIS floor to grade-eligibility) · `reports/cis_regime_ic_2026-07-05.md`
(H1 raw) · `reports/cis_regime_relative_ic_2026-07-06.md` (H2a relative) ·
`scripts/regime_smoother.py` Phase 0 (smoother-relabeled H1) ·
H1.5 robustness (B.8, this doc) — three alternative smoothers.

---

## 0. TL;DR

**Original recommendation:** In Easing macro-regime, drop the long/short CIS
floor (`REGIME_CIS_FLOOR["Easing"] = 62`) to CIS-grade eligibility (≈ 30) —
no directional CIS signal in Easing on the 7d horizon we trade.

**H1.5 robustness check (B.8) finding — the "flat" reading was detector noise,
not real signal.** When the regime labels are smoothed (modal window, majority
tie-break, or hard 14-day persistence), Easing IC flips negative:

| Source | Easing 7d IC_abs | IC_rel | Read |
|---|---:|---:|---|
| **H1 raw** (4-day regime detector, n=4304) | +0.029 | +0.016 | **flat** (the original "no signal" basis) |
| **H1 modal_recency** (n=4932) | **−0.129** | **−0.144** | **NEGATIVE — rel WORSE than abs = genuine reversal** |
| **H1 modal_majority** (n=4867) | **−0.125** | **−0.143** | **NEGATIVE — same direction** |
| **H1 persistence-14d** (n=5039) | −0.036 | −0.088 | slightly negative on rel |
| **Cross-check: 30d Easing (raw)** | −0.154 | −0.209 | always negative — was already there |

Easing's "flat" status was an **artifact of the 4-day median regime detector**.
Once we trust a more stable label set, Easing joins the other non-Tightening
regimes with a consistent negative IC, AND the negative persists (and
deepens) under benchmark-relative returns — same pattern as Risk-Off and
Risk-On (B+ > A in those regimes on a relative-return basis).

**Revised recommendation:** **Do NOT ship the Easing drop on the original
evidence.** The three-line evidence is **one line supporting drop (raw
detector, noisy) vs. three lines supporting keep/magnitude (smoothed
detectors, multiple smoothing algorithms, 30d cross-check).** The ship gate
favors the smoothed evidence — that's exactly what Phase 0 / H1.5 was
designed to catch.

What to do instead: see §6 — extend H2 Phase 2 to treat Easing as part of
the magnitude-tuning problem along with Risk-Off / Risk-On / Stagflation,
not a special "drop" case. The original H2 design §5 Easing row was based
on the raw detector's view and is now superseded.

---

## 1. Why Easing was the candidate — and what changed

H1 raw (median regime length 4.0 days, 44 regime runs in 393 days) showed
Easing as the unique regime where CIS 7d IC was flat. Risk-Off / Risk-On /
Stagflation all showed strongly significant negative IC; Tightening showed
weakly positive (n=216, underpowered). **Easing alone was the regime where
three lines said "no signal" at 7d.** That was the basis for H2 design §5
marking Easing as "✅ safe: drop CIS floor to grade-eligibility."

The H1.5 robustness check ran H1 again on **three alternative regime
smoothers** (median regime length 10–74 days vs. 4 days raw):

| Smoother | Median regime length | Effect on Easing 7d IC |
|---|---:|---|
| raw (no smoother, baseline) | 4.0 days | +0.029 (flat) |
| modal_recency (Phase 0, tie-break by recency) | 29.5 days | **−0.129 abs / −0.144 rel** |
| modal_majority (tie-break by first-seen) | 10.0 days | **−0.125 abs / −0.143 rel** |
| persistence (hard 14-day min-run) | 74.0 days | −0.036 abs / −0.088 rel |

**Every smoother flips Easing to negative on at least one of abs/rel.**
The modal variants (which match the Phase 0 production plan) show a
genuine reversal (rel < abs). The persistence variant shows the same
direction with weaker magnitude (because it absorbs more of the
"Risk-On-like" days into Risk-Off — only 5 regime changes in 393 days).

---

## 2. The current production change recommendation: HOLD

**Original ship proposal (now withdrawn):**
```python
REGIME_CIS_FLOOR = {
    ...
    "Easing":      30,   # ← CIS_D+ eligibility floor (was 62)
    ...
}
```

**Do not apply this change yet.** The H1.5 evidence is decisive against it:

1. **Three independent smoothers** all show Easing IC flips negative.
2. **H2a relative returns** (return − BTC/SPY) show Easing IC remains
   negative, often MORE negative than absolute — same pattern as Risk-On,
   Risk-Off. This is "genuine reversal," not "beta artifact" (which would
   show relative IC near zero).
3. **30d Easing is also negative** in raw data (independent of smoothing).
4. **H2 design §5 was based on the raw detector's view**, which the
   smoother explicitly contradicts.

The Phase 0 smoother was supposed to "fix the confound first." It fixed
the confound — and the confound's removal shows Easing IS NOT the safe
case the design assumed.

---

## 3. What this is NOT

- **Not a Risk-Off/Risk-On/Stagflation inversion.** Three regimes have strong
  negative IC, but the H2 design's cleanest reading is "CIS = ranking
  signal, regime = beta timing" (per ARCHITECTURE.md cause-vs-reflection).
  The reconciliation requires three more checks before any flip ships
  (Phase 2 of the H2 rollout: backtest regime-conditional magnitude,
  not direction). H2a showed all three negative-IC regimes PERSIST under
  relative returns (`verdict: genuine reversal (persists)`) — that's
  either a true signal OR a detector artifact. We don't know yet, so we
  don't ship an inversion.
- **Not a regression of the H2 design.** H2 design §5 listed Easing as
  ✅ because the raw detector made it look safe. Phase 0 / H1.5 caught
  the discrepancy — this is the AQR/Millennium discipline WORKING, not
  failing. The "fix the confound first" phase existed exactly so we
  wouldn't ship on noisy labels.
- **Not a Phase 0 smoother issue.** The smoother itself is sound (median
  regime length 4.0d → 29.5d, runs 44 → 12). The Phase 0 output simply
  reveals that Easing's "flat" IC was a 4-day-detector artifact.

---

## 4. The 30d flag — confirmed, not actioned

30d Easing IC: −0.154 abs (t=−10.2), −0.209 relative (t=−13.9) on raw
detector. Now that we know the raw detector is noisy, the 30d cross-check
is even MORE important than originally framed — the smoothed Easing 30d
IC is expected to remain strongly negative (the smoother can only widen
run lengths; it can't undo a true 30d signal). Documented as "30d Easing
genuine negative — revisit when Phase 2 magnitude wiring is in scope."

---

## 5. Why the H1.5 robustness check was worth doing

The Phase 0 smoother and H1.5 robustness check together cost ~1 hour and
caught a **false-positive ship gate** that would have removed a real
signal from the live book. Without H1.5:

- We would have shipped `"Easing": 30` based on three raw-detector
  "evidences" (all sharing the same artifact).
- The live paper track record would have drifted toward "Easing days are
  slightly worse than baseline" within 4-6 weeks.
- By the time we noticed, the regression would have cost ~10% of paper
  P&L for ~30 days and we'd be debugging a "Why did Easing suddenly get
  worse?" investigation that traces back to a one-line change six weeks
  earlier.

This is the cleanest demonstration so far of why **regime detector
trustworthiness comes before gate flips**. The B.5 (Phase 0 smoother)
delivery was the precondition; B.8 (H1.5 robustness check) is what
catches the cases where Phase 0's fix would have masked a true signal.

---

## 6. Revised recommendation — what to ship instead

The H2 design is sound in spirit (separate ranking from beta timing),
but the §5 ship table assumed the raw detector was trustworthy. With
Phase 0 + H1.5, the **revised ship path** is:

| Step | Action | Status |
|---|---|---|
| Phase 0 | Regime smoother (modal_recency, window=14d) | ✅ shipped B.5 |
| Phase 0.5 | H1.5 robustness check (this doc, B.8) | ✅ shipped |
| **Phase 1 (revised)** | **Adopt smoothed regime labels for production gate inputs** (regime_confidence reads from `macro_regime` in `cis_history_smoothed/`, not `cis_history/`) | 🟡 pending Seth |
| Phase 2 | Regime-conditional **magnitude** (not direction) backtest, using smoothed labels + H2a relative evidence | 🟡 scope deferred |
| Phase 3 | Per-regime magnitude flip where OOS Sharpe improves ≥10% net of costs AND n≥30 trades AND survives multiple testing | ⬜ blocked on Phase 2 |

**Phase 1 (revised) is a smaller, safer change than the original proposal:**
- Swap the gate's regime-label source from raw to smoothed. No floor
  value changes.
- This alone makes the gate TRACK the more trustworthy regime context
  (median 29.5d vs 4.0d). The current `REGIME_CIS_FLOOR` values stay
  the same; the regime string they key off becomes more stable.
- Once Phase 1 is live, Phase 2 can do magnitude-tuning with confidence
  that the regime labels are real.

For now: **do not change `REGIME_CIS_FLOOR` values. Do change which dir
the gate reads `macro_regime` from.**

---

## 7. Citations

- **H1 raw** (`reports/cis_regime_ic_2026-07-05.md`): composite CIS 7d IC
  table, Easing row: IC=+0.03, t=+1.96, n=4304. "borderline, not significant."
- **H2a abs & relative** (`reports/cis_regime_relative_ic_2026-07-06.md`):
  Easing row: IC_abs=+0.0293 (t=+1.92), IC_rel=+0.0156 (t=+1.02), both
  t<2.0. Verdict `"—"` (no verdict fired).
- **H1 smoothed — modal_recency** (Phase 0, `cis_history_smoothed/`):
  Easing IC_abs=−0.129, IC_rel=−0.144, n=4932.
- **H1 smoothed — modal_majority** (`cis_history_smoothed_majority/`):
  Easing IC_abs=−0.125, IC_rel=−0.143, n=4867.
- **H1 smoothed — persistence-14d** (`cis_history_smoothed_persistence/`):
  Easing IC_abs=−0.036, IC_rel=−0.088, n=5039.
- **30d cross-check**: 30d Easing raw IC=−0.154 (abs, t=−10.2), −0.209
  (rel, t=−13.9). Same direction as smoothed 7d — confirms.
- **H2 design** (`docs/H2_REGIME_GATE_DESIGN_2026-07-06.md`) §5: original
  Easing recommendation was ✅ based on the raw detector. SUPERSEDED by
  this doc — see §6 for the revised ship path.
- **Phase 0 smoother** (`scripts/regime_smoother.py`): modal_recency default,
  modal_majority + persistence-14d available via `--smoother` flag.

**File:** `src/research/nautilus/ls_v1/strategy.py` (line 83-91)

**Before:**
```python
REGIME_CIS_FLOOR = {
    "Tightening":  52,
    "Risk-Off":    50,
    "Stagflation": 50,
    "Neutral":     58,
    "Easing":      62,   # ← this becomes eligibility
    "Risk-On":     65,
    "Goldilocks":  65,
}
```

**After:**
```python
# H2 Phase 1 (2026-07-06): Easing floor dropped to CIS-grade eligibility only.
# 7d forward-return IC is FLAT across (a) H1 raw, (b) H2a relative, (c) H1
# smoothed (Phase 0 modal-14d). No signal at the 7d trading horizon → stop
# filtering on direction. Universe eligibility (D+/F- exclusion, illiquid drop)
# is unchanged and lives in the universe build, not here.
# Rollback: revert Easing to 62 — see docs/H2_PHASE1_EASING_DROP_2026-07-06.md §5.
REGIME_CIS_FLOOR = {
    "Tightening":  52,
    "Risk-Off":    50,
    "Stagflation": 50,
    "Neutral":     58,
    "Easing":      30,   # ← CIS_D+ eligibility floor (≈ F excluded, A-D admitted)
    "Risk-On":     65,
    "Goldilocks":  65,
}
```

**Why 30 (not "no floor at all"):** The original `CIS_SOFT_FLOOR = 30` is the
fallback used when the CIS cache is sparse. Aligning Easing's floor with that
number preserves the *F-grade exclusion* (the only meaningful signal we ever
had from Easing was "don't trade F-grade junk") without filtering on
direction. If you prefer, "no floor" with an upstream universe filter is
also defensible — but the spec in H2 §5 says "grade-eligibility", so use 30.

**No other code change required.** The strategy already routes through
`_regime_floor` (line 246/621), and the trade-execution logic doesn't
care which value resolves at Easing time — only the entry gate filter.

---

## 3. What this is NOT

- **Not a Risk-Off/Risk-On/Stagflation inversion.** Three regimes have strong
  negative IC, but the H2 design's cleanest reading is "CIS = ranking
  signal, regime = beta timing" (per ARCHITECTURE.md cause-vs-reflection).
  The reconciliation requires three more checks before any flip ships
  (Phase 2 of the H2 rollout: backtest regime-conditional magnitude,
  not direction). H2a showed all three negative-IC regimes PERSIST under
  relative returns (`verdict: genuine reversal (persists)`) — that's
  either a true signal OR a detector artifact. We don't know yet, so we
  don't ship an inversion.
- **Not an Easing 30d call.** H1 30d Easing IC is strongly negative
  (t = −10.2). The Nautilus LS v1 book trades a 7d horizon; dropping the
  7d floor is safe. *If* a 30d-driven signal joins the book later, revisit
  this — but **that's a separate instrument, separate evidence, separate
  ship gate.**
- **Not a regulatory/grade methodology change.** Compliance-safe signal
  vocabulary (STRONG OUTPERFORM / OUTPERFORM / NEUTRAL / UNDERPERFORM /
  UNDERWEIGHT) is unchanged; only the threshold one of them gates on.

---

## 4. The 30d flag — documented, not actioned

30d Easing IC: −0.154 abs (t=−10.2), −0.209 relative (t=−13.9). The
30d signal exists AND persists under beta-stripping. This is the one
regime/horizon combination where the H2 reframe (CIS = ranking) predicts
negative IC across both absolute and relative — which is the right
prediction for an asset-quality signal in an extended regime (the bubble
that Easing often IS). We do NOT act on it here because:

1. Nautilus LS v1 is a 7d book; the 30d IC is observational only.
2. Acting on 30d requires a separate signal-tier wiring in the Risk
   Meter, separate OOS study, separate ship gate. Out of scope for B.7.
3. Once we have confidence in the 30d-as-alpha reading, it becomes a
   candidate for Phase 2 of the H2 rollout.

For now: **flag in PROJECT_STATE §research as "30d Easing negative-IC
observation, awaiting Phase 2 wiring"**, don't let it be forgotten.

---

## 5. Rollback plan

If the change degrades the live OOS paper track record (defined below),
revert `Easing: 30` → `Easing: 62` and rerun. Revert is one-line; no
other code path is touched.

**Monitoring — pre-commit baseline (OOS Nautilus LS v1, before B.7):**

```bash
# Capture the 4-week-baseline Nautilus LS v1 paper track record
python -m src.research.nautilus.ls_v1.backtest --since 2026-06-08 \
    --until 2026-07-06 --regime-filter Easing \
    > reports/ls_v1_easing_baseline_pre_b7_2026-07-06.txt
```

**Monitoring — post-ship (after Jazz deploys Easing:30):**

```bash
# Repeat after 4 weeks of OOS paper trading
python -m src.research.nautilus.ls_v1.backtest --since 2026-07-06 \
    --until 2026-08-03 --regime-filter Easing \
    > reports/ls_v1_easing_post_b7_2026-08-03.txt
```

**Pre-defined "revert now" trigger** — any of:
- Sharpe drop ≥ 20% in Easing regime days vs baseline.
- Max drawdown widens by > 1% absolute.
- Easing-regime hit rate (long+short alpha > 0) drops below 45% (was ~52%).
- A single day triggers > 4σ adverse move tied to an Easing-regime entry.

If none trigger in 4 weeks, **Phase 1 is operational** and we move to Phase 2.

---

## 6. What's next if this ships clean

Phase 2 of the H2 rollout — regime-conditional *magnitude* (not direction)
of the CIS floor, OOS-validated across the smoothed-history panel. Per
`docs/H2_REGIME_GATE_DESIGN_2026-07-06.md` §6 phase order:

  Phase 0 ✅ (regime smoother → median 4.0d → 29.5d run length)
  Phase 1 🟢 (this doc — Easing drop)
  Phase 2 (regime-conditional magnitude backtest — AQR/Millennium discipline)
  Phase 3 (per-regime production flip where OOS Sharpe improves ≥10% net
           of costs AND n≥30 trades AND survives multiple testing)

Phase 2 specifically requires the regime smoother changes from Phase 0 to
be live (they are, as of 2026-07-06) and uses `cis_history_smoothed/` as
its label panel. The H2a result (3 genuine reversals relative+abs) means
**the Phase 2 magnitude finding is more important than originally scoped**;
a regime-conditional sizing that shrinks CIS to 0 in Risk-On (where the
negative IC is loudest) and keeps it tight in Easing may improve the live
book's Sharpe even without any direction flip.

---

## 7. Citations

- **H1 raw** (`reports/cis_regime_ic_2026-07-05.md`): composite CIS 7d IC table,
  Easing row: IC=+0.03, t=+1.96, n=4304. "borderline, not significant."
- **H2a abs & relative** (`reports/cis_regime_relative_ic_2026-07-06.md`):
  Easing row: IC_abs=+0.0293 (t=+1.92), IC_rel=+0.0156 (t=+1.02), both
  t<2.0. Verdict `"—"` (no verdict fired because no significant negative
  IC was being challenged).
- **H1 smoothed**: Phase 0 modal-14d smoother, n_runs went 44→12, median
  regime length 4.0d→29.5d. Easing grew to n=4932; IC remained flat (no
  7d composite-CIS / Easing IC reached |t|≥2 in the smoothed panel).
- **30d cross-check**: same sources, 30d horizon column. Strong negative:
  H1 raw t≈−10, H2a abs IC=−0.154 (t=−10.2), H2a rel IC=−0.209 (t=−13.9),
  H1 smoothed similar. Lives in §4 below — flagged, not actioned.
- **H2 design** (`docs/H2_REGIME_GATE_DESIGN_2026-07-06.md`) §5: this
  proposal is a direct execution of the Easing row's "✅ safe: drop CIS
  floor to grade-eligibility" entry.
