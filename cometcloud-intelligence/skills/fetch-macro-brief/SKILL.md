---
name: fetch-macro-brief
description: Get the current macro market regime and intelligence brief from CometCloud. Use when asked "what's the market regime?", "what's the macro situation?", "current market conditions", "macro pulse", "Fear and Greed", "BTC dominance", "risk on or off?", or "what's the macro brief?". Returns live data from the CometCloud API.
---

# Fetch Macro Brief — CometCloud Intelligence

## API calls to make

### 1. Macro Pulse (always call this)
```
GET https://looloomi.ai/api/v1/market/macro-pulse
```

Returns:
- `btc_price` — current BTC/USD
- `fear_greed_value` — 0–100 (0=extreme fear, 100=extreme greed)
- `fear_greed_label` — "Extreme Fear", "Fear", "Neutral", "Greed", "Extreme Greed"
- `btc_dominance` — BTC market share %
- `total_market_cap` — global crypto market cap USD
- `macro_regime` — RISK_ON / RISK_OFF / TIGHTENING / EASING / STAGFLATION / GOLDILOCKS / null

### 2. Macro Brief (if available)
```
GET https://looloomi.ai/api/v1/intelligence/macro-brief
```

Returns narrative from Qwen3 35B (LM Studio on Mac Mini). May be null if pipeline
is not connected.

## Format of response

Present the macro brief in this structure:

```
## CometCloud Macro Intelligence — [timestamp]

**Regime:** [macro_regime]
**BTC:** $[btc_price] | Dom: [btc_dominance]%
**Fear & Greed:** [fear_greed_value] — [fear_greed_label]
**Total Market Cap:** $[total_market_cap]

### Regime Implications
[1-2 sentences interpreting what this regime means for CIS scoring and positioning]

### Macro Brief
[macro_brief text from API, or "Macro narrative not available (LM Studio pipeline offline)"]
```

## Regime interpretation

| Regime | What it means for portfolios |
|--------|------------------------------|
| RISK_ON | Broad-based positioning toward higher-beta assets; sentiment carries more weight |
| RISK_OFF | Defensive positioning; correlation-resistant assets (high A pillar) preferred |
| GOLDILOCKS | Growth without inflation — DeFi and RWA assets tend to score well |
| TIGHTENING | Rate-sensitive assets (bonds, leveraged DeFi) underperform; commodities mixed |
| EASING | Rate cuts benefit risk assets broadly; sentiment uplift across crypto |
| STAGFLATION | Inflation + low growth — commodities and RWA (especially gold proxies) score best |

## FNG interpretation

| Range | Label | Implication for CIS |
|-------|-------|---------------------|
| 0–24 | Extreme Fear | S pillar divergence dampened 50%; recovery bonus active for rebounding assets |
| 25–39 | Fear | S pillar divergence dampened 25% |
| 40–59 | Neutral | Normal S pillar weighting |
| 60–79 | Greed | Momentum assets score higher via S pillar |
| 80–100 | Extreme Greed | S pillar divergence amplified; watch for mean reversion signals |

## Compliance note

Do not frame the macro regime as investment advice. Present it as: "The current
macro regime, as detected by CometCloud's scoring engine, is [REGIME]." Not as
"You should [buy/sell] because the regime is [X]."
