# T-251 —— R-v2 名义合计上限 30% / 40% / 100% 三档回放

> **状态:脚本在跑,结果待收。** 本文件先落方法与口径;三档的对照表由下一轮补齐。
> 卡 `tasks/T-251.json` 里 `notes` 同步写明当前状态。

## 1. 问题

Jazz 11-05:「4. 更灵活,40%?」——R-v2 的名义合计上限现在是 30%
(`src/data/execution/portfolio_targets.py: RV2_GROSS_CAP_FRAC`,上限 0.40,
`R_V2_GROSS_CAP_FRAC` 可覆盖)。40% 相对 30% 多放出来的那点名义,代价没量过。
**本卡只报,不判**:三档(30% / 40% / 100% 参考)各跑一遍,把差别摆出来,拍板是 Jazz 的事。

## 2. 口径(与主机的跳过规则逐条对齐)

票源不是 `r_tickets_paper` —— **那张表现在是 0 行**(实测:`select count(*)` = 0,
与 `migrations/2026-11-05_r_tickets_perp_source.sql` 头注一致:切换源时它就是空的)。
所以票是**回放**出来的:`r_tickets_scan`(11-05 版,读 `perp_bv_daily`)的 plpgsql
逐条翻成 Python(对齐 `docs/research/t156_rv2_replay_twokernels.py: run_v2` 的移植)。

- 宇宙:`perp_bv_pairs` 里 `kind='coin'` 或(`kind is null` 且 `dead_from` 有值)的符号,去掉
  USDC / BTCDOM / DEFI。
- 数据:`perp_bv_daily`(symbol, d, o, h, l, c, qv),全历史;指标窗口与 SQL 一一对应
  (sma20 / sma200 / atr14 / adv30 / adv40p / hh40 / ll40 / mindd120 / dd)。
- 闸门:`style_index_pit_daily` 的 `style='majors' AND weighting='cap'` ——
  level = Π(1+ret),`gate = level > 200 日均线`;n<200 时开着。
- 信号:`rn>=220 and adv30>=5e6 and mindd120<=0.5 and (hh40-ll40)/hh40<=0.40
  and c>hh40 and c>sma200 and dv>=2*adv40p`。
- 出场:止损 > 收盘破 SMA20(挂标记、次日开盘出)> 120 根到期(收盘价)> 停更 10 天(最后收盘)。

主机侧(`src/exec_host/tickets.py: ticket_actions`)逐条落:

| 规则 | 回放里的实现 |
|---|---|
| 名义 = 净值 × risk_frac ÷ stop_frac | `risk_frac = 0.5%`;`stop_frac = 2.5×ATR(信号日) ÷ 收盘(信号日)`(= 主机计划里的算法) |
| 单票名义 ≤ 净值 50% | `min(target, alloc×0.5)` |
| 名义 < HL 最小名义额 $10 ⇒ 不可执行 | `qty` 取整后 `qty×mid < 10` ⇒ 不做 |
| 主机已满 10 张 ⇒ 不可执行 | `len(book) >= 10` ⇒ 不做 |
| 同一个币已有一张票的仓位 ⇒ 不可执行 | `symbol in held` ⇒ 不做 |
| 名义合计 > 净值 × gross_cap ⇒ 这张票不做、**不找替补** | 跳过该票,继续看下一张 |

逐日顺序:先按开盘平掉当日的止损 / 破 SMA20 出场 → 再按 (信号日, 名字) 顺序处理当日进场
→ 收盘平掉当日到期 / 停更的票 → 按收盘价给净值。**复利**;起始净值取今天账户的
**$630**(这样 $10 最小名义规则全程真实生效)。

## 3. 三档对照表(待收)

| 指标 | 30% | 40% | 100%(参考) |
|---|---|---|---|
| 总收益 | 待收 | 待收 | 待收 |
| CAGR | 待收 | 待收 | 待收 |
| 最大回撤 | 待收 | 待收 | 待收 |
| Calmar | 待收 | 待收 | 待收 |
| 最差月 | 待收 | 待收 | 待收 |
| 做了几张票 | 待收 | 待收 | 待收 |
| **被上限挡掉的票数** | 待收 | 待收 | 待收 |
| **被挡掉的票的 R 合计** | 待收 | 待收 | 待收 |
| 名义合计 中位 / p95 / 最大 | 待收 | 待收 | 待收 |

## 4. 30% → 40% 的边际(待收)

多做了哪些票、它们的 R 分布,并按 majors 指数在 200 日线**上 / 下**分开报
(闸门是在信号日判的,进场日可能已经翻,所以按进场日分档)。

## 5. 真钱尺度(待收)

按今天净值 ≈ $630 算每张票的名义(止损越宽名义越小),低于 HL 最小名义额 $10 的比例,
在 30% / 40% 两档各多少。

## 6. 声明的近似(读结果前先看这里)

1. **HL 永续列表没进回放**:`ticket_actions` 里「HL 上没有这个永续 ⇒ 不可执行」这条
   需要 HL 的历史列表,离线没有(库里的 HL 名单来自实时 API)。这条规则在三档里**同样**
   不适用,所以三档的**比较**不受影响;绝对数字里含了主机当时不会开的票。
2. **szDecimals 用价格档近似**(BTC 5 位 → 小币 0 位),取整损耗 ≈ 1%,没有 HL 的真实
   每币小数位快照。
3. **P&L 走纸面账本的止损与出场价**(进场价 − 2.5×ATR),**名义**按主机的计划算法
   (2.5×ATR ÷ 信号日收盘)算;两者差的是「信号日收盘 → 次日开盘」的隔夜跳空。
4. **没有 OOS 切分**:本卡是口径内的三档对照,不是新因子的三检。
5. `r_tickets_paper` 仍是空的 —— 回放出来的票**没有入账**,主机读不到。

## 7. 产物

- 脚本:`docs/research/t251_gross_cap.py`
- 结果:`docs/research/t251_results.json`
- 运行日志:`docs/research/t251_run.log`
- 取数缓存(Mac 数据根,不是 /tmp):`/Volumes/CometCloudAI/cometcloud-local/research/t251_cache/`
- 情景文件:`docs/research/scenarios/lane-b-T-251.json`
