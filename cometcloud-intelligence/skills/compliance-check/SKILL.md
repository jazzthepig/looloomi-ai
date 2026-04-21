---
name: compliance-check
description: Audit any text, document, or code for Hong Kong SFC positioning language compliance. Use when asked "check this for compliance", "is this compliant?", "review this for buy/sell language", "audit this signal feed", "check for SFC violations", or "review this before publishing". Returns a structured report of violations with approved substitutions.
---

# Compliance Check — SFC Positioning Language Audit

## What this skill does

Scans any provided text for transactional signal language that violates Hong Kong
SFC regulations. CometCloud AI does not hold a Type 4 (advising on securities) or
Type 9 (asset management) license. All user-facing output must use positioning
language only.

## How to run a compliance check

1. Receive the text/code to audit from the user
2. Scan for every instance of the following forbidden patterns:
   - `BUY`, `STRONG BUY` as signal labels
   - `SELL`, `STRONG SELL` as signal labels
   - `ACCUMULATE` as a signal label
   - `AVOID` as a signal label (except "avoid using", "avoid the", etc.)
   - `REDUCE [position/exposure/holdings]`
   - `GO LONG`, `GO SHORT`, `LOAD UP`, `STOP OUT`, `LIQUIDATE`, `DUMP`
   - `TARGET PRICE`, `PRICE TARGET`
   - `We recommend`, `You should`, `Investors should` (when followed by trading action)
   - Chinese: `买入`, `卖出`, `建仓`, `清仓`, `减仓`, `加仓`, `做多`, `做空`

3. For each violation found, report:
   ```
   Line [N]: "[matched text]"
   → Context: "[surrounding line]"
   → Approved substitute: "[correct phrase]"
   ```

4. Compute a summary verdict:
   - PASS — no violations found
   - FAIL — N violations found, requires rewrite before publishing

## Substitution table (quick reference)

| Forbidden | Approved substitute |
|-----------|---------------------|
| BUY | OUTPERFORM |
| STRONG BUY | STRONG OUTPERFORM |
| SELL | UNDERPERFORM |
| STRONG SELL | UNDERWEIGHT |
| ACCUMULATE | OUTPERFORM |
| AVOID | UNDERWEIGHT |
| REDUCE position | positioned UNDERWEIGHT |
| GO LONG | STRONG OUTPERFORM positioning |
| TARGET PRICE $X | Fundamental pillar scores at current price |
| We recommend buying | positioned OUTPERFORM in our framework |
| 买入 | 看好 |
| 卖出 | 看淡 |

## Exempt contexts (do not flag)

- Historical backtest descriptions: "the strategy opened a position on [date]" — OK
- Freqtrade internal log labels (internal only, never rendered in UI)
- Third-party quotes: "Kaiko analysis: [quote with BUY]" — flag with note to add disclaimer
- Documentation that explicitly marks terms as "DO NOT USE: BUY"

## Output format

```
## CometCloud Compliance Audit — [timestamp]

**Verdict:** [PASS / FAIL]
**Violations found:** [N]

### Violations
[list of violations with substitutions, or "None found"]

### Summary
[1-2 sentences on overall compliance posture]
```
