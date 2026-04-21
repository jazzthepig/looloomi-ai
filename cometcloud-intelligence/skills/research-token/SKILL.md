---
name: research-token
description: Deep research on any crypto or TradFi asset using CometCloud's CIS scoring engine. Use when asked to "research [token/asset]", "tell me about [symbol]", "analyze [asset]", "what's the CIS score for [symbol]", or "how does [token] score". Returns: 5-pillar CIS breakdown, grade, signal, liquidity-adjusted score, data tier, and market context. Compliant with Hong Kong SFC positioning language — all signals are positioning-only (OUTPERFORM / NEUTRAL / UNDERPERFORM), never transactional (BUY/SELL).
---

# Research Token — CometCloud Intelligence

## How to use this skill

When a user asks to research an asset, do the following:

1. Call the CometCloud CIS API for the specific asset:
   ```
   GET https://looloomi.ai/api/v1/cis/universe
   ```
   Filter the response for the requested symbol.

2. If not found in universe, call:
   ```
   GET https://looloomi.ai/api/v1/cis/top?limit=100
   ```

3. Format the response as a structured research brief:

```
## [SYMBOL] — CometCloud Intelligence Brief
**Asset class:** [asset_class]
**Data tier:** [T1 — Local Engine / T2 — Market Estimation]

### CIS Score
CIS: [cis_score] / 100 | Grade: [grade] | Signal: [signal]
Raw (no regime): [raw_cis_score] | LAS (liquidity-adj): [las]
Confidence: [confidence]%

### Five-Pillar Breakdown
F (Fundamental):  [F_score]/20 — [brief interpretation]
M (Momentum):     [M_score]/20 — [brief interpretation]
O (On-chain):     [O_score]/20 — [brief interpretation]
S (Sentiment):    [S_score]/20 — [brief interpretation]
A (Alpha):        [A_score]/20 — [brief interpretation]

### Context
Macro regime: [regime]
Category rank: [class_rank] of [class_total] in [asset_class]

### Positioning
[Signal] — [1-2 sentence positioning narrative using OUTPERFORM/NEUTRAL/UNDERPERFORM language]
```

## Compliance

- NEVER use BUY, SELL, STRONG BUY, ACCUMULATE, AVOID, REDUCE as signal labels
- Use: STRONG OUTPERFORM, OUTPERFORM, NEUTRAL, UNDERPERFORM, UNDERWEIGHT
- The narrative must be positioning-language only — not investment advice
- Always note data tier (T1 = Mac Mini engine, T2 = Railway estimate)

## Pillar interpretation guide

| Score | Interpretation |
|-------|---------------|
| 17–20 | Very strong — top decile for this pillar |
| 13–16 | Above average — positive contribution |
| 9–12  | Neutral — benchmark weight |
| 5–8   | Below average — mild drag |
| 0–4   | Weak — significant drag on overall score |
