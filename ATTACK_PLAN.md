# CometCloud Attack Plan — Week 3+ Execution
*Updated: 2026-04-27 | Based on 30-day playbook audit + codebase bug check*

---

## Bug fixes deployed this session (all in COMMIT_READY.md)

| File | Fix | Severity |
|------|-----|----------|
| `src/api/routers/agent.py` | `_run_task` top-level try-except — tasks can no longer stay "pending" forever | P0 |
| `src/api/routers/agent.py` | Redis SET/GET now log warnings instead of silently swallowing errors | P0 |
| `src/api/routers/agent.py` | `_save_task` logs when Redis persist fails (task is in-memory only) | P1 |
| `src/api/routers/agent.py` | All 3 executor error logs now include `exc_info=True` (stack traces in Railway logs) | P1 |
| `src/api/routers/agent.py` | `1 / len(selected)` → `1 / max(len(selected), 1)` edge case guard | P1 |
| `dashboard/src/components/ScoreAnalytics.jsx` | `VITE_API_BASE` → `VITE_API_URL` (was wrong env var, diverged from all other components) | P1 |

**Known open issues (not fixed, require Jazz decision or Solana work):**

- `factory.py` — 7 endpoints marked `# TODO: Integrate with Solana RPC`, return mock data. Gate behind feature flag or remove from agent.json until Solana programs are ready.
- `intelligence.py`, `market.py`, `onchain.py` — bare module-level `from data.*` imports. Work in production (main.py sets sys.path). Fragile if run in isolation. Not blocking.

---

## Playbook deliverables deployed this session

| Deliverable | Status | Notes |
|-------------|--------|-------|
| `dashboard/public/llms.txt` + `dist/llms.txt` | ✅ Created | Day 1 requirement from playbook |
| `Link` + `X-Llms-Txt` HTTP headers in `main.py` | ✅ Added | All responses now advertise llms.txt to LLM crawlers |
| `glama.json` (repo root) | ✅ Created | Required for Glama.ai claim (17,200+ servers, auto-index) |
| MCP assertive descriptions (7.5x multiplier) | ✅ Applied | `get_cis_exclusions`, `get_cis_universe`, `get_macro_pulse`, `get_cis_report`, `get_inclusion_standard` |

---

## Week 3 attack sequence (Apr 28 – May 4)

### BY TUESDAY AFTERNOON (Jazz out networking Apr 27)

| Action | Owner | Time | Notes |
|--------|-------|------|-------|
| Build 60-second screen recording demo | Jazz | 1h | Required for Product Hunt. Record: MCP tool call → CIS score → exclusion check flow in Claude Desktop or Cursor. |

### MONDAY (Apr 28)

| Action | Owner | Time | Notes |
|--------|-------|------|-------|
| **Product Hunt launch** (12:01 AM PST) | Jazz | 4h | Title: "CometCloud — Morningstar-style ratings + exclusion list for crypto, via MCP". Tag: AI Agents, Developer Tools, Crypto. Stay in comments 4+ hours. |
| Minimax push (COMMIT_READY.md sequence) | Minimax | 30min | Clears this entire session's work to Railway. |
| Submit to Official MCP Registry | Jazz | 1h | `mcp-publisher` CLI + `server.json` metadata. GitHub auth only. Near-instant approval. |
| Submit to Glama.ai | Jazz | 30min | Submit GitHub URL at glama.ai/mcp/servers → claim via GitHub auth → `glama.json` already in repo ✅ |
| Submit to Smithery.ai | Jazz | 30min | `smithery mcp publish "https://looloomi.ai/mcp/sse" -n cometcloud/cis-server` |
| Submit to LobeHub (Stocks & Finance) | Jazz | 1h | "Submit MCP" button at lobehub.com/mcp. TARGET: "Stocks & Finance" category (2,000 servers vs 25,700 in Developer Tools). |
| Submit to awesome-mcp-servers | Jazz | 30min | PR to github.com/punkpeye/awesome-mcp-servers (80K+ stars) |
| Submit to Anthropic Connectors Directory | Jazz | 2h | Remote MCP review form. Requirements: OAuth 2.1 (we have bearer), safety annotations ✅, 3 usage examples ✅, privacy policy (need to add). Highest-leverage single submission. |

### TUESDAY (Apr 29)

| Action | Owner | Time | Notes |
|--------|-------|------|-------|
| Submit to MCP.SO, PulseMCP, Cline Marketplace, MCP.directory, Cursor Directory | Jazz | 3h | MCP.SO = call volume leaderboard drives rank (our north star metric). PulseMCP = "Most Popular" weekly sort. |
| Write "State of Crypto Intelligence for AI Agents" benchmarking report | Jazz | 4h | Benchmarks Nansen/Dune/Kaito/Glassnode against CIS criteria. Conclusion: agents making financial decisions with current tools are flying blind. Only CometCloud provides rejection reasons. Publish to Dev.to + cross-post. |
| DM 10 crypto researchers on X | Jazz | 2h | Targets: @woonomic, @WClementeIII, @RyanSAdams, @cryptoquant_com, @ArkhamIntel, @DefiIgnas, @lookonchain, @ai16zdao, @ZachXBT, @swyx. Use the playbook DM template. |

### WEDNESDAY (Apr 30)

| Action | Owner | Time | Notes |
|--------|-------|------|-------|
| Write tutorial: "Build a Crypto Screening Agent with CometCloud MCP in 5 Minutes" | Jazz | 3h | Publish to Dev.to. Shows Claude Desktop + MCP config + first tool call. This drives MCP.SO invocation counts. |
| Create OpenAI Custom GPT | Jazz | 3h | Actions pointing to CometCloud API endpoints. Publish to GPT Store. Tags: AI Agents, Finance, Crypto. |
| Submit Cursor Marketplace plugin | Jazz | 2h | eToro and Circle already have verified plugins here. Precedent for financial tools. |
| Join MCP Community Discord, Cursor Discord, ElizaOS Discord | Jazz | 2h | Introduce yourself, answer questions. 30min/day from here forward. |

### THURSDAY (May 1)

| Action | Owner | Time | Notes |
|--------|-------|------|-------|
| Publish "5 Most Overrated Crypto Assets Per Our Rating System" | Jazz | 3h | Name names. Back with CIS data. Controversial stance-taking = organic distribution. Cross-post: Twitter thread → r/cryptocurrency → r/CryptoAI |
| Begin ElizaOS plugin (`@elizaos-plugins/plugin-cometcloud`) | Seth | 4h | Use eliza-plugin-starter template. Actions + Providers. `elizaos publish`. Most crypto-native agent framework. |
| Conference logistics | Jazz | 1h | LED backpack order ($150 Amazon), 8-person dinner venue (book 2 weeks ahead) |

### FRIDAY (May 2)

| Action | Owner | Time | Notes |
|--------|-------|------|-------|
| Submit ElizaOS plugin | Seth | 2h | Via `elizaos publish` — no formal approval gate. |
| Begin Solana Agent Kit plugin | Seth | 4h | `@solana-agent-kit/plugin-cometcloud`, PR to github.com/sendaifun/solana-agent-kit. 1,400+ commits, 800+ forks. |
| Pre-schedule 15-20 meetings at Web3 conference via DM/email | Jazz | 3h | Use playbook DM template. Book dinner venue. |

### WEEKEND (May 3-4)

| Action | Owner | Time | Notes |
|--------|-------|------|-------|
| Submit Solana Agent Kit PR + Solana Agent Skill | Seth | 2h | Register at solana.com/skills |
| Build "Financial AutoResearch" template | Seth | 6h | Fork of Karpathy's AutoResearch (42K GitHub stars). Points Claude Code at crypto screening loop using CometCloud MCP. Every developer who clones it = CometCloud user. |
| Weekly analytics review | Jazz | 3h | Track: tool invocations/day, GitHub stars, registry positions, content engagement |

---

## Asymmetric bets — execute when other items are clear

| Bet | Effort | Payoff | Notes |
|-----|--------|--------|-------|
| "Financial AutoResearch" GitHub template | 6h Seth | Massive | Karpathy's AutoResearch = 42K stars in 2 weeks. CometCloud fork rides the wave. |
| "State of Crypto Intelligence" report (Bet #3) | 4h Jazz | High | Positions CometCloud as the authority. Drives press + backlinks. |
| Hackathon speedrun (AI Agent Olympics May 13-20, Ruya Devpost) | 6h Jazz+Seth | High | Same project submitted to multiple hackathons. Wins = credibility + press. |
| LED backpack + conference dinner (Bet #2) | $350 | High | 8-seat dinner with fund managers outperforms $50K booths. Book now. |

---

## Week 3 milestones (targets)

- Product Hunt launched ✓
- Listed on 10+ registries ✓
- MCP.SO + Glama.ai + Smithery + LobeHub + Cline + Cursor Directory live
- Anthropic Connectors Directory submission filed
- ElizaOS + Solana Agent Kit integrations submitted
- "State of Crypto Intelligence" report live
- 150+ GitHub stars
- First X outreach sent (10 accounts)
- OpenAI Custom GPT published

---

## Infrastructure still missing (Seth to build)

| Item | Effort | Priority | Playbook reference |
|------|--------|----------|--------------------|
| Privacy policy page (`/privacy`) | 2h | P0 for Anthropic submission | Required for Anthropic Connectors Directory |
| PostHog `withAnalytics()` wrapper on MCP tools | 3h | P1 | North star metric = tool invocations/day → drives MCP.SO rank |
| ElizaOS plugin | 4h | P1 | Week 3 Thu |
| Solana Agent Kit plugin | 4h | P1 | Week 3 Fri |
| Financial AutoResearch template | 6h | P2 | Week 4 Mon |
| `llms-full.txt` (complete inline documentation) | 2h | P2 | Max AI parsing vs llms.txt |

---

## COMMIT_READY additions (add to Minimax push)

Files created/modified this session that need `git add`:

```bash
# Add to existing Minimax git add sequence:
src/api/routers/agent.py          # bug fixes
src/api/main.py                    # llms.txt headers + agent_router
dashboard/src/components/ScoreAnalytics.jsx  # VITE_API_URL fix
dashboard/public/llms.txt         # new
dashboard/dist/llms.txt           # new
glama.json                        # new (repo root, required for Glama.ai)
src/mcp/cometcloud_mcp.py         # assertive descriptions on 5 tools
ATTACK_PLAN.md                    # this file
```

Combine with existing COMMIT_READY.md sequence — one commit covers everything.
