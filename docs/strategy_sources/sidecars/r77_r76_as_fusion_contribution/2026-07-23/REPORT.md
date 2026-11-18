# R77 — R76 (funding residual) as 3rd fusion contribution to R69 family
**Run date:** 2026-07-23T01:22:52
**Panel:** 2024-06-07 → 2026-06-07 (731 days, 28-asset strict universe)

## Verdict
**FUSION_LIFT** — ✅ FUSION LIFT — R76 carries as 3rd fusion contribution to R69 family

- Best w_R76 = **0.30**
- Best w_R76 gross_t = +3.10, OOS_t = +3.61, passes_all = True
- ΔOOS_t vs frozen baseline = +1.17
- ΔW5 ann% = +16.6

## Frozen baseline (R69 cell, w_R76=0)
- w_R46 = 0.25, w_R62 = 0.75
- gross_t = +2.52, OOS_t = +2.44, passes_all = True, maxDD = -11.05%

## Per-leg gauntlet (on 28-asset)
- **leg_r46**: gross_t = +1.77, OOS_t = -0.44, maxDD = -33.62%
- **leg_r62**: gross_t = +2.03, OOS_t = +2.94, maxDD = -18.85%
- **leg_r76**: gross_t = +2.11, OOS_t = +3.15, maxDD = -24.70%

## Leg-correlation gate (lesson #42, R76 result)
- corr(R76, R46) = +0.103
- corr(R76, R62) = +0.004
- max |corr| = 0.103 (gate ≤ 0.3)
- passes_orthogonality_gate = **True**

## w_R76 sweep (3-component fusion on top of frozen R69 cell)
| w_R76 | gross_t | OOS_t | pass | maxDD | sharpe | ΔOOS_t | W5 ann% | ΔW5 ann% |
|---:|---:|---:|:--:|---:|---:|---:|---:|---:|
| 0.00 | +2.52 | +2.44 | ✓ | -11.05% | +1.69 | +0.00 | +45.6 | +0.0 |
| 0.05 | +2.63 | +2.67 | ✓ | -10.33% | +1.77 | +0.23 | +48.3 | +2.8 |
| 0.10 | +2.75 | +2.90 | ✓ | -9.68% | +1.86 | +0.46 | +51.1 | +5.6 |
| 0.15 | +2.86 | +3.11 | ✓ | -9.03% | +1.93 | +0.67 | +53.9 | +8.3 |
| 0.20 | +2.96 | +3.31 | ✓ | -8.68% | +1.99 | +0.87 | +56.6 | +11.1 |
| 0.25 | +3.04 | +3.48 | ✓ | -8.57% | +2.04 | +1.04 | +59.4 | +13.9 |
| 0.30 | +3.10 | +3.61 | ✓ | -8.91% | +2.06 | +1.17 | +62.2 | +16.6 |

## Capacity proxy (P2, 3-leg)
- turnover_ann ≈ 82.0
- declared_capacity ≈ $7.5M (crude ADV × 5%/leg × 3-leg)

## Live book impact
- Touches frozen R69 cell: **False**
- R65 paper book unaffected: **True**
- R66 tracking unaffected: **True**
- Note: R77 is research-only. Forward R78 candidate MAY rebalance w_R46 + add w_R76 based on R77 verdict.

## Aggregate lesson (proposed, depends on verdict)
- ✅ Aggregate lesson: "Lesson #43 holds — orthogonal candidates (funding residual, |corr|=0.156) DO carry as 3rd fusion contribution. Lesson #42 + #43 form a complete pair: 'don't rescue via fusion' + 'do test orthogonal candidates'. The R76 W5=+98.4% (where R46 fails at −54.1%) translates directly into positive ΔOOS_t at the fusion level. R78 candidate = rebalance w_R46 down from 0.25 + add w_R76=0.10-0.15 to the live R69 cell."