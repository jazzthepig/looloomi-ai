# T-217 · 前向记录连续性账 + 近 7 天超时类 error 的来源(只读)

**lane-a · 2026-11-01 · 只读**:全部是 SELECT 与公开端点;没有改代码、没有写库、没有 DDL、没有碰密钥。
**产物**:本文件 + `t217_*.py`(探针,全部可复跑)+ `t217_*.json`(原始读数)+ `continuity.json` / `continuity_table.md` / `continuity_summary.json`。

> 两次自动轮次(11-01 11:11Z / 11:31Z)都因「Prompt is too long」零交付,产物散在 `/tmp`。
> 本轮用 `t217_relocate.py` 把脚本的输出路径搬回 `docs/research/`(规则 3a),并**用原始数据重核了一遍**——
> 核出一个**我自己脚本的真 bug**(见 §4),已修。

---

## 0. 一句话结论

**「记录没断」是真的,但「记录能证明它是当天写的」不成立**:
`core_cap_daily` 全表 110 行**共用同一个 `computed_at`(2026-11-01T11:29:00.217568Z)**,
28/30 行比自己的 `d` 晚 2 天以上 —— 这是**整段重算回写**,不是逐日写入。
⇒ 这批表**不能**被外部第三方当作「自首日起连续、未回填」的证据;
真正逐日写的那几张(`cis_tilt_daily.cis_a1_u`、`multiplier_daily`、`r_money_daily`、`risk_meter_history`、`hl_book_daily`)才是。
超时的来源在**同一句错误串**上(`no response from Supabase`),但**按时间点对齐那一档做不了**(见 §3 的阻塞)。

---

## 1. ① 连续性账(逐臂)

卡面点名 10 张表,publishable key 实测:

| 表 | 可读 | 证据可用性 |
|---|---|---|
| `core_cap_daily` | ✅ 直读 | **否 —— 整段回写**(§2) |
| `cis_tilt_daily` | ✅ 直读 | 部分:逐日臂 ✅ / 回放臂 ❌ / 混合臂未定 |
| `hl_book_daily` | ✅ 直读 | 是(逐日 ts 连续),但每臂只有 6~7 行 |
| `depth_divergence_log` | ✅ 直读 | 是 |
| `beta_plus_daily` | ❌ 42501 | 不可算 |
| `tokenization_tilt_daily` | ❌ 42501 | 不可算 |
| `allocation_daily` | ❌ 42501 | 不可算 |
| `allocation_nav_daily` | ❌ 42501 | 不可算 |
| `live_account_daily` | ❌ 42501 | 不可算 |
| `rr_matrix_daily` | ❌ 42501 | 不可算 |

**10 张卡面表里 6 张用 publishable key 读不到(42501 permission denied)** —— 这是本轮最大的阻塞,
与 lane-c §C-auto-1101-1209 请 @seth「给 lane 一条读那 6 张表的通道」是同一件事,这次拿到了确证。

另外发现并读到的前向表(不在卡面点名里):
`core_variants_daily`、`multiplier_daily`、`r_money_daily`、`short_paper_money`、
`beta_core_nav`、`risk_meter_history`、`cis_official_daily`、`signal_journal`。
其中 `core_variants_daily` / `multiplier_daily` / `portfolio_layer_daily` / `feature_arms_daily` /
`meta_allocator_daily` 只有**臂级计数**(series 端点),**逐日明细不可读 ⇒ 缺失/缺口算不出来**。

---

## 2. 核心发现:`core_cap_daily` 是整段回写,不是逐日写入

直接查库(不是从文件继承的结论):

```
core_cap_daily 共 110 行(4 臂:cap_a05 / cap_a1 / cap_a1_u / ew_a0)
全表 distinct computed_at = 1
  = 2026-11-01T11:29:00.217568+00:00
每臂: d = 2026-10-02 .. 2026-10-31,distinct_ts = 1,每 ts 30 行
late_gt_2d(= computed_at 的日期 > d + 2 天):28/30(cap_a05、cap_a1、ew_a0),18/20(cap_a1_u)
```

⇒ **同一时刻把 30 天的历史一次性 upsert 了**,其中 28 行的落库时间比它们自己的日期晚 2 天以上。
第三方拿到这批行**无法区分**「当天写的」与「事后整体回填」——
所以它**不能**作为「自首日起连续、未回填」的证据(这正是卡面问的那一句,答案是「不能」)。
内容本身可能仍然正确(每天重算最近 30 天是常见做法),但**时间戳不再承担举证责任**。

**逐日写入确实存在的那几张**(原始行算出来的 `distinct_ts`):

| 表 · 臂 | 行数 | 不同 computed_at | 每个 ts 行数 | 判定 |
|---|---|---|---|---|
| `cis_tilt_daily.cis_a1_u` | 20 | **20** | 1 | 逐日写 ✅ |
| `multiplier_daily.mult_v2` | 19 | **19** | 1 | 逐日写 ✅ |
| `r_money_daily` | 13 | **13** | 1 | 逐日写 ✅(`d` 10-19..10-31,落库在次日 00:45~05:27 UTC) |
| `risk_meter_history` | 51 | **51** | 1 | 逐日写 ✅ |
| `hl_book_daily`(全表) | 39 | **39** | 1 | 逐日写 ✅(但按臂拆开后每臂 6~7 行) |
| `cis_tilt_daily.*_replay` | 1399 | 1380~1387 | 20 | **回放臂,不是前向记录**,必须分开报 |
| `beta_core_nav` | 74 | 74 | 1 | ⚠️ `distinct_d = 1`(日期列全 null)⇒ **日期轴不可用,做不了连续性账** |
| `signal_journal`(按臂) | 每臂 5~8 | 1 | 8 | ⚠️ 同一 ts 多行 ⇒ 批量写,不能逐日举证 |

---

## 3. ② 近 7 天超时类 error 的来源

**能读到的部分**:

| 口径 | 数字 |
|---|---|
| loops(59) | failing **2** / refusing **8** / never_ran **0** |
| liveness(53) | live **50** / dead **3** / frozen **6** / stale 0 |
| dead_loops | `_forward_record_loop`、`_hl_book_loop`、`_perp_mcap_backfill_loop` |

**两个 failing 的错误串是同一句** ⇒ 同一来源:
- `_forward_record_loop`:`refresh: no response from Supabase after retries` + `refresh returned NoneType`
- `_signal_attribution_loop`:`live_mixed 写入失败:no response from Supabase`

⇒ **「拿不到 Supabase 响应」是一条共同根因**,不是各自独立的问题。

**refusing 里有两个 why 为空**:`_hl_book_loop`(2 次)、`_perp_mcap_backfill_loop`(9 次)——
它们与 liveness 的 dead_loops **完全重合**,但**没有给出原因**。
另外 6 个 refusing 是 Jazz 10-20 的**有意冻结**(不是故障)。

**一条可能同源的线索**(探索性):`binance_um_hist` 数据源已 **DEAD 85 天**(最后一根 bar 2026-08-08,
最近 3 天 0 个标的写入);`hyperliquid` DEAD 70 天、`coingecko` DEAD 45 天、`yfinance` DEAD 23 天。
`_perp_mcap_backfill_loop` 正需要 perp 的 mcap 输入 —— **输入源已死 85 天** 与「no response」很可能是同一片区域,
但**我没有证据把两者连起来**,只作为假设登记。

**做不了的那一档(阻塞)**:卡面要求「把近 7 天 loop_attempt 里的 ~50 次超时按时间点对齐成一张表」。
本轮 `/internal/loop-attempts` 端点返回 **"Not found"** ⇒ **按时间点对齐这一档没有做**,
需要 @seth 给出 loop_attempt 的真实位置(表名或端点路径)。

---

## 4. 我自己脚本里的一个真 bug(已修)

`t217_lag_anatomy.py` 原来写 `nts = len(lag)`(`lag` 是**滞后值的直方图**)当「不同 computed_at 的个数」,
又用 `max(lag.values())` 当「同一 ts 下的最大行数」。

后果:`core_cap_daily.cap_a05` 被报成「ts 数 30 / max同ts 1 / MIXED」,
而**真实值是 ts 数 1 / 每 ts 30 行 / BULK_BACKFILL** —— 判定整整错了一档,
而且恰好错在最要紧的那张表上(它被当成 MIXED,而不是「整段回写」)。

已改成从 `t217_ts_sequence.py` 的**原始行计数**取 `distinct_ts` / `max_rows_per_ts`;
取不到时标 `-1` 并**不猜**(不拿直方图冒充 ts 数)。
重跑后 `core_cap_daily.cap_a05` = `ts数 1 / max同ts 30 / BULK_BACKFILL`,与直接查库一致。

> 教训(自查用):**同一个量用两个名字存两遍,其中一个是推导出来的,迟早对不上**。
> 本轮是对不上之后才查了库 —— 顺序应该是:先查库,再让两个产物对齐。

---

## 5. 需要 @seth 回答 / 给的

1. **读表通道**:卡面 10 张表里 6 张用 publishable key 读不到(`beta_plus_daily`、`tokenization_tilt_daily`、
   `allocation_daily`、`allocation_nav_daily`、`live_account_daily`、`rr_matrix_daily`,全部 42501)。
   要一条能读它们的通道(RLS 白名单或服务端端点),否则这 6 张表的连续性**无法裁决**。
2. **`loop_attempt` 的位置**:端点返回 "Not found";给我表名或端点,我把「近 7 天 ~50 次超时按时间点对齐」
   这一档补上(卡面 ② 的核心)。
3. **`_hl_book_loop`(2 次)与 `_perp_mcap_backfill_loop`(9 次)为什么 refusing 但 why 为空** ——
   这是「监视器沉默」里唯一还藏着的那部分。
4. **`core_cap_daily` 的整段回写是设计还是副作用**:如果是「每天重算最近 30 天并 upsert」,
   那时间戳就不能再用于举证,建议给前向表加一个**不可变的写入时间**(append-only 的 `written_at`,
   不随 upsert 覆盖);如果它本该逐日写,那就是写入端的问题。

---

## 6. 探索性 —— 需另立预注册、在新数据上过零信号对照

1. **`beta_core_nav` 的日期列全 null**(74 行、`distinct_d = 1`)⇒ 这张表**在连续性账上是瞎的**;
   值得单独查一次它的时间轴到底存在哪一列。
2. **`cis_tilt_daily` 的回放臂(`*_replay`,各 1399 行)与真前向臂混在同一张表里** ——
   如果第三方要拿这张表当证据,同表混臂本身就是缺口;建议加一列区分或分表。
3. **三个数据源连续死了 23~85 天**(binance_um_hist / hyperliquid / coingecko / yfinance),
   而 `eodhd`、`coingecko_pro_ohlc`、`binance_hist` 仍 flowing —— 这个「一半死一半活」的分界
   值得查一次是不是采集器编排的问题(而不是逐源偶发)。
