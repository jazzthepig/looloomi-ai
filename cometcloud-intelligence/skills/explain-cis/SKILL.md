---
name: explain-cis
description: Explain the CometCloud Intelligence Score (CIS) methodology to any audience — from retail users to institutional investors. Use when asked "what is CIS?", "how does CIS work?", "explain the scoring", "what does the grade mean?", "what is OUTPERFORM?", "explain the five pillars", or "what is LAS?". Adapts explanation depth to the audience.
---

# Explain CIS — CometCloud Intelligence Score

## What CIS is

CIS (CometCloud Intelligence Score) is a 0–100 composite intelligence score across
five pillars, applied to crypto assets, TradFi instruments, and commodities.
It is used to rank assets by multi-dimensional quality, not just price momentum.

The score is produced by two engines:
- **T1 (Mac Mini local engine):** Full 5-pillar scoring with real DeFiLlama TVL,
  Binance market depth, on-chain data, and Qwen3 35B macro analysis. ~25 assets.
- **T2 (Railway CoinGecko estimation):** Market estimation using CoinGecko data.
  ~60 additional assets.

## The Five Pillars

| Pillar | Abbreviation | Weight* | What it measures |
|--------|-------------|---------|-----------------|
| Fundamental | F | 20–35% | Project quality, tokenomics, TVL, development activity |
| Market Structure | M | 20–25% | Liquidity, spreads, volume depth, trading quality |
| On-chain / Risk | O | 15–25% | Real on-chain activity, holder behavior, smart money flows |
| Sentiment | S | 15–35% | Fear & Greed Index, social divergence, volatility regime |
| Alpha Independence | A | 10–15% | BTC/SPY factor regression — how much independent return |

*Weights vary by asset class and macro regime.

## Grades

| Grade | Score range | Meaning |
|-------|------------|---------|
| A+ | 85–100 | Exceptional — strong across all pillars |
| A  | 75–84  | High quality positioning |
| B+ | 65–74  | Above average |
| B  | 55–64  | Qualified — benchmark weight |
| C+ | 45–54  | Watchlist — underweight relative to benchmark |
| C  | 35–44  | Below average |
| D  | 25–34  | Weak — significant underperformance risk |
| F  | 0–24   | Excluded — not eligible for allocation |

## Signals (positioning language only)

| Signal | CIS range | Meaning |
|--------|----------|---------|
| STRONG OUTPERFORM | A+ (85+) | Top-tier positioning relative to benchmark |
| OUTPERFORM | A–B+ (65–84) | Above-benchmark positioning |
| NEUTRAL | B (55–64) | Benchmark-weight |
| UNDERPERFORM | C+–C (35–54) | Below-benchmark positioning |
| UNDERWEIGHT | D–F (<35) | Bottom-tier positioning |

Note: These are positioning signals, not trading recommendations. CometCloud does
not hold a Hong Kong SFC Type 4 or Type 9 license.

## LAS (Liquidity-Adjusted Score)

LAS = CIS × liquidity_multiplier × confidence

- `liquidity_multiplier`: 0.7–1.0 based on market depth and spread quality
- `confidence`: 0–100% based on data completeness (how many pillar inputs were available)

LAS is the score used for actual portfolio weighting — it down-weights assets with
thin liquidity or incomplete data, even if their raw CIS is high. Agents should use
LAS for allocation decisions.

## Macro Regime

The regime affects pillar weights and score dampeners:

| Regime | S pillar | A pillar | Effect |
|--------|---------|---------|--------|
| RISK_ON | Normal | Normal | No adjustment |
| RISK_OFF | Reduced weight | BTC corr floor -8 (not -15) | Divergence dampened |
| GOLDILOCKS | Boosted | Normal | Sentiment drives more |
| STAGFLATION | Reduced | Inverted | Defensive assets score higher |
| TIGHTENING | Reduced | Normal | Rate-sensitive assets penalized |
| EASING | Boosted | Normal | Risk assets favored |

## How to adapt the explanation

**For retail / first-time user:**
"CIS is a 0–100 score that measures how well-positioned an asset is across five
dimensions — fundamentals, market quality, on-chain health, sentiment, and how
independently it moves from Bitcoin. Higher score = stronger positioning. A+ is
the top tier, F means the asset is excluded from consideration."

**For institutional investor:**
Use the full table above. Emphasize: regime-aware weights, LAS for allocation,
T1 vs T2 data tier distinction, and that signals are positioning-only per SFC rules.

**For AI agent:**
Point to `GET /api/v1/agent/cis` for machine-readable scores. Explain key fields:
`cis_score`, `raw_cis_score`, `las`, `grade`, `signal`, `data_tier`, `confidence`,
`pillars` (F/M/O/S/A), `macro_regime`.
