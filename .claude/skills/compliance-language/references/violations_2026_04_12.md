# Compliance Violations Found — 2026-04-12

Audit run by Seth as part of Phase A skill structure buildout. All violations
are in live code that is either deployed or could be deployed.

## User-facing (MUST FIX before any investor-facing demo)

### AssetRadar.jsx (line 88-92)
Signal color map still uses old labels:
```js
"STRONG BUY": { color: T.green, ... },
BUY:          { color: T.green, ... },
AVOID:        { color: T.red, ... },
```
**Fix:** Replace keys with STRONG OUTPERFORM / OUTPERFORM / UNDERWEIGHT.

### CISWidget.jsx (line 36)
Signal badge map includes:
```js
"AVOID": { bg: "rgba(220,38,38,0.15)", color: "#dc2626", label: "VERY LOW" },
```
**Fix:** Replace key with UNDERWEIGHT.

### MobileApp.jsx (lines 28-29, 179)
Color map and comment use old signal names:
```js
"STRONG BUY": "#00E87A", BUY: "#4B9EFF", HOLD: "#9CA3AF",
REDUCE: "#E8A000", AVOID: "#FF3D5A",
// comment: "BUY or STRONG BUY"
```
**Fix:** Full signal map replacement + comment rewrite.

### CIS_METHODOLOGY.md (line 48)
Schema example shows old signal enum:
```
"signal": str,  // STRONG BUY / BUY / HOLD / REDUCE / AVOID
```
**Fix:** Replace with STRONG OUTPERFORM / OUTPERFORM / NEUTRAL / UNDERPERFORM / UNDERWEIGHT.

## Backend (internal-facing but could leak)

### mmi_index_v3.py (lines 149, 157)
Generates literal user-facing strings:
```python
return "🔴 SELL SIGNAL - Market overheated"
return "🟢🟢 STRONG BUY - Extreme fear = opportunity"
```
**Fix:** Replace with positioning language. This is used in the MMI API response.

### market.py (line 933)
Regime context string:
```python
"AVOID new longs; consider reducing exposure on bounces."
```
**Fix:** Rewrite with positioning language.

### protocol_engine.py (line 12)
Docstring mentions old signal names:
```python
Output: CIS grade (A+ → F), signal (ACCUMULATE/HOLD/REDUCE/AVOID),
```
**Fix:** Rewrite docstring.

## Already correct (no action needed)

### cometcloud_mcp.py (lines 60, 298, 778)
Uses BUY/SELL in the context of "Do NOT interpret as BUY/SELL recommendations" —
this is the correct usage: warning consumers not to use advisory language.

## Summary

| Severity | Count | Files |
|---|---|---|
| User-facing | 4 files | AssetRadar.jsx, CISWidget.jsx, MobileApp.jsx, CIS_METHODOLOGY.md |
| Backend (leakable) | 3 files | mmi_index_v3.py, market.py, protocol_engine.py |
| Correctly used | 1 file | cometcloud_mcp.py |
| **Total violations** | **7 files, ~12 instances** | |

## Recommended action

Fix the 4 user-facing files first. These are the ones Nic would show to family
offices. Backend fixes can be batched in a single compliance sweep commit.
