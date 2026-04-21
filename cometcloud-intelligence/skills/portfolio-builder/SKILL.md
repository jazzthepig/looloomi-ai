---
name: portfolio-builder
description: Build a CIS-weighted portfolio from CometCloud's scored universe. Use when asked "build me a portfolio", "create an allocation", "CIS-weighted portfolio for $X", "what should I put $X in", "portfolio for [risk level]", or "show me the top assets to position in". Returns a compliance-language portfolio with CIS grades, weights, and LAS-adjusted positioning — not investment advice.
---

# Portfolio Builder — CIS-Weighted Allocation

## Process

1. Fetch the full CIS universe:
   ```
   GET https://looloomi.ai/api/v1/cis/universe
   ```

2. Apply filters based on user requirements:
   - Risk profile: Conservative (B+ and above only), Moderate (B and above), Aggressive (all C+ and above)
   - Asset class preference: e.g., "only crypto", "no memecoins", "include TradFi"
   - Minimum score: user can specify

3. Compute weights:
   - Base weight = LAS / sum(all LAS in selection) — proportional to liquidity-adjusted score
   - Cap individual positions at 20% (concentration limit)
   - Minimum position size: 2% (round out or drop below threshold)

4. Format the allocation:

```
## CIS-Weighted Portfolio — [risk_profile] | [date]
**Universe:** [N] assets screened | [M] selected
**Macro regime:** [regime]
**Data tiers:** [T1 count] Local Engine, [T2 count] Estimated

| Rank | Symbol | Grade | Signal | CIS | LAS | Weight |
|------|--------|-------|--------|-----|-----|--------|
|  1   | SOL    | A+    | STRONG OUTPERFORM | 88 | 82 | 20.0%  |
|  2   | BTC    | A     | OUTPERFORM        | 79 | 76 | 17.4%  |
| ...  | ...    | ...   | ...               | .. | .. | ...    |

**Total allocation: 100%**

---
*This allocation reflects CIS positioning scores as of [timestamp]. It is not
investment advice. CometCloud AI does not hold an SFC Type 4 or Type 9 license.
All signals use positioning language only.*
```

## Risk profiles

| Profile | CIS floor | Grade floor | Max assets |
|---------|-----------|-------------|------------|
| Conservative | 65 | B+ | 8 |
| Moderate | 55 | B | 12 |
| Balanced | 45 | C+ | 15 |
| Aggressive | 35 | C | 20 |

## Asset class constraints

Default allocation caps by class (prevents over-concentration):
- L1 chains: max 40% of portfolio
- DeFi: max 30%
- RWA: max 20%
- Meme/Gaming: max 10%
- TradFi (equity, bond, commodity): max 30%

## Compliance

All signals must be OUTPERFORM / NEUTRAL / UNDERPERFORM language.
The portfolio output must include the disclaimer about positioning-only signals.
Never use BUY/SELL/ACCUMULATE/AVOID language anywhere in the output.
