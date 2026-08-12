# 配置者的文献图谱 —— 以及为什么我们的架构本来就是对的

*Seth,2026-08-09。Jazz:「你太容易忘掉我们这个项目和架构的优势,又回到平庸交易者的模式」。*
*本文是纠正:先读配置者的文献,而不是交易员的文献。*

---

## 0. 一句话

**四篇独立的顶刊文献,从四个方向,收敛到同一句话:edge 在配置,不在选择。**
**而这句话就是 `CLAUDE.md` 的收益层级(①→②→③→④)已经写下的东西。**

我今天一整天在读交易员的文献(因子、动量、BAB),那是**选择**的文献。
我们是**配置者**。我找错了书架。

---

## 1. 四篇,以及它们的交点

### 1.1 Berk & Green (JPE 2004) —— 按历史业绩选人,理论上得零

理性资金流 + 主动管理的规模递减 ⇒ 均衡中**净 alpha 为零**。
**「过去业绩既不能预测未来收益,也不能推断平均技能水平。」**

**⇒ 对 FoF 是存在性打击:如果我们的选策略逻辑是「谁历史 alpha 高选谁」,这篇说我们得零。**

### 1.2 Berk & van Binsbergen (JFE 2015) —— 但换个度量,技能持续十年

技能存在,只是**度量错了**。用**从市场中抽取的美元金额**(毛 alpha × AUM):
- 平均基金每年约 **$3.2M**
- **横截面差异持续长达十年**,过去的价值增量**能**预测未来的价值增量
- 论证:「在 $10B 上做 1% 的人,比在 $1M 上做 10% 的人技能更高」

**⇒ 百分比 alpha 不持续,美元价值增量持续。**
**⇒ 我们的 `signal_track_record`、SHIP 门槛、对外材料,记的全是百分比 ——
我们一直在度量那个被证明不持续的量。**

### 1.3 McLean & Pontiff (JF 2016) —— 折扣率

发表后的横截面预测变量:**样本外低 26%,发表后低 58%**。
26% 是统计偏差(过拟合),额外 32% 是知情资金的价格压力。

**⇒ 可直接写进门槛的两个乘数:**
- **自己找到的:× 0.74**(样本外偏差)
- **文献里拿的:× 0.42**(偏差 + 拥挤)

### 1.4 FoF 文献 —— 价值来自配置与尽调,不来自选人

双重收费(叠加约 1% / 10%,合计常超 3% + 28% 的利润)是极高的门槛。
证据分歧,但**支持方的结论很具体**:
> FoF 增加的价值**主要来自战略资产配置**,并且这个价值超过双重收费的成本。
> 以及:FoF 为不具备能力的投资者**降低搜索与监督成本**。

**⇒ FoF 的两个合法价值源:①配置 ②尽调规模化。都不是选人。**

---

## 2. 交点

| 文献 | 说「不行」的 | 说「行」的 |
|---|---|---|
| Berk & Green | 按 % 业绩选人 | — |
| Berk & van Binsbergen | % alpha | **美元价值增量** |
| McLean & Pontiff | 未折扣的发现 | 打折后仍存活的 |
| FoF 文献 | 选人 | **配置 + 尽调** |

**四条否定都指向「选择」,两条肯定都指向「配置」。**

**而 `CLAUDE.md` 的收益层级早就是这个:**
① 吃 beta → ② 持仓内超配(tilt) → ③ 暴露择时 → ④ 纯 alpha(最难最后)。
**①②③ 全部是配置,④ 是选择,而且被排在最后。**

**我们的架构本来就是对的。是我一天之内三次退回去做 ④。**

---

## 3. 一个我认为原创、且是我们独有的推论

### A2A 市场让 Berk–Green 的机制加速,而这**提高**装置的价值、**降低** alpha 的价值

Berk–Green 的 alpha 消失机制,速度取决于**资金重新配置的速度**。
`ARCHITECTURE.md` 说我们为 human LP 和 AI agent **同等**设计。

**在 agent 配置资金的市场里,资金流的速度是数量级上升的。** 于是:

- **任何给定 alpha 的半衰期变短** ⇒ alpha 作为资产,估值下降
- **「多快能验证一个主张」的价值上升** ⇒ 验证装置作为资产,估值上升

**⇒ 在 A2A 世界里,装置比 alpha 值钱 —— 这不是口号,是 Berk–Green 在流速上升下的直接推论。**

`ARCHITECTURE.md` 早就写了「验证装置本身就是产品」。**现在它有机制了,而不只是信念。**

而 FoF 文献里那条「降低搜索与监督成本」——**在 A2A 市场里,搜索与监督是机器问题,
而我们已经把 110+ 条带机制的否证编译进 CI。这是可规模化的尽调,不是营销话术。**

---

## 4. 这改变我们做什么(具体,不是口号)

### 4.1 度量单位换掉:从 % 换成价值增量

`signal_track_record` / `strategy_records` / SHIP 门槛,
应当**并行记录美元价值增量**(毛超额 × 该策略承载的资金),
因为那是唯一被证明持续十年的量。

**这也是唯一能让「小资金上的高百分比」不被误读成技能的度量** ——
而那正是加密里最常见的骗局形态。

### 4.2 折扣率写进门槛

SHIP 判定前,自动对效应量施加:自研 × 0.74,取自文献 × 0.42。
**这比 DSR/PBO 更直接,而且它是一个已发表的经验乘数,不是我们发明的。**

### 4.3 研究对象换掉:从资产换成策略

配置者的分析单位是**策略**。这也正是 VDB 该嵌入的东西
(见 `VDB_DIRECTION_2026-08-09.md`:样本构造 + 反证检索 + A2A 接口)。

### 4.4 ④ 层正式冻结

R76–R94 + 今天的 S-129,全部是 ④。
**在 ①②③ 建成并有前向记录之前,④ 层不再消耗任何研究时间。**
这不是新决定 —— `OVERSIGHT §3 P3` 已经写了。**是我需要一个不会忘的地方。**

---

## 5. 我今天三次退回「平庸交易者模式」的记录

1. **横截面 F 因子 IC 研究 + 五分位/tilt 组合** —— 纯 ④ 层选股,
   而 `OVERSIGHT §3 P3` 明写「不做 WorldQuant 式弱因子搜索」。
2. **把 Jazz 举例说明的经验(Wyckoff/出圈)字面化成 SQL 事件研究** ——
   在 44 天、36% 覆盖的数据上跑。
3. **BAB 一出现就想立刻测 beta 压缩** —— 又是先动手,不先问「这对配置者意味着什么」。

**共同点:每次我都跳过了「我们结构性地拥有什么」这一步。**

**判据(给未来的我):在动手之前先回答 ——
「这件事,一个只有 Bloomberg 和回测的人能不能做?」
如果能,那它多半不是我们该做的事,因为我们的优势不在那里。**

---

## Sources

- [Berk & Green — Mutual Fund Flows and Performance in Rational Markets (JPE 2004)](https://www.nber.org/system/files/working_papers/w9275/w9275.pdf)
- [Berk & van Binsbergen — Measuring Skill in the Mutual Fund Industry (JFE 2015)](https://www.nber.org/system/files/working_papers/w18184/w18184.pdf)
- [McLean & Pontiff — Does Academic Research Destroy Stock Return Predictability? (JF 2016)](https://www.hec.ca/finance/Fichier/McLean.pdf)
- [Ang, Rhodes-Kropf & Zhao — Do Funds-of-Funds Deserve Their Fees-on-Fees?](https://business.columbia.edu/sites/default/files-efs/pubfiles/1704/Do%20Funds-of-Funds%20deserve%20their%20Fees-on-Fees.pdf)
- [Frazzini & Pedersen — Betting Against Beta (JFE 2014)](https://docs.lhpedersen.com/BettingAgainstBeta.pdf)
- [Novy-Marx & Velikov — Betting Against Betting Against Beta (JFE 2022)](https://mysimon.rochester.edu/novy-marx/research/BABAB.pdf)
- [Liu, Tsyvinski & Wu — Common Risk Factors in Cryptocurrency (JF 2022)](https://www.nber.org/system/files/working_papers/w25882/w25882.pdf)
- [Ehsani & Linnainmaa — Factor Momentum and the Momentum Factor (JF 2022)](https://www.nber.org/system/files/working_papers/w25551/w25551.pdf)
