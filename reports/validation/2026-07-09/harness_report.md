# A2 — OOS Validation Harness Report

**Date:** 2026-07-09  
**Window:** 2024-01-01 → 2026-03-12  
**Cost model:** 5.0bps taker + 2.0bps maker per side  
**Pairs:** BTCUSDT-PERP, ETHUSDT-PERP, SOLUSDT-PERP (3 pairs × 4 OOS windows)

---

## Headline

- 5 variants × 3 pairs × 4 OOS windows = **60 backtests**
- Verdicts: **KEEP=0** | PRUNE=3 | INCONCLUSIVE=0 | REFERENCE=2

## Per-variant verdicts

| variant | family | mean OOS Sharpe | total OOS PnL % | n_trades | verdict |
|---|---|---:|---:|---:|---|
| `frozen_baseline` | baseline | +1.413 | +3.81% | 57 | **REFERENCE** |
| `alpha_only` | sanity | -1.292 | -5.19% | 190 | **REFERENCE** |
| `kernel_edgegate` | gated | -3.286 | -3.14% | 73 | **PRUNE** |
| `kernel_edgegate_strict` | gated | -2.534 | -2.30% | 56 | **PRUNE** |
| `kernel_edgegate_loose` | gated | -3.316 | -3.14% | 76 | **PRUNE** |

## Multiple-testing (BH-FDR @ α=0.05, gated family only)

_fdr_bh α=0.05: 0/3 rejected  (FWER ~ 0.050)_

| variant | raw p | BH-corrected p | rejected |
|---|---:|---:|---|
| `kernel_edgegate` | 0.8671 | 0.8691 | ❌ |
| `kernel_edgegate_strict` | 0.8423 | 0.8691 | ❌ |
| `kernel_edgegate_loose` | 0.8691 | 0.8691 | ❌ |

## Variant definitions

### `frozen_baseline` (baseline)
_REGIME_CIS_FLOOR dict (Tightening 52 / Risk-Off 50 / Stagflation 50 / Neutral 58 / Easing 62 / Risk-On 65 / Goldilocks 65). conv_variant=baseline, edge_gate OFF. The thing we are trying to beat._

- **Layers on:** quality
- **Env overrides:** (module defaults)

### `alpha_only` (sanity)
_All gates OFF (enable_cis_gate=False, enable_adx_gate=True). Pure technical alpha: EMA cross + ATR SL/TP + ADX>=25. Sanity variant — if alpha alone doesn't beat gated, the baseline itself is broken._

- **Layers on:** (none)
- **Env overrides:** LSV1_ENABLE_CIS_GATE=0

### `kernel_edgegate` (gated)
_Edge gate ON (LSV1_USE_EDGE_GATE=1, default cost 10bps). Replaces discrete REGIME_CIS_FLOOR with continuous expected-edge = side × IC_regime × z × σ × √horizon − cost. H1 fix: direction derived empirically per regime×side._

- **Layers on:** quality, edge_gate
- **Env overrides:** LSV1_USE_EDGE_GATE=1

### `kernel_edgegate_strict` (gated)
_Edge gate ON with doubled cost assumption (LSV1_EDGE_COST=0.002). Tests whether edge gate holds up under harsher cost (20bps RT)._

- **Layers on:** quality, edge_gate
- **Env overrides:** LSV1_USE_EDGE_GATE=1, LSV1_EDGE_COST=0.002

### `kernel_edgegate_loose` (gated)
_Edge gate ON with halved cost assumption (LSV1_EDGE_COST=0.0005). Tests whether edge gate over-filters at the stated 5+2 bps cost._

- **Layers on:** quality, edge_gate
- **Env overrides:** LSV1_USE_EDGE_GATE=1, LSV1_EDGE_COST=0.0005

## Per-window OOS metrics (avg Sharpe across 3 pairs)

| variant | w0 Sharpe | w1 Sharpe | w2 Sharpe | w3 Sharpe | mean |
|---|---:|---:|---:|---:|---:|
| `frozen_baseline` | +6.010 | -0.234 | -0.032 | -0.089 | +1.414 |
| `alpha_only` | +0.686 | -0.719 | -2.478 | -2.655 | -1.292 |
| `kernel_edgegate` | +1.093 | -11.910 | -1.087 | -1.239 | -3.286 |
| `kernel_edgegate_strict` | +1.506 | -10.073 | -0.749 | -0.820 | -2.534 |
| `kernel_edgegate_loose` | +1.093 | -11.761 | -1.358 | -1.239 | -3.316 |

## Verdict legend

- **KEEP** — OOS Sharpe > 0 AND BH-FDR survivor @ α=0.05 (gated family)
- **PRUNE** — OOS Sharpe ≤ 0 OR n_trades < 30 (insufficient evidence)
- **INCONCLUSIVE** — positive but not BH-survivor
- **REFERENCE** — baseline or sanity variant, reported for context only

**Compliance:** positioning language only; not investment advice.
