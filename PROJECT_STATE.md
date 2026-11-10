# PROJECT_STATE.md — the living single source of truth

**Last updated:** 2026-11-10 05:36 UTC (Seth — **对外材料改版:PPT 改成情景分析。** Jazz「要改写一下,做情景分析,不要防御性解释,降低二象性表达,维持投资银行策略师标准」。`docs/articles/tokenized_funds_hk_2026-11-09_zh.pptx` 由 18 页改 **19 页**:删掉「能说的 / 不能说的」那张自辩页,换成**「证据基础:量过的,和正在补的」**(左栏已建底座 / 右栏数据缺口 / 底部一条「已排除的解释」——「规模能预测价格」样本外 R² +0.0006、「价值捕获比有效」留出段残差 IC +0.018、倾斜篮子的超额由后见之明的选样带来);新增**「三档情景:未来十二个月」**(上行 / 基准 / 下行,每档给 机制 / 第一个信号 / 判定窗口)与**「情景切换的判据」**(六行读数表:当前 / 上行读数 / 下行读数,Class F 持有人 8、双边报价 无、VATP 成交量披露 未公布、黄金 ETF 试点 证监会已点名、总分布价值 30 日 −5.09%、资产数 123)。**文风按指令改:** 防御性自述收进「证据基础」,判断句改成主动描述;二象性拆掉三处(「网络效应把中间层挤成零还是放大它」→「推向哪一边」;「既不需要牌照也不与三方争收入」→「唯一把「记录与路由」当产品卖的一段:三张牌照在别人手里,收入来自第四方」;「与许可无关」删)。三档情景**不用绿/红**(那是方向色,合规上会被读成信号),统一 indigo 卡 + 正文点名「当前证据落在下行情景」。**机器闸门全绿:** 溢出/出血/文本重叠 0、**372 个文本框 0 违禁词**(违禁表扩到 做多/做空/减仓/加仓/推荐,反向测试塞「推荐买入并做空」→ 三条全报、exit 1)、字形覆盖 0 缺失、**19 页全部 ≤ 6.92in**(地板线 6.96);本轮修掉的四页溢出:第 8 页 band、第 10 页(两栏各 6 条压到单行 + band 三行)、第 15 页 band、第 17 页(机制句压到两行 + body 11.5→11)。**无 git 写入**(沙箱),Mac 侧待提交。)

**更早:** 2026-11-10 05:25 UTC (Seth — **Jazz 11-10 两件落地。** ① **真钱 T25 在带内灵活**(「30/30/20 是推荐比例,像保险公司的组合一样灵活」):`portfolio_targets.flex_weights` —— 再平衡日由 RBv2 定权重(加密、股 20–40%,金 10–30%;下一次 **11-30**),其余日子沿用,算不出沿用上一次;计划里带 `weights` / `weights_source`;常数推荐比例留在影子臂 `flex_x1v:T25_K` 作并排对照。DECISIONS 已记。② **东京主机已更新**(04:26 UTC 三个服务重启,自检 live、agent 到 2027-01-27):头部账户持仓汇总第一批 40 个币进了 `hl_whale_positioning_hourly`(04:00 桶)—— 头部账户整体重仓偏空:BTC 多 $0.92 亿 / 空 $8.98 亿、ETH 多 1.06 / 空 5.38 亿、HYPE 多 0.45 / 空 3.92 亿(S-794 前向从 11-10 起记)。。**之后:** 持仓汇总有了读面 `/internal/whale-positioning`(每币净向、名义额、账户数、24h 变化;只描述);前向记录体检全绿(韩国溢价前向 74 行 11-09 起、crowding 每日在写但 10-30 后没有新 squeeze、`asset_flow_forecast_daily` 等 11-09 那行 asset_flow 落库)。**S-802 预注册 → A 道 T-324:** 高维的 P 在 ① 的 24 名里做 ② 倾斜,能否胜过现任 S-428(动量 + 52 周高点)—— 卡先进 main 再派(lane-c 提的流程修正)。HIGH_DIM 11-10 读法已写。)

**更早:** 2026-11-09 18:52 UTC (Seth — **夜间收尾:7b 的边有了一版可以摆给 Jazz 的 —— RB v2。** **S-801 ✅**(C 道 T-323):风险预算臂把加密腿也限在 0.20–0.40(修掉 X1V 空仓时被加权到 46–63% 的结构陷阱)后,两段都过 —— 2022 崩盘段回撤 −22.1% vs 常数 T25 −25.9%、收益 −12.1% vs −15.7%;2024–26 收益 +62.2% vs +53.8%、回撤只差 0.37pp、两半都赢。限制:两段显著性都不够(p 0.12 / 0.24);少亏有一部分来自多放股金本身;回放不是前向。`flex_alloc.BOUNDS['crypto']` 已改 0.20–0.40,影子臂 RB_T25 就是 RBv2。**🟡 等 Jazz 拍:真钱 T25 的目标权重要不要改由 RBv2 给**(`portfolio_targets` 现为常数 30/30/20;RBv2 平均约 加密 26 / 股 31–36 / 金 25–29,每 21 个交易日按波动重配,仍在偏离预算内)。证据链:S-797 ❌(RB 原版差一点)→ S-799 ✅(崩盘段少亏)→ S-800(好处一半以上是配比)→ S-801 ✅(修陷阱后两段都过)。**另一件等 Jazz:** 东京主机双击 `scripts/host_update.command`(头部账户持仓)。)

**更早:** 2026-11-09 17:46 UTC (Seth — **夜间(Jazz「长任务打通」):7b 的边通了,但还没挣到进真钱的资格;三条研究收卷。** **S-797 ❌**(C 道 T-318 算 / B 道 T-320 盲复算逐位一致;窗口 2024-01 → 2026-10,不含 2022):RB 风险预算 +65.0% vs 常数 T25 +53.8%、两半都赢、回撤只差 0.6pp,但 Calmar 2.049 < 门槛 2.140、A/B p 0.21 ⇒ 不过;STYLE 五条全挂(按天气调权重第六次失败)。真钱 T25 不动;风格表按条款冻结进 `STYLE_TABLE_FROZEN`,三条影子臂前向记。**S-799 ✅(C 道 T-321):** RB 在没碰过的 2022 崩盘段少亏 —— 回撤 −19.5% vs −25.9%、收益 −9.9% vs −15.7%、最差月 −6.5% vs −9.0%。**S-800 ✅ 形式上(T-322):** 两段都胜过 RB 自身的平均配比,但 2024–26 的增益 74% 是常数配比、时变部分把回撤拉深(加密被放到 44–63%)。**结构陷阱:** X1V 空仓时加密腿看起来「低风险」⇒ RB 给它 40–60% 权重,重新进场时超过 DECISIONS 11-01 的 30% 策略层。**S-801 预注册(C 道 T-323):** RB v2 = 加密腿也只许 0.20–0.40,两段复验;过了才连同 S-797 / 799 / 800 摆给 Jazz。**S-798(A 道 T-319):** P 后半段更强是市场态(固定前 150 里两半 −0.008 / +0.120);但最低一档在前 150 里 **+1.45%** ⇒ 「最差一档跑输」是小币尾部性质,不能拿去给 ① 的大币做排除。**S-796 ❌**(C 道 T-317):对手盘四类事件都不进 R-v2 开票闸;squeeze 挡的是真坏票,但金额由 ZEC +73R 一张决定(留一后翻正)—— 以后开票闸预注册一律加「最大 |R| 留一」。**S-795 ❌**(A / B 逐位一致):单币形状认不出「出事之前」;基线认得出但不挣钱。**流程:** 我让 lane「分支上没有卡就别新建」与 seth_bot 范围检查冲突(T-315 合并被拦)⇒ 规矩改为从主目录拷卡、status 改 in_review。**等 Jazz:** 东京主机双击 `scripts/host_update.command`(持仓汇总 520a14f7 已推,主机拉了才有第一行)。)

**更早:** 2026-11-09 15:47 UTC (Seth — **第 7b 段打通第一条边:天气 → 策略风格矢量 → 组合权重(Jazz「根据风格矢量和对应应用策略优化之前跑过的组合,没通就打通」)。** 核 `universe/flex_alloc`(风险预算 RB:波动倒数、与 T25 同事前风险;风格矢量 STYLE:此刻天气下有优势的腿 ±10pp;偏离预算 加密 0–0.9、股金 ±10pp;回放与前向同一个核,调仓函数只看得到当天及以前),灵活组合多三条影子臂 `flex_x1v:T25_K / RB_T25 / STYLE_T25`(不动钱,前向从 10-16 起;RB 40 个共同日后离开 T25,STYLE 等 T-318 冻结风格表)。**S-797 预注册**:两臂在长回放上对常数 T25 判(Calmar ≥ 1.15 倍、总收益不降、回撤不差 2pp 以上、两半都赢、A/B p ≤ 0.10),过的那条提给 Jazz 接进真钱 T25 目标;C 道 T-318(T-317 之后)。**S-795 ❌**(lane-a T-315,B 道冒烟窗口同向):单币 17 维形状认不出「出事之前」—— AUC 0.523(p 0.127)vs 动量 / 回撤 / 波动 / 成交额基线 0.706;而且**基线认得出、却不挣钱**(前 10% 之后 30 天 −0.03pp):每周 330 个币里平均只有 2 个正样本,刚跌完的币多数会反弹。B 道判定区间的完整数下一轮补。)

**更早:** 2026-11-09 15:34 UTC (Seth — **「谁押了什么」接进库(Jazz「要」)。** 东京主机 T-130 自 10 月起每 15 分钟记 HL 30 天盈利前 200 账户的真实持仓,但只在主机硬盘;强平地图只收强平价 20% 以内的仓位。现在同一批快照按币汇总多 / 空名义额、仓位数、账户数(不含地址)随每小时的 liqmap 回报一起送,Railway 写 `hl_whale_positioning_hourly`(表已建);持仓那一半坏了不拒强平地图。S-794 前向登记(2027-05 起判,金额判据:头部账户最偏空的一档 4 周 ≤ −1.5pp)。**等 Jazz:** seth_bot 推完 `20261109-1450-whale-positioning`、Railway 部署后,双击 `scripts/host_update.command` 让主机拉新代码;之后下一个整点应出第一批行(判活:`select ts, count(*) from hl_whale_positioning_hourly group by 1 order by 1 desc limit 3`)。验证装置补三处(循环平移 / 单侧 p / 内容指纹)排队中。。**Pattern recognition 第一步(Jazz「按你建议来」):S-795 预注册** —— 打监控标签 / 宣布下架之前 60 天的单币形状(`window_vector` 17 维,永续全宇宙含死币)能不能被 kNN 提前认出,且 AUC 胜过动量 / 回撤 / 波动 / 成交额的逻辑回归基线 ≥ 0.02;金额判据:得分前 10% 之后 30 天 ≤ −3pp 且比基线前 10% 再低 1pp。A 道 T-315 算、B 道 T-316 只读原文盲复算,唤醒已写。T-313 合并被翻页静态检查误拦(位置参数传排序串),检查已修,合并重排 1520。。**策略升级(Jazz「在等的时候先做」):S-796 预注册** —— 对手盘族站住的四类事件(squeeze / Binance 上币 / 上永续 / Upbit 韩元上币)之后 30 天不开 R-v2 新票,在 T-310 同一个回放账本(956 张、14 名额、40% 上限,引擎一字不改)上逐类判:被挡 ≥ 15 张、平均 R 低 ≥ 0.3R(Bonferroni)、**账本总收益不降且回撤不更差**、两半同号;过的那一类提给 Jazz 作硬规则。C 道 T-317,唤醒已写。)

**更早:** 2026-11-09 14:14 UTC (Seth — **回到高维:节点层两条路都收了,下一步是跨空间的边。** 资金面(S-776 / S-778)与交易所的决定(S-790)在价格相位 P 之上都不再多给信息;P 站着(S-791:周 IC 0.096、t 5.1)但力量几乎全在后半段(0.032 / 0.153)。**S-793 预注册:** Regime 空间(`market_state_vectors` 24 维)的 kNN 能不能提前读出 P 此刻排得准不准 —— 判据要求在 IC 自身惯性(最近 12 周均值)之上 NW t ≥ 2,外加金额判据(态说「准」的周,最低五分位亏得多 ≥ 1pp)。这是 5b-bis OVERRIDE 层(风格周期)第一次有可检验的形态。**结果 ❌**(A 道 T-313 算、C 道 T-314 只读原文盲复算,两份独立实现逐位一致):ρ 0.247 ✅,但在惯性之上 NW t **1.79** ❌、两半 0.30 / **0.05** ❌;金额上方向对(态说「准」的周最低一档多亏 2.8pp,CI 含 0)⇒ ② 倾斜按常数开,OVERRIDE 层在 P 上收卷。盲复算查出我写的「循环块置换」有两种读法(p 0.014 / 0.075),(b) 不过故结论不变。**其它:** 早上三个合并已落(862646b1 / d7d4e149 / 3a05c042);13:56 那批提交被 `test_lessons` 拦 —— 状态头里的 VI 色值 `6366f1` / `818cf8` 被子串匹配读成 Lesson 63 / 81,测试已修;R-v2 11-09 周期 09:49 跑了:新票 0、出场 0、持仓 0(没有信号,14 名额与标签规则还没被用上)。东京主机 07:56 由 Jazz 重启,原因是 SSH 只听 443、客户端走 22;已给 `~/.ssh/config` 的 `Host tokyo`。)

**更早:** 2026-11-09 10:10 UTC (Seth — **对外材料:同一篇研究做成 VI 版 PPT。** Jazz「好的,按照我们的 vi 出个 ppt」。产出 `docs/articles/tokenized_funds_hk_2026-11-09_zh.pptx`(**18 页 / 16:9 / 81 KB**),内容即上午那份代币化基金香港二级市场研究,未另起稿。**VI 取自 `dashboard/src/index.css` 这一个真源**(void `020208` / card `0f2860` / royal `2563eb` / indigo `6366f1` / lavender `818cf8` / bloom `c7d2fe`;Syne + Exo 2 + JetBrains Mono + PingFang SC)。**新建三件套** `scripts/decks/`:`build_tokenized_funds_deck.py`(构建)、`deck_metrics.py`(真字体度量)、`audit_deck.py`(独立审计 + PNG 渲染 + 合规扫描 + 字形覆盖)。**PPTX 没有自动适应,只会裁切不会长高**,所以每个组件用真 TTF 量自己的高度 —— 行框系数实测 Exo 2/Syne 1.21、JetBrains Mono 1.32、PingFang SC **1.40**(PowerPoint 取一行里最高的字体定行高,一行有中文整行就是 1.40 em)。**这一轮量出来并修掉的:** card/stat 测量助手与组件内边距差 0.10in(每组 band 都压在卡片上)· `report_floors()` 跳过 `top>=6.95` 等于把溢出藏起来(揪出 5 页真溢出;来源行统一 8.5pt 后全部回到地板线内)· Exo 2/Syne 无 U+25B8、Exo 2 无 U+2192(PPTX 不嵌字体 ⇒ 豆腐块;项目符号改 JetBrains Mono、第 6 页箭头改等宽)· 第 3 页标签压在 98.5% 折行边界上估成两行 ⇒ 子行留出一行空洞(新增 **PHANTOM-LINE** 检查,全篇只此一处,文案已拆)· 含中文的数值行框更高导致该块标签低 0.039in(整行 tile 现共用最高值行高)。**验证方式换掉了,原因是硬的:** Keynote 的 AppleScript 导出与 WPS 的无头转换在本机均不可用(辅助功能/录屏授权缺失、WPS 无 `--convert-to`),改**独立审计器读已保存 pptx + 自渲染 PNG**:溢出/出血/文本重叠 0、合规扫描 **344 个文本框 0 命中**、字形覆盖 **0 缺失**、18 页全部 ≤ 6.95in(地板线 6.96,页脚横线 7.02);两个关卡**反向验证过**(往副本塞「买入」+ Exo 2 画不出的字符 → 确实报出并 exit 1,不是永远绿的橡皮章)。**如实记下:** PPTX 不嵌字体,收件人机器上没有 Syne/Exo 2/JetBrains Mono 仍会回退(本机已装到 `~/Library/Fonts/`,可撤销);**没有真机 PowerPoint / WPS 打开验证**。**无 git 写入**(沙箱),Mac 侧待提交。)

**更早:** 2026-11-09 08:03 UTC (Seth — **早间:digest 分诊 + 三条 lane 交付审完。** digest 判 DEGRADED 的四条里三条不是故障:`agent_call_log` 能写(探针 07:54:48 入表;24h 0 行 = 没有外部 MCP 流量)· 拒绝的循环 10 个 = 6 本 ④ 账(Jazz 10-20 冻结)+ hl_book「已记录」+ r_tickets_paper 等当天的 `perp_bv_daily`(每天 07:30–08:40 UTC 落)+ anchor · `_mcap_deepen_loop` 是 11-07 一次 ConnectTimeout。**真问题一条:** anchor 落后一天 —— 它在等两本只在工作日 / 每周写的 NAV(`world50_book_nav` / `forward_book_nav`),周末永远等不到 ⇒ `anchor.NOT_DAILY` 修复排队。**S-789 ✅**(lane-b T-309):监控标签在逐句解析的事件集上重量(80 → 137 个代号,有价 60),30 天相对 BTC 中位 **−15.78%**、对照分位 0.005;旧 80 个复现 −18.28% 逐位相同 ⇒ 差异全来自事件集;硬规则照拍板保留,`crowd_map` 与 BP 改引 −15.8%。**S-791**(lane-a T-312):今天快照上 R IC 0.0878 / P 0.0963(旧 0.1006 / 0.1118 作废),`asset_flow_forecast_daily` 旁只引这两行;排序力几乎全在后半段。**T-305**(lane-c,只报):真钱基线 v1 全窗口 +91.6% / 回撤 −16.9% vs ① +41.3% / −77.7%,但**四腿齐全的 2022-08 起 ① 反超 48pp** —— 低 β 账户在涨的年份系统性落后;卡面那句 X1V 是我转述错,实盘是仓库内核(口径 A)。11-08 两次合并失败都是卡冲突没带 fixup,15:56 又把 T-305 派了一遍(重算作废)。合并排队 0801 / 0802 / 0804。**下一个要核:** R-v2 11-09 是 14 名额 + 标签规则的第一个真实进场日,08:45 UTC 之后。)

**更早:** 2026-11-09 04:52 UTC (Seth — **对外材料改版:代币化基金香港二级市场(篇二,含上周金融科技周)。** Jazz「再做新的websearch,加入上周香港fintech week颁布的内容」。新的一手检索把上一版最关键的一个数改了:被批准在持牌 VATP 上做二级交易的**只有两只基金的 Class F 份额** —— Class F HKD $1.64M(3 持有人)+ Class F USD $7.64M(5 持有人)= **$9.28M / 8 个持有人**;市场一直引用的 $628.04M(4 持有人)是 Class A $92.27M + Class I $535.77M,而这两个类别**只有一级、不可二级交易**,且与 Class F **是不同的代币**。依据是 2026-10-23 的 HKEXnews 股东通告(10-26 生效,13 页),与 RWA.xyz 类别标签、26EC23 三源一致。对外版标题因此从「六亿多美元,四个持有人」改成「九百万美元,八个持有人,撮合簿是空的」。**金融科技周(11-02–06)提供的是监管者自己的问法,不是新规则:** 证监会主题演讲《From Tracks to Traffic》——「能否产生真正的车流」「17 只代币化零售产品 / US$1.3bn / 过去一年 +78%」「代币化黄金 ETF 可能成为下一个试点」「创新通道」「金融工作流的速度只取决于最慢的那一步」;金管局 —— EnsembleTX 进入 **24/7 银行间代币化 CeBM 结算**(12 家银行 + 20 家先行者)、DART 四支柱、Project SAGE + Agentic Finance Expert Group、PQC Toolkit、代币化外汇基金债券二级与回购试点、tConnect Launchpad;财政司 —— 第四次数字绿色债券约 200 亿港元 / 四种货币、代币化结算一个营业日(传统五个)、首两张稳定币发行人牌照(4 月)、FPS 注册超 2,200 万、CDI 逾 12.5 万宗 / 约 1,100 亿港元、「AI 代理可以执行任务,但责任仍在机构」。**11-09 数据刷新:** 代币化国债 + MMF $14.63B → **$14.12B**(30 日 −5.09%)、资产 120 → 123、持有人 85,942 → 86,278、APY 3.60% → 3.58%;平台层重排(Benji 第一、Galaxy 进前十、Centrifuge 出),前十占 87.9%。**新做的实测(只读):** 交易平台自己的撮合簿 —— CAMFF 24h 成交 0.01 份 / **0.85 港元**、CUMFU 0.02 份 / **0.00 美元**、**两边都没有挂单**、24h 涨跌 0.00%;而规则要求至少一家做市商报买卖价、iNAV 每 15 秒刷新 ⇒ 规则落地与报价出现是两件事。产出:`docs/articles/tokenized_funds_hk_2026-11-09_zh.md`(485 行 / 26.2k 字符),旧的 `tokenized_funds_hk_2026-10-27_zh.md` 已删;内部稿 `docs/research/tokenized_funds_hk_2026-11-09.md` 改名并追加「增补(2026-11-09)」五节(份额类别更正 / 金融科技周一手材料 / 数据刷新 / 未能独立复核的项 / 方法与合规记录)。**合规:** `python3 scripts/compliance_scan.py` 对两份文件均 0 hit(注意 `docs/` 不在 `--all` 范围内,必须显式传路径)。**没做到的:** 链上第二来源不可复现(ethplorer 401/406/429,Etherscan / blockchair / geckoterminal / dexscreener 均不可得)⇒ 链上持有人与转账额只依据 RWA.xyz 一个来源,已在文中披露;「13 只产品 / $10.7B」仍未复核,继续不用;金融科技周**没有**新的规则修改(唯一新规仍是 10-26 批准 + 4-20 通函);财经事务及库务局黄伟绰 11-03 演讲与代币化无关,已排除。无 git 写入(沙箱),Mac 侧待提交。)

> **本项目的主导缺陷类:「拿不到」被渲染成一个合理的数字,而不是被渲染成「拿不到」。**
> 十一次实例(S-180…S-243)+ 三条课 + 守卫自己失败七轮的记录 →
> **见本文件 §一个形状,十次(在 OPEN RISKS 之后)。**
> 那一段移出第一屏不是降级:**第一屏按 `test_project_state_opens_with_open_risks` 只装活的危险,
> 历史教训排在危险后面** —— 2026-09-22 我把方向段插在 OPEN RISKS 之前,当场被这条判据抓到。

## 现在能跑的 / 不能跑的

```
(2026-10-30 17:20 UTC 实测,Supabase 直查;上一版是 10-20)
✅ 价格源       binance_hist 现货口径贯通(S-698 10-30;永续 bar 存 source = binance_um_hist)· coingecko_pro_ohlc 210 · eodhd 193(World50 扩池后)
✅ 循环         loop_attempt 3 天内 78 个:69 最近一次 ok · 6 本 ④ 冻结记 refused(causal / scalable / combined / dingge / fusion / two_layer,S-631)
                · _hl_book_loop refused「当天已记录」· _meta_allocator_loop refused「策略库只到前天」· _cis_inputs_loop error(macro.global_recent 单项)
✅ 正式 CIS     cis_official_daily 每天一批、只追加,最新 = 昨天
✅ 前向记录     S-560 起 d ≤ 今天 − 2 冻结;① cap_a1_u / ③ tom_pd13 / R-v2 票(r_tickets_state)都到昨天;ⓠ 两臂 10-22 起出前向行
✅ 部署        Railway 16:56 → 20:40 UTC 卡了约 4 小时(02fc20c0 的部署记录建了没动,之后的推送没有部署记录),20:40 自己恢复(89dff45b、6761340c 上线);原因未查 —— 再出现就去 Railway 看部署队列
🟢 执行器       东京主机 **live**(X1V / R-v2 10-29 起、T25 腿 10-30 15:44 起);真钱第一批成交 SPYX 0.23 @ 762.23、XAUT0 0.03 @ 3907.5;每小时心跳
                 select at, outcome, detail->>'book', detail->>'mode', left(reason,80) from loop_attempt where loop_name = 'executor_host' order by at desc limit 6;
✅ 真钱记账     live_account_daily(每日快照,锚定)· execution_quality_daily(10-30 起:成交对决策中间价,锚定,证据面 execution 段)· portfolio_targets_daily
⚪ agent_call_log 0 行 = 没有外部 agent 流量(写入任务 S-562 已修;watch_census 标「量随流量,不判活」)
✅ lane 数据通路 lanes 只拿 publishable key(10-20 轮换后),读权限按表开 lane_read;写只经 seth_bot
```

## OPEN RISKS  (≤7 · cold-start first screen · every item ships a VERIFY command)

*Why this block is first: measured on 2026-07-30, a cold agent following CLAUDE.md exactly could
not reach S-92 or the still-open security hole — the header was dated older than the incident and
the lessons lived only in a 5,672-line ledger. **Don't transmit memory, transmit verification.**
Contract + failure-path walkthrough: `docs/AMNESIA_PROTOCOL.md`; enforced by
`tests/test_cold_start_contract.py`.*

*2026-10-30 17:20 UTC 整块重写(Seth):旧块 390 行、11 条,逐条按它自己的 VERIFY 核过 —— #0a 面板断线三条判据全过(writer 4 / 当日 210 名 / loop_attempt 1,968 行/天)、
#0c nav_panel 声明按 10-06 兜底撤掉、#0d Supabase key 已收尾、#0b INTERNAL_TOKEN 收敛已落地(d0bdf7ab)、8 月的 0–5 号全部早已关闭或被取代。
原文整块移到 `PROJECT_STATE_LOG.md` `[OPEN RISKS archived 2026-10-30]`,一行没删。下面只有活的。*

1. **🔴 Railway 10-21 入侵后的变量轮换没做完,而真钱已经在跑(10-30 15:44 起)。**
   已换:`GITHUB_TOKEN`(10-22)、Supabase secret(10-22)、CoinGecko key(10-29 脚本)。**没换或不确定:** `INTERNAL_TOKEN`(Mac 推 CIS / ⓪ 开关 / 一键停 —— 收敛 d0bdf7ab 之后轮换**现在是原子的**,
   改 Railway 的值所有端点同一时刻切;同一时刻改 Mac 引擎 env 与仓库根 `.env`)、`EXECUTOR_TOKEN`(主机 10-29 重建时 write_env 问过一次 —— 填的是新值还是旧值只有 Jazz 知道;泄露的后果是能读计划、能伪造执行记录,不能下单)、
   `UPSTASH_REDIS_REST_TOKEN` / `EODHD` / `TELEGRAM_BOT_TOKEN` / 其余(`docs/RAILWAY_ROTATION_RUNBOOK.md` §4 表)。runbook 第 1–4 步一次改完再部署,第 5 步 Seth 验。
   VERIFY: Supabase → Logs 里旧 secret 前缀 0 次;`curl -s https://web-production-0cdf76.up.railway.app/internal/build-state | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d["git_sha_short"], d["last_cis_push"]["age_seconds"])'` 换 INTERNAL_TOKEN 后 30 分钟内 age < 1800;主机 `install.sh` 自检 `plan_http: 200`。
   OWNER: **Jazz(密钥只经他的手)** · Seth(每步之后的验证命令与日志核对)

2. **🟡 真钱第一周:三条新记账线都只有一两行,每条都要在第一个完整日核一次。** **10-31 00:19 UTC 第一天核过:** `live_account_daily` 10-30 行 equity 629.49(USDC 338.11 + SPYX 175.04 + XAUT0 116.34)、nav 0.99817、ret −0.18%、mode unifiedAccount,note 写明两条腿按心跳中间价估;00:08 UTC 第二天的 T25 轮:两条腿偏离 0.8% / 0.6% ≤ 5%、不是再平衡日 ⇒ 0 单(按设计);X1V 0 单;10-31 目标表 gold / equity `executable = true`。
   ① `live_account_daily` 10-30 这行应把 XAUT0 / SPYX 按主机心跳市值计入(`spot_usd` 两个键,`note` 含「HL 中间价」);② `execution_quality_daily` since_inception:t25_legs_live 2 笔、fill_rate 1、滑点 +3.5 bps、费 7 bps(HL 现货 taker 0.07%);
   ③ `portfolio_targets_daily` 10-31 起 gold / equity `executable = true`。11-01 起资本 = 最近快照净值(5da2bfca,P5 已定),加钱当天再平衡;11-02 起最近一天的快照先与 HL 公开余额独立核对(对不上 ⇒ note + Telegram)。记着:HL 现货买单手续费扣基础币 ⇒ 持仓 0.029979 不是 0.03,整仓卖出会留 0.0099 零头(≈ $39)——当前规则不会整仓卖。
   VERIFY: `select d, equity_usd, spot_usd, nav, note from live_account_daily order by d desc limit 2`(note 不该含「对不上」)· `select d, sleeve, capital_usd from portfolio_targets_daily order by d desc limit 4`(capital_usd 应是快照净值,不是 600)· `select sleeve, n_intents, fill_rate, mean_slippage_bps, implementation_shortfall_bps from execution_quality_daily where span = 'since_inception'` · `select d, sleeve, executable from portfolio_targets_daily where d = current_date`。
   OWNER: Seth

3. **🟡 IC 乘数这一层留不留(S-702)。** 更正 10-30 的说法:CIS 的 IC 乘数读 Redis `cis:factor_performance`(纸面平仓喂,372 样本,**活着**),等于 1 是因为没有一个因子过 |r| > 0.10;`cis_regime_fitness` 是一张 0 行、没有读者的表,`_regime_fitness_loop` 每天往里写 0 行(有写入端没消费者)。同一批数据:90 天窗口 M / O 的 IC 是负的(18 个独立日,噪声),365 天全是 +0.03~0.12(185 个独立日,t≈1.6);套上去对今天排名的影响:前 10 名 9 个不变、名次相关 0.976。**要 Jazz 定:** 留(365 天 + 门槛 + 显著性)还是关(停循环、删表,CIS v2 本来不靠这层)。
   VERIFY: `select count(*) from cis_regime_fitness`(0);`curl -s .../api/v1/factors/performance | python3 -c 'import sys,json;d=json.load(sys.stdin)["report"];print(len(d["active"]), len(d["candidate_removal"]))'` → 0 活跃。
   OWNER: Jazz(方法论)· Seth(执行)

4. **🟡 `INTERNAL_TOKEN` 的 Mac 副本仍在 `cometcloud-local/.env`(lane 能读到的位置)。** #0d 的尾巴:Mac 引擎的 secret 应搬到 `~/.cometcloud/engine.env`(SYNC #31),搬完再做第 1 条的轮换才不会漏一处(S-371 的「漏改第三份」09-28 发生过)。
   VERIFY: Mac 上 `grep -c INTERNAL_TOKEN /Volumes/CometCloudAI/cometcloud-local/.env` → 0,`test -s ~/.cometcloud/engine.env`。
   OWNER: Minimax(搬)· Jazz(值)· Seth(核)
5. **🟡 ① 的执行场所装不下 $30M(T-082 ④,11-08)。** 全市场成交口径 core_cap 能装 $8.84B;在我们真下单的 Hyperliquid 上:一次扫 ±2% 薄边 $5.8M、
   5 天 10% 参与 $21.5M —— 卡在 BTC(HL 现货 24h ≈ $31M,全市场的 1/869)。24 名里 7 名 HL 无深度,其余除 BTC / ETH 只有永续,而 ① 只持现货(08-23)。
   量级可信(20 个深度快照 / 4 个成交快照),小数点不可信。**不是策略问题,是场所问题**:同一个式子换成 Binance 现货 USDT 对 ⇒ ① 能装 ≈ $7.4 亿(卡在 BTC)。**Jazz 11-08:AUM 起来再扩;BP 写清路线图**(已写,分阶段、按门槛)。
   VERIFY: `curl -s https://web-production-0cdf76.up.railway.app/api/v1/fund/capacity | python3 -c 'import sys,json;b={x["book"]:x for x in json.load(sys.stdin)["books"]}["core_cap"];print(round(b["capacity_aum_usd"]/1e6), round(b["venue_capacity_aum_usd"]/1e6,1), round(b["venue_flow_capacity_aum_usd"]/1e6,1))'`
   OWNER: Jazz(何时扩、选哪个场所)· Seth(接新场所的深度 / 成交进同一接口)

## 一个形状,十次(历史教训 —— 排在危险之后)

> **S-283 最需要记住的一条:三个 P0 里有两个不是「没有控制」,是「控制的作用域差一格」。**
> inception 身份护住了 Postgres、漏了先应答的 Redis;`test_table_columns_match_the_code`
> 只覆盖 `api_keys`,于是新增一列本可静默杀死 ① 账。**作用域太窄的控制会把注意力从它漏掉的
> 地方引开 —— 因为它看起来「已经有守卫了」。** 与 MEMORY.md 那条(只给 MEMORY 加上限,成本
> 搬到 PROJECT_STATE)是同一个形状。

## 本轮一句话:**一个形状,十次**

> **S-262/S-263(2026-08-30→09-01)。** `/internal/` 40 条路由全部行为验过:12 条有意公开 ·
> 27 条已收口 · 1 条已知坏 · 匿名可用的敏感端点 **0**。详见台账。**危险项已进 OPEN RISKS。**

每一次都是**「拿不到」被渲染成一个合理的数字**,而不是被渲染成「拿不到」。
一个 0 在合法区间内、看起来正常、是空累加的天然产物 —— 所以九次都没人发现。

| # | 哪里 | 缺失变成了什么 |
|---|---|---|
| S-180 | `redis_get_key` miss=error | 一次丢包 → 58 资产 T1→T2,评级写进永久记录 |
| S-184 | quant / crowd_clock / 日快照 | 交易历史被覆盖 · 重复行 · 影子行 |
| S-185 | 占用查询用了不存在的列 | fail-closed 拒写 → **静默停机 115 分钟,`/health` 全绿** |
| S-190 | 深度面板覆盖率下限只标注不拦截 | 1/262 的运行照写,`max(trade_date)` 显示当天 |
| S-194 | 五本账本 `pnl = 0.0` + 条件累加 | **面板 +23.99% 期间账本记 0.00%** |
| S-195 | CoinGecko 用错端点四个月 | 小时点塌缩成"日收盘",08-19 BTC 记 +0.30%(实际 +7.15%) |
| S-200 | T2 构建 110s / 预算 12s | 缓存永远填不上 → 永久降级,`regime=None` |
| S-201 | `NAV_TABLE` 声明了没写入者 | 表存在、永远空、看起来这项有人管 |
| S-202 | `{"ok": True, "rows": 0}` | **CIS 四个月用中性权重打分,日志每天说正常** |
| S-242 | 接收端漏写顶层 `macro_regime` | HIGH 级 regime 信号**从 feed 里消失**(守卫是 `if regime:`);CIS gate 落到 58 默认值而非 TIGHTENING 的 52 → **27 个过闸报成 20 个** |
| S-243 | 每资产 regime 从没和顶层对过账 | 同一份响应顶层 `Tightening` / 每资产 `RISK_ON`(58/58)→ 配置面板对投资人显示 **"Risk appetite elevated. Full allocation eligible."** |

**S-242/243 三课**(细节见 ledger,别在这里展开):① **沉默也是一种渲染** —— 前九次是「拿不到」
渲染成一个合理的数字,这次渲染成**什么都没有**,一条缺席的 HIGH 信号和「没这个状况」在输出上
一样;所以 `cis_regime_unmeasured` 那条 pillar 全 0 的信号不是装饰,**未测量必须占一个位置**。
② **读对 key 还不够** —— 引擎发 `Tightening`,所有表是 UPPER_SNAKE,miss 的表现是默认值不是报错。
③ **「两处写法不一致」要当缺陷查,不是当风格容忍** —— S-243 正是问「要不要统一大小写」问出来的,
表层不一致底下压着一个不一致的**事实**。四条出口(含最易烂的 degraded/LKG)统一走 `_unify_regime()`,
矛盾一律 `_logger.error`,**不静默调和**(引擎侧归 Minimax lane)。

⚠️ 守卫失败第七轮,同一类(匹配名字而非构造):S-243 前端守卫初版按 `if "regime" in line` 过滤,
而出问题的 key 所在行**恰好没有这个词** —— **在真实的坏文件上通过**。已改成跟踪代码块 +
补「用 fixture 重新引入 bug 确认守卫会响」的测试;旧版 CISWidget 实测 7 处全捕获。

⚠️ **守卫自己失败了六轮**,两类:匹配名字而非构造(**解释 bug 的注释废掉了抓这个 bug 的测试**,已抽成 `tests/_source.py`);测试样本过度确定。每个守卫现在都用重新引入 bug 验证过。

## 方向(不放 MINIMAX_SYNC —— 那个文件会按体积轮转)

### 2026-11 铺排(Jazz 11-01「往前铺排」;Seth 11-01 15:20 UTC 写,按先后排)

真钱已经在跑(T25,600 USDC,10-30 起),地基三件(现货口径 / 按时点 ① / 执行质量)都落了。接下来两周的主线只有一条:**把「可验证的前向记录」从 JSON 变成 LP 和 agent 看得见的东西,同时把真钱账本的第一个月跑干净。**

| 期限 | 事 | 谁 | 判据 |
|---|---|---|---|
| 11-01 | **Track Record 页展示真钱**:`other_lines`(真钱 t25_live、World50、灵活组合)+ `execution` 段(成交对决策中间价)—— 页面现在只画纸面 books,标题还写「paper book」 | Seth | 页面三段齐;静态测试守合规词;dist 已构建 |
| 11-02 | **每日 00:30 UTC Telegram 简报**:真钱 equity / nav / 当日、三本执行账昨夜的轮次、执行质量累计、不 ok 的循环、OPEN RISKS 条数 —— 让 Jazz 每天一眼 | Seth | `loop_attempt` 里 `_daily_digest_loop` 每天一行,Telegram 收到 |
| 11-09 | **CIS v2 加密切换**:11-01 中期读数(S-704)① ② 11 / 11 天过;11-09 照 `docs/research/cis_v2_switch_check.sql` 原样再跑,不掉就按 Jazz 10-22 的裁定切(S-668) | Seth 跑 → 切 | `/api/v1/cis/v2` shadow.crypto_consecutive_days ≥ 20 且 SQL 两段都过 |
| ✅ 11-01 | ~~P5 再平衡日资本~~:= 最近一次真钱快照,加钱当天再平衡(5da2bfca);USDY 收益腿仍未建 | — | `select d, sleeve, capital_usd from portfolio_targets_daily order by d desc limit 4` |
| 11-04 起 | **情景台账第一批结算**(E53–E56,11-03 的值);之后每份周复盘的预期表同一轮写进台账(WEEKLY_REVIEW.md 开头已写);lane-a T-218 的前向命题审后入账 | Seth | `select s.id, s.outcome, s.brier from scenario_scores s` |
| 主机拉代码后 | **强平地图每小时一批**(T-221);一周后给 lane-a 开回放卡:历史上地图显示「冲击 × 深度」高的时候,之后有没有踩踏 | Seth → lane-a | `select ts, count(*) from hl_liq_map_hourly group by 1 order by 1 desc limit 3` |
| 11-08 | **容量第一份 7 天报告**:`venue_depth_snapshots` 满 7 天(21 批)后按名字 / 按账写「场所口径 vs 全市场口径差几倍」进台账(T-082 验收 ④)。管子已在跑(Railway 直接读 HL 公开盘口;主机录的逐 10 秒盘口留在主机上做日内研究) | Seth | `select count(distinct fetched_utc) from venue_depth_snapshots` ≥ 21 |
| ✅ 11-02 | **规模 / 冗余定了(DECISIONS 11-02)**:主机死了只报警(HL 不收现货触发单、不开对冲空单);**第一笔外部钱或 T25 > $5 万** ⇒ 独立 HL 账户 + key + 第二台待命主机;**股票 / 黄金腿限 HL 现货容量内**(现 ≈ $13–20 万基金),超出走券商或更深场所。简报每天看这两条线,每月 1 号提醒重跑探针 | Seth(到线时执行) | 简报里出现 ⚑ 行 |
| 待 Jazz | **① 本身的场所计划**:HL 现货 BTC ±2% 只有 $3.8M ⇒ ① 一次吃进 ≈ $5.3M;上 $30M 前要定 ① 在哪些场所持现货(OSL / CEX 现货 / 链上 DEX)或接受多天建仓 | Jazz 定 → Seth 接 | DECISIONS 一行 |
| 待 Jazz | IC 乘数这层留不留(S-702);密钥轮换(runbook 就位);World50 EW×Mom 有链上形式后股票腿换掉 SPYX 替身 | Jazz | DECISIONS 一行 |
| lanes | Mac 引擎 secret 搬家(SYNC §IN-FLIGHT 第 43 行);S-690 / S-695 在现货面板上复核(S-701 之后研究与前向同口径了) | Minimax | SYNC 回执;台账 M- 条目 |

**不做的:** 不加新数据源;不开新策略臂;不碰 ④。真钱第一个月的全部注意力在「账对不对、显示对不对、停得住不住」。

> **2026-09-22 定规(S-398):** 09-21 一次按体积的轮转把 SYNC 从 69,725 砍到 21,602,
> **「自证率 / 棘轮 / S-380」在活文件里的提及变成 0 次。**
> 设计来防止「三天没人发现六个价格源死了」的那个机制,自己被归档掉了。
> **方向从此住在这里**(有上限,但是被策展的,不整体轮转)。**A/B/C 冷启动读这一段。**

### 产品边界(Jazz 2026-09-22 裁定 —— 这条决定什么需要机构级严谨)

> **「jev 的模块是用来做测试的,不是最终的;
> 交易模块不应该属于 looloomi.ai 的产品,是我们自己用数据 dashboard 的应用,现在还在测试。」**

**和 ARCHITECTURE 那句不矛盾,是把它切细了:**

    产品        = **可验证的前向记录 + 它的归因与 provenance**
    内部工具    = 执行/交易管道、Jev 实验、ops console、回测脚手架

「验证装置就是产品」仍然成立 —— **我们卖的是证据,不是交易机器人。**

**这条的直接后果(不是口号,是判据):**
1. **实验模块不许被生产 runner 在 import 期硬依赖。**
   实测 S-402:`spec_runner.py` 顶层 import 三个 Jev 模块,脚本路径下 import 先炸,
   症状伪装成「`--book=c` 退出码不对」。**S-403 已改惰性导入,缺失 ⇒ BLOCKED 而非跳过。**
2. **投资人可见面 vs 内部工具,合规口径不同。** 规则 1(只用 STRONG OUTPERFORM…
   那套枚举)守的是**投资人可见面**;内部执行工具里说「order」是可以的,
   **但它一旦出现在任何对外表面就适用规则 1 和规则 8。**
3. **严谨度分级**:前向记录、归因、provenance 要机构级(60 天、OOS、β-matched 基准);
   内部工具「够用 + 失败要响」即可。CLAUDE.md 那句「Internals can be rough;
   interfaces cannot」在这里第一次有了明确的分界线。
4. **所以 S-397 Jev overlay 不是「§5b ④ ship-ready 的产品内核」** ——
   它是一次**评测**(M-176 的对象)。任何把它当产品腿来排期的说法都要改。

### 目标:装置自证率,棘轮式,只能升,**没有到期日**

> **每天都要能回答:这套装置今天说的话,有几成是量出来的。而这个比例只许上升。**

两个比值,全部取自装置已经在报的数,**不新建指标**:

    ① 覆盖率     = coverage.n_covered / n_total    (2026-09-18 基线 **14 / 81**)
    ② 可证成功率 = 有 last_ok_at 的循环 / 全部循环  (2026-09-18 基线 **3 / 23**)

机制与 `scripts/lesson_enforcement_baseline.txt` 同源:基线落盘,
**preflight 拒绝任何让这两个比值下降的推送。**

**为什么是它而不是「60 天前向记录」**(前一版目标,Jazz 当场否掉):
日历门控的目标会把工作变成等待;**而且等不到** —— 实测 41 天里五次 inception,
平均每段活 8 天(S-384),每一次重置都是**一个部件没有停下来、产出了一个貌似合理的数**:
历史被截断 / vol 三分位没接上用了冻结默认值 / 面板动了账本记 0.00% / inception 经未加作用域的 key 继承。

    装置分不清「量到了」和「没量到」
      → 部件产出貌似合理的数 → 账本照记 → 几天后才发现
      → 整段作废 → 记录重置 → 永远到不了 60 天

**所以棘轮不是那个目标的代理,它是因果路径。** 自证率 ↑ ⇒ 缺陷当天可见 ⇒
inception 不必重置 ⇒ 记录才可能长到 60 天。**这条链是量出来的,不是论证的。**

### 打平时的破局方向:从反射层走向因果层

ARCHITECTURE:最深的对象是 **Entity/Decision**,CIS 与动量是它的反射。
实测(S-383,43 天截面):`pillar_m` 动量 Q4−Q1 **+0.941pp/天 t=2.43**,
而复合 CIS **+0.747 t=2.23** —— **复合分弱于它自己的动量支柱**;
`pillar_o` 链上 **+0.059 t=0.20**(C 已证其离散度正常,是前向信号真的弱)。
**反射层有效,因果层贡献≈0,而 `decisions` 至今 0 行。**
两件活对棘轮贡献相近时,**选离因果更近的那个**。

### 三条 lane 的分母归属

**A**(统筹):循环的 `last_ok_at` 地基 · 面板宽度(cg_pro ≥20 标的 ≥415 天,现 6 / 中位 73)· 入库存活
**B**:把这两个比值做成脚本 + 棘轮进 preflight(**现在是手算的,手算的指标下周就没人算**)· 判据审计
**C**:ⓠ 阈值重标定(458 天 0 次触发)· 分级中段倒挂 · ② 的规格题

### 我保留、不下放的四件

换源 / 换口径(`PANEL_SOURCE` 由 Seth 执行,S-245)· 降地板(默认否)·
策略自由参数(阈值窗口权重 → C 出方法 + Jazz 拍)· 花钱 · key 真值(只经 Jazz)

---

## §S-RATE-DAILY · task #113 (2026-09-14,Seth lane)

**Why this section exists.** Minimax-C's「高海拔系统重设计」plan's success metric is **rate decline**: pre-plan baseline ~6 S/day (Pattern A + D cadence),post-plan target **<2 S/day** within 14 days of plan ship (2026-09-14 → 2026-09-28). Headline metrics here,rebuilt weekly by `scripts/s_rate_daily.py`. **Two failure shapes both look like S-rate "levels off"; this section is the read-side discipline that distinguishes them.** Detail: REFUTATION_LEDGER S-342/S-343 sibling note.

### Current snapshot (live,2026-09-14)

```
total dated entries  : 178
dated days           : 32
last 7d mean         : 6.00  S/day
last 14d mean        : 6.36  S/day
all-time mean        : 5.56  S/day
max day              : 2026-08-27  (15 entries)
today (2026-09-14)   : 3 entries  (S-342, S-343, S-345)
```

### Per-day table (last 14d)

```
date          count  s-numbers
--------------------------------------------------
2026-09-01    6      S-263 S-264 S-265 S-266 S-267 S-268
2026-09-02    13     S-269 S-270 S-271 S-272 S-273 S-274 S-275 S-276 S-277 S-278 S-279 S-280 S-340
2026-09-03    2      S-281 S-282
2026-09-04    7      S-288 S-289 S-290 S-291 S-292 S-293 S-294
2026-09-05    14     S-295 S-296 S-297 S-298 S-299 S-300 S-301 S-302 S-304 S-305 S-307 S-308 S-309 S-310
2026-09-06    3      S-311 S-312 S-314
2026-09-07    1      S-315
2026-09-08    11     S-317 S-318 S-319 S-320 S-321 S-322 S-323 S-323b S-323c S-323d S-323e
2026-09-09    15     S-323j S-323k S-323l S-323m S-323n S-323o S-323r S-323s S-323u S-323v S-323x S-323y S-323z S-324 S-325
2026-09-10    1      S-326
2026-09-11    5      S-327 S-328 S-329 S-330 S-331
2026-09-12    6      S-332 S-333 S-334 S-335 S-336 S-337
2026-09-14    3      S-342 S-343 S-345
```

### ⚠ Undated entries (53 of 231 headings — do not count in the rate)

These are **legacy entries** (S-180…S-241 era) where neither the heading nor the
body has a parseable `YYYY-MM-DD`. They are NOT counted in the rate metric —
an honest "no date" beats a fabricated one. The 4-strategy walker
(`scripts/s_rate_daily.py:_extract_date`) covers trailing-parens /
author-trailer / body `**日期**` / heading-fallback; no strategy matches
these specific headings. Run with `python3 scripts/s_rate_daily.py
--since 2026-08-01` to see them in context (output emits the body excerpt
for each, so reading the first 5 is enough to recover the date for
re-issuance if needed).

These are **legacy entries** (S-180…S-241) where neither the heading nor the
body has a parseable `YYYY-MM-DD`. They are NOT counted in the rate metric —
an honest "no date" beats a fabricated one. The 4-strategy walker
(`scripts/s_rate_daily.py:_extract_date`) covers trailing-parens /
author-trailer / body `**日期**` / heading-fallback; no strategy matches
these specific headings. Read with `python3 scripts/s_rate_daily.py
--since 2026-08-01` to see them in context.

### Verification cadence

- **Weekly:** `python3 scripts/s_rate_daily.py --summary --since 2026-09-01`
- **Per PR:** registered in preflight stage 3a-undevicesima-quater — the
  4-strategy walker + sub-ID expansion are regression-guarded.
- **14-day target:** on or after 2026-09-28, the `last_14d_mean` should
  drop below 2.0 if the structural plan is working. Below 1.0 is the
  stretch goal. **A drop that isn't accompanied by the per-day count
  decreasing is a slow-creep false positive** — same shape as S-244
  (silent regression of the watcher).

---

## 2026-09-05:S-294 / S-295 —— 心跳首日,两个误报一个真故障

心跳(S-282)部署后第一轮抓到 3 个循环 failing。**其中两个是我造成的:**

**① 正确的拒绝被记成故障。** `_deep_panel_loop` 的错误原文是
`Write REFUSED so the gap stays visible` —— 那是 S-245 地板守卫在正确工作。
采集器**自己早就返回 `refused: True`**,是心跳层把它折叠进 `ok=False`。
→ 加第三态 `REFUSED`:不计入失败,自己计连续轮数(连续拒绝 30 轮说明上游没恢复)。

**② 修①时又犯同一形状。** 我给 `beat()` 和调用点都加了 `refused`,
**唯独漏了中间那层薄包装 `main._beat`** —— 线上报 TypeError。
而我为此写的守卫**只检查调用点有没有 `refused=` 这个字符串,从没真的调用过**。
→ 新守卫逐字比对两个签名并**实调一次**。

**③ 真故障。** `_pod_aggregator_loop` 连续 5 轮 `ImportError: R62_Z` ——
那两个常量住在 `r63_fusion_validation`(名字带 R62 而住在 r63),
`pod_aggregator_paper` 是全仓唯一没拆开这两个 import 的调用点。
`pod_aggregator_nav`(一张 NAV 表)因此停写,而心跳上线前无人知晓。

**④ S-295:时间维度上的同一形状。** 循环 24h 一轮、心跳 TTL 3 天 ——
**修复上线后,旧构建记的失败会挂满三天**,而「修了还在失败」和
「还没轮到它跑」完全同形。→ 每条心跳带 `build`,`assess` 给 `stale_build`。

🔴 **沙箱已跑不完 preflight**(>178s 硬上限 + 后台进程随调用结束被杀)——
我只能跑改动到的子集,**完整的门只在 Mac 侧**(与 S-280 同结论)。

## 2026-09-04:S-288…S-292 —— 把已付费的能力接上

**Jazz:**「我们有 coingecko analyst 是 139 刀一个月的,你又把他忽略了?
这件事已经被失忆了很多次。」→ 属实。S-264 我自己写下那 14 项能力清单,
此后 Entity 那批**零调用**;S-290 我还用免费端点建快照层并写下
「历史买不来,今天开始攒」——**而付费档直接给到 2020-08-11**。

我判「不可用」的依据是一次 HTTP 403 —— 那是 **Cloudflare 1010 客户端指纹拦截**
(裸 urllib),不是权限。换 httpx 立刻 200(`plan=Analyst`,剩余 482,574)。
**「我探测失败」和「我们没有这个能力」是两个状态。**

**已接通(S-292):** `transaction_history` → `treasury_decisions`,
同时插进 **心跳 (S-282) · 判活 (S-278) · 覆盖清册 (S-279) · Supabase**
四个面 —— Jazz:「就像买了显卡、存储、网卡,但服务器不是连通的」。
`signal_outcomes` 死 123 天 = 心跳没接;`market_state_vectors` 停 27 天 =
从没上日程。**两个前车都在隔壁。**

**实跑:** 56 实体;写入被 `role=replica` 正确挡住(只有线上可写)。

| | 按家数 | **按持仓** |
|---|---:|---:|
| BTC | 19.4% | **87.0%** |
| ETH | 61.8% | **22.9%** ⚠️ |

**ETH 看家数还行、看持仓很糟** —— BitMine(占企业 ETH 74.6%)解析不出 id。
只报一个口径这个洞看不见。

**防复发做成 CI:** `tests/test_paid_capability_is_used.py` —— 每项付费能力
要么有真实调用点,要么带理由登记未接,未接数只减不增。台账/注释/CLAUDE.md
**都已经存在过而失忆照样发生**,因为那些要人主动读。

## 2026-09-03:S-281 / S-282 —— 根因找到了

**「怎么都说健康,但总有东西停了?」的完整答案是四行代码:**

```python
except Exception as _e:
    print(f"[OUTCOME] ⚠️  daily run failed: {_e}")   # ← 只进 stdout
await _asyncio.sleep(_OUTCOME_INTERVAL_S)             # ← 然后继续睡
```

循环**活着**、启动打了 ✅、每天准时跑、**每天失败一次**,而 `signal_outcomes`
从 2026-05-03 起死了 **123 天**,没有任何监控知道。

    写入者悄悄失败 (S-282) × 表无人判活 (S-279) = 静默死亡

**39 个循环里 28 个是这个形状。** 已接心跳 11 个(覆盖全部 9 张 NAV 表),
其余走只减不增预算。

**两张死表两个诊断:** `market_state_vectors` 每行 computed_at 精确到微秒相同
⇒ **从未被调度**(要加日程);`signal_outcomes` 是跑着天天失败(要查错)。
**两者在 max() 上同形。**

**S-281:** `risk_meter_history` 那行 `d=2099-12-31` 的 interpretation 写着
"[smoke test from D2 swap verification]" —— 一个「用远期日期以免撞车」的合理
直觉,把判活器**静默关了 10 天**。没删数据,改为让 max() 只看已发生的行
(判活器要对污染鲁棒,否则下一个冒烟行会再关一次)。

⚠️ **我当天第二次夸大动机数字**(先报 67/64,真实 39/28;上一次是 27%→22%)。

## 2026-09-02 追加:S-279 —— 「还差多少」终于是一个整数

**Jazz:**「怎么都说健康,但就是有东西停了?」→ 查证:**端点没撒谎**,
它们此刻正在报 degraded / stale / domain_without_usable_source。
病在**覆盖**:health-summary 只查 4 件事,S-278 只看 10 张表,而库里有 67 张。

```
n_total 67 · 已覆盖 11 · 显式排除 18 · 未覆盖 38(track_record 层 17)
```

**9 张 NAV 表只有 `beta_core_nav` 一张在被判活** —— 而产品就是可验证的前向记录。

🔑 **跑实盘要写的 `execution_intents` / `execution_outcomes` 恰好在那 17 张里。**
所以补 track_record 覆盖不是官僚流程,**它就是 1000u 的前置条件**。

设计:清册现查 information_schema(明天新建的表明天就在缺口里)· 按层报不按总数报 ·
排除逐条带理由禁止模式匹配 · **覆盖不全不把裁决压红**(常亮的灯 = 坏灯,
那正是要修的病)而是给裁决加 `covers` / `unqualified`。

## 2026-09-02 追加:S-278 —— 生产者判活,查出三个活故障

任务 #33。data-freshness 只看 ohlcv 的**数据源**,而静默死亡大多发生在**生产者表**上,
且**没有一张在被判活**。实测:

| 表 | 写时钟 | 事件时钟 | |
|---|---|---|---|
| `risk_meter_history` | 09-02 | **2099-12-31** | 未来日期 ⇒ max() 永远报新鲜 |
| `signal_outcomes` | (无) | **2026-05-03** | 停 **122 天** |
| `market_state_vectors` | **2026-08-06** | 08-05 | 停 **27 天**(我自己建的 writer) |

`signal_outcomes` 尤其刺眼:data-freshness 的 docstring 把「它曾死 80 天」
当成建那个端点的理由,而**它现在死了 122 天**。

> **一个判活器最坏的失败不是漏报,是被它监视的数据本身关掉。**

🔴 **看见 ≠ 修好。** 三个故障只是被看见了:2099 行要删、两个 writer 要重启查因。
已上提 §IN-FLIGHT。

## 2026-09-02 追加:S-277 —— 我欠 Minimax 的 18 天

Jazz:「minimax 都在等你修完和下指令」。查 §IN-FLIGHT:**他们不是在等指令,
是在等我。** 四行「等 Seth 开 endpoint」,`risk_meter_history` 自 **08-15**。

> **一条只有禁令没有出口的规则,考验的是对方的耐心,不是系统的正确性。**

已开 `POST /internal/mac-write/{dataset}`(4 张表,逐条裁决,X-Internal-Token)
+ `GET /internal/mac-write/schema`(契约回声)。守卫那一条:**未知列拒绝不丢弃** ——
`risk_meter_history` 用 `regime`、`asset_embeddings_history` 用 `macro_regime`,
写错一字就是一行静默的坏数据。列名取自 information_schema 实查,不抄 Mac 侧代码。

**指令已下** `MINIMAX_SYNC §SETH-DISPATCH-2026-09-02`:A 切四个 writer(一个一个,
先发 1 行试);C 回三个问题 + 跑全panель覆盖表(M-123)、**停止建抓取器**(rule 3b)。

## 2026-09-02 追加:S-276 —— 跨 lane 基线(统筹)

**查实:** M-118 报「PENDLE +820 天大赢家」——Supabase 里 coingecko 源
**1940 行、2021-04-28 起,与他抓到的起始日一模一样**。+933 天里最大那项是重复,
其余是 binance_hist 停更后的近期天数,非历史深度。

**根因不是粗心 —— minimax-c 读不到 Supabase**,只能拿单一个源当基线。
⇒ 已开 `/internal/data-coverage`(无凭证)+ Supabase RPC `ohlcv_symbol_coverage`
(已应用,405 标的/530 组合)。主字段 `deepest_start` = **跨源并集**。

**分工定案(回答 Jazz「让他多承担」):**
抓取/落库归一到 Seth lane 一条路(有守卫/schema/preflight);
minimax-c 多承担的是**用**——挖掘、回测、VDB 维护。
「多承担」若变成「各建各的抓取」,代价就是今天咬了我们两次的那个形状:
两个看起来一样的序列其实不是同一个量。**不要把他的 fetcher 接进 cis_scheduler。**

**待他回:** fetcher 的 retry 耗尽路径返回什么(可能带着 S-269 修掉的缺陷)。

## 2026-09-02 追加:S-275 —— ETF 是产品,不是资产(并作废 S-274 的数字)

**Jazz:**「要找对资产的指数先,etf 是产品,所以你现在的逻辑不对的,价格也不会对。」

实测:`ohlcv_daily` 的 TradFi 面板 **14 个 symbol 全部是 ETF** —— 没有一个指数、
一个现货、一个收益率。TLT 按月付息(票息**是债券回报的主体**,不在价格里),
USO 是期货 ETF(展期拖累可达 −30%/年)。

**约束是窗口不是禁令**(容差 2%):GLD 撑 1260 天 · TLT 126 天 · USO **16 天**。
S-274 用的是 1926/2801 天 ⇒ **差一个数量级,该条已挂 ERRATUM**。
方法层(spread 主产出、pre-anchor 单列、相关报离散)与 2019 切点仍然成立。

**两次自咬:** ① 第一版 `can_ratio` 只比 convention,GLD/TLT 判 True —— 两者
都是 price_return 而泄漏 40 vs 400,**差十倍**(同一个标签装两个状态,
正是这模块要修的形状)。② `abs(400-400)=0 → 上限 3968 年` 是假精确,
**估计值相等不是相等** ⇒ 差值下界 50bp。

**缺口是后缀,不是数据源:** 代码每处硬编码 `.US`,EODHD(已付费)的
`.INDX/.FOREX/.GBOND/.COMM` 从未用过。`scripts/probe_eodhd_index.py`
需 **Mac 侧跑**确认后才谈落库。
**其中 `USDJPY.FOREX` + `US10Y/JP10Y.GBOND` 正是 S-273 结论那份采购单** ——
两条独立的路走到同一个缺口。

## 2026-09-02 追加:S-273 / S-274 —— 一次证伪 + 一层跨资产读数

**S-273(证伪,本日最有价值的一条):** Jazz 的「传统三角套利今年失效」按**跑前写死的判据**
检验 ⇒ **不支持,且双向不支持**。历史窗口三对全不协整(所以谈不上失效),
唯一较强的反而在近期窗口。真正产出是**「测错了层」**:日元套息的收益来自
利率差与 swap points,不是 ETF 价格协整。Jazz 确认「那个层面在 fx 市场」。
⇒ **具体采购清单:美日利率差 / forward points / GOFO。三样一样都没有。**

**S-274(新层):** `src/data/market/cross_asset.py` —— 相对估值 / 相关性 / 历史分位,
核心产出是 `spread`(同一值在多窗口下分位的极差)而不是分位数本身。
实测 GLD/UUP:1y 43% vs 11y 95%,**52pp 的差纯粹来自窗口选择**。
Jazz 指出 2019 是新周期起点后,spread 0.52 → **0.033(robust)** ——
三个黄金比价对 2019 前是 **100.0%**,那段对当下零信息量。
⇒ **spread 大不一定是数据脏,也可能是切点没找对;后者是体制边界,是信息。**

读数(**不是信号**):黄金对债/日元/美元同时贴在体制内 ~93 分位,
债券对日元贴在 11 分位 —— 形状与「拿套息收益换黄金」一致,但无因、无基础率、
无 OOS,只作 S-271 `divergence()` 的输入,不进定仓。

## 历史条目(完整内容 → `PROJECT_STATE_LOG.md`)

S-251/S-259 价源现状 / S-261 Supabase 额度 / S-273-279 / S-288-295 / S-281-282 / S-276 / S-275 / S-274 全部已迁出。

11-04 晚:T-232 复核通过(簇首日 4 个与 state_daily 独立重算一致),合并入队;T-232 报告只报不判(簇<8)。

## 附:被挤出第一屏的旧头部状态(自 2026-11-06 轮次移入)

**更早:** 2026-11-04 05:10 UTC (Seth — **Entity / Decision 层今天落表(S-712;Jazz「按设计还缺什么矢量」→「今天开始」)。** 七个空间对账:Asset ✅(无原因维)· Regime ✅(`market_state_vectors`)· Strategy ❌ · **Entity / Decision 此前从未建表** · Text 有行无向量 · 时序窗口半 · Outcome 半 · ⓪ 层空。建了:`issuer_entities`(37 家,代码 `entity/issuers.ENTITIES` 为真源,全部 assumed;**T-230 lane-b 带出处核验**)+ `issuer_decisions`(只追加;回购 / 分红 / 摊薄稀释 ← 基本面按**披露日**;上下币 ← events;每周一 payout_class / token_dilution ← treatment_daily)← `_issuer_decisions_loop` 每 6 小时 → `GET /internal/entities?entity=`。下一步:每季一个「待遇向量」挂在 entity 上,CIS v2.1 从这里读。同日早些:S-711 ② 待遇倾斜前向账起跑、记分表首批结算(E53–56 全 ✅)、近邻臂向量取日修正。**在跑:** lane-a T-222 v3 · lane-b T-223 v2 / T-227 / T-230 · lane-c T-226 续 / T-228。**周一 11-09 第一封周信。**)
**更早:** 2026-11-04 03:20 UTC (Seth — **「继续升级策略」:② 换原因,前向账起跑。** ① **S-711 ② 小股东待遇倾斜前向账**(`treatment_tilt_daily` ← `_treatment_tilt_loop`,公用内核):面板等权 × 乘数(分利 ≥ 0.5 → 1.5 / 有收入不分 → 0.5 / 无协议收入 → 1.0),乘数取再平衡日前一天的 `treatment_daily`,周一再平衡,基准臂 panel_hold,**起点 11-04 收盘**;90 天后对随机乘数 1,000 次的 95 分位判。这是 ② 第 4 条路,第一条用 Jazz 的原因(慢变量)而不是动量 / 杠杆。② **记分表第一批结算了**:E53–56 全 ✅(Brier 0.03–0.09;BTC 77,454 落在 74–82k 带内、广度 0、dist_200 +5.9%、vol_pct_3y 5%)。③ 11-03 的 ③ 决定 01:49Z 发群(敞口 0%,DVOL 39.9 / 分位 41%);**近邻臂两天都空** —— d 的状态向量 d+1 08:00 才算出来,决定 02:00 发;改成取 ≤ d 最近 3 天内的向量并记下用了哪天(待推)。**在跑:** lane-a T-222 v3 · lane-b T-223 v2 / T-227 · lane-c T-226 续 / T-228。**周一 11-09 第一封周信。**)
