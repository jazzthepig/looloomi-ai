# Current State — Updated 2026-04-21

## Commits on Railway (confirmed via `git log origin/main`)
- `11dd71c` — Fix T2 scoring crash: hoist fng_value, fix FX/RE/EM routing, per-asset try/except
- `3e5464c` — fix: expand EODHD error check for FRED fallback
- `484b88c` — fix: add FRED fallback for macro indicators when EODHD unavailable
- `db44af0` — Add /api/v1/cis/debug/datasources
- `13668fc` — fix(cis): CIS v4.2 scoring corrections — market rebound detection
- `cb9eaee` — fix: CIS data layer — Binance geo-block + Upstash L2 cache
- `b5d2bc7` — feat: Phase B+C+D — compliance hook, subagents, Portfolio tab

## CIS v4.2 Scoring Fix (commit `13668fc`) — Applied 2026-04-18

### What changed in `src/data/cis/cis_provider.py`:

1. **Dual score display** — `raw_cis_score` (base weights, no regime) vs `cis_score` (regime-adjusted)
   - `calculate_total_score()` now returns both `total_score` and `raw_cis_score`
   - Each asset in universe now carries both fields
   - Frontend can show: `CIS BASE: 72 / CIS ADJ: 58 (Risk-Off)`

2. **S pillar recovery bonus** — rebounding assets (24h+7d positive, 30d negative) get +0–5 bonus
   - `s_components["recovery_bonus"]` exposed for transparency

3. **S pillar vol/mcap threshold** — lowered from 0.3% to 0.05%
   - More assets qualify for vol_surge_signal in low-volume recovering markets

4. **A pillar correlation floor** — in Risk-Off, BTC corr discount floor raised from -15 to -8
   - Prevents double-penalizing BTC correlation (S pillar already handles macro beta in Risk-Off)

5. **Divergence dampener** — in extreme fear (FNG<25), divergence halved; FNG<40: 0.75x
   - Prevents panic-sell assets from being doubly penalized vs category peers

### What changed in `src/api/routers/cis.py`:
- T1 merge now preserves `raw_cis_score` from Mac Mini
- T1-only assets get `raw_cis_score` computed from pillars if missing

### Fix 6 (Skipped): CometCloudStrategy.py compliance
- Shadow folder is read-only per CLAUDE.md rules — cannot modify
- GRADE_ORDER dict itself is compliance-safe (grade letters only)

## Production health (2026-04-18)

| Component | Status | Notes |
|-----------|--------|-------|
| Railway | ✅ LIVE | HEAD = 13668fc (CIS v4.2) |
| CIS Universe | 🔄 DEPLOYING | v4.2 fixes live after Railway auto-deploy |
| raw_cis_score field | ✅ ADDED | Now in /api/v1/cis/universe + /top responses |
| Mac Mini data fetcher | ✅ FIXED | CoinGecko null handling fixed; confidence=0 filter added |
| Mac Mini scheduler | ✅ FIXED | Skips zero-confidence assets from universe |
| Mac Mini cis_push | ✅ CONFIRMED | macro_regime field in payload (line 114) |
| Macro Pulse | ✅ LIVE | Expected unchanged |
| Signal Feed | ✅ LIVE | Expected unchanged |
| DeFi Overview | ✅ LIVE | Expected unchanged |

## Pending by owner

### Minimax (Mac Mini)
- [x] **CORRECT FIX**: Removed 13 excluded assets from `ASSET_UNIVERSE` (§4A) — POLYX, PEPE, WIF, BONK, SAND, MANA, AXS, CRV, SUSHI, SNX, ICP, BCH, FTM — from config.py + data_fetcher.py symbol mappings
- [x] DOGE added back (was removed accidentally) — §4A keep list
- [x] CoinGecko null handler — skip null items, don't cache price=0
- [x] cis_scheduler confidence=0 filter — skip zero-data assets from universe
- [x] cis_push.py macro_regime confirmed in payload
- [x] CoinGecko symbol mappings cleaned up — all 73 universe assets have CG IDs
- [x] DeFiLlama protocol_map updated — removed excluded assets, fixed POL → "polygon-ecosystem-token"
- [ ] Restart `cis_scheduler.py` to apply fixes + push clean universe to Railway

### Jazz
- [ ] Verify Railway deployment of `13668fc` completes without crash
- [ ] Check `/api/v1/cis/top?limit=5` — should show `raw_cis_score` field and B+ grades
- [ ] Railway → Variables: verify `COINGECKO_API_KEY`, `SUPABASE_URL`, `SUPABASE_KEY`

### Seth (Austin)
- [ ] Verify CIS universe populates after deploy — `universe_size > 0`, grade distribution spans C to B+
- [ ] Wallet connect E2E test with Phantom devnet
- [ ] Strategy.html walkthrough prep for Nic

## HARNESS_UPGRADE.md progress
- Phase A: ✅ All 6 skills (compliance-language, cis-methodology, mac-mini-coordination, deploy-workflow, design-system, tech-stack)
- Phase B: ✅ Compliance hook (.claude/hooks/compliance_check.py, dry-run mode)
- Phase C: ✅ Subagents (compliance-auditor, cis-validator, deploy-verifier, code-frontend-reviewer, local-data-coordinator)
- Phase D: ✅ Session handoff + agent memory
- Phase E: ✅ Plugin structure (cometcloud-intelligence/ — manifest + 5 skills + 2 commands + 1 agent + MCP config)
- Phase F: ✅ GitHub Agentic Workflows (.github/workflows/ — compliance-pr-check, post-deploy-verify, weekly-cis-audit)
- Phase G: Scheduled task migration — not started (Mac Mini cron stays for now)

## ROADMAP_A2A.md progress
- Phase 1: ✅ Foundation fixes (all done in previous sessions)
- Phase 2.1: ✅ Agent Card (dashboard/public/.well-known/agent.json — A2A discovery)
- Phase 2.2: MCP server FastMCP wrapper — not yet deployed (cometcloud.json references it)
- Phase 3: Solana agent infrastructure — not started
- Phase 4: Competitive moat — not started

## Production health (2026-04-21 — updated after Minimax sync)
| Component | Status | Notes |
|-----------|--------|-------|
| Railway | ✅ LIVE | HEAD = 11dd71c + FRED fallback deploying |
| CIS universe | ✅ 84 assets | T1=25 (Mac Mini) + T2=59 (Railway). COINGECKO_API_KEY confirmed set |
| CIS T1 Mac Mini | ✅ RUNNING | cis_scheduler.py PID 33143, pushing every 30min |
| macro_regime | ✅ Tightening | Mac Mini regime flowing through (was Neutral before) |
| Macro Pulse | ✅ LIVE | BTC + FNG + dominance + regime |
| Signal Feed | ✅ LIVE | Timestamps + HTML strip fixed |
| DeFi Overview | ✅ LIVE | DeFiLlama TVL live |
| MacroBrief | ❌ NULL | LM Studio pipeline not connected |
| Economic Indicators | ⏳ DEPLOYING | FRED fallback code pushed, waiting Railway redeploy |
| Supabase | ❌ NOT CONNECTED | SUPABASE_URL + SUPABASE_KEY missing from Railway |
| Shadow sync | ✅ DONE | 4 files synced (see MINIMAX_SYNC.md §7) |

## Pending by owner

### Jazz (Railway env vars)
- [ ] Add `COINGECKO_API_KEY` → CIS universe populates
- [ ] Add `SUPABASE_URL` + `SUPABASE_KEY` (service_role) → score history + leads
- [ ] Run scripts/supabase_all_tables.sql in Supabase SQL Editor

### Minimax (Mac Mini)
- [ ] Restart `cis_scheduler.py` → push clean universe (13 excluded assets removed)
- [ ] Rotate EODHD + Finnhub API keys (exposed in old git history)
- [ ] Start Freqtrade dry run (start_dry_run.sh)
- [ ] Add LAS calculation to local engine output

### Seth (next)
- [ ] Commit harness upgrade (Phase A-F + agent card) to git
- [ ] Plugin marketplace submission (Phase E) — once jazz green-lights
- [ ] Wallet connect E2E test (Phantom devnet)
