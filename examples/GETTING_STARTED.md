# CometCloud AI — Getting Started

> Institutional-grade crypto intelligence for AI agents via MCP.
> MCP endpoint: `https://looloomi.ai/mcp/sse`

---

## Option A: Claude Desktop (30 seconds)

1. Open your Claude Desktop config file:
   - **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
   - **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

2. Add the CometCloud server:

```json
{
  "mcpServers": {
    "cometcloud": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "https://looloomi.ai/mcp/sse"]
    }
  }
}
```

3. Restart Claude Desktop. Then ask:

> "What is the current macro regime and which crypto assets pass CometCloud's institutional filters?"

---

## Option B: Cursor (30 seconds)

Create `.cursor/mcp.json` in your project root:

```json
{
  "mcpServers": {
    "cometcloud": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "https://looloomi.ai/mcp/sse"]
    }
  }
}
```

Restart Cursor. CometCloud tools appear automatically in Agent mode.

---

## Option C: REST API (no MCP client needed)

```bash
# Macro regime
curl https://looloomi.ai/api/v1/market/macro-pulse | jq .

# Full CIS universe (80+ assets, 5 pillars, grades, signals)
curl https://looloomi.ai/api/v1/cis/universe | jq .

# Signal feed (7 sources, compliance-safe)
curl https://looloomi.ai/api/v1/market/signals | jq .

# A2A task: portfolio analysis
curl -X POST https://looloomi.ai/api/v1/agent/tasks \
  -H "Content-Type: application/json" \
  -d '{"type":"portfolio_analysis","params":{"min_cis":52,"limit":10}}' | jq .
```

---

## Option D: Python agent (full workflow)

```bash
pip install httpx rich
python examples/agent_example.py
```

See [`agent_example.py`](./agent_example.py) for a complete 4-step workflow:
macro context → CIS universe → signal feed → A2A task delegation.

---

## Available MCP tools

| Tool | What it does |
|------|-------------|
| `get_macro_pulse` | Current regime (RISK_ON/TIGHTENING/GOLDILOCKS etc.), BTC price, Fear & Greed, BTC dominance. **Call first.** |
| `get_cis_universe` | Full 80+ asset universe — 5-pillar scores, grades (A+→F), signals, LAS |
| `get_cis_exclusions` | Why 99.5% of assets fail institutional filters. Returns rejection reasons per asset. |
| `get_cis_report` | Single-asset deep scorecard with pillar breakdown and due diligence narrative |
| `get_inclusion_standard` | The 7 institutional criteria used to build the investable universe |
| `get_signal_feed` | Compliance-safe positioning signals from 7 concurrent data sources |
| `get_regime_allocation` | Regime-aware portfolio weights (adjusts by TIGHTENING/GOLDILOCKS/RISK_ON etc.) |

---

## CIS score interpretation

| Score | Grade | Signal | Meaning |
|-------|-------|--------|---------|
| ≥ 85 | A+ | STRONG OUTPERFORM | Exceptional institutional quality |
| ≥ 75 | A | OUTPERFORM | High institutional quality |
| ≥ 65 | B+ | OUTPERFORM | Above threshold |
| ≥ 55 | B | NEUTRAL | Borderline |
| ≥ 45 | C+ | NEUTRAL | Below threshold |
| < 45 | C–F | UNDERPERFORM / UNDERWEIGHT | Failing institutional filters |

**Regime-aware thresholds** (what Freqtrade and portfolio agents use):
- TIGHTENING → require CIS ≥ 52
- RISK_ON → require CIS ≥ 60
- GOLDILOCKS → require CIS ≥ 65

---

## Sample prompts for Claude + CometCloud

```
"What's the current macro regime and which assets pass institutional filters?"

"Screen the CIS universe and build a 10-asset portfolio for Tightening conditions."

"Why was XRP excluded from the CometCloud investable universe?"

"Compare BTC and ETH on all 5 CIS pillars. Which is the better institutional hold right now?"

"What signals is CometCloud showing for DeFi assets this week?"
```

---

## Agent Card (A2A v0.3)

Machine-readable discovery: `https://looloomi.ai/.well-known/agent.json`

Supports async task delegation via `POST /api/v1/agent/tasks`:
- `portfolio_analysis` — CIS-filtered portfolio with weights
- `cis_snapshot` — Full universe snapshot at a point in time
- `regime_briefing` — Macro regime + asset positioning narrative

---

## Compliance note

CometCloud AI does not hold an SFC Type 4 or Type 9 license.
All signals use positioning-only language: OUTPERFORM / NEUTRAL / UNDERPERFORM / UNDERWEIGHT.
Not investment advice. Jurisdiction: Hong Kong SAR.
