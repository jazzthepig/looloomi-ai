# H2 — Regime-Conditional CIS Gate: Design (not yet a production change)

**Author:** Seth / Austin · 2026-07-06 · **Status:** 🟡 design, awaiting OOS validation before any production flip
**Builds on:** `reports/cis_regime_ic_2026-07-05.md` (H1, done) · `RESEARCH_CIS_REGIME_INTERACTION_2026-07-06.md`
**Standard:** AQR (factor-time discipline, multiple testing, OOS) + Millennium (soft sizing, turnover, sample honesty)

---

## 0. TL;DR

H1 found the composite-CIS 7d **absolute** forward-return IC flips sign by regime (positive in
Tightening, negative in Risk-On / Risk-Off / Stagflation, flat in Easing). The naïve read is
"invert the CIS gate in 3 regimes." **We are NOT going to do that in production yet.** Three
things block a direct inversion, and a cleaner design dissolves the paradox:

1. **The regime detector is noisy** (median regime length ≈ 4 days; stale `fed_funds_rate=5.25`
   default). Conditioning a live book on unreliable labels is how you convert noise into losses.
2. **Two regimes are underpowered** (Tightening n=216, Stagflation n=195) — can't size a gate on them.
3. **The inversion is measured on ABSOLUTE returns.** Our edge map measures BENCHMARK-RELATIVE
   alpha and finds CIS's top tier POSITIVE (STRONG OUTPERFORM +3.3% / 30d). Both can be true at
   once — and reconciling them is the whole design.

**Core reframe:** CIS is a **cross-sectional RANKING** signal (who outperforms whom). Its
*absolute* directional loading is a **beta-timing** question that belongs to the regime layer, not
to CIS. So the fix is to *separate* the two controls that today are fused in one `REGIME_CIS_FLOOR`:
- **CIS → cross-sectional spread** (long high-CIS, short low-CIS *within* a regime). Ranking.
- **Regime → net/gross exposure + spread sign** (how much beta, and whether the spread is even reliable). Timing.

---

## 1. The evidence (H1, 12,059 obs, 40 assets, 2025-05→2026-05)

7d absolute forward-return IC, composite CIS:

| Regime | IC | t | n | quantile spread (top−bottom) | read |
|---|---:|---:|---:|---:|---|
| Tightening | **+0.20** | +3.0 | 216 ⚠️ | +2.90% | high-CIS good (but small n) |
| Easing | +0.03 | +2.0 | 4304 | +2.19% | ~flat |
| Risk-Off | −0.06 | −4.3 | 5578 | −2.21% | high-CIS underperforms |
| Risk-On | −0.19 | −8.3 | 1766 | **−7.26%** | high-CIS reverts hard, low-CIS bounces |
| Stagflation | −0.29 | −4.1 | 195 ⚠️ | −7.80% | inverted (tiny n) |
| Neutral / Goldilocks | — | — | 0 | — | never observed in window |

The Risk-On row is the loud one: top-quintile CIS returned **−4.1%**, bottom-quintile **+3.2%**
over 7d. That is textbook **short-horizon mean reversion in an euphoric tape** — the already-run-up
quality/momentum names give back, the beaten-down junk bounces.

---

## 2. Why NOT "just invert" — the three live interpretations

H1 itself lists three, and each implies a *different* action. We must not ship before we know which:

- **(B) Mean reversion.** CIS is loaded on momentum/quality that is *extended* by the time it
  scores high; 7d reversal drags IC negative. → the answer is horizon/timing, not "CIS is wrong."
- **(C) CIS is a risk filter, not an alpha.** The LS book is already +$328 OOS with the CIS gate
  *mis*-directed in 3/6 regimes — the real alpha is ADX+EMA+ATR; CIS screens out names that would
  drop. → then CIS should *gate universe eligibility*, not *set direction*.
- **(D) The regime detector is too noisy** to condition on (4-day median regime). → then the
  regime-conditional IC variation is partly an artifact and any regime gate is fragile.

**All three point away from a naïve production inversion and toward: (a) fix the detector, (b)
use CIS cross-sectionally, (c) let regime govern exposure — validated OOS.**

---

## 3. The reconciliation (the design's key idea)

Absolute IC (H1) and relative alpha (edge map) disagree only if you conflate *return* with *alpha*:

```
absolute_return(asset) = beta(asset) · market_return(regime)  +  alpha(asset)
```

In Risk-Off the market term dominates and is negative; high-CIS crypto names are **higher beta**
(the composite is momentum-tilted), so they fall *more* in absolute terms → negative absolute IC.
But their **alpha** (return minus BTC/SPY) can still be positive — which is exactly what the edge
map measures and finds (STRONG OUTPERFORM > 0 on 30d relative). 大象无形: **ranking is stable, the
tradeable *direction* is beta-timing and regime-conditional.**

Testable prediction (H2a, below): recompute the H1 IC on **benchmark-relative** forward returns.
If the sign flips vanish or shrink sharply, interpretation (B)+beta is confirmed and CIS-as-ranking
is intact — the safest and most likely outcome.

---

## 4. Proposed target architecture (three decoupled controls)

Today `REGIME_CIS_FLOOR` fuses eligibility + direction + magnitude into one number per regime.
Split it:

| Control | Driven by | What it does | Where it lives |
|---|---|---|---|
| **Eligibility screen** | CIS grade (quality) + executability | keep names investable; drop D/F & illiquid | universe build (unchanged) |
| **Cross-sectional spread** | CIS **rank** within regime + edge map | long top-rank, short bottom-rank; size by edge-map expected alpha | Risk Meter weights |
| **Net / gross exposure** | **regime** (risk gradient) + regime IC confidence | how much beta to run and in which direction; shrink to market-neutral where IC≈0 or detector unreliable | Risk Meter gross scale + `shorts_allowed` |

This is not a rebuild — it is what the pieces already do, made explicit:
- The **edge map** (`signal_edge_map`) already is the empirical signal-tier × risk-gradient → alpha surface.
- **Regime-gated shorts** (`_SHORT_OK`) already gate the short side on regime.
- **Season/cause-proximity** already tilts sizing by diffusion phase.
- What's MISSING is wiring the **regime-conditional IC confidence** into the cross-sectional spread's
  *magnitude* (size up where CIS ranking is trustworthy this regime, shrink toward neutral where it isn't).

---

## 5. The gate table — as a HYPOTHESIS to validate, not to ship

Per-regime action, gated on sample adequacy and OOS confirmation:

| Regime | n | CIS cross-sectional use | net-exposure posture | ship gate |
|---|---:|---|---|---|
| Tightening | 216 ⚠️ | long high-CIS (IC+ confirmed) | normal | ⚠️ underpowered — keep current, don't tighten |
| Easing | 4304 | **no CIS direction** (flat) — eligibility only | normal | ✅ safe: drop CIS floor to grade-eligibility |
| Risk-Off | 5578 | shrink CIS magnitude; lean market-neutral | reduce gross | ✅ candidate after H2a |
| Risk-On | 1766 | **reversal tilt** (low-CIS bounce, high-CIS fade) IF H2a keeps sign | reduce net long | ⚠️ only if relative-IC also inverts |
| Stagflation | 195 ⚠️ | inconclusive | reduce gross | ⛔ do NOT act — n too small |
| Neutral / Goldilocks | 0 | unobserved | prior | ⛔ no data |

**Nothing here is executed until §6 clears it.** The only *immediately* safe changes are Easing
(drop the floor to eligibility — CIS carries no 7d/30d direction there, n>4000) and shrinking gross
in low-confidence regimes (a risk reduction, always allowed).

---

## 6. Rollout — AQR/Millennium discipline (the gate on production)

1. **Phase 0 — fix the confound first.** Interpretation (D) taints everything downstream. Coordinate
   with Minimax on `MacroSnapshot.determine_regime`: kill stale defaults, add the regime smoother
   (median-length ≥ N days), re-label the history. Re-run H1 on smoothed labels. *No gate change
   until the detector is trustworthy.*
2. **Phase 1 — H2a relative-IC test (analysis only).** Recompute H1 IC on benchmark-relative returns.
   Outcome decides whether Risk-On is a *reversal* (invert) or a *beta* effect (keep ranking, cut beta).
3. **Phase 2 — H3 continuous soft gate, backtest only.** Replace the hard floor with conviction-scaled
   sizing (linear/sigmoid/rank), regime-conditional magnitude from the (smoothed) IC. Walk-forward
   IS=70/OOS=30, HOLM correction, 5bps+2bps costs, turnover ≤ 1.5× baseline, Calmar ≥ baseline.
4. **Phase 3 — flip production per-regime, only where** OOS Sharpe improves ≥10% net of costs AND
   n≥30 trades AND survives multiple-testing. Underpowered regimes keep the current (documented) floor.

**Guardrail:** the live LS book is already profitable. Every phase must beat the current book OOS
*after costs* before it touches production. We are looking for a better-directed gate, not a story.

---

## 7. Fusion with what's already built

- **Conviction tilt** (`risk_meter.conviction_from_track_record`) → extend to read `cis_regime_fitness`
  (per-regime IC): scale the cross-sectional magnitude by regime IC confidence, N-gated (≥50), clamped.
  This is the concrete Phase-2 wiring and it reuses the existing self-tuning machinery.
- **Edge map** is the serving surface for "given today's regime/gradient, what does each CIS tier do."
  Add a `regime` axis alongside `risk_band` once smoothed labels exist.
- **Season/cause-proximity** stays orthogonal (diffusion phase, not regime) and multiplies in as sizing.

---

## 8. What this is NOT
- **Not** a production inversion of the CIS gate today. (Blocked on Phase 0–3.)
- **Not** an action on Tightening/Stagflation (underpowered) or Neutral/Goldilocks (unobserved).
- **Not** a claim that CIS is broken — the likely truth (pending H2a) is CIS-ranking is fine and the
  regime layer should own beta timing.

## 9. Immediate next step (safe, analysis-only)
**H2a:** recompute H1 IC on benchmark-relative forward returns (`return − BTC/SPY`) per regime. One
script in `src/research/cis_regime_studies/` reusing the H1 loader. If the sign-flips shrink, we have
our answer and the design collapses to "CIS = ranking, regime = beta timing" — ship the Easing floor
drop + low-confidence gross-shrink, and leave direction alone.
