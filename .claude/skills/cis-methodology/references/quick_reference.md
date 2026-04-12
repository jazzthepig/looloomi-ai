# CIS v4.1 Quick Reference

One-page cheat sheet. For full spec see `CIS_METHODOLOGY.md`.

## Pillar formulas (continuous, no step functions)

### F — Fundamental
- mcap_score = min(50, 10 × log₁₀(mcap / 1M))
- tvl_score = min(20, 5 × log₁₀(tvl / 1M))  [DeFi/L2 only; else redistribute to mcap cap=70]
- fdv_score = max(0, 15 × (1 - fdv/mcap) / 4)
- supply_score = 15 × (circ / total)
- F = mcap + tvl + fdv + supply  [max 100]

### M — Momentum
- vol_score = min(40, 8 × log₁₀(vol_24h / 100K))
- liq_ratio = min(25, vol_24h / mcap × 200)
- price_mom = linear_interp(-50%→0, 0%→15, +50%→30, +100%→35)
- M = vol + liq + price_mom  [max 100]

### O — On-Chain / Risk-Adjusted
T1: sharpe_score + mdd_score + tvl_stability  [35+35+30]
T2: ath_recovery + drawdown_estimate + supply_tvl  [35+35+30]

### S — Sentiment
- baseline: crypto = FNG × 0.4 [0-40], TradFi = VIX_inverse [0-40]
- divergence: asset_30d vs category_median_30d [clamped -15 to +25] + 24h burst [-5 to +10]
- vol_regime: breakout +15, capitulation -10, accumulation +10, stagnation -5
- S = baseline + divergence + vol_regime  [max 100]

### A — Alpha Independence
- benchmark_div: 30d return vs BTC(crypto)/SPY(equity)/-SPY(bond) → min(40, max(-20, div × 0.8))
- class_premium: DeFi/RWA > L1 > Meme [0-20]
- size_efficiency: smaller cap + strong score → bonus [-5 to +20]
- correlation_discount: high beta → penalty [-15 to 0]
- A = div + class + size + corr  [max ~80 practical]

## Composite
CIS = Σ(pillar × weight_by_class)
Weights: see SKILL.md table. T1 applies regime adjustment. T2 does not.

## Grading
A+ ≥85 | A ≥75 | B+ ≥65 | B ≥55 | C+ ≥45 | C ≥35 | D ≥25 | F <25

## Signals (positioning language ONLY)
A+: STRONG OUTPERFORM | A,B+: OUTPERFORM | B,C+: NEUTRAL | C: UNDERPERFORM | D,F: UNDERWEIGHT

## LAS
LAS = CIS × min(1.0, vol_24h × 0.10 / 1.5M) × confidence
Spread penalty if 24h range > 5%: × max(0.8, 1.0 - (range - 0.05) × 2)

## Confidence
Sum of available data weights. T1: 0.85-1.00. T2: 0.50-0.70.
Display: ≥0.7 full grade | 0.5-0.7 ~grade | <0.5 no grade

## Data tier badges
T1: "CIS PRO · LOCAL ENGINE" (green) — Mac Mini scoring
T2: "CIS MARKET · ESTIMATED" (amber) — Railway fallback

## Regime (T1 only)
RISK_ON | RISK_OFF | TIGHTENING | EASING | STAGFLATION | GOLDILOCKS
