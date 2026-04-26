# CometCloud Upgrade Roadmap — A2A Competitiveness
**Date:** 2026-03-19 · **Authors:** Seth + Austin

---

## Context

The agent-to-agent (A2A) landscape has moved fast. Google's A2A protocol hit v0.3 and moved to Linux Foundation. Anthropic donated MCP to the same foundation. Virtuals has 18K+ agents deployed with $450M+ "Agentic GDP." Olas hit 10M+ agent-to-agent transactions. ElizaOS owns 60% of Web3 agent dev market share. Bybit just launched 253 API endpoints for agent trading.

CometCloud's positioning — "built for human LPs and autonomous AI agents equally" — is no longer aspirational. It's table stakes. The fund that agents can't discover, query, or transact with doesn't exist in their world.

The good news: Minimax's WebSocket + Agent API (commit `21b0da3`) is the right instinct. The infrastructure gap is narrower than it looks.

---

## Current State vs. A2A-Ready State

| Layer | Current | Target |
|-------|---------|--------|
| **Discovery** | No agent registry | Agent Card (JSON) at `/.well-known/agent.json` |
| **Query** | `/api/v1/agent/cis` (broken pillar keys) | MCP server exposing fund data, CIS scores, history |
| **Real-time** | `/ws/cis` (basic broadcast) | A2A-compliant SSE task streaming |
| **Transactions** | None | Solana program-derived addresses with scoped session keys |
| **Payments** | None | x402-compatible or native USDC settlement |
| **Identity** | None | On-chain agent registry (ERC-8004 pattern adapted for Solana) |

---

## Phase 1: Fix the Foundation (Week 2-3, Mar 20 – Apr 2)

Fix the bugs that make the current agent surface broken or unsafe.

| # | Task | Owner | Effort |
|---|------|-------|--------|
| 1.1 | Fix agent API pillar keys (`F/M/O/S/A` not `Fundamental/Momentum/...`) | Seth | 15 min |
| 1.2 | Fix agent API score key (`score` not `cis_score`) | Seth | 5 min |
| 1.3 | Fix internal token auth (reject-by-default) | Seth | 15 min |
| 1.4 | Remove debug token leak from stdout | Seth | 5 min |
| 1.5 | Add CORS OPTIONS handler to Cloudflare proxy | Seth | 15 min |
| 1.6 | Fix WebSocket connection leak (dead connection cleanup) | Seth | 30 min |
| 1.7 | Split `main.py` into FastAPI routers | Seth | 3h |
| 1.8 | Add batch sparkline endpoint (`/api/v1/cis/history/batch`) | Seth | 2h |
| 1.9 | CoinGecko Pro upgrade (remove rate limit errors at scale) | Jazz | Config |

**Gate:** Agent API returns correct CIS data for all assets. WebSocket doesn't leak memory.

---

## Phase 2: Agent Discovery + MCP Server (Week 4-5, Apr 3 – Apr 16)

Make CometCloud discoverable and queryable by any A2A or MCP-compatible agent.

### 2.1 Agent Card (`/.well-known/agent.json`)
Standard A2A discovery document. Any compliant agent can find us.

```json
{
  "name": "CometCloud AI",
  "description": "AI-curated crypto Fund-of-Funds — CIS scoring, cross-asset analytics, institutional DeFi",
  "url": "https://looloomi.ai",
  "version": "1.0.0",
  "capabilities": {
    "cis_scoring": {
      "endpoint": "/api/v1/agent/cis",
      "format": "json",
      "assets": 50,
      "asset_classes": ["Crypto", "L1", "L2", "DeFi", "RWA", "US Equity", "US Bond", "Commodity"],
      "refresh_interval_seconds": 1800
    },
    "fund_data": {
      "endpoint": "/api/v1/vault/funds",
      "format": "json"
    },
    "realtime": {
      "websocket": "/ws/cis",
      "protocol": "json",
      "events": ["score_update", "signal_change"]
    }
  },
  "authentication": {
    "type": "bearer",
    "scopes": ["read:cis", "read:fund", "subscribe:realtime"]
  },
  "pricing": {
    "model": "free_tier",
    "rate_limit": "60/min"
  }
}
```

### 2.2 MCP Server for CIS Data ✅ COMPLETE (2026-04-26)
Expose CometCloud intelligence as an MCP tool server. Any MCP-compatible agent (Claude, GPT, Gemini, Cursor) can query CIS scores natively.

**Live endpoint:** `https://looloomi.ai/mcp/sse` (SSE transport)
**Message endpoint:** `https://looloomi.ai/mcp/messages`

**Tools deployed (7):**
- `cometcloud_get_cis_universe` — full leaderboard with grades, signals, pillars, LAS
- `cometcloud_get_cis_asset(symbol)` — single asset deep dive
- `cometcloud_get_macro_pulse` — regime, BTC, FNG, dominance
- `cometcloud_get_signal_feed` — 7-source signal feed
- `cometcloud_get_top_assets(n)` — top N by CIS score
- `cometcloud_get_macro_brief` — Qwen3 35B macro narrative
- `cometcloud_regime_allocation` — regime-aware allocation

**Implementation:** `src/mcp/cometcloud_mcp.py` (FastMCP, 2072 lines) mounted as ASGI sub-app inside FastAPI via `app.mount("/mcp", mcp.sse_app())`. Zero new Railway services — rides the existing worker. Fail-safe try/except keeps main app alive if dep missing.

**MCP config:** `cometcloud-intelligence/mcp/cometcloud.json` updated with `remote.url = "https://looloomi.ai/mcp/sse"`.

### 2.3 A2A Task Endpoint
Long-running analysis tasks for agent delegation.

```
POST /api/v1/agent/tasks
{
  "type": "portfolio_analysis",
  "params": {
    "target_return": 0.15,
    "max_drawdown": 0.10,
    "asset_classes": ["Crypto", "DeFi"],
    "horizon": "6m"
  }
}

→ 202 Accepted
{
  "task_id": "task_abc123",
  "status": "working",
  "poll": "/api/v1/agent/tasks/task_abc123",
  "stream": "/api/v1/agent/tasks/task_abc123/stream"
}
```

| # | Task | Owner | Effort |
|---|------|-------|--------|
| 2.1 | Create `/.well-known/agent.json` + serve via Cloudflare | Seth | 1h |
| 2.2 | Build MCP server (FastMCP) wrapping CIS + fund endpoints | Seth | 4h |
| 2.3 | Deploy MCP server to Railway (sidecar) or Cloudflare Worker | Seth | 2h |
| 2.4 | Implement `/api/v1/agent/tasks` with async task queue | Seth | 6h |
| 2.5 | Add SSE streaming for task progress | Seth | 3h |
| 2.6 | API key management (free tier: 60 req/min, pro: 600 req/min) | Seth | 3h |

**Gate:** External agent can discover CometCloud, query CIS data via MCP, and submit analysis tasks.

---

## Phase 3: Solana Agent Infrastructure (Week 6-8, Apr 17 – May 7)

On-chain layer for agent transactions. This is where CometCloud becomes a real A2A participant, not just a data provider.

### 3.1 Agent Wallet Program (Solana)
Program-derived addresses (PDAs) with scoped session keys. Agents get temporary transaction authority within pre-approved risk limits — no private key exposure.

**Design:**
- LP creates a vault position → grants agent PDA with constraints: max position size, allowed asset classes, daily loss limit, expiry
- Agent trades within scope → settlement auto-deducts performance fee
- Revocation: LP or admin can revoke PDA instantly

### 3.2 CIS Oracle (On-Chain)
Push CIS scores to Solana as an oracle feed. Other Solana programs can gate operations on CIS grade (same pattern as Freqtrade's CIS gate, but on-chain).

```
CIS Oracle Account:
  authority: CometCloud multisig
  scores: HashMap<Pubkey, CISScore>
  last_updated: i64

CISScore:
  symbol: String
  score: u8
  grade: u8  // A+=7, A=6, B+=5, B=4, C+=3, C=2, D=1, F=0
  signal: u8 // STRONG_BUY=4, BUY=3, HOLD=2, REDUCE=1, AVOID=0
  timestamp: i64
```

### 3.3 Agent Payment Rails
USDC settlement for agent interactions. Performance fees auto-collected via Solana program instruction on position close.

| # | Task | Owner | Effort |
|---|------|-------|--------|
| 3.1 | Design Solana agent wallet program (Anchor) | Austin | 2w |
| 3.2 | CIS Oracle program — push scores on-chain every 30 min | Seth + Minimax | 1w |
| 3.3 | Agent payment settlement program (USDC) | Austin | 1w |
| 3.4 | Integration test: agent discovers → queries CIS → deposits → trades → settles | All | 3d |

**Gate:** End-to-end agent lifecycle on Solana testnet.

---

## Phase 4: Competitive Moat (Week 9-12, May 8 – Jun 3)

### 4.1 CIS-as-a-Service
Other protocols can consume CIS scores via MCP or on-chain oracle. This makes CometCloud the scoring layer of the agent economy, not just a fund.

**Revenue:** Per-query pricing via x402 or subscription tiers.

### 4.2 Agent Marketplace
Curated registry of agents that can interact with CometCloud vaults. Think Olas "Agent App Store" but scoped to institutional DeFi.

**Categories:**
- Rebalancing agents (auto-rebalance vault based on CIS signals)
- Arbitrage agents (cross-venue execution)
- Risk monitoring agents (alert on drawdown, grade degradation)
- Research agents (generate investment memos from CIS + on-chain data)

### 4.3 Cross-Chain Agent Bridge
Accept agent deposits from Ethereum, Base, Arbitrum via Wormhole/Stargate → auto-convert to Solana position. Agents don't need to be on Solana natively to use CometCloud.

### 4.4 ElizaOS Plugin
60% of Web3 agent development uses ElizaOS. A CometCloud plugin for ELIZA gives instant access to that ecosystem.

```typescript
// @cometcloud/eliza-plugin
export const cometcloudPlugin: ElizaPlugin = {
  name: "cometcloud",
  actions: [
    getCISScores,      // Query CIS leaderboard
    getCISHistory,     // Score trend analysis
    analyzeFund,       // Deep fund analysis
    depositToVault,    // Agent deposit with session key
    subscribeCIS,      // WebSocket real-time updates
  ],
};
```

---

## Performance Enhancement Priorities

### Backend
| Enhancement | Impact | Effort |
|-------------|--------|--------|
| Redis response caching (5 min TTL) for `/api/v1/cis/universe` | 10x throughput | 1h |
| Connection pooling for Upstash + Supabase (reuse `httpx.AsyncClient`) | 3x latency reduction | 2h |
| Batch CIS history endpoint | Eliminate N+1 sparkline fetches | 2h |
| Gzip compression middleware | 60% smaller payloads for agents | 15 min |
| Rate limiting per API key (Redis sliding window) | Prevent abuse, enable tiered pricing | 3h |

### Frontend
| Enhancement | Impact | Effort |
|-------------|--------|--------|
| `Promise.all` for sparkline fetches (concurrency=5) | 2.4s → 0.5s load | 1h |
| Virtual scrolling for CIS leaderboard (50+ assets) | Smooth at any universe size | 3h |
| Service worker for offline CIS cache | Works on bad connections | 4h |
| WebSocket integration in dashboard (live score updates) | Real-time without polling | 3h |

### Scoring Engine
| Enhancement | Impact | Effort |
|-------------|--------|--------|
| Replace demo S pillar with real VIX/DXY/10Y correlations | 15% of score becomes real | Minimax 4h |
| Real F pillar data (DeFiLlama TVL + CoinGecko FDV) for local engine | 20% of score becomes real | Minimax 4h |
| Expand to 80+ assets (add mid-cap DeFi, new L2s) | Broader coverage | 2h config |
| Score confidence interval (based on data completeness) | Agents can weight by confidence | 4h |
| Multi-timeframe scoring (1d, 7d, 30d CIS) | Richer signal for agents | 6h |

---

## Competitive Landscape Summary

| Project | What They Do | CometCloud Advantage |
|---------|-------------|---------------------|
| **Virtuals** | Agent deployment platform (18K agents) | We score assets; they deploy agents. Complementary — Virtuals agents consume CIS |
| **ElizaOS/ai16z** | Agent framework (60% market share) | Plugin opportunity. CometCloud becomes a data source inside ELIZA |
| **Olas/Autonolas** | Agent marketplace + micropayments | CIS Oracle becomes an Olas service. Agent marketplace pattern is our Phase 4 |
| **Fetch.ai** | DEX trading agents | Competing on execution. Our edge is scoring + fund structure, not raw trading |
| **Bybit AI** | 253 API endpoints for agent trading | CEX-bound. CometCloud is DeFi-native + cross-asset |

**CometCloud's moat:** Nobody else has a 5-pillar cross-asset scoring engine that works for both crypto and TradFi, exposed as both MCP tool and on-chain oracle, inside a regulated Fund-of-Funds wrapper. The scoring intelligence is the moat. A2A/MCP are the distribution channels.

---

## Timeline Summary

```
Week 2-3  (Mar 20 – Apr 2)   Phase 1: Fix Foundation
Week 4-5  (Apr 3 – Apr 16)   Phase 2: Agent Discovery + MCP Server
          (Apr 16)            Nic Demo: CIS + Agent API + MCP live
Week 6-8  (Apr 17 – May 7)   Phase 3: Solana Agent Infrastructure
Week 9-12 (May 8 – Jun 3)    Phase 4: Competitive Moat
          (Jun)               Target: Agents actively querying + transacting
```

---

*Build things that feel alive — and let agents find them.*
