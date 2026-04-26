# Current State — Updated 2026-04-26

## Commits on Railway (confirmed via `git log origin/main`)
- PENDING PUSH — feat(mcp): Phase 2.2 — MCP server mounted at /mcp/sse (ROADMAP_A2A)
  Files staged in COMMIT_READY.md: src/api/main.py, requirements.txt, cometcloud-intelligence/mcp/cometcloud.json,
  dashboard/src/components/CISWidget.jsx, dashboard/src/components/StrategyPage.jsx, dashboard/dist/
- `b7095fc` — tests + COMMIT_READY.md + MINIMAX_SYNC.md §7 + compliance-pr-check.md fix
- `4aada1a` — feat: Phase A-F + A2A agent card + harness supplement (agent MCP config etc.)
- `31194ae` — feat(harness): Phase A-F + A2A agent card — complete agent stack upgrade
- `13668fc` — fix(cis): CIS v4.2 scoring corrections — market rebound detection

## Production health (2026-04-26)

| Component | Status | Notes |
|-----------|--------|-------|
| Railway | ✅ LIVE | HEAD = b7095fc (Phase 2.2 commit PENDING Mac Mini push) |
| CIS Universe | ✅ LIVE | 84 assets (T1=25 Mac Mini + T2=59 Railway) |
| Mac Mini scheduler | ✅ RUNNING | cis_scheduler.py PID 33143, ~30min pushes |
| macro_regime | ✅ Tightening | Nested key path fixed; flowing through correctly |
| Supabase | ✅ CONNECTED | soupjamxlfsmgmmtoeok — score history writing ✅ |
| Macro Pulse | ✅ LIVE | BTC + FNG + dominance + regime |
| Signal Feed | ✅ LIVE | Correct timestamps + compliance language |
| DeFi Overview | ✅ LIVE | DeFiLlama TVL live, 25 protocols |
| MacroBrief | ❌ NULL | LM Studio pipeline not connected |
| Economic Indicators | ⏳ DEGRADED | FRED fallback active; EODHD key needs rotation |
| Freqtrade | ❌ NOT STARTED | dry-run not yet started by Minimax |
| Agent harness | ✅ DEPLOYED | Phase A-F complete (31194ae) |
| A2A discovery | ✅ LIVE | /.well-known/agent.json served |
| MCP server | ⏳ STAGED | Phase 2.2 code ready; boots after Mac Mini push |

## HARNESS_UPGRADE.md progress
- Phase A: ✅ All 6 skills (compliance-language, cis-methodology, mac-mini-coordination, deploy-workflow, design-system, tech-stack)
- Phase B: ✅ Compliance hook (.claude/hooks/compliance_check.py, dry-run mode)
- Phase C: ✅ Subagents (compliance-auditor, cis-validator, deploy-verifier, code-frontend-reviewer, local-data-coordinator)
- Phase D: ✅ Session handoff + agent memory
- Phase E: ✅ Plugin structure (cometcloud-intelligence/ — manifest + 5 skills + 2 commands + 1 agent + MCP config)
- Phase F: ✅ GitHub Agentic Workflows (.github/workflows/ — compliance-pr-check, post-deploy-verify, weekly-cis-audit)
- Phase G: Scheduled task migration — not started (Mac Mini cron stays for now)

## ROADMAP_A2A.md progress
- Phase 1: ✅ Foundation fixes (all done)
- Phase 2.1: ✅ Agent Card (dashboard/public/.well-known/agent.json — A2A discovery)
- Phase 2.2: ✅ MCP server mounted at /mcp/sse in FastAPI (ASGI sub-app, zero new Railway services)
  - `src/api/main.py`: `app.mount("/mcp", mcp.sse_app())` with fail-safe try/except
  - `src/api/main.py`: SPA fallback now excludes "mcp/" from prefix list (prevents index.html serving /mcp/* on 404)
  - `requirements.txt`: mcp[cli]>=1.6.0, cachetools, tenacity added
  - `cometcloud-intelligence/mcp/cometcloud.json`: remote.url = https://looloomi.ai/mcp/sse
  - `scripts/test_auth_e2e.py`: 11-test backend E2E for wallet sign-in (run on Mac Mini)
  - 3 UI fixes: CISWidget timestamp (epoch *1000), MACRO REGIME (macro_regime field), StrategyPage CTA contrast
  - COMMIT_READY.md prepared — Mac Mini must push
- Phase 2.3: A2A Task endpoint /api/v1/agent/tasks — not started
- Phase 3: Solana agent infrastructure — not started
- Phase 4: Competitive moat — not started

## CIS Scoring — Live bugs fixed (2026-04-21 to 2026-04-24)

### Mac Mini fixes (Seth applied directly — `/Volumes/CometCloudAI/cometcloud-local/`)

1. **`data_fetcher.py` POL ID**: `SYMBOL_TO_COINGECKO_ID["POL"]` was `"polygon"` (old CG ID, 404).
   Fixed to `"polygon-ecosystem-token"`. Same table also used by `fetch_fundamental_data()`.

2. **`cis_v4_engine.py` FundamentalScorer.asset_class**: `score()` only checked
   `== AssetClass.CRYPTO` ("Crypto" — BTC/LTC/BCH only). All other crypto subclasses
   (L1/L2/DeFi/RWA/INFRA/MEME/GAMING) fell through to `_score_generic()` → always returned 50.
   Fixed: now checks `in (AssetClass.CRYPTO, L1, L2, DEFI, RWA, INFRA, MEME, GAMING)`.
   Effect: MKR/UNI/AAVE/PENDLE now score F=70 (real DeFiLlama TVL data).

3. **`cis_scheduler.py` subprocess path**: `subprocess.run([sys.executable, "cis_push.py"...
   used system Python instead of venv Python → CG Pro key not loaded in child process.
   Fixed: now calls `str(BASE_DIR / "venv/bin/python")` explicitly.
   Effect: `history_written: true` on every push, Supabase score history populating.

### Railway fixes (committed to GitHub)

4. **`cis_provider.py` CG mcap=0 fallback** (commit `4aada1a`): CG `/coins/markets`
   returns `circ_supply=0` for MKR/AAVE/UNI (rebranded tokens), causing
   `price×circ_supply=0` mcap estimation. Added secondary fallback:
   `price×total_supply` before FDV and volume×20.
   Effect: T2 DeFi assets now get real mcap estimates from CG Pro.

### CIS Score State (2026-04-24)

```
T1 (Mac Mini, 25 assets):
  MKR  B    CIS=56.8  F=70  ← TVL=5.3B DeFiLlama (fixed FundamentalScorer)
  TIA  C+   CIS=52.1  F=50
  NEAR C+   CIS=50.4  F=50
  ETH  C    CIS=45.8  F=50
  BTC  C    CIS=44.8  F=50

T2 (Railway, 59 assets):
  F pillar: working (LTC=66.3, BCH=69.6, ALGO=65.1, ICP=67.4)
  Bottleneck: S pillar (12-13 for many) and A pillar (20-30) too low
  No B+ assets (CIS≥65) — freqtrade MIN_CIS_SCORE=65 gate blocks all trades
```

**Core problem**: S pillar (Sentiment) and A pillar (Alpha) systematically low. F is now
correct. Need to investigate S/A scoring formulas on Railway T2.

### CIS Score Investigation Notes

- CG Pro `/coins/markets` batch endpoint returns `market_cap=0` for MKR but not ETH/BTC
- CG Pro `/coins/{id}` individual endpoint returns `circ_supply=0, total_supply=91377` for MKR
- `price × total_supply ≈ 169M` matches FDV → used as secondary mcap fallback
- T2 data_tier=2 assets (STRK, VET, ICP, etc.) all have real F scores via mcap log-scale
- T1 assets use Mac Mini engine with real Binance klines + DeFiLlama TVL
- T2 assets use CG Pro market data only (no Binance klines on Railway)

## Pending by owner

### Seth (next up)
- [x] Wallet connect auth code review — no critical bugs found; flow is correct
- [x] Backend E2E test script: scripts/test_auth_e2e.py (11 tests, Mac Mini must run)
- [ ] Wallet connect live test: Minimax/Jazz runs scripts/test_auth_e2e.py on Mac Mini
- [ ] Verify ScoreAnalytics heatmap populates (>24h of Supabase inserts)
- [ ] Phase 2.3: A2A Task endpoint /api/v1/agent/tasks — P2
- [ ] Plugin marketplace submission — once Jazz green-lights
- [ ] My Portfolio view (after wallet connect)

### Minimax (Mac Mini)
- [ ] Rotate EODHD + Finnhub API keys (exposed in old git history)
- [ ] Start Freqtrade dry run (start_dry_run.sh)
- [ ] Add LAS calculation to local engine output
- [ ] MacroBrief pipeline stability (LM Studio Qwen3 35B crash recovery)
- [ ] Run T1 backtest (run_t1_backtest.sh)

### Jazz + Nic
- [ ] Strategy.html walkthrough with Nic
- [ ] Seed investor deck draft
- [ ] Family office soft intros (3-5 targets via Nic)

## Notes on FUSE git constraints
- VM FUSE filesystem: `.git/index.lock` and `.git/HEAD.lock` cannot be removed from Cowork
- All `git add`/`commit`/`push` must run from Mac Mini terminal
- COMMIT_READY.md at repo root has the exact 5-step sequence for Mac Mini
- `git add` in Cowork shows warnings but exits 0; staged index doesn't persist to disk
