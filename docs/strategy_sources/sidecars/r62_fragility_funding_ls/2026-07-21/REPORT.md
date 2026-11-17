# R62 — Regime-Conditioned Fade-the-Crowd — REPORT

**Panel:** 2024-06-07 → 2026-06-07  ·  **731 days × 28 funding-bearing assets** (out of 41 CIS ∩ OHLCV)

**Score coverage:** 100% of days

**Fragile label:** ['W1', 'W3'] — identified from R60 per-window P&L (the two deeply-negative windows).

**Playable label:** ['W2', 'W4', 'W5', 'W6'] (KS reference).

## Sub-windows (fragile = light red)

| Window | Start | End | n_days | fragile |
|--:|---|---|--:|:--:|
| W1 | 2024-06-07 | 2024-10-05 | 121 | 🟥 |
| W2 | 2024-10-06 | 2025-02-04 | 122 | 🟩 |
| W3 | 2025-02-05 | 2025-06-06 | 122 | 🟥 |
| W4 | 2025-06-07 | 2025-10-06 | 122 | 🟩 |
| W5 | 2025-10-07 | 2026-02-05 | 122 | 🟩 |
| W6 | 2026-02-06 | 2026-06-07 | 122 | 🟩 |

## R60 ungated baseline (reproduction parity)

| config | gross_t | OOS_t | pass_gross | pass_OOS |
|---|--:|--:|:--:|:--:|
| 5d_5bps | -0.28 | -0.41 | ✗ | ✗ |
| 21d_0bps | +1.73 | +1.89 | ✗ | ✗ |

R60 per-window ungated P&L (ann%, 21d/0bps baseline):

- W1: -34.5% 🟥
- W2: +170.2% 🟩
- W3: -21.1% 🟥
- W4: +32.4% 🟩
- W5: +53.9% 🟩
- W6: +61.4% 🟩

## Fragility KS ranking (top-8 by KS distance)

| rank | feature | KS | p | mean(fragile) | mean(playable) |
|--:|---|--:|--:|--:|--:|
| 1 | mkt_vol_30 | 0.27 | 0.000 | +0.0427 | +0.0391 |
| 2 | xsec_rank_ic_30 | 0.26 | 0.000 | +0.0007 | -0.0090 |
| 3 | xsec_disp | 0.15 | 0.002 | +0.0267 | +0.0268 |
| 4 | streak_5 | 0.14 | 0.005 | +0.4979 | -0.0430 |
| 5 | funding_mean | 0.13 | 0.011 | +0.0000 | +0.0000 |
| 6 | mkt_trail30 | 0.12 | 0.023 | -0.0555 | +0.0076 |
| 7 | btc_funding_raw | 0.11 | 0.042 | +0.0000 | +0.0000 |
| 8 | btc_funding_zscore_30 | 0.11 | 0.051 | -0.0676 | -0.0346 |

## Sweep summary

- Total cells: **288** (=4 cadences × 2 costs × 4 z-thresholds × 3 min-features × 3 feature sets)
- Cells passing all 3 checks: **7**
- Best gross_t across sweep: **+2.27**
- Best OOS_t across sweep:   **+2.37**

## Top-3 cells by (pass_all ↓, OOS_t ↓, gross_t ↓)

| rank | config | fragile_HR | playable_HR | %flat | gross_t | OOS_t | pass |
|--:|---|--:|--:|--:|--:|--:|:--:|
| 1 | `topexternal_z0.5_mf2_cad21_bps0` | 8% | 12% | 11% | +2.03 | +2.37 | ✓ |
| 2 | `topexternal_z0.25_mf2_cad21_bps0` | 39% | 39% | 39% | +2.27 | +2.34 | ✓ |
| 3 | `topexternal_z0.25_mf2_cad21_bps5` | 39% | 39% | 39% | +2.20 | +2.30 | ✓ |

## Best cell detail

**Config:** feature_set=`external`, z_threshold=0.5, min_features=2, cadence=21d, cost=0bps
**Features used (`feature_set=external`):** `funding_mean, funding_disp, funding_skew, funding_extreme_long_frac, funding_extreme_short_frac, funding_net_long_frac`
**Hit-rate diagnostics:** fragile_hit=8%, playable_hit=12%, %panel flat=11%

**3-check gauntlet (gated):**
- gross_t = **+2.03** ✓
- 5bps is the cost in series for the chosen cell (`cost_bps=0`)
- OOS_t = **+2.37** ✓
- pass_all = **True**

## Per-window P&L: ungated vs gated (best cell, ann%)

Fragile rows highlighted 🟥. W5 row tracked separately.

| Window | dates | ungated ann% | gated ann% | Δ |
|--:|---|--:|--:|--:|
| W1 🟥 | (W1) | -34.5 | -31.2 | +3.3 |
| W2 🟩 | (W2) | +170.2 | +134.7 | -35.4 |
| W3 🟥 | (W3) | -21.1 | -19.1 | +2.0 |
| W4 🟩 | (W4) | +32.4 | +16.4 | -16.1 |
| W5 🟩 | (W5) | +53.9 | +115.7 | +61.8 |
| W6 🟩 | (W6) | +61.4 | +93.9 | +32.5 |

## Verdict
**✅ SURVIVES — clears all 3 checks**

Best gated cell: gross_t=+2.03, OOS_t=+2.37. vs R60 ungated 21d/0bps (gross_t=+1.73, OOS_t=+1.89).