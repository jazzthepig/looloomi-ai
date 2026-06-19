# COMETCLOUD HEALTH CHECK — 2026-04-21 (Scheduled Run)

```
══════════════════════════════════════════════════════════

MACRO PULSE    ⛔ UNREACHABLE — egress proxy blocks Railway domain
CIS UNIVERSE   ⛔ UNREACHABLE — egress proxy blocks Railway domain
SIGNAL FEED    ⛔ UNREACHABLE — egress proxy blocks Railway domain
TOP ASSETS     ⛔ UNREACHABLE — egress proxy blocks Railway domain

OVERALL: ⚪ UNABLE TO VERIFY — network egress blocked

══════════════════════════════════════════════════════════
```

## Details

All endpoints (`web-production-0cdf76.up.railway.app` and `looloomi.ai`) are
blocked by the Cowork sandbox network egress proxy. Health checks cannot be
performed from this environment.

## Attempted endpoints

- `https://web-production-0cdf76.up.railway.app/api/v1/market/macro-pulse`
- `https://web-production-0cdf76.up.railway.app/api/v1/cis/universe`
- `https://web-production-0cdf76.up.railway.app/api/v1/signals`
- `https://web-production-0cdf76.up.railway.app/api/v1/cis/top`

## Known status (from CLAUDE.md as of Apr 19)

- **CIS Universe**: EMPTY — `COINGECKO_API_KEY` missing from Railway env vars
- **Macro Pulse**: LIVE (as of Apr 19)
- **Signal Feed**: LIVE (as of Apr 19)
- **MacroBrief**: NULL — Mac Mini LM Studio pipeline not connected
- **Economic Indicators**: EMPTY — EODHD API key missing/expired
- **Supabase**: env vars not set in Railway

## ACTION NEEDED

1. **Add Railway domain to egress allowlist** — `web-production-0cdf76.up.railway.app`
   must be allowlisted for automated health checks to function from Cowork sessions.
   (Team/Enterprise admins: Admin settings → Capabilities → Network access)

2. **Pending from Week 5 (unchanged)**:
   - Jazz: Set `COINGECKO_API_KEY`, `SUPABASE_URL`, `SUPABASE_KEY` in Railway dashboard
   - Minimax: Restart `cis_scheduler.py` to push clean universe
   - Minimax: Rotate EODHD + Finnhub API keys

---
*Automated monitor — next run will retry. Manual verification recommended via browser.*
