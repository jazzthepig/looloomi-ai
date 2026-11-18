# R63 — Sleeve Fusion Validation — REPORT

**Panel:** 2024-06-07 → 2026-06-07  ·  **731 days × 28 funding-bearing assets** (STRICT intersection, both legs re-computed on this subset)

**Leg R46:** pillar_O 5d/5bps L/S, k=3, on 28-asset strict intersection
**Leg R62:** fade-the-crowd 21d/0bps gated by `external` fragility detector (z=0.5, mf=2)
**Fusion:** w × Leg R46 + (1−w) × Leg R62, weight sweep [0.0, 0.25, 0.33, 0.5, 0.67, 0.75, 1.0]

## Per-leg gauntlet (re-computed on 28-asset strict intersection)

| leg | gross_t | OOS_t | pass_gross | pass_OOS | maxDD |
|---|--:|--:|:--:|:--:|--:|
| R46 pillar_O 5d/5bps | +1.77 | +0.61 | ✗ | ✗ | -33.62% |
| R62 fade-the-crowd 21d/0bps gated | +2.03 | +2.37 | ✓ | ✓ | -18.85% |

**Cross-leg correlation:** ρ(R46, R62) = -0.05  →  orthogonal? **✓ (|ρ| < 0.5)**

## Per-window ann%: R46 vs R62 vs Best-fused

| Window | character | R46 ann% | R62 ann% | Best-fused ann% |
|--:|---|--:|--:|--:|
| W1 🟥 | — | +74.4 | -31.2 | -11.4 |
| W2 🟩 | — | +354.9 | +134.7 | +183.5 |
| W3 🟥 | — | -11.7 | -19.1 | -16.2 |
| W4 🟩 | — | +61.9 | +16.4 | +28.5 |
| W5 🟩 | — | -58.1 | +115.7 | +45.6 |
| W6 🟩 | — | +44.1 | +93.9 | +81.3 |

## Weight sweep — fused gauntlet + max DD

| w_R46 | gross_t | OOS_t | pass | maxDD | sharpe | %TIM | IR vs R46 | IR vs R62 |
|--:|--:|--:|:--:|--:|--:|--:|--:|--:|
| 0.00 | +2.03 | +2.37 | ✓ | -18.85% | +1.32 | 86% | -0.06 | +nan |
| 0.25 | +2.52 | +2.38 | ✓ | -11.05% | +1.69 | 99% | -0.06 | +0.06 |
| 0.33 | +2.61 | +2.28 | ✓ | -9.94% | +1.77 | 99% | -0.06 | +0.06 |
| 0.50 | +2.62 | +1.90 | ✗ | -15.04% | +1.80 | 99% | -0.06 | +0.06 |
| 0.67 | +2.39 | +1.40 | ✗ | -21.76% | +1.63 | 99% | -0.06 | +0.06 |
| 0.75 | +2.24 | +1.18 | ✗ | -24.77% | +1.52 | 99% | -0.06 | +0.06 |
| 1.00 | +1.77 | +0.61 | ✗ | -33.62% | +1.19 | 95% | +nan | +0.06 |

## Best fused (w_R46 = 0.25)

**Gauntlet:** gross_t = +2.52 ✓, OOS_t = +2.38 ✓, pass_all = True
**Max DD:** -11.05%  ·  Sharpe: +1.69  ·  Time-in-market: 99%
**IR vs each leg standalone:** vs R46 = -0.06, vs R62 = +0.06

**Factor decomposition (R² attributable / residual %):**
- β_market = -0.000
- β_momentum = -0.000
- β_leg_r46 (in-fused) = +0.250
- β_leg_r62 (in-fused) = +0.750
- α_const = -0.00000
- R²_attrib = 1.00, residual var = 0% of fused total

## Verdict gates

- (1) fusion passes 3-check: **✓** (gross_t=+2.52, OOS_t=+2.38)
- (2) max DD improves (best-fused < min(R46, R62)): **✓** (fused=-11.05%, min(legs)=-33.62%)
- (3) orthogonal: |ρ(R46, R62)| < 0.5: **✓** (ρ=-0.05)

Gates passed: **3/3**

## Capacity proxy (MECHANISM_SPEC §P2 — binding capacity)

- Fused turnover (ann): **56.0** (R46 leg: 88.2, R62 leg: 45.2)
- Crude declared capacity: **$5.0M** (assumes median ADV $50M/asset × 5%/leg × 2-leg)
- **CRUDE — verify with fill-attribution (P2 req'd) before deployment.**

## Verdict
**✅ FUSION WINS — passes 3-check + DD improves + corr < 0.5**

**Action per MECHANISM_SPEC §P2:** declare joint capacity `$5.0M` (P2) and start flat-recording the fragility-gated position count (P3). Per §P1 forward commitment: this report IS the pre-declared criterion — the live numbers must reconcile to the cells in this sweep at horizon.