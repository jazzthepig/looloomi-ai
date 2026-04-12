# CIS Validator — Agent Memory

## Current engine state (as of 2026-04-12)

### Engine versions
- Railway (T2): `src/data/cis/cis_provider.py` — v4.1 continuous scoring, unified thresholds
- Mac Mini (T1): `Shadow/cometcloud-local/cis_v4_engine.py` — v4.1 (after Minimax applies config.py update)
- Both engines: A+ ≥85 | A ≥75 | B+ ≥65 | B ≥55 | C+ ≥45 | C ≥35 | D ≥25 | F <25

### Known data issues by asset
- MKR: CoinGecko Pro key required for full data; may show reduced confidence on T2
- POLYX: Same — Pro key dependent
- NEON: Has a specific CoinGecko ID that was fixed (check `fetch_cg_markets()` for explicit IDs)
- GENIUS: Removed from universe (check if re-added)
- MATIC: Renamed to POL — if old `matic-network` ID appears, it's stale data

### Production state (as of 2026-04-12)
- CIS universe: EMPTY — Mac Mini not pushing + Railway CoinGecko key missing
- COINGECKO_API_KEY: NOT YET added to Railway env vars (as of last sync)
- Redis bridge: Functional when both sides have data
- T1 badge: Will only appear when Mac Mini `cis_push.py` is running and pushing

### T1/T2 divergence baselines
- Normal T1 > T2 gap: 5–15 points (T1 has Sharpe/MDD, T2 only has ATH proxy)
- If gap > 20 points: suspect data quality issue on one side
- Memecoins: T1 and T2 often diverge more (Binance klines add precision for M pillar)
- RWA assets: T2 often underscores because CG doesn't have full TVL data for MKR/POLYX

### Score clustering context
- When all scores land 55–70 (B/B+): normal in neutral regime (FNG 40–60)
- Clustering is informative, not a bug — see CIS_METHODOLOGY.md §10
- Per-asset differentiation comes from pillar breakdown, not grade

### S pillar known behavior
- FNG is the crypto baseline (0–40 range, FNG×0.4)
- Category median divergence: must be computed per asset class, not global
- If all S pillar scores identical: category_median computation is broken (returning global median)

## LAS parameters (production defaults)
- AUM: $30,000,000
- max_single_position_pct: 5% → target_position = $1,500,000
- participation_rate: 10%
- Assets with vol_24h < $15M will have LAS < CIS (partial liquidity penalty)

## File map (where to look for bugs)
- T2 scoring: `src/data/cis/cis_provider.py`
- T2 API: `src/api/routers/cis.py`
- Redis read/write: `src/data/cis/cis_provider.py` + `src/api/routers/internal.py`
- T1 scoring: `Shadow/cometcloud-local/cis_v4_engine.py` (READ ONLY — Minimax owns)
- Interface contract: `MINIMAX_SYNC.md`
