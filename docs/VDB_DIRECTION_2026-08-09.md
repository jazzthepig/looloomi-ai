# 矢量数据库:它不是什么,它是什么

*Seth,2026-08-09。Jazz:「认真理解我们矢量数据库的价值和方向」。*
*本文的每条否定都有文献或实测支撑,每条肯定都说明为什么它不需要预测能力就成立。*

---

## 0. 结论先行

**VDB 的价值不在预测,在三件事:样本构造、反证检索、A2A 接口。**

把它当预测器用,证据不支持。把它当**统计功效的放大器**和**失忆的解药**用,
它是我们目前最被低估的资产 —— 而且它解决的正是我们每一次研究都死在上面的那个约束:样本。

---

## 1. 它不是什么(两条都有证据)

### 1.1 不是「找相似资产」的选股工具

**Liu, Tsyvinski & Wu (JF 2022)**:加密横截面收益由**恰好三个因子**解释
(market / size / momentum);他们构造了股票市场全部主流预测变量的加密对应物,
**十个能做出显著多空的特征,全部被三因子模型吸收**。

⇒ **一个 18 维资产向量,是在用 18 个带噪坐标张一个 3 维空间。**

实测吻合:两两余弦**中位数 0.846**,**29.9%** 的配对高于工具文档称为「近乎相同」的 0.95。
BTC 的五个最近邻全部 >0.98。**这个空间几乎是退化的,而这不是 bug,是维度冗余的必然结果。**

**推论(重要,且和我今天的判断相反):** 资产嵌入五个支柱全为零这件事,
**对产品的伤害比我上午说的小** —— 因为资产相似度本来就不该是 VDB 的主用途。
修它是对的(数据完整性),但它不在关键路径上。

### 1.2 不是「历史类比 → 预测明天」的预测器

analog / kNN 预测的实证:**下一根 K 线方向准确率 50.0–53.2%**,
文献自己的措辞是「与短周期 EMH 一致」。只有 4–12 周的长周期上出现过 60% 级别的方向命中,
且显著性有限。

⇒ **「找到最像今天的历史日子,然后照抄它明天的收益」这条路,证据不支持。**

---

## 2. 它是什么

### 2.1 样本构造 —— 把硬过滤变成软加权(这条最重要)

**我们每一次研究都死在样本上,而且死法完全一样:**

| 研究 | 有效样本 |
|---|---|
| 30 天非重叠 IC | **14** |
| 5 天非重叠 IC | 84 |
| 出圈事件(有行情的) | 88 / 245 |
| S-108 派发假说 | 20 |
| S-109 相位探测 | **13 episodes / 7 资产** |
| N_eff(75 资产 ρ̄=0.310) | **3.1** |

根因不是数据少,是**条件策略需要条件样本**:
「在状态 Y 下,X 发生后会怎样」—— 一旦按状态切,样本就只剩个位数。

**而 VDB 让「按状态切」不必是硬过滤。**
不是「只取 regime == TIGHTENING 的 10 天」,而是
**「全部 582 天,按与今天状态的相似度加权」** —— 核回归 / 局部加权。

**这不需要 VDB 有任何预测能力。** 它只需要距离度量是有意义的排序,
而排序恰好是嵌入唯一确定擅长的事。**它换来的是统计功效,不是 alpha。**

⇒ `market_state_vectors`(582 天、24 维)才是主角,
**不是 `asset_embeddings`。**

### 2.2 反证检索 —— 失忆的解药

`ARCHITECTURE.md`:**验证装置本身就是产品**。我们有 110+ 条带机制的台账。

把**策略**(不是资产)嵌入,问「这个想法有没有被否过、以什么机制否的」——
**这是纯检索问题,没有任何预测主张**,而检索正是嵌入确定有效的地方。

今天一天就有四次「仓库里同时存在已修正版和未修正版,而没有东西从一个指向另一个」
(Lesson #109)。**这个病的解药就是可检索的机制索引。**

`sample_grade='none'` = 从未出现过 —— MEMORY 已经把它记为一等信息。
**「我没见过这个」是嵌入能诚实给出的、最有价值的一句话。**

### 2.3 A2A 接口 —— 产品面,不是 alpha 面

`ARCHITECTURE.md`:在 A2A 市场里,稀缺资源是**可验证的前向记录**。

一个「策略 + 机制 + 结果」的向量库,是**可被别的 agent 查询的**。
这是产品表面,不是收益主张 —— 而且它不需要我们有 alpha 就能卖。

---

## 3. 方向:两件事该改

### 3.1 主角换人:`market_state_vectors` 而不是 `asset_embeddings`

实测:582 天、24 维、**平均只有 13.9 维被测量**、`regime_label` **0 个不同取值(全 NULL)**。

**一个用来做状态检索的表,它的状态标签是空的。** 这比资产向量的五个零严重得多,
因为它在关键路径上。**这应该是 VDB 方向上的第一个 P0。**

### 3.2 用途换向:从「相似资产」到「相似时刻的加权样本」

`similar_market_states()` 已经存在。缺的是把它**接进研究流程**:
每一个条件检验,用相似度加权而不是硬过滤,并且报告**有效样本量**
(Kish 的 `(Σw)²/Σw²`),这样「功效从哪来」是可审计的。

---

## 4. 与风格配置的关系(Jazz 的框架)

**Ehsani & Linnainmaa (JF 2022)**:动量**不是一个独立的风险因子 —— 它是给其它因子择时的机制**。
平均因子在亏损一年后月收益 6bps,盈利一年后 **51bps**;
且因子动量**集中在解释横截面更多的那些因子上**。

配合 LTW 的三因子:**加密的风格配置 = 用 market / size / momentum 自身的过去收益给它们择时**,
而不是找第四个因子。

**VDB 在这条链上的位置是「择时的条件」** —— 因子动量在什么状态下有效、在什么状态下失效,
是一个需要条件样本的问题,而条件样本正是 §2.1。

**这三者是一条线,不是三件事:**
LTW 给因子集合 → E&L 给择时机制 → VDB 给择时所需的条件样本。

---

## 5. 我今天错在哪(记下来,免得重犯)

1. 把资产嵌入的五个零当成 P0 —— 它是数据完整性问题,不在关键路径。
2. 更早的时候,直接用 VDB 做「找相似资产」的横截面工作 ——
   而 LTW 说那个空间只有 3 维,做多少维的嵌入都改变不了这一点。

**教训:先问「这个工具的能力边界是什么」,再问「它能做什么」。
嵌入确定擅长的是排序与检索,不确定擅长的是预测 —— 把用途放在确定的那一半。**

---

## Sources

- [Liu, Tsyvinski & Wu — Common Risk Factors in Cryptocurrency (JF 2022)](https://www.nber.org/system/files/working_papers/w25882/w25882.pdf)
- [Ehsani & Linnainmaa — Factor Momentum and the Momentum Factor (JF 2022)](https://www.nber.org/system/files/working_papers/w25551/w25551.pdf)
- [Moskowitz, Ooi & Pedersen — Time Series Momentum (JFE 2012)](https://www.aqr.com/Insights/Datasets/Time-Series-Momentum-Original-Paper-Data)
- [Moreira & Muir — Volatility-Managed Portfolios (JF 2017)](https://www.nber.org/system/files/working_papers/w22208/w22208.pdf)
- [Cederburg et al. — On the performance of volatility-managed portfolios (JFE 2020)](https://www.sciencedirect.com/science/article/abs/pii/S0304405X2030132X)
- [Lou, Polk & Skouras — A Tug of War (JFE 2019)](https://personal.lse.ac.uk/polk/research/TugOfWar.pdf)
- [Barber & Odean — All That Glitters (RFS 2008)](https://faculty.haas.berkeley.edu/odean/papers/Attention/All%20that%20Glitters.pdf)
- [Fast Exact Nearest-Neighbor Learning for High-Frequency Financial Time Series (arXiv 2026)](https://arxiv.org/html/2606.10219)
