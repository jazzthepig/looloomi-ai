# PROJECT_STATE.md — the living single source of truth

**Last updated:** 2026-11-27 19:17 UTC (Seth · 高维线 — **S-930 补(11-27)**:我 11-26 报 Jazz 的「S-923 扎堆检验也过了」是错的 —— 评审轮 11-26 12:55 已裁(按天等权用配对日读,两格都不过,等 T-444-v2);匹配板与旧头部已更正。**复核定为必经**(RULEBOOK「两条报告规矩」:判据算式写进预注册;交互会话的数标「未复核」,复核前不进匹配板 / 状态结论)—— S-925 – S-929 目前都是未复核。 **Jazz 11-27「决策链路还是出了问题」⇒ S-930**:四轮模拟都由 Jazz 纠错 —— 规则没有现行版(空单定稿只在 T-370 卡备注,教义还留旧写法)、研究脚本各写口径、预注册只核自己、尺子没清单、结论没复核。已落地:`docs/RULEBOOK.md`(现行规则一页 + 研究前三问)、`src/data/evaluation/house_rules.py`(数值只此一份,`setup_watch` 改为取它)、`tests/test_house_rules.py`(文档 = 代码;s929 起的研究脚本必须声明 `HOUSE_RULES`)、CLAUDE.md 必读表一行。 **两件等 Jazz 定的事先模拟了(Jazz 11-26「先模拟一下看看要不要做」;台账 S-925 / S-926)。** ① **World50 的链上门槛(S-925)**:严格版(有链上形式 + 链上日成交中位 ≥ 10 万美元)12-31 会换掉 17 / 50 家(占市值 16%,往下够到第 96 名),历史跟踪误差 5.2%/年 > 事前定的 5% ⇒ 建议**原账不改、另开「World50 · 链上可持有版」**;只要「有链上形式」则换 8 家(三星、四大中资银行里三家 + 中国银行、罗氏、寒武纪、汇丰)、2.4%/年。回放里门槛版收益高很多(+2 / +8 个百分点)是倒着用今天状态的偏差,不是理由。按 5 亿美元规模,成交额下限还得往上调,到 100 万美元/天就凑不满 50 家。② **联合模型 z 接进 ① 的仓位(S-926)**:不建议。两条规则(z < −1 减半 / 线性)对同平均仓位的恒定持有,前段 +10%/年、后段为负,打乱分位 0.75 / 0.85;**最大回撤反而更深** —— 2025-10 → 2026-06 那次 −53% 里规则 A 平均仓位 0.91,没看见。z 继续只做描述 + 前向记分,12-05 起 live 行结算。Jazz 11-27 追问「深熊为什么不直接空仓 / 做空」⇒ **S-927**:问题在信号不在动作 —— 深熊段(2025-10 → 2026-06,BTC −53%)z < −1 只占 18.7% 的日子、多在反弹里,z 一响就空仓 / 做空反而亏 −54% ~ −56%;③ 层的趋势三态 R6(前向账今天这一格的主臂)那段只亏 −15.7%,代价是上涨只拿三到六成、净值离 2025-01 高点还差 29%。R6 今天 −0.3(11-20 斜率转负);它的前向账从 11-19 起在等 CG 的 BTC 价。**Jazz 11-27:这种跑法不合我们的标准(空头当仓位拿、条件一到就机械动、单信号)⇒ S-928 按规矩重做**(⓪ 周线 × 边际流动性确认才防守、多头书空仓、空头只用写好四样出场的票)。**结果没过门**:崩塌削掉 0 / 46% / 49%(要 ≥ 50%)、回本时间不比满仓短 —— 确认来得晚(见顶后跌 29 – 40% 才确认);**但两层成了**:流动性交叉后三段上涨拿到 98 – 100%(只看价格的防守只拿到 35 – 59%),空头票两段都赚(+0.27R / +0.67R、盈亏比 3.5 / 3.7)。今天 D1 在防守(10-26 起)。**Jazz 11-27:S-928 的空头票也不对 —— 我用了 3R 目标 + 1R 保本 + 风险定尺寸,这是 S-612 / S-865 / T-370 v1 已经否掉的写法 ⇒ S-929 改回 T-370 v1**(⓪ 签名的 short 状态 + 形态 #1 生产口径:收盘破 20 日低价、资金费正、认错线 20 日低 × 1.01 ≤ 8%、一次进满、28 天、不提前止盈、档位 10% / 币):每张 +10.4% 名义(S-928 写法 +3.3%),两段都过票的门(盈亏比 3.97 / 4.68);不经 ⓪ 的同一套触发留出段只有 +3.8%;账户层仍差一点(2022 削 49.9%、2025-26 削 50.4%、2021-05 没进 ⓪)。今天开着两张:BTC 11-12 @71,423、ETH 11-13 @1,929,浮盈 +15% / +12%,12-10 / 12-11 到期。等 Jazz 定:World50 两本并存与否。S-924 盲复算(B 道 T-444)在跑。)

 **更早:** 2026-11-26 10:58 UTC (Seth · 高维线 — **策略层第一次上「特征组合 + 模型」与「参数面」,结果出来了(Jazz 11-26「有没有做特征组合还有算法优化的?」→「按你建议来先做」;台账 S-920 – S-924)。** ① **S-921 参数面 = 平台**:带 EMA 过滤的突破回踩做多,回看 10 – 60 × 吊灯 2 – 5 倍 ATR 的 16 格两段全为正、全高于同倍数随机进场;进场增量每张 +0.14 ~ +0.24R,回看 40 最好;默认参数不换(换就是挑最优点)。② **S-920 meta-labeling**:做多一侧没站住(差一点);**做空一侧两格四条判据全过** —— 候选单整体每张 −0.09R,模型挑出的上三分之一 +0.24R(逻辑回归)/ +0.33R(提升树),三年都更好。我事前押的正好相反(P1 / P2 / P3 都错)。**S-923 扎堆检验(11-26 12:55 评审轮更正:「按天等权」按配对日读两格都不过,−0.01 / +0.07R ⇒ 按事前写的降为「扎堆造成的」,正式数等 T-444-v2;此处原写「也过了」是错的)**。下一步 **S-924 盲复算**(B 道 T-444 照书面口径另写特征拼装与判据,不读 A 的脚本);对上了才建纸面前向写入端(S-925)。③ **S-922 修好**:按币资金面前向表 `asset_flow_forecast_daily` 上线 19 天 0 行 —— 找周一读的是「最新 8 行」(每天 35 个币 ⇒ 8 行同一天),后面还排着 17 秒的 RPC 走 10 秒客户端。修完部署后第一轮 105 行落表(11-09 / 11-16 / 11-23 各 35,标补写),循环痕迹 `_asset_flow_forecast` ok;11-30 起按时写,12-11 第一次结算。匹配板 `docs/research/s916_matching_board_2026-11-26.md` 已写进 ① ②。)

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

3. **🟡 IC 乘数这一层留不留(S-702)。** 更正 10-30 的说法:CIS 的 IC 乘数读 Redis `cis:factor_performance`(纸面平仓喂,372 样本,**活着**),等于 1 是因为没有一个因子过 |r| > 0.10;`cis_regime_fitness` 是一张 0 行、没有读者的表,`_regime_fitness_loop` 每天往里写 0 行(有写入端没消费者)。**11-13 新事实:13:36 UTC 这条循环第一次算出了行(过了 20 个独立日的门槛),写库时 400 —— 它带的 `return_source` 这一列表里没有(`scripts/data_landing_migration.sql` 里有、线上那张表没有)。没修:补上这一列,这张没有读者的表就开始有行;删掉这条循环也行 —— 留不留是同一个决定。**同一批数据:90 天窗口 M / O 的 IC 是负的(18 个独立日,噪声),365 天全是 +0.03~0.12(185 个独立日,t≈1.6);套上去对今天排名的影响:前 10 名 9 个不变、名次相关 0.976。**要 Jazz 定:** 留(365 天 + 门槛 + 显著性)还是关(停循环、删表,CIS v2 本来不靠这层)。
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

7. **🔴 CoinGecko 订阅已被 Jazz 停掉(11-21 亲口),overage 计费现在正在跑,12-01 才恢复。** 仓库侧已修(`401/403` 开 6 小时长闸,见头部)⇒ 仓库侧从「打满日预算」变成 **~4 次/天**;**Mac 侧不在闸门内,实测有两个「不同的 401」,别混成一个**:**(a) `cg_news_listener` —— 实测 401,而且已经瞎了 23 天**(`_logs/cg_news_listener.log`:最后一条成功 2026-10-29 18:49,之后每小时 3 次重试全是 `401 Unauthorized`,≈96/天,累计 2,732 次)⇒ **它拿的是 10-29 轮换前的那把旧 key**,**换新 key 也不能让它活过来,只能让它换个新的 401** ⇒ 停它是唯一办法;**(b) `cis_scheduler` —— 计划里那个「≈1,272/天」已经过期**(本轮实测 `cis_scheduler.log.2026-11-21` **0 次 coingecko 命中**,23:02 JST 正常完成)⇒ **它已经改读仓库的 L2 了,别照着过期数字去停它**;⚠️ 但它每小时推 `/api/v1/cis/universe`,而那个端点在 T2 预计算过期时**会扇出到 CG** ⇒ 它是**间接**驱动仓库侧 CG 调用的人。**(c) 待 Minimax 核实**:`data_fetcher.py:1397/1440/1505/1990` 四处**裸 `requests.get`**(绕过它自己的限速器)、`market_compass.py:36` 明文 Pro key —— 文件还在,**是否还在活跃路径上要自己量,别照抄旧登记**。**本仓库不动 Mac 侧代码(规则 3a/3b)**,登记在 `MINIMAX_SYNC.md §IN-FLIGHT` 第 62 行。
   VERIFY: 部署后 `curl -s https://web-production-0cdf76.up.railway.app/internal/cg-quota -H "X-Internal-Token: $INTERNAL_TOKEN" | python3 -m json.tool` ⇒ 看 `daily_budget` / `used_today` / `breaker_reason` / `total_calls_today`;**注意分清「被预算挡在出网前」和「真撞到 401」两种暗**(见头部 ⑦);12-01 恢复后 `breaker_open` 应回 false。
   OWNER: Minimax(Mac 侧停手)· Jazz(恢复订阅 / 决定 key 与预算)· Seth(仓库侧闸门已上线,核对读数)

   **11-22 08:50Z 更正与新增(Seth):** ① **仓库侧其实从 11-20 起就没再出网**(Seth 11-21 读 `/internal/cg-quota`:`daily_budget=200`、`used_today`(11-20)=**7,915**、`remaining=0`、请求被预算挡在出网前)⇒ **漏掉的钱就是 11-20 那 7,915 条**;我 11-21 推的 401 长闸**今天是睡着的**,它的价值在 **12-01**(订阅若没真恢复 ⇒ 第一条 401 就开 6 小时闸 ⇒ ~4 次/天,不是 16,000)。② **官方档已卡在 11-19**(缺 11-20 / 11-21 两批;下一次发布尝试 11-23 06:00Z)⇒ **兜底开不开是 Jazz 的口径决定,但顺序是死的:先有来源标记再开** —— `cis_official_daily` 只追加 + 触发器拒 UPDATE/DELETE ⇒ 发出去的档事后补不了标记(**标记今天已在仓库侧补上并推**)。③ **价腿活着**:`/api/v1/ohlcv/BTC` 的 `binance_hist` 已到 **11-21**(Railway 侧写)⇒ 停 Mac 侧**取数**不会断它,停**写端**才会。

 **更早:** 2026-11-21 04:15 UTC (Seth — **CoinGecko 额度收敛 S-895 阶段 5:剩下的重复取数收敛 + 调用点级单一活路守卫。** 这一段是整个计划里**收益最低、形状最值钱**的一段:省的那点调用是低把握的小头(计划估 ~50–230/天,**推导不是实测**),真正交付的是「**以后开不了洞**」。**① 收敛了什么(按代码重读一遍,比计划多找出三条纯重复):** `/coins/{id}` **4→1**(`data_layer.get_cg_coin_payload`)、`/coins/{id}/tickers` **2→1**(`get_cg_tickers_payload`)、`/coins/list` **3→1**(`get_cg_coin_list`)+ **1 条登记例外**(永续市值回填要 `status=active,inactive`,而 `/coins/list` 的响应里**没有 per-coin 的 status 字段**(实测只有 id/name/platforms/symbol)⇒ 拿到全量也**本地筛不出** ⇒ 必须自己打)、`/coins/categories/list` **2→1**(`get_cg_category_list_payload`)、`/coins/categories` **2→1**(`get_cg_categories_payload`)、`/search/trending` **2→1**(`get_cg_trending_payload`)。⇒ **收敛的不是「端点」,是「端点 × 参数」** —— 判据是 `SPINE.md:188-191`「不能给出不同答案 ⇒ 是重复」:同端点 + 同参数 ⇒ 重复;**参数形状不同 / 失败语义不同 ⇒ 问的不是同一个问题** ⇒ 登记在册,不算重复。**② 为什么又加一个守卫(文件级不够):** `test_cg_call_sites.py` 管的是**文件级**(哪个文件可以打哪个端点),它**看不见「同一个文件里写了两遍同一个形状」** —— 而那正是阶段 5 里真实发生过的事(前端 trending 栏 + CIS 的 trending map 原本在同一文件各写一遍)。⇒ 新增 `tests/test_cg_single_live_path.py`(**调用点级**,已挂进 `scripts/preflight.sh` stage 3):两张表 —— `SINGLE_PATH_ENDPOINTS`(必须**只有 1 个文件、1 个调用点**)与 `EXCEPTIONS`(登记在册的多活路,每条必须写清**为什么它问的不是同一个问题**)。**登记不是空白名单**:理由为空/太短 ⇒ 红;登记的调用点数与代码对不上 ⇒ 红;代码里多出未登记的文件 ⇒ 红;表里登记的端点代码里已没有 ⇒ 红(**「登记要跟着代码一起退役」**)。⇒ **下一个 agent 想开第二条活路,必须先在这里写一行理由 —— 那是一次有意识的动作,不是「顺手加一行请求」。** **③ 一条自指的坑(我自己写出来的那个形状):** 新的计数 helper 最初写成 `_CG_EXTERNAL_CALLS.get("/coins/{id}", 0)`,而扫描器的判据是「`.get(`/`.post(` 的源码段里含 CG 路径字面量」⇒ **一句记账语句被当成了三次外部调用点** ⇒ 守卫开始说假话 ⇒ **这正是 `SPINE.md:170-174`「一个因错误理由变绿的检查,比红的更坏」,而且是我自己写的那个形状** ⇒ 修法:key 从**变量**传(`_count_external(endpoint_key)`),让扫描器看不见字面量。**④ 跨 lane(Mac 侧)只登记不动:** Mac 引擎侧还有 **2 处同形状的 `/coins/{id}`** 与 **4 处裸 `requests`**(`data_fetcher.py:1397/1440/1505/1990`,绕过它自己的限速器)⇒ 登记在 `MINIMAX_SYNC.md §Seth-1121a`,**本仓库没有改 Mac 侧任何一行**(规则 3a/3b)。**⑤ 线上 CoinGecko 仍然全暗(04:13 UTC 探针):** `/coingecko-markets` 仍 `{"data":[],"count":0}`,`macro-pulse` 的 CG 两块仍全空 —— **而那是在 UTC 日预算重置之后 4 小时 13 分** ⇒ ledger §十三 的「日预算烧穿」被**降级(不是证伪)**:它单独解释不了「重置后仍然暗」,除非 4 小时内再烧 16,000(≈67 次/分钟,比我们估的稳态量级高一个数量级)⇒ **要么有个热循环,要么根本不是预算**。`api.coingecko.com/api/v3/ping` 正常 ⇒ **CoinGecko 服务没宕** —— ⚠️ **但那是免费层主机,不是 `pro-api` ⇒ 它不证明我们的 Pro 计划/key 还有效**(我差点把它当成「key 没问题」的证据;这是本集 episode **第四次**「一个绿的检查只证明它量的那一维」)。**只有 CG 暗**(同一次响应里 Alternative.me fng=12 ✓、DeFiLlama tvl=66,370,856,839 ✓、制度源 RISK_OFF ✓)⇒ **不是出网路径坏了**。**CMC 兜底确认是哑的 —— 这次是「读出来的」**:来源标签代码(`data_layer.py:2409-2415`)是 `if _cmc_global and _cmc_btc: "coinmarketcap" / elif 任一: "coingecko+coinmarketcap" / else: "coingecko"` ⇒ **`data_source == "coingecko"` 就是「CMC 两个来源同时为空」的证明** ⇒ Railway 上那个变量**仍然不叫 `CMC_API_KEY`**。**⑥ 我今天没做、也不会自己做的两件事:** 没改日预算 16,000(改预算是把停机线往后挪一格)、没轮换 Pro key(轮换会让 Mac 侧那份明文硬编码 key 立刻挂,**顺序错了是自伤**)。**⑦ 唯一能分开「预算 vs key/上游」的读数仍然只有一个,且需要 Jazz 的 token:** `GET /internal/cg-quota` ⇒ `used_today` / `budget` / `breaker_open` / `unbudgeted_today` / `trips_total`。**我没有授权拿手上的环境变量去打生产内部端点 ⇒ 这一条我不自己做** ⇒ 需要 Jazz 跑一次并把四个数回贴。**⑧ 一个诚实的自指:做完阶段 5,我依然答不上「CG 是被预算拒的还是被 key 拒的」** —— 把「我答不上来」写清楚,比把形状做得漂亮更值钱。)
 **更早:** 2026-11-20 15:50 UTC (Seth — **CoinGecko 额度收敛 S-895 阶段 4:读路径 TTL 口径统一 + 预热只热本地缓存。** Jazz 11-20 点头「做:120s → 300s」。**这一阶段最值钱的一条不是改了什么,是计划里那条前提只对第一轮成立:** 一次读穿三层(进程内 `data_layer._cache_get` / Redis / ASGI `public_cache`(`max-age=N` ⇒ `stale_age = min(max(N*12,300),3600)`)),预热循环每 **240s** 一轮 —— 计划 §阶段 4 写「max-age ≥ 预热间隔 ⇒ 预热命中新鲜条目」,而 **HIT 不重置条目的年龄**:t=0 存下、t=240 命中(240 秒老但还没过期)、t=480 过期 ⇒ 触发后台刷新 ⇒ **一次外呼**。⇒ **预热一条外网路径的代价 ≈ 1 次外呼 / 2×max_age,不是 0** ⇒ **「调大 TTL」本身不省外呼,只是把刷新周期拉长;真正把外呼拿掉的是「把外网路径从预热清单里拿掉」** —— 所以主改动是**拆表**,TTL 对齐只是让它别那么冷。**① 改了什么:** `get_cg_markets` 内存 TTL 120→300(原来的 120s **恰好等于前端轮询间隔** ⇒ **每次轮询都踩在过期线上,一次不落**)、`get_macro_pulse` 内存层 120→300(Redis 本来就是 300 ⇒ **进程内那层永远是短的那一层**)、ASGI `max-age` 120→300(`/coingecko-markets` 与 `/macro-pulse`;相邻四条本来 ≥300 不动);`_WARM_PATHS`(25 条)拆成 **`_WARM_PATHS_LOCAL`(12 条)+ `_WARM_PATHS_EXTERNAL`(13 条,每条写明打到哪一家、代码在哪一行)**,预热循环**只遍历 LOCAL** —— 依据是 `SPINE.md:184-213`「预热是缓存维护职责,不是采集职责」:预热顺手把采集做了 = 有了**第二条活路**,而那条活路不在任何 `loop_attempt` 的记账里 ⇒「今天打了多少」永远少一块。**② 分类我错了两次**(逐跳读代码才知道):`macro-events`(RSS + DeFiLlama Raises)、`protocols/universe`(DeFiLlama)、`cis/universe` 与 `portfolio/risk-meter`(T2 预计算过期时扇出到 CG / DeFiLlama / Alternative.me)—— 四个都**是**外网 ⇒ **13 EXTERNAL / 12 LOCAL,并集仍是那 25 条**(少一条 = 有人把一条路径从登记里拿掉了)。**③ 省多少(代码推导,不是实测 —— 11-21 把 ASGI 层也算进去重算过一次,区间比上一版宽):** `get_cg_markets` **~720 → ~240/天**(省 ~480 —— 外呼节奏由**内层 TTL(300s)与前端轮询网格(120s)**共同决定:原来 120s TTL **恰好等于**轮询间隔 ⇒ **每次轮询都踩在过期线上,一次不落**;改 300s 后落在 ~360s 一次 ⇒ **240/天,不是 288**)。`get_macro_pulse` 的 handler 从「每轮询一次(300s)」变成「每 ~600s 一次」(ASGI `max-age=300` 与轮询 300s 的相位)⇒ 每次 handler 至少 2 次外呼(fng + btc;`/global` 有 180s 缓存、defi 有自己的 TTL)⇒ **~288–576/天**(原来 ~576–1152)⇒ **省 ~290–580**。⇒ **合计 ~770–1,050 次/天 CoinGecko**(计划写的 ~790 落在这个区间的下沿);⚠️ **是区间不是点值** —— `macro_pulse` 一次 handler 到底打 2 家还是 4 家我数不准 ⇒ **真要验收省了多少,看 24h `used_today` 的差值,不要看推导**(`unbudgeted_today` 数得出闸门内总量,数不出「同一个 handler 打了 4 家」的分布)。⚠️ **预热拆分本身 ≈ 省 0 额度**(那 13 条的内层 TTL 本来就长:1800s / 14400s / 4h / 60min)⇒ **它的价值是架构 + 掐掉 `calculate_cis_universe` 那个间歇性 10-provider 扇出的触发器** ⇒ **省额度的主力是 TTL 口径统一(不是拆分);量级主力仍是阶段 3。** **④ 代价(诚实):** 13 条路径不再被预热 ⇒ 安静期之后的第一个访客自己付计算时间(最重一条 `protocols/universe` **8–90 秒**);缓解:`public_cache` 把**慢响应**(≥0.5s、≤400KB)写进 Redis(键活 ~30 分钟、条目可用 ~20 分钟)⇒ 部署后的冷启动这关是过的。**⑤ 守卫:** 新 `tests/test_cache_warm_does_not_call_external.py`(5 条,已挂 preflight)—— 构造(`for` 必须遍历 `_WARM_PATHS_LOCAL`、旧名 `_WARM_PATHS` 不得再出现)+ 集合纪律(两表互不相交、并集 = 冻结的 25 条、理由必须指到代码)+ 登记跟代码对得上(AST 读路由装饰器下的第一跳)+ 分类是真的(EXTERNAL 至少一跳碰到网络入口、LOCAL 一跳都不许有)—— **做过变异测试**(把 EXTERNAL 塞进 LOCAL ⇒ 红;循环改遍历 EXTERNAL ⇒ 红);⚠️ **诚实**:第 4 条的调用链是**手工登记**的(全仓库调用图会炸:`get`/`report`/`main` 同名候选几百个),守不住「有人把链路藏起来」,前三条才是硬的。**⑥ 访客可见的新鲜度 120s → 300s(Jazz 已点头)—— 但「用户可见粒度不变」这句我收回,三个数字要分开说:** **① 新鲜窗口 = 访客看到的数字有多老,由「内层缓存 TTL」决定,不由 ASGI `max-age` 决定**:`/coingecko-markets` 内层**内存** TTL 300s(⚠️ **Redis 那层对这条路径根本不存在** —— `get_cg_markets` 只 `_cache_get`/`_cache_set`,**从不 `_redis_set`** ⇒ `data_layer.py:1967`/`:1976` 那两次 `_redis_get` 永远是 miss ⇒「出错回落旧 L2」是**死代码**,上游一挂这条路径返回 `[]` = 「未测量塌成空」);`/macro-pulse` 内层内存 300 + Redis 300 ⇒ **访客看到的数字最多老 ~5 分钟**(原来 ~2–4 分钟)。**② ASGI 层**:`max-age` 120→300 ⇒ 窗内 HIT 不跑 handler;超窗 ⇒ 先发一份 STALE **再**后台刷新 ⇒ 后台刷新命中内层缓存 ⇒ **不打外网**。**③ 旧值兜底上限 —— 这次 TTL 对齐里唯一一个「用户可见变差」的地方**:中间件**只解析 `max-age`,不采纳路由里声明的 `stale-while-revalidate`**(`public_cache.py:151` `storable()`)⇒ 旧值上限 = `min(max(max_age*12,300),3600)`(`:38`)⇒ **120s 时 1440s(24 分钟)→ 300s 时 3600s(60 分钟)** ⇒ **刷新打不通时,同一份旧正文能连续送到访客面前 ~55 分钟(原来 ~19 分钟)**。⇒ **Jazz 点头的措辞「列表最多晚 3 分钟」说的是 ①(新鲜路径);③(旧值路径)不在那次点头的射程里** ⇒ 登记为待修项(见 ⑦a)。**⑦ 这一阶段顺手查出来的三条(只登记,不改 —— 每一条都要动别人的口径):** (a) **中间件不采纳声明的 `stale-while-revalidate`** ⇒ 头里那个数只对**下游共享缓存**有效(它们按 `age`+`max-age` 算 ⇒ 我们发 `age`,所以下游没被骗),**对我们自己无效**;要修就得改 `storable()` ⇒ 那会让 crowd-clock(900)/defi-overview(600) 等端点提前失效 ⇒ **可能增加外呼**(与本阶段目标相反)⇒ **单独一个阶段、单独量,不在本轮**。(b) **`get_cg_markets` 的 Redis 层不存在** ⇒ 跨 worker 不共享 + 失败回落是死代码 + 「未测量塌成空」⇒ 计划 §风险 1 已标「本轮只登记」。(c) **预热拆分之后 `/coingecko-markets`、`/macro-pulse` 不再被预热** ⇒ 我自己写在路由注释里的「预热请求拿到的是新鲜条目」**已经不成立**(这一轮把那句注释改掉了)。**下一阶段:** 阶段 5(剩下的重复取数:`/coins/{id}` 4→1、`/coins/{id}/tickers` 2→1、`/coins/list` 共用一份 TTL 缓存、`get_cg_markets_strict` 收敛 —— **Mac 侧还有 2 处 `/coins/{id}`,跨 lane 同形重复,本仓库不动 Mac 侧**)。**已上线(`efc7c517`,`/internal/build-state` 已核):** 生产上带 cache-buster 读到的头两条都对(`/macro-pulse` ⇒ `max-age=300, stale-while-revalidate=180`;/`coingecko-markets` ⇒ `max-age=300, stale-while-revalidate=60`)。**⚠️ 但这一轮撞上一个「验证方法本身会骗人」的坑,值得单独记:** 部署后第一次 curl `/api/v1/market/macro-pulse`,拿回来的头**还是 `max-age=120`**(`x-cache: STALE`、`age: 697`)—— 而 `build-state` 明明白白报 `git_sha_short: efc7c517`。差在哪:`public_cache._store` 把**慢响应**(≥0.5s、≤400KB)连同**它当时的头**一起写进 Redis(`_store` 只剔除 `content-length`/`date`/`age`/`x-cache`,**`cache-control` 留着**),`restore` 再把这份**旧头**原样回放 ⇒ 部署后那 ~20 分钟(条目可用 ~20 分钟、键活 ~30 分钟)里,这个端点**对外报的仍然是旧口径** ⇒ **「改 `Cache-Control` 之后 curl 一下看头」不是一个有效的部署验证** —— 它量的是**缓存里存的那一份**,不是**现在这段代码会生成什么**。判据必须是**绕开那一层缓存再问**:加一个 query 参数(缓存键 = path + query string ⇒ 键变了 ⇒ handler 真跑)。⇒ **本轮第 N 次同一个形状(又一次):验证手段会继承被验证对象的那一层缓存,于是它量的是旧值,而它看起来是绿的。** 和「一次失败留一个洞,而洞在 `max(trade_date)` 上完全不可见」(S-190)是同一族:**要问「现在这段代码会产出什么」,就必须绕开「上一段代码产出的缓存」。** ⇒ **推论:凡是只改 `Cache-Control`/`max-age` 的改动,部署验证必须带 cache-buster;否则会得到一个「没生效」的假结论 —— 然后有人去改代码,而代码本来就是对的。** **⚠️ 收尾时撞上的一道路障(已解,值得单独记 —— 尺子量错了东西):** `tests/test_vite_bundle_freshness.py`(preflight B-4)判的是「**最后一次改 `dashboard/src` 的提交 ≤ 最后一次改 `dashboard/dist` 的提交**」—— 这把尺子问的是「dist 的提交是不是比 src 的提交新」,而真正要问的是「**线上那一份产物,是不是当前 src 编出来的那一份?**」。`efc7c517` 只改了 `AssetRadar.jsx` 的**一行注释** ⇒ 产物**逐字不变**(49/49 文件哈希相同)⇒ **没有可提交的 dist 差异** ⇒ 老尺子永远红 ⇒ **整个仓库推不动**(seth_bot 的每个 commit / merge job 都卡在 preflight)⇒ 「再提交一次 dist」这条路**不存在**。⇒ 尺子已改成**量内容**(把当前 src 构建到**临时目录**,逐文件比哈希;量不到才退回提交时间比较),并带两条**反向对照**(改一个字节必须被抓到 —— 否则「它永远说一致」就是装饰品)。**教训:守卫红的时候,先问「这把尺子量的是不是那个东西」,再问「我怎么把它弄绿」—— 前者会产生一个永久红的仓库,后者会造出一份假的 dist。** **⚠️ 收尾核对时撞见的第二件事:线上 CoinGecko 整片是暗的(15:33–15:50 UTC 连续实测)。** 现象:`/api/v1/market/coingecko-markets?ids=bitcoin` ⇒ `{"data":[],"count":0}`;`/api/v1/market/macro-pulse` ⇒ `data.market_cap_percentage = {}`、`btc = {}`、`btc_price = null`、`total_market_cap_usd = null` —— **凡是要打 CoinGecko 的都在空,不打 CG 的都活着**(FNG/alternative.me ✓、DeFiLlama ✓、`/cis/universe` ✓ —— T1/T2 推的库数据,`stale: true`、39 分钟老)⇒ **不是这次部署带坏的**(本 commit 只改注释与 docstring),是 **CG 侧本身取不到数**;而且**空结果被缓存了**(ASGI `x-cache: HIT`、`age: 26`)⇒ **恢复了也要再等 ≤300s 才看得见**。**为什么现在没有兜底:** `macro-pulse` 的 `data_source` 仍是 `"coingecko"`(不是 `"coinmarketcap"` / `"coingecko+coinmarketcap"`)⇒ `cmc_provider` 那一层**一个字都没给** ⇒ 与已知的 `key_present: false`(Railway 上那个变量**不叫 `CMC_API_KEY`**)**完全吻合** ⇒ **兜底是哑的** —— 「装了兜底 ≠ 兜底是活的」这句话今天有了市场价。**⇒ 三种可能,只有读数才能分开:** ① **闸门日预算用尽**(16,000 ⇒ 要到 UTC 零点)② **熔断打开**(429/5xx ⇒ 300s 自愈)③ **Pro key / 上游本身拒绝**(401/5xx)。**② 已排除**:连续实测 ≥16 分钟仍暗 ⇒ 不是 300s 的熔断窗口。**① 与 ③ 必须读 `/internal/cg-quota`(要 Jazz 的 token)。** **⇒ 我的头号假设(未验证,读一次额度就能定):不是 CG 出故障,是「我们自己的日预算烧穿了」。** 算术上相容:计划自己估的「稳态 9,000–11,000/天 + 回填峰值 ~18,000」就在 16,000 这条线上下 ⇒ **烧穿之后,凡是要打 CG 的都取不到数,直到 UTC 零点** —— 今天这一片暗正好落在下午那个时间窗里。**今天 14:09 UTC 阶段 4 上线(把那 13 条外网路径从预热清单里拿掉)⇒ 但额度按 UTC 日计数,今天这一天的账已经记在旧量级上了 ⇒ 明天(11-21)才是第一个低量读数。** ⚠️ **这段是假设不是结论** —— 读一次额度就能定:如果 `used_today` 顶到 16,000 且 `breaker_open` 为 false ⇒ 就是它;如果 `used_today` 远低于 16,000 ⇒ 是 ③(key/上游),得处理 key。**⇒ 留给你的三步(顺序别换):** ① **先读额度**:`curl -s https://web-production-0cdf76.up.railway.app/internal/cg-quota -H "X-Internal-Token: $INTERNAL_TOKEN" | python3 -m json.tool` —— 看 `used_today` / `budget` / `breaker_open` / `unbudgeted_today` / `trips_total`;② **把 Railway 上那个 CMC 变量改名成 `CMC_API_KEY`** —— 它现在不叫这个名 ⇒ 兜底层是哑的 ⇒ **CG 一暗,整片就暗**(这条从「30 秒的整洁活」升级成「CG 暗时的唯一防线」);③ **读完额度再决定要不要调 16,000**(16,000 是仓库侧口径,Mac 侧同账号)。**⇒ 顺带一条方法论(和上面「验证手段会骗人」同一族,但更狠一档):** 我这一轮对阶段 4 的部署验证**只看了响应头**(`max-age=300` ✓)⇒ **头是对的、数据是空的,它照样绿** ⇒ **凡是要验「这个端点活着吗」的部署检查,必须同时看正文里有没有那个字段**(本次:`count` / `btc_price` / `market_cap_percentage`),**光看头不够** —— 头证明的是「缓存策略生效了」,不是「数据到了」。)
 **更早:** 2026-11-20 13:15 UTC (Seth — **CoinGecko 额度收敛 S-895 阶段 3:面板回填改成按覆盖差驱动 + 失败退避阶梯 —— 这才是省额度的主力。** 阶段 0 让「今天花了多少」变成真的,阶段 1 把交易路由的标记价管住,阶段 2 把 `/global` 从四个实现收敛成一条活路;**阶段 3 管的是最大的那个漏斗:`_cg_panel_loop` 每 6 小时把同一批标的的同一个 60 天窗口重打一遍,从不问「库里已经有什么」** ⇒ 4 轮 × ~59 ≈ 944 次/天,失败时 10 分钟一轮 ⇒ ~8,500 次/天。**范本早就在仓库里**(`perp_mcap_backfill.stale_coins()`:读库 → 算差 → 没有差就不打外网)—— 这一步不是发明新机制,是**把一个循环改写成仓库里已经有的那种形状**。**判据的三个「不是」(这一段才是这一阶段真正的内容):** ① **不是 `max(trade_date)`,是逐日集合** —— 一次失败留一个洞,而洞在前沿上完全不可见(S-190 的形状):「最新那根是今天」和「今天往前有一天空缺」在 max 上完全同形;② **不是跨源并集,是这个循环自己写的那个源**(`coingecko_pro_ohlc`)—— 并集回答的是「这段历史我们有没有」(S-276 的 `deepest_start`),这里要回答的是「**我要写的这个序列**有没有洞」;拿并集当跳过依据会把 `coingecko_pro_ohlc` 的行**少写**,而它在 `TRUSTED_RETURN_SOURCES` 里 ⇒ 少写它就是少一份可信价源 ⇒ **并集只用来回答「它那时候存在吗」,不用来当跳过依据**;③ **窗口左端按并集里最早的那一天裁(上市前的日子不是洞),右端按墙上时钟(今天)**。**右端为什么必须是墙上时钟 —— 差点写错的那一个:** 「右端取**库里最新的一天**」听起来更省(库里全都有 ⇒ 全跳过 ⇒ **0 次外呼**),但那样**面板会冻结**:库里最新的一天不会自己往前走,而「没有洞 ⇒ 不打外网 ⇒ 库里不前进」是个**闭环** ⇒ 面板永远停在那天,一天都不再前进。⇒ 代价是「今天那根 bar 在当天第一轮还没写进库 ⇒ 它是洞 ⇒ 打一次;写进去之后当天剩下的几轮全跳过」⇒ **每个标的每天一次**,不是 0 次。**实测(对着线上库):** `_covered_days` 读得到(`ohlcv_daily` 只读 `coingecko_pro_ohlc` 那个源,按 100 符号分块)—— BTC/ETH/AAVE 各 30 天(10-20..11-18);`_union_first_days` 一次 RPC 拿全部 ⇒ BTC `2015-07-14` / ETH `2015-08-07` / AAVE `2020-10-03` ⇒ **裁剪依据有**,不用逐标的读。**我自己踩的坑(值得单独记):首版把两个读法设成 `run_once` 的默认值** ⇒ `tests/test_cg_coin_map_manual_is_sticky.py` 里一个**既有**测试(测的是 `vendor_paired` 语义:市值裁决出来的不享受放行)**单独跑绿、批量跑红** —— 批量跑时线上库里 BTC 的窗口已经够新 ⇒ 被正确地跳过 ⇒ `seen["pairs"]` 这个键根本没出现。那个断言**没有错**;错的是**它被一个它没声明的输入改变了含义** —— 它测的是「BTC 必须被回填」,而现在这句话是**有条件的** ⇒ **一个测试的结论依赖它没声明的输入,就不是一个测试**。⇒ **读不读库是调用方的决定,不是函数的默认行为**:默认改成「没有判据 ⇒ 照旧全量回填」(旧形状,安全方向),生产那条路**显式**传,测试显式传假件,并加一条**形状守卫**(AST 匹配 `_cg_panel_loop` 里 `run_once(...)` 这个**调用**的关键字)钉住「生产必须传」。**失败退避:** 固定 600s → 阶梯 600/1200/2400/4800/9600/21600(封顶 = 成功间隔 6h),连续失败 ≥6 轮打红但**循环不停**(静默地不跑是最坏的形状)⇒ **失败峰值 ~8,500/天 → ~900/天**;稳态 ~944/天 → **~230–290 次/天**(每个标的每天一次)。⚠️ 这两个数是**代码推导,不是实测** —— 阶段 0 的 `unbudgeted_today` 落地后才能变成实测。**顺带一个不在本阶段范围的现象(单独查,不在这里改):** ~~库里 `coingecko_pro_ohlc` 最新只到 **11-18**,而 `binance_hist` / `eodhd` 都到 **11-19** ⇒ 面板那两天没写进去 ⇒ 面板循环**疑似已停或在拒写**~~ **✅ 11-20 13:15Z 查清并更正:是排程竞态,不是停摆。** 原观察写在 11-20 06:05Z,而**那轮循环在 06:07:12Z 才跑 —— 观察时刻比它早两分钟,而它写的正是 11-19 那根**;现在三个源都到 **11-19**(`coingecko_pro_ohlc` 107,538 行 / 220 标的,11-14..11-19 每天 208–210 根)。`loop_attempt` 里 `_cg_panel_loop` 近 7 天 **77 轮 `ok` + 2 轮 `panel_unavailable`(都在 11-13 当天,之后再没有)**,每轮写 12,926–12,965 行、213–214 标的成功、9–10 标的因「只取到 N 根 bar < 地板」不写 ⇒ **循环活着,面板在前进**。**教训:「某源落后一天」在 6 小时一轮的循环里是常态 —— 判停摆要看 `loop_attempt` 的 outcome 与轮次,不能只看某一天的 `max(trade_date)`**(与本次改动无关;记忆里已有「3 条管道已死」的同类记录 —— 那条记录提醒的是「别凭印象说死」,这次差点又凭印象说了一次)。**阶段 3 还剩一件没做(记在台账,不默默跳过):** `mcap_deepen.py` 的 `done` 从 `loop_attempt` 的 checkpoint 改成「从库算」(`asset_mcap_daily` 的**区间**判定)—— 计划自己标它「是加固,不是省额度」,而且它动的是另一条管道(S-700 补深);「有没有行」≠「区间满了」⇒ 单独做、单独对拍,**不夹带**进这一阶段。**下一阶段:** 阶段 4(TTL 口径统一 —— **访客可见的新鲜度 120s → 300s,等你点头**)/ 阶段 5(剩下的重复取数:`/coins/{id}` 4→1、`/coins/{id}/tickers` 2→1、`/coins/list` 共用一份 TTL 缓存)。**留给你的两步(同阶段 1,还没做):** ① **Railway 上把那个 CMC 变量改名成 `CMC_API_KEY`**(30 秒,不部署)—— 现在 `key_present: false`,兜底层是**哑的**;② **仓库侧日预算是否下调**(16,000 是仓库侧口径,Mac 侧同账号)。)
 **更早:** 2026-11-20 06:05 UTC (Seth — **CoinGecko 额度收敛 S-895 阶段 3:面板回填改成按覆盖差驱动 + 失败退避阶梯。** 回填前逐标的查库,**窗口里没洞的标的一个 `/ohlc/range` 都不打**;失败退避从固定 600s 改成阶梯 600/1200/2400/4800/9600/21600(封顶 = 成功间隔 6h),连续失败 ≥6 轮打红但**循环不停**。**判据的三个「不是」才是这一阶段的真正内容:** ① 判据是**逐日集合**不是 `max(trade_date)`(洞在前沿上完全不可见,S-190:「最新那根是今天」和「今天往前有一天空缺」在 max 上完全同形);② 覆盖读的是**这个循环自己写的那个源**(`coingecko_pro_ohlc`)不是跨源并集 —— 并集回答的是「这段历史我们有没有」(S-276),这里要回答的是「**我要写的这个序列**有没有洞」,拿并集当跳过依据会把 `coingecko_pro_ohlc` 的行**少写**(它在 `TRUSTED_RETURN_SOURCES` 里)⇒ **并集只用来回答「它那时候存在吗」,不用来当跳过依据**;③ 窗口左端按并集最早那天裁、右端按**墙上时钟(今天)** —— 「右端取库里最新那天」听起来更省(库里全都有 ⇒ 全跳过 ⇒ **0 次外呼**)⇒ **面板会冻结**:「没有洞 ⇒ 不打外网 ⇒ 库里不前进」是个**闭环** ⇒ 右端 = 今天 ⇒ **每个标的每天一次**,不是 0 次。**自己踩的坑:默认读库 ⇒ 既有测试被线上库的内容改了含义** —— 首版把判据设成 `run_once` 的默认,于是一个**既有**测试单独跑绿、批量跑红(批量时库里窗口已够新 ⇒ 被正确跳过)⇒ 那个断言**没有错**,错的是**它被一个它没声明的输入改变了含义** ⇒ **一个测试的结论依赖它没声明的输入,就不是一个测试** ⇒ **读不读库是调用方的决定,不是函数的默认行为**:默认改成「**没有判据 ⇒ 照旧全量回填**」(旧形状,安全方向),生产那条路**显式**传,测试显式传假件,并加一条 **AST 形状守卫**钉住「生产必须传」。**省了多少(代码推导,不是实测):** 稳态每 6 小时一轮 ⇒ **~230–290 次/天**(原来 ~944);失败峰值 **~8,500/天 → ~900/天**;⚠️ 阶段 0 的 `unbudgeted_today` 落地后这两个数才能从「推导」变「实测」。**顺带修了一个假阳性判据:** 取数入口预算 **23 → 16** —— 计数原来匹配**原文**(docstring 里写一句端点名字就算一条私有取价路径),改成匹配**构造**后实测 16,掉下来的 8 个文件**在代码里一个价格端点字面量都没有**,逐个查过 ⇒ **不是放宽阈值,是修假阳性**。**⚠️ 实测发现(不在本阶段改):** 线上库 `coingecko_pro_ohlc` 最新只到 **11-18**(`binance_hist`/`eodhd` 到 11-19)⇒ 面板那两天看起来像没写进去 —— **判据没错,是现象**;面板循环**疑似已停或在拒写**,与本次改动无关,**单独查**。**【11-20 13:15Z 更正:查过了 —— 不是没写,是落后一根 bar(循环每 ~6h 跑一轮,写的是刚收盘那根;当时那轮还没到点),面板一直在写;详见上面那条。】**)(阶段 2 的全文接着下面这段 ——)`/global` 收敛成一条活路 + 6 处裸 client 收口 + 全仓库端点覆盖表。** 阶段 1 把交易路由的标记价管住了(闸门 + 90s 缓存 + `None` 传播),阶段 2 管的是**「同一个问题被问四遍」**。**① `/global` 曾经有四个实现:** `data_layer.get_cg_global()`(扁平化 + CMC 兜底)/ `data_layer.get_macro_pulse()` 内嵌(扁平化 + CMC 兜底)/ `cis_provider.fetch_cg_global()`(CG 原始 `data` 段)/ `global_history.fetch_today()`(总市值 + 主导率,抛异常)⇒ **四个额度池、四种降级语义、四个缓存键** ⇒「今天 `/global` 打了几次」没人答得上来(`/internal/cg-quota` 只报总数,分不出是哪条路打的);而 `/global` 是**全站最重的那个端点**(global 市值 + 全市场活跃币数 + 主导率)。判据不是「长得像不像」,是 `docs/SPINE.md:188-191`「**不能给出不同答案 ⇒ 是重复**」—— 这四个给的是**同一个答案**(CG 的 `data` 段)⇒ 重复 ⇒ 必须收敛。**收敛后的形状:** 新增 `data_layer.get_cg_global_raw()` = 仓库里**唯一**打 `/global` 的地方(180s 内存 + Redis,失败返回 `None`,**永不换源**);四个消费者各自**保留自己的形状与降级语义**(那是它们给下游的契约)—— `get_cg_global()` 仍扁平化 + CMC 兜底 / `get_macro_pulse()` 仍带兜底 / `fetch_cg_global()` 仍返回原始 `data` 段 / `fetch_today()` 仍抛异常且**不吃 CMC 兜底**(轨迹要同源可比,换源会污染序列,`DATA_ARCHITECTURE.md:70`)。**形状不同不是重复,机制相同才是。** **② `fetch_cg_global` 顺手修一个现存违例:** 它的返回值**没有来源标记** ⇒ 拿到数据的下游分不清这是 CoinGecko 还是别家 ⇒ 现在带 `source`(`coingecko_pro` / `coingecko`,规范名照 `source_policy.PAID_SOURCES`)。⚠️ **加 `source` 必须先 `dict(raw)` 复制** —— `get_cg_global_raw()` 返回的是**共享缓存对象**(进程内 + Redis),原地加字段 ⇒ 缓存里多一个键 ⇒ 而且这个污染**跨进程**。**③ 6 处裸 client 收口进闸门:** `cis_provider`(删掉自己的 `httpx.AsyncClient` + `note_unbudgeted_call` 记账行)/ `deep_walk.py` / `global_history.py`(`fetch_today` 走唯一活路,`fetch_total_mcap_history` 走闸门)/ `rwa/collect.py`(`fetch_markets` + `fetch_issuer_map`)⇒ 裸 `httpx.AsyncClient` → `GuardedCGClient`。**顺手删掉 6 行 `note_unbudgeted_call`** —— 那是阶段 0 的**临时脚手架**,调用点收口进闸门后必须同时删,否则**双计**(闸门自己会记账)。**④ 形状守卫从「描述现状」升级成「挡住下一个」:** `tests/test_cg_call_sites.py` 加了 **24 个端点的覆盖表**(端点 → 允许的文件 → 允许的 client 类型)—— **新增端点必须改这张表**,改表 = 一次有意识的登记;另加**动态端点登记表**(6 个 URL 在运行时才确定的文件)+ 两条「登记不能变成死的」守卫(登记的文件消失了 / 登记的端点不再有实现 ⇒ 都红)。**⑤ 守卫自己抓到了一个真 NameError:** `data_layer.get_macro_pulse()` 里还写着 `global_r.json()`(变量已改名成 `global_raw`)⇒ **运行时才炸 ⇒ 前台宏观面板整块变空**;`py_compile` 抓不到、boot smoke 抓不到(那条分支要特定输入才走到)。已修,并把 `data_layer.py` 加进 `tests/test_no_undefined_names.py` 的 `SCANNED` —— 然后**故意把 bug 放回去验证守卫真的会红**(报 `data_layer.py:2320 in get_macro_pulse() → 'global_r'`),再恢复。**守卫没被证明过就等于没有守卫。** **⑥ 三个计划项被证据推翻,记进台账而不是默默跳过:** (a) 「`cis_provider.fetch_cg_markets` → `get_cg_markets()` 函数层合并」**会*增加*调用** —— `get_cg_markets()` 的 Redis TTL 是 120s、`cis_provider` 自己是 300s 内存 + **1800s Redis** ⇒ 合并 = 把 1800s 降成 120s ⇒ **调用量上升**。收敛停在 **HTTP 层**(共用一次取数),**每个消费者保留自己的缓存与形状**。(b) 「`get_cg_markets_strict` 是纯重复,合并进 `get_cg_markets`」—— **不是**:它**读不到就抛异常**,`get_cg_markets` 返回 `[]` ⇒ 合并会**制造出它自己的 docstring 警告的那个错误**(把「读不到」说成「没有数据」)。(c) 「三个 `/coins/markets` 查询形状是重复」—— **不是**:它们问的是**不同的问题**(`?ids=` / `?category=` / `?category=recently-added`)⇒ 按 SPINE:188-191 **不构成重复**,**登记进覆盖表**即可。**⑦ 诚实口径 —— 不报编出来的省数:** 计划里阶段 2 估 ~1,050–1,150 次/天,但那是**基于「读库替代 API」那一档的估算**,本轮**只做了「收口 + 收敛 HTTP 实现」**,**没有一条把 API 调用换成读库** ⇒ 实测口径下达不到那个数。**本轮的真实价值是三条:** (i) **6 个调用点从「无上限」变成「有闸门」**;(ii) **`/global` 的实现从 4 变 1**(额度池从 4 个变 1 个);(iii) **一笔一直没人看见的消耗现在看得见了**(闸门外记账)。**省多少调用/天:本轮 ≈ 0(量级上);省的是「不确定」和「多个额度池」。** 真正的省额度主力在**阶段 3**(`_cg_panel_loop` 改成按覆盖差驱动,范本 `perp_mcap_backfill.stale_coins()` 已在仓库里)。**顺带一个发现: `global_history.py` 在本仓库内没有生产调用方**(只有 `tests/test_global_history.py`)⇒ 它那条「永不换源」的约束现在是**理论约束**,等它有生产消费者才真成立。**判据(8 条 + 3 条覆盖表守卫,全绿):** 仓库内打 `/global` 的文件数 = 1 / `cis_provider` 不再有任何 CG client / `fetch_cg_global` 带 `source` 且形状不变(`market_cap_percentage.btc` == 57.31)/ **加 `source` 不污染共享缓存** / 拿不到返回 `None` 不是 `{}` / `fetch_today` 走唯一活路且拿不到就抛(不落 0)/ 覆盖表里的端点都有实现 / 动态端点登记没有失效 / 登记没有变成死的。**下一阶段:** 阶段 3(`_cg_panel_loop` 覆盖差驱动 —— **这才是省额度主力**)/ 阶段 4(TTL 口径统一 —— **访客可见的新鲜度 120s → 300s,等你点头**)/ 阶段 5(剩下的重复取数)。**留给你的两步(同阶段 1,还没做):** ① **Railway 上把那个 CMC 变量改名成 `CMC_API_KEY`**(30 秒,不部署)—— 现在 `key_present: false`,兜底层是**哑的**;② **仓库侧日预算是否下调**(16,000 是仓库侧口径,Mac 侧同账号)。**跨 lane 登记(MINIMAX_SYNC,等你/等 Minimax):** Mac 侧 4 处裸 `requests` 绕过限速器(`data_fetcher.py:1397/1440/1505/1990`)/ `market_compass.py:36` 明文 Pro key(**轮换时机 = Jazz 决定,本仓库不主动轮换**)/ `cis_scheduler.plist` 每小时 × 53 资产 ≈1,272/天 / Mac 侧要不要改消费仓库的 L2(跨 lane 架构裁定,不是执行细节)。**另外顺手修了一处「差一行就断」的结构:** `## OPEN RISKS` 块原本在**第 60 行**(`tests/test_cold_start_contract.py` 的判据是「前 60 行内必须有」),本轮标题多一行 ⇒ 块被顶到第 61 行 ⇒ **preflight 当场红** ⇒ 仓库一直卡在「再加一行会话标题就断」的位置上。**修法不是再挤一行**(那只是把断点推到下一轮),而是**把块整体上移到第 5 行**(标题区 55 行余量,以后 20 轮都顶不掉)—— **块一字未动,只搬了位置**;顺带让文件符合判据自己的措辞「BEFORE any narrative」(原来 40 行会话标题就排在它前面,是**过了机械阈值、没过意图**)。**所有冷启动的 agent 记住:OPEN RISKS 现在在文件最上面。**)
 **更早:** 2026-11-19 16:45 UTC (Seth — **CoinGecko 额度收敛 S-895 阶段 1:交易路由的标记价 —— 进闸门 + 90s 函数层缓存 + 拿不到价就说「没测量」。** Jazz 11-17 拍板:「只加闸门+缓存+修降级(推荐)」—— 标记价源不变(继续 CoinGecko),**不**换 Hyperliquid venue。**① 降级语义先修(本轮重点)。** 原来写的是 `price = prices.get(sym, pos["entry_price"])` —— 拿不到标记价就用**开仓价**兜底 ⇒ **PnL 精确等于 0** ⇒ 与「仓位真的平了」同形;而止损位常常就落在开仓价之内 ⇒ 一个「价格取不到」的仓位会被**假止损**平掉 ⇒ 写进 `trade_results` 的已实现盈亏是编出来的,还会喂给 Learn 循环。**实测(改之前,同一套场景,闸门关着):** `current_price=100.0`(开仓价)/ `unrealized_pnl=0.0` / `unrealized_pct=0.0` / **没有** `price_source` / **没有** `price_coverage` / **`sl_triggered=True`** ⇒ 闸门一开始真的会拒绝之后,这条路径会**自己造一个假止损**。合成 503 之所以一直没出事,是靠 `except` 分支「碰巧」兜住了,**不是语义声明的** ⇒ 现在改成显式的(非 200 ⇒ 没有标记价;不解析正文、不编造价)。改后:拿不到价 ⇒ `current_price=None` / `unrealized_pnl=None` / `unrealized_pct=None` / `price_source="unavailable"`;**NAV 仍按开仓价计入**(保守估值,不破坏账面),但 P&L 不再假装是 0(`DATA_ARCHITECTURE.md:109` 未测量 = NaN 且必须传播(I1)/ `:70` source 不可变)。**② 进闸门:** `_fetch_price` / `_fetch_prices_cg_batch` 的裸 `httpx.AsyncClient` → `GuardedCGClient`。**③ 90s 函数层缓存:** key = **symbol**(不是请求批次 —— 批量与单个两种问法,按批次缓存两者会互相看不见);**只缓存成功的价**(失败从不缓存 ⇒ 关着的闸门不会凭空发出一份 90 秒内不存在的价)。TTL 90s 的理由:`_sl_tp_loop` 与 `_cis_flip_loop` **故意错开 60 秒** ⇒ 90s 让后一条命中前一条的缓存 ⇒ 每 5 分钟只打一次(10s 一次都命中不了)。**④ 其余语义收紧:** `close_position` 拿不到价 ⇒ 503 且**不平仓**(不写编造的已实现盈亏);`sweep_aged_positions` / `_sl_tp_exit` 统计 `unpriced` 并跳过;`_run_paper_rebalance` / `_close_rebal_position` 拒绝缺价的标的;响应体加 `price_coverage`。**⑤ 前端:** 后端传 `null` ⇒ 显示「—」而不是 `+0.00`(新增 `fmtSignedPnl`,`dashboard/src/lib/safeFormat.js`);**真的 0 仍然是「+0.00」**(真的平了 ≠ 没测)—— `(pos.unrealized_pnl || 0)` 那种塌法去掉,这也是 S-262 家族的形状。**省多少:~288/天**(576 → 288)。**不报成 550** —— 前台路径本来频率就低,缓存对它们省不了多少;真正的价值是**给这条无上限路径封了顶 + 拆掉一个假数字**。**判据(11 条,全绿):** 合成 503 与真 503 ⇒ `current_price is None`(不是 entry_price)/ `unrealized_pnl is None` / SL·TP **不触发** / 手动平仓拒绝(503)/ 同一批 symbol 连打两次只发一次外部请求 / 单问与批问看得见彼此的缓存 / 失败不缓存 / 前端 null ⇒「—」而 0 仍是「+0.00」;另:`tests/test_cg_call_sites.py` 里 `src/api/routers/trading.py` 的**豁免登记撤掉**(留着 = 一个已经不裸的文件继续占豁免名额 ⇒ 白名单变永久豁免)。**登记但不动的事:** `price_route.py:175-190`(Jazz 2026-08-20 钉死的「THE price route」—— execution/book 用途的价格必须来自场馆、没有就**拒绝而不是替代**)与本路由的钉法违例 ⇒ **本轮不改**,作为独立发现。**本轮还把上一轮的堵点按关注点分提交落地(都是 Seth lane,preflight 全绿):** ① **S-893 派卡盲区** —— `lane_bot` 看不见带后缀的返工分支(`lane-a/T-359-v2`)、已并进 main 的分支永远挡路 ⇒ 三条 lane 全部 0 张可动;改法:一条 for-each-ref 拿全 lane 分支(60 秒复用),按卡号归并,**最新的那条未合并分支说了算**;已合并的用 `merge-base --is-ancestor` 判掉;「读不到」与「在等审」分成两个返回值,不合成一个 None。② **「守卫注册了」≠「守卫跑过」** —— `python3 -m tests.foo` 只跑 `__main__` 块里**已经定义**的测试,定义在块之后的永远跑不到,而文件照样打印一份绿色的清单;实测五个文件 24 条这样的测试从没执行过(20 条是 lane_bot 缰绳、11 条要 pytest fixture)⇒ preflight 里这四个文件改用 pytest 跑 + 新增一条守卫(任何测试文件都不许把 `__main__` 块放在它要跑的那些测试之前)。③ **seth_bot 清 `.git/index.lock` 要看年龄** —— 原来无条件删 ⇒ 一个**活着的** git 进程会被抽掉锁 ⇒ 两个进程同时写 index ⇒ 索引损坏;改成只删「存在且比 120s 老」的锁。④ 登记 **T-413 / T-414** 两张新卡 + 看板重生(413 张)+ 教训强制执行基线 300 → 382 + T-241 报告的合规措辞订正(『加仓确认』→『风险确认量』)。**下一阶段:** 阶段 2(`/global` 收敛成一条活路 + 12 处裸 client 收口 + 全仓库形状守卫)/ 阶段 3(`_cg_panel_loop` 改成按覆盖差驱动 —— 范本 `perp_mcap_backfill.stale_coins()` 已在仓库里)/ 阶段 4(TTL 口径统一 + 预热只热本地缓存 —— **访客可见的新鲜度 120s → 300s,等你点头**)/ 阶段 5(剩下的重复取数)。**留给你的两步:** ① **Railway 上把那个 CMC 变量改名成 `CMC_API_KEY`**(30 秒,不部署)—— 现在 `key_present: false`,兜底层是**哑的**;② **仓库侧日预算是否下调**(16,000 是仓库侧口径,Mac 侧同账号)—— 下调多少等阶段 0 的实测数出来再拍。)
 **更早:** 2026-11-19 07:45 UTC (Seth — **Seth 缺席期间把机器的堵点解开:合并队列 → 陈旧卡 → 未提交改动 → 派卡链续上。** Jazz 的 Claude 订阅暂停(新卡在途)⇒ **Seth 角色层无人**(派卡 / 验收 / 合并);Mac 侧 `seth_bot` 与三条 lane 照常(走 `api.minimax.io` 的 Anthropic 兼容端点,认证方式 none,与订阅无关)。**真正空掉的是 `seth_bot` 的队列**(它只跑放进 `.seth_bot/queue/` 的任务,队列 0 条)⇒ 一条完整的链卡在最后一厘米:**lane 交了活 → 没人排合并 → 分支躺在 origin 上**。**本轮解掉五个堵点:** ① **合并队列** —— T-056 / T-366 / T-238 / T-308 / T-388 落地;T-228 的合并死了两次,两个原因都查到了:`_data/strategy_records.json` 停在 07-21(T-056 重生成后实测 70/70 绿)+ 沙箱留下的 `.git/index.lock` 挡住 `sync_main()` 的快进(`seth_bot` 的 `_clear_index_lock()` 一直排在 `sync_main()` **之后** ⇒ 一个陈旧的锁能杀掉任何 op 的第一次快进;已加年龄护栏并提前)。② **50 张陈旧 `in_review` 卡** —— 全部收口(`status: done` + `verified`)。③ **cold-start 预算** —— `MINIMAX_SYNC.md` 86,645 → **30,497 字符**(21 段 lane 轮次报告 57,353 字原文进 `MINIMAX_SYNC_ARCHIVE.md` §AR-2026-11-19-seth,**未结项先提到 §IN-FLIGHT 再归档**(S-370))⇒ preflight 红灯解除。④ **S-893 派卡盲区** —— `lane_bot` 看不见带后缀的返工分支(`lane-a/T-359-v2`),三条 lane 当时 0 张可动。⑤ **T-228 卡重建** —— 两口径 ρ 并列(同期 +0.3681/p=0.0118 vs 未来 30 日窗口 +0.0329/p=0.8299)+ 情景概率重标(0.45/0.53/0.55 → 0.13/0.11/0.37)。**今天的市场读数(2026-11-19 07:19Z,只读,是观测不是预测):** 基准 30 日 −22.1% ⇒ 仍在 `1_deep_off` 档;Fear & Greed **10**(极端恐惧,较昨 11 再降 1);BTC $63,591 / 占比 58.1%;DeFi TVL $70.51B(24H −1.13%);**资金费率几乎全平**(BTC +5.4%/yr、ETH +6.8%/yr、SOL +1.3%/yr;35 个标的里没有一个 overleveraged_long,也没有一个极端空头;OI/MCap 最高的不是 BTC(0.0286)而是 AVAX(0.6534)⇒ 杠杆在山寨,不在 BTC)⇒ **边际流动性温和收缩,但没有挤兑、没有杠杆堆积。** **这一档的历史:** STRONG OUTPERFORM **−3.49%/30d(n=172)**、UNDERWEIGHT −3.23%(n=560)、NEUTRAL **+0.76%(n=2840)**、OUTPERFORM +0.36%(n=1453)⇒ **深度 risk-off 里,最高质量标签历史上是负的**。**前向账(as_of 11-18):** ① core_cap 47 天 −28.36%;② 全部倾斜臂负超额(cis_tilt −1.06% / beta_plus_w −5.20% / tokenization_tilt −5.93% / beta_core −7.14%);③ 减仓型臂正(tom_overlay +3.61% / q_slow +3.28% / q_overlay +9.78% 但 anytime 下界 −1.73);①+③ 现货腿 hl_jev **+14.20%** / hl_mech **+9.79%**(47 天);④ carry_hl +17.33%(13 天,名义本金口径);**分配层仍给 core 100% 权重**(`l3_weight` = 1,其余全 0)⇒ 机器自己的结论是「不分配超额仓位」。这些是本仓自己的观测记录,**不是预测,不是投资建议**;`fusion_paper` 明确标「记录只扣成本、不记价格 —— 数字不可信」⇒ 不作证据。**没做:** 不下真实订单、不碰真钱路径、不改研究口径与 CIS 权重、不动公开面展示模块、不 `git add -A`;主目录那三条外来脏文件(`src/api/routers/trading.py` / `dashboard/src/components/QuantMonitor.jsx` / `tests/test_cg_call_sites.py`,属 S-895 阶段 1)已验绿但**不代为提交**。)
**更早:** 2026-11-18 08:43 UTC (Seth — **CoinGecko 额度收敛 S-895 阶段 0:让「今天花了多少」变成真的(度量可信)。** Jazz:「对于 coin and asset api 调用上 还能怎样优化? 请你回到高维,认真看完我们整个项目的设计,再下结论。」—— 计划全文在 `~/.claude/plans/parallel-doodling-taco.md`(6 条架构结论 + 阶段 0–5 + 明确不做的事 + 风险 + 验证)。落地从**阶段 0(度量可信)**开始,因为**度量不可信时,任何一次优化都无法证明自己有效**。**S-894 的闸门只数它自己放行的请求** —— 全仓库 23 个文件打 CoinGecko、**13 个调用点在裸 client 上** ⇒ 闸门外的消耗**一概不进账** ⇒ `GET /internal/cg-quota` 报的 `used_today` 从第一天起就是**残缺的**(只数闸门内的 11 个文件)。SPINE.md:170-174:「一个因错误理由变绿的检查,比红的更坏 —— 红的会被修,绿的会被信任。」**① 记账(`cg_guard.note_unbudgeted_call(source, endpoint)`,同步函数 ⇒ 同步/异步调用点同一形状):** 独立计数器 `cg:quota:unbudgeted:{day}` + 分端点明细 `cg:quota:unbudgeted_ep:{day}`;Redis 与进程内取**较大者**(宁可报多不报少 —— 少报 = 因错误理由变绿);13 个裸调用点(7 个文件)全部记账。**② `report()` 只加不改:** `unbudgeted_today` / `unbudgeted_endpoints` / `unbudgeted_total` / **`total_calls_today`(= 闸门内 + 闸门外)**。**③ 形状守卫 `tests/test_cg_call_sites.py`(新):** AST 扫描把每个 CG 调用点分类成 gated/injected/bare,断言每个裸点都在记账、登记的例外都还活着、登记的端点跟代码对得上 —— **只看 AST 节点不看注释**(「我等下接进闸门」不能冒充合规);**记账是一次性的,守卫是让下一个 agent 开不了洞。****开发中真抓到三个 bug:** `endpoint_label` 把集合端点 `/coins/markets` 误归成 `/coins/{id}`(新增测试照出来的)/ `src.data.market.cg_guard` 与 `data.market.cg_guard` 会加载出两个模块对象 ⇒ 两份进程内计数 ⇒ Redis 写失败时读数漏掉一半 ⇒ **少报**,现在用 `sys.modules.setdefault` 把两个名字钉到同一个对象(**不变量变成结构性的**)/ preflight 抓到 Rule #7 违例(引用 S-895 却没先认领标题)。**顺带修 S-302 计数器一个假阳性**(`scripts/loop_status.py`):它按原文匹配取价原语,闸门 docstring 里写了 `market_chart` ⇒ 被算成新增取价路径(24 > 23);闸门是**共享路径**不是私有路径 ⇒ 按**构造**(AST 判 `class GuardedCGClient`)排除,**阈值仍是 23,别的文件一个不多算**(没改阈值,也没换成 `code_only()` —— 那会漏掉 8 个**真实**的私有取价路径,它们只是端点写法不在那 7 个原语里)。**记账行是临时脚手架:** 调用点收口进 `GuardedCGClient` 后必须同时删掉,否则双计 —— `test_登记在册的例外没有变成死的` 守这条。**下一阶段:** 阶段 1(`trading.py` 闸门 + 90s 函数层缓存 + 降级语义改成 `None` 传播 + 前端「—」)/ 阶段 2(`/global` 收敛成一条活路 + 裸 client 收口)/ 阶段 3(`_cg_panel_loop` 改成按覆盖差驱动 —— 范本 `perp_mcap_backfill.stale_coins()` 已在仓库里)/ 阶段 4(TTL 口径统一 + 预热只热本地缓存)/ 阶段 5(剩下的重复取数)。**留给 Jazz 的一步(30 秒,不部署):** 在 Railway 把那个 CMC 变量改名成 `CMC_API_KEY` —— 现在 `key_present: false`,兜底层是**哑的**。)
**更早:** 2026-11-17 06:00 UTC (Seth — **CoinGecko 超额计费打开 ⇒ 加一道闸门 + 一层 CMC 兜底(S-894;Jazz:「现在coingecko的outage是打开了的,因为有策略模拟还有策略在跑着」)。** 上一轮(S-892)治的是「**同一份数据取两遍**」,这一轮补的是**「用量本身没有闸门」** —— 前者治浪费,后者治**上限**:超限之后每一次重试都是一次付费调用,而我们原来的行为是「429 当成没数据,下一轮照打」,**没有人知道今天花了多少**。**① 新建 `src/data/market/cg_guard.py`:一个闸门三件事 —— 日预算(`CG_DAILY_BUDGET`,默认 16,000 次/UTC 日 ≈ Analyst 档 500,000/月 的 95% 不到;可用 Redis 键 `cg:quota:budget` 在线改,不用重新部署)、熔断(收到 429 / 5xx 就开闸 300 秒,期间**一次外部请求都不发**)、计数(每次请求记一次,写进 Redis,跨进程共享)。实现方式是 `GuardedCGClient` —— **`httpx.AsyncClient` 的子类,不是包装器**(仓库里到处在用 `isinstance` / `async with` / 直接构造,包装器会到处破);覆写 `request()`(httpx 的 `.get()` / `.post()` 全经过它)⇒ **一处收口,全覆盖**。拒绝时返回**带 `request` 的合成 503**而不是抛异常:既有代码的 `raise_for_status()` / `except` 分支一个字都不用改,闸门不必逼着全仓库改一遍降级逻辑。**② 把闸门接到每一个线上 CG 客户端:`data_layer._get_cg_client`(它罩着全仓约 30 个调用点)、`social_collector._get_cg_client`、`main.py` 的 cg_panel_sync 循环(面板回填是单条路径里调用最多的消费者:每个标的每轮一次)与 treasury 循环;`cis.py` 路由 / `positioning.py` 走 `data_layer` 的 client ⇒ 自动受管。** 另加一条**形状守卫**测试:新写一个裸 `httpx.AsyncClient` 就是把闸门拆了 —— 那个 bug 静默、无异常、只在账单上现形。**③ 新建 `src/data/market/cmc_provider.py`:CMC 免费档兜底**,自带 Redis 自计数日预算(默认 40 次/天,`CMC_DAILY_BUDGET`),撞到额度错误码(1001/1002/1008/1009/1010/1011)⇒ **今天不再试**(而不是下一轮再撞一次);key 认三个名字(`CMC_API_KEY` / `COINMARKETCAP_API_KEY` / `CMC_PRO_API_KEY` —— Jazz 补 key 时用的名字没人记录过,不该为了一个变量名再发一版)。接了两个面:`get_cg_global`(CG 失败 → CMC `/global-metrics`)与 `get_macro_pulse`(CG 的 `/global` 与 BTC 价两块 → CMC)。**换源必须标来源**:结果带 `source` / `data_source`;CMC 没有的字段(ETH 占比 / DeFi 市值)是 **None 而不是 0** ——「没有数据」塌成「0」会让面板显示一个看起来合理、其实不存在的数字(S-262/S-396 家族)。**④ 新增 `/internal/cg-quota`(token 守卫)**:今天用了多少 / 还剩多少 / 熔断了没有 / CMC 用了多少 —— 账单是唯一的反馈,那时候已经晚了。**验证:** `tests/test_cg_guard.py`(9)+ `tests/test_cmc_provider.py`(9)= 18 passed;**两份都注册进 `scripts/preflight.sh`**(S-244:测试文件存在 ≠ 会被运行,而「额度闸门没跑」的缺席永远是静默的 —— 闸门形同不存在 = 继续烧钱)。钉死的判据:预算没用完请求照发(**不许误伤**)/ 预算用完一条都不发 / 429 与 5xx 都开闸 / 合成 503 带 `request` 能照常 `raise_for_status()` / CMC 撞额度今天停用 / 兜底标来源且缺字段是 None。**⑤ 部署后实测(S-894 补充):闸门活了** —— `GET /internal/cg-quota` 实测 `used_today 62` / `daily_budget 16000` / `breaker_open false` / `trips_total 0` / `redis_shared true`(计数跨进程共享)。**但同一份响应里 `coinmarketcap.key_present: false`** ⇒ Jazz 补的 CMC key **不在**我认的三个显式名里 ⇒ **兜底层装上了但是哑的**(闸门一关宏观脉冲就空;而闸门一关正是超额开始烧钱的那一刻 ⇒ **兜底哑掉 = 闸门不敢关**)。**修法不是「再发一版改名字」,是按规则扫环境变量** —— 但**只在我们自己的命名空间里扫**:变量名**以 `CMC_` / `COINMARKETCAP_` 开头、且以 `KEY` / `TOKEN` 结尾**的才算(`CMC_*_KEY` / `CMC_*_TOKEN` / `COINMARKETCAP_*_KEY` / `COINMARKETCAP_*_TOKEN`);**别家的 key 一个都不看**(`COINGECKO_API_KEY` / `MORALIS_API_KEY` / `INTERNAL_TOKEN` 不在这个命名空间里),`CMC_ENABLED` 这类不是凭据 ⇒ 排除;按名字排序取第一个 ⇒ 确定性(不靠字典序运气);判定规则集中在 `_looks_like_cmc_key_name()` 一处、测试直接引用它;`report()` 多报一个 `key_env`(**变量名,不是值**)—— 再哑的时候一眼看得出是「没配」还是「配在我没认的名字下」。**教训(比这个 bug 本身重要):「装了兜底」和「兜底是活的」是两件事** —— 我写了 9 条 CMC 测试覆盖预算 / 停用 / 标来源 / 缺字段是 None,**没有一条测「key 到底找没找到」**,因为测试用 `monkeypatch.setenv` 造了个**名字必然命中**的 key;**生产上恰恰是名字不命中**。**要你在 Railway 上加的环境变量(都有默认值,不配也能跑):** `CMC_API_KEY`(CMC 免费档 —— **配了才有兜底**;名字不在名单里也没关系,会按规则扫到)、`CG_DAILY_BUDGET`、`CG_BREAKER_COOLDOWN_S`、`CMC_DAILY_BUDGET`(`COINGECKO_API_KEY` 已有)。**没做:** 12 条路径的「读库优先」改造(范围大)、QuantMonitor 的 30 秒价格缓存(要挪到 Binance,不是日库)、前端两个 5 分钟轮询能不能改成日粒度读库(还在等你)。)
**更早:** 2026-11-16 12:45 UTC (Seth — **四处烧额度的 bug 修完(S-892;Jazz:「coingecko analyst api 现在调用超限制了」「你先修bug」「继续修bug」)。** 查下来不是"用得多"这么简单 —— 是**同一份数据被取了两遍、该读库的路径直接打了 API**,四个口子各自吃一个额度池。**① positioning.py 打的是公开端点:** `/derivatives` 与写入端 `derivatives_market.py` 是**同一个端点、同一份数据**,写入端每 6 小时取一次,positioning 每 30 分钟取一次 —— 一个端点、两个额度池。改成**先读库**(`derivatives_market_daily`),库空或太旧(>12 小时)才回落 API。口径必须一模一样,所以落库存的是**分子 + 分母**(`funding_oiw_sum` / `oi_funding_usd`),读者自己算 `Σ(f·oi)/Σ(oi)`,不是存一个算好的比值 —— 两条路因此不可能悄悄分叉。新迁移 `migrations/2026-11-16_derivatives_market_funding_oiw.sql`;**迁移没跑时写入端退回旧列集(不丢数据)并标 degraded,positioning 读不到新列就回落 API** —— 迁移顺序错了也不会断管、不会改数。**② cis.py 的 watchlist 逐个 symbol 打 CG:** 9 个币 = 9 次调用;缓存用**全局时间戳**(一次未命中把所有人的 TTL 一起重置);每个 symbol 各建一个 httpx client。改成**一次 `/coins/markets`**(ids 逗号分隔)+ **按 key 的 TTL** + 共享 client;有 key 走 Pro host(Pro key 在公开 host 上会被忽略)。**③ token_holders 把周频币种每天排进日频队列:** 周频数据(max_d 已最新)的币种每轮仍占 450 个日频名额。改成读 `token_holders_coverage` 的 `n` / `n_weekly` 算出 `n_daily`(**不需要迁移**),周频币种进**有界探测池**(每轮最多 30 个,按日期 hash 轮转)。**④ mmi_index_v3 一轮取两次 `/market_chart`:** `get_historical_score()` 与 `get_onchain_score()` 要的是同一个 URL、同一组参数 —— 合成一次取、两个分项共用。**顺带修的三处(不修就看不见回归):** `pytest tests/` 之前**根本收集不起来** —— repo 根下的运行时产物目录 `data/` 是 namespace package,抢在 `src/data` 前面被解析(namespace package 一旦解析就粘住,之后改 sys.path 也救不回来)。改 `tests/conftest.py` + `src/api/main.py` 的 sys.path 顺序 + `tests/test_regime_reaches_the_signal_feed.py` 的守卫。**收不起来 = 任何回归都看不见。** 另两处是**假绿 / 假红**:锁测试顺序相关(官方 overlay 把 `universe[0]` 从 BTC 换成 HYPE)⇒ 用端点自带的 `official=False` 关掉 overlay,不改生产代码;`test_loops_envelopes` 的 `tmp_path: Path = None` —— pytest **不给带默认值的参数注入 fixture**,传进来的是 None,`None / "large.jsonl"` 抛 TypeError,这条断言在 pytest 下从来没跑过,而 self-runner 只收 `t_*` ⇒ 两边都没覆盖(preflight 说绿、pytest 说红,两个都在说一件没发生的事)。**验证:** 受影响 5 个文件 27 passed;守卫 4 个文件 25 passed;`compileall scripts src` 退出 0;全量 `pytest tests/` **2667 passed / 6 failed / 5 skipped**(13 分 10 秒;改前 2665/8 ⇒ 两个假失败变成通过、**没有新增失败**;剩下 6 个全是沙箱没装 `pytest-asyncio`,而这两份文件在 preflight 里走自带 self-runner,覆盖得到)。**没做 / 还等你:** CMC 兜底层(自计数日预算)、CG 429 熔断 + 负缓存、12 条路径的"读库优先"改造(范围大,不在这次授权内)、QuantMonitor 的 30 秒价格缓存(要挪到 Binance,不是日库)。**两个问了没答复的:** ① 前端两个 5 分钟轮询(`/market/macro-pulse` / `/market/crowd-clock`)能不能改成日粒度读库?② CoinGecko 账号**是否开了超额计费**?(不开 = 超限只掉数据,开了 = 超限直接烧钱。) **已推(Jazz 11-16 授权直接推)。** 另:**preflight 拦下了三处** —— 新写的三份测试不在 preflight 的手写枚举里(S-244:测试文件存在 ≠ 会被运行,这类缺席永远是静默的)⇒ 已注册进 `scripts/preflight.sh`。)
**更早:** 2026-11-16 04:30 UTC (Seth — **公众号第二篇整篇重写:11-15 那版未发布,已被这一版替换(`docs/articles/tokenized_funds_hk_2026-11-15_zh.md` 已删除)。新文 `docs/articles/tokenized_funds_hk_2026-11-16_zh.md`,标题《二十一天,四十八港元》,约 20,700 字,五张图全部由同一份快照渲染。** Jazz「上次那篇我还没有发布出去,整篇重新写,重新整合,根据最新数据写,按财新和经济学人的风格,图文并茂」⇒ 新数据 = 2026-11-16 03:12 UTC(11:12 HKT)与 04:15 UTC(12:15 HKT)两次只读实测,加 11-15 13:09 UTC 的对照快照。****新的核心事实:盘口上摆着的两个数字是最近两笔成交价本身 —— 买价与最后一笔成交逐位相等,卖价是上一笔;不是两张挂着没成交的订单。报价时间戳停在 11-16 02:11 / 02:55,比读数旧 9 小时 01 分 / 8 小时 17 分;12:15 再读一次仍在原地 —— 周一开盘后四个小时十四分钟,报价一次也没刷新;08:01–12:15 的 255 个逐分钟采样点成交为零。** 平台口径 24 小时成交额 48.00 港元 / 6.01 美元,而逐笔能验证的只有 24.00 港元 + 12.01 美元 —— 两个币种对不上的方向相反(港元两倍、美元一半),文章里一律写成「平台口径」,不拿它当成交量。** 四类份额链上可见持有人 3 / 5 / 3 / 1,可转手的两类 8 个地址,七天一个没多;30 日净流出 $53,557,798,其中 91.6% 来自不能转手的那两类;四类份额的转让计数器(周 / 月 / 近 30 日)笔数与金额全部为 0,而平台行情页记着成交 —— 两个数据源对不上,公开数据判不出来,已写进正文而不是绕过去。** 可转手的价格写在管理费里:港元 45 bp、美元 55 bp,与净收益率差额 45.17 / 55.03 bp 对齐。** 三档预判 + 八条可判观察点,基准档 =「通道继续是通道」,我们站基准档。** 合规:正文过 `scripts/decks/audit_deck.py` 的 FORBIDDEN 清单(33 条)→ **0 命中**(「目标价」一处已改写);本轮两个脚本过 `scripts/compliance_scan.py` 显式扫描 → Compliance OK(该脚本全仓的 238 条命中全是 `src/`、`dashboard/` 里既有的历史违规,本轮未碰那些文件;文章是 `.md`,本就不在它作用域内)。** 独立重算核对已落成可重跑的脚本 `scripts/articles/verify_tokenized_funds_hk.py`(仅标准库):从三份快照重算 98 条派生数字 + 15 条布尔断言 → **命中 98 / 未命中 0 / 断言全过,退出码 0** —— 文章里「每个数字都出自那份 JSON」现在是一条可重跑的约束,不是一句承诺。** 未做 git add / commit / push。**)
**更早:** 2026-11-15 06:45 UTC (Seth — **公众号第二篇:香港代币化基金二级市场开通第 20 天(观察 / 分析 / 预判;财新 + 经济学人笔法)。** 新文 `docs/articles/tokenized_funds_hk_2026-11-15_zh.md`(335 行 / 14,509 字),标题《报价来了,人还没来》;11-09 那篇与那份 PPT 不动 —— 这是第三份材料,也是第一份**自己实测**的。**这一版的新事实(2026-11-15 05:19–05:25 UTC / 13:19 HKT 只读实测,无写入):撮合簿从「无挂单」变成有双边报价** —— CAMFF 买 103.0938 / 卖 103.1051(价差 1.10 bp,iNAV 103.0999),CUMFU 买 104.6326 / 卖 104.6543(2.07 bp,iNAV 104.6437);**报价中值相对 iNAV 偏离 −0.0004% / −0.0002%** —— 报价就是净值,一根头发都不多;CAMFF 那条报价的时间戳是 01:39 HKT,读到时已经**旧了 11 小时 40 分**。**流量没跟上:全天成交 12.01 美元,2 笔,各约 0.057 份 / 6.00 美元(08:13 与 10:48 HKT);两笔相对 iNAV 各偏 +0.0101% / −0.0106%**,都落在价差里面。**同一天两笔钱方向相反:能转手的 Class F 从 928 万美元涨到 953 万(+2.7%,持有人 8 个不变);不能转手的 Class A+I 从 6.28 亿降到 5.975 亿(−3,055 万,其中 CUMIU 一只 −3,016 万,过去 30 天赎回 48.1 万份 / −9.09%)。** 市场层面:代币化美债总分布价值 141.20 亿 → 139.14 亿(−2.06 亿),**前十只固定样本解释了 2.029 亿,其余 113 只六天只动了 272 万**;固定样本的占比 84.7% → 84.5%(基本没动)。**最精确的一组对应:可交易类的收益率差额 = 管理费差额,港元 45.06 bp、美元 54.65 bp,基点级对齐 —— 「可以转手」的定价写在净值上。** 三个机制:① NAV 锚 ② 对手方池被一级 PI 门槛(HK$800 万组合)锁住 ③ 做市商退出要提前 3 个月通知 ⇒ 持续报价先是**合规产物**,不是流动性产物。**预判三档 + 八条可判观察点,基准档是「通道运转、流量稀疏」;我们站基准档。** 合规:仓库 `scripts/compliance_scan.py` 与 deck 审计表双扫 **0 命中**;「谁为流动性付钱」一节标注为推断;全文无买入 / 卖出 / 增持 / 减持 / 目标价。**未做 git add / commit / push。**)

**更早:** 2026-11-15 06:31 UTC (Seth — **策略按状态重新打分并组合(Jazz 11-15 三句话,DECISIONS 已记):「不需要全局高效,特定矢量下 2–3 个月跑出超额就可以;发挥优势」「可以不用高胜率,但盈亏比需要高」「(真钱规则升级用哪把尺)you can decide」。** **结论翻过来了,我上一版写错了:** 按我原来的判据(六成的段为正)组合与安慰剂分不开;**换成 Jazz 的判据(盈亏比 ≥ 2,台账 S-871)之后,「按状态取长处」的组合均值 / 波动 1.09、落在安慰剂(200 次状态标签平移)的 100 分位,不看状态只拿好的只有 0.37 —— 增量确实来自看状态。** 旧判据把 X1V 与 R-v2 挡在名单外,所以测不出来。核对过三样:门槛 1.5 / 2 / 3 三档都在 91.5 分位以上;不靠杠杆(各条缩放倍数中位 0.2–1.7);**把 8 条坟场族全拿掉、只剩核心 / X1V / R-v2 / 股 / 金五条,仍是 1.09。** **这本组合就是四句话:** 线上且稳定币在注入 ⇒ 做多加密(占盈利 43%);线上但在抽 ⇒ 空仓;线下且在注 ⇒ 金(35%);线下且在抽(今天)⇒ 做空(21%;名单里是 S642,A 道面板上还有三态敞口 R6)。只看线上 / 线下的版本只到 87 分位 —— 增量在稳定币那个轴上。**放到 26 条上还站得住(S-873;加了 A 道补的 Trader Tom × 2、三态敞口、闸门关时空大盘、套息、七个风格指数):均值 / 波动 1.01、安慰剂 94.5 分位、去掉套息 0.94,2022–2026 每年为正;新进来的做多各条形状一模一样(Tom 在线上·注 +82% / +139%、在线下·抽 −23% / −18%);「线上·抽」二十条做多的没有一条有像样的超额。** 并集版在 26 条上变差(0.52)⇒ 纸面账只起「这个状态的长处」一条臂。 **再加 C 道的 8 条(共 34 条):1.19、安慰剂 98.5 分位、每年为正 —— 三个面板上结论一样;但 34 条全拿等风险自己也有 0.94,状态取长处比它多 0.25,两个数都要看。** **边界:** 表已盲复算(B 道 T-391,156 格对上);组合仍是单份实现、13 条、一条 4.8 年的路径,最长水下 636 天。A 道补进 13 条后的重跑里组合数被一条套息曲线放大失真(等风险缩放上限 25 倍太松),**全面板的数先不读**,上限已改 3 倍、C 道 T-393 重跑。 **我定的(Jazz 交给我):真钱规则的升级两把尺都要过 —— 状态内超额决定想不想做,回本时间有否决权;形态用倾斜不用开关。** 第一件按它判的:R-v2 在稳定币抽时减半(S-872,脚本写好、我在沙箱里跑不了,C 道 T-394)。**两件新结果:** ① S-872(C 道 T-394):R-v2 在稳定币抽时减半 / 不开,按字面过了我的两道「不变差」的门,但年化略低、回撤略深、水下多 12 天 —— 没有一把尺变好,**不改真钱规则**(判据以后写成「不变差且至少一把尺变好」)。② S-874(A 道 T-396;Jazz 要先看模拟再定 T-370 的止损:基准 25% 随波动放宽、冲高不止损而加仓):**360 种管法没有一种盈亏比过 2;他那一格 2022 年 +6.2% / 张、2023 年起 −2.2%;过得了盈亏比的是近止损(8% → 2.74、12% → 2.05)。** 连近止损 2023 年后也略负 —— 「线下·抽」里机械地空不挣钱,挣不挣在进场判断(⓪)。我提的默认值写在 T-370 卡上(ATR 封顶 12% 或固定 8%、一次进满、28 天、不自动加仓、冲高加仓做成他单独签名的动作),等他点头。 **矢量库(Jazz 问:模拟有没有走矢量库 —— 之前没有,补了三轮):** S-875 用生产的 56 维融合向量找邻域选策略:0.55、安慰剂 52.5 分位;S-876 换成 2 / 19 / 28 维的子空间:0.04 / 0.18 / 0.27,分位 12 / 24 / 19 —— **维数越少越差,我说的「被维数冲淡」是错的;坏的是「邻域 + 之后 60 天 + 每月选一次」这套做法**(同样两个轴按天切成四格是 94.5 分位)。查库:特征表 106 个键里没有任何利率 / 收益率的键,策略向量表只有 50 行 —— 这两处是真缺口(T-399)。**Jazz:「先再模拟和 mining」⇒ 两张挖掘卡在跑:** S-877(C 道 T-400)用站得住的做法逐键量 56 个键在趋势之外带不带「该拿哪些策略」的信息;S-878(A 道 T-401)挖空单的进场 —— 每个键在高 / 低位时,Jazz 的管法与近止损的空单之后挣不挣,带发现段 / 留出段与平移对照。T-370 的默认值等挖完再定。 **挖掘回来三件:** ① S-878:单个键圈不出「该空的时候」(336 个条件,留出段确认 0 个)。② **S-879:Jazz 11-15 在 HL 上实际做的动作(ETH 破 1,800 返空)站得住 —— 在「线下·抽」里等破位再空、收回就认错:+2.3 ~ +3.2% / 张、盈亏比 4 – 5.7,2023 年后仍为正**(日历进场在留出段是负的);已写进 T-370 的卡。③ **S-877:挖到比稳定币更强的第二轴 —— 山寨相对主流的 30 日强弱(趋势 × 它 = 1.94,稳定币轴 1.01);但面板里有七条风格指数自己,有循环嫌疑,复核 T-403(C 道)没回之前不算数。** **分工(Jazz 11-15):交易那条线(T-370 / 手动仓记分 / 做空通道)他在另一个对话里做,交接写在 T-370 卡的最后一条 note;这个对话回到高维:挖维度复核 → 利率族入库(T-369 ② / T-399)→ 纸面前向账(T-395)。** **三步走完两步半(Jazz 11-15 点的顺序):** ① 复核回来 —— **风格轴不是面板内动量(去掉七条风格指数仍 2.0);同一窗口它把只看趋势的 0.98 抬到 1.95,稳定币轴是 1.14。这条轴 = 「谁在领」(主流 30 日收益 − 二线 L1 / L2):线上·主流领 ⇒ X1V / R-v2;线上·二线领 ⇒ 山寨篮子(R-v2 反而不挣);线下·主流领 ⇒ 三态敞口 / 金;线下·二线领 ⇒ 做空、做多全线最差。我先前把方向说反了,已更正。** 利率 / 美元 / VIX 族做成慢状态轴 0 / 10 过(S-880)。② **「把利率族接进特征表」不用做:它工作日本来就在表里(我查的是周六那一行,第三次更正),真缺口只是周末不向前带;这一族对策略选择没有信息,不为它改生产 SQL。** ③ 纸面账的配方定了(T-395):主臂 趋势 × 谁在领,对照臂 趋势 × 稳定币 / 只看趋势 / 全拿;前置 = 盲复算 + 各策略的前向收益来源(R6 / S642 / 闸门空 / Tom 只有研究回测)。 **(2026-11-15 06:50 UTC 补)Jazz「向前建」:** 给只有研究回测的几条策略建前向序列 —— A 道 T-406(三态敞口 R6 + 闸门关时空大盘两档,照 tom_trader 的写法进 `forward_book_nav` 的新账 `state_arms`;runtime 改动,合并前 Seth 读 diff)· C 道 T-407(S642 是票的引擎,先出前向化清单)。Trader Tom 已有前向序列(`tom_trader` 14 条臂,10-16 起)。纸面账的写入端(T-395)等这两样 + B 道的盲复算(T-405)。 **(2026-11-15 07:06 UTC 补)Jazz 的批评成立(台账 S-881):挂着 Trader Tom 名字在跑的 14 条臂全是价格规则,教义 §5 的机制(持仓拥挤、确信度定尺寸、形态登记表)一条没接;我默认走了「把现成的简单策略排一排」的路。改法:挖掘与建账的单位从因子换成形态(因 × 状态 × 触发 × 认错写在价格上 × 按段的基率 × 前向记分)。** 登记表建了:`docs/SETUP_REGISTRY.md`(四条,其中只有「线下·抽 + 破位」六样齐);S-881(C 道 T-408)在量 状态四格 × 破位 / 突破 × 触发当天的持仓读数;下一轮按币(用资金面向量挑哪个币,库里那一侧到现在一次没用过)。T-406 降格为给纸面账接线。 **(2026-11-15 07:13 UTC 补)S-882:Jazz 贴来交易对话的「周末大跌 → 反弹 → 回落 ⇒ 两边都被扫」当周期性机会的例子;我用库里的小时线补了对照 —— 不带条件的周末本来就 77% 碰上沿、53–59% 碰下沿、95% 至少碰一边;这个形态里真有的只是「大跌之后波动大」(±2.5–3% 的偏移 60–70% 对普通周末 26–45%),具体价位被扫的概率不比平常高。** 该学的:对象是走法、样本按状态配、结论落在单子的结构上;该补的:每张基率表自带对照。装置缺口开了 T-409(走法的原子函数、按小时线结算的命题、小时线回补到 2017)。登记表 #5。 **(2026-11-15 07:38 UTC 补,Jazz 外出前:「继续,你可以去市场上和其他 top trader 参考,完成长任务」)形态登记表有了第一条「状态 × 触发 × 人群」三样齐的:线下 · 稳定币抽 + 收盘破 20 日低做空 + 破位那天资金费仍为正(多头还没认输)—— +8.7% / +3.1% 每张(≤ 2022 / 2023 起),资金费为负时 −3.3%(S-886);底下那条形态第二份实现(SQL)逐项相同、平移 p = 0.09(S-879 补)。** 外部参考(`docs/research/EXTERNAL_SETUPS_2026-11-15.md`):公开的「顶级交易者方法」几乎都没有基率;加了对照之后,**「周末缺口会补」(70% 对同距离反方向 68–70%)、「到期前钉住」(秩检验不显著、2023 后消失)、「扫过前高前低再收回就反手」(四格无一站住)、「反弹回撤一半就空」(早进被挤)都是常态**(S-883 / S-884 / S-885)。站住的另一条:**线上 · 主流在领时收盘突破 20 日高做多**(2023 起 85 张 +6.1% / 张)—— 就是 R-v2 的开票方式与主场;多头那一侧资金费不分好坏(S-887,牛市里拥挤的多头是燃料)。「状态取长处」组合的盲复算对上(B 道 1.953 对我 1.945)。装置:走法命题(`high:` / `low:`,某时刻前碰没碰到某价位)可以记分了、BTC / ETH 小时线往回补到 2017(T-409,两个 runtime 提交在队列尾)。 **(2026-11-15 07:45 UTC 补)山寨轮动有了触发:** 山寨风格指数收盘突破 20 日高,在「线上 · 主流还在领」时 8 个指数 7 个两段都站住(平移 p = 0.033;S-888);落到 22 个主流山寨单币上也站住(620 张 +5.5% / 张、胜率 21%、盈亏比 9.6;S-889)—— **但单币版的平移 p = 0.27:站住的是「突破」本身,状态的用处是排除(线下 · 二线领做多两层都负),不是挑选。** 形态 #1 第一次前向记分已写成 6 条命题(11-12 ~ 11-14 BTC / ETH 的触发,结算 12-12)。 **(2026-11-15 07:47 UTC 补)两条道的结果回来了:** S-884 第二份(Python)与我的 SQL 逐项相同,整张表平移 p = 0.30 ⇒ 「扫过再收回」定稿为常态;S-881 的持仓读数切分退化(按时点 z 在 2023 年后漂到一边,T-399 改滚动分位)。**一句总话(登记表):价格触发是主力;状态在熊市做空那一侧最有用、要与人群读数一起确认(#1);在做多那一侧主要用来排除坏的格子(#2 / #3 平移 p = 0.19 / 0.27)。** **(2026-11-15 08:13 UTC 补,Jazz「这两个都不用等我…向前开始了」)前向开账:** 纸面账 `state_strength_v2`(T-395)写入端建好、排在提交队列尾(runtime,`0815-t395`);规则先登记(S-890):名单冻结 11-01 那一份、看前一天收盘的状态、等风险、对现金的超额,四条臂(趋势 × 谁在领 / 趋势 × 稳定币 / 只看趋势 / 全拿),**11-15 收盘开账,判读日 2027-02-15**。26 条成员里 9 条只有研究回测或等 T-406(R6、闸门空),当天按「该拿、拿不到」记;**开账这天 = 线下 · 主流领、名单只有 R6 ⇒ 主臂现金 —— 这套最优解此刻的主张是空着等。** 成员的生产序列与研究面板差多少 → T-411(A 道)。T-370 空单默认值由 Seth 定稿写在卡上(状态对 + 破位才开、被破那档之上 1% 且 ≤ 8%、一次进满、28 天、不自动加仓),交给交易那个对话执行。 **(08:41 UTC 补,loop-watch 日报)** 复测没有新坏的:不 ok 的 9 个循环里 7 个是冻结的 ④ 账本、1 个「已记录」、R 票纸面账在等 perp_bv 的 11-14(已落);`agent_call_log` 0 行 = 托管 /mcp 没有流量(管道 11-07 / 11-09 写过),不是回归 —— 日报技能的那条基线过期了。日报没看到的一处修了:CIS 输入拼装在事件循环里卡 5.9 秒 → 进线程(`0840-stall`)。今天 6 个 lane 分支排了合并;S642 的生产纯函数开 T-412(C 道)。 **(08:56 UTC 补)形态 #1 的前向记分自动化了(S-891):** 每天判 BTC / ETH,触发就写三条命题进情景台账(作者 `seth:setup-watch`,概率 = 基率两段中点);形态 #2 早段样本不够、按规则不进 v1。提交 `0845-setupwatch`。 **下一步:** 部署后判活 `select arm, min(d), max(d), count(*) from forward_book_nav where book = 'state_strength_v2' group by arm`(11-16 有开账行、11-17 有第一天收益);T-406 合入时把 R6 / 闸门空接进来;真钱不动。)

**更早:** 2026-11-15 01:17 UTC (Seth — **夜间收尾(Jazz 11-14 睡前「分配任务给各 lane,并完成交易优化、策略升级、组合优化的长任务」):四张卡都先登记后算,四份结果都回了、都合并了、都记了台账(S-865 / 866 / 867 / 868 结果),每份另核过一处。** **① 交易 —— 周期仓位通道的管票形态(T-385 + T-389 → T-370 卡上的表):管法动不了均值,动的是最差那一张。** 固定 8% 止损最差封在 −8%,45–65% 的票亏着出去;卡上现写的「上一周最高价之上」最差 −12%(BTC)/ −43%(ETH)、随便哪天有 21% 的日子开不了;2.5 × ATR 亏着被止损最少,但最差 −57%(ETH,暴跌之后 ATR 最宽)。**补量的一种:「2.5 × ATR 但不超过 12%」+ 2R 减半 —— 最差封在 −12%(30% 档 = 账户 −3.6%),8 个空的切片里 8 个没被别的管法压过;** 上限放 8% 就只是更贵的固定 8%(登记时先写明了:加上限只会让止损更近,买不到两头)。空的一侧 2R 减半不花钱;多的一侧提前落袋要付 0.7–1.4 个点 / 张。**没有判断的进场救不回来:** 随便哪天进场的 BTC 空单 18 种管法均值全负;机械条件(周线坏且线下)的空单只在两个熊市年是正的(2022、2026,2026 更大),其余六年合计为负 —— 判断来自 ⓪。**三样默认值等 Jazz 选,我没替他选。** **② 策略 —— 同格历史进了档案(T-386 盲复算 16 / 16 一致;已上线 095ba3f3,现构建 97ba9d76):** ③ 的档案与 ⓪ 简报多一行 —— 今天这一格历史上几段、之后 30 天 BTC / ETH / SOL 的分布、两种 p 并排。今天这一格(利率升 · 稳定币抽 · 周线坏 · 线下)12 段 / 257 天:「不涨」是 BTC 的读数(涨超 10%:14% 对全样本 32%),ETH / SOL 只是略差;**没有一个资产两种「双侧 p」都过 0.05(BTC 0.15 / 0.08,SOL 0.14 / 0.037,ETH 0.33 / 0.29;前一个是登记的算法)** ⇒ 档案里两种都写,「分得开」要两个都过线。只描述,不进规则。 **判活 ✅ 第一行真实数据(11-15 01:12 UTC 写入的 d = 11-14 那条 ③ 决定):12 段 / 257 天;BTC、ETH、SOL 的格内数与两份研究实现逐项相同,`missing` 里没有它。** 这一行的格子取的是 11-13(11-14 的稳定币读数当时还没到;那行字要把日期印出来,记在 T-388);③ 档案 v5 的作者行还没出现,看 02:12 UTC 之后那一轮:`select d, author from agent_judgment_daily order by d desc limit 2`。 **③ 组合 —— 机构规格的前沿与被动腿的代价(T-387):40% 线下 16 格只有一格过 —— 每票 0.25% / 名额 10(年化 20.7%、波动 18.6%、去掉最大一张票后 16.5%);我在 S-837 提的名额 14 自己就在线外(0.413)。回本时间在 16 格之间只差 21 天(741–762)—— 调 R-v2 的旋钮改不了回本时间。被动腿移出实盘在历史上:年化 −8.2 个点(35.7 → 27.5),最长水下不变(750 天),有效来源 2.0 → 1.5、R-v2 占风险 74% → 81%。** 不改 11-13 的裁定(范围是自有账户),只把代价放上来;对机构规格,被动腿不能照搬那条裁定。 **等 Jazz:** T-370 三样默认值(表在卡上;候选里多了「ATR 封顶 12% + 减半」)· 机构规格 v1 名额 14 → 10 · `T25_PASSIVE_LEGS_LIVE=0` 设不设(现在有代价的数了)· T-370 / T-371 开工(新会话、他在场)。 **没做 / 没推:** `_cis_tilt_loop` 每小时在事件循环上算约 5 秒(修法写好测过、记在 T-380,跟下一批 runtime 一起上,没有为它单独重启);一次性的定时核对建不了(本机不能再建定时任务)。新卡 T-388(验证装置给两种双侧 p 起名字;不急)。SYNC 16:44 归档过(现 54k)。**更正两处(都记了台账):** S-868 的「空单为正靠 2022 一年」读错了,是 2022 与 2026 两年;S-866 表里 SOL 的全样本与 p 来自 B 道脚本的一个坑(上市前 32 天拿最新收盘当进场价),已换成生产的数、B 道 T-390 修脚本;B 道报的「段首分歧 37 个」不是分歧,是我的脚本每格只输出最后 12 个段首。)

**更早:** 2026-11-14 16:07 UTC (Seth — **高维回看 11-14(Jazz「回到高维,继续推进」;全文 WEEKLY_REVIEW):现实走到了我给权重最小的那一格 —— BTC 11-11 收 74,015 → 11-14 盘中 65,735,三天 −11%;触发在利率(2 年期一周 +35bp 到 4.86),而我 11-13 把利率读成了缓和。** Jazz 11-13 签名的 off 判断与「明显是空头机会」在这三天是对的;系统加密敞口 0(① 一周 −10.4%,真钱 −0.7%、亏在被动腿),**但空的一侧没有任何表达:周期仓位通道(T-370)没建。** 没有一个投降标记(资金费 +5.3%、隐含波动没跳、吸筹清单 0 / 8);恐惧贪婪 13。下一段(到 12-12)三情境 30 / 55 / 15,8 条可结算命题已入库。**一个优先项 = T-370**(新会话、Jazz 在场、先 dry-run;上线前要他定止损线 / 止盈减仓形态 / 档位名义三样)。**等 Jazz:** `T25_PASSIVE_LEGS_LIVE=0` 还没设(11-13 的裁定,目标表今天仍是 股 30% / 金 20%)。同轮:执行主机取计划的 7 秒计算进了线程(T-380 b,已上线 bda3fda3)。**S-864 结果(A 道 T-384,先登记后算):今天这一格(利率升 · 稳定币抽 · 周线坏 · 线下)历史上 12 段 —— 之后 30 天中位约 0,涨超 10% 的机会 14% 对全样本 32%,跌超 10% 的 28% 对 20%;与随机平移分不开(p 0.15)。是「不涨」,不是「必跌」。只描述;接进档案的活在 T-369 ⑫。**)

**更早:** 2026-11-14 14:52 UTC (Seth — **Jazz「修复」(S-863,DECISIONS 已记),四件,已上线(78553f07)并核验前三件:regime fitness 13:51 写出第一批 5 行(TIGHTENING × 五个支柱,21 天,与事前量的一致);工厂循环记了冻结;新构建 0 条报错、19 分钟没有卡顿。GDELT 新节奏才跑两轮、都被限速,说明不了什么。⚠️ 看门线程又点了两处在请求里的:`/internal/schema-drift` 启动后第一次请求冻住进程约 52 秒、之后每次 6 秒上下(preflight 每跑一次请求它一次;已修并上线 5c996412,新构建前 13 分钟没再记到;剩 5–7 秒一档的零头,每次部署点到的名字不同,攒一批再搬);`/internal/executor/plan` 7 秒(真钱路径,没动,等 Jazz 在场 → T-380)。** 各件的细节:① `_regime_fitness_loop`:400 是因为表缺 `return_source` 列,已补(另加 `n_days`);补之前查过 —— **没有任何评分路径读这张表**(线上 IC 乘数读 Redis、正式 CIS 不用乘数),它是记录;第一批预计 5 行(TIGHTENING × 五个支柱,21 天)。② `_factory_recalibrate_loop` 跟随 combined book 的冻结(`frozen.py` 新字段 `also`;这是 Seth 对「修复」的读法,删那一行即恢复)。③ T-380 的两处同步请求进了线程;稳态三小时(10:26 → 12:56)看门线程全是 ok。④ GDELT:**更正 —— 我说「11-13 18:05 起一条没落」是错的,那之后落了 5 条新序列(最后一条 11-14 03:51);21 条里 10 条有行。** 原节奏一天 8 轮、每轮至多落一条,结构上轮不过来 21 条;改成 20 分钟看一次、通了一轮最多取 6 条,GPR 文件改 12 小时一次。**新节奏能多落多少没有把握**(限速按出口 IP,每次部署都换、与别的租户共用);判据:24 小时内 topic 数从 10 往 21 走。**)

**更早:** 2026-11-14 09:59 UTC (Seth — **每次部署后服务进程有两段共约 3 分钟完全不动(S-862 补二 / 补三):过去 12 次部署次次如此 —— 网站不回应、执行主机拿到过 502、循环的「读不到」多数是它(库 0.4 秒就回了,进程没空收)。** 装了一个测量(`src/api/loop_stall.py`:卡住的当时记下主线程停在哪一行,写进 `loop_attempt` 的 `_loop_stall_loop`),09:12 那次重启就点了名,四处同步重活合计 181 秒:市场态逐日计算 62.7 秒 · 信号归因 10.6 秒 · regime fitness 的同步请求加计算 64.2 秒 · 信号工厂同步拉 Binance 43.8 秒。四处都搬进线程,**已上线并核验(d3d38d11,09:46 启动,看了前 12 分钟):那四处不再出现,不回应从 193 秒降到两次 5 秒(新点名两处同步请求 → T-380);前两次重启读超时的三条循环这次都跑成了。范围:一次重启;稳态一整天还没看。****两条循环要 Jazz 定去留:** `_regime_fitness_loop` 10-30 起每轮以 400 失败(缺 `return_source` 列),白跑;`_factory_recalibrate_loop` 重算的是已冻结的 combined book。同批:`fetch_panel` 每页 10,000(T-379 第二步;`_read_all` 那一步没碰到 ohlcv_daily,量过了)。**)

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
