# R45 Deepening — Cadence Sweep + Sub-period OOS

**Window:** 2024-06-07 → 2026-06-07  ·  **Days:** 731  ·  **Universe:** 41 assets

Per Jazz 2026-07-20: do NOT change CIS yet. This deepens the diagnostic, not the production methodology.

## Cadence × cost grid (composite CIS, daily-rebal baseline = R45)

`t` = Newey-West residual-α t-stat after {market, momentum}. **Bold** = clears t > 1.96.

| rebal (d) | turnover≈ | 0 bps t | 5 bps t | 10 bps t | first-cad-at-5bps-to-clear |
|--:|--:|--:|--:|--:|--:|
| 1 | 228.6 | **+2.24** | +1.68 | +1.14 | **3d** (t=+2.08) |
| 3 | 86.4 | **+2.34** | **+2.08** | +1.81 | **3d** (t=+2.08) |
| 5 | 66.4 | **+2.85** | **+2.64** | **+2.43** | **3d** (t=+2.08) |
| 7 | 57.4 | +1.89 | +1.73 | +1.57 | **3d** (t=+2.08) |
| 14 | 38.2 | +0.41 | +0.32 | +0.22 | **3d** (t=+2.08) |
| 21 | 28.8 | +0.94 | +0.87 | +0.80 | **3d** (t=+2.08) |

### pillar_O

| rebal (d) | turnover≈ | 0 bps t | 5 bps t | 10 bps t | first-cad-at-5bps-to-clear |
|--:|--:|--:|--:|--:|--:|
| 1 | 267.8 | **+2.49** | +1.84 | +1.20 | — |
| 3 | 105.2 | **+2.29** | **+1.97** | +1.66 | — |
| 5 | 79.5 | **+3.53** | **+3.33** | **+3.13** | **3d** (t=+1.97) |
| 7 | 60.2 | **+2.21** | **+2.04** | +1.87 | **3d** (t=+1.97) |
| 14 | 40.2 | +0.54 | +0.44 | +0.34 | **3d** (t=+1.97) |
| 21 | 30.7 | +0.92 | +0.84 | +0.77 | **3d** (t=+1.97) |

### pillar_S

| rebal (d) | turnover≈ | 0 bps t | 5 bps t | 10 bps t | first-cad-at-5bps-to-clear |
|--:|--:|--:|--:|--:|--:|
| 1 | 55.9 | -0.56 | -0.77 | -0.98 | — |
| 3 | 51.3 | +0.07 | -0.05 | -0.17 | — |
| 5 | 61.6 | -0.14 | -0.25 | -0.35 | — |
| 7 | 59.4 | +0.51 | +0.43 | +0.35 | — |
| 14 | 46.7 | +0.60 | +0.56 | +0.52 | — |
| 21 | 24.7 | +0.19 | +0.14 | +0.10 | — |

## Sub-period α_t (6 fixed-width windows, daily rebal)

Per-window Newey-West residual-α t after {market, momentum}. **Bold** = clears t > 1.96. n = days in window.

| Window | dates | n | CIS t | pillar_O t | pillar_S t |
|--:|---|--:|--:|--:|--:|
| W1 | 2024-06-07 → 2024-10-06 | 122 | +1.30 | +1.30 | +0.54 |
| W2 | 2024-10-06 → 2025-02-04 | 122 | **+3.48** | **+2.54** | +0.73 |
| W3 | 2025-02-04 → 2025-06-05 | 122 | -0.20 | +1.05 | +0.28 |
| W4 | 2025-06-05 → 2025-10-04 | 122 | +1.76 | +1.70 | +0.24 |
| W5 | 2025-10-04 → 2026-02-02 | 122 | -1.75 | **-2.32** | -1.29 |
| W6 | 2026-02-02 → 2026-06-07 | 126 | **+2.14** | +1.42 | -1.53 |

## Synthesis (per Jazz: deepening, not action)

- **CIS** clears t>1.96 at 5 bps when rebal ≥ **3d** (5bps t=+2.08, ann=+43.2%) — daily-rebal was overfit to turnover-flavored returns.
- **pillar_O** clears t>1.96 at 5 bps when rebal ≥ **3d** (5bps t=+1.97, ann=+38.3%) — daily-rebal was overfit to turnover-flavored returns.

- **CIS** clear-t windows: **2 / 6** (33%)
- **pillar_O** clear-t windows: **2 / 6** (33%)
- **pillar_S** clear-t windows: **0 / 6** (0%)

- **CIS** sub-period sign distribution: 4 positive / 2 negative of 6 valid windows. Mixed signs ⇒ partial regime conditioning.
- **pillar_O** sub-period sign distribution: 5 positive / 1 negative of 6 valid windows. Concentrated flip ⇒ regime-specific death (regime-conditioning is the upgrade path).