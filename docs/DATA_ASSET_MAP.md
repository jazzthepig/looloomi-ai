# 数据资产地图 — 什么活着、什么是孤儿、什么接错了

*Seth, 2026-08-06 · Jazz: "看有什么一些是散乱的东西都接起来汇总"*
*全部为实测行数,非估计。40 张表 + 10 个视图逐个点过。*

> **一句话:数据不缺,缺的是接线。** 本次汇总发现的最大问题不是空表,
> 而是**同一个概念被拆在两张表里、中间有缺口、而所有消费者只读到了一半**。

---

## 0. 决策链 — 现在通了

```
market_state_vectors (582d)
        ↓  similar_market_states(day,k,min_shared)
   相似历史环境
        ↓  strategy_response  ×  market_state_cluster()
   谁在那类环境里活过(含 sample_grade='none' = 从未出现)
        ↓
      配置决策
```
价格只在最后一环(执行择时)出现。这是 `DECISION_PATH_SPEC` 要的顺序,
也是 S-92→S-99 之前**从未接通过**的那条链。

---

## 1. 核心资产(活的,有量,被使用)

| 表 | 行数 | 跨度 | 角色 |
|---|---|---|---|
| `ohlcv_daily` | **228,586** | 2015-07 → 2026-08 | 价格底座。**多源多行,必须读 `ohlcv_daily_canonical`** |
| `cis_scores` | **106,882** | 2025-05 → 2026-08 | 五柱质量分。436 天,76 symbols |
| `signal_outcomes` | 7,743 | 2025-05 → **2026-05-03** | 旧世代信号结果 |
| `conviction_verdicts_daily` | 1,216 | — | 每日 conviction 裁决 |
| `trending_log` | 1,635 | 2026-06-26 → | 注意力(41 天,太短) |
| `macro_briefs` | 687 | 2026-06-19 → | 宏观简报(48 天) |
| `market_state_vectors` | **582** | 2025-01 → 2026-08 | **环境向量(本轮新建)** |
| `cause_snapshots_daily` | 552 | — | 上游因快照 |
| `signal_track_record` | 491 | — | 前向记录 |
| `narrative_snapshots` | 396 | — | 叙事 |
| `trade_results` | 184 | 2026-06-29 → 2026-08-01 | 纸面成交(2 策略,薄) |
| `signal_journal` | 149 | **2026-05-25** → 2026-08-04 | **新世代信号(32 未解决)** |
| `asset_embeddings` | 72 | 单快照 | 资产向量(**无时间序列**) |
| `strategy_response` | 48 | — | **响应面(本轮新建)** |

## 2. 关键视图(读这些,不要读原表)

| 视图 | 为什么存在 |
|---|---|
| **`ohlcv_daily_canonical`** | 原表 48,582 对重复;成交量单位差 62,617×;同日收盘差 5%。**回测必须读这个** |
| **`ohlcv_venue_spread`** | 保留跨源价差作为特征(Jazz),带 `spread_kind` 标注它今天是口径差不是套利 |
| **`signal_outcomes_unified`** | **本轮新建 —— 见 §3,这是最大的那处断线** |
| `asset_edge_moments` | β 调整后边缘风险矩(I5) |
| `signal_beta_scorecard` | β 归因 |
| `cis_score_latest` / `_history_7d` | 服务路径便捷视图 |
| `regime_transitions` | 相位切换 |

## 3. ⚠️ 本次汇总发现的最大断线 — 响应面只读到一半历史

```
signal_outcomes   7,743 行   2025-05-03 → 2026-05-03   ~650/月 · 24-38 symbols
       ⋯ 3 周缺口(05-04 → 05-24)⋯
signal_journal      149 行   2026-05-25 → 2026-08-04    ~50/月 · 32 未解决
```

**outcome tracker 从未坏过 —— 是上游换了。** 一次管道迁移把同一个测量拆到两个 schema,
**每个消费者都静默地只拿到了旧世代**,所以 `strategy_response` 是在三个月前就截止的数据上算的,
**完全不含当前环境**。

**已修:`signal_outcomes_unified` 视图并列两个世代,`era` 列暴露接缝。**
缺口**被表示出来而不是抹平** —— 两个世代的采样密度差 13 倍(650/月 vs 50/月),
且新世代**没有 β 调整 alpha**。**盲目跨接缝取平均,得到的数字两个世代都不描述。**
重算后响应面窗口 2026-05-03 → **2026-07-06**。

## 4. 孤儿表(有 schema,零或近零数据 —— 需判定:接上或删除)

| 表 | 行数 | 判定建议 |
|---|---|---|
| `risk_meter_history` | **0** | **接上** —— risk_meter 有代码无落库,`DECISION_PATH` ⓪层缺它(M-WO-D2) |
| `asset_embeddings_history` | **0** | **接上** —— schema 就绪,回填脚本待 service_role(OPEN RISK #1 阻塞) |
| `decisions` / `entities` | 0 / 1 | **判定** —— Entity/Decision 本体层,架构核心但从未落数据 |
| `cause_outcomes` | 0 | **判定** —— 有 `cause_snapshots_daily` 552 行,结果侧却空 |
| `cis_backtest_results` | 0 | **判定** —— 回测结果从未入库,全在文件里 |
| `cis_regime_fitness` | 0 | **判定** |
| `signal_edge_map` | 19 | 稀疏,确认是否仍在用 |
| `*_paper_nav` × 4 | 15–24 | 四张 NAV 表各存一点,**建议合并成一张带 `book` 列** |

**`decisions`/`entities` 空这件事值得单独说:** `ARCHITECTURE.md` 说最深的对象是
**实体与决策**,不是资产。这两张表是那个本体的落点,而它们是空的 ——
**架构的核心主张在数据层没有任何体现。**

## 5. 已修的接线问题(本轮)

| 问题 | 修法 |
|---|---|
| 多源重复被消费者静默双计 | `ohlcv_daily_canonical`(去重)+ `ohlcv_venue_spread`(留价差)**成对** |
| 向量无来源标注 | `price_sources[]` / `spread_kinds` / `provenance_note` |
| 响应面只读旧世代 | `signal_outcomes_unified` |
| 环境无时间序列 | `market_state_vectors` 582 天 |
| 无"谁在此环境活过" | `strategy_response` + `market_state_cluster()` |

## 6. 下一步优先级(按"解锁什么"排,不按工作量)

1. **`risk_meter_history` 落库** — ⓪层进不了任何回测,这是四层架构里唯一完全没有数据的一层
2. **`asset_embeddings_history` 回填** — 卡在 service_role key(OPEN RISK #1)
3. **`signal_journal` 补齐未解决的 32 条** — 9 条已成熟,直接可解
4. **`decisions`/`entities` 定性** — 要么接上,要么从架构叙事里降级。**空表撑不起本体主张**
5. 四张 `*_paper_nav` 合并

---

**维护规则:** 本文档只记**实测**行数与跨度。任何"应该有 X 行"的陈述都不属于这里。
重新点数用 §1 的查询,不要凭记忆更新。
