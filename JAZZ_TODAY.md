# Jazz — Distribution Tasks (by Tuesday afternoon)

---

## 1. 60-second screen recording

Record this exact flow:

1. Open Claude Desktop (with CometCloud MCP configured)
2. Ask: "What's the current macro regime and which crypto assets pass institutional filters?"
3. Show: macro_pulse response → cis_universe → top assets table
4. Ask: "Why is XRP excluded from the investable universe?"
5. Show: `get_cis_exclusions` response with reasons

- No audio needed. Screen only.
- Save as: `cometcloud-demo.mp4`
- Time: 1h

---

## 2. Product Hunt launch

- **Title:** "CometCloud — Morningstar-style ratings for crypto, via MCP"
- **Tagline:** "Institutional CIS scores + exclusion list for 80+ assets. One MCP config away."
- **Tags:** AI Agents, Developer Tools, Crypto/Web3
- **Gallery:** demo video + 3 screenshots (leaderboard, exclusion response, macro pulse)
- **Description:** lead with the MCP config snippet (30 seconds to connect), then the "99.5% of crypto fails" stat
- **After launch:** stay in comments 4+ hours

---

## 3. Registry submissions — in order of leverage

| # | Registry | Action |
|---|----------|--------|
| 1 | **Official MCP Registry** | `mcp-publisher` CLI, GitHub auth only |
| 2 | **Glama.ai** | glama.ai/mcp/servers → submit GitHub URL → claim via GitHub auth (`glama.json` ✅ in repo) |
| 3 | **Smithery.ai** | `smithery mcp publish "https://looloomi.ai/mcp/sse" -n cometcloud/cis-server` |
| 4 | **LobeHub** | lobehub.com/mcp → "Submit MCP" → target "Stocks & Finance" category |
| 5 | **awesome-mcp-servers** | PR to github.com/punkpeye/awesome-mcp-servers |

Time: ~4h total

---

*Seth handling Minimax tasks (T21/T22/T23) in parallel. No backend blockers on your end.*
