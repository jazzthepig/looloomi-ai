# CometCloud AI — Project Status
*Updated: 2026-04-10*

---

## Production State

| System | Status | Notes |
|--------|--------|-------|
| Railway (backend) | ⚠️ PENDING PUSH | Commit ready, blocked by git index.lock |
| CIS Universe | ⚠️ T2 FALLBACK | Mac Mini not pushing + CoinGecko key missing in Railway |
| Macro Pulse | ✅ LIVE | BTC price, FNG, dominance live |
| Signal Feed | ✅ LIVE | 19 signals with full data |
| MCP Server | ⚠️ STALE | Working but needs restart after git push |
| Supabase | ⚠️ ENV VARS MISSING | Tables exist, env vars not in Railway |
| agent.html | ⚠️ BUILT, NOT DEPLOYED | In dist/, waiting for push |
| analytics.html | ⚠️ BUILT, NOT DEPLOYED | In dist/, waiting for push |
| portfolio.html | ⚠️ BUILT, NOT DEPLOYED | In dist/, waiting for push |

---

## Jazz: 3 Steps To Unblock Everything (10 min total)

### Step 1 — Mac Mini terminal
```bash
cd /Users/sbb/Projects/looloomi-ai
rm -f .git/index.lock .git/HEAD.lock
git add src/ dashboard/src/ dashboard/dist/ \
        dashboard/agent.html dashboard/analytics.html \
        dashboard/portfolio.html dashboard/vite.config.js
git commit -m "Phase 0: inclusion standard, exclusion list, agent API page, 3 new MCP tools, HumbleBee fix"
git push origin main
```

### Step 2 — Railway Variables
Go to Railway → your service → Variables → add:
- `COINGECKO_API_KEY` = CoinGecko Pro key
- `SUPABASE_URL` = `https://soupjamxlfsmgmmtoeok.supabase.co`
- `SUPABASE_KEY` = service_role key

### Step 3 — Restart Claude Desktop
MCP reloads with 3 new tools (get_cis_exclusions, get_inclusion_standard, get_regime_context).

---

## Built This Session (Apr 9-10)

### Documents
- `INCLUSION_STANDARD.md` v1.1 — 7-criterion institutional standard, alpha-preserving
- `EXCLUSION_LIST.md` v1.1 — 14 confirmed exclusions; HYPER reinstated
- `DECISIONS.md` — all 8 PRD open questions answered and logged

### Backend
- `src/api/routers/cis.py` — 2 new endpoints: /api/v1/agent/cis-exclusions + /api/v1/agent/inclusion-standard
- `src/mcp/cometcloud_mcp.py` — 3 new MCP tools + get_vc_funding renamed to get_institutional_flows

### Frontend
- `/agent.html` — Agent API page (MCP tools, pricing, key request form)
- `/analytics.html` — Standalone Score Analytics page
- `/portfolio.html` — Standalone Portfolio page
- All HumbleBee Capital fixes across 6 files

---

## Minimax: What To Do Today

See MINIMAX_SYNC.md §4 for full detail. Short version:

P0 (now):
1. Rotate EODHD + Finnhub keys (exposed in git history)
2. cp Shadow/cometcloud-local/data_fetcher.py → /Volumes/CometCloudAI/cometcloud-local/
3. cp Shadow/cometcloud-local/config.py → /Volumes/CometCloudAI/cometcloud-local/
4. Restart cis_scheduler.py
5. Verify Redis cis:local_scores has data

P1 (this week):
6. Remove 14 excluded assets from cis_v4_engine.py (list in MINIMAX_SYNC.md §4A)
7. Keep HYPER — reinstated under v1.1 standard
8. Add LAS field to local engine output
9. Run Freqtrade T1 backtest → report PF/WR/MaxDD

---

## MCP Server — 19 Tools

Free tier: get_cis_universe, get_cis_asset, get_cis_top, get_cis_report, get_regime_context,
           get_macro_pulse, get_signal_feed, get_macro_events, get_institutional_flows,
           get_protocols, get_defi_overview, get_defi_yields, get_prices, get_market_movers,
           get_fund_portfolio, get_portfolio_stats

Pro tier ★: get_cis_exclusions (unique — no other MCP server has this),
            get_inclusion_standard, get_cis_history

---

## One Open Decision

RUNE (Thorchain): Include with "remediated" tag or exclude?
3+ years clean since 2021 exploits. Partial user compensation (unclear if ≥80%).
Default: provisionally included with flag. Jazz decides when back.
