# 对标与落地:成功的交易项目、开源框架、超级交易者案例(2026-10-19)

*Seth。Jazz 10-19:「再深度研究,和成功的交易类项目和开源框架比较,再从超级交易者的案例出发落地看」。*
*外部资料多为二手整理,数字以原文为准;每条后面写了来源与可信度。我们自己的数字出自台账(S-xxx)。*

## 0. 结论(三句话)

1. **成功项目赢在结构,不在信号**:一套代码从研究跑到实盘(研究 = 实盘);每个信号只按前向表现、按对整本账的边际贡献计分(不信回测夏普);仓位与风险独立于信号,先保证活下来。
2. **超级交易者赢在「原因」**:在流动性、反身性、结构失衡这些原因上下注,用价格择时,亏小赢大,确认之后才重仓;他们的失败(Druckenmiller 2000、3AC)都是情绪或杠杆压过了规则。
3. **我们现在最缺的四样**:原因层数据(流动性、持仓结构)、研究与实盘同一个内核、跨腿的组合风险层、主观判断的成绩单。第 4 节是落地清单。

## 1. 成功的交易项目:它们做对了什么,我们对照

| 项目 | 做对了什么 | 证据(来源 / 可信度) | 对我们 |
|---|---|---|---|
| Renaissance Medallion | 短周期、计算机驱动;**主动封顶规模**(约 100 亿美元) | 1988–2018 年均毛收益约 66%、净约 39%(Wikipedia,二手) | 我们的优势只能来自大资金做不了的地方:薄山寨、慢逆向(fill_log 的论证同此)。规模不是我们现在的问题 |
| Man AHL / SG Trend(CTA 趋势) | 长期、分散的趋势跟踪,当作「危机时的分散器」 | 2022 年 SG Trend 约 +27%,股债双杀;Asness 指出近年「危机保护」打了折扣(行业评论) | X1V 属于这一族;它的价值要按「和 ① 一起时」评,不单独比收益 |
| Ethena(资金费 / 基差收费,百亿级) | 把现货多 + 永续空做成产品,备付金吸收短期负费率 | BTC/ETH 资金费年化 2024 约 11%、2025 约 5%(Coin Metrics);备付金约占供应 1.1%(二手) | **收费率的油水随资本涌入变薄**;T-128 的周末费率要按「薄」预期 |
| Hyperliquid HLP 金库 | 做市 + 承接强平;2023 年起累计利润约 1.37 亿美元,26 个月里 24 个月赚 | 2025-10-10 闪崩一天约 +4,150 万美元;2025-03 JELLY 事件:承接了被操纵的薄币空单,浮亏一度 1,200 万+(CoinGecko 等,二手) | **最赚钱的日子是别人被迫平仓的日子** —— 「接住爆仓」是可研究的机会;薄币会被操纵 —— R 臂要避开易被操纵的小币 |
| Numerai | 信号只按**实盘**表现、按对元模型的**边际贡献(MMC)**计分 | 官方文档 | 验证装置就是产品,这条我们方向对;缺的是「按对整本账的边际贡献」评每条腿(R 臂那条相关性检验) |
| Quantopian(反面) | 888 个策略:**回测夏普对样本外几乎没有预测力(R² < 0.025)**;回测得越多,落差越大;波动、回撤、对冲更有预测力;2020 年关闭 | 论文 *All that Glitters Is Not Gold*(Wiecki 等 2016) | 我们的预注册 + 试验计数 + 前向是对的;**要数试验次数**;评腿时看波动 / 回撤 / 相关,不看回测夏普 |
| 三箭资本 3AC(反面) | 杠杆 + 集中 + 抵押品流动性差 ⇒ LUNA 一个仓位引发连环追保 | 多方报道(二手) | 硬上限:单名、总杠杆、抵押品流动性;任何单一仓位都不能威胁生存 |

## 2. 开源框架:设计对照

| 框架 | 核心设计 | 我们有 / 缺 |
|---|---|---|
| **NautilusTrader** | 一个确定性的事件驱动内核同时跑回测 / 沙盒 / 实盘,「策略代码从研究到生产不用重写」 | **缺**。S-610 的 SQL 模拟、Railway 纸面空跑、东京主机执行是三份实现 —— 三处行为可能各不相同。落地见 §4-1 |
| **QuantConnect LEAN 算法框架** | 五个模块串联:选宇宙 → 信号(Insight)→ 组合构建 → 风控 → 执行 | 选宇宙、信号、执行都有;**组合构建与跨腿风控是空的**(① / X1V / R / 灵活组合各自记账) |
| **freqtrade / FreqAI** | 独立线程滚动重训、上万特征、离群值剔除、回测里模拟重训 | 缺 ML 层;但它的「超参优化」正是 Quantopian 说的过拟合机器 —— 只借重训与特征管道,不借调参 |
| **Hummingbot(Avellaneda–Stoikov 做市)** | 按库存偏离调报价,控制库存风险 | 现在不做市;规模上来后用于挂单执行(省费、不被「割」) |
| **hftbacktest** | 按盘口逐笔回放,模拟延迟与排队位置 | 等 T-129 自录的 HL 盘口攒够再用;Binance 深度带不是逐笔盘口,用不上它 |

## 3. 超级交易者案例 → 机制 → 我们的数据 → 落地

| 案例 | 机制 | 我们有的数据 | 落地 |
|---|---|---|---|
| **Paul Tudor Jones 1987**:指数跌破 200 日线,崩盘顶部空仓;「打好防守」、要求约 5:1 盈亏比(二手,访谈) | 趋势闸门 + 不对称盈亏 | 日线全有 | X1V 已用 200 日线;R 臂盈亏比 7.3(S-610)。**所有做多腿都要有一道防守闸** —— 现在只有 X1V 有 |
| **Druckenmiller**:「盈利不决定大盘,美联储决定 —— 流动性」;有把握时集中重仓;2000 年情绪化追科技股顶部,6 周亏 30 亿(二手) | 流动性定 β;确认后加码;用规则压住情绪 | 稳定币边际流动性(S-570)有;**美联储净流动性没有** | 接 FRED(免费):资产负债表 − 财政部存款 − 逆回购。预注册:净流动性 4 周变化当 ③ 的推力闸,对照稳定币版 |
| **Arthur Hayes**:美元流动性指数(同上公式)判断 BTC;流动性没回来时「有 1 块钱也不买」(二手) | 同上;耐心 | 同上 | 同上一条,一并测 |
| **GCR 做空 LUNA(2022)**:公开赌 1,000 万美元;理由是算法稳定币的结构脆弱、竞争会抽走它(The Block,一手报道) | 找会自我断裂的反身性循环(价格支撑自身抵押 / 锚定) | 稳定币市值、资金费、未平仓量;**解锁与锚定偏离没有** | 「反身性脆弱」观察名单:锚定偏离 + 杠杆拥挤同时出现。先做研究卡,不交易 |
| **海龟(Dennis)**:20 / 55 日突破、按 N(20 日 ATR)定仓位、2N 止损、按 N 加仓(规则来自二手整理) | 把超级交易者系统化 | 日线全有 | X1V 与 R 是近亲;**缺的是按 N 统一定仓位** —— 现在各腿用不同口径,跨腿风险没法加总(§4-3) |
| **Kullamägi / Minervini** | 第二段突破、抛物线做空 | 日线 | 已测(S-610):第二段样本太少、2025–26 全亏;抛物线做空加止损后变成高胜率小赚 —— 不采用 |
| **HLP 的大赚日** | 承接别人的被迫平仓 | 未平仓量:HL 09-27 起;**Binance Vision 5 分钟版 2020 起(T-133 接入中)** | 预注册:BTC / ETH / SOL 「24 小时未平仓量骤降 + 价格急跌」后次日进、止损放在踩踏低点下方,对照随机日 |

## 4. 对标后的差距 → 落地清单

**P0(本周)**
1. **研究 = 实盘,同一个内核**(Nautilus 原则):把东京主机的决策函数(`exec_host.core.plan_host_orders` + 止损判定)做成能按历史日线回放的「回放器」,S-610 这类模拟与 Railway 纸面空跑都改走它。三份实现收成一份,模拟出来的就是实盘会做的。
2. **原因层数据(全部免费)**:T-133 Binance Vision 持仓结构(进行中);FRED 美元净流动性(新卡)。
3. **组合层**(LEAN 的组合构建 + 风控、Numerai 的边际贡献):每条腿按 N(波动)统一换算风险;跨腿相关;总风险与回撤上限;每条腿按「加进来之后整本账变好了多少」评。

**P1**
4. 主观判断的成绩单(`decisions` 表一行都没有)。
5. 两条预注册:流动性闸(Druckenmiller / Hayes)、承接爆仓(HLP)。
6. 过滤模型:FreqAI 式滚动重训 + 清洗过的交叉验证(López de Prado),等 T-133 数据。

**P2**
7. 挂单执行与库存控制(Hummingbot)、盘口逐笔回放(hftbacktest)—— 等规模与 T-129 数据。
8. 反身性脆弱观察名单(GCR)。

**护栏(Quantopian / 3AC 的教训,写进每张卡)**:数试验次数;前向优先于回测;单名、总杠杆、抵押品流动性硬上限。

## 来源

- Renaissance:<https://en.wikipedia.org/wiki/Jim_Simons>
- CTA 2022:<https://hedgenordic.com/2023/03/bringing-back-crisis-alpha/> · <https://www.man.com/maninstitute/de/gaining-momentum-trend>
- Ethena / 资金费:<https://coinmetrics.substack.com/p/state-of-the-network-issue-335> · <https://eco.com/support/en/articles/14798653-susde-explained-ethena-s-yield-bearing-stablecoin>
- HLP / JELLY:<https://www.coingecko.com/learn/hyperliquid-hlp-vault-analysis> · <https://www.theblock.co/post/348314/hyperliquid-delists-jellyjelly-memecoin-amid-whale-manipulation-fiasco>
- Numerai:<https://docs.numer.ai/numerai-signals/scoring> · <https://docs.numer.ai/numerai-tournament/scoring/true-contribution-tc>
- Quantopian:<https://quantpedia.com/quantopians-academic-paper-about-in-vs-out-of-sample-performance-of-trading-alg/>
- 3AC:<https://www.learnsignal.com/blog/three-arrows-capital-collapse-case-study/>
- NautilusTrader:<https://nautilustrader.io/docs/latest/concepts/overview/>
- LEAN:<https://www.quantconnect.com/docs/v2/writing-algorithms/algorithm-framework/overview>
- FreqAI:<https://joss.theoj.org/papers/10.21105/joss.04864.pdf>
- Hummingbot:<https://hummingbot.org/strategies/avellaneda-market-making>
- hftbacktest:<https://hftbacktest.readthedocs.io/>
- Paul Tudor Jones:<https://www.antoinebuteau.com/lessons-from-paul-tudor-jones/> · <https://valuefund.substack.com/p/paul-tudor-jones-200-day-moving-average>
- Druckenmiller:<https://macroops.substack.com/p/lessons-from-a-trading-great-stanley> · <https://wealthyretirement.com/market-trends/stan-druckenmiller-s-hard-lesson-echoes-today-s-overvalued-market/>
- Arthur Hayes:<https://my.tradingview.com/chart/USCBBS/Giz0oXxR-Arthur-Hayes-USD-Liquidity-Index> · <https://cryptonews.com/news/arthur-hayes-net-liquidity-bitcoin-strategy/>
- GCR / LUNA:<https://www.theblock.co/post/145739/trader-doubles-down-on-10-million-bet-against-do-kwon-by-shorting-luna>
- 海龟规则:<https://www.mql5.com/en/articles/23448>
