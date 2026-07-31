# 决策路径规格 — 智能必须流进决策,否则系统等于失效
*Seth, 2026-07-27 · Jazz: "如果每次都是走 dummy 路径,那我们设的系统不就等于失效了?
这跟做个 bot 做海龟策略有什么差别?"*

## 0. 病灶诊断(用代码证据,不是感觉)
扫描全部策略模块的实际依赖:

| 模块 | CIS | VDB | RiskMeter |
|---|---|---|---|
| R73–R81 等研究模块 | ✅ | — | — |
| r63_fusion | ✅ | ✅ | — |
| **`m_wo_a_beta_capture.py`(①层基座)** | ❌ | ❌ | ❌ |
| **`m_wo_q_o1_stablecoin_gate.py`(⓪层闸门)** | ❌ | ❌ | ❌ |
| **Seth 的 beta_core / S-83~S-91 全部实验** | ❌ | ❌ | ❌ |

**结论:研究 lane 在用 CIS,产品 lane 是纯价格。我们花一年建的入池标准、五维评分、向量库、
risk meter,没有一条流进最终的仓位决策。** 这不是"忘了调用" —— 是**架构上没有任何东西强制它被调用**,
所以每个人(包括我)都会滑向最省事的价格代理。**系统不是失效,是从未被接上。**

## 1. 注意力顺序错了(Jazz 的核心批评)
我一直按这个顺序做决策:
```
❌ 价格趋势(200MA) → 情绪(F&G) → 波动率 → [CIS/VDB/RiskMeter 从未进入]
```
正确顺序必须是**从高维到低维、从因到果**:
```
✅ ① 风格/相位判断     ← VDB 聚类 + regime 指纹 + RiskMeter(边际风险偏好)
   ② 入池筛选         ← CIS 质量分 + 流动性/容量标准(谁有资格被持有)
   ③ 权重分配         ← CIS 倾斜 + 风险预算(持有多少)
   ④ 执行择时         ← 价格/波动率(什么时候动手)  ← 价格只配站在最后
```
**价格是最下游的反射(ARCHITECTURE 内核),我却让它当了第一决策者。** 高维信息被低维代理 override,
这就是"低维困境"的准确定义。

## 2. 强制机制(不靠记性,靠 CI)
每个策略/回测模块必须声明它的决策输入,缺失即 CI 红灯:
```python
DECISION_INPUTS = {
    "regime":    "vdb_cluster" | "regime_fingerprint" | "risk_meter" | "price_proxy(需说明理由)",
    "universe":  "cis_quality"  | "liquidity_only(需说明理由)",
    "weights":   "cis_tilt"     | "equal(需说明理由)",
    "timing":    "price/vol",
}
```
- **默认路径必须是智能路径**;用 `price_proxy` / `equal` 必须在 `justification` 字段写明理由,
  且该理由会出现在 ledger 条目里 —— **让走捷径变得可见且尴尬**。
- CI 检查:`tests/test_decision_path.py` 断言每个策略模块存在 `DECISION_INPUTS`,
  且 SHIP 级别的记录不得在 `regime`/`universe` 两项上使用 fallback。

## 3. 但先解决数据缺口(否则强制也没用)
**强制调用一个空表毫无意义。当前两个致命缺口:**

| 资产 | 现状 | 缺什么 | 后果 |
|---|---|---|---|
| **pgvector `asset_embeddings`** | **72 行,单日快照(2026-07-24)** | **没有时间序列** | **风格聚类/轮动无法回测** |
| **`cis_scores` pillar 历史** | 66,685 行,**仅 2025-05 起** | 缺 2021 牛市 / 2022 熊市 | 只能在 8 个月分化样本上验证 |
| RiskMeter | 有代码,无历史输出 | 每日快照未落库 | 无法回测 |

**⇒ 在补齐之前,任何"用 CIS/VDB 做风格轮动"的结论都是在 8 个月样本上过拟合。**

## 4. 立即执行(顺序不可颠倒)
1. **[Minimax P0] 历史 embedding 序列**:用 cis_scores 的 pillar 历史,**每日回算一条 27 维向量**
   写入 `asset_embeddings_history(d, symbol, vec, vec_full)` —— 有了它风格聚类才能回测。
2. **[Minimax P0] RiskMeter 每日落库**:`risk_meter_history(d, band, score, components jsonb)`。
3. **[Minimax P1] CIS pillar 历史延长**:目标覆盖 2021 牛市 + 2022 熊市(可用 11yr 代理重建,
   但必须标注 proxy vs real,见 S-80 教训)。
4. **[Seth] 决策路径 CI**:`DECISION_INPUTS` 契约 + `tests/test_decision_path.py`。
5. **[双方] 现有产品模块整改**:`m_wo_a_beta_capture` / `m_wo_q_o1_stablecoin_gate` / `beta_core`
   必须接入 CIS 入池 + RiskMeter 相位,或显式声明 fallback 理由。

## 5. 判断标准(怎么知道修好了)
**在①②③④四层里,前三层至少有两层使用智能资产,且 ledger 条目能显示具体用了哪个。**
如果一个策略只用价格,它必须能回答:"为什么我们的 CIS/VDB/RiskMeter 对这个决策没有帮助?" ——
**答不上来就不许上生产。** 这正是 Jazz 的问题:**否则我们和一个跑海龟策略的 bot 没有区别。**
