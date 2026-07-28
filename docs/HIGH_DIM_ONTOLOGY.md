# High-Dimensional Ontology — 高维、量子、降维的核心思想
*The Jazz↔Seth core communications on the vector/field/quantum layer, consolidated 2026-07-27.
Companion to `ARCHITECTURE.md` (the soul) — this is its geometry. Do not dilute; extend by appending.*

## 0. 一句话
**市场的真实状态是高维的;我们的全部工作是一连串"保结构的降维",而 VDB 是这条链的基底。**
每一次降维丢什么、保什么,决定我们是看见因、还是只看见反射。

## 1. The kernel, stated geometrically(内核的几何表述)

- ARCHITECTURE 的内核:最深的对象不是 Asset,是 **Entity/Decision** —— 影响力作为**向量场**
  传播成 quality 与 price。CIS 与动量是波前**经过之后**的反射。**Edge = lag(时滞就是优势)。**
- 几何化:embedding 相似度图 = **扩散场/传播介质**。相似 = 传播意义上的"近"。一个决策在场上
  注入信号,沿边扩散 —— `propagation.py` 的 `p=(1−α)s+αWp` 就是这个波前的线性算子。
- **beta+ 是时间向量**:站在波前上游。判据(S-81 定义):`entanglement_delta = p − s` —— 场
  (邻域)已动而节点自身反射未动 ⇒ 节点在波前上游 ⇒ beta+ 候选。

## 2. Be water(大象无形的算子形式)

- 没有冻结的因子。场算子 **W 每个周期随 embedding 重塑** —— 策略是"当前 regime 下对
  价格发现的追踪",不是固定公式(ARCHITECTURE §大象无形)。
- Regime 不是标签,是**场的相**:同一算子在不同相里给出不同的传播结构。R20 的教训:相变
  不可 profitable 地择时 —— regime 信息只进 sizing,不做 alpha 轮动。
- 稳定性溢价的真解读(S-76/R63b):ΔS/ΔO 大 = 场刚经历大重定价 = 高波相 = edge 退化。
  这是"相"的读数,不是采样延迟问题。

## 3. Be quantum(量子表述 —— 是严格类比,不是玄学)

- **叠加态**:资产的状态不是一个标量分,是**分布** —— I5 规定编码 mean/vol/p10(左尾)。
  R63 证明高 S 均值不变而尾部加深:只看均值的 schema 恰好瞎在亏钱的地方。v5 的
  `blended_for_display` 明令禁止用于排序 —— 因为它把两个正交可观测量塌缩成一个数。
- **非局域/纠缠**:节点的完整状态依赖**整个场**,不只自身坐标。`entanglement_delta` 度量
  "场对节点的隐含"超出其自身反射的部分。
- **测量与塌缩**:CIS 快照是一次**测量** —— 它把连续演化的场塌缩成一个读数,且带 lag。
  S-76 的实证:S/O 与价格同 bar 塌缩(coincident),所以**测量结果(level)不携带波前信息**。
- **S-81 的核心定理(实证,勿丢)**:**扩散"反射"(level)被证伪**(IC −0.16 —— 只是反推
  低分);**必须扩散"因"(change/flow/decision)**。正确形态:邻域的 Δpillar / 资金流(D1)/
  注意力扩散(D4)/ holder-Δ 是否领先节点自身的前向变化。这是 frontier 的可证伪形式,
  等真·多周期 CIS 数据(data_align)开测。
- **量子计算应用(前向钩子,保持线性以便移植)**:
  - 场扩散 `p=(1−α)s+αWp` 是**线性算子** = 经典 PPR,天然对应 **quantum walk**;保持算子
    线性,未来量子版是直接替换,不是重写。
  - 组合/sleeve 选择(coverage_gaps 填洞 + redundancy 去重 + 容量约束)是 **QUBO 结构**,
    QAOA/量子退火的标准候选。
  - 高维 embedding 的 **amplitude encoding**:27+ 维态可编码为 log₂(n) qubits —— VDB 里的
    向量就是未来量子态制备的经典描述。
  - 诚实边界:今天全部是 **quantum-inspired classical**;不声称量子优势;所有主张仍过
    反冒充 gauntlet(事件计数、OOS、per-cycle)。

## 4. 高维→低维:压缩级联(每一层写明"保什么")

```
市场微观态 (~∞维)
  → 27维 asset embedding v2      保: pillar levels+Δ+stability + 风险矩 (edge_vol/p10)
  → pgvector 相似场 (HNSW)       保: 传播邻接结构 (谁和谁"近")
  → CIS v5 双分数                保: 收益可观测量(F锚/M/A) ⊥ 风险可观测量(O主导+稳定性)
  → sizing (S-78语法: regime×vol) 保: 相位条件化的仓位语法
  → 1个配置决策                   保: 可审计的证据链 (base_rate→OOS→事件计数→60d paper)
```
**每次投影的四条守恒律(违反任何一条 = 把亏钱的维度平均掉了):**
I1 未测=NaN 永不为0 · I3 β分离不内嵌 · I5 分布不点估计 · R63b 三种因子"类"不做单加权和。
**降维的存储法则:dense+many → pgvector HNSW;sparse+few → jsonb + NaN-aware 共享维余弦。**
(稀疏向量做 0 补齐再算稠密余弦是**错误度量** —— 策略向量永远走 Python 共享维路径。)

## 5. VDB 做多(Jazz 2026-07-27:"尽量做多" —— 扩张路线图)

VDB 不是缓存,是**本体论的几何基底** —— 内核六对象全部向量化、全部可查询、跨空间连边:

| 空间 | 维度/形态 | 状态 | 备注 |
|---|---|---|---|
| Asset (CIS v2) | 27d, dense核+NaN尾 | ✅ live (pgvector) | `asset_embeddings` + kNN RPC |
| Strategy | 30d 稀疏 | 🔨 M-WO-3 | 持久 jsonb + Python 余弦, **不进 ANN** |
| Regime 指纹 | 12d | 📋 已算未入库 | `generate_regime_embedding` → 入 pgvector, 历史相位检索 |
| Entity/Decision | 待定义 | 🎯 frontier | 内核的缺失层; 从 holder/flow/治理事件起步 |
| Text/News (RAG) | 384-1536d | 📋 规划 | 独立表; 叙事→资产 连边 |
| 时序窗口 | shapelet/窗口向量 | 📋 规划 | "当前60天像历史哪段" = 相位检索 |
| Outcome | 结果向量 | 📋 规划 | 信号→30d结果分布, §P1 的几何形式 |

跨空间边 = 内核边(Entity→Decision→Asset→Quality→Outcome)。终态:**任何 operator(人/agent)
对任何对象问"像什么/谁领先/什么没覆盖",都是一次向量查询。** 这就是 OS 的 kernel 落成几何。

## 6. 反冒充边界(这一层的纪律)

高维语言容易变成玄学。此文档的每个可操作主张都已经或必须过 loop:S-76/S-81 是已跑的实证
(含证伪);§3 的 frontier 形式有明确数据门槛;量子钩子只约束**算子保持线性**,不改变任何
当下决策。**凡不能被外部 agent 验证的表述,不得出现在投资者面前。**
