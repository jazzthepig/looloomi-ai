# T-426 —— 执行计划的收盘价兜底(`EXEC_PRICE_FALLBACK`)

**日期**:2026-11-23(lane-b / Minimax-B)
**卡**:`tasks/T-426.json`
**分支**:`lane-b/T-426`
**开关由 Seth 定。** 本文只给数与取舍,不开关、不替真钱做决定。

---

## 0. 一句话

CoinGecko 订阅停了(Jazz 11-21 → 12-01),真钱执行计划的收盘价只认 CG 的 `asset_mcap_daily`,
该表从 **2026-11-20 起 0 行** ⇒ `host_plan.plan_core` 每轮 `ok=False` ⇒ X1V 的目标与止损线刷不出来。
库里有第二条价(`ohlcv_daily` / `binance_hist`,照常落到 **2026-11-22**),两源 365 天逐日差 **中位 6.4–6.9 bp**。
本卡交付一个**默认关**的兜底:开关打开时只补主源缺的那几天、来源逐日标出来,关着时行为与今天**逐位相同**。

---

## 1. 机制(实测,不是推演)

`host_plan.plan_core(asof)` → `forward_books.tom_inputs(asof)` → `forward_books.prices(["BTC","ETH"], …)`
只读 `asset_mcap_daily`(CG `market_chart`)。主源最后一天 < `asof` ⇒
`{"ok": False, "why": "… 的收盘还没全部落库:{'BTC': '2026-11-19', 'ETH': '2026-11-19'}"}`。
(Seth 的卡记:7 天 613 次只有 4 次 ok,最后一次 ok 是 2026-11-20 00:10Z。)

**真库复核(只读,本卡脚本 `t426_probe.py live`)**:

| | `tom_inputs` BTC/ETH 最后一天 | `plan_core("2026-11-22")` |
|---|---|---|
| `EXEC_PRICE_FALLBACK` 未设 / ≠ "1" | **2026-11-19** | `ok=False`,why = 「收盘还没全部落库」 |
| `EXEC_PRICE_FALLBACK=1` | **2026-11-22** | `ok=True`;targets BTC 0.0 / ETH 0.0;stop_px BTC 54235.38 / ETH 1493.24;last_close BTC 61271.1 / ETH 1724.33 |

兜底接管时逐日来源(实测):

```
2026-11-19 → asset_mcap_daily
2026-11-20 → binance_hist
2026-11-21 → binance_hist
2026-11-22 → binance_hist
```

---

## 2. ① 两源逐日差(2025-11-20 → 2026-11-19,365 天)

`asset_mcap_daily.price`(source=`coingecko_pro_market_chart`)vs `ohlcv_daily.close`(source=`binance_hist`),
差 = (CG / binance − 1) × 1e4(bp)。两源这 365 天**都有 365 行**,无缺口。

| | BTC | ETH |
|---|---|---|
| 共同日 | 365 | 365 |
| 绝对差中位数 | **6.94 bp** | **6.39 bp** |
| 绝对差 p99 | **48.98 bp** | **58.07 bp** |
| 绝对差 max | **362.37 bp**(2026-02-22) | **431.97 bp**(2026-02-22) |
| 有符号中位数 | −5.94 bp(CG 略低于 binance) | −5.24 bp |
| 有符号范围 | −362.37 … +38.23 bp | −431.97 … +60.27 bp |

**有没有错一天**(T-044 的做法:CG 当日 vs binance 同日 / 前一日 / 后一日,哪个更近):

| | 同日更近 | 前一日更近 | 后一日更近 |
|---|---|---|---|
| BTC | **328 / 365** | 20 | 17 |
| ETH | **339 / 365** | 11 | 15 |

⇒ **不是系统性错一天**(90% / 93% 同日命中);剩下 8%–10% 是"离得太近分不出"的一类,不是时区错位。

---

## 3. ② 11-01 … 11-19:两源各跑一次 `make_plan`(19 天)

`host_plan.make_plan` 是纯函数(不改它)。CORE 腿两源共用同一条(`multiplier_daily.core_u_replay`),只有 BTC/ETH 的收盘换源。

| | 结果 |
|---|---|
| 目标权重不同的天数 | **0 / 19**(19 天逐位相同) |
| 止损线最大差 | **14.83 bp**(BTC,11-08 与 11-09);ETH 最大 14.46 bp |
| CORE 止损线差 | 0 bp(同一条序列) |
| 19 天的目标值 | **全是 0.0**(两个源都是) |

⇒ 两源差异对**目标**没有影响,对**止损线**的影响在 15 bp 以内 —— 比 p99(49–58 bp)还小,因为止损线取的是 20 日窗口最低,单日噪声被抹平。

---

## 4. ③ 兜底的形状(代码)

新文件 `src/data/execution/price_fallback.py`;接点**只在** `forward_books.tom_inputs`(卡点名的那一处)。

- **开关**:`EXEC_PRICE_FALLBACK=1` 才开;不等于 `"1"` 的任何值(含未设置)都当关。
- **接管条件**:该币**主源最后一天 < `end`**。主源已经跟到 `end` 的币 —— 一个字节都不动。
- **补什么**:主源缺、而兜底源有的那些天(≤ `end`)。主源已有的行**一律保留主源的值**。
- **补的价**:`ohlcv_daily`(source=`binance_hist`)的 `close` —— 库内真实成交价。**不补 0、不补前一日的值**。
- **兜底源自己缺的那天**:宁可序列断在那里,也不填(测试 `test_gap_in_fallback_is_left_alone`)。
- **来源标注**:接管时每个日期的来源写进 `Series.attrs["price_source_by_date"]`;另留模块级
  `price_fallback.last_takeover()`(哪个币、接管了哪几天、主源最后一天)。
- **默认关的行为**:`tom_inputs` 的返回与 11-23 之前**逐位相同**,而且**一次 `ohlcv_daily` 查询都不发**。
- 没改 `executor.py` / `host_plan.py` / 任何止损与限额常量。

---

## 5. ④ 测试(`tests/test_exec_price_fallback.py`,9 个,全过)

| 测试 | 钉住什么 |
|---|---|
| `test_off_by_default_returns_identical_and_asks_nothing_extra` | 关 ⇒ 逐位相同 + 不多打一次库 |
| `test_off_is_the_default_even_when_env_is_garbage` | `"0"/""/"true"/"yes"/"11"` 一律当关 |
| `test_on_takes_over_only_missing_days_and_marks_source` | 开 ⇒ 只补缺的天、来源逐日标出、值不是 0 也不是前一日 |
| `test_on_leaves_alone_a_symbol_whose_primary_is_current` | 主源已跟到 end ⇒ 不接管 |
| `test_gap_in_fallback_is_left_alone` | 兜底源缺的那天不填 |
| `test_fallback_plan_matches_perfect_fallback` | 兜底价取真实 binance close ⇒ 目标逐位相同、止损线差 < 50 bp |
| `test_mutation_must_break_the_consistency_check` | **变异:兜底价 × 1.01 ⇒ 一致性必须被打破** |
| `test_merge_missing_never_overwrites_primary` | 主源的值不许被覆盖 |
| `test_last_takeover_records_which_days` | 接管记录可读 |

**变异测试(卡 §④ 明写的那条)**:把兜底价乘 1.01 后,一致性断言从「止损线差 < 50 bp」变成「> 50 bp」——
变异前 gap = 0.00 bp(通过),变异后 gap > 50 bp(红)。假价格曲线特意做成「先涨后跌」,让 20 日窗口最低落在兜底补的那几天,
否则止损线取的是主源里的老价、变异杀不死(第一版就是这么写的,变异没杀死,改的)。

---

## 6. ⑤ 停写清单(2026-11-19 之后停写的前向账 / 真钱输入)

只读扫描(48 张代码里读写的表 + 40 张手写候选表;每张表 `order=<日期列>.desc&limit=1` + `Prefer: count=exact`)。
**本 lane 只能读 publishable key 能读的表** —— `forward_book_nav` / `forward_book_holdings` /
`portfolio_targets_daily` / `world50_book_nav` 对本 key 是 **401 权限拒绝**,最后一天未知,需 @seth 用 service_role 核。

| 表 | 最后一天 | 卡住原因(因为读了哪个 CG 源) | 库内替代 |
|---|---|---|---|
| `asset_mcap_daily` | **2026-11-19** | 本身就是 CG `market_chart` 的落库(订阅停) | `ohlcv_daily`(`binance_hist`)→ 11-22 ✓ |
| `cis_official_daily` | **2026-11-19** | CIS 的 F / O 柱要 CG 的价与市值 | 价:`ohlcv_daily` ✓;市值:无(T-422 已做兜底,默认关) |
| `style_index_pit_daily` | **2026-11-19** | 风格指数的价格腿走 CG | `ohlcv_daily` ✓ |
| `r_money_daily` | **2026-11-19** | 真钱快照的估值走 CG | `ohlcv_daily` ✓ |
| `hl_book_daily` | **2026-11-19** | HL 账本要 CG 收盘(`_hl_book_loop`) | `ohlcv_daily` ✓ |
| `cg_coin_mcap_daily` | **2026-11-18** | 另一张 CG 市值表 | 无(CG 专有) |
| `execution_intents` / `execution_outcomes` / `decisions` / `j_tickets` / `j_tickets_state` / `trade_results` / `nav_exceptions` / `regime_calls` / `holder_concentration_history` | **0 行** | 写端存在但一行都没写进去(S-405 那一类:不是 CG 断供) | — |
| `forward_book_nav` / `forward_book_holdings` / `portfolio_targets_daily` / `world50_book_nav` | **本 lane 读不到(401)** | 未知 | 需 @seth 核 |
| `ohlcv_daily` / `core_cap_daily` / `multiplier_daily` / `state_daily` / `carry_hl_daily` | 2026-11-22 | 正常在写 | — |
| `market_state_vectors` | 2026-11-21 | 未归因(本卡范围内未查) | — |
| `crowd_clock_log` | 2026-11-20 | 未归因 | — |
| `world50_mcap_weekly` | 2026-11-20 | 周更节奏(6 天一轮),非断供 | — |
| `experiment_runs` | 2026-11-14 | 未归因 | — |
| `macro_briefs` / `beta_core_nav` / `funding_history` / `world50_revenue` / `open_interest_history` / `loop_attempt` | 有行但无匹配日期列 ⇒ 最后一天**未测出** | — | — |

卡上点名的循环对应:`_executor_dry_run_loop` ← `asset_mcap_daily`;`_cis_official_loop` ← `cis_official_daily`;
`_hl_book_loop` ← `hl_book_daily`;`_r_tickets_paper_loop`(停在 11-19「majors index missing on 2026-11-20」)← 风格/指数腿;
`_tokenization_tilt_loop` ← 本次扫描的表名里没定位到它的落库表(未归因)。

**清单行数:19 张有明确结论(其中 6 张因 CG 断供停在 11-19、9 张 0 行、4 张 401 读不到),另 10 张未归因/未测出。**

---

## 7. 探索性发现(**探索性 —— 需另立预注册、在新数据上过零信号对照**)

1. **11-01 … 11-22 的目标敞口连续 40 天全是 0**(最后一天非 0 是 **2026-10-13**)。
   ⇒ 这段时间 X1V 的目标本来就不在场,"拿不到计划"**没有错过任何一次在场信号**;
   真正丢的是**止损线的刷新**(主机会沿用上一次的 `stop_px`)。
   兜底对止损线有实际影响:11-22 用 CG 序列算的止损线是 56967.7,用兜底序列(含 11-20/21/22 的真实收盘)是 **54235.38**(低 4.8%)——
   因为新加入的三天收盘更低,成了 20 日窗口的新低。
2. **兜底的价值窗口不是"现在",是"下一次目标 > 0 的那天"**。12-01 之前只要 X1V 重新给出敞口,
   关着就漏掉那一次信号;开着则目标与止损线都能按时算出来。这是开关取舍的真正依据(不是"计划显示 ok 与否")。
3. **两源 2026-02-22 同一天同时出大差**(BTC −362 bp、ETH −432 bp),而 BTC/ETH 的方向一致 ⇒
   更像**那一天的取数时点**问题(CG `market_chart` 的 UTC 00:00 快照 vs binance 当日收盘)在高波动日被放大,
   不是某一源的数据错误。**这一条没有单独查证** —— 需要另立预注册去核(单日、多源、跨资产)。

---

## 8. 开关的取舍(给 Seth 的数,不是建议)

- **开**的好处:计划恢复(`ok=True`),目标与止损线按兜底价算;实测 11-20/21/22 三天目标与 CG 序列**逐位相同**(都是 0),
  止损线差 ≤ 15 bp(§2/§3 的量级);主源恢复后自动交回(CG 有 `end` 那天的行 ⇒ 不接管)。
- **开**的代价:兜底价与真 CG 价**不是同一个价**(中位差 ~6 bp、p99 ~50 bp、个别日 ~400 bp),
  止损线因此可能与 12-01 之后 CG 恢复后的口径不同(那几天会有一道"接缝")。
- **关**的代价:计划持续 refused,主机沿用旧 `stop_px`;下一次目标 > 0 的信号会漏掉。
- **默认**:关(卡要求)。本卡不改任何运行时默认值。

**测得的原始数字汇总**:① BTC 中位 6.94 bp / p99 48.98 bp / max 362.37 bp(2026-02-22),同日命中 328/365;
ETH 中位 6.39 bp / p99 58.07 bp / max 431.97 bp,同日命中 339/365。
② 19 天目标权重逐位相同(0 天不同),止损线最大差 14.83 bp(BTC)/ 14.46 bp(ETH)。
③④ 测试 9 个通过;变异测试红的那一条 = `test_mutation_must_break_the_consistency_check`(×1.01 ⇒ gap 0 bp → >50 bp)。
⑤ 清单 19 行有结论 + 10 行未归因/未测出。

---

## 9. 复现

脚本(只读)在 Mac 数据根:`/Volumes/CometCloudAI/cometcloud-local/research/t426_probe.py`
(step:`diff` / `plan` / `inv2` / `inv3` / `live` / `status` / `targets_hist`;产物同目录 `t426_*.json`)。
真库验证:`EXEC_PRICE_FALLBACK` 未设 vs `=1` 各跑一次 `tom_inputs("2026-11-22")` 与 `plan_core("2026-11-22")`。
