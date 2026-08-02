# MEMORY.md — long-term facts index (read at session start, 30s)

> **Rules:** ≤8KB cap (auto-load truncates ~24KB; headroom is the point). One line per fact — EXCEPT
> the ontology core below, which is soul-material and never evicted (Jazz 2026-07-27). A fact enters
> only if it was EXPENSIVE to discover and will be needed again. Evict when stale or when compiled
> into code/CI. Detail belongs in the pointed-to file, not here.

## 💰 RETURN HIERARCHY — never evict (Jazz, 2026-07-27; full text `HIGH_DIM_ONTOLOGY.md` §5b)
- **① 保证吃到 beta(持有 panel)→ ② beta+(持仓内超配 = CIS 的真岗位,tilt 非 L/S)→ ③ beta multiplier(择时调总暴露 0.7–1.3x,不做空)→ ④ pure alpha(中性,最难最后)。优先级,不是菜单。**
- **我们做反了:R76–R94 全是④(demean = 构造上扔掉 beta),①从未建过。15 连败是设定错误,不是运气。**
- 默认满仓多头:**tilt, don't neutralize**。基准永远是"等权持有本 panel",不是 0。β-adj 只用于**归因**(R62),绝不用于中性化仓位。每个结果报 total_return / vs 持有 / 再报超额。
- **⓪层 OVERRIDE 凌驾四层(最该建的能力,`REGIME_OVERRIDE_SPEC.md`)**:风格/流动性周期转向时**空仓(0x)甚至裸空(−0.3x)优先于吃 beta** —— ①是**条件性默认**,非无条件义务。暴露区间 [−0.3, 1.3]。
- **正交是归因工具,不是建仓约束**(我曾写错):转向时三层应同时服从ⓠ层,事后再拆归因。
- ⓠ层判据独特:不判 Sharpe,判**三段崩塌(2018/2022/2025-26)是否在回撤前 1/3 内降暴露**(≥2/3)+ maxDD 改善≥10pp + 切换≤6次/年 + 优于随机。最强先验 O1 = stablecoin 供应Δ(已验 DD −56.5% vs 持有 −75.2%)。
- **Millennium 模型**:平台 edge 在**中心化风险分配**,不在单个 pod。**强制:每个组件必须有 `max_dd_stop` + 触发动作,且回测时带着止损跑;无止损不许进生产**(含⓪层自己)。

## 🧭 THE ONTOLOGY CORE — never evict (full text: `docs/HIGH_DIM_ONTOLOGY.md` + `ARCHITECTURE.md`)
- 市场真实状态是高维的;全部工作 = 一连串**保结构的降维**;VDB 是这条链的几何基底。
- 内核:最深对象是 **Entity/Decision**,影响力作向量场传播;CIS/价格是波前过后的**反射**;**edge = lag**。
- **Be water**:无冻结因子 — 场算子 W 随 embedding 每周期重塑;regime 是场的**相**,只进 sizing 不做轮动 (R20)。
- **Be quantum**:资产态是**分布**(mean/vol/p10, I5)非标量;非局域 — `entanglement_delta = p−s` 度量场超出节点自身反射的隐含;CIS 快照是带 lag 的**测量塌缩**。
- **S-81 定理:扩散 level(反射)被证伪(IC−0.16);必须扩散 CHANGE(因)** — Δpillar/D1流/D4注意力/holder-Δ;等真·多周期 CIS 开测。
- 压缩级联:微观态∞ → 27d embedding → pgvector 相似场 → v5 双分数(收益⊥风险) → regime×vol sizing 语法 → 1 个可审计决策。四守恒律:I1 NaN≠0 · I3 β分离 · I5 分布 · R63b 三种因子类。
- 存储法则:**dense+many → pgvector HNSW;sparse+few → jsonb + NaN-aware 共享维余弦**(稀疏0补做稠密余弦是错误度量)。
- 量子计算钩子:扩散算子保持**线性**(→quantum walk 直接移植);sleeve 选择是 QUBO(→QAOA);amplitude encoding 备用。今天全部 quantum-inspired classical,不声称量子优势,一切过 gauntlet。
- **VDB 做多(Jazz)**:六对象全向量化 — Asset✅ / Strategy🔨 / Regime指纹📋 / Entity-Decision🎯frontier / Text-RAG📋 / 时序窗口📋 / Outcome📋;跨空间边=内核边;终态 = 任何 operator 的任何问题都是一次向量查询。

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

- **pillar_O is structural anomaly detector (Jazz, 2026-07-28)** — by design fires only when anomalies are present, "not effective most of the time". R46's persistent L/S on pillar_O is a structural mis-use; correct use is CONDITIONAL (only when pillar_O is firing) or DETECTOR-gated (R62-style fragility on pillar_O). Lesson #67.

- **Regime fingerprint (VDB 做多, M-WO-7.1, Seth, 2026-07-28)** — 12-dim per-trade-date vector over validated modules (S-78 vol + M-WO-2 EXT pillar IC + R75 S/O + R62 detector + R76 funding + asset_embeddings centroid). Schema v3, HNSW cosine on dense core + JSONB null for NaN. UNBLOCKS M-WO-1 ≥8 episode floor via match_regime_fingerprints RPC. Spec: docs/REGIME_FINGERPRINT_SPEC.md.

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
