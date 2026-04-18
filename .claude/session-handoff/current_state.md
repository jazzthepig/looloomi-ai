# Current State — Updated 2026-04-18

## Commits on Railway (confirmed via `git log origin/main`)
- `13668fc` — fix(cis): CIS v4.2 scoring corrections — market rebound detection
- `cb9eaee` — fix: CIS data layer — Binance geo-block + Upstash L2 cache
- `b5d2bc7` — feat: Phase B+C+D — compliance hook, subagents, Portfolio tab
- `9ebc5a8` — fix: wallet auth graceful degradation
- `6c09dad` — Phase A: compliance-language + cis-methodology skills

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
- [x] CoinGecko null handler — POLYX/PEPE: skip null items, don't cache price=0
- [x] cis_scheduler confidence=0 filter — skip zero-data assets from universe
- [x] cis_push.py macro_regime confirmed in payload
- [ ] Restart `cis_scheduler.py` to apply fixes
- [ ] Confirm POLYX + PEPE removed from ASSET_UNIVERSE (§4A exclusion list)

### Jazz
- [ ] Verify Railway deployment of `13668fc` completes without crash
- [ ] Check `/api/v1/cis/top?limit=5` — should show `raw_cis_score` field and B+ grades
- [ ] Railway → Variables: verify `COINGECKO_API_KEY`, `SUPABASE_URL`, `SUPABASE_KEY`

### Seth (Austin)
- [ ] Verify CIS universe populates after deploy — `universe_size > 0`, grade distribution spans C to B+
- [ ] Wallet connect E2E test with Phantom devnet
- [ ] Strategy.html walkthrough prep for Nic

## HARNESS_UPGRADE.md progress
- Phase A: ✅ Skills
- Phase B: ✅ Compliance hook
- Phase C: ✅ Subagents + memory
- Phase D: ✅ Session handoff
- Phase E: Plugin packaging — not started
- Phase F: GitHub Agentic Workflows — not started
- Phase G: Scheduled task migration — not started
