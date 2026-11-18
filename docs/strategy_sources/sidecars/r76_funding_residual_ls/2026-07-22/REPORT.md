# R76 — Funding residual cross-sectional L/S
**Run date:** 2026-07-22T14:18:28
**Panel:** 2024-06-07 → 2026-06-07 (731 days, 28-asset strict universe)

## Verdict
**SURVIVES_ORTHOGONAL** — ✅ SURVIVES + ORTHOGONAL — eligible for R77 fusion candidate

- Passes gauntlet: **True**
- Passes orthogonality gate (|corr| ≲ 0.3): **True**

## Leg-correlation gate (lesson #42)
- corr(R76_leg, R46_leg) = +0.156
- corr(R76_leg, R62_leg) = -0.040
- max |corr| = 0.156 (gate ≤ 0.3)
- fusion_candidatable = **True**

## Best cell (after matched-cell sign audit)
- 5d/0.0bps, sign=high_fund_long
- gross_t = +2.11, OOS_t = +3.15, passes_all = True

## Matched-cell sign audit (top-3)
- 5d/10.0bps: high=+1.34, low=-2.14, diff=+3.48
- 5d/0.0bps: high=+2.11, low=-1.37, diff=+3.48
- 5d/5.0bps: high=+1.73, low=-1.75, diff=+3.48
- **Sign verdict: high_fund_long** (matched-cell diff = +3.48)

## Per-window W1-W6 ann% at best cell
- W1: +59.7%  (n=121, maxDD=-11.50%)
- W2: +21.9%  (n=122, maxDD=-15.52%)
- W3: -26.2%  (n=122, maxDD=-22.28%)
- W4: +6.6%  (n=122, maxDD=-18.18%)
- W5: +98.4%  (n=122, maxDD=-8.69%)
- W6: +147.3%  (n=122, maxDD=-8.56%)

## Per-leg gauntlet
- **r76_3d_0bps**: gross_t = +1.41, OOS_t = +0.53, passes_all = False
- **r46**: gross_t = +1.77, OOS_t = -0.44, passes_all = False
- **r62**: gross_t = +2.03, OOS_t = +2.94, passes_all = True

## Live book impact
- Touches frozen R69 cell: **False**
- Note: R76 is research-only. R77 fusion candidate MAY be built only if verdict is SURVIVES_ORTHOGONAL.

## Aggregate lesson #43 (proposed, depends on verdict)
- ✅ Aggregate lesson #43: "Orthogonal signal sources carry real cross-sectional edges that survive the 3-check gauntlet AND are uncorrelated with existing fusion legs. Lesson #42 holds: leg-correlation gate is necessary; orthogonal candidates are the right next R-number. Funding residual = cross-sectional demean funding is a viable R77 fusion-contribution candidate."