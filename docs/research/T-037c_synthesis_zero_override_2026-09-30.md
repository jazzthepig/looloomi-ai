---
task: T-037c
lane: B (Seth/Austin)
parent: T-037
status: in_progress
acceptance: "T-037 25 策略 + 11 graveyard entry × {§5b layer / spec_family / universe / regime gate / ⓪ OVERRIDE use / style exposure / ready-live} 综合矩阵。零模拟、零数字。只读 + 综合。"
date: 2026-09-30
---

# T-037c — ⓪ OVERRIDE doctrine 综合矩阵(T-037 策略 × ⓪ 缺口的结构图)

**Per JAZZ §S-440 / §S-442(2026-09-30)+ HIGH_DIM_ONTOLOGY §5b-bis + DECISION_PATH_SPEC §1 +
ALLOCATION_ARCHITECTURE_v0.2 §3 L1.** JAZZ 自指的实际空缺是 **⓪「风格/流动性周期」判断
从未被结构化接上** —— 设计文档把它摆在四层之上,但代码层:
- 没有「风格表头」(T-039 在做);
- 没有 ⓠ 阶段把动量/广度/趋势强度 lead 指标接到仓位(per R11/R12/R14);
- §9 entity/decision 写者活着,`decisions` 0 行(SPINE §2 第 9 段);
- §7b 组合 gross 预算段**根本没建**(SPINE §2 第 7b 段,3.3x 前提);
- meme/AI 价格历史空白(binance_hist 只 3 个 meme,hyperliquid 几周后停)。

**本表的目的:** 把 T-037 25 策略 + 11 graveyard entry 摊在一张矩阵里,看清楚哪条策略
依赖 ⓪ 而 ⓪ 没接上、哪条完全 style-blind、哪条已经在吃 lead 指标、哪条只在残差里找。
这把 T-038(多风格轮动预注册)和 T-039(风格表头落库)的输入合一 —— 风格表头落库前
哪些策略可以重算,落库后又解锁哪些。

**零模拟、零数字、零代码。** 本表是**结构图**,不是设计提议。

---

## §A · 主综合矩阵 —— T-037 25 策略 × 7 维度

**列定义:**
- **§5b 层**:①=beta capture,②=beta+ tilt,③=multiplier(never short),④=pure alpha,⓪=OVERRIDE(per HIGH_DIM_ONTOLOGY §5b / §5b-bis)
- **family**:spec_runner `spec_family` 落点或 research-only
- **universe**:T-037 §A 八桶标注(粗);T-039 落库后才有 PIT 完整版
- **regime gate**:策略实际用 `macro_regime` / `regime_daily` / 5a/5b 相位 / 无
- **lead 指标**:用 R11/R12/R14 类型的提前信号吗(pane-CIS leads macro 7d / breadth_200ma leads CIS 1d / trend_strength leads CIS 1d)
- **⓪ OVERRIDE 依赖**:策略的判定/权重是否依赖**风格/相位判断** —— 这是设计第一性,不是 §5b 层的辅助
- **ready**:🔬 research-only / 📋 spec_runner wired(无 paper) / 📊 paper-track(有 / 真实) / 🟢 live

| # | 策略 | §5b 层 | family / wiring | universe | regime gate | lead 指标 | ⓪ OVERRIDE 依赖 | ready |
|---|---|:---:|---|---|---|---|---|:---:|
| 1 | C-5 ① 等权 NAV(24-name) | ① | research-only | 全桶(无 meme/AI) | **无** | **无** | **❌ style-blind** | 🔬 |
| 2 | C-12 ① NAV cap-weighted(静态 mcap) | ① | research-only | 全桶 | **无** | **无** | **❌ style-blind** | 🔬 |
| 3 | C-16 ① NAV cap-weighted(real historical mcap) | ① | research-only | 全桶 | **无** | **无** | **❌ style-blind** | 🔬 |
| 4 | C-17 Book B excess vs C-16 | (差) | (差) | 全桶 | (随基线) | (随基线) | (随基线) | 🔬 |
| 5 | M-93 single survivor | ②/③ | `decide_survivors_book` 内 | panel 多资产 | 间接(regime_quorum) | **无** | **❌ 不显式** | 📋 |
| 6 | M-113 Book A(M-93+R19-Lite) | ② risk-parity | `survivors_only_lag1_book` | panel | 间接(regime_quorum) | **无** | **❌** | 📋 |
| 7 | M-115 Book B(M-93+R14-Lite) | ② risk-parity | 同上 | panel | 间接 | **无**(R14-Lite 是 factor,不是 lead) | **❌** | 📋 |
| 8 | M-116 OOS split Book B | ② | (OOS test) | panel | — | — | — | 📋 |
| 9 | **M-128d 2D gate** | ⓪ + ③ | `decide_gated_2d` wrapper,**无 family** | panel | **5a 宏观 + 5b 微观 两角度** | **composite_z 来自 R11/R12** | **✅ 强 — RISK_OFF×NEUTRAL → CASH** | 📋(per §S-442 registry-only) |
| 10 | **M-130 ⓪ OVERRIDE trigger A** | ⓪ | research-only | panel | DD-stop −20% → cash | **无 lead**(只是反应) | **✅ 强反应式 OVERRIDE** | 🔬 |
| 11 | **M-131 ⓪ OOS** | ⓪ | research-only | panel | ⓪ derived β=0.060 | β=0.060 = 94% decoupled | **✅** | 🔬 |
| 12 | M-140 ⓪+④ composition | ⓪ + ④ | research-only | panel | — | — | **✅ 形态对,M-145 sparse 守卫 FAIL** | 🔬 |
| 13 | M-146 R73-B cluster-aware ④ | ④ | research-only | panel | — | — | **❌ 残差里找,无 ⓪** | 🔬 |
| 14 | **M-147 ⓪+④ book** | ⓪ + ④ | research-only | panel | — | — | **✅ 形态对,8/8 SHIP-READY** | 🔬 |
| 15 | M-152 CDCB-A v2(BTT-LEX + CCCL) | ① + ② | BTT-LEX 走 `btc_trend_regime_ladder`;CCCL **无 family**(per §S-442) | BTC + panel | BTT-LEX 用 regime ladder | **regime ladder 是 lag=1 反应式,不是 lead** | **❌ 不显式** | 📋(BTT-LEX)+ 🔬(CCCL) |
| 16 | R70 production-realistic | ② | research-only | 28-asset strict | macro_regime-gated | **无 lead** | **❌ 不显式**(regime gate 是 lag,不是 lead) | 🔬 |
| 17 | R76 standalone L/S | ④ | research-only | 28-asset strict | — | — | **❌ 残差里找** | 🔬 |
| 18 | R77 fusion cell | ④ | research-only | 28-asset strict | — | — | **❌** | 🔬 |
| 19 | M-150b 25/75 cost-Pareto | ② | research-only | panel | — | — | **❌** | 🔬 |
| 20 | **M-129 §5b-ter stop rule** | ⓪ | research-only(无 spec family) | panel | DD-stop −20% → cash | **无 lead**(反应式) | **✅ bear-window OVERRIDE 验证** | 🔬 |
| 21 | M-189(T-034) MECH_tom HL 4-coin | ① + ③ | `m189_replay.py` + `hl_book.tom_targets`,**不接 spec_runner** | BTC/ETH/SOL/HYPE | — | — | **❌ 不显式**(但风格 = 大币 only) | 📋 |
| 22 | M-189 VOL_tom | ① + ③ | 同上 | BTC/ETH/SOL/HYPE | — | — | **❌** | 📋 |
| 23 | BETA_PLUS ②-MOM | ② | `beta_plus_momentum.compute_path`,**不接 spec_runner** | 24-name panel | — | — | **❌** | 📋(per §S-442 无 family) |
| 24 | TOKENIZATION_TILT ②-TOK | ② | 同上 | 75% panel + 25% basket | — | — | **❌ 但 25% 篮子 = 风格切片**(S-427) | 📋 |
| 25 | M-140 H0_hold baseline | ① | — | BTC/ETH/SOL/HYPE | — | — | **❌ 大币 only,无 ⓪** | 🔬 |

### Graveyard(11 entry)

| # | Sleeve | §5b 层 | 死因 | ⓪ 缺口诊断 |
|---|---|:---:|---|---|
| G1 | R76-R94(15 attempts) | ④ | 构造上中性 = 先扔 beta | **❌ 从来没用 ⓪**,所以 15 次全灭是设定错误 |
| G2 | M-95c / M-108 / M-110 / M-112 | ④ | same-bar look-ahead + cost calibration moot | **❌ 无 ⓪**;book Sharpe +8.2 是同一 bar leak,不是真 edge |
| G3 | V7_MTF(R332-R346) | ④ micro-trend | minute-:15 exit 95.4% P&L = code defect | **❌ 无 ⓪**(这是 micro trend,不是 cycle 判断) |
| G4 | Strategy 3 Pod Aggregator | ④ + ② | per-pod −15% DD circuit breaker trips W3 | **⚠️ 有 DD stop,但缺 ⓪ OVERRIDE 早期信号** |
| G5 | Strategy 4 Cross-Asset Tilt | ② long-only | W5=-28.25%;0/720 sweep pass | **❌ 含 TradFi ETF 但无 ⓪ 风格轮动判断** |
| G6 | R89 perp-spot basis | ④ | dies ≥10bps(cost_t=-0.69) | **❌** |
| G7 | Outter v1.0 fixtures | (advisory) | S-435 ② 拒:合成数据非证据 | **⓪ OVERRIDE 形态对,但 fixture 是 0** |
| G8 | m147 walk-forward v2 | ④ ETH-only | ETH-only single-asset ML = §5b ④ 在 ETH 第 16 次 | **❌ + ETH-only = 暴露高度集中** |
| G9 | R95 funding IVOL residual | ④ | ΔOOS_t +0.18 < bar +0.5 | **❌ 残差里找** |
| G10 | R96 funding MOMENTUM residual | ④ | ΔOOS_t +0.05 marginal | **❌** |
| G11 | R82 pillar_A regime-gated | ④ | gross_t=+1.45 < 1.96 | **❌ regime-gated 但 lag,不是 lead** |

---

## §B · ⓪ OVERRIDE 依赖视图 —— 谁靠 ⓪、谁不要 ⓪、谁假装用 ⓪

**三组:**
- **A. 真用 ⓪ 的策略(7 条):** M-128d / M-130 / M-131 / M-140 / M-147 / M-129 / TOKENIZATION_TILT(形式上)
- **B. 假装用 ⓪ 但实际是 lag-reaction 的(8 条):** BTT-LEX / R70 / R82 / Strategy 4 / Pod Aggregator(DD-stop 是 reaction,不是 lead)/ R77 fusion / R76 / R89
- **C. 完全 style-blind 的(11 条 + 11 graveyard):** 所有 ① NAV、所有 ④ 残差、所有 cross-sectional

**关键洞察:** **A 组总共也只 7 条,且全部 research-only(spec_runner 仅 M-128d wrapper,无 family)。**
B 组用 `macro_regime` 当 lead 用,但 macro_regime **本身** 是 lag(S-440:macro_regime 单阈值跳变,median 3d 持久,< 5d CI 门槛),所以即使 gate 了也是事后。
C 组不知道自己在哪一段周期 —— **C-5 vs -7.5% 的 51pp 差就是 C 组根本不知道风格暴露存在的实证**。

| 类别 | 数量 | 决策依赖 | 当前 ready |
|---|---:|---|---|
| **A 真 ⓪**(依赖 style/phase 判断) | 7 | 必须有风格表头 + 5a/5b 相位 + lead 指标 | 全 🔬(M-128d 仅 📋 wrapper) |
| **B 假装 ⓪**(实际 lag-reaction) | 8 | regime_quorum / DD-stop / regime ladder | 📋🔬 混合 |
| **C style-blind**(不知周期) | 11 + 11 | 不知道依赖什么 | 全 🔬 |

**架构含义:** 如果只让 A 组 live,B + C 全 paper-track,**⓪ OVERRIDE doctrine 就只覆盖 25 策略里的 7 条 + 11 graveyard 中的 1 条(Outter)** —— 还不到三分之一。**要 doctrine 真起作用,A 组必须扩到 ≥ B + C 的关键 sleeve,而 B + C 要先表态愿不愿意用 ⓪**。

---

## §C · 风格暴露模式图 —— 哪些策略聚在同一风格,哪些跨风格

按 T-037 §A 八桶(JAZZ 定):

| 风格桶 | T-037 内 strategy 命中 | 含义 |
|---|---|---|
| **大币**(BTC/ETH) | #21/22/25 M-189 + H0_hold | M-189 全仓大币,**无风格切换能力**(这就是为什么它在 BTC 周期 +92% / 山寨周期反向时表现依赖周期) |
| **头部公链 + 二线公链 + L2** | #1-4 C-5/C-12/C-16/C-17 + #5-8 Book A/B + #15 M-152 + #23-24 ②-MOM/②-TOK + #16 R70 + #17-19 R76/R77/M-150b + #9-14/20 M-128d/M-130/M-131/M-140/M-147/M-129 | **占 21 条 —— 整个 panel 多资产策略都聚在这块,无风格切换** |
| **DeFi** | 同上(panel 含 DeFi) | 全 panel 策略都暴露 |
| **基础设施与代币化** | #24 TOKENIZATION_TILT 25% 篮子 + #16 R70(若 RWA 主题计) | **只有 1-2 条** |
| **AI** | **0 条** | **空白** |
| **meme** | **0 条**(DOGE 跨界但 panel 中是头部公链桶) | **空白** |

**关键洞察:**
1. **整个 panel 多资产策略(19/25)** 都吃同一风格 = 头部公链 + 二线 + DeFi。当 BTC 周期 / 山寨周期轮动时,**这 19 条策略的相关性会同时变化,本质上是同一个 beta**(R13:零结构 lead-lag,所有 panel 内 pair 在 lag=0 相关最大)。
2. **唯一明确做风格切片的是 TOKENIZATION_TILT(25% 篮子)**,但**形式上是 75% panel + 25% basket 固定权重,不是 ⓪ OVERRIDE 动态切**。
3. **AI / meme 桶零策略**,与 JAZZ 指出的"meme/AI 价格历史空白"对称 —— 数据空白 → 无策略可建。
4. **大币 only sleeve(M-189 / H0_hold)用 BTC/ETH/SOL/HYPE** —— SOL 在 T-037 §A 是头部公链,HYPE 是单 perp(不在 24 名),所以 M-189 实际是 1 大币 + 1 头部公链 + 1 perp,**风格标签混**。

**架构含义:**
- 19 条 panel 多资产策略的相关性结构让它们**事实上是一个 sleeve**,分散度是错觉
- 真正的分散需要**风格间**(大币 vs 山寨 vs DeFi vs meme)而不是**风格内**
- ⓪ OVERRIDE 真正的价值就是做**风格间切换**,不是策略内调权 —— 这是 JAZZ 2026-09-30 提的"大币周期还是山寨周期"的真意

---

## §D · 结构缺口 —— ⓪ OVERRIDE doctrine 真接上需要哪些组件

按优先级(谁挡谁):

### D1 · 风格表头(per JAZZ T-039)—— **第一缺**

- 缺什么:每个标的 × 每天 × 风格桶(大币/头部公链/二线+L2/DeFi/基础设施/AI/meme)+ PIT 市值档位 + 各风格市值加权/等权指数 + 每本账本对各风格的暴露
- 谁挡:§5b-bis ⓪ / DECISION_PATH_SPEC ① / ALLOCATION v0.2 §3 L1 / M-128d composite_z 全要这张表头
- 现状:asset_class 现有 schema 只有 L1/L2/DeFi/RWA/Infrastructure 五类粗分类,T-039 落库前没有任何结构化风格数据
- 谁做:**JAZZ**(per Rule 3b 数据回填归 JAZZ)

### D2 · 5a/5b 相位检索(per SPINE §2 第 5 段)

- 缺什么:`similar_market_states()`(5a 宏观 15 维)+ `regime_match`(5b 微观 11 维 CIS)+ **合成规则**(按排名一致性,不允许平均相似度数值)
- 谁挡:M-128d composite_z / §6 ⓠ 层 `beta_core_q_overlay`(per SPINE §5 第 9 项 `vdb_matcher_live` 已接)
- 现状:**5a 已修 S-362(z 化 + 排邻 + 接线),底表停 42 天**(binance_hist 8 天死)**= 通了但源死了**;5b 已修且每日更新
- 谁做:C lane 修源(SPINE §5 第 3 项,已上日程 S-361 `_market_state_loop`)+ **合成规则需要落到 ⓠ 层(per §4)** = C lane / Seth 拍

### D3 · Lead 指标族(per R11/R12/R14)

- 已有:**R11 panel-CIS leads macro_regime 7d** · **R12 panel-breadth leads asymmetric** · **R14 trend_strength + breadth_200ma lead CIS 1d**
- 缺什么:这 4 个 lead 指标**没有一个进 ⓪ OVERRIDE** —— 它们还停在 R-number 阶段,没人 ship 到 spec_runner / nav_kernel
- 谁挡:M-128d 是唯一用了 lead 的(用 R11/R12 composite_z),但 §S-442 JAZZ 拍 M-128d **registry-only 不接 family**
- 现状:lead 指标是研究金矿,但**研究 → 生产** 没 ship —— 这是 §5b-bis 设计第一性的"从未被接上"的具体形态
- 谁做:**Seth**(把 R11/R12/R14 ship 到 nav_kernel 旁路 OR spec_runner wrapper)

### D4 · ⓠ 层归宿(per SPINE §5 第 9 项 + §5b-ter Millennium stop)

- 缺什么:ⓠ 每天的 cap 决定有持久归宿(不是 `/tmp/.../regime_track.csv` —— Railway 每次部署就清空);每 sleeve 有 `max_dd_stop` + `capital_action_on_breach`
- 谁挡:M-129 / M-130 验证 bear-window OVERRIDE 有效,但**没 ship 到 spec**;§7b 组合 gross 预算根本没建
- 现状:`regime_override_enforcer` 零导入(S-366 查清);活的是 `beta_core_q_overlay`(乘数语义,正确);S-378 已接 `vdb_matcher_live` 默认 True;**v2 needs borrow-cost model 未 ship**(短卖成本是 −0.5x 能否成立的前提)
- 谁做:**Seth + JAZZ**(`max_dd_stop` 字段 + `allocation_override` 表 per ALLOCATION v0.2 §3.4)

### D5 · §9 entity/decision 内核(per SPINE §2 第 9 段)

- 缺什么:`entities` 103/103 有 vec 但 `decisions` 0 行;`treasury_*` 是领域源不是后继(已澄清);`treasury → entities/decisions` 的抽象跳缺
- 谁挡:⓪ OVERRIDE 的「决定」要有去处 —— 没 §9 落地,ⓠ 永远是 /tmp
- 现状:写者活着(`entity_store.py:83/:104`),产出近乎为零(S-334 模式:写者返回 False 被吞)
- 谁做:**Minimax-C**(per SPINE §5 第 8 项,先查写入返回再怀疑数据源)

### D6 · meme / AI 价格历史(per JAZZ 2026-09-30)

- 缺什么:binance_hist 只 DOGE/PEPE/1000SHIB;hyperliquid 几周后停(08-23 起)
- 谁挡:AI 桶 / meme 桶 0 策略(§C)
- 谁做:**JAZZ**(per Rule 3b 数据回填归 JAZZ)

### 总结 —— ⓪ OVERRIDE 接上的依赖图

```
T-039 风格表头(D1)
     ↓
5a/5b 相位 + 合成规则(D2) + Lead 指标族(D3)
     ↓
ⓠ 层归宿 + §5b-ter stop(D4)
     ↓
§9 entity/decision 内核(D5) → decisions 落地
     ↓
⓪ OVERRIDE doctrine 真起作用
     ↓
A 组 7 条 live + B/C 关键 sleeve 表态愿不愿意用 ⓪
```

**JAZZ §S-442 答的 v0.2 phase 1 三件(T-037 + T-037b + T-039)是这条链的**第一步**;**第二步到第六步还全部没排期**。

---

## §E · 对 T-038(多风格轮动预注册)与 T-039(风格表头落库)的输入

### 给 T-038(lane-c 预注册)

按 JAZZ §S-440 T-038 = "BTC↔alt 切片,粗到不能再粗"。从本综合矩阵看:

- **第一步该跑的是「风格间相关性」:** R13 已证 panel 内零 lead-lag,所以 panel 多资产 19 条策略事实是一个 sleeve。**真轮动应该是「BTC vs 山寨等权」+「头部公链 vs 二线+L2」+「DeFi vs 基础设施」+「meme vs 其它」**(meme 桶要 D6 先填数据)
- **预注册格子建议:** (BTC vs 山寨) × (周期 vs 反周期) × (R11 lead 用 vs 不用) = 8 格,不要 4 桶(§S-442 JAZZ 答 v3 不分桶)
- **baseline:** 等权 BTC + 等权山寨,不用 0;每格 n 至少 30 天

### 给 T-039(JAZZ 落库)

按本表需要:

- **表头最少要 8 桶:** 大币 / 头部公链 / 二线公链+L2 / DeFi / 基础设施与代币化 / AI / meme / (可选 RWA 主题)
- **每币 × 每天 × 桶 + PIT 市值档位:** 用 CoinGecko categories + 自维护映射 + 历史 mcap 分位(per T-037 §E Q6)
- **每桶算两个指数:** 市值加权 + 等权
- **每本账本对各桶的暴露:** 现有 9 本逐日账本(`beta_core_nav` ① / `beta_plus_daily` ②-MOM / `tokenization_tilt_daily` ②-TOK / `hl_book_daily` / `fusion_paper_nav` / `combined_book_nav` / `causal_paper_nav` / `dingge_paper_nav` / `scalable_book_nav`)在每桶的暴露比例
- **不能做:** 不能用现有 asset_class 5 类粗分类(缺 meme / AI / 档位)直接迁

### 给 JAZZ 的直接问题

| Q | 内容 |
|---|---|
| Q1 | ⓪ OVERRIDE 接上的 6 件(D1-D6),哪件先做?要不要在 T-039 + nav_kernel 之间塞 5a/5b 合成规则 + R11/R12/R14 ship? |
| Q2 | B 组(lag-reaction 的 8 条)要不要表态愿不愿意用 ⓪?如果不愿意,⓪ OVERRIDE doctrine 只覆盖 7/25 + 1/11 = 28% sleeve |
| Q3 | §9 entity/decision 内核缺抽象跳(`treasury → entities/decisions`),JAZZ 拍不拍 Min-C 的 producer rebuild?per Rule 5b 三缺一当前写者活着 = producer 缺 = P0 |
| Q4 | meme / AI 数据回填是 JAZZ lane(per Rule 3b),T-039 风格表头要不要等 meme/AI 数据再落? |

---

## §F · References

- T-037 §A-§F — 25 策略 + 11 graveyard + §C 数字差异 reconcil + §D 守卫 vs 记账
- T-037b §A-§G — 代码 → 目标权重函数接口表
- HIGH_DIM_ONTOLOGY §5b / §5b-bis / §5b-ter — 4 层 + ⓪ OVERRIDE + Millennium stop
- DECISION_PATH_SPEC §1 — 决策顺序(风格/相位 → 入池 → 权重 → 执行)
- ALLOCATION_ARCHITECTURE_v0.2 §3 — L0 数据 → L1 状态(风格表头 = T-039) → L2 策略库 → 评估 → L3 配置 → L4 执行
- SPINE.md §2 第 5a/5b/6/7b/9 段 — 5a 宏观相位 / 5b 微观相位 / ⓠ 层 / 组合 gross / entity-decision kernel
- TRADER_TOM_DOCTRINE §3 IR / §5b expectancy / §5c skew × ruin — 书 level 与 §5b-bis 同向
- ARCHITECTURE.md §kernel / §strategy first principle / §iPod → OS — 设计与产品形态
- MEMORY r11/r12/r13/r14 / m127/m128a/m128c/m128d / m129/m130/m131/m140/m146/m147 / m152 / m189 — R/M-编号 mining output

---

*Lane: B (Seth/Austin) · Status: in_progress · 验收:25 策略 + 11 graveyard × 7 维度 ✓ · 零模拟 ✓ · 零数字 ✓ · 不出 nav_kernel 规格 ✓*