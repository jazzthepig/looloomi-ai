# PROJECT_STATE.md — the living single source of truth

**Last updated:** 2026-11-13 11:32 UTC (Seth — **Jazz 11-13:「这几周明显是空头机会,为什么没有布局 —— 指标有问题,规则也有问题」。量了,两样都是(S-844):** 宏观标签连续 102 天都是 TIGHTENING(63% 的日子都是偏空标签,不带时点);⓪ 周期向量只有一个分量、没接任何利率预期;趋势只有日线、只有 200 日线过零会动钱。规则侧:敞口下限是 0(11-12 的裁定只改了文档)、没有「低仓位」这一档、⓪ 只有 on / off / flat。**Jazz 已点头(「基本的没做对,很难放更多资金」,DECISIONS 已记):** T-370 ⓪ short 状态(Seth;上线两步都要 Jazz 在场)· T-369 利率预期进库进周期向量(Seth)· T-368 / S-845 加密腿「半仓」档的账户级检验(A 道,预注册已写)。周线标志这次 10-25 就亮(比 200 日线早两周半),但历史上亮灯后 4 周 BTC 平均仍 +1.7% ⇒ 单看它支持更早降档、不支持按规则开空 —— **但 Jazz 指出这是低维读法(要和宏观 cross reference),量了他是对的(S-844 补二):同一个周线标志,利率升且流动性在抽时之后 8 周 −0.9%,利率降且流动性在加时 +17.4%。** 决策要读「状态 + 历史相似状态」,不读单个标志;**边际流动性先行(S-844 补三,Jazz 写过很多次):这一次主动买盘占比 09-20 跌破 0.5、稳定币增量在见顶那周(10-04)归零、次周转负 —— 比周线早两周、比 200 日线早五周,库里每天都在量,没有任何决策读它;它过去只被当作单独的择时开关检验(S-508 / S-615 / S-673–674,单独都不过)就进了墓地。** 状态读法改成流动性第一栏、价格在后;**再叠减半相位(S-844 补四,Jazz:BTC 的硬支撑):减半后 18–30 个月是历史上最差的一段(之后 8 周 −8.3%),30–48 个月是筑底回升段(+17.2%;稳定币在抽时 26 周仍 +54%);今天是第 30.8 个月 ⇒ 9–10 月是空头窗口,今天对 BTC 开空已迟且站在硬支撑对面。** **维度对账(S-848):十族里八族库里已有序列、决策只读三四条;真缺 8 条(收益率与利率预期、ETF 净流入、美元指数、清算、Coinbase 溢价、解锁日历、美国以外流动性、日内状态)。没读的今天在说:MVRV 1.37(前两次底 0.69 / 0.78)、算力 30 日 −5.7%、高收益债利差 2.65 → 3.30 ⇒ 上一句「站在硬支撑对面」只用了日历,估值不同意 —— 两维打架本身就是状态。** **第一步已落地(S-848 补):③ 的档案加了背景栏 `inputs.context`(稳定币供应、主动买盘、借贷利率、MVRV、Puell、算力、信用利差、VIX、减半相位;带截至日、缺就不写、维度打架单列),只描述、不进规则;LLM 判断臂换成 v3。**真缺的 8 条先补了两条(S-848 补二):2 年期 / 10 年期 / 实际利率 / 联邦基金 / 广义美元走已有的 FRED 路径进 `macro_daily`(按可得日),背景栏读它们。** **第一批真实数据已到(S-848 补三):2 年期今年 3.47% → 4.73%(BTC 见顶那周 4.83%),联邦基金 9 月中到 10 月初 3.63% → 3.88%(加了 25bp,正在见顶前),2 年期仍高出联邦基金 85bp,美元 118.1 → 121.4 —— Jazz 说的加息风险,今天之前库里一行都没有。**⚠️ 第一行真实数据要等 11-14 02:00 UTC 那一轮,之前不算完。** A 道 T-368(只用周线的半仓档)❌:水下只短 9 天 —— 低维基线,如登记。 **C 道 T-372(S-847,流动性在抽时空山寨篮子、多 BTC)❌:条件管用(状态周 +0.03% / 周 对 非状态周 −0.65%),但等权篮子摊不掉尾巴(最差一周 −20.6%,单币一周 +147% 拖 7.4pp)⇒ 小币的空只能是人的判断加很小的仓位,T-370 的「默认走篮子」已作废。** 背景栏再加周线结构、期权偏斜、交易所流入(v1.1,9 条测试;用 10-04 见顶那周的读数复现了「价格好看、钱在走」当时就该被列出)。 小币没有这层支撑、但单币空票死在逼空与资金费上(S-840)⇒ S-847(C 道 T-372)❌:流动性在抽时空山寨篮子、多 BTC —— 条件有用(−0.65% → +0.03% / 周)但尾巴没摊掉(最差一周 −20.6%,一个币一周 +147% 拖 7.4pp)⇒ 小币的空没有任何机械形态过表,空单工具里只留「人选 + 很小仓位 + 每张硬止损」;T-369 的范围已扩大到把周线结构与利率写进市场状态向量和 ⓪ 简报。 **时间口径(S-846,Jazz「还有时间戳和时间的问题」):** ⓪ 判断到执行隔 19.6 小时(主机一天一轮);85 张日表里 29 张的 d 是写入日、55 张是已收盘日;动钱的表每小时覆盖、查不出首次写入时间;对人的日期本地与 UTC 混用。无时区时间戳列 0、未来日期行 0。→ T-371(Seth)。 此前:**S-835 这一轮判完:11 个候选没有第二个引擎。** 跨资产趋势(S-841 / T-364)是第一个真的不相关的(对账户 −0.03、对 R-v2 −0.08、真信号在随机符号的 97.5 分位),但十年年化 +2% 且只占账户风险 1.5% ⇒ 不准入;坟场八族(T-363)全不过;唯一活着的是 S-681 H4(靠前向纸面臂判)。**水下 750 天拆开(S-843):** 2021-12 一个月的 R-v2(−9)+ 2022 的两条 β 腿(加密 −7.2、股票 −7.2,R-v2 全年不在场)+ 2023 年 2–10 月的假突破成串;回来只用 72 天。**预注册并当场判了一条:股票腿 / 黄金腿按 10 月均线离场 ❌**(750 → 762 天,年化 −1.2pp;2022 省下的在 2023 反弹里还回去)。择时拿不掉这段水下(连同 S-659 等共三条路);它是突破引擎的成本。**实测有效的旋钮只剩 R-v2 的尺寸(归 Jazz)**;另有一处数据缺口:回放里 2021–2022 现金利率是 0。后端:MINIMAX_SYNC 75.8k → 23.6k(归档,T-348 / T-308 未结项已重提);**我的名片原型里的 `.trim()` 撞了合规词扫描,08:53 起挡住过 preflight,已改掉**;T-367(策略空间补账)未动;只读入口切换仍等 Jazz 的三把 token。)

**更早:** 2026-11-13 08:24 UTC (Seth — **前端:Otter AI 名片的 H5 原型(Jazz 11-13 四条裁定,DECISIONS 已记):只留 Otter 的名字、视觉重做;首批受众内地微信社群;微信里只放人和 AI、不放加密;先出可点的原型。** `docs/prototypes/otter-card/index.html`(单文件,未入库):名片 / 问 Otter / 群里的 Otter 三屏 + 交换名片(Otter 分诊)+ 转发卡。**对话是写死的示例,没有接模型、不发任何东西;只看过首屏截图,其余交互只过了语法检查。** **同日改向(Jazz):海獭只是他自己喜欢的 —— 每个人选一只自己的海洋生物当 AI 伙伴**;原型已加:八种可选(各带一句性格)、交换名片时选、名片墙按物种显示并计数;名片上的 Otter 改成厨师海獭(照 OutterDish 原图的气质重画)。旧 TG 频道最近三条是第三方广告,已提醒 Jazz 查管理员。下一步等 Jazz 看完定:接真模型、名片内容、小程序类目与审核。)

**更早:** 2026-11-13 07:04 UTC (Seth — **矢量库对账(S-842;Jazz「是否齐全」→「go fix,分给各条道」):四个空间在流且连续(市场态 2,539 天、时序窗口、文本 15,198 条、按币资金面 652 个币),三处有洞。** ① 策略空间:`book_vectors` 只有 4 本冻结旧账 —— 写入端没坏,是设计上要前向满 60 天(在跑的账 7–51 天,最早 11-22 前后自己进来);真洞是 X1V / RBv2 / R-v2 / 真钱目标表 / H4 臂不在登记表里,以及 `strategy_response` 没有写入端(→ Seth T-367)。② 资产空间:在更新的加密资产只有 24 个,R-v2 的票开在几百个永续上(→ B 道 T-366 先对账)。③ 结果空间:9 月以来 73 行实验记录没有台账编号 —— 坟场不在库里(→ B 道 T-365,每轮一个月;入库要 token,交 Jazz)。**已修:** `match_asset_embeddings` 只在同 schema、未停更的行里找近邻(迁移已应用;59 个目标的结果前后相同,停更的 14 行不再能当目标)。**我第一遍报的两条成因不对,已在台账改正**(「断了 99 天」「可能返回旧向量」)。小项未修:`regime_daily` 缺 29 天、发行方 37 家只核验 1 家(T-230 在分支上没合)。)

**更早:** 2026-11-13 06:24 UTC (Seth — **第二引擎的挖掘(S-835)到今天没有一个候选过准入;我 03:17 报的「反转规则 A 在 30 天上过表」是错的,撤回(台账「S-835 第二批 更正」):那个数丢了周末,B 道自己标了矛盾、合并轮 8 小时前已判作废。** 我用另一份数据(U 本位永续日线)从零重写了一遍(S-840,先登记后算):**规则 A ❌ 结案** —— 典型的一张票是赚的(中位 +12%、胜率 0.72),但被逼空的尾巴(TRB −211%)和资金费(每票均值 −4%)把均值吃光;计入资金费后 30 / 45 天两档贡献为负,三档无一过表。B 道修掉周末后的现货版(T-360 v3,不读我这份做的)同样三档无一准入 —— 两台引擎、两份数据结论一致。与 S-808 同一个结构,第三次量到:「暴涨之后典型地跌」是真的,「空它能赚钱」不是。**套息也 ❌(A 道 T-359 返工,06:14 UTC):** 与账户月收益相关 +0.51、压力月 +0.62 —— 费率高的月份就是加密在涨的月份,套息是顺周期的,是好的现金替代、不是第二个引擎。**到今天的准入表:** 规则 A ❌ · 套息 ❌ · 规则 B 尺寸不可行 · S-681 H4 三条过、第二个窗口不可得 ⇒ 靠前向纸面臂判(10-25 起在记)· 其余坟场族待 C 道 T-363 按「更正三」重报。**加密内部到今天找不到第二个引擎。** **下一个候选在加密之外(S-841 预注册,C 道 T-364):** 跨资产趋势(SPY / EEM / GLD / TLT / USO,可多可空)—— 买方说的「互不相关」通常指这一类,有上百年外部证据;我们只量它在**我们的账户旁边**是不是真的不相关。这是给机构产品规格(S-837)找来源,不进自有账户。判据自身两处毛病已记在 S-840(最差窗口里空仓的候选过不了严格的 (iii);压力月只有 13 个),交合并轮定,不在看过结果之后改。真钱没有任何变化。)

**更早:** 2026-11-13 05:09 UTC (Seth — **Jazz 11-13:数据访问不能匿名,必须登记或留痕(S-838,DECISIONS 已记)。** 现状:匿名可读对象 149 个(lane 共用一把公开 key)。已建只读入口 `/lane/rest/v1/<对象>`(`routers/lane_read.py`):一人一把 token、只放行 147 个研究对象、只有 GET / HEAD、每次读写一行 `data_access_log`;lane 的脚本不用改,只换地址与 key。**⚠️ 三步没走完,匿名读现在仍开着:** ① Jazz 生成三把 token → Railway `LANE_READ_TOKENS` + 各 lane 的环境;② 观察一天(日志表里三条 lane 都有行、边缘日志无匿名 GET);③ 迁移删掉全部 `to anon` 策略(含 `webhook_subscriptions`、`weekly_letters` 这两样本来就不该匿名可读的)。其余:两份规格(S-837)、第二引擎候选 H4 与反转规则 A(S-835)、账户内核进 src(S-836)。 **2026-11-13 05:09 UTC 补:⓪ 第一条人的判断落库(S-839)—— Jazz 11-13 05:08 UTC:off,14 天(到 11-27),理由「一年下行里的反弹失败,看不到支撑」;没签名不碍事(off 是少做的方向,主机照办)。闸门若在 11-27 前重开,R-v2 仍不开新票,这条判断按挡掉的票记分。** )

**更早:** 2026-11-13 03:17 UTC (Seth — **Jazz 11-13 裁定:两份规格(S-837,DECISIONS 已记)。自有账户 = S-831(先投机);机构产品 = 多来源、互不相关、单一来源风险占比有上限(Seth 提的线 40% ⇒ 今天的账本上 R-v2 每票 0.25%:年化 +21%、波动 20%、有效来源 3.4)。** 第二引擎的挖掘在跑(S-835):坟场里只有 S-681 H4 过准入(与 R-v2 负相关,前向纸面臂 10-25 起在记);套息(A 道 T-359)与反转(B 道 T-360)待出数。匿名可读查清:120 张表是设计好的只读(lane 用),账户 / 权重 / ⓪ / CIS / 前向净值读不到;前端不带 key ⇒ 不改,控制点是 key 给谁。⓪:Jazz 回了「ok」,状态与期限还没给。过夜工程(S-836):账户内核进 src、asset_mcap_daily 索引、读价缓存只留了设计卡 T-362。 **2026-11-13 03:17 UTC 补:** B 道 T-360 出数 —— 反转规则 A(山寨暴涨后相对 BTC 做空)在 30 天持有期上过了准入(账户年化 +12.5pp、p 0.005、账户最差的 20 天里它 +3%),但 7 天与 90 天不过 ⇒ 对持有期敏感,要补邻点(20 / 45 天)与独立重写才谈影子臂。A 道 T-359(套息)又一次上下文溢出,未出数。)

**更早:** 2026-11-12 17:14 UTC (Seth — **分散度体检(S-834;Jazz 11-13 转述买方前上司:多来源、互不相关、扛得住高波动):来源之间确实不相关,市场崩也扛得住(① 月均 −21% 的那些月账户 −1.3%),但风险压在一个引擎上 —— R-v2 占账户波动 74%、收益 64%,有效来源数 2.0;账户最差 20 日 −19.4% 里 −14.8% 是 R-v2 自己的假突破成串(2023-02)。** 尺寸与集中度是同一个旋钮:每票 0.25% → 有效来源 3.4、年化 +21%、波动 20%;现在的 0.75%(S-831)→ 2.0、+35.7%、36.7%。**⚠️ 要 Jazz 定:自有账户与机构产品是不是两份规格**(自有:现在的 B;产品:单一来源风险占比设上限)。**往下挖(S-835,准入标准已登记):不找对冲,找第二、第三个与 R-v2 不同步的引擎 —— A 道 T-359 套息、B 道 T-360 反转、C 道 T-361 坟场准入表。** 10-07 的触发条件 11-11 已成立,⓪ 判断仍等 Jazz。 **2026-11-12 16:58 UTC 补(过夜工程升级,S-836):** ① `evaluation/ticket_account.py` —— 账户内核进 src,带不变量与 5 条测试,与 B 道修后引擎三个配置逐日对账差 $0;② `asset_mcap_daily` 补 `(source, coin_id, d)` 索引(之前 4.3 万次查询每次顺序扫 76 万行);③ 权限查过:212 / 213 张表开着行级安全,无匿名可写;两处匿名可读的姿态留给 Jazz 定;④ 读价缓存(数据库最大的一块负载)只写了设计卡 T-362,没动手 —— 真钱也在用的入口不在无人值守时改。S-835 三张卡:A 道 T-359 脚本已推、数未跑出;B / C 在跑。 **2026-11-12 16:59 UTC 补:S-835 第一批(C 道 T-361):坟场 8 族里只有 S-681 H4(熊市反弹失败做空)过了准入 —— 与 R-v2 负相关(−0.21),把账户最差 20 日从 −19.4% 拉到 −8.0%,p 0.002;折扣:两个窗口其实是同一段、改善多半来自 2022。其余做空族压力月与账户同涨同跌(+0.56 至 +0.87),World50 是加重集中。H4 的前向纸面臂 10-25 起已在记。**  **2026-11-12 17:14 UTC 补:** B 道 T-360(反转)部分交付,并指出 S-835 的 (ii) 写漏了统计量(整体平移下「自己的总收益」不变,p 恒为 1)—— 已定为对齐型(账户年化之差),H4 的结果本来就是按这个算的,不变。规则 B 已是窗口依赖;规则 A 与 A 道的套息(T-359)下一轮出数。)

**更早:** 2026-11-12 06:38 UTC (Seth — **高维回看(11-12):10-07 写下的触发条件成立 —— 11-11 收盘面板 dist_200 < 0 且 breadth_ma50 = 0,BTC 74,015;当时的 S3(反弹失败,权重 35%)兑现。按那次的约定:Jazz 带理由与期限决定 ⓪,决定先落库。** 规则已经把加密敞口降到零(X1V 空仓、R-v2 闸门 11-10 关),真钱 1.0025 对 ① 0.886。下一段三个情境与五条可结算命题在 `scenarios/seth-review-{today}.json`(本底:闸门关闭 20 次里 14 次不到 10 天收回;撑过 10 天的 6 段里 2 段真熊)。**日报的两条红旗查过,都不是故障:** 三个「新报错」的循环是 11-11 07:08 UTC 同一次 Supabase 断路(30 秒),之后都正常;`agent_call_log` 24 小时 0 行 = 托管 /mcp 没有外部流量(挂载正常;本机连接器的调用本来就不进这张表;全表只有 2 行)。日报的提示词该改:这张表不判活,循环只在「最近一次是 error」时才算报错。)

**更早:** 2026-11-12 05:39 UTC (Seth — **真钱偏离 S-831(Jazz 11-12「you can make your call」):R-v2 改成 名额 10 / 名义上限 80% / 每票风险 0.75%**(S-829 的 B 格;11-13 起进场的票生效;只改 Railway 出计划的一侧,主机不用更新;加密总敞口上限 0.9 不动)。依据:修掉幽灵仓的两台独立引擎 × 两份独立票源,回放 +26.4% → +35.6% / 年、最长水下 762 → 750 天、回撤 −28.0% → −31.4%、去掉最大一张票仍 +22%。**不放心的三处写在台账里:全是回放(生产内核至今 0 张票)、没有保证金 / 强平、本周模拟器错过三次。** 退出条件:强平或追保 / 20 张票后比旧尺寸差 > 2% 净值 / 连续 5 个开票日被拒单 / Jazz 说停;每月新旧尺寸并排记账。**⚠️ Jazz:Railway 里若设过 `R_V2_GROSS_CAP_FRAC` / `R_V2_RISK_FRAC`,会盖过新默认值。** 其余他交给我定的:Binance 历史归档(含下架币)下载 = 做,走 T-354;定时任务 = 我的决定是开「高维回看」与「外部探针」、合并轮不再加开,**但这里开不了**:五个任务已迁到云端,本机只剩停用的副本(我 11-12 重写的两份提示词写在本机副本上,云端那份可能还是旧的)—— 要 Jazz 在侧栏 Scheduled 里操作。投机仓子账户地址仍等他。 **2026-11-12 05:07 UTC 补:** Jazz:子账户还开不了(交易量不够)⇒ 投机仓记分账搁着。**T-354 交付:Binance 归档现货日线含下架交易对已落研究目录(532 对、304 个之后下架;库里同窗口只有 75 个符号)。** R-v2 要 220 根预热 ⇒ 2017 山寨季在 Binance 上本来就测不了,S-832 改问 2018-03 → 2020-07(A 道 T-357)。主机对保证金不足的处理核过:按可用余额截断或记错跳过,不会重试风暴。S-831 是否生效要等主机下一轮(约 09:15 UTC)。 **2026-11-12 05:35 UTC 补:** **S-832 ❌(A 道 T-357):含下架币之后,2018-03 → 2020-07 仍只有 1 张 R ≥ 10 的票(BTC 2019-04);2018 整年闸门关着 0 张进场。** 右尾出在趋势年,不是每个阶段都有;对 S-831 没有新增不利或有利证据。幸存者偏差在这条规则上不大(票没开在后来下架的币上)。MINIMAX_SYNC 已归档。 **2026-11-12 05:39 UTC 补:** **S-833:生产 R-v2 内核 0 张票的成因查清 —— 内核是好的**(在必定回滚的块里重放:09-25 → 10-15 出 27 张,10-20 → 11-10 出 HOT 一张),11-05 换源之后没有新信号,**majors 闸门 11-10 起关着 ⇒ 新尺寸在闸门重开前不会有任何真钱动作**。)

**更早:** 2026-11-12 00:53 UTC (Seth — **⚠️ 等 Jazz 拍板:R-v2 三个真钱参数(S-829;两台独立引擎逐格一致,差 ≤ 0.6pp)。** 引擎修好之后:现配置(名额 14、上限 40%、每票 0.5%)回放 **+26.4% / 年**(不带 R-v2 +12.1%),最长水下 762 天,回撤 −28.0%,去掉最大一张票仍有 +17.6% —— R-v2 是真的在出钱。**三个参数都有余地:** A. 只把每票风险开到 0.75% → +31.5%,回撤不变;B. 上限 40% → 80% + 每票 0.75% + 名额 14 → 10 → +35.6%,回撤 −31.4%(四周的格都站住);C. 同 B 每票 1.0% → +39.6%,回撤 −37.8%。40% 上限现在是咬合的(上限不动只开每票风险到 1.0% 会掉回 +26%);名额 10 不比 14 差。**他定之前不动任何真钱参数。** 生产核对了:`r_tickets_scan` 先成交再查止损,没有幽灵仓。T-352(B 修引擎)、T-353(A 第二台引擎)已交;S-815 / S-817 / S-825 的旧数作废,以 S-829 为准。其余:做空一侧收了(均线定义的「趋势明显」≈ 0);S-827 量不了(库里没有下架币,T-354 入库);T-348 第三轮(长账本)未完。 **2026-11-12 00:06 UTC 补:** 逐年看,B / C 每年都不输现状,A(只开每票风险)在 2024、2026 输 ⇒ A 最不稳。**生产内核 `r_tickets_paper` 至今 0 张票(回路活着)—— R-v2 的证据全是回放。** 票源只有一份实现 ⇒ A 道 T-355(照生产 SQL 从零重写,逐张对);C 道 T-348 第三轮按新 C0 重出。 **2026-11-12 00:31 UTC 补:** C 道 T-348 第三轮 —— 新 C0 上坟场里只有 **S-681 H4(熊市反弹失败做空)** 在账户口径上改善(年化 +4.9pp、最长水下 763 → 422 天),只有一个窗口、没过零分布,第四轮补长账本与零分布。A 道 T-355(票源第二份)票面结构对上(956 / 908 / 48 / 575 / 333),逐张对账卡在它自己引擎的不变量上,退回。 **2026-11-12 00:53 UTC 补:** **S-830 结果:票源第二份对上(956 / 956,照生产 SQL 从零重写)** ⇒ S-829 的票与记账各有两份独立实现,共用的只剩数据与这条五年路径。T-352 的合并在排队(前两次分别卡在情景文件格式与状态头日期,都已修)。另一个 Seth 窗口在跑评审轮(§Seth-1112f)。)

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

6. **🟡 收益层级 ② 在 ① 真实持有方式上只剩一个候选,而且族内不显著(S-803,11-10;Jazz「keep open」)。** 等权面板上的 ② 结论大半是规模效应:S-428 对等权 +3.6%/年,叠在 ① 的市值加权底上 −1.06%/年(p 0.60);P 在 ① 里也输(S-802)。市值底上过了回测的只有 **S-640**(BTC / ETH 钉住、山寨里少配资金费拥挤的名字;全程 +22.7pp、留出 +0.8pp,族内第 4 次 ⇒ 不显著),**前向 10-26 起,最早 12-25 判**。β+ 两本账的基准已改成 ① 本身(11-10)。S-804(韩国溢价,原因类)在市值底上 ❌(留出 −0.58pp、打乱分位 0.755)⇒ **原因类是必要条件、不是充分条件**。
   VERIFY: `grep -n "^### S-803 结果\|^### S-640 结果" REFUTATION_LEDGER.md`;S-640 前向:`select max(d), count(*) from cis_tilt_daily where arm = 'fund_a1_u'`(10-26 起;对照 `cis_a1_u` / ①)。
   OWNER: Seth(② 候选一律在市值底、S-640 同一框架上测)· Jazz(11-10:② keep open)

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

- **⏰ 11-22(S-818):开三张情景交叉结算卡**(A 结 B 的 manual 命题、B 结 C 的、C 结 A 与 Seth 的)。先查 `scenario_ledger` 里 `variable = 'manual' and horizon_d < current_date` 且未结的;格式与纪律见 `docs/research/scenarios/settlements/README.md`。第一条 `code_ref` 含 manual 的 `scenario_scores` 行落地之前,S-818 不算完。
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
