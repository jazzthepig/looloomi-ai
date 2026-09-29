---
task: T-037
lane: B (Seth/Austin)
parent: T-036
status: in_progress
acceptance: "覆盖 B 阶段 1 报告里 A 表全部行;每个自报数字都标「自报,未重算」;不出现任何新算的数字。"
date: 2026-09-30
---

# T-037 — 历史策略清点(只收集、不重算)

**Per JAZZ §S-438 / §S-438b 2026-09-30.** JAZZ 指出研究的真正缺口是 ⓪「风格/流动性周期」在
设计里排第一(HIGH_DIM_ONTOLOGY §5b-bis, DECISION_PATH_SPEC ①, ALLOCATION_ARCHITECTURE_v0.2
§3 状态表头),而研究一路往二值方向做。T-039 风格表头由 JAZZ 拍板 + Seth 执行;T-038 多风格轮动
研究由 lane-c 预注册;**本表(T-037)是 v0.2 阶段 1 公用记账内核落库前的输入**:把过去每个「报过
跑赢持有」的策略清点出来,逐行标风格暴露,让 T-039 落库后能用同一套 nav_kernel 重算,看「alpha」
是不是只是某个风格暴露。

**三处 JAZZ 纠正(已应用):**
1. 表中所有 SR / cum / MaxDD / OOS 数字均 **自报,未重算** —— 来自原文献(MEMORY / REFUTATION_LEDGER
   / STRATEGY_PLAYBOOK / mining output)的报告值。**重算由 JAZZ 用 v0.2 阶段 1 的公用记账内核做,
   B 不跑任何模拟。**
2. 等权面板 24 名 −58.84% 与 JAZZ 实测 −7.5% 对不上,§C 详记两处来源、窗口、币池范围、可能的差异原因。
3. M-114 / regime_quorum 等是**守卫** —— 它们只判断"这条数字能不能信",不构成记账方法。**记账只有
   一套:所有策略共用同一个日 NAV 计算函数**(v0.2 phase 1 要建的就是它,ALLOCATION_ARCHITECTURE_v0.2 §3)。

---

## §A · 风格桶(JAZZ 2026-09-30 定)

| 桶 | 范畴 | 标的(2026-09 snapshot,仅作示例 — 真表头 T-039 才有完整 PIT 历史) |
|---|---|---|
| **大币** | 市值 ≥ BTC/ETH 一档或 BTC/ETH 本身 | BTC / ETH |
| **头部公链** | 老牌 L1 + 高市值智能合约平台 | SOL / BNB / XRP / ADA / AVAX / DOGE |
| **二线公链 + L2** | 二线 L1 与 L2 | NEAR / APT / ATOM / DOT / ARB / OP |
| **DeFi** | DEX / 借贷 / 流动性质押 / 衍生品 | UNI / AAVE / CRV / LDO / COMP / GRT / INJ / MKR*(已迁 SKY)* |
| **基础设施与代币化** | 预言机 / 跨链 / 发行 / 链上场所 | LINK / ONDO / PENDLE / POLYX |
| **AI** | AI 主题 | (空 — 没有系统化定义,JAZZ 拍后补) |
| **meme** | meme 主题 | DOGE*(跨界,头部公链重叠)* / PEPE / 1000SHIB |
| **RWA 主题**(JAZZ 09-26 加) | 传统金融上链通路 | 与「基础设施与代币化」高度重合;S-427 篮子用 LINK/ONDO/PENDLE/POLYX/AAVE/UNI/HYPE |

**空白:** asset_class 现有 schema 只有 L1 / L2 / DeFi / RWA / Infrastructure 五类粗分类,**没有档位、
没有 meme、没有 AI、没有市值分位**。这就是 T-039 要补的表头。meme / AI 的价格历史目前只在
Hyperliquid 有几周(且 08-23 起停),其余空白 —— T-039 由 JAZZ 亲自回填(per Rule 3b 数据回填归 JAZZ)。

---

## §B · 主清点表 —— 每个「报过跑赢持有」的策略一行

> **数字阅读提示:** SR / cum / MaxDD / OOS 列均为**自报,未重算**。窗口 / 基准列精确到日。风格列
> 反映策略所用币池的桶分布(粗标 —— 具体单币映射 T-039 落库后才有)。⚠️ 风格列里凡是涉及"小盘"
> 或"meme"的多半是**没暴露**,不是漏标 — 旧实验的币池是 24/28-asset strict 主流币,没有 meme / AI。

| # | 策略 / Sleeve | §5b 层 | 窗口 | 宇宙(币池) | 风格暴露(粗) | SR(自报) | cum(自报) | MaxDD(自报) | OOS(自报) | 基准 | 备注 |
|---|---|---|---|---|---|---:|---:|---:|---|---|---|
| 1 | **C-5 ① 等权 NAV**(24-name) | ① | 2023-12-27 → 2026-09-20 (999d) | BTC/ETH/SOL/BNB/XRP/ADA/AVAX/DOGE/ARB/OP/NEAR/APT/UNI/AAVE/MKR/LINK/ONDO/DOT/INJ/CRV/LDO/ATOM/COMP/GRT | 大币+头部公链+二线/L2+DeFi+Infra/Toke,**无 meme/AI** | -0.381 | **-58.84%** | -84.03% | — | 自身 | c-path memory 自报;**§C 与 JAZZ −7.5% 冲突,需 reconciliation** |
| 2 | **C-12 ① NAV cap-weighted**(静态 mcap) | ① | 同上 | 同 24 名 | 同上 | +0.281 | +47.19% | -61.02% | — | 自身 | C-path memory;**BIASED HIGH(用 09-20 静态 mcap 倒推,C-17 验 −25.66pp bias)** |
| 3 | **C-16 ① NAV cap-weighted**(REAL historical mcap) | ① | 同上 | 同 23 名(MKR 由 ADV 自动退出) | 同上 | +0.134 | +21.53% | -61.67% | — | 自身 | C-path memory;**TRUTH 版** |
| 4 | **C-17 Book B excess vs C-16** | (差) | 2023-04-02 → 2026-07-18 (936d) | 24-22 aligned | 同上 | ΔSR -1.656 | **+325.30pp** | — | — | C-16 | C-path memory;**biased baseline UNDERSTATED alpha +50.99pp** |
| 5 | **M-93**(single survivor post-M-112) | ②/③ | 1196d | panel 多资产(具体见 R77/R76 模块) | 大币+公链+DeFi(待 T-039) | — | — | — | — | — | M-113/115/128d/130/131/146/147 共享组件 |
| 6 | **M-113 Book A**(M-93+R19-Lite) | ② risk-parity | 1196d | 同 M-93 | 同上 | **+1.249** | +180.6% | -26.89% | — | hold-the-panel | MEMORY m113-honest-book-baseline |
| 7 | **M-115 Book B**(M-93+R14-Lite) | ② risk-parity | 1196d | 同 M-93 | 同上 | **+1.629** | +321.5% | -22.9% | +1.218 (60/40) | hold-the-panel | M-115 SHIP-READY |
| 8 | **M-116 OOS split Book B** | ② | 60/40 split | 同上 | 同上 | +1.218 | — | — | pass | hold-the-panel | OOS test;**70/30 +0.354 borderline,V3 REFUTED** |
| 9 | **M-128d 2D gate** | ⓪ OVERRIDE + ③ | OOS split | 同 panel 多资产 | 大币+公链(TRADFI RISK_OFF 维度) | **+2.778 OOS** | — | -26.47% | +2.448 (70/30) | hold-the-panel | 9/10 PASS;M-114 retention 1.578 |
| 10 | **M-130 ⓪ OVERRIDE** | ⓪ | bear window | 同 panel | 大币+公链+DeFi | +1.251 | — | — | — | ② 原值 -0.094 | Trigger A DD-stop −20% → cash 转换 |
| 11 | **M-131 ⓪ OOS** | ⓪ | OOS | 同 panel | 同上 | +0.428 | — | — | β=0.060 | hold-the-panel | 10/10 PASS;**94% decoupled from market** |
| 12 | **M-140 ⓪+④ composition** | ⓪ + ④ | — | 同 panel | 同上 | — | — | — | — | — | 6/7 FAIL M-145 sparse-sleeve guard(hit_rate 0.245-0.440 < 0.45);winner 0%/100% pure ⓪ |
| 13 | **M-146 R73-B cluster-aware ④** | ④ | 1206d | 同 panel | 同上 | +0.805 | +140.7% | — | +0.400 | hold-the-panel | validated ④ slot |
| 14 | **M-147 ⓪+④ book** | 60% ⓪ + 40% ④ R73-B | — | 同 panel | 同上 | **+1.121** | +141% | **-17.4%** | — | hold-the-panel | 8/8 SHIP-READY |
| 15 | **M-152 CDCB-A v2**(BTT-LEX + CCCL) | ① + ② | 775d | panel 多资产 | 大币+公链 | **+1.115** | +178.0% | -20.44% | 2025 vs BTC -8.42pp | BTC | 7/8 PASS(T-035 待 S-420 复核) |
| 16 | **R70 production-realistic** | ② macro_regime-gated pillar_A L/S | 1196d | 28-asset strict (R64) | 大币+公链+DeFi | **+1.083** | — | — | — | hold-the-panel | M2 β-IS-fixed |
| 17 | **R76 standalone L/S**(Strategy 2) | ④ cross-sectional funding LEVEL residual | 770d | 28-asset strict | 大币+公链+DeFi(无 perp-only 标的) | t +2.06 | — | — | t +2.47 | hold-the-panel | frozen 5d/0bps/k=3/high_fund_long;forward 0/60d |
| 18 | **R77 fusion cell**(Strategy 1) | ④ R46+R62+R76 fusion | 770d | 28-asset strict | 同上 | t +2.44 | — | -14.70% | t +2.45 | hold-the-panel | w_R46=0.25/w_R62=0.75/w_R76=0.30;forward 34/60d |
| 19 | **M-150b 25/75 cost-Pareto** | ② cost-Pareto | 775d | panel 多资产 | 大币+公链+DeFi | +5.0× LP-mandate | — | — | pass | hold-the-panel | 25/75 + 50/50 都 on Pareto at 4/4 cost levels;**50/50 hit rate 0/4 LP mandate** |
| 20 | **M-129 §5b-ter stop rule** | ⓪ OVERRIDE in bear | bear window | 同 panel | 大币+公链+DeFi | **+1.352** | +96.26% | -17.82% | — | ② -0.196 | ⓪ OVERRIDE doctrine validated |
| 21 | **M-189 (T-034) MECH_tom HL 4-coin** | ① + ③ Tom doctrine | 2227d / 1226 Mondays | BTC/ETH/SOL/HYPE | **大币 only + HYPE(HYPE 是单 perp,非 24 名)** | **1.42** | — | **-36.04% (MECH) / -27.43% (VOL)** | — | H0_hold SR 1.07 MaxDD -56.26% | lag-1 retention 0.840/0.827;cost 12 bps;**lane-b just shipped** |
| 22 | **M-189 (T-034) VOL_tom** | ① + ③ Tom doctrine + vol-formula | 同上 | 同上 | 同上 | 1.42 | — | -27.43% | — | H0_hold | Δ sharpe vs fixed +0.0024(几乎平,MaxDD 改善 8.6pp) |
| 23 | **BETA_PLUS_2026-09-26 (②-MOM)** | ② 面板内动量+52w 高点 | 7-yr history(2020+) | 24-name panel | 大币+公链+DeFi+Infra | — | **+16.6%/年 t 3.29** | -11.0% | +8.7% | 同日程等权 | forward 0/60d;7 份分批周频 + 月频 4 臂 |
| 24 | **TOKENIZATION_TILT_2026-09-26 (②-TOK)** | ② 代币化倾斜 | 4-yr history(2022-10+) | 75% 24-name panel + 25% basket(LINK/ONDO/PENDLE/POLYX/AAVE/UNI/HYPE) | 75% 大币+公链+DeFi + 25% Infra/Toke | — | tilt +154% vs panel +78% | — | — | panel_hold 24 名等权 | **篮子事后挑的**;forward 0/60d |
| 25 | **M-140 MECH_tom baseline(H0_hold)** | ① | 2227d | BTC/ETH/SOL/HYPE | 大币 only + HYPE | 1.07 | — | -56.26% | — | — | HL 4-coin panel baseline;**真痛点:无风控时 −56% DD** |

### 已被 REFUTED / Graveyard(打过 buy-hold 但死了 / 或死了但有信息)

| # | Sleeve | §5b 层 | 死因(自报) | 宇宙(自报) | 风格暴露(粗) | 来源 |
|---|---|---|---|---|---|---|
| G1 | **R76-R94**(15 attempts) | ④ cross-sectional demean | "构造上中性 = 先扔 beta = ④" | panel 多资产(变体) | 大币+公链+DeFi | ARCHITECTURE §5b;R-numbering |
| G2 | **M-95c / M-108 / M-110 / M-112** | ④ | **same-bar look-ahead + cost calibration moot** | panel 多资产 | 同上 | M-112 P0 voided;Book Sharpe +8.2 → 真 +1.25/+1.63 |
| G3 | **V7_MTF (R332-R346)** | ④ micro-trend-following | 342/1010 trades exit at minute-:15 = 95.4% book P&L = code defect | 多资产 | 多风格 | MEMORY v7-mtf |
| G4 | **Strategy 3 Pod Aggregator** | ④ + ② | per-pod −15% DD circuit breaker trips in W3, flatlines W4-W6 | R77 family | 大币+公链+DeFi | STRATEGY_PLAYBOOK |
| G5 | **Strategy 4 Cross-Asset Tilt** | ② long-only | gross_t=+0.310, oos_t=+1.530, W5=-28.25%;0/720 sweep configs pass | 41-asset crypto + 17 TradFi ETFs | **多风格 + TradFi** | STRATEGY_PLAYBOOK |
| G6 | **R89 perp-spot basis** | ④ | clears 3/3 at 5bps but dies ≥10bps (cost_t=-0.69) | panel 多资产 | 大币+公链+DeFi | STRATEGY_PLAYBOOK |
| G7 | **Outter v1.0 fixtures** | (advisory) | S-435 ② 拒绝:合成数据上选出的格子不是证据 | (fixture only) | n/a | MINIMAX_SYNC §S-435 |
| G8 | **m147 walk-forward v2** | ④ ETH-only single-asset ML | ETH-only single-asset ML = §5b ④ 在 ETH 上的第 16 次尝试 | ETH only | **大币,但 single-name** | JAZZ 2026-09-29 第二轮 pushback;_archive/2026-09-29_eth_wf_v2/ |
| G9 | **R95 funding IVOL residual** | ④ | standalone REFUTED;作为 R77 4th leg ΔOOS_t +0.18(< bar +0.5) | 28-asset strict | 大币+公链+DeFi | STRATEGY_PLAYBOOK |
| G10 | **R96 funding MOMENTUM residual** | ④ | standalone REFUTED;cleanest orthogonal (max \|corr\|=0.198) but ΔOOS_t +0.05 marginal | 同上 | 同上 | STRATEGY_PLAYBOOK |
| G11 | **R82 pillar_A regime-gated** | ④ | gross_t=+1.45 < 1.96 | 同上 | 同上 | STRATEGY_PLAYBOOK |

---

## §C · 等权面板 24 名 −58.84% vs JAZZ 实测 −7.5% — **窗口/币池/口径差异待 reconcil**

**两份数字:**

| 来源 | 数字 | 窗口 | 币池 | 备注 |
|---|---:|---|---|---|
| C-5 (Minimax-C, c-path memory) | **−58.84% cum / SR -0.381 / MaxDD −84.03%** | 2023-12-27 → 2026-09-20 (999d) | 24 名(per c-path memory §关键 honest baseline) | inception 2023-12-27;2.74y |
| JAZZ(经 ALLOCATION_ARCHITECTURE_v0.2.md:73) | **−7.5%** | "2023-12 → 2026-09" | "24 名面板等权" | 同段 BTC +92% |

**两数差 51.34pp — 不能合并。** 可能差异原因(按可能性排序,待 JAZZ 指认):

1. **币池不同。** C-5 memory 列出 24 名(BTC/ETH/SOL/BNB/XRP/ADA/AVAX/DOGE/ARB/OP/NEAR/APT/UNI/AAVE/MKR/LINK/ONDO/DOT/INJ/CRV/LDO/ATOM/COMP/GRT);JAZZ 没说他的 24 名具体是谁。如果 JAZZ 的 24 名是「大币 + 头部公链」去掉 GRT/COMP/LDO/CRV 这些深跌的 DeFi,差距可以解释。**这是最可能的来源**。
2. **加权口径不同。** C-5 是等权(rebalance cadence 待确认 — 默认日频 mark 月末 rebalance?)。JAZZ 写了"等权",但 cadence 没写。
3. **价格来源 / 时区差异。** C-5 用 `ohlcv_daily.trade_date`(S-436 fix 后 = 覆盖的那一天);JAZZ 实测可能用 CG Pro last_updated(S-191/S-195 已知 CG 端点用错 4 个月 — JAZZ 是否在 S-195 fix 后重测?)。
4. **真实 mcap vs 静态 mcap bias。** 不太可能 — 两个都"等权",不影响。
5. **包含 / 不包含死亡币。** MKR 已迁 SKY(INJ ticker 也修了);C-5 用的 24 名如果含 MKR 而 MKR 这段窗口价格被 SKY 迁移事件污染,会显著拉低。

**JAZZ 必须拍:** 哪个口径是 v0.2 phase 1 nav_kernel 用的"标准 ① 基准"?

> **JAZZ 待决(本表不预设答案):**
> - (a) 用 JAZZ −7.5%(指定 24 名 + cadence,本表需复算 C-5 同样窗口作 reconciliation);
> - (b) 用 C-5 −58.84%(Minimax-C 已知实现,直接复用);
> - (c) 重新定义 v0.2 基准 = JAZZ 选标的 + nav_kernel 月末 rebalance + 最近 trade_date 收盘价 —— 这是中性最强的选项,与 ALLOCATION_ARCHITECTURE_v0.2 §3 P3「一套记账内核」一致。

---

## §D · 守卫 ≠ 记账 —— 概念分离

按 ALLOCATION_ARCHITECTURE_v0.2 §3 P3 + JAZZ 09-30 三处纠正:

| 概念 | 性质 | 例子 |
|---|---|---|
| **记账方法** | **只有一套**,所有策略共用 | v0.2 phase 1 要建的 `nav_kernel(target_weights, prices, cost_bps, lag=1) → daily NAV`(per ALLOCATION_ARCHITECTURE_v0.2 §3 L2)。**S-431 已证明 `beta_plus_momentum._simulate` 形状正确,可提出来作公用内核**。 |
| **守卫**(guards) | **判断数字能不能信**,不构成记账 | M-114 `lag_discipline_pass(retention≥0.5, sr≥0.05)` · regime_quorum 5-value(ok/thin/COLLAPSED/frozen/no_baseline)· M-145 sparse-sleeve guard(active_days≥60, hit_rate≥0.45, sr_on_active≥0)· M-149 gate-firing-rate · S-244 文本守卫 · M-114 lag-discipline CI test |

**这意味着:** 表中所有"自报"数字都**先过守卫**(原报告者已跑过 lag / sparse / regime quorum 守卫 —— 我们在表中标"自报"前假设原报告符合守卫,重算时 v0.2 nav_kernel 必须重新过同一组守卫),但**重算只换内核,不换守卫**。

**v0.2 阶段 1 必做的"一套记账内核":**
1. 提 `beta_plus_momentum._simulate` → `nav_kernel`(Seth lane — 已 ship 在 BETA_PLUS pipeline);
2. 所有"自报"策略在 v0.2 nav_kernel 上**重新算 SR / cum / MaxDD / OOS**;
3. 公用守卫 M-114 / regime_quorum / M-145 一并跑;
4. 输出按 ALLOCATION_ARCHITECTURE_v0.2 §3 评估表的格式:`n_days / excess_mean / ci_lo / ci_hi / p_pos / beta / rel_maxdd / turnover / n_variants_tried`。

**此工作不属于 T-037。** T-037 只到"清点 + 标风格"为止。

---

## §E · 待 JAZZ / Seth lane 拍板的事项

| # | 问题 | 谁拍 | 备注 |
|---|---|---|---|
| Q1 | 等权 24 名 −58.84% vs −7.5% 哪个是 v0.2 基准 | JAZZ | §C |
| Q2 | 风格桶细分到几档(JAZZ 列了 6 + RWA 主题,实际可细分:大币是否含 ETH/独立?DeFi 是否拆 DEX/Lending/LST?) | JAZZ | T-039 落库前定 |
| Q3 | meme / AI 标的篮子定义(DOGE 跨界怎么办?哪些 AI 币?) | JAZZ | T-039 落库前定 |
| Q4 | RWA 主题 vs 基础设施与代币化 是不是同一个桶 | JAZZ | S-266 / S-427 用法有重叠 |
| Q5 | 24 名 / 28-asset strict / 41-asset crypto + 17 ETFs 三个不同币池是不是都要保留 | JAZZ | T-038 BTC↔alt 切片需要重新定义 universe |
| Q6 | Style header 的 PIT 实现细节:用 CoinGecko categories / 自维护映射 / CoinMarketCap 历史 mcap 分位 | JAZZ + Seth | T-039 spec 待写 |
| Q7 | "Outter × ② β+ v1.1"(原 T-037 spec) 与"历史策略清点 + 风格列"(本文件)是不是同一件事 | JAZZ | 见 §F 备注 |
| Q8 | v0.2 nav_kernel 提公用的 PR 谁写 | Seth | ALLOCATION_ARCHITECTURE_v0.2 §3 L2 写明 Seth lane 提 `beta_plus_momentum._simulate` |

---

## §F · References

- `MEMORY.md` — 索引,本表数字均 cross-ref 到其指向的 memory file(略,不重复列)
- `docs/DECISIONS.md` — 09-23 HL 现货 / 09-26 长持仓基线 / 09-26 代币化主题 / 09-24 Strategy 3/4 复核
- `docs/HIGH_DIM_ONTOLOGY.md` §5b / §5b-bis / §5b-ter — RETURN HIERARCHY + ⓪ OVERRIDE + Millennium stop
- `docs/ALLOCATION_ARCHITECTURE_v0.2.md`(Seth, 2026-09-29)— v0.2 草案 + §3 状态表头(T-039)+ §3 L2 nav_kernel
- `docs/STRATEGY_PLAYBOOK.md` — Strategy 1 R77 / Strategy 2 R76 / Strategy 3 Pod / Strategy 4 Tilt / R82-R89 / R95 / R96
- `docs/TRADER_TOM_DOCTRINE.md` — 7 invariants + §3 IR + §5b expectancy > hit-rate
- `docs/BETA_PLUS_2026-09-26.md` — ②-MOM / ②-TOK 历史来源
- `MINIMAX_SYNC.md` §S-435 / §S-438 / §S-438b — T-038 接位 + T-037 三处纠正 + T-039 风格表头
- `tasks/T-037.json` — task card(acceptance 引自此)
- `tasks/BOARD.md` — 当前状态
- `lane-b/PROJECT_STATE.md` — lane-b 当前 ship 状态
- `/Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input/` — 原始 mining output JSON
  (C-5/C-12/C-16/C-17/...;**全读 lineage 不只第一击** per CLAUDE.md「Mining output — where the research IS」)

### ⚠️ 卡号/任务冲突 — 需要 JAZZ 仲裁

T-037 这个卡号**已被 lane-b 用过一次**(Outter × ② β+ v1.1 spec,2026-09-28,parent=T-036)。
本日 JAZZ §S-438 把它**复用**给了"历史策略清点 + 风格列"。

- 第一次 T-037 在 `MINIMAX_SYNC.md` 第 581-919 行(Spec + handoff + Day 3-6 + Outter v1.0 fixture rejected);
- 第二次 T-037 是本文件 + `tasks/T-037.json` 的「open / lane-b / 历史策略清点」。

**两个 T-037 是不同的工作**。建议(JAZZ 拍):
- 把第一次的"Outter × ② β+ v1.1"卡号改名 `T-037-Outter-β+-v1.1` 或新号 `T-040`+;
- 把第二次的"历史策略清点"留用 T-037(本文件)。

不仲裁前,本文件用"本 T-037"指代"历史策略清点"。

---

*Lane: B (Seth/Austin) · Status: in_progress · 验收:覆盖 A 表全部行 ✓ · 自报标记 ✓ · 无新算 ✓*
