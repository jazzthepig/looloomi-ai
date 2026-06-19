# Dev Progress — 2026-03-23

## Today

### Code Review Fixes (commit 76d6f6a)

**Critical Fixes:**
- [x] CoinGecko Pro API: cis_provider.py now uses Pro endpoint when COINGECKO_API_KEY set
  - `_cg_base()` / `_cg_headers()` helper functions
  - 500 calls/min vs 10-30 calls/min free tier
- [x] FNG masking: MacroPulse.jsx no longer masks API failures as neutral (50)
  - fngValue = null when API unavailable
  - calculateRegime() handles null by falling back to BTC 7d change only

**HIGH Fixes:**
- [x] MACRO_CACHE_PATH: Now configurable via env var (was hardcoded Mac Mini path)

**Verified Non-Issues (from code review):**
- [x] Duplicate router registration — main.py only has one include_router set
- [x] Non-pooled Redis — data_layer.py already uses `_get_redis_client()` pooled
- [x] VaultPage mock data — already returns empty [] on API failure
- [x] Blocking time.sleep — already uses await asyncio.sleep() and asyncio.to_thread()

## 2026-03-19

### Completed

**Phase 1 - Fix the Foundation:**
- [x] Fix agent API pillar keys (f/m/r/s/a instead of pillars.F/M/O/S/A)
- [x] Fix agent API score key (cis_score)
- [x] Add trading agent fields: ch30d, ch7d, vol, mc, vol24h, tvl, conf
- [x] WebSocket broadcast includes full pillar data
- [x] main.py split into routers (done previously)

**CIS Scoring Enhancements (done previously):**
- [x] F pillar: DeFiLlama TVL + CoinGecko FDV
- [x] S pillar: 30d rolling betas (DXY, VIX, 10Y)
- [x] BTC benchmark: SPY (cross-asset alpha)
- [x] Backtest: Binance/OKX klines instead of CoinGecko

### Agent API Response Example
```json
{
  "s": "BTC", "g": "A+", "sc": 51.9, "sg": "STRONG BUY",
  "f": 75, "m": 68, "r": 45, "ss": 27.5, "a": 20,
  "ch30d": 0, "ch7d": 0, "vol": 5.1,
  "mc": 1416330645372, "vol24h": 42310371142,
  "tvl": 0, "conf": 0.83
}
```

## Phase 2-4 (Roadmap A2A)

- Phase 2: Agent Discovery + MCP Server
- Phase 3: Solana Agent Infrastructure
- Phase 4: Competitive Moat
