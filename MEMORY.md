# MEMORY.md — long-term facts index (read at session start, 30s)

> **Rules:** ≤4KB hard cap (auto-load truncates ~24KB; headroom is the point). One line per fact.
> A fact enters only if it was EXPENSIVE to discover and will be needed again. Evict when stale or
> when compiled into code/CI (then it lives there). Detail belongs in the pointed-to file, not here.

## Environment / infra (traps)
- FUSE sandbox: git write-cmds strand `.git/index.lock` → ALL git Mac-side; `git unlock` to unstick.
- Frontend CAN build in sandbox (`scripts/build_frontend.sh` → /tmp then copy back).
- Supabase = ap-southeast-2 (NOT US) → Postgres `http` ext reaches api.binance.com directly (Railway can't).
- Binance public klines reachable from sandbox; yfinance rate-limited/dead; CryptoCompare needs key.
- Sandbox has no arbitrary egress (allowlist); Railway is US → Binance geo-blocked there.
- preflight = compile + boot + discipline + schema echo. py_compile alone 502'd prod (2026-07-13).

## Data layout (where truth lives)
- `signal_outcomes` (Supabase): β-adjusted cols backfilled 2026-07-22; ex `symbol=bench`; view `signal_beta_scorecard`.
- `ohlcv_daily`: 2017+ deep panel `source='binance_hist'` (82k rows, 41 syms, 25≥2000d) — 731-day limit GONE.
- `asset_edge_moments` view: per-symbol edge_vol/edge_p10 (I5 risk moments).
- pgvector: `asset_embeddings` + `match_asset_embeddings(target,k,class_mode)`; dense v1 core in `vec`, full v2 NaN→null in `vec_full`. Rule: dense+many→pgvector; sparse+few→jsonb+NaN-aware Python cosine.
- 11yr proxy CSV (`_data/cis_historical/`): headerless 20-col, NO pillar_a, pre-2024 = momentum proxy, fwd_ret raw — cannot validate deep signals (S-80/S-81 caveats).
- T2 writers persist pillars shape-tolerantly + `canonical_regime()` UPPER_SNAKE (fixed 2026-07-23 after T1 stall exposed null-pillar latent bug).

## Validated findings (cite ledger, don't re-derive)
- R62: raw `a_ret−b_ret` = leveraged beta (β 1.4–2.4); β-adjust flips OUTPERFORM −0.36→+2.86 t5.75. CIS works. UNDERWEIGHT broken (t−3.79).
- S-77: v5 two-score validated; **O is the dispersion pillar** (corr edge² +0.145, 2× others), F pure-return.
- S-80: 11yr — score IC positive 12/12 years; **F_IC +0.197 12/12** = durable anchor. Bear-window pessimism (S-78/79) was regime confound.
- S-79: A = RISK_ON-concentrated, coin-flip monthly elsewhere; UNRESOLVED long-horizon (no A in proxy).
- S-78: (macro×vol) map real descriptively, NOT tradeable (event-count: 4 episodes 2/2).
- S-81: level-diffusion refuted (IC −0.16); change-diffusion untestable on proxy (Δscore≡return leak). Propagation layer built, gated on real multi-cycle CIS.
- Regime signal validated on clean period: RISK_ON +10.22/RISK_OFF +1.74/EASING −1.49 (β-adj edge by regime).
- Meta-lessons: #21 audit METRIC before MODEL · #22 factor can fail mean & still be risk info · count EVENTS not autocorrelated days (killed S-78+S-79 pooled claims) · 1yr single-regime sample cannot falsify a signal.

## Coordination (standing)
- Ledger: S-/M- prefix from 76; R1–75 frozen bare; append-only EOF; claim heading first.
- Never `git add -A`; own paths only. PROJECT_STATE is co-edited — anchor edits to stable headers, expect mid-session rewrites.
- Minimax feedback 2026-07-27 executed: P0 deep panel + P2 discipline CI. Open (their/joint lane): session-state.json, cold_start.sh, webhook queue, portfolio_state schema (needs Jazz ownership call), Mac MEMORY.md 30KB>24.4KB truncation.
- Known Mac-side: T1 engine stall class (§OUTCOMES-STALE/§REGIME-ALIGN); launchd EPERM on external volume log paths.
