# PROJECT_STATE.md — the living single source of truth

**Last updated:** 2026-10-25 13:48 UTC (Seth — **13:48 做空研究(Jazz「认真研究一下做空策略」;台账 S-680 → S-682)**:做空坟场 12 条的共同死因 = 正漂移 + 没有硬止损的轧空 + 跌完才空。新起 S-681 一套:四个有原因的做空假设、同一模拟器(`docs/research/short_lab_common.py`:次日开盘进、硬止损含跳空、真实资金费记给空头、R 单位、同日随机空对照、2024 起留出)、Binance 永续**全部**合约含已下架 890 个日线 + 891 个资金费(数据根 research/s681/)。**H1 新币做空(Seth)不过**:单腿空新币 +0.05R / +0.06R(两段都不显著),但**相对**老币两段都稳(对照分位 1.00 / 0.996);对冲版(空新币 + 多 BTC)+0.26R / +0.155R、七年里没有一年为负 ⇒ S-682 拿 2017–2020 现货上市判:+0.07R、p 0.32,ICO 狂热季反向 ⇒ **是 2020 年后低流通高估值发币模式的现象,不是规律**。S-680 广度塌了空山寨也不过(19 次 −0.68R,和随机日一样)。H2 暴涨回落 + 硬止损(C 道 T-194)、H3 资金费拥挤(B 道 T-195)、H4 熊市反弹失败(A 道 T-196)等内核推上去后开。** **S-680 ❌:山寨广度两天塌 30 点后空山寨篮子,和随便哪天空一样(H=5 样本内 −0.68%,零分布分位 0.52);不开纸面前向臂。** 此前 10-23 17:00 UTC:Seth — **17:00 夜班(Jazz「我准备睡了,做个长任务挖掘价值吧」)**:① **R-v2 样本外(S-677 / S-678,Binance 全部现货对含已下架,2018-01 → 2020-02)**:只看 USDT 对 26 张(只报);加上 BTC 计价对 40 张 +0.10R、p 0.32 ⇒ **按预注册不过** —— 那段没有山寨季,带着它几乎不亏(f 0.5% 资金曲线最深 −7.7%),但「两个时代的证据」不成立 ⇒ 真钱停在 L = 1。A 道 T-189 独立复现 26 / 26 逐张一致(已合并 9ab44d26)。探索性:平均 R 上「突破选币」≈「同月随便挑一个流动性够的币 + 同样止损出场」(样本内 +0.49 vs +0.48R),突破买的是右尾(≥ 10R 的票 1.9% vs 0.86%)—— 钱来自闸门 + 出场管理 + 每月票数;HL「不替补」规则受挑战但不改。② **S-679 快回场(Seth 份 G1 NASDAQ 1971–2014 + G2 Binance 37 币)两个变体都不过**;但 **X1V 本身在没看过的数据上复现**:NASDAQ 1971–2014 年化 10.6% / −32%(持有 9.3% / −78%),37 个山寨回撤中位 −40% vs −74%。A 道 T-190 做三组独立复现。③ 崩盘图谱跨市场汇总第 1 版(数据根 _reports/absorb_input/S-675_crash_atlas_synthesis.md):崩之前最一致的是「没有迹象」,过线的非同源线索只有 NASDAQ「曲线解除倒挂」;现在只亮 NASDAQ P5 与加密 C4(稳定币收缩 —— 从不出现在顶之前)。C 道 T-187 返工在跑。④ **③ 的 0–1 并行臂上线(d18441b5)**:mult_v2_c1 / tom_pd10,规则不变、上限 1.3 → 1.0,10-23 收盘起前向,旧臂照跑。⑤ B 道 T-188 金 / 股腿场所:PAXG / XAUT 深(±1% $3.9–6.0M)、香港不在禁止名单;xStocks 股票代币 ±1% 只有 $0.17–0.34M;HL 现货没有金 / 股 —— 待挪走第三方条款原文后合并。模型额度 16:56 起停 60 分钟。** **15:15 高维复盘 + 计划(Jazz「back to high dimension and plan ahead」;全文 WEEKLY_REVIEW 2026-10-23,私有)**:交易核已定、有证据(X1V 在 BTC 2015–2026 回撤 −38.7% vs 持有 −83.6%,样本外 12/12),缺的是真钱与时间 —— 系统里 0 美元、外部 agent 调用 0 次、现行前向时钟大多 6–28 天。2023 → 2026 回放 BTC 持有(51.7% / −53%)跑赢我们造的每一样;② 只动 ±2pp,③ 动回撤。10-22 广度 0.58 → 0.125、稳定币 30 天 −1.52%、波动分位 0.03:S2「任两条」已认出;mult_v2 = 1.3(压缩极点满杠杆,且违反 0–1)。**主线 = 真钱上线 + 不再撕时钟**:Jazz 四件(新钱包隔开手动交易、Railway 轮换、三条关停线默认 −18% / 1.4pp / 30 票、时钟政策一句话);Seth:③ 开 0–1 并行臂、真钱周报;研究:崩盘图谱 → 跨市场线索 → ③ 前向臂、R-v2 样本外(先补 2017–2019 山寨日线)、T-188(B)金 / 股腿的链上场所;T-074 10-25 收卡。** **14:44 子账户开不了(Jazz:HL 要累计成交 ≥ $100k,文档核过)⇒ 改用另一个钱包隔开**:手动交易挪到新钱包(HL 内部转账,新账户 1 USDC 开户费),现在的账户 + 主机上已有的 API 钱包整个留给执行器 —— 不换钥匙、不改 env、不改代码;子账户那套等成交量到了再用(TRADE_PATH §3g)。** **14:27 执行器可以挪到子账户(5bde5f82)**:Jazz 在主账户上手动交易,执行器把整个主账户当成自己的 —— R-v2 空跑读到的永续净值 10-20 → 10-22 是 204 → 113 → 60 美元(在跟着手动交易动),上 live 会按它定每票风险,同一个币上 Jazz 平掉的仓位会被记成「交易所上已平」。新增可选 `HL_SUBACCOUNT_ADDRESS`:读余额 / 仓位 / 成交全在子账户,下单带 vaultAddress(同一把 API 钱包私钥替子账户签名,HL 文档允许);子账户不在主账户名下 ⇒ 不启动;不设照旧。**Jazz 的动作:HL 网页开子账户、划 ≥ 600 USDC 进它的永续 → 主机加 env 跑 install.sh → 空跑对上后改 live**(docs/TRADE_PATH.md §3g)。R-v2 前向账本 10-19 起 0 张票(规则没触发,不是坏了:扫描每天 ok、new_pending 0)。**S-676 前向预注册**(Jazz「sure」):每次美联储 / 日本央行加息之后 60 天 BTC 减半仓;凑满 6 件(只算 10-23 之后公告的、窗口不重叠)判一次,事件由 Seth 议息后 7 天内追加到台账。另一会话在收崩盘图谱 T-184–T-187。** **13:01 崩盘图谱开工(Jazz「给每个市场崩盘(主流、EM、crypto)前的事件、迹象和情绪,还有对应的策略风格,做个挖掘」)**:协议台账 S-675(写于把任何迹象与崩盘放在一起看之前)+ 补记(卡号、取数地址);**挖掘不是检验** —— 每个迹象对基准率、循环平移零分布,「线索」(分位 ≥ 0.95、提升 ≥ 1.5、锚点 ≥ 6、前后两半都亮)只进候选,要用另立预注册按前向判。共用内核 `docs/research/crash_atlas_common.py`(熊市两态机 —— 「回到历史新高才算结束」会把 2007–09 吞进 2000 那段;急跌去簇;按时点分位;发布滞后写死;9 个测试在 preflight,68a8cc1c)。FRED 快照 25 条在数据根 research/crash_atlas/fred/。卡:A = T-185 主流(NASDAQ 1971 起,14 个新一轮顶)· B = T-186 EM(EEM 2015 起锚点不足 ⇒ 主力是 1981 起的 EM 货币危机)· C = T-187 加密(BTC 2014 起)。数据缺口:EM 股票 2015 年前没有、ICE 高收益 / EM 利差 FRED 只给 3 年、Stooq 有机器人校验不用。MINIMAX_SYNC 归档到 36k。** **09:49 S-674 ❌(Jazz:边际流动性是「关键事件之后的一段效应」,S-673 的稳定币代理不算数)**:美联储加息 + 日本央行加息 22 件,之后 20 天 BTC 平均 −2.5% vs 同年随机 −1.0%(分位 0.32;2024 以后 6 件反而略好于随机);降息 + 加密准入 13 件之后反而更差(−4.7% vs +3.2%,主要是 2019–2020)。只报项里 60 天收紧组 −13% vs −1.8%(分位 0.02,窗口重叠 + 多期限挑出)⇒ 要另立预注册按前向判。最近一次收紧(2026-09-16 / 09-18)之后 20 天 BTC +11.6%。** **09:40 09:40 S-673 ❌(Jazz「边际流动性变差还能现价开空吗,去验证」)**:按 S-570 的边际流动性定时、变差时空 BTC 永续,2020-03 → 2026-10 年化 −28.5%(两段都负),与同空仓比例的随机定时分不开(分位 0.44);赚钱只在 BTC 下跌的年份(2022 +29%、2026 至今 +21%)⇒ 量的是大盘方向,不是流动性的定时能力。边际流动性此刻确实在变差(USDT + USDC 30 日 −1.5%)。** **19:27 19:27 夜班收尾**:T-179 ✅ 按申报股数 |52 周变化| > 5% 的 18 / 125 家全是真的公司行为(16 家 SEC 封面逐位对上;CMCSA 是 wavg 口径、WELL 是一年持续增发),顺带抓到 CoinGecko 那一路按 symbol 定类、T(Threshold)撞 AT&T ⇒ 69 行币价标成 Equity —— 已改数据 + 写入端守卫。T-180:H1 / ISSUE 按申报股数重跑结论不变,旧版「反向」就是股东收益率(缺口在零分红股上精确为 0)。T-182:S-625 挪一天不垮(p 0.0002)—— 叙事族历史证据保留(票集是 R-v2 的 813 张,不是逐位复现)。v2 个股输入一周只留一行(world50 同一周留着 2–3 行,26 周波动里混了日收益)。T-089 改 blocked(那两张表开不开读权限是 Jazz 的)。T-183:v2 加密供给维照旧(三种写法排名相关 ≥ 0.97);S-665 前向改用两端 7 日中位数(单日端点挪一天 4.4% 换档 vs 0.57%;尖刺是 CoinGecko 市值与价格当日快照错位)。三道今晚交 10 张卡,全部复核合并;空闲等新问题,不硬派。** **18:21 股数已填**:world50 周更 18:19 跑完(市值 141/141,v21),`shares` 80,898 行;按申报股数的 52 周变化 VZ −1.5% / MO −0.6% / CMCSA −4.2%(旧推法 −7.6 / −6.9 / −14.8)。CRM −13.6、TTE −8.0、TSLA +22.4 等交 A 道 T-179 逐家核;C 道 T-180 按申报股数重跑 H1 / ISSUE。**S-665 稳健性 ❌(T-178 + Seth 复跑):中位数切半的 ① 只在信号日当天成立,测量日挪 1 / 2 / 3 / 7 天 p 全 ≥ 0.31** —— 形式上的过不当证据;稳的只有「一季度稀释 > 2.2%」那一档(每个挪法平均 R 0.24–0.31 vs 0.64–0.69),但门槛事后定 ⇒ 前向假设。新常规:信号日当天的派生量挪一天再判(lane prompt 已写)。S-672 ❌(B 道 T-177,另一会话收)、S-597 加密篮子 L / LC 都不胜等权(A 道 T-181)、t155 判定不变(T-176)。B 道新卡 T-182:S-625 复现 + 挪一天。** **16:59 夜班(Jazz「做点长任务和分配给 minimax 们」):个股股数口径修了** —— CIS v2 个股的「供给纪律」与 CIS 页公开的「股数 52 周变化」原来是 市值 ÷ ohlcv_daily 收盘,而那个收盘是**总回报复权**的 ⇒ 股息 / 分拆被算成回购(VZ 每个除息日 −1.6%、CMCSA 分拆那周 −6%;10-21 有 40 / 125 家 > 5%)。`world50_mcap_weekly.shares` 新列 + 内核直接读股数(09782b4e,线上 d325e680);错数已不再对外展示,shares 由部署后 75 分钟的 world50 周更整段填上(PART_VERSIONS mcap 21)。**S-668 H1 的供给纪律、S-670 的 ISSUE 量的其实是股东收益率 —— 台账已更正,T-180 按申报股数重跑。**S-671 ❌(A 道 T-175):按时点的前 50 池子上 SMALL 发现段就没过(IC −0.015,Seth SQL 复算 −0.012),S-670 的 SMALL 是幸存者偏差。T-093 第 3 轮收卡(0 / 3)、T-026 收卡(fusion 已冻结)。第二波卡:B = T-177(S-672 v2 慢维度合成 vs R-v2 票,已预注册)· C = T-178(S-665 独立复算)· A = T-181(S-597 加密篮子小脚本重写,取代 T-117);T-179 / T-180 等 shares 列。ed5f0d94 在 Railway 构建失败一次(平台偶发,本地 boot smoke 通过;下一推 44 秒上线)。另一个 Seth 会话在并行收 T-174(§Seth-1022g / h 对过账)。** **10:25 Railway 恢复构建(~06:14 上线 9102de73),积压全部上线、各循环 ok;轮换按 RAILWAY_ROTATION_RUNBOOK 交 Jazz 做。CIS v2 判定:加密 H2 ❌(山寨内倾斜分位 69 < 80;但 IC 0.156 vs v1 0.110、换档 0.45 vs 2.55 次 / 30 天)、个股 H1 ❌(合成与之后 4 周反向,IC −0.075);**Jazz 裁定:加密影子满 20 天即切 v2(产品理由,评级=描述,② 不用);125 家公司进 CIS 页面只给状态与事实、不给档位**。状态层 + 加密影子档位 + `GET /api/v1/cis/v2` + CIS 页 v2 面板已排队上线;S-670(C 道 T-172)找个股信号、T-173(B 道)复核 S-634 的翻页问题。** **05:40 CIS v2(Jazz「先升级 CIS」:拆两层、只扩传统资产不加币、影子过了再切;「abc 要多协同」)**:分数只留慢维度(规模 / 稳定 / 供给纪律,加密另加 v1 的 F / O),动量 / 情绪 / 热度改「状态」只描述(S-668 / S-669 预注册,`docs/CIS_V2_SPEC.md`)。同一个「供给纪律」跨两类:币的流通量增长 = 公司的净增发。内核 `cis/v2.py`(研究与影子共用)+ 影子 `cis_v2_daily`(表已建,写入端等 Railway 部署);真数据干跑:加密 25 / 个股 125 全有分(STRK 90 日稀释 12.5% 垫底,PANW / INTC / CVX 发股收购排后)。**三道并行:A = T-169 个股 H1、B = T-170 加密 H2(在跑)、C = T-171 状态层 —— 已交并收(S-669:趋势标签能展示,动量 / 拥挤只给数值;没有标签过置换 ⇒ 写「描述,不是预测」)**;数据缺口:SKY 无资金费、DELL / MS 无 eodhd 价、world50 三个市值口径并存(v2 只读 v3);积压 6 张已交卡收口(内容早在 main),T-166 / T-092 合并。**02:10 Railway 平台被入侵** —— **02:10 Railway 平台被入侵(10-21 07:24 起暂停全平台构建,环境变量部分被解密拿走)⇒ 线上停在 27d52ba0,积压的提交(⓪ 开关、真相之书、协议收入、票据标签、简报)都没上线**;Supabase 日志里我们那把 secret 只来自 Railway 的 IP、无外部直连,未见盗用。应对:**主机不信上游**(TRADE_PATH §3f,`exec_host/verify`)—— R-v2 进场票主机用 HL 公开日线重算(S-666 ❌:伪造票只过 6%,真票只过 78%、全栽在 HL 成交额闸 ⇒ 默认 report;S-667 前向判 V′),J 票与信心倍数要 Jazz 在 Mac 上的签名(始终强制;`regime_calls.signed/sig` 已上库),每票风险主机守 2%;币安 1000 前缀对上 HL k 币。轮换清单 `docs/RAILWAY_ROTATION_RUNBOOK.md`(构建恢复后一次做完;GITHUB_TOKEN / 推理 key / Resend 现在就作废)。另:R-v2 前向账本自 10-20 起 0 张票(BTC / HYPE 都在 40 日高点之下)—— 现在能动的只有 ⓪。**00:20 安全:探针报 `CRITICAL:anon-read-cis_scores`** —— **00:20 安全:探针报 `CRITICAL:anon-read-cis_scores`** —— 10-20 的 lane_read 把 cis_scores 放进了 anon 可读,而 legacy anon JWT 还在生效 ⇒ 已收回该 policy(00:06),探针转绿;**legacy key 从没真停用 → Jazz 00:30 停用 + 00:34 吊销 legacy JWT secret,均已验(OPEN RISK #0d ✅)**;Mac `active_monitor` 自轮换起 7 个 canary 全 401(SYNC #38)。**17:17 夜间价值挖掘(Jazz「做点长任务做价值挖掘」):** 新数据维度 = DeFiLlama 协议收入 / 持币人收入。**S-661** 价值捕获比(持币人收入 ÷ 收入)留出段 IC +0.086、t 3.45 ✅,收入动量 ❌、收入收益率(便宜)反向 ❌(S-662);**S-664** 控制规模 / 波动 / 稀释后留出段只剩 +0.018 ❌ ⇒ 价值捕获比是质量因子的另一种读法,**最强的单变量是「不稀释」(IC +0.119、t 4.05)**;**S-665 ✅** R-v2 的票开在高稀释币上(一季度流通量涨 > 2.2%)平均 +0.28R vs 其余 +0.57 / +0.76R(低 − 高 +0.54R,p 0.022,两段同号)⇒ `r_ticket_tags` 前向打标签(不进执行);C 道 **S-663** 链级稳定币流入 ❌(无信号过发现段)。建了 `protocol_revenue_daily`(DeFiLlama 概览两次请求,01:20 UTC)+ 战场简报加价值捕获比列(描述,不是信号)。复核并排队合并:T-164 v2 / S-655 ❌(−24R)、T-165 / S-656 ❌(p 0.166)、T-167 / S-660 ❌、T-168 / S-663 ❌。Railway 仍停构建(prod 27d52ba0)。 ‖ **14:47 Jazz ⓪ 开关(Jazz「回到高维 … 开始」):** 人给判断(on / off / flat、信心 1–3、战场币、离场币、14 天到期),执行器按规则管票,每次判断记分。`regime_calls` / `j_tickets` / `j_tickets_state` 已建(migration 已应用);`execution/regime_call`:计划叠加(off/flat 挡新票、flat 全平、信心 × 风险,读不到判断 ⇒ 不开不平)+ J 票(HL 日线、R-v2 同一套管理,SMA20 离场在第一次站上 SMA20 后才生效)+ 记分卡;`POST/GET /internal/regime-call`、`scripts/regime_call.py`;主机守 2 倍风险上限。排队 1500;Railway 构建恢复后生效,主机要再跑一次 install.sh。C 道 T-167 / S-660(全市场 OI 流入 + 主动买盘广度)❌ 7.9 分位 ⇒ 免费数据上的系统化「何时在场」两条都不过,人的 ⓪ 是现在唯一的候选,记分卡就是它的检验。 ‖ **13:40 Jazz「继续提高策略,钱不急」—— 三条都不过:** S-657 R-v2 原样用到 143 个 HL 独有永续(HYPE / WLD / TAO …)只出 11 张、平均 −0.45R ⇒ 宽度不是答案,不建写入端;S-658 第二段臂(+100% 第一段 → 回撤 20–50% → 放量再突破)629 张 +0.57R、两段都正、去顶 5 张 +0.40R,但同币同月随便哪天进就有 +0.475R(89 分位,p 0.112)、与 R-v2 月度相关 0.71;HYPE 2025 两张第二段票都亏;S-659 按 R-v2 最近 20 张战绩调仓 ⇒ 循环平移 67 分位,窗口一换就反。**结论:钱在「山寨走趋势的月份」,不在进场形态** ⇒ 派 C 道 T-167 / S-660 全市场「谁在买」状态(OI 流入 + 主动买盘广度)。 ‖ **13:15 主机已更新(Jazz 13:03 跑 install.sh):** 新代码在跑(心跳带 truth_pending),R-v2 第一轮空跑 asof 10-20 ✅(前向账本 0 张票 ⇒ 无进出);**永续账户只有 $204.06** ⇒ 每票风险 $1.02,按历史 770 张票的止损宽度(中位 17%)**96% 的票名义额 < HL 最低 $10、不可执行**;$704 全进永续 ⇒ 99.9% 可执行。真钱前把余下 USDC 从现货划到永续(Jazz)。Railway 构建仍暂停,真相之书接口未上线(404 = 旧版本,预期内)。 ‖ **12:30 ⚠️ Railway 全平台故障,07:24 UTC 起构建暂停**(status.railway.com「builds paused」):prod 仍是 27d52ba0、运行正常;此后 12 次推送都没部署(seth_bot「900s 没等到」全是这个原因,不是我们的代码)。8408eb22(真相之书)等构建恢复自动上线;主机那一半不依赖 Railway,install.sh 照常可跑。 ‖ **11:45 Trader Tom 重学 → 应用(Jazz「深度学习 trader tom 再研究开发应用」):** S-654 ❌ 对了才加(半仓进 + +1R / +2R 各加半个单位、各带止损):770 张票总盈亏 372 → 273 B、回撤 −56 → −45 —— 加仓单位每个 +0.33R < 新票 +0.48R,R-v2 的边在突破进场那一刻;「不收部分利润、机械拿住赢家」这一半系统本来就有(S-612)。doctrine §11 写下书里的动作 vs 我们的数据。**应用 = 真相之书**(`execution/book_of_truth` ← `GET /internal/executor/book-of-truth`,INTERNAL_TOKEN):纸面票 vs 交易所逐票对账(滑点、止损实际成交 vs 止损线、venue R vs 纸面 R)+ 违规(no_record / unfilled / no_stop / late_exit / orphan / off_plan)+ **挣来的杠杆上限**(真钱干净平仓 20 / 50 / 100 张 ⇒ 2 / 3 / 5 倍,违规降一级;建议,不生效)。主机修两处:止损触发单补意图、交易所上的平仓按真实成交记(不再假设成交在止损线);出场单没成交时触发单已撤 ⇒ 现在会重挂(之前会裸着到第二天)。排队 1150 / 1151 / 1152;**主机要 Jazz 再跑一次 install.sh 才生效**(本来就要跑)。派单(预注册在先):A = T-164 / S-655「一周还没站上进场价就走」;B = T-165 / S-656「+1R 那天主动买盘确认才加」。C 道 T-163 / S-650 ❌(按时点风格向量的类比预测 IC −0.05)。 ‖ **11:00 回撤与分级三条(都只动研究,不动前向账本):** S-651 ❌ +3R 后 3 × ATR 吊灯线几乎从不先于 SMA20(770 张里 5 张,模拟逐位不变);最深回撤 = 2024-11 同一波 8 张票一起回吐 19R(浮盈 62R)+ 窗口内新票 −10.8R。S-652 ❌ 组合层 15% 回撤减半:3 倍回撤 −30.5% → −20.6% 但年化 36.7% → 20.2%,与直接用 2 倍几乎同一点 ⇒ 风控规则没有白捡的部分,旋钮只有杠杆与劣后厚度。**S-653 FoF 分级:** 纯 ① 要 76% 劣后(99% 持续覆盖、优先 5%);① / R-v2 各半(3 倍)→ 48%,中位年化 +43% → +53%、最差 5% 回撤 −69% → −46%;加 ① 闸门 → 44%;**只要求三年到期覆盖 → 18–22%**(条款是最大的旋钮)。 ‖ **08:50 Jazz:向量库有问题,让 abc 协助获取和升级。** 实测:market_state_vectors 声明 24 维、平均只测到 11.1 维,**跨全史一次 z-score(含未来信息)**;regime_daily 只从 2025-05 起;风格只有 4 层级 + 4 板块;HL 原生币(HYPE)不在价格面板。派单:A = T-161 向量库体检(覆盖 / 按时点 / 谁在读 / 宇宙对照,量化全史 z-score 的泄漏);B = T-162 风格分类 v2(≥ 12 板块)+ 取数规格与回补请求(入库仍归 Seth,规则 3b);C = T-163 / S-650 按时点风格向量 v2 + 历史类比检验。S-641(B 道 T-158)❌ 方向相反:晚期风格里的票更好。 ‖ **08:30 S-649 ❌(方向相反):** Jazz「大币行情只拿 BTC / ETH」用风格层相对强弱(山寨层级 ÷ majors,> 50 日均才开山寨票)做开关 —— 挡下的 306 张山寨票合计 +279R、最好 10 张里挡掉 7 张,3 倍年化 +36.7% → +13.6%、回撤 −30.5% → −45.1%;两段里被挡的票都比留下的好(R-v2 最好的票诞生在山寨整体还弱的时候)。与 S-613 同向。R-v2 最差路径 = 「大盘还行、山寨不跟」的突破失败 + 山寨顶部后浮盈回吐 + 没赶上少数大行情月份(S-648 补),不是熊市。 ‖ **07:50 Jazz:长尾风险必然发生,用 FoF 分级(优先 / 劣后)承接**(DECISIONS 10-21)。**S-648:** R-v2 这条腿在 99% 路径里让优先级(5%/年)每天都被覆盖所需的劣后 —— 恒定 1 / 3 / 5 倍 = 25% / 45% / 61%,回撤刹车 5 倍 = 36%(刹车 = 覆盖测试触发器);劣后中位年化 +28% / +55% / +69%。下一步:整个 FoF(① + R-v2 + 现金同月联合重抽)的分级。 ‖ **07:10 S-647 代入模拟(Jazz「代入做模拟,不是简单回测」):** 新引擎 `src/exec_host/sim_tickets.py` 逐日调实盘的 `ticket_actions`,带 HL 保证金 / 整户强平、真实资金费、滑点手续费、放贷、恒定 vs 回撤刹车;校准 = 关掉摩擦后与 S-638 真内核期末 4.145 vs 4.12、回撤 −32.31% vs −32.3%。HL 宇宙 $704、钱全留 HL(B):L 1 / 3 / 5 → 三年中位年化 +11 / +32 / +50%,最差 5% 回撤 −18 / −42 / −59%,0 次强平;回撤刹车 L 5 → +27% / −34%。**钱借出去只留薄保证金 ⇒ 26–68% 的三年路径至少被强平一次**(浮盈大的赢家在急跌日被打穿)⇒ 这个账户钱全留 HL。数据缓存用 C 道 T-159 的。**Jazz 10-21:不走 Binance 通道**,R-v2 继续现货日线出信号(T-58 关)。 ‖ **05:55 Jazz 裁定:**05:55 Jazz 裁定:策略层 0–1 倍(参考,不加杠杆);组合 / 选择层可加杠杆,最多 5 倍**(DECISIONS 10-21)。执行器加组合杠杆旋钮 `R_V2_PORTFOLIO_LEVERAGE`(Railway,默认 1,超 [1, 5] 拒绝;主机再守 5 倍)。**S-646(只报):** ① 1 / 1.5 / 2 / 3 / 5 倍 = 年化 +41 / +48 / +47 / +21 / −62%,回撤 −57 / −74 / −85 / −97 / −100%;闸门版 ①g 2 倍 +54% / −71%;R-v2 2 / 3 / 4 倍 回撤 −32 / −43 / −52% ⇒ 杠杆该放在 R-v2 这类有止损的腿上,不放 ①。**两条熊市检验都 ❌:** S-642 空头臂每票 −0.13R(p = 0.01)⇒ 熊市 = 放贷 + R-v2 自动停,不做空;S-645 闸门关压 0.5 方向对(7/7 指数年化更高、回撤更浅)但幅度没过线。**S-644 核对:** 10-20 半根日线已被覆盖(83101.3 → 83028.1,差 0.09%);旧代码 03:53 又写了一根 10-21 半根,新代码不会再写,明早 00:10 被整根覆盖。 ‖ **04:20:** 40fc382c(S-644)/ 7de9299a(执行器单票)/ 7e40cea9(MCP yields)已上线;**等 Jazz:** 主机 `install.sh`、USDC 现货 → 永续、主机上 `curl fapi.binance.com` 探测(Railway 新加坡出口对 Binance 永续 / 现货接口都 451 ⇒ 永续口径的实时来源只能是主机或晚约 6 小时的 Vision 归档,T-58 的方案取决于这一条)。**04:05 补:** ① **执行器单票模式写完、排队上线**(`execution/ticket_plan` → `/internal/executor/plan` 的 `tickets` 段;主机 `exec_host/tickets`:IOC 进场、按成交价挂减仓止损触发单 + 每分钟后备、出场前撤单、单票名义 ≤ 净值一半且合计 ≤ 1.5 倍、读不到账户不记平仓;`EXECUTOR_TICKETS_MODE` 默认 dry_run;TRADE_PATH §3d)。上线后 Jazz 要做两件:主机跑 `install.sh` 更新、HL 上把 USDC 从现货划到永续。② **S-644 数据口径 P0:** binance_hist 曾写入未收盘的当天日线(10-20 那根 22:59 UTC 写入),三条日循环随部署漂移 ⇒ 修:不写今天、深盘 00:10 / 风格指数 00:30 / R-v2 扫描每小时 :45。③ **S-643 熊市减伤(只报):** 闸门关时 ① 降到 0.3–0.5 倍,回撤 −57% → −36~−39%、年化少 1–2pp;200 日闸门只防慢熊。Aave 熊市存款利率实测 3.2–3.4%。改 ③ 下限要 Jazz 拍板。④ MCP defi yields 修好(TVL 显示、$10M 下限、只看稳定币)。 ‖ 03:30:**Jazz 10-21 裁定:R-v2 在 HL 永续上执行,现在就上真钱(HL 704 USDC)**;binance_hist 的 192 个非核心名字回永续口径,① 的核心名字仍现货。**在做:** 执行器单票模式(收盘后出计划 → IOC 进场 → HL 挂减仓触发止损 → SMA20 / 120 根出场 → 同时最多 10 张;不在 HL 上的票记「不可执行」不替换;每票风险 0.5%;**先空跑,第一张票空跑与回放对上后 Jazz 切 live**)。最少资金:f = 0.5% 约 $550–600,704 够;只有约 48% 的信号在 HL 上有。**熊市问题(Jazz 10-21)查过的数:** 资金费按 BTC 200 日线分牛熊 —— 熊市 BTC 期现 +3.4%/年、ETH +2.3%、山寨等权 −6.9% ⇒ 套利是牛市的生意,熊市停车位是放贷;UNI 2026 第一段被闸门挡、第二段 R-v2 出票 +67%(「第二段介入」就是 R-v2 + 闸门);HYPE 不在 binance_hist(只有永续)⇒ 永续口径改造顺带纳入。**新预注册:** S-641 风格成熟度(B 道 T-158)、S-642 熊市空头臂 vs 躺放贷(C 道 T-159)。T-157 Jazz「迟些先」⇒ blocked。**发现:** `cometcloud_get_defi_yields` 按 APY 把垃圾池排最前且 TVL 全是 $0 —— 接口缺陷待修。)

**10-20 22:21 UTC (Seth — **夜间(Jazz 睡前「分配多点任务、慢慢做长任务或升级策略」)。** **① R-v2 记成钱(S-638):** 只读内核 `r_tickets_nav`(前向与回放同一个函数;逐日盯市与独立写法差 3e-15;B 道独立 Python 实现对上:回撤 −32.6% vs −32.3%)。f★ = 1%(盯市回撤 −35% 反推)⇒ 回放 2020-03 → 2026-10 年化 +24.4%、盯市回撤 −32.3%、总名义峰值 0.99 倍(不需要杠杆)。前向钱曲线写 `r_money_daily`(前向锁)。**S-621 ✅**(B 道 T-141:宽止损 + 最多 10 张在同回撤下胜出,两种口径都过)。**② 要 Jazz 定的三件(docs/TRADING_LAYER_V2.md §4):** 探索仓给多少 —— S-639:30% 配 R-v2,① 年化不变(+41%)、回撤 −57% → −36%,tom_pd13 + 30% → +43% / −32%;**永续还是现货执行** —— S-637 已量化(切换日 08-08):永续口径 R-v2 年化 +23.6%、现货 +19.6%;**按真实费率扣资金费后永续 +23.4%(每票 0.058R)**,配 30% 进 ① 时永续还多压 8pp 回撤(−36.8% vs −45.1%)⇒ 永续两头占优;真钱开关。**③ 资金费补到整个 binance_hist 宇宙**(Binance Vision 月档,`_binance_vision_funding`)—— 已上线并补完(259 个名字、122.9 万期,22:15 UTC 积压 0;Railway 16:56 → 20:40 卡了约 4 小时后自己恢复)。**⑤ ② 族第一个过预注册的候选(S-640,B 道 T-155,Seth 独立 SQL 复算一致):** 在 ① 的山寨里少配资金费拥挤的名字(BTC / ETH 钉住),全程 +22.7pp、留出段 +0.8pp、随机分位 0.98;族内第 4 次、不显著 ⇒ 纸面前向臂 `fund_a1_u`(cis_tilt_daily,10-26 起)。**④ lanes:** S-634 ❌(② 仍空)· S-635 ❌ · S-636 N/A · S-612 M2 更正(仍 ❌)· T-147 合并并修了 W44 被提前冻结 · T-146 的 (i) 作废 → T-152 逐步瀑布 · 新卡 T-153(现货面板钱曲线)/ T-154(一个鱼计数器,先复现 286 —— A 道曾数出 837)· T-140 r3 在跑。判活:`select max(d), nav from r_money_daily`;`select count(*) from funding_vision_plan`(应降);`select git_sha from /internal/build-state` = origin/main。)

**Previous update:** 2026-10-20 14:52 UTC (Seth — **回到高维:S-632「大鱼前兆图谱」❌**。问:价格突破之前,哪个维度已经在动(持仓量 / 大户与散户多空比 / 主动买卖 / 资金费 / 量价结构,对照同日同价格状态的非鱼)。发现段(2022–23,96 条鱼)入选主动买卖比、成交额放大、区间更宽,持仓与多空比都不是前兆;**留出段(2024-01 → 2026-05)前 10% 的鱼率 1.64% vs 其余 1.74%,p 0.65 ⇒ 不复现**(发现段是少数鱼的极端值撑起来的)。**更大的读数:鱼成潮出现,多在全市场急跌见底之后**(2024-08-05 一天 14 个、2025-03-29 → 04-16 13 个)—— 挑名字几乎不可预测,时机高度集中。⇒ **S-633「鱼潮」已预注册**(全市场突破广度做单票风险开关,判据 = 在鱼比例 + 平均 R),交 B 道 T-145。)
**🟢 DEPLOY VERIFIED 2026-09-23**:commit `1bb885f` pushed → Railway `build=1bb885fa`;`_cg_panel_loop` heartbeat `verdict=ok`,age=158min(well within `_CG_PANEL_INTERVAL_S=6*3600` success cadence — **not staleness**),`stale_build=false`,`late=false`,`reason=上次成功 158 分钟前`。S-410 ✅ CLOSED。

**A-408-2 ✅ SHIPPED 2026-09-23 (commit `067e10f`, PR-A, A lane — `loop_attempt` per-iteration record)**: 43 async loop 中 0 个写 per-iteration row;`_beat()` 是 Redis hash 不能回答 COUNT。Ship `scripts/supabase_s408_2_loop_attempt.sql`(新表 + 3 索引 + RLS + 3 grant + `loop_attempt_health()` helper,镜像 `write_health()`)+ `_record_loop_attempt()` in `rpc_diagnostics.py`(`LoopOutcome = Literal["ok","refused","error","panel_unavailable"]` 字面冻结,writer 显式传入,`build` 字段 = inline env 查找(`RAILWAY_GIT_COMMIT_SHA`→`GIT_COMMIT_SHA`→`SOURCE_COMMIT`)[:8],**不** import `loop_beat.build_sha` 以避开 S-341c mypy strict 两文件范围)+ wire `_cg_panel_loop` 3 分支(panel_unavailable/ok|refused/error)。测试 `test_a_408_2_loop_attempt_smoke.py` **12/12 PASS**(T1 Literal vocab / T2-T3 never-raises+短路 / T4-T7 payload+truncation+build / T8 常量 / **T9 S-244 文本守卫** main.py ≥ 3 sites / T10 与 _beat 并行 / T11 幂等 / T12 4-branch replay)。preflight 注册 stage 3。判据 `select count(*) from loop_attempt where loop_name='_cg_panel_loop' and at::date = current_date` ≥ 100。**DDL 待 MCP apply** —— 表不存在时 `_record_loop_attempt` try-hard 返 False 永不抛,所以 deploy 后 24h 内补 DDL 即可,无静默错数据风险。**Push 时 preflight 🔴**(S-302 预算越界,Seth `hl_book_daily.py` 未跟踪,Jazz override)。

**A-408-3 ✅ SHIPPED 2026-09-23 (commit `a34e804`, PR-B, A lane — `ohlcv_daily` write_log coverage 1/5 → 3/5)**: §SETH-AUDIT-2026-09-23 🔴 复查后 1 真 1 转路 2 误报。`_upsert_ohlcv` (ohlcv.py:54-77) 直 httpx POST 绕过 `@log_write_attempt` 装饰器 → 重构为 `supabase_upsert_table` per chunk(chunk 仍 500)。admin.py 是路由→collect_ohlcv→_upsert_ohlcv 的转路(修了 ohlcv.py 自动覆盖);deep_panel_collector 已走 helper,S-415 silent-fail fix 后自动出现;price_route.py 根本没写(grep 无 ohlcv_daily 写入),**ledger 注明 false-positive 锁**。测试 `test_a_408_3_write_log_coverage_smoke.py` **8/8 PASS**(T1 chunk 仍 500 / T2 走 helper / T3 partial success / **T4 S-244 守卫** `_upsert_ohlcv` 内无 `client.post(` 无 `?on_conflict=` / **T5 deep_panel_collector 守卫** / **T6 price_route false-positive 锁** / T7 writer attribution / T8 累计 inventory = 3 writers:cg_pro_backfill + ohlcv._upsert_ohlcv + deep_panel_collector)。preflight 注册 stage 3。判据 `select count(distinct writer) from write_log where table_name='ohlcv_daily'` ≥ 2 ship 后立即,≥ 4 由 S-415 + admin transitively 累积。**Push 时 preflight 🔴**,同 A-408-2,S-302 越界,Jazz override。

**S-397 P1+P2 audit backlog ✅ SHIPPED 2026-09-23 (8 sites + 1 false-positive)**: JAZZ 「abc 都做」。8 sites of S-262 family fixed (A7 verified NOT broken — `setLoading(false)` IS in `finally` block): A2 `StrategyPage.jsx:545` BTC 7D color branch / A6 `DiagnoseHome.jsx:32` radius NaN when cis missing / A8 `AssetRadar.jsx:152-158,552` fmtVol $1e3 divisor on mcap → fmtMcap via `fmtDollar` / A9 `AssetRadar.jsx:341-353` sort `|| 0` collapses missing → isMissing last / C2 `IntelligencePage.jsx:67-73` fmt.amount falsy-zero → isMissing / C3 `CISWidget.jsx:343-344,718-723` pillar `?? 0` color + composite recalc normalize by presence / C4 `PortfolioDiagnosis.jsx:42` `cis:25` fallback → isMissing + outer rim / C7 `QuantMonitor.jsx:227,279` median_return falsy-zero → isMissing. Tests `tests/test_s397_p1p2_audit_backlog.py` 27 cases PASS (runtime isMissing smoke + 8 per-site grep guards + A7 false-positive verification + preflight registration). preflight stage 3 注册 + `lesson_enforcement_baseline.txt` 196→197 (auto-bump). Bundled fix: `paper_trading/jev_smoke.py` 加 `sys.path` bootstrap(S-402 — pre-existing RED from S-397 main batch,不带 bootstrap 时脚本路径调用下 `from paper_trading.X` 会在 argparse 之前炸,症状伪装成参数校验失败)。) — 【更早条目 → `PROJECT_STATE_LOG.md` §2026-09-23-HEADER-MOVED-FOR-CAP】

> **本项目的主导缺陷类:「拿不到」被渲染成一个合理的数字,而不是被渲染成「拿不到」。**
> 十一次实例(S-180…S-243)+ 三条课 + 守卫自己失败七轮的记录 →
> **见本文件 §一个形状,十次(在 OPEN RISKS 之后)。**
> 那一段移出第一屏不是降级:**第一屏按 `test_project_state_opens_with_open_risks` 只装活的危险,
> 历史教训排在危险后面** —— 2026-09-22 我把方向段插在 OPEN RISKS 之前,当场被这条判据抓到。

## 现在能跑的 / 不能跑的

```
(2026-10-20 19:1x UTC 实测,Supabase 直查;上一版是 10-13)
✅ 价格源       binance_hist 136 标的日更(① 价源;08-08 起非核心名是现货口径,见 #0e)· coingecko_pro_ohlc 210 · eodhd 193(World50 扩池后)
✅ 循环         loop_attempt 3 天内 78 个:69 最近一次 ok · 6 本 ④ 冻结记 refused(causal / scalable / combined / dingge / fusion / two_layer,S-631)
                · _hl_book_loop refused「当天已记录」· _meta_allocator_loop refused「策略库只到前天」· _cis_inputs_loop error(macro.global_recent 单项)
✅ 正式 CIS     cis_official_daily 每天一批、只追加,最新 = 昨天
✅ 前向记录     S-560 起 d ≤ 今天 − 2 冻结;① cap_a1_u / ③ tom_pd13 / R-v2 票(r_tickets_state)都到昨天;ⓠ 两臂 10-22 起出前向行
✅ 部署        Railway 16:56 → 20:40 UTC 卡了约 4 小时(02fc20c0 的部署记录建了没动,之后的推送没有部署记录),20:40 自己恢复(89dff45b、6761340c 上线);原因未查 —— 再出现就去 Railway 看部署队列
🟡 执行器       东京主机 dry_run,每小时心跳;改 live 是 Jazz 的动作:
                 select at, outcome, detail->>'kind', detail->>'mode' from loop_attempt where loop_name = 'executor_host' order by at desc limit 5;
⚪ agent_call_log 0 行 = 没有外部 agent 流量(写入任务 S-562 已修;watch_census 标「量随流量,不判活」)
✅ lane 数据通路 lanes 只拿 publishable key(10-20 轮换后),读权限按表开 lane_read;写只经 seth_bot
```

## OPEN RISKS  (≤7 · cold-start first screen · every item ships a VERIFY command)

*Why this block is first: measured on 2026-07-30, a cold agent following CLAUDE.md exactly could
not reach S-92 or the still-open security hole — the header was dated older than the incident and
the lessons lived only in a 5,672-line ledger. **Don't transmit memory, transmit verification.**
Contract + failure-path walkthrough: `docs/AMNESIA_PROTOCOL.md`; enforced by
`tests/test_cold_start_contract.py`.*

### #0e · 🟡 binance_hist 口径拼接:192 个名字 08-07 及以前是永续、08-08 起是现货 —— 等 Jazz 定执行口径(S-637, 2026-10-20)

**T-151 已量化(台账 S-637 量化):** 切换日 **2026-08-08,整块切**(08-07 及以前与永续逐位一致、成交量是现货的 5.2–5.9 倍;08-08 起全部与现货一致,73 天无例外)。全程现货 40(核心)、切换前永续 192、全程永续 0。R 臂(2023-01 → 2026-06-20,k = 2.5):**现状 769 票 / +0.253R;永续面板 759 / +0.234;现货面板 492 / +0.178(票少 36%)**。研究回测窗口整段是永续口径,前向 R-v2 账本是现货口径 —— 不是同一个宇宙。
**要 Jazz 定:** R-v2 在**永续**上执行 ⇒ 采集器改回永续口径(研究结论几乎不变);在**现货**上执行 ⇒ 历史重取现货、S-638 / S-639 按现货面板重算(票少三分之一)。**定之前不改任何一行。**

VERIFY: `select symbol, trade_date, volume from ohlcv_daily where source='binance_hist' and symbol='CRV' and trade_date in ('2026-07-15','2026-09-15')` 对比 `https://data-api.binance.vision/api/v3/klines?symbol=CRVUSDT&interval=1d&startTime=1784073600000&limit=1` 的第 6 列。

### #0e · 🔴 Railway 平台被入侵(10-21)—— 构建暂停、环境变量须全部轮换

Railway 公告:存放客户环境变量的系统被入侵,部分变量被解密拿走;全平台构建暂停(10-21 07:24 UTC 起,10-22 02:00 仍未恢复)。我们的线上停在 27d52ba0(10-21 06:59 部署),之后的提交都没部署。**查过:** Supabase 7 天 edge 日志里 secret key 的请求全来自 Railway(asOrganization = Railway)与 Mac;库没有外部直连;GitHub 10-20 以来的提交全是我们自己的身份。**已做:** 主机复核(TRADE_PATH §3f)—— 能写库最多只能让主机做一张像信号的票(R-v2 复核目前 report,J 票 / 信心倍数签名强制)。**GitHub(10-22 02:50 已做):** Railway 的 `GITHUB_TOKEN` 与 Mac 的 `gh` 登录是同一份 OAuth 授权(repo + workflow,覆盖全部仓库)⇒ Mac 改用只限本仓库的 fine-grained token,`gh` 的 OAuth 授权已撤销;私有文档(台账 / 策略手册 / DECISIONS)的备份仓库 `~/Projects/looloomi-private` **没有 GitHub 远端**,从没上过 GitHub ⇒ 不在这把授权能读的范围内;本仓库是公开的。Mac 的推送已用新 token 验通(4fb6c44b)。**Jazz 还要做:**(推理 key / RESEND:Jazz 10-22 判 Railway 上几乎没有,不急,随构建恢复后的轮换一起做)构建恢复后按 `docs/RAILWAY_ROTATION_RUNBOOK.md` 一次轮换;~~Mac 上 `regime_call.py keygen` + 抄密钥到主机~~ ✅ 10-23 01:10 UTC 主机已配 `JAZZ_CALL_KEY`(主机指纹 8ec89132;install.sh 自检过,executor / recorder / whales 三个服务在跑,dry_run,代码 d821e36;当前生效的判断是配 key 之前提交的、未签名 ⇒ 风险倍数 1、不开 J 票,要生效就在 Mac 上重提一次)。**切 live 前的前置条件(10-23):Jazz 在同一个 HL 主账户上手动交易试错** —— 执行器现在把账户当成只属于自己:X1V 现货把账户里全部 UBTC / UETH 当自己的持仓(目标 0 就卖、灾难止损线下也卖),上限 3,000 以内的 USDC 当自己的现金;R-v2 按整个永续账户的净值定仓位(封顶 1,000)。代码不支持子账户(没有 vault_address)⇒ **手动交易挪到 HL 子账户,主账户只放执行器那份钱**,再切 live。空跑期间互不影响。**主机保持空跑,轮换完才切真钱。** VERIFY:`curl -s https://web-production-0cdf76.up.railway.app/internal/build-state` 的 git_sha_short = origin/main;Supabase 日志旧 secret 前缀 0 次。

### #0d · ✅ Supabase key —— 10-22 收尾:legacy JWT key 停用(00:30)+ legacy JWT secret 吊销(00:34),均实测

**10-22 更正(S-94 探针报红后查出):** 下面「legacy 已停用」不成立 —— 那天看到的是「06:05 后我们自己零 legacy 请求」,不是「legacy key 被拒」;10-20 之后 legacy anon 读 `cis_scores` 仍 200。细节与日志核查在 `MINIMAX_SYNC` §IN-FLIGHT #31(私有)。已做:`cis_scores` 的 anon policy 收回(`migrations/2026-10-22_restore_s94_cis_scores.sql`;探针 200+`[]` 或 401/403 都算过;`tests/test_cis_scores_not_anon_readable.py` 守住)。① **Jazz 10-22 00:30 停用 legacy JWT API keys —— 已验**:探针那把 legacy anon 读 `ohlcv_daily` / `cis_scores` / `cis_official_daily`、带 Bearer 也一样,全 401;Railway(secret key)停用后照常 200 / 201;探针 ✅。② **Jazz 00:34 吊销 legacy JWT secret —— 已验**:有效 publishable key + 旧 secret 签的 JWT(Bearer)⇒ 401 `PGRST301 No suitable key was found to decode the JWT` ⇒ 泄露过的 service_role JWT 彻底作废;Railway 吊销后照常 200 / 201;publishable 单独读 200;探针 ✅。剩的只是 Mac 侧 `active_monitor` 的 key(SYNC #38)与引擎 secret 搬家(SYNC #31)。

两处泄露:`/api/v1/auth/config` 自 03-26 返回 `SUPABASE_KEY`(Railway = service_role);lane-a 把同一把 key 推到公开分支 `lane-a/T-137`。代码侧已封(接口不返回 key;`scripts/secret_scan.py` 在 preflight 与 pre-push)。**已完成**:Railway 05:50 起用新 secret(0 错误);Mac 两份 .env 换新;publishable 换新、公开的那把已删;legacy anon + service_role 已停用(06:05 后零 legacy 请求)。06:02–06:05 那批 legacy 请求 = seth_bot 的 preflight(主仓库 .env 还没换),不是常驻进程。**尾巴**:① Mac 引擎的 secret 仍在 `cometcloud-local/.env`(只靠钩子挡 lane)→ Minimax 挪到 `~/.cometcloud/engine.env`(SYNC #31);② advisor:8 个 SECURITY DEFINER 函数 anon 可执行(panel_closes / panel_funding / public_columns / catalog_inventory 等,早于本次,只读)→ 逐个改 INVOKER 或收回。 **Jazz 10-20 裁定:lane 只拿 publishable key。** 已做:`migrations/2026-10-20_lane_read_publishable.sql`(28 张研究表 + 4 个只读 RPC 给 anon 读)—— **已暂停**(`..._suspend.sql`):现用的 publishable key 自 06-19 写在公开的 `docs/SUPABASE_SETUP.md` 里,RLS 分不出是哪把 publishable;Jazz 建新的 `lanes` publishable、删旧的之后再开;lane_bot 启动时清掉一切写权限 key,只从 `~/.cometcloud/lane.env`(Jazz 建,只放 URL + sb_publishable_)注入;钩子拦 lane 读 `.env` / 打印 key。**Mac 引擎那把 secret 不能再放 `cometcloud-local/.env`**(lane 读得到)—— 放 `~/.cometcloud/engine.env`,引擎脚本改读它(Minimax 侧,SYNC 已登记)。

VERIFY: `curl -s https://<prod>/api/v1/auth/config` 不含 `key`;Supabase → Settings → API Keys → Legacy 显示 disabled;`python3 scripts/secret_scan.py` ✓。

### #0a · 🔴 面板断线 2 天,而每个仪表都说它活着 (S-408, 2026-09-22) — 已派 A,判据三条

`coingecko_pro_ohlc` 当日标的数 **09-20 = 157 → 09-21 = 17 → 09-22 = 25**。
活下来的 25 个是 **① 的持仓面板**,不是宇宙 —— **行情最猛的两天,观测宽度塌了 85%。**

断点是 09-20 08:11–13:36 一次 **5h25m Railway 停机**:七个写入端全部恢复,
**只有 `_cg_panel_loop` 的两段(`cg_coin_map` + `cg_pro_backfill`)再也没回来**。
两段同死 ⇒ **不是额度**(额度只杀回填那段)。**S-401 的额度结论已被推翻。**

**两天没人发现,是因为 `write_log` 对 `ohlcv_daily` 的覆盖率是 1/5** ——
`routers/ohlcv.py`、`routers/admin.py`、`deep_panel_collector.py`、`price_route.py`
四个写入端一行都不记。**看表 ⇒ 活着;看账 ⇒ 09-20 死。两个都对,说的是不同的写入端。**

**VERIFY(三条,缺一不算完):**

```sql
select count(distinct writer) from write_log where table_name='ohlcv_daily';
select count(distinct symbol) from ohlcv_daily
 where source='coingecko_pro_ohlc' and recorded_at::date = current_date;
```

判据:writer ≥ 4(现 1)· 当日 distinct symbol ≥ 150 连续 3 天(现 25)·
`loop_attempt` 每天 ≥ 100 行(现:表不存在)。
⚠️ 用**当日 distinct symbol**,不是 `max(trade_date)` 也不是总行数 —— S-379 的并集统计教训第二次适用。
派活:`MINIMAX_SYNC.md` §S-408-面板断线-2026-09-22。

**S-410 ✅ closed caller unpack,本条三条 VERIFY 仍未过 —— 两条独立**:
S-410 (commit `1bb885f`, 2026-09-23) 修了 `main.py:1056` 2-tuple → 3-tuple unpack,
`_cg_panel_loop` heartbeat `verdict=ok`,age=158min(well within `_CG_PANEL_INTERVAL_S=6*3600`)。
**但 S-410 只闭合 caller 漏接返回值,**§S-408 三条 VERIFY 判据(distinct writer ≥ 4 /
`_cg_panel_loop` ≥ 100 attempt/天 / 当日 distinct symbol ≥ 150 连续 3d)仍派 A,
**A-408-1 让它重新跑起来 + A-408-2 写 loop_attempt + A-408-3 补四个 write_log writer**。
**A-408-2 ✅ SHIPPED `067e10f` 2026-09-23 + A-408-3 ✅ SHIPPED `a34e804` 2026-09-23** —— DDL 待 MCP apply(A-408-2 表不存在时 `_record_loop_attempt` try-hard 返 False 永不抛,无静默错数据),distinct writer ≥ 4 等 S-415 累积(A-408-3 自身 ship 后即得 +1 writer → 累计 2:cg_pro_backfill + ohlcv._upsert_ohlcv)。**A-408-1 未指派**(S-410 闭合即隐式闭合 — `_cg_panel_loop` heartbeat 已恢复)。
**S-302 cross-lane**:两个 PR push 时 preflight 🔴,Seth 未跟踪的 `src/data/signals/hl_book_daily.py` 加 1 entrypoint 越过 S-302 「只减不增」预算(24→25)。Jazz override 推。**lane owner 拍板项**:见 `MINIMAX_SYNC.md` §S-302-2026-09-23(选项 1 ship S-413 + bump 预算 25 / 选项 2 hl_book_daily 走 panel_read / 选项 3 加白名单例外)。本条不因 S-410 而关,也不因 A-408-2/A-408-3 ship 而关 —— VERIFY 三条要绿才算完。

### #0c · `nav_panel_*` 两张表:**声明在前,写入端在后** (S-399, 2026-09-22)

`/internal/schema-drift` RED:`nav_panel_daily` / `nav_panel_rebalances` 不存在。
**这个红灯是对的,而它此前的措辞是错的。**

实测:`src/` 里**零调用点**写这两张表;它们只出现在
`c13_nav_panel_manifest.WRITES_TABLES` 的声明里(注册 commit `83aab37` 在写入端存在之前)。
Mac 侧只有 `nav_writer_2026-09-20.py` 的骨架(TODO 在 43/101 行),**无 launchctl 调度**。
7 步 ship 规格在 `cometcloud-local/research/c_path_15_mac_ship_7step_2026-09-20.md`:
步骤 1–6 归 Min-A(~2 个工作日),步骤 7 归 Seth(~4 小时)。

**为什么不现在建表(三个方案都不选):**
- 建了 → drift 立刻变绿,而两张表**永远是空的** = **S-201 原形**
  (「表存在、永远空、看起来这项有人管」,就在本文件 §一个形状,十次 里)。
  **一个因错误理由变绿的检查,比红的更坏。**
- 撤注册(方案 A)→ 等写入端真 ship 而表仍缺失时,**没有东西会抓到**。拆守卫。
- `pending_writer: true` 降级 WARN(方案 C)→ **一个没有理由字段、没有删除条件的豁免**。
  仓库里唯一好用的豁免机制(`test_every_test_is_registered.EXEMPT`)两样都有,
  它的注释写着为什么:**「豁免不是赦免……被注册之后这一行必须删掉,否则名单会变成永久特赦」**。
  且 RED→WARN 在一个打几十行的 preflight 里等于不存在(S-372:三个监控面报健康而五个 producer 在死)。

**已做的(S-399,不是把红灯变绿,是让红灯说真话):**
`write_tables_by_provenance()` 把「有调用点」和「只有声明」分开,
drift 的 consequence 按来源分两段措辞。
⚠️ **关键口径:`declared_only` ≠ 没有写入者** —— 实测六张 declared_only 表里**四张是活的**
(`cg_coin_map` 211 / `corporate_treasury_history` 3852 / `treasury_decisions` 896 /
`treasury_entities` 102),因为显式声明这个机制存在的理由正是 AST 走查跟不进
`cometcloud-local/`。所以措辞只说「从这里看不到调用点」。守卫:
`tests/test_drift_separates_declared_from_written.py`(已进 preflight)。

VERIFY: `curl -s .../internal/schema-drift | python3 -m json.tool | grep -A2 missing_declared_only`
→ 期望 `nav_panel_daily` / `nav_panel_rebalances` 落在 `missing_declared_only`,
**且 consequence 里那一段不含「returns False and is swallowed」**。
**解除条件**:A 完成步骤 1–6 且 launchctl 有调度 → Seth 建表(步骤 7)→ 红灯因为管子通了而变绿。
**日期兜底 2026-10-06**:到期未 ship,则**撤掉 manifest 注册**(不是撤红灯),
并在这里记明「声明先于实现」这次的代价。
OWNER: Min-A(1–6)· Seth(7 + 本条到期盯)

### #0b · `INTERNAL_TOKEN` 按已泄露对待,而我们**选择**带着它继续开发 (S-371, 2026-09-17)

**这是一条被接受的风险,不是一个被遗忘的缺陷。** Jazz 2026-09-17 裁定:
**先赶开发进度,做完再收回和更换。** 记在这里是为了让它有到期日,不是为了提醒它存在。

事实(实测,非估计):`INTERNAL_TOKEN` 在 Mac 的 `.env` 里,而 Minimax-backed 的
Claude Code 在这个仓库跑过,其上下文走第三方中转。它打开 ~30 个 `/internal/*` 写入口
+ trading 的 DELETE —— **写的是 system of record**。同批量到的另外六个 key 代价有界:
anon 读 80 表 / 写 0 表,4 个付费 key 只能盗配额,`SUPABASE_SERVICE_KEY` 不在 `.env`(S-169 守住)。
**七个里只有这一个值得花力气**,所以这条 OPEN RISK 只装它。

**而且轮换今天是坏的**,不是"还没做":36 处比较 / 17 个文件 / 零共享校验函数,
12 个 router 在 import 期读常量而 `main.py` 请求期读 environ —— 改掉 Railway 的值之后
**旧 token 打 router 仍 200、打 main.py 已 401**。所以"到时候换一个就行"这句话现在不成立:
**必须先收敛(36→1,请求期读 env),换才是原子的。** 判据已写好并跑过(见 VERIFY)。

**解除条件(两个都写,因为只有里程碑的待办就是会被忘掉的那种):**
① 开发冲刺结束由 Jazz 宣布 → 立即执行 A-1 收敛 → A-2 拆 lane token → 旧值作废;
② **日期兜底 2026-10-08** —— 到期未动则此条转 🔴,不再是"接受的风险"而是"过期的接受"。
**🔴 2026-10-08 已到期,未执行。** Jazz 10-07 对已泄露的 CoinGecko key 说「之后统一 revoke,先跑通」—— 那是推迟,没给新日期;所以这条现在是**过期的接受**,不是被接受的风险。需要 Jazz 给一个新兜底日(或宣布冲刺结束触发 ①)。

VERIFY: `python3 -m pytest tests/test_internal_token_contract.py -q`
→ 今天预期 **2 failed / 9 skipped**(红得对:活没干)。
全绿 **且** 该文件已进 `scripts/preflight.sh` 清单 ⇒ 本条可关。
**只绿不进清单不算** —— preflight 跑的是显式清单不是 glob,清单外的测试永远不跑。
OWNER: Seth(收敛判据 + 到期盯)· Minimax-A(执行 A-1/A-2)· **Jazz(唯一接触 key 真值的人)**

**解冻即实施**(`docs/AUTH_DESIGN.md`,2026-09-17 第一性原理设计冻结):
所有 auth 收口到 `src/api/auth_internal.py::require_internal_token()`,env 读每次重新读,
constant-time compare,返回值=lane 名;36 处端点 / 加 lane / 换 HSM / 加审计 都不需要写第二遍。
paid-first 同步 hold —— 它经过的 ohlcv.py 落 36 处之一,A-1 收敛后才能 push。

HL 那条路已正确关闭(用途轴:面板行情是 market_data,归 CG Pro)。
CG Pro 那条路只覆盖 `ASSETS_CONFIG` 的 25 个,因为**全仓没有面板级的
symbol→coin_id 映射表** —— `cg_pro_backfill` 与 `deep_walk` 都要求
调用方传 `(symbol, coin_id)` 对,而那份对照表从来没有被建过。

**这不是「源选错了」的残留,是一个独立的缺口。** 修法是一次 CG Pro
`/coins/list` 调用(~17,000 条 symbol+id)落成映射表,再用 S-258 的
实证校验(收盘价对比,错的 coin_id 会差几十倍)逐个确认后写入。
**不要在没有校验的情况下按 symbol 猜 id** —— 一个错的映射会把另一个币
的整段历史写进这个标的,而曲线看起来完全正常。

```
curl -s 'https://web-production-0cdf76.up.railway.app/internal/data-freshness' | python3 -c 'import sys,json;d=json.load(sys.stdin)["by_source"];print(json.dumps(d,ensure_ascii=False)[:400])'
```

⚠️ **用 `d["key"]` 不要用 `d.get("key")`。** 2026-09-05 我给 Jazz 的两条验证命令
都问错了字段(`loop-health` 上问 `n_failing`,`data-coverage` 上问 `n_covered`),
两条都打印 `None` —— **而「字段不存在」和「系统健康但没什么可报」在 `None` 上同形**。
心跳面板在 `/internal/data-freshness` 的 `loops` 键下,不在 `/internal/loop-health`。

*RETIRED 2026-08-12 to make room for #0: **#5 MCP streamable-transport migration** — closed
2026-08-09, no open follow-on, and its VERIFY (`grep -c 'mcp/sse' src/mcp/*.py` → 0) is a
regression check, not a risk. Moved to the ledger. Structural note while retiring it: **5 of
the 8 entries were 🟢 closed.** A cap of 7 does not bind on risk, it binds on the list, so
resolved items crowd out live ones and a cold agent reads eight entries to find three risks.
The cap is doing its job only if closure is as routine as addition.*

0. **🔴 两份 regime 标签在同一台机器上打架,而 book 读的是没人复核的那一份 (S-263, 2026-09-01)。**
   Supabase 侧(系统记录)`daily_macro_regime` = **TIGHTENING**,自 07-27 起 36 天未翻;
   M-120 往 Mac 本地 `_data/cis_history.db::narrative_daily` 回填的是 **EASING**,由 BTC 30d
   收益(+24.6%)导出 —— **那不是宏观判定,是单资产动量换了个名字**。book_trader 读本地那份。
   两份都不可全信:本地那份没有宏观内容;Supabase 那份是**一个多数票,而选民从 3 个掉到过 1 个**
   (08-17/21/22 `n_sources=1`),而 `daily_macro_regime` 这个 VIEW **每天都算出 `n_obs`/`n_sources`,
   两个消费者却只 `select d,regime`** —— 票数被扔了,所以「3 票一致」和「1 票独裁」在下游同形。
   已建 `src/data/market/regime_quorum.py` 五值裁决(ok/thin/COLLAPSED/frozen/no_baseline),
   今日实测 **thin**(信源 2/基线 3)。**Seth 侧闸已 ship**(2026-09-04 S-284 C fix →
   `paper_trading/spec_runner.py:430 decide_gated()`,commit 62133ad;22 守卫绿 +
   24 CLI 守卫绿,全部 wired preflight)。thin/COLLAPSED/frozen/no_baseline/no_data
   现在**真的拦 book**(Seth 侧全链路 ready,等 Mac 切到新入口)。原来的
   「只报不拦」是 HALT 期主动选择 —— 跟 OPEN RISK 0b 同源。
   **Mac 侧 `book_trader.py` 仍读裸 label,没接 decide_gated —— 闸 Seth 侧 ship 了,
   Mac 侧要接才生效**(见 §SETH-DISPATCH-2026-09-05)。
   VERIFY: `python3 -m tests.test_regime_quorum` → green ·
   `python3 -m tests.test_regime_quorum_blocks_book` → green ·
   `python3 paper_trading/spec_runner.py --book=b --dry-run --require-regime=ok --as-of=2026-09-01` →
   `ENTERED`,regime=EASING,synthetic_quorum=true ·
   `python3 paper_trading/spec_runner.py --book=b --dry-run --require-regime=COLLAPSED --as-of=2026-09-01` →
   `SKIPPED`,reason 引用 S-263 ·
   `select d,regime,n_obs,n_sources from daily_macro_regime order by d desc limit 10;`
   → `n_sources` 连续 ≤1 即为塌陷
   OWNER: Seth(闸 + 闸守卫 + ingestion guard,shipped)· Minimax-C(Mac book_trader 接 decide_gated)·
   Minimax(本地 `narrative_daily` 的 producer 与定义)

0b. **🟢 Option C signed 2026-09-05 (BOOK_TRADER_DECISION_2026-09-01.md)。**
   M-112(08-30,P0)：`book_trader.py` HALT,Sharpe +8.2 是 same-bar look-ahead,诚实值 +1.25/+1.63。
   M-120(08-31)：「book_trader 自 08-29 18:06 起未运行」—— 时间线是 18:04:46 触发
   DD-STOP **-60.07%**、18:06:35 停止,**109 秒 by design 不是崩溃**。
   M-115 Book B(M-93 + R14-Lite,lag-1,SR +1.629 / cum +321.5% / MaxDD -22.9%,beats
   Book A by Δ +0.380 SR)over M-113 Book A;**Seth lane 闸已 ship**:regime_quorum 5-value
   arbiter + `decide_gated()` wrapper(spec_runner.py:430)+ 22 闸守卫(test_regime_quorum_blocks_book)+
   24 CLI 守卫(test_spec_runner_cli --require-regime=ok/thin 放行,COLLAPSED/frozen/no_baseline/no_data SKIPPED)
   + ingestion lane guard(test_one_ingestion_lane,§M-118,待 commit)。**下一步 Minimax-C**:
   `book_trader.py` 切到 `decide_gated` 入口,regime_quorum 闸把 verdict=COLLAPSED/frozen/no_baseline/no_data
   全部拦截成 SKIPPED(thin 放行,但带 `verdict_kind=skipped` 标注);恢复时走 Book B config(M-93+R14-Lite)。
   **不在 OPEN RISK 0 重抄「要不要拦,跟恢复 book 一起签」** —— 那一句在 OPEN RISK 0 顶部已升级为
   「闸已 ship 等 Mac 切」,本条只剩 Mac 侧 wiring 一件事。
   VERIFY(Mac 切完): `python3 paper_trading/spec_runner.py --book=b --dry-run --require-regime=ok` →
   `ENTERED` · 同上 COLLAPSED → `SKIPPED` · `bash scripts/preflight.sh` 绿 ·
   `ps aux | grep book_trader` → 1 line · `select max(trade_date) from beta_core_nav` ≥ 恢复日 ·
   `python3 -m tests.test_regime_quorum_blocks_book` 绿 ·
   `python3 -m tests.test_spec_runner_cli` 绿
   OWNER: Seth(闸 + 守卫全部 shipped)· Minimax-C(book_trader 切 decide_gated + 恢复 Book B config)· JAZZ(已签 C)

0c. **✅ 已收口 (S-345, 2026-09-14) · bridge option(a)。** `daily_runner.py:50-58` 改
   `subprocess.run([sys.executable, ...], capture_output=True, ...)` 为
   `importlib.import_module(module_name)` + `mod.main()`,保留 prototype
   sleeve + spec_runner 两条路,删掉 subprocess 这块让它们各走各的方向的胶水;
   5 个守卫(`tests/test_paper_books_uses_direct_imports.py`)全 5/5 绿,登记
   preflight stage 3a-undevicesima-ter;`test_every_test_is_registered` 报 125 注册 ·
   0 orphan。A-17 `panel_long_only` 已 ship spec_runner canonical path(M-117g
   Book B 同 lane),paper_books 仍是 prototype 不动 —— **这是关掉 0c,不是解决
   0c**(解决要等 60d verdict 后或 Jazz 拍 fold 才到)。原 (A) fold / (B) ack
   两个候选已弃用,**bridge 是 C 的 plan 第 5 项**(Seth 评价同意);详见
   `REFUTATION_LEDGER.md` S-345。
   VERIFY: `python3 -m tests.test_paper_books_uses_direct_imports`(5/5);CLAUDE.md
   lane table line 113「`src/research/paper_books/` (older sleeve+ledger prototypes,
   pre-spec_runner — reconciliation pending, see PROJECT_STATE.md OPEN RISKS §0c)」
   —— 已写「pre-spec_runner」字样,test 4 即验。
   OWNER: **Seth** · closed by S-345

0. **🔴 C3 sizing table was INVERTED ON BOTH AXES (S-151, 2026-08-12).** Measured by
   execution: `lookup_size(regime=5 out-of-distribution, signal=1 weakest) = 1.30` and
   `(regime=1 in-dist, signal=5 strongest) = 0.10` — exactly backwards from the module's own
   stated design; `compute_size(None, None) = 1.20`, i.e. **no information produced leverage**,
   and `beta_core_size_hook` documented that 1.20 as the intended first-ship baseline.
   It survived because table + smoke test + hook docstring all agreed with EACH OTHER; only the
   stated intent dissented. **A frozen-value check could not have caught it — the table was
   transposed before it was frozen, and freezing preserves it.** Fixed by making the wrong
   ORIENTATION unable to load (`src/data/signals/strategy_params.py`, behavioural invariants
   validated at load), not by editing Minimax-C's 25 values. Until C seeds a re-oriented table,
   C3 runs the neutral table = ① baseline, no edge. Reversing both axes yields a passing table
   from the SAME 25 values — the magnitudes were designed right, the assembly was not.
   **AWAITING MINIMAX-C** (`MINIMAX_SYNC.md` §C3-SIZE-INVERSION-2026-08-12, items C6/C7).
   VERIFY: `python3 -m tests.test_sizing_cannot_invert` → green ⇒ an inverted orientation
   cannot load · `python3 -c "from src.data.signals.beta_core_size import compute_size as c;
   print(c('x',None,None,1.0).size_final)"` → ≤1.0 ⇒ no information buys no leverage
   OWNER: Seth (the gate) · Minimax-C (the 25 values + C7 polarity call)

1. **🟢 Service_role RESOLVED in production 2026-08-09 13:57Z.** `/health.strategy_library:
   pg_configured:true, degraded:false, consecutive:0`. ① clock live (OPEN RISK #4 below),
   §BETA-METRIC-AGG track record populated (66 signals, 60 scored). Kept here as the lesson +
   the local-Mac-side follow-on: **local `.env` still missing the real service_role key** —
   Mac-side Seth backfills (D1, D2, §OHLCV-DEAD backfill) remain blocked until Jazz pastes
   the real key. Downgraded from P0 to P2 because: (a) the immediate P0 consequence (Railway
   writes blocked, ① ② ③ unable to start) is RESOLVED, (b) all Mac-side-only work can be
   deferred without blocking product surface. **Lesson #72: a JWT that decodes is not a JWT
   that verifies.** The token carried `iss=supabase`, `ref=soupjamxlfsmgmmtoeok`,
   `role=service_role`, exp 2036 — every local check passed. It was the **anon key's signature
   spliced onto an edited payload**: byte-identical header, byte-identical 43-char signature,
   only the `role` claim differed. A signature is an HMAC over header+payload, so it cannot
   survive a payload edit — proof it was hand-assembled, not issued. Server verdict:
   `401 Invalid API key`. Almost certainly an earlier agent that needed service_role, had only
   anon, and produced one. **Never validate a credential by decoding it; validate it against
   the server that issued it.** Now enforced in `build_l1_observations.py --diagnose`, which
   probes for ROWS (real anon returns 200/0 rows under S-94 RLS, so status alone also proves
   nothing). Forged copies purged from `.env` and both `.claude/**/settings.local.json`
   (12 entries); never git-tracked (`.gitignore:42`).
   VERIFY: `bash -c 'set -a; . .env; set +a; curl -s -H "apikey: $SUPABASE_KEY" "$SUPABASE_URL/rest/v1/ohlcv_daily?select=symbol&limit=1"'`
   → `[{...}]` = real service_role · `401` = forged/stale · `[]` = anon under RLS, still blocked
   → **currently returns `401` (no local key) — expected, deferred**
   OWNER: Jazz (dashboard → Project Settings → API Keys → service_role → paste into `.env` —
   follow-on, not P0)

   **Lesson #71: a security linter's silence is not safety.** Four of the worst exposures were absent from the advisor's 11 errors — it excludes permissive SELECT policies, so `cis_scores` was world-readable and unflagged. Audit `pg_policies` / `pg_proc` directly.

2. **🟡 External probe live 2026-07-30, unproven** — `cometcloud-external-probe`, every 2 h,
   **outside the monitored process** (5 checks: liveness · the endpoint that died · Mac-push
   freshness · security-regression on the revoked RPC · anonymous read). Worst-case blind window
   **10.4 h → 2 h**. Still open because: it runs only while the desktop app is open, it has never
   fired on a real failure, and **an unfired alarm is not a proven alarm**. Downgrade to 🟢 only
   after it catches something, or after a deliberate induced failure confirms it fires.
   VERIFY: `ls /Users/sbb/Documents/Claude/Scheduled/cometcloud-external-probe/` and check the
   last run reported `✅ probe OK`; no run in >3 h ⇒ the probe itself is dead.
   OWNER: Jazz (keep the app open) / Seth (induce a failure to prove it fires)

3. **🔴 The VDB's durable layer is not finished — and one gap was silently losing research.**
   *(merged from two entries: "tables are empty" and "the graveyard was in a cache" are the same
   problem seen from the data side and the mechanism side.)*

   **(a) A table that was never created.** `scripts/supabase_strategy_records.sql`, written
   2026-07-26 specifically to move the strategy record library off a 24 h-TTL Redis key, **was
   never applied.** `_pg_upsert()` POSTed to a nonexistent table, caught the exception, logged one
   WARNING, returned False, and `upsert_record()` fell back to Redis with `_TTL = 86_400`.
   CLAUDE.md calls the graveyard the asset; the asset sat in a cache that expires daily, for 12
   days. **It survived because the warning fired on EVERY write — an always-on warning carries no
   information.**

   **🔴→🟢 THE CLASS, NOT THE INSTANCE (S-166, 2026-08-15).** This entry described ONE table
   that was never created. On 2026-08-15 the same check run across the whole codebase found
   **ELEVEN more** — `beta_core_nav_q(_meta)`, `beta_core_nav_size(_meta)`, `strategy_params`,
   `execution_intents/outcomes`, `fusion_paper_nav/lifecycle`, `crowd_clock_log`. This file's
   own header had called C2 and C3 "complete; 79/79 smoke green" while neither sleeve had
   anywhere to write a row. **The risk was written here, the lesson was recorded, and it still
   recurred eleven times — because what got fixed was that table, not the absence of any
   comparison between the set of tables the code writes and the set that exists.** Fixing an
   instance and calling the class closed is how one bug gets renamed eleven times.
   All 11 created; verified live `23/23 present, missing: []`.
   VERIFY: `python3 -m tests.test_every_written_table_exists` (offline: manifest matches source)
   · `curl -s -H "X-Internal-Token: $INTERNAL_TOKEN" $RAILWAY/internal/schema-drift` → `missing: []`
   OWNER: Seth (both halves shipped) · **🟢 2026-09-20 close (M-189)** — `scripts/supabase_fusion_paper.sql`
   no longer grants PUBLIC writes: only `DROP POLICY IF EXISTS` + history comments remain, no live
   `CREATE POLICY` lines. All 7 migration files (`supabase_setup`/`supabase_all_tables`/
   `supabase_fusion_paper`/`supabase_migration_cause_history`/`supabase_migration_week10`/
   `supabase_migration_timeseries`/`supabase_strategy_records`) verified clean; the 3 files that
   DO have live CREATE POLICY use `service_role_only` posture (fusion_paper_regime_track /
   fusion_paper_state / strategy34_books). `tests/test_no_sql_file_grants_public_access.py` 5/5
   PASS (no-PUBLIC-grant / no-TO-clause / no-false-denial / OR-trap-doc / leaked-tables-named).
   "Next person re-runs it" failure mode is now mechanically impossible at the file level
   (S-167 in production + structural guard in preflight).

   Migration now applied (RLS on, anon revoked); `/health` gained
   `data_layer.strategy_library`; `tests/test_strategy_durability.py` 4/4 in preflight. Kept OUT of
   `degraded` on purpose: losing durable research does not make the API unhealthy, and conflating
   them would either 503 a healthy API or bury data loss under a green tick.
   **Service_role RESOLVED on Railway 2026-08-09** (see risk #1 below) — Railway-side writes work.
   `/health.strategy_library: pg_configured:true, degraded:false, total:0, last_ok_ts:null` (no
   records yet because no record has been written since the migration). **Mac-side backfill remains
   P2** awaiting local `.env` service_role key (Jazz's call). DUAL_WRITE=0 flip safe to schedule
   once first record lands and Postgres ≥ Redis is verified.
   **Task #20 "VDB 落库" was logged COMPLETE but only the asset half landed** — `asset_embeddings`
   72 rows, strategy side absent. A half-migration recorded as done is how the next agent stops looking.

   **(b) Tables that exist but are empty.** `asset_embeddings_history` (risk #1) ·
   `risk_meter_history` 0 rows (M-WO-D2) · **`decisions` 0 rows / `entities` 1 row.**
   ARCHITECTURE.md says the deepest object is the entity-and-decision, not the asset; that is where
   the claim lands, and it is empty. **Either wire them or demote the claim — an empty table cannot
   carry an ontological argument.** `signal_outcomes` also ends 2026-05-03, so the response surface
   omits the last 3 months.
   VERIFY: `select count(*) from strategy_records;` → 0 ⇒ backfill pending ·
   `curl -s $BASE/health | jq .data_layer.strategy_library.degraded` → true ⇒ writes not durable ·
   `select count(*) from decisions;` → 0 ⇒ ontology claim still unbacked
   OWNER: Jazz (service_role → risk #1; judgement call on the ontology) · Seth (backfill, extend
   signal_outcomes) · Minimax-A (M-WO-D2)

4. **🟢 ① beta_core: v2 inception LIVE 2026-08-09 13:57Z.** `/internal/beta-core-clock`
   returns `{"configured":true,"marks":1,"started":true,"inception":"2026-08-09",
   "last_mark":"2026-08-09","days_since_mark":0,"missing_days":0,
   "gate_days_remaining":59,"stalled":false}`. Migration ran (v2 row present),
   service_role works (`/health.strategy_library.pg_configured:true, degraded:false`),
   the loop fires and writes. **60-day SHIP-ready gate opens 2026-10-08** (was
   2026-10-初 per OVERSIGHT §3). Kept here as a verification record + monitor; if
   `marks` stops advancing or `stalled:true` flips back, escalate P0.
   VERIFY: `curl -sm 15 -H "X-Internal-Token: $INTERNAL_TOKEN" "$BASE/internal/beta-core-clock"`
   ⇒ `marks≥1, started:true, gate_days_remaining:59-58-...` ⇒ loop firing.
   `stalled:true` ⇒ escalate P0.
   OWNER: Seth (verify) · Jazz (service_role → resolved 2026-08-09)

   *Original entry, for the record (kept as the lesson, not the status — see header above).*
   S-103 + S-105 refuted the ④-layer cross-sectional market-neutral L/S construction (β confounded
   across all 5 tiers, cost 4.6 %/yr > ~3 % best-case effect). **3 of 5 live L/S paper books
   (causal_paper / combined_book / scalable_paper) demoted to RESEARCH RECORDS on 2026-08-08**
   (commit `fc4d331`). The product book `beta_core_paper` (commit `121b54c`) is the only forward-clock
   with a SHIP floor in mind: equal-weight hold-the-panel (no short, no neutralisation) + ex-ante
   vol target + ⓠ regime override caps gross at {0.0, 0.5, 1.0, 1.3}, marked daily to Supabase
   `beta_core_nav` with `benchmark_nav` alongside `nav` so excess is arithmetic. S-123 fix in code
   (commits b8af18b + c0516f9) AND migration `scripts/supabase_beta_core_reinception.sql` BOTH
   deployed & applied by 2026-08-09 13:57Z. **A book that is silent cannot be told from a book
   that is alive but writes were dropped on the floor (S-105 redux) — the silent period
   (2026-08-08 → 2026-08-09) was both; the S-123 fix was the half that was visible. The migration
   was the other half, and was the harder dependency to see because it sat in Supabase, not in
   code.** Full audit (S-103, S-105, S-106, demotion reasoning, anti-amnesia state recovery,
   S-123 inception identity) lives in OVERSIGHT_2026-08.md §0 + §3 + §7 + REFUTATION_LEDGER.md S-124.
   · Seth (verification probe — see VERIFY; re-run once Jazz pastes key) · Minimax-A
   (M1: keep T1 engine push alive — Mac T1 health drives this loop's panel).

5. **🔴 CoinGecko 日线整体错位一天 (S-191, 2026-08-20).** 我们 `trade_date=2026-08-19` 的
   BTC close 是 **64,686.30**;Hyperliquid 的 **08-18** close 是 64,696,08-19 是 69,323。
   ETH(我们 1,916.40 / HL 08-18 1,916.8)、SOL(77.00 / 77.036)同样。**写入端用【写入日期】
   打标签,不是【K线日期】** —— 07:49 跑的 loop 把昨天的收盘记在今天名下。
   影响:coingecko 全部 25 个 symbol 的收益序列整体滞后一天 · 与 `binance_hist`/`eodhd` 拼接
   就是两套日期口径的 splice(**S-106 在日期轴上的重演**)· 所有纸面账本 mark 晚一天。
   **这是我今天回答"暴涨抓到没有"时答错的原因** —— 库里说 08-19 BTC +0.30% 是平的,
   HL 说 +7.15%,ETH +17.57%。**Bar 知道自己是哪天,写它的进程不知道。**
   缓解(已做):`hyperliquid` 采集器上线,日期取自 candle 自带 epoch,`ohlcv_daily_canonical`
   的 source 优先级里 hyperliquid 已经排在 coingecko 之上,所以有 HL 行的地方会自动改用。
   **未做:coingecko 写入端本身没改,历史也没回补(那是改写历史,需要决定)。**
   VERIFY: `curl -s -X POST https://api.hyperliquid.xyz/info -d '{"type":"candleSnapshot","req":{"coin":"BTC","interval":"1d","startTime":1755648000000,"endTime":1755907200000}}' -H 'Content-Type: application/json' | python3 -m json.tool | head -20`
   → 对比 `select trade_date, close from ohlcv_daily where source='coingecko' and symbol='BTC' order by trade_date desc limit 3;`
   两者应当同日同价;若我们的 D 等于 HL 的 D−1,bug 仍在。
   OWNER: Seth(写入端 + 是否回补历史 → 需 Jazz 决定)

***RETIRED 2026-09-01 为 #0 腾位:🟢 S-104 T2 fan-out fix** — 2026-08-09 已在生产验证(`git_sha=5a54d1c1`, `fanout_total_ms=634`, `degraded_branches=[]`),其 VERIFY 是回归检查而非风险。正文进 `PROJECT_STATE_LOG.md` / 台账。**它带的那句教训单独留下:***
   *代码修好而它的数据迁移没跑,是修了一半* —— S-123 的修复本身就带了迁移,
   而迁移要 service_role,于是修复挂在另一条 OPEN RISK 上。

---



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

