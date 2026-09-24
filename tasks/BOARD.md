# 任务看板(生成物,勿手改:`python3 scripts/task_board.py`)

| 状态 | 任务 | 负责 | 标题 | 验收 | 之前 | 验证 |
|---|---|---|---|---|---|---|
| open | T-015 | jazz | 创建 HL API 钱包 + 开东京/新加坡云主机 | API 钱包只可交易不可提币;主机可 SSH | 无 |  |
| open | T-001 | lane-a | T1 的 TradFi 改从 ohlcv_daily(eodhd)读,撤回 30 天过期缓存 | = 43,且 19 个 TradFi 最新价格日期 ≥ 最近一个美股交易日 | 24 |  |
| open | T-002 | lane-a | 确认 T1 每小时一批恢复 | >= 20 | 1(09-24 恢复当天) |  |
| open | T-003 | lane-a | S-396 三臂回放 live 验证(读路径分页修复后) | 相等 | replay 读到 1,000 行(截断) |  |
| open | T-004 | lane-a | 恢复持币集中度写入(holder_concentration_history) | = 今天(UTC) | 2026-08-31 |  |
| open | T-011 | lane-b | Jev 仓位乘数对照线:先预注册(只调 1 个参数,4 级基准) | 合并者确认后 Seth 接进 hl_book_daily | 无 |  |
| open | T-005 | lane-c | Layer C 重新设计(不强制现金),先写 M- 台账再跑 | β 匹配超额 > 0 的格子 ≥ 1 个 split 过半,且 β ∈ [0.5, 0.9] | β 匹配 0/30,β≈0.35 |  |
| open | T-006 | lane-c | Strategy 3/4 按正确问题复核 | 每格都有数字,不是只给一个总 Sharpe | 只用绝对 Sharpe 判为 REFUTED |  |
| open | T-009 | lane-c | data_quality_score:先修 data_freshness,再算分,随推送落库 | > 0 且 值有区分度(不全相同) | 0(列一直为空) |  |
| open | T-010 | lane-c | Mac 上的 key 统一到 ~/.config/cometcloud/.env(chmod 600),plist 不放 key | = 0 | 2 个 plist 硬写 key |  |
| open | T-008 | seth | Railway 侧:新闻事件表 + mac_writes 白名单 | 201 且 write_log 有行 | 无 |  |
| open | T-012 | seth | HL 采集器加持仓量(OI) | > 200 个币 | 0(没有存) |  |
| open | T-013 | seth | 首页和页面路由免于限流 | 仍返回 HTML 200 | 返回 JSON 429 |  |
| open | T-014 | seth | 产品面审计(内置浏览器,走 Jazz 网络) | 每页有结论,问题都转成任务卡 | 3 周未动 |  |
| blocked(等 T-008) | T-007 | lane-c | CG 新闻监听器写入 Supabase(经 Railway mac_writes) | > 0 | 只在 Mac 本地 cis_history.db,13 行 |  |
| blocked(等 T-015) | T-016 | seth | 实盘执行器(只算不发两天 → 3,000U 真跑) | > 0,且每日对账有数 | 0 |  |

open 14 · blocked 2
