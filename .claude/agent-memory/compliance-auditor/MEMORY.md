# Compliance Auditor — Agent Memory

## Codebase compliance status (as of 2026-04-12)

### Post-sweep state
Full audit run on 2026-04-12. All 12 violations fixed in commit 6c09dad.
Codebase is currently CLEAN for user-facing signal language.

### Files that had violations (watch for regression)
- `dashboard/src/components/AssetRadar.jsx` — had legacy compat signal map (BUY/AVOID keys)
- `dashboard/src/components/CISWidget.jsx` — had legacy compat (AVOID key)  
- `dashboard/src/components/MobileApp.jsx` — had legacy compat map + comment referencing "BUY or STRONG BUY"
- `CIS_METHODOLOGY.md` — schema example used old signal enum
- `src/analytics/mmi/mmi_index_v3.py` — get_signal() returned "SELL SIGNAL" and "STRONG BUY" strings
- `src/api/routers/market.py` — regime context string used "AVOID new longs"
- `src/data/market/protocol_engine.py` — docstring used ACCUMULATE/HOLD/REDUCE/AVOID

### Known-safe exception files (don't flag these)
- `.claude/skills/compliance-language/` — rule documentation
- `CIS_METHODOLOGY.md` "DO NOT USE" sections — rule documentation
- `CLAUDE.md` compliance section — rule documentation
- `src/mcp/cometcloud_mcp.py` lines 60/298/778 — "Do NOT interpret as BUY/SELL recommendations"
- `Shadow/freqtrade/` — Freqtrade uses BUY/SELL as internal API terms, never surfaces to users

### Common false positives in this codebase
- "buying pressure" / "selling pressure" in market commentary — fine (describes market dynamics, not recommendations)
- "buyer/seller" in liquidity context — fine
- Historical backtest output: "strategy entered BUY on [date]" — fine in methodology docs (past tense, factual)
- `data_fetcher.py` BUY/SELL in Binance kline context — internal only

## Signal language pattern (correct)
STRONG OUTPERFORM / OUTPERFORM / NEUTRAL / UNDERPERFORM / UNDERWEIGHT
ZH: 强烈看好 / 看好 / 中性 / 看淡 / 低配

## Next audit trigger
Next full audit recommended before any investor-facing demo or Nic presentation.
Run: `rg -i -g '!node_modules' -g '!dashboard/dist' -g '!Shadow/' -e 'STRONG BUY|"BUY"|"SELL"|ACCUMULATE|AVOID|REDUCE' src/ dashboard/src/ CIS_METHODOLOGY.md`
