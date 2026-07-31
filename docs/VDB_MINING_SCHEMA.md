# VDB 表头重设计 — 让策略成为可持续挖掘的对象
*Seth, 2026-07-27 · Jazz: "价格是高维信号的映射…让你做 vdb 表头,就是要持续挖掘并提升策略,
现在都是后视镜开 120 然后撞车,我在其他平台都可以做,我根本不用自己开发"*

## 0. 病灶:现有向量全是"后视镜"
现 30 维策略向量的每一维都是**历史标量总结**:
`regime_calm_vol = "Sharpe conditional on calm vol"` · `sharpe_5bps` · `realized_alpha` · `decay_slope`…
**它回答"这个策略曾经是什么",不回答"什么条件下它会活"。** 用这种向量做决策必然退化成后视镜 ——
**这也是为什么我每次都滑回价格代理:向量里没有任何可前瞻的东西。**

**关键认知(Jazz):价格是高维信号的映射。** 所以正确方向不是"从价格出发",而是
**先刻画高维环境,再问"在这种环境里,谁活过"** —— 价格只是环境向量的一个投影,不是输入。

## 1. 新架构:三张表,一个查询范式
```
① market_state_vectors   每日环境向量(高维,不含策略信息)
② strategy_response      策略 × 环境簇 的响应面(不是标量 Sharpe)
③ 查询范式:今日环境 → kNN 找历史相似环境 → 那些环境里谁活 → 前瞻配置
```
**这是"后视镜"与"导航"的分界:** 后视镜说"A 策略过去 Sharpe 0.8";
导航说"**今天的环境最像 2019-Q2 与 2023-Q4,在那些环境里,坐标在此区域的策略跑赢,而 A 恰在其中/不在**"。

## 2. ① `market_state_vectors` — 环境向量(核心资产,今天就该建)
**每日一条,只描述市场状态,不含任何策略信息。** 这是我们全部智能资产的汇流点。

```sql
market_state_vectors(
  d date primary key,
  vec vector(24),          -- 下表 24 维,HNSW 索引
  vec_full jsonb,          -- 含 NaN 的完整版(I1)
  regime_label text,       -- 事后标注,仅用于人读,不参与检索
  source_completeness real -- 有多少维是真实测量的(可信度)
)
```
| 块 | 维度 | 来源 | 为什么它是"因"而非"果" |
|---|---|---|---|
| **横截面质量** | cis_mean, cis_disp, cis_skew, pct_grade_A | cis_scores 五维 | 池子整体质量与分化度 |
| **风险偏好** | alt_btc_spread, breadth_200ma, disp_return, corr_mean | 面板横截面 | **边际资金愿不愿承担额外风险** |
| **流动性** | stable_supply_chg, volume_trend, adv_concentration | 链上+成交 | 边际买方的燃料 |
| **杠杆/情绪** | funding_mean, funding_disp, fng, oi_mcap | 衍生品 | 拥挤度与脆弱性 |
| **波动结构** | vol_mkt, vol_of_vol, downside_ratio | 价格(**仅此一块用价格**) | 环境的二阶矩 |
| **趋势相位** | trend_strength, trend_age_days | 价格 | 相位位置,不是方向预测 |
| **CIS 动态** | d_cis_mean, stability_OS | pillar Δ | R63b 的稳定性溢价 |

**⚠️ 价格只占 24 维中的 5 维,且只用于二阶矩与相位 —— 不用于方向判断。**
这是对"价格是高维信号的映射"的直接实现:**我们重建高维,不消费投影。**

## 3. ② `strategy_response` — 响应面(不是标量总结)
```sql
strategy_response(
  strategy_id text, state_cluster int,     -- 环境簇(由①的 kNN/kmeans 得到)
  n_days int, ret_mean real, ret_vol real, ret_p10 real,  -- 分布,不是单一 Sharpe(I5)
  hit_rate real, max_dd real, sample_grade text,          -- sample_grade: 充分/稀疏/无
  primary key (strategy_id, state_cluster)
)
```
**关键差别:一个策略不再有"一个 Sharpe",而有"在每类环境下的收益分布"。**
`sample_grade='无'` 是**一等公民**:它诚实地说"这个策略从未在这种环境里活过"——
**这正是我们最该知道的事,而现有 schema 把它藏成了 NaN 或平均掉了。**

## 4. ③ 查询范式 — 这才是 VDB 的意义
```sql
-- 今天的环境,历史上最像哪 20 天?
select d, 1-(vec <=> (select vec from market_state_vectors where d=$today)) sim
from market_state_vectors where d < $today order by vec <=> (...) limit 20;

-- 在那些相似环境里,哪些策略活过?(前瞻配置的依据)
select sr.strategy_id, avg(sr.ret_mean), avg(sr.ret_p10), sum(sr.n_days)
from strategy_response sr join (上面的相似日→簇) using (state_cluster)
group by 1 having sum(n_days) >= 30 order by 2 desc;
```
**决策链变成:环境向量(高维)→ 相似历史 → 谁活过 → 配置 → 价格仅用于执行择时。**
与 `DECISION_PATH_SPEC` 的四层顺序完全一致,且**现在有了可查询的实现**。

## 5. 持续挖掘(Jazz 的"持续做挖掘并提升策略")
这套 schema 让下面三件事变成**日常查询**,而不是每次重写一个回测:
1. **策略分类**:对 `strategy_response` 做聚类 → 自动发现"防御型/进攻型/横盘型"族群,不靠人贴标签。
2. **覆盖缺口**:哪些 `state_cluster` 下所有策略的 `sample_grade='无'` ⇒ **我们对这类环境完全没有武器**
   —— 这是研究议程的自动生成器(取代拍脑袋选题)。
3. **策略提升**:某策略在簇 A 活、簇 B 死 ⇒ 直接给出"加一个 A/B 判别闸门"的具体改造方向,
   **而不是整体重训**。这就是"提升策略"的可操作形式。

## 6. 与现有资产的关系(不推倒重来)
- 现 30 维 `strategy_records` **保留**,作为策略的"身份/契约"(容量、止损、晋升阶段)。
- **新增的是环境侧与响应面** —— 补上缺失的那一半。身份 × 环境 = 决策。
- `asset_embeddings` 继续管资产相似度;**`market_state_vectors` 管环境相似度** —— 两者正交,别混用。

## 7. 立即执行
| # | 事项 | 归属 | 阻塞 |
|---|---|---|---|
| 1 | `market_state_vectors` 建表 + HNSW | Seth | 无,今天做 |
| 2 | **历史回算**(cis_scores 2025-05起 + 面板 2018起,能算多少算多少,缺失记 NaN) | Minimax | 无 |
| 3 | `strategy_response` 建表 + 从现有 sleeve 回填 | Minimax | 依赖 1、2 |
| 4 | 每日写入(与 CIS 推送同批) | Minimax | 依赖 1 |
| 5 | 三个挖掘查询封装成 API/脚本 | Seth | 依赖 3 |
**先做 1+2 就能立刻回答一个我们现在答不出的问题:"2025 年 2 月的环境,历史上像什么?当时什么活?"**
