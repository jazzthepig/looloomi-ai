# COMETCLOUD HEALTH CHECK — 2026-04-19 (Scheduled Run)

```
══════════════════════════════════════════════════════════

MACRO PULSE    ❌ UNREACHABLE — Egress blocked by network proxy
CIS UNIVERSE   ❌ UNREACHABLE — Egress blocked by network proxy
SIGNAL FEED    ❌ UNREACHABLE — Egress blocked by network proxy
TOP ASSETS     ❌ UNREACHABLE — Egress blocked by network proxy

OVERALL: 🟡 UNABLE TO VERIFY — All endpoints blocked by egress proxy
```

## What happened

All four health check endpoints returned `EGRESS_BLOCKED` errors:

- `https://web-production-0cdf76.up.railway.app/api/v1/market/macro-pulse`
- `https://web-production-0cdf76.up.railway.app/api/v1/cis/universe`
- `https://web-production-0cdf76.up.railway.app/api/v1/signals`
- `https://web-production-0cdf76.up.railway.app/api/v1/cis/top`

The Cowork session's network egress proxy does not allow outbound connections to `web-production-0cdf76.up.railway.app`. This is a session-level network restriction, **not** a Railway or CometCloud issue.

## Root cause

The CometCloud MCP tools (which previously provided authenticated access to these endpoints) are not connected in this Cowork session. Without either MCP tools or direct network access, the monitor cannot reach Railway.

## ACTION NEEDED

1. **Reconnect CometCloud MCP** — The scheduled monitor depends on either:
   - The CometCloud MCP server being connected (tools like `cometcloud_get_macro_pulse`, `cometcloud_get_cis_universe`, etc.), OR
   - The Railway domain being allowlisted for network egress in the Cowork session

2. **Manual spot-check recommended** — Until the monitor can reach the endpoints, Jazz or Seth should manually verify:
   - Open `https://web-production-0cdf76.up.railway.app/api/v1/market/macro-pulse` in a browser
   - Open `https://web-production-0cdf76.up.railway.app/api/v1/cis/universe` in a browser
   - Confirm BTC price > 0, universe_size >= 50, and signals are flowing

3. **Known pre-existing issues (from CLAUDE.md as of Apr 2):**
   - CIS universe was **EMPTY** — Mac Mini not pushing + Railway CoinGecko key possibly missing
   - MCP CIS universe was **BROKEN** (pending MCP restart)
   - MCP Signal feed was **BROKEN** (pending MCP restart)
   - Supabase env vars (`SUPABASE_URL`, `SUPABASE_KEY`) may still be missing from Railway

## Previous known-good state (from CLAUDE.md, 2026-04-02)

| Endpoint       | Status        | Detail                                      |
|----------------|---------------|----------------------------------------------|
| Macro Pulse    | ✅ LIVE       | BTC=$68,795, F&G=8 (Extreme Fear), Dom=56.3% |
| DeFi Overview  | ✅ LIVE       | DeFiLlama $92B TVL                           |
| Signal Feed    | ✅ LIVE       | 19 signals with full data                    |
| CIS Universe   | ⚠️ DEGRADED  | 70 assets via fallback, T2 only              |

---

*Next scheduled run will retry. Reconnect MCP or allowlist Railway domain to restore monitoring.*
