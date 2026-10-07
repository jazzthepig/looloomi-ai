# 后台循环清单 —— 按探测器分层(2026-10-07)

*Seth。数据截至 10-07 08:55 UTC:`loop_attempt` 近 7 天、各表最新一行、`src/api/main.py` 的调度。只读,未改任何东西。*

## 怎么读这份清单

Jazz 10-07:复杂的循环、VDB、各种抓取是为了**从噪音里筛出少数有效数据**——像在南极冰层里收上十亿条记录、最后只留下几条。
所以这里**不按「多 / 少」评**。传感层宁宽;对每一路只问三件事:

1. **活着吗**:有调度、有判活、有真实数据(规则 5b)
2. **有本底吗**:知道这一路在没有信号时长什么样,才分得出那几条真事件
3. **执行路径是否一次只写一遍**:同一件事不该每个想法各写一套循环和表

决策端才极简:超配 / 低配、贵 / 不贵、推力高 / 低。中间是筛选:**传感 → 特征 → 评估(含本底)→ 候选证据 → 一张小权重表**。

**总数**:调度中的循环 55 个;其中 33 个每轮写 `loop_attempt`,**22 个不写**(健康只能从它写的表推断);`src/` 写 68 张表。
「状态」列:`ok/err/其他` = 近 7 天 `loop_attempt` 次数;无记录的写「表最新」。

## 1 传感层(13)—— 宽,多源,带噪

| 循环 | 采什么 | 状态 | 建议 |
|---|---|---|---|
| `_cg_panel_loop` | CG Pro 日线面板 → `ohlcv_daily`(coingecko_pro_ohlc) | 53/0/6 | 保留 |
| `_deep_panel_loop` | 262 币研究面板 → `ohlcv_daily`(binance_hist,到 10-07) | 25/0/0 | 保留 |
| `_ohlcv_collector_loop` | CIS 宇宙 + TradFi(eodhd,到 10-06) | 无记录 | 补判活;与 cg_panel 写同表,核对分工 |
| `_hyperliquid_loop` | 资金费 / 未平仓 / mark | 32/0/0 | 保留(它的 HL 日线 08-23 起停写,见 §8) |
| `_channels_loop` | 稳定币 / 代币化 / RWA 分类市值 | 33/0/0 | 保留 |
| `_style_header_loop` | 风格成员 / 市值 / 风格指数 | 41/**15**/0 | 保留;15 次都是 10-04 读超时,补重试 |
| `_holder_refresh_loop` | 持币集中度(CG 链上) | 14/1/0 | 保留 |
| `_treasury_decisions_loop` | 企业 / 主权持币决策流 | 26/0/0 | 保留 |
| `_trending_loop` | CG 热搜(注意力扩散) | 无记录;表 08:55 | 补判活 |
| `_positioning_loop` | 资金费 / OI 的杠杆因 | 无记录;表 10-07 | 补判活 |
| `_forward_supply_loop` | 解锁 / 供给因 | 无记录;表 10-07 | 补判活 |
| `_conviction_loop` | 叙事事件 + 观察名单 | 无记录;表 03:26 | 补判活 |
| `_price_agreement_loop` | 跨源价格一致性(传感器自检) | 23/0/0 | 保留 |

(Mac T1 的 CIS 推送不在这 55 个里,也是传感层。)

## 2 特征 / 状态层(10)—— 把噪声压成特征

| 循环 | 产出 | 状态 | 建议 |
|---|---|---|---|
| `_state_daily_loop` | 17 个状态特征 `state_daily` | 12/0/0 | 保留 —— 决策读这份 |
| `_market_state_loop` | 市场状态向量(VDB 相似度) | 26/0/0 | 保留;与 state_daily 的关系写清(§7) |
| `_regime_daily_loop` | 5b 微观相位指纹 | 27/4/0 | 保留(4 次是 10-04 写超时) |
| `_embedding_rebuild_loop` | 资产向量(VDB 几何基底) | 无记录;表 08:47 | 补判活 |
| `_interpret_loop` | 历史类比 → 各风格后续 | 53/0/0 | 保留 |
| `_t2_precompute_loop` | CIS T2 宇宙离线计算 | 无记录 | 补判活 |
| `_hourly_t2_snapshot_loop` | CIS T2 每小时快照 | 无记录;cis_scores 08:51 | 补判活 |
| `_daily_snapshot_loop` | 全宇宙 CIS 日快照 | 无记录 | 补判活 |
| `_factory_recalibrate_loop` | 信号工厂每周重标定 | 无记录;表 10-07 | 补判活 |
| `_regime_fitness_loop` | 支柱 × regime 相关 | 无记录;**`cis_regime_fitness` 0 行** | **先判成因**(无调度 / 写不进 / 正确拒绝) |

## 3 评估层(7)—— 量出来,还要扣本底

| 循环 | 产出 | 状态 | 建议 |
|---|---|---|---|
| `_rr_matrix_loop` | 每本账 × 状态格子 vs ① | 9/0/0 | 保留,**加本底带**(下面) |
| `_track_record_loop` | 信号战绩 | 27/0/0 | 保留 |
| `_outcome_tracker_loop` | 信号结果回填 | 28/0/0 | 保留 |
| `_prediction_resolver_loop` | 预测结算 | 无记录;表 03:25 | 补判活 |
| `_forward_return_backfill_loop` | 纸面交易 7 日实现收益 | 无记录 | 补判活 |
| `_forward_record_loop` | 前向记录时钟 / 停摆告警 | 24/1/0 | 保留 |
| `_band_log_loop` | regime 带日志 | 无记录;表 08:55 | 补判活 |

**缺口:本底(零信号)校准没有任何循环在算。** 评估层会量「这本账在这个格子里赚了多少」,但不知道「什么都不会的账本在同一个格子里会随机赚出多少」。
M-208 就栽在这里:一条「SR > 0.5」的判据,纯噪声每格也有 35–40% 通过。
建议:`rr_matrix` 每格并排给出**打乱日期后的分布带**(块自助,1,000 次),格子结论 = 实测值落在本底带的哪个分位。这是「多算」的那一部分,应该加,不是减。

## 4 候选证据:前向纸面账本(17 + 纸面交易引擎 4)

每本账都是一路前向记录 —— 这是产品本身,一本都不该因为「复杂」而丢。问题在执行路径:**每本账一个专门的循环、一张专门的表**。

| 层 | 循环 | 状态 |
|---|---|---|
| ① | `_core_cap_loop` | 91/0/15 |
| ② | `_cis_tilt_loop`(24 次「其他」= 收盘数据未定时正确拒绝)· `_beta_plus_loop` · `_tokenization_tilt_loop` · `_beta_core_loop`(等权 + 波动率目标,原 ①) | 都在写 |
| ③ | —— **没有一本在跑**(m88 那类要按 0.7–1.3× 重做) | 缺口 |
| HL | `_hl_book_loop`(134 次「其他」= 每小时看一眼、没有新日线) | 在写 |
| ④ | `_causal_paper_loop` · `_scalable_book_loop` · `_combined_book_loop` · `_dingge_paper_loop` · `_fusion_paper_loop` · `_pod_aggregator_loop` · `_factor_tilt_loop` · `_r76_paper_loop`(无记录,状态存文件) | 每天都有一行(09-30 → 10-07 连续);`loop_attempt` 只从 10-05 起记,所以 7 天只有 3 次 |
| ④ 附属 | `_fusion_paper_tracking_loop`(在写)· `_fusion_paper_regime_track_loop`(**`fusion_paper_regime_track` 0 行**) | 后者先判成因 |
| 已退役 | `_two_layer_paper_loop` —— registry 标「按设计退役」,仍每天记一行零仓位 | 待你定:停,还是留作「零仓位也是一次观测」 |
| 纸面交易引擎 | `_paper_rebalance_loop`(6 小时)· `_sl_tp_loop`(5 分钟)· `_cis_flip_loop`(5 分钟)· `_age_sweep_loop`(每天)→ `trade_results` | 最新一行 10-01;**当前 0 笔持仓**,三个退出循环在正确地空转;再平衡 6 天没开仓 —— 核对是规划器判断还是停了 |

**建议:一个通用账本运行器**。账本写成数据(一份 JSON:宇宙、权重规则、调仓频率、基准),一个循环按日跑所有账本,写一张表 `(book_id, d, weights, nav)`;
现有 14 张账本表保留历史只读,`rr_matrix` / proof 面改读新表。账本数量不变(还可以更多),执行路径从 14 套变 1 套。
有状态的(fusion 生命周期、追踪)作为运行器的钩子保留。

## 5 决策层(1)—— 极简

| 循环 | 状态 | 建议 |
|---|---|---|
| `_allocation_loop` | 35/28/0 —— 28 次错误全在 10-06 03:02 之前(S-489 那 13 小时);近 24 小时 11/0 | 保留。它就是「一张小权重表」的落点:读候选证据 + 状态,出 ① / ② / ③ 的权重 |

## 6 产品 / 叙述(2)

| 循环 | 状态 | 建议 |
|---|---|---|
| `_ai_briefing_loop` | 无记录(写 Redis) | 补判活 |
| `_metering_flush_loop` | 无记录;**`api_usage` 0 行** | 判成因:是没人用付费 API,还是计数没落库 |

## 7 运维(1)

`_heartbeat_loop` —— 保留。

## 8 按优先级的问题清单

1. **22 个循环没有逐轮记录**(上表「无记录」)。每个加一行 `_record_loop_attempt(...)`,判活才完整 —— 机械活,lane 可做。
2. **3 张 0 行的表,有调度中的写入端**:`cis_regime_fitness` / `fusion_paper_regime_track` / `api_usage`。按 5b 先判成因,再决定修或停。
3. **评估层加本底带**(§3)。这是 M-208 的教训变成基础设施。
4. **通用账本运行器**(§4)。账本不减,执行路径 14 → 1。
5. **「现在是什么天气」有四份**:`state_daily`(17 特征)/ `market_state_vectors`(VDB)/ `regime_daily`(5b 指纹)/ `daily_macro_regime`。四个角度可以并存,但要在 SPINE 写清哪份是决策读的、各自量的是什么 —— 规则 3b:两份看起来像同一个量的序列最容易被误用。
6. **`ohlcv_daily` 里停更的旧源**:`coingecko`(09-17 止)、`yfinance`(06-18)、`hyperliquid`(08-23)、`binance_hist_ffill`(08-08)。在数据覆盖接口与 SPINE 标「冻结」,防止研究读到半截序列。
7. **③ 推力没有前向账本**(§4)—— 优先级在 ④ 之前,m88 那类按 0.7–1.3× 重做后接入。
8. **待你定**:`_two_layer_paper_loop` 停或留。

**不建议动的**:所有传感层与特征层循环(除了补判活)。它们是筛选的原料,宽是对的。
