# PROJECT_STATE.md — the living single source of truth

**Last updated:** 2026-10-30 18:26 UTC (Seth — **夜班(Jazz「回到高维,按你的想法完善整个项目」),到 17:25 落了四件:** ① **执行质量日表** `execution_quality_daily`(18d3cb96):`fill_log.execution_quality` 自 T-122 起从没有调用者,真钱第一批成交之后有了 —— 每本执行账每天一行 + 累计,滑点对决策时中间价 / 费 / 机会成本 / 实施差额,锚进 forward_anchor_daily,证据面 `/api/v1/proof/books` 加 `execution` 段;实测 t25_legs_live 2 笔 fill_rate 1、滑点 +3.5 bps、费 7 bps、差额 10.5 bps。证据面的 note 不再说「全是纸面」。② **S-371 A-1 + A-2 收敛落地**(d0bdf7ab):`INTERNAL_TOKEN` 的 45 处比较 / 17 个文件 / 12 个 import 期常量 → `src/api/auth_internal.require_internal_token()` 一处,请求期读 env、常数时间、按 lane 归因;契约测试 2 红 9 跳 → 11 绿并进 preflight;**轮换现在是原子的**(Railway 入侵后的轮换从此可做,OPEN RISK 1)。③ **S-700 按时点的 ① 对照臂** `cap_pit24`(b8bbe7a9):逐月前 24 大市值、含死币、排稳定币 / 包裹凭证 / 代币化债权、选成员那天换手 ≥ 1%,权重公式同 `core_alpha_daily`,2019 起,6 小时一轮写 core_variants_daily;`asset_mcap_daily` 补齐循环在跑(2018-12 起 + 22 个死币 / 缺名,核价后才写)。补齐前第一眼:2021 PIT +203% vs 幸存者 +236%。**不改 registry.core_nav,换锚是 Jazz 的决定。**④ **OPEN RISKS 整块重写**:11 条 → 5 条活的,旧块原文进 LOG;C-13 nav_panel 声明按 10-06 兜底撤掉;venue registry 90 天复核(4580e07d:HYPE 已在 Binance 现货、MKR 全场死、SKY 加入)。另:`asset_embeddings_history.vec` 全空是 S-178 的设计(vec_full 为准),我 06:38 那句「要走 §2 合约」是错的,撤回。T25 腿 10-30 15:44 真单成交(SPYX 0.23 @ 762.23、XAUT0 0.03 @ 3907.5,费 $0.20),`LEGS_LIVE = True`(f0a8f48b)。)

**更早:** 2026-10-30 15:42 UTC (Seth — **T25 黄金 / 股票腿接进东京执行器(Jazz 10-30「change the nav_cap to 600 // yes」),先空跑。**同一个 HL 账户、同一套意图 / 成交记录:XAUT0/USDC(@182)目标 $120、SPYX/USDC(@703)目标 $180,来自 `portfolio_targets.plan_fields` 的 `portfolio.t25`(与目标表同一份权重)。规则 `exec_host/legs`:第一次接上(持仓 0)直接建仓;再平衡日回到目标;其余日子只纠偏离 > 5% × 600 的腿;差额 < $10 或没报价 ⇒ 不动(没报价 ≠ 持仓 0);卖在前、不超过可用余额。`EXECUTOR_T25_MODE` 默认 dry_run(sleeve `t25_legs_host_dry`),一天一轮按模式记 ⇒ 当天空跑过、切 live 当场跑一轮。R-v2 统一账户净值从此把现货代币按 USDC 中间价算进去;每日真钱快照用主机心跳里的 XAUT0 / SPYX 市值(没有日线收盘)。顺手修了一个会留零头的取整(0.06 − 0.02 向下取整成 0.03)。**15:39 UTC 主机已更新、空跑核过:** nav_cap 600(X1V 实际 $180)、agent 有效到 2027-01-27;`execution_intents` 两行 sleeve `t25_legs_host_dry`(SPYX 买 0.23 ≈ $175.35 限价 766.22、XAUT0 买 0.03 ≈ $117.24 限价 3927.6,都是中间价 +0.5%;估滑点 2.8 / 4.9 bps;`t25:再平衡日` = 开账日),回报 `book = t25` 被 Railway 收下,心跳 `t25_done_asof = 2026-10-29`。**剩 Jazz 一步:** 双击 `scripts/host_t25_live.command`(要输 yes)⇒ 当场真单;成交后 Seth 把 `LEGS_LIVE` 翻成 True。X1V 实际额度仍是 min(600, 加密腿 $180) = $180。commit 走 seth_bot `zv`。)

**更早:** 2026-10-30 06:38 UTC (Seth — **矢量库 v2 上线 + 地基修好(S-698 / S-699)。** **① `binance_hist` 统一成现货:** 06:05 UTC 跑完,262 个标的全过(216 改成 / 核成现货,46 个没有现货对、留原处并从面板排除);187,928 行永续 bar 原样存进 `binance_um_hist` 后换成现货,141 个标的补深度 79,834 行(2020-01-01 前已有数据的标的 14 → 59、2019 年 7 → 17);独立复核:同一脚本 2025-06-15 抽 10 个,修前 9 个是永续,修后 10/10 是现货。**会动的:** 吃成交量的回放(R-v2 历史扫描、ADV 准入、① 回放臂)—— 前向锁住的行不动。**② `market_state_vectors` v2(06:31 UTC):** 2,525 行,2019-12 → 2026-10;按月时点面板(上月末 30 日成交额前 25,83 个月 / 140 个成员,无前视)、扩张窗口 z;实测维 v1 每天 11 → 2021–24 年 15–16、2026 年 20.5(资金费 / OI / CIS / fng / 稳定币供给接上;旧读法一页 limit=5000 撞 1000 行上限,那几维原来只有几天);与 v1 近邻重叠平均 1.08 / 10,18% 的近邻落在新补的 2020–21。`similar_market_states` 改在共同实测维上比(旧版只留维数齐备的天,v2 下会只剩最近一年)。**③ T-214 done:** 黄金 XAUT0 与股票 SPYX 都在 **HL 现货上有 USDC 对** —— T25 三条腿可以在同一个账户、同一个执行器(待 Jazz 定)。**④ 东京主机已更新(13:54 UTC 10-30,Jazz):** 自检 `perp_account.mode = unifiedAccount`、R-v2 记账净值 630.64(原来读成 0)、X1V `nav_cap_effective = 180`(组合层加密腿额度);13:55 心跳已带 `account` 段 ⇒ 每日真钱快照从 10-30 起有账户模式。443 那次「主机钥匙变了」是 known_hosts 里重建前旧机器的记录,脚本核对 22 上认过的同一把钥匙后才替换。`asset_embeddings_history` 4,003 行 vec 空(Mac 推 27 维、列是 18 维,要走 §2 合约)。)

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

2. **🟡 R-v2 的研究与前向不是同一个宇宙(S-637 → S-698 之后剩下的半截)。** 数据侧已定:`binance_hist` 10-30 起现货贯通,永续 bar 原样存 `source = binance_um_hist`(禁入收益序列)。
   研究(S-610 / S-638 / S-639,769 票 / +0.253R)跑在永续混合口径上;前向 `r_tickets_scan` 读 binance_hist = 现货。T-151 量过:现货面板 492 票 / +0.178R(少 36%)。
   前向宇宙随之从约 181 个名字缩到 **135**(46 个只有永续对的名字被排除)。10-19 起 0 张票**不是故障**:10-30 复算,majors 闸门整个 10 月都开着(高于 200 日线 6–20%),是全市场没有 40 日新高(10-19 起 0 个突破、10-26 那周 1 个;8 月下旬那周有 27 个信号)—— 规则在正确地等。
   **要 Jazz 定:** 要不要按现货面板重算 S-638 / S-639 并把它当前向的对照;或者 R-v2 的回放改读 `binance_um_hist`(永续 = 它实际执行的市场)。定之前两边都不改。
   VERIFY: `select source, count(*) from ohlcv_daily where symbol = 'CRV' and trade_date between '2025-06-01' and '2025-06-30' group by 1` → 两个 source 各约 30 行;`select count(*) from ohlcv_daily where source = 'binance_um_hist'` = 259,986(10-30 实测;187,928 是改成现货的那部分,其余是没有现货对、原地保留并同时存档的)。
   OWNER: Jazz(定口径)· Seth(执行)

3. **🟡 真钱第一周:三条新记账线都只有一两行,每条都要在第一个完整日核一次。**
   ① `live_account_daily` 10-30 这行应把 XAUT0 / SPYX 按主机心跳市值计入(`spot_usd` 两个键,`note` 含「HL 中间价」);② `execution_quality_daily` since_inception:t25_legs_live 2 笔、fill_rate 1、滑点 +3.5 bps、费 7 bps(HL 现货 taker 0.07%);
   ③ `portfolio_targets_daily` 10-31 起 gold / equity `executable = true`。已知未做:再平衡日(21 个交易日后 ≈ 11-30)资本仍按 600 定,不按真钱快照(legs.py 注「P5」);HL 现货买单手续费扣基础币 ⇒ 持仓 0.029979 不是 0.03,整仓卖出会留 0.0099 零头(≈ $39)——当前规则不会整仓卖,记着。
   VERIFY: `select d, equity_usd, spot_usd, nav, note from live_account_daily order by d desc limit 2` · `select sleeve, n_intents, fill_rate, mean_slippage_bps, implementation_shortfall_bps from execution_quality_daily where span = 'since_inception'` · `select d, sleeve, executable from portfolio_targets_daily where d = current_date`。
   OWNER: Seth

4. **🟡 ① 的历史是今天的名单回填(S-700):状态层与评估层拿幸存者名单当基准。** 对照臂 `cap_pit24`(逐月前 24 大市值、含死币、2019 起)10-30 起每 6 小时写 `core_variants_daily`;`asset_mcap_daily` 补齐在跑(2018-12 起 + EOS / LUNA / BSV / LEO / HT / OMG …,每个映射核价后才写)。
   补齐前第一眼(描述,不判):2021 PIT +203% vs 幸存者 +236%;2020 +267% vs +285%;LUNA / FTT 接上后 2022 会再低。**换不换 `registry.core_nav` 的历史锚是 Jazz 的决定**;换了 ⇒ state_daily 回填 2019 起、rr_matrix 重算。
   VERIFY: `select min(d), max(d), count(*) from core_variants_daily where arm = 'cap_pit24'` → 2019-01 起、到昨天;`select detail->'remaining', detail->'notes' from loop_attempt where loop_name = '_mcap_deepen_loop' order by at desc limit 1` → remaining 0,notes 里 rejected 的名字逐个看。
   OWNER: Seth(数据 + 臂)· Jazz(锚)

5. **🟡 `cis_regime_fitness` 0 行、IC 乘数四个月从未通电,而循环一直记 ok。** 函数早在 S-202 改成 degraded,`_regime_fitness_loop` 照旧记 ok(ba453fcb 起记真话,同形的另三个循环一并改)。原因:90 天窗口里独立交易日 18 < 20。**要 Jazz 定:** 窗口放到 365 天让它通电(CIS 权重会变),还是接受 CIS 一直在 NEUTRAL 权重上跑。
   VERIFY: `select count(*) from cis_regime_fitness`;`select at, outcome, reason from loop_attempt where loop_name = '_regime_fitness_loop' order by at desc limit 2` → 应是 refused + 原因。
   OWNER: Jazz(方法论)· Seth(改窗口)

6. **🟡 `INTERNAL_TOKEN` 的 Mac 副本仍在 `cometcloud-local/.env`(lane 能读到的位置)。** #0d 的尾巴:Mac 引擎的 secret 应搬到 `~/.cometcloud/engine.env`(SYNC #31),搬完再做第 1 条的轮换才不会漏一处(S-371 的「漏改第三份」09-28 发生过)。
   VERIFY: Mac 上 `grep -c INTERNAL_TOKEN /Volumes/CometCloudAI/cometcloud-local/.env` → 0,`test -s ~/.cometcloud/engine.env`。
   OWNER: Minimax(搬)· Jazz(值)· Seth(核)

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

