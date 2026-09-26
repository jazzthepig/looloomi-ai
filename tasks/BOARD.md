# 任务看板(生成物,勿手改:`python3 scripts/task_board.py`)

| 状态 | 任务 | 负责 | 标题 | 验收 | 之前 | 验证 |
|---|---|---|---|---|---|---|
| in_review | T-018 | lane-a | Mac 对 Railway 的读请求带 X-Internal-Token;空快照不生成简报;macro_brief 合约副本更新到 mb-3 | empty = 0 且 n > 0;最新一行 prompt_version = mb-3(Railway 日志 [MACRO] 无 prompt_version 告警) | 09-23:47 份里 36 份快照为空({}),39 份写「平静」;Mac 副本 mb-2 |  |
| in_review | T-011 | lane-b | Jev 仓位乘数对照线:先预注册(只调 1 个参数,4 级基准) | 合并者确认后 Seth 接进 hl_book_daily | 无 |  |
| in_review | T-025 | seth | ② 代币化基础设施倾斜账本上线:第一行真实数据 + 连续前向记录 | 两臂都有行,min(d)=2026-09-25,max(d)=昨天(UTC 06:00 后);09-26 起 nav ≠ 1.0 | 代币化论点 09-01 起只在观测层(S-266),没有任何账本;① 里只有 LINK 3.8% |  |
| in_review | T-029 | seth | ② β+ 动量 + 52 周高点前向账本上线(四臂) | 四臂都有行,min(d)=2026-09-25、max(d)=昨天;momentum_52w_w 与 panel_hold_w 的 NAV 不同 | ② 从未建过前向账本;S-428 研究周频 +17.2%/年(t 3.22) |  |
| open | T-015 | jazz | 创建 HL API 钱包 + 开东京/新加坡云主机 | API 钱包只可交易不可提币;主机可 SSH | 无 |  |
| open | T-001 | lane-a | T1 的 TradFi 改从 ohlcv_daily(eodhd)读,撤回 30 天过期缓存 | = 43,且 19 个 TradFi 最新价格日期 ≥ 最近一个美股交易日 | 24 |  |
| open | T-003 | lane-a | S-396 三臂回放 live 验证(读路径分页修复后) | 相等 | replay 读到 1,000 行(截断) |  |
| open | T-004 | lane-a | 恢复持币集中度写入(holder_concentration_history) | = 今天(UTC) | 2026-08-31 |  |
| open | T-023 | lane-a | CIS universe API:把 Tier 标签(T1/T2)传到前端,CISLeaderboard 徽章按源染色 | T1 标的徽章绿、T2 标的徽章琥珀;不再全部 50% 灰 | GET /api/v1/cis/universe:universe 58 行,但 data_source=None(API 层未传播 Tier)。CISLeaderboard 徽章当前无法区分 |  |
| open | T-024 | lane-a | P0:找到并停掉第二个 T1 写入端(非整点推送,DQS 全空、confidence 不同) | 每小时 pushes = 1 且 dq_null = 0,连续 12 小时 | 09-24 起 19 次非整点 T1 推送(08:09、08:15、09:09 … 09-26 02:07、03:09);这些推送 confidence 为 0.67/0.83/1.0(常规引擎是 0.70/0.85),DQS 全空,BTC 分类为 L1(常规为 Crypto)。网站在两版之间每小时切换一次。 |  |
| open | T-005 | lane-c | Layer C 重新设计(不强制现金),先写 M- 台账再跑 | β 匹配超额 > 0 的格子 ≥ 1 个 split 过半,且 β ∈ [0.5, 0.9] | β 匹配 0/30,β≈0.35 |  |
| open | T-006 | lane-c | Strategy 3/4 按正确问题复核 | 每格都有数字,不是只给一个总 Sharpe | 只用绝对 Sharpe 判为 REFUTED |  |
| open | T-007 | lane-c | CG 新闻监听器写入 Supabase(经 Railway mac_writes) | > 0 | 只在 Mac 本地 cis_history.db,13 行 |  |
| open | T-009 | lane-c | data_quality_score:先修 data_freshness,再算分,随推送落库 | > 0 且 值有区分度(不全相同) | 0(列一直为空) |  |
| open | T-010 | lane-c | Mac 上的 key 统一到 ~/.config/cometcloud/.env(chmod 600),plist 不放 key | = 0 | 2 个 plist 硬写 key |  |
| open | T-012 | seth | HL 采集器加持仓量(OI) | > 200 个币 | 0(没有存) |  |
| open | T-013 | seth | 首页和页面路由免于限流 | 仍返回 HTML 200 | 返回 JSON 429 |  |
| open | T-021 | seth | 死链与遗留路由:6 个静态 .html 200/41121(全返落地页)+ 4 个 SPA 不用的 API 返 404 | curl -I /market.html 返回 30x 或 4xx(非 200/41121);SPA bundle 仍能在 /app.html 正常加载 8 个 section | /market.html 200/41121,/cis.html 200/41121,/vault.html 200/41121,/protocol.html 200/41121,/intelligence.html 200/41121,/quant-gp.html 200/41121;SPA shell 在 /app.html(2424 字节);Sidebar/SiteNav 全链 /app.html;4 个 API 全 404 但 SPA bundle 不调用 |  |
| open | T-022 | seth | 移动端 RECENT SIGNALS 卡片:百分比与文案跨度对齐(短时价格不和"strong momentum"同屏) | DOM/截图: 卡片百分比后缀为 '24h' 或 '(24h)';文案与百分比跨度一致(避免 −7% 旁边写 'strong momentum') | MobileApp 卡片:'positions to outperform on strong momentum' 旁显示 −7.45% / −8.98%(百分比实为 24h,跨度与文案冲突) |  |
| open | T-026 | seth | fusion 账本:22 天只扣成本不记价格(ret ≡ −0.05%),state 表为空 | > 1(按价格记账,不再是常数) | 22 天 daily_return 全为 −0.00050,NAV 0.9990→0.9960 线性 |  |
| open | T-027 | seth | 多空账本存完整权重(不只前三),让「是否持有 X」可回答 | 完整权重 jsonb,非空 | 只存 top_longs/top_shorts 各 3 个;09-24/25 LINK 是否持有无法回答 |  |
| open | T-028 | seth | SKY 日线回填(替换已下架的 MKR 进代币化篮子) | 覆盖到昨天、≥365 天;之后篮子加 SKY 为新起点(旧记录留档) | SKY 只有 15 天(08-09→08-23),之后停更 |  |
| open | T-030 | seth | binance_hist 回填:过去一年整天缺 41 天(最后 09-06) | = 0 | 20 个币各缺 41 天,ETC/SUI/TRX 29 天,BCH 17 天 |  |
| open | T-031 | seth | CG Pro 面板停写 5 个 ① 面板币(BCH/DOGE/FIL/LTC/TRX,自 09-13) | 5 个都 = 昨天;并在 SPINE / 守卫里说明为什么它们会掉出写入宇宙 | 5 个币最后一行都是 2026-09-13 |  |
| blocked(等 ['T-001']) | T-020 | lane-c | DQS 的新鲜度改用源自己的时间戳(CG last_updated / kline close / TVL date / 日线 bar date),不用抓取时刻 | 同一次 push 内的取值随各资产源时间戳变化;日线源在最近一个应有收盘之内不被衰减 | 同一次 push 只有 2 档(0.67/0.81 → 0.70/0.85),随批次时刻整体漂移 |  |
| blocked(等 T-015) | T-016 | seth | 实盘执行器(只算不发两天 → 3,000U 真跑) | > 0,且每日对账有数 | 0 |  |
| done | T-002 | lane-a | 确认 T1 每小时一批恢复 | >= 20 | 1(09-24 恢复当天) | 24 个不同小时有 T1 推送(过去 24h),≥20 通过;Mac 侧卡按数据直接验收(S-426) @ 2026-09-26 |
| done | T-008 | seth | Railway 侧:新闻事件表 + mac_writes 白名单 | 201 且 write_log 有行 | 无 | POST /internal/mac-write/narrative-events(rows=[{event_id,date,event_type,narrative_tag,description,related_assets,source_round}])→ 200 verdict=ok n_written=1 n_rejected=0;write_log id=26527 outcome=ok writer=src.api.routers.mac_writes.mac_write;narrative_events 表里 verify 行落成功 @ 2026-09-26T02:01:00Z |
| done | T-014 | seth | 产品面审计(内置浏览器,走 Jazz 网络) | 每页有结论,问题都转成任务卡 | 3 周未动 | docs/PRODUCT_AUDIT_2026-09-24.md 已写满 4 屏(开屏/落地/SPA/Mobile)+ 2026-09-26 路由审计 + 6 页结论;3 张任务卡派生(T-021 死链/死 API,T-022 移动端文案冲突,T-023 CIS Tier 标签)。SPA 实际路由 8 section 走通,4 个死 API + 6 个死 .html 全部 404/200-landing 已审计(不阻塞,转为清理卡)。剩余 Portfolio/API Keys/Portfolio Builder/Score Analytics/Agent API/Fund Strategy/移动 Rankings/Signal — 暂留 follow-up。 @ 2026-09-26T03:30:00Z |
| done | T-017 | seth | 宏观简报:兜底模板去掉仓位建议 + 24h 变化读对键名 + 不再把几分钟的静止写成市场平静;移动端把缺失的 direction 显示成 NEUTRAL | 文本含 24h 变化数值;不含 Accumulat/contrarian entry/Allocate/Reduce/favoured;Mac 推来的 prompt_version = mb-3 | 模板:'BTC at $83,403 (— 24h)' + 'Risk-off positioning favoured';LLM 简报:'market tape is currently flat',当日总市值 24h -6.4%;移动端 RECENT SIGNALS:空标的行 + 4 条全显示 NEUTRAL(feed 里 direction 全为 null) | Railway mb-3 端:GET /api/v1/macro/brief 含 24h 变化('-2.1% over 24 hours' / '-0.0% over 24 hours' + 02:54 UTC 时间戳),最新 brief 文本无 Accumulat/contrarian entry/Allocate/Reduce/favoured。src/api/contracts/macro_brief.py PROMPT_VERSION=mb-3 ✅,src/api/routers/macro.py 收端校验 prompt_version=mb-3。**Mac 副本 mb-2 → mb-3 仍待**(/Volumes/CometCloudAI/cometcloud-local/macro_brief_contract.py:36 仍 mb-2)→ **T-018 lane-a**(卡 notes 已声明) @ 2026-09-26T01:55:00Z |
| done | T-019 | seth | prediction_resolver:4 个 date 列来源恢复出结果;不再 409 | 5 个来源都有行(positioning/forward_supply/conviction/narrative 各 >0);409 = 0 | 只有 signal 170 行,其余 4 个来源 0 行;2h 内 409 × 326 | 5/5 来源有行:positioning 436 · conviction 428 · signal 170 · forward_supply 104 · narrative 14;部署后首轮 15:24–15:30 UTC,POST prediction_outcomes 982×201、0×409 @ 2026-09-25 |

open 20 · blocked 2 · in_review 4 · done 5
