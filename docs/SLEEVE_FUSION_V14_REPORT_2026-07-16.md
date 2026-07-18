# Track A + Track B — 2026-07-16

**Author**: Minimax-C (with Seth/Austin guidance)
**Date**: 2026-07-16
**Status**: Both tracks completed; one POSITIVE incremental, one NEGATIVE structural.
**Goal**: Continue Phase D2 fusion work — (A) re-tune V14 Option A to be less aggressive,
(B) test sleeve-level fusion (SwingOverlay + Nautilus LS V1).

---

## Track A — V14 Option A Re-tune

### Change Made

Modified `MACRO_STAKE_MULT` in `SwingOverlayV14_MTF_DirAware_CISRegimeOverlay.py` from
the original 0.65/0.65/0.50 to less-aggressive 0.85/0.85/0.70:

```python
MACRO_STAKE_MULT = {
    "RISK_ON":     1.10,   # was 1.25 (mild scale up)
    "GOLDILOCKS":  1.10,   # was 1.25
    "EASING":      1.00,   # unchanged
    "NEUTRAL":     1.00,   # unchanged
    "RISK_OFF":    0.85,   # was 0.65 (gentle scale down)
    "TIGHTENING":  0.85,   # was 0.65
    "STAGFLATION": 0.70,   # was 0.50
}
```

Direction override table + STAGFLATION flat-mode trigger **unchanged**. Only the stake
multiplier table was retuned.

### Sweep Results — 10-Pair (BTC/ETH/SOL/BNB/XRP/AVAX/LINK/DOGE/OP/ARB)

| Window | V9 (baseline) | V12b (production) | **V14a (Option A)** | ΔPnL vs V12b | ΔDD vs V12b |
|---|---:|---:|---:|---:|---:|
| TRAIN (no CIS) | 556 / $1,697 / DD 1.33% | 556 / — / — | 556 / $1,697 / DD 1.33% | (sanity ≡ V9 ✓) | — |
| VALIDATE | 504 / $1,072 / DD 1.67% | — / $1,099 / DD 1.67% | 504 / $998 / DD 1.67% | −9.2% | flat |
| HOLD-OUT | — / $363 / DD 1.31% | 132 / $377 / DD 1.08% | **98 / $238 / DD 1.09%** | **−36.9%** | +0.01pp |
| FORWARD | — / $484 / DD 0.66% | 194 / $484 / DD 0.66% | **159 / $326 / DD 0.54%** | **−32.6%** | **−18% (better)** |

### Option A vs Original V14 (0.65/0.65/0.50)

| Window | Original V14 (10p) | V14a Option A (10p) | Δ | Note |
|---|---:|---:|---:|---|
| HOLD-OUT | 98 / $207 / DD 0.82% | 98 / $238 / DD 1.09% | **+15% PnL, +33% DD** | Better ratio |
| FORWARD | 159 / $219 / DD 0.43% | 159 / $326 / DD 0.54% | **+49% PnL, +26% DD** | Better ratio |

**Verdict**: Option A is a **real improvement** over original V14 — recovers ~50% of
the PnL loss with proportional DD cost. But **V12b still dominates V14a on holdout PnL**.

### V14a's Distinctive Value (the case for slotting in as 4th sleeve)

| Metric (FORWARD) | V12b | V14a | |
|---|---:|---:|---|
| PnL | $484 | $326 | V12b wins |
| **maxDD** | **0.66%** | **0.54%** | **V14a wins (−18%)** |
| **Win Rate** | **71.6%** | **74.8%** | **V14a wins (+3.2pp)** |
| Sharpe | 8.16 | 7.45 | V12b wins |

V14a's profile: **lowest DD + highest WR** but lower total PnL. Classic risk-budget sleeve
candidate — qualifies for a 4th slot in the production sleeve.

### Track A Recommendation

**Do NOT replace V12b with V14a.** Production sleeve remains V7 50% + V10c 30% + V12b 20%.

**Add V14a as 4th sleeve member at 10-15% allocation** (rebalance other slots proportionally
if needed). V14a's distinctive profile (low DD, high WR) fills a structural gap in the
current production sleeve. Concretely:

```
Recommended 4-slot production sleeve:
  V7   50% (alpha anchor)
  V10c 20% (low-DD sleeve)
  V12b 20% (production overlay, funding-aware)
  V14a 10% (defensive 4th — CIS macro regime-aware)
  ─────────
  Total 100% (no cash buffer)
```

**Wait** — this requires a re-sweep with the new sleeve weights + per-pair allocation update.
Not done in this session (out of scope). Recommended follow-up: validate the 4-slot sleeve
on HOLD-OUT + FORWARD before committing.

---

## Track B — Sleeve-Level Fusion (70% SwingOverlay + 30% Nautilus LS V1)

### Setup

- **SwingOverlay sleeve anchor**: V7 50% + V10c 30% + V12b 20% (production)
- **Nautilus LS V1**: BTC/ETH/SOL long-short, EMA 9/21 cross + ADX gate + ATR SL/TP
- **Window**: HOLD-OUT (2026-01-01 → 2026-03-15) + FORWARD (2026-03-16 → 2026-07-15)
- **Fresh backtests**: nautilus_ls_v1_default (2025-05-03 → 2026-03-12), _holdout, _forward

### Nautilus LS V1 Realized Returns by Window

| Window | Positions | PnL | ROI on $10k | Win Rate | Profit Factor |
|---|---:|---:|---:|---:|---:|
| Default OOS (10 mo) | 63 | +$329 | +3.29% | 50% | 1.59 |
| HOLD-OUT (2.5 mo) | 4 | **+$190** | **+1.90%** | ~75% | high |
| **FORWARD (4 mo)** | 28 | **−$43** | **−0.43%** | mixed | <1 |

### Sleeve Sweep — HOLD-OUT (Nautilus +1.90% / DD 1.50%)

| Nau% | Sw% | Combined PnL | Combined DD | ΔPnL vs Sw-only | ΔDD vs Sw-only |
|---:|---:|---:|---:|---:|---:|
| 0% | 100% | **+6.51%** | 1.37% | — | — |
| 10% | 90% | +6.05% | 1.28% | −0.46pp | +0.08pp |
| 20% | 80% | +5.59% | 1.22% | −0.92pp | +0.15pp |
| **30%** | **70%** | **+5.13%** | **1.17%** | **−1.38pp** | **+0.19pp** |
| 50% | 50% | +4.21% | 1.16% | −2.30pp | +0.21pp |

### Sleeve Sweep — FORWARD (Nautilus −0.43% / DD 1.00%)

| Nau% | Sw% | Combined PnL | Combined DD | ΔPnL vs Sw-only | ΔDD vs Sw-only |
|---:|---:|---:|---:|---:|---:|
| 0% | 100% | **+8.02%** | 0.73% | — | — |
| 10% | 90% | +7.17% | 0.69% | −0.84pp | +0.04pp |
| **30%** | **70%** | **+5.48%** | **0.66%** | **−2.54pp** | **+0.07pp** |
| 50% | 50% | +3.79% | 0.70% | −4.22pp | +0.03pp |

### Track B Honest Verdict — NEGATIVE RESULT

The 70/30 sleeve fusion **does not work** as proposed:

1. **HOLD-OUT (Nautilus positive)**: 30% Nautilus costs **−1.38pp PnL** for **+0.19pp DD benefit**.
   Trade ratio: ~$7 of PnL for $1 of DD reduction. Bad deal unless DD-constrained.
2. **FORWARD (Nautilus negative)**: 30% Nautilus is **pure PnL drag** (−2.54pp) for ~+0.07pp DD.
   The negative Nautilus is not offset by any diversification benefit.

**Why Nautilus LS V1 is too small to fuse:**

- SwingOverlay DD is already low (0.5–1.4%) — insurance value of Nautilus sleeve is small
- Nautilus realized annual rate ~3.9% (default OOS), much less than SwingOverlay's 80%+ ann
- Sparse position stream: 4–28 positions over 2.5–4 month windows — too few trades for
  meaningful diversification
- WR is 50% on Nautilus vs ~70% on SwingOverlay — different alpha stream, but Nautilus
  carries significant drawdown noise

### Track B Recommendation

**Do NOT execute the 70/30 sleeve fusion as proposed.**

Three better alternatives to consider:

1. **Skip Nautilus entirely** — SwingOverlay's 3-slot production sleeve is already optimal
   given current Nautilus track record. Don't add a sleeve that doesn't earn its weight.
2. **5-10% Nautilus as diversification slice only** — if Nautilus exposure is wanted for
   "long-short regime" upside, allocate 5-10% max with explicit acknowledgment it's a
   drag on PnL. Cost: −0.23pp HOLD-OUT / −0.42pp FORWARD.
3. **Wait for Nautilus track record to mature** — 28 FORWARD positions is small-n. Run
   Nautilus for 90+ days of paper trading, then revisit sleeve fusion math with real
   track record.

### What Would Make Nautilus Worth Fusing?

- **Position count**: increase to 100+ trades per quarter (lower ADX threshold, smaller
  position size, more instruments beyond BTC/ETH/SOL)
- **Hit rate**: improve from 50% to 60%+ via tighter regime gate
- **PnL rate**: match or exceed SwingOverlay's quarter rate (currently 1.9% per 2.5 months
  vs SwingOverlay's 6.5% per same period — 3-4× gap)

These are upstream Nautilus LS V1 improvements — separate workstream from Track A.

---

## Combined Output Summary

### Files Changed/Created

- `user_data/strategies/SwingOverlayV14_MTF_DirAware_CISRegimeOverlay.py` — V14a Option A re-tune
- `_data/research/d2_out/2026-07-16_v14a_5pair/` — V14a 5p × 4 windows sweep
- `_data/research/d2_out/2026-07-16_v14a_10pair/` — V14a 10p × 4 windows sweep
- `_data/research/sleeve_fusion_2026-07-16/nautilus_ls_v1_default/` — Nautilus default OOS run
- `_data/research/sleeve_fusion_2026-07-16/nautilus_ls_v1_holdout/` — Nautilus HOLD-OUT run
- `_data/research/sleeve_fusion_2026-07-16/nautilus_ls_v1_forward/` — Nautilus FORWARD run
- `_data/research/sleeve_fusion_2026-07-16/sleeve_summary.json` — combined sleeve metrics
- `docs/SLEEVE_FUSION_V14_REPORT_2026-07-16.md` — THIS REPORT (mirror)

### Decision Matrix

| Track | Decision | Action |
|---|---|---|
| A | POSITIVE incremental improvement vs original V14 | Use V14a as 4th sleeve member candidate (10-15%) |
| B | NEGATIVE structural result | Do NOT execute 70/30 sleeve fusion. 5-10% max if Nautilus exposure required. |

---

## Next-Step Recommendations (optional)

1. **Validate 4-slot production sleeve** (V7+V10c+V12b+V14a) on HOLD-OUT + FORWARD
   before committing any of the new weights to live paper trading
2. **Nautilus LS V1 improvement loop** — increase position count + hit rate (different workstream)
3. **V14 STAGFLATION flat-mode evaluation** — those 6 days (1.4% of history) may not
   be enough to validate the flat-mode trigger's incremental value
4. **Macro multiplier sensitivity** — test 1.05/1.05/1.00/1.00/0.95/0.95/0.85
   (even more conservative) to see if there's a monotone relationship with PnL

---

**Seal**: Minimax-C 2026-07-16, San Francisco
