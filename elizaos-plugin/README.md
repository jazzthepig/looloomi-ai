# @elizaos-plugins/plugin-cometcloud

**CometCloud CIS (Crypto Intelligence Score) plugin for [ElizaOS](https://elizaos.ai).**

Gives your ElizaOS agent institutional-grade crypto ratings, macro intelligence, and exclusion screening — the same data layer used by CometCloud's AI-curated Fund-of-Funds.

---

## What it does

| Capability | Details |
|---|---|
| **CIS Scoring** | Morningstar-style composite score (0–100) + letter grade (A+→F) for 80+ assets |
| **5-Pillar Breakdown** | Fundamental · Momentum · On-chain · Sentiment · Alpha |
| **Macro Pulse** | Fear & Greed index · BTC dominance · Total market cap · DeFi TVL · Macro regime |
| **Macro Regimes** | RISK_ON · RISK_OFF · TIGHTENING · EASING · STAGFLATION · GOLDILOCKS |
| **Exclusion Screening** | §4 exclusion list — meme coins, regulatory failures, insufficient liquidity |
| **LAS** | Liquidity-Adjusted Score for position sizing (CIS × liquidity × confidence) |
| **Context Injection** | Ambient market context on every agent response (no explicit tool call needed) |

**Positioning signals (compliance-safe):**  
`STRONG OUTPERFORM` · `OUTPERFORM` · `NEUTRAL` · `UNDERPERFORM` · `UNDERWEIGHT`

---

## Installation

```bash
elizaos plugins add @elizaos-plugins/plugin-cometcloud
```

Or manually:

```bash
npm install @elizaos-plugins/plugin-cometcloud
```

---

## Usage

### In your character file

```json
{
  "name": "CryptoAgent",
  "plugins": ["@elizaos-plugins/plugin-cometcloud"],
  "settings": {
    "COMETCLOUD_API_BASE": "https://looloomi.ai"
  }
}
```

### In code

```typescript
import { createAgent } from "@elizaos/core";
import { cometcloudPlugin } from "@elizaos-plugins/plugin-cometcloud";

const agent = await createAgent({
  plugins: [cometcloudPlugin],
  settings: {
    COMETCLOUD_API_BASE: "https://looloomi.ai",
  },
});
```

---

## Actions

### `GET_CIS_SCORE`

Fetch CIS score, grade, pillar breakdown, and signal for a specific asset.

**Triggers:** "Get CIS score for ETH", "Rate BTC", "What is SOL's rating?"

**Example response:**
```
## CometCloud CIS — ETH (Ethereum)

Score: 71.4 / 100   Grade: B+ Above Average (65–74)
Signal: OUTPERFORM  ·  LAS 68.2
Regime: GOLDILOCKS

### Pillar Breakdown
F 74  |  M 68  |  O 72  |  S 65  |  A 70
```

---

### `GET_CIS_UNIVERSE`

Full CIS universe leaderboard — all scored assets ranked by CIS.

**Triggers:** "Show CIS leaderboard", "Top rated crypto", "CIS universe overview"

---

### `GET_MACRO_PULSE`

Current macro conditions — Fear & Greed, BTC dominance, market cap, regime.

**Triggers:** "What's the macro regime?", "Market sentiment right now", "Fear and greed index"

---

### `CHECK_EXCLUSION`

Screen an asset against the CometCloud §4 exclusion list.

**Triggers:** "Is PEPE excluded?", "Check if WIF is eligible for CIS", "Exclusion check for BONK"

---

## Provider

The `cisContextProvider` automatically injects current regime + top-5 CIS context into every agent response. No explicit trigger needed — your agent always has ambient market awareness:

```
## CometCloud Market Intelligence (live context)
Macro Regime: GOLDILOCKS  |  Fear & Greed: 72 (Greed)  |  BTC Dominance: 54.2%

Top 5 CIS-Rated Assets:
1. MKR  CIS 71.2  B+  OUTPERFORM
2. AAVE  CIS 68.4  B+  OUTPERFORM
...
```

Context is cached for 5 minutes to avoid hammering the API.

---

## Configuration

| Setting | Default | Description |
|---|---|---|
| `COMETCLOUD_API_BASE` | `https://looloomi.ai` | Override API base URL (useful for self-hosted) |

---

## Data sources

- **CIS scores**: CometCloud Mac Mini local engine (T1) + Railway estimation (T2)
- **Macro data**: CoinGecko, Alternative.me, DeFiLlama
- **Refresh**: CIS scores every ~30 minutes, macro every 5 minutes

---

## Links

- **Platform**: https://looloomi.ai
- **MCP Server**: https://looloomi.ai/mcp/sse (for Claude, Cursor, Windsurf)
- **llms.txt**: https://looloomi.ai/llms.txt
- **Agent card**: https://looloomi.ai/.well-known/agent.json
- **CIS Methodology**: https://looloomi.ai — see CIS Methodology in the dashboard

---

## Disclaimer

*CometCloud CIS scores are for informational purposes only and do not constitute investment advice. CometCloud does not hold an investment advisory license. All signals represent relative positioning only — not buy/sell recommendations.*

---

## License

MIT © CometCloud AI
