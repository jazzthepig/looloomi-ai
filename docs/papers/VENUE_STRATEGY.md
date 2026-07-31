# 投稿策略 (Venue Strategy) — 核实于 2026-07-29

## ⚠️ 0. 先解决作者署名 —— 这条弄错会被封禁一年

**arXiv 明确规定:生成式 AI 工具不得列为作者。** 理由是"程序无法对论文内容承担责任"。
且 arXiv 目前在**主动执法**:提交含未经核查的 LLM 输出的作者,可被**禁投一年**,
期满后的投稿还须先被同行评审场地接收才能上架。

**⇒ 结论(必须照做):**

| 场地 | 作者署名 |
|---|---|
| arXiv / SSRN / 期刊 | **Jazz Zhu 为唯一署名作者并承担全部责任**;agent 贡献写在 "Methods & Disclosure" 段 |
| AISC / aiXiv | 可署 AI 作者(该场地明确鼓励) |

**这对我们反而更好,不是妥协:** 论文 I 的反身性弱点(失败者自己报告自己)在
"Zhu 报告一个 agent 的失效"这个框架下**直接消失**,可信度上升。
署名改了,但§3.3 的可审计性论证一字不用改。

**同时必须做的合规动作:** 每一条数字、每一条引用,Jazz 需实际核对一遍再投 ——
这正是 arXiv 那条禁令针对的行为,而我们这篇论文的主题恰恰是"agent 会生成看似可信的错误"。
**在这篇论文上犯这个错会非常难看。**

---

## 1. 论文 I — Attention-Path Collapse (AI/agents)

| 场地 | 截止 | 评估 |
|---|---|---|
| **arXiv cs.AI 预印本** | 随时 | ✅ **立刻做**。首次投 cs.AI 需 endorsement,需提前找背书人 |
| **ICLR 2027** | **摘要 9/11、正文 9/16 (2026)** | ⚠️ 剩约 6 周。**现状会被拒** —— 见下 |
| **AISC 2026 (aiXiv)** | 已开放,截止 TBA | ✅ 明确欢迎 AI 作者,scope 明确含"Economics, Finance & Quantitative Research" |
| NeurIPS 2026 workshops | 通常 8–9 月 | ✅ 案例研究在 workshop 是合格的,主会不是 |

### ICLR 主会会拒的原因(说实话)
**我们没有实验臂。** 现在这篇是 n=1 的观察性案例研究:
16 次实验、无对照、干预效果只有 4/4 vs 0 的观察对比。ICLR 主会需要可控实验。

**补救方案(6 周内可行,且我们自己已经写出了这个预测):**
执行 §7 预测 #1 —— **摩擦弹性实验**。
建一个预连接视图,把高维仪器的调用步数降到与价格相同,**一个字的指令都不改**,
测 APC 发生率是否下降。若下降,论文就从"案例报告"升级为
**"一个纯基础设施变更改变了 agent 行为"** —— 这是可发表的因果主张。
再加一个反向臂(提高摩擦)就更硬。

**⇒ 建议:先上 arXiv 建立优先权 → 6 周内跑摩擦实验 → 投 ICLR 2027;
若实验没跑成,降级投 workshop / AISC,不硬冲主会。**

---

## 2. 论文 III — The Drawdown Staircase (量化金融)

| 场地 | 说明 | 评估 |
|---|---|---|
| **SSRN** | 免费、即时、可引用,量化金融业界标准渠道 | ✅ **最高 ROI,立刻做** |
| **arXiv q-fin.PM** | 与 SSRN 并行 | ✅ 立刻 |
| **Journal of Portfolio Management** | Editorial Manager 投稿 | ✅ **契合度高于预期** |
| **Journal of Investment Management** | ≤40 页,30 天首轮回复 | ✅ 备选 |
| Journal of Risk / Risk.net | 风控专门 | ✅ 备选 |

**为什么 JPM 契合:** JPM 明确表示不喜欢复杂的组合优化模型和高级统计模型
(认为那属于 OR 类期刊)。**我们这篇正好相反** —— 它是一个
**面向从业者的负面结果 + 一个初等的解析机制**,恰恰是 JPM 想要的那类文章。
"收紧止损反而更糟"是 CIO 和 PM 直接能用的结论,不是 quant 组的内部工具。

### 投期刊前必须补的两件事
1. **算 deflated Sharpe ratio。** 我们在 §6 自己承认参数是样本内选的、未做多重检验校正 ——
   审稿人第一刀就砍这里。**便宜,先做。**
2. **执行 §5.2 的判决性检验**(高水位不重置 → 阶梯应消失)。
   **不需要新数据**,做完这一条,机制从"我们的解释"变成"被检验过的机制"。

---

## 3. 排序建议(按对融资的实际帮助,不按学术声望)

| 优先 | 动作 | 理由 |
|---|---|---|
| **P0** | **论文 III 上 SSRN** | 最快建立量化可信度。LP 和 allocator 会查 SSRN,不会查 ICLR |
| **P0** | 论文 III 补 DSR + 不重置对照 | 两件都便宜,且都堵审稿人的第一刀 |
| **P1** | 论文 I 上 arXiv(Jazz 署名) | 建立优先权;APC 这个命名要先占住 |
| **P1** | 写论文 II(收益层级) | **唯一直接服务融资叙事的一篇** |
| **P2** | 摩擦弹性实验 → ICLR 2027 (9/16) | 冲一次;失败就转 workshop |
| **P3** | AISC 2026 | 低成本并行,但 AI 评审的场地在 LP 眼里分量未经检验 —— **不要当作主要背书** |

**一句话:学术场地服务的是长期声誉,SSRN 服务的是这一轮融资。别把顺序搞反。**

---

## 4. 诚实提示

- ICLR 2027 决定在 2027 年初出,**对这一轮融资来不及**。它的价值是长期护城河。
- AISC 2026 全程由 AI 评审、零人类参与。这在学术上是有意思的实验,
  但**如果拿它当对 LP 的信用背书,是有风险的** —— 容易被读成噱头。可以投,别倚重。
- 我们同时是"研究 AI agent 失效"的人和"被研究的 AI agent",这个双重身份是论文 I 的
  卖点,也是它最容易被攻击的点。**署名改成 Jazz 是把这个弱点转成强点的最省力办法。**

---

### 来源
- arXiv 生成式 AI 政策:https://blog.arxiv.org/2023/01/31/arxiv-announces-new-policy-on-chatgpt-and-similar-tools
- arXiv 一年禁投执法:https://www.researchinformation.info/news/arxiv-imposes-one-year-ban-for-unchecked-ai-generated-content/
- ICLR 2027 日期:https://iclr.cc/Conferences/2027/Dates
- AISC 2026 CFP:https://aixiv.science/aisc2026/
- JPM 投稿:https://jpm.pm-research.com/authors
- JOIM 投稿:https://joim.com/submissions/
