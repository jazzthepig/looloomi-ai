# T-217 —— 前向记录连续性账:日期连续是有的,写时连续只有一张表

**一句话:6 张可读的按日前向表,日期层面 0 缺失日;但其中 5 张是整段重算(不是逐日记录),只有 `hl_book_daily` 有逐行写入的时间戳证据。**
**第二句(11-03 补):写这些表的循环本身从 10-30 起开始大面积失败 —— `_forward_record_loop` 在 11-01、11-02 两天「零次成功」。日期不缺,是因为别的路径整段重算补上了。**

只读 SELECT(2026-11-03 实测,含 11-02 §Seth-1102g 授权后的复查)。脚本 `docs/research/t217_record_continuity.py` → `docs/research/t217_continuity.json`。
未改代码、未动密钥、未入库、未 DDL;翻页全部带 `order=`。

---

## 0. 连续性总表

**可读的按日前向表(6 张)。**「应有天数」= 末日 − 首日 + 1;「缺失」= 应有 − 实有;「晚于 d+2」= `computed_at` 的日期比该行 `d` 晚 2 天以上的行数。

| 表 | 首日 | 末日 | 应有天数 | 实有天数 | **缺失天数** | **最长连续缺口** | 行数 | 行/天 | 写入口径判定 |
|---|---|---|---|---|---|---|---|---|---|
| `core_cap_daily` | 2026-10-02 | 2026-11-01 | 31 | 31 | **0** | 无 | 114 | 3–4 | **整段重算** |
| `cis_tilt_daily` | 2023-01-02 | 2026-11-01 | 1400 | 1400 | **0** | 无 | 2855 | 2–5 | **整段重算** |
| `hl_book_daily` | 2026-09-23 | 2026-11-01 | 40 | 40 | **0** | 无 | 40 | 1 | **逐行 upsert** ✅ |
| `multiplier_daily` | 2023-01-02 | 2026-11-01 | 1400 | 1400 | **0** | 无 | 10060 | 7–16 | **整段重算** |
| `style_index_pit_daily` | 2020-01-01 | 2026-11-01 | 2497 | 2497 | **0** | 无 | 38922 | 12–16 | **整段重算** |
| `core_variants_daily` | 2019-01-01 | 2026-11-01 | 2862 | 2862 | **0** | 无 | 18262 | 1–12 | **整段重算** |

**日志 / 心跳 / 执行表(11-02 开权限后重新分类)。**

| 表 | 本 key 实测 | 精确行数 | 判定 |
|---|---|---|---|
| `loop_attempt` | 可读 | **34,475** | 11-02 §Seth-1102g 开的 |
| `regime_band_log` | 可读 | **906** | 同上 |
| `crowd_clock_log` | 可读 | **41** | 同上 |
| `agent_call_log` | 可读 | **0** | 真 0 行(§Seth-1102g (b) 同结论) |
| `write_log` | 可读 | 0(本 key) | RLS 过滤 —— 服务端读 579,623 |
| `execution_intents` | 可读 | 0(本 key) | RLS 过滤 —— 服务端读 4 |
| `execution_outcomes` | 可读 | 0(本 key) | RLS 过滤 —— 服务端读 2 |

**读不到的(见 §2)。**

| 类别 | 表 | 状态 |
|---|---|---|
| 按日前向表 · 401 | `forward_anchor_daily` · `portfolio_targets_daily` · `portfolio_layer_daily` · `book_style_exposure_daily` · `meta_allocator_daily` · `execution_quality_daily` · `feature_arms_daily` · `market_interpretation_daily` · `style_pit_coverage_daily` | **401** ×9 |
| 卡上点名的 401 表 | `beta_plus_daily` · `tokenization_tilt_daily` · `allocation_daily` · `allocation_nav_daily` · `live_account_daily` · `rr_matrix_daily` | **401** ×6(逐个实测) |

---

## 1. 日期连续 ≠ 写时连续 —— 这张表真正的答案

日期层面完美:6 张表**一天不缺**,最长连续缺口 = 无,覆盖 100.00 %。

但日期齐 ≠ 记录是当天写的。卡上要求先判写入口径,判据是 `computed_at`(相对 `d`)和 `correction` 列:

| 表 | `computed_at` 唯一值数 | 落在几个 UTC 日 | **晚于 d+2 的行** | `correction` 非空 | 判定 |
|---|---|---|---|---|---|
| `core_cap_daily` | 1 | **1** | 106 / 114(92.9 %) | — | 整段重算 |
| `cis_tilt_daily` | 87 | 21 | 2768 / 2855(**96.9 %**) | — | 整段重算 |
| `hl_book_daily` | 40 | **35** | **2 / 40(5 %)** | **11** | **逐行 upsert** ✅ |
| `multiplier_daily` | 83 | 21 | 9811 / 10060(**97.5 %**) | — | 整段重算 |
| `style_index_pit_daily` | 54 | 26 | 38490 / 38922(**98.8 %**) | — | 整段重算 |
| `core_variants_daily` | 25 | 21 | 18017 / 18262(**98.7 %**) | — | 整段重算 |

**`core_cap_daily` 是最干净的例子:114 行的 `computed_at` 全是同一个时刻 `2026-11-02T11:30:57`。**
它是 11-30 一次性把 2026-10-02→11-01 的 31 天全写完的 —— 31 天一天不缺,却**没有一天是当天写的**。

`cis_tilt_daily` / `multiplier_daily` / `core_variants_daily` 覆盖 2023–2026,`style_index_pit_daily` 覆盖 2020–2026,
它们的写入集中在 **21–26 个 UTC 日**里,97–99 % 的行比自己的 `d` 晚两天以上
(最早的 2020-01-01 那批 `computed_at` 是 2026-10-08)。⇒ **整段重算,无逐行时间戳证据**(卡上纪律:不判为回填,只报整段重算)。

`hl_book_daily` 是唯一逐行 upsert 的:40 行、每天 1 行、40 个不同的 `computed_at` 跨 35 个 UTC 日,
只有 2 行晚于 d+2(2026-09-26 的行 09-29 写、2026-09-29 的行 10-02 写)。
⇒ **它可以是第三方证据**。但要说清两点:① 其中 **11 / 40 行的 `correction` 非空** ⇒ 这张表 27.5 % 的日子是后来改过的,
第三方看到的是修订后的版本;② 它的连续性只覆盖 2026-09-23 起的 40 天,不是「自首日起」—— 首日之前有没有,表里没有证据。

**能不能被外部第三方当作「自首日起连续、未回填」的证据:**
- `hl_book_daily` —— **可以,但只有 40 天**,且要同时披露 11 行修订。
- 另外 5 张 —— **不可以**。日期齐是重算的结果,时间戳证明不了「当时就写了」。

⚠️ §3.5 给出了「为什么日期齐不能当证据」的机械版本:写这些表的循环本身在失败,是别的路径整段重算补的。

---

## 2. 读不到的(需 Seth 用 Supabase MCP 只读补)

**① 9 张 401 的按日前向表**(上面的清单)—— 它们的连续性既不能证明也不能证伪。
**② 卡上点名的 6 张 401 表**(逐个实测确认 401):`beta_plus_daily` / `tokenization_tilt_daily` / `allocation_daily` /
`allocation_nav_daily` / `live_account_daily` / `rr_matrix_daily`。
**③ 4 张日志表本 key 读不到行**(`write_log` / `execution_intents` / `execution_outcomes` / `agent_call_log`):
前 3 张是 RLS 过滤(服务端读得到行),`agent_call_log` 是真 0 行。
**§Seth-1102g (a)**:9 + 6 张 401 表的连续性由 Seth 在 11-09 的 7 天容量报告里一起量,本卡不单开。

---

## 3. §Seth-1102g 的 (b)–(e) 代查结果 —— 全部自核(不采信转述)

### 3.1 (b) 7 张「0 行」表:是 RLS,不是空

本 key 实测(HTTP 200 + `Prefer: count=exact` 精确行数):

| 表 | 11-03 本 key | §Seth-1102g (服务端 key, 11-02 13:52) | 差 |
|---|---|---|---|
| `loop_attempt` | 34,475 | 34,143 | +332(表是活的,这三轮之间又写进去的) |
| `regime_band_log` | 906 | 901 | +5(同上) |
| `crowd_clock_log` | 41 | 41 | 0 ✅ |
| `agent_call_log` | 0 | 0(真 0) | 0 ✅ |
| `write_log` | 0(RLS) | 579,623 | RLS 过滤 |
| `execution_intents` | 0(RLS) | 4 | RLS 过滤 |
| `execution_outcomes` | 0(RLS) | 2 | RLS 过滤 |

⇒ §Seth-1102g (b) 的结论**自核一致**:7 张表里 3 张现在对本 lane 可读,只有 `agent_call_log` 真的 0 行。
**这条要留在台账里:「200 但 0 行」= RLS 把行过滤成了 0 行,不是「表空」。** 11-02 那版报告把这一组整体写成
「HTTP 200 但 0 行 ⇒ 7 张日志表对本 key 全部 0 行」,并据此推出 S-405 那一类问题 —— 那个推论对 `agent_call_log` 成立,
对其余 6 张不成立。

### 3.2 (c) executor_host 心跳缺口 —— 自核:确实断了,而且是唯一的一次断

自核方法(不采信任何人的转述):把 `loop_attempt` 里 `loop_name='executor_host'` 在 2026-10-25→10-31 的**全序列**按时间排序,
量相邻两行之间的**最大缺口** —— 这比「区间里有没有行」更硬,它直接给出「主机不在」的那一段及其两侧活着的心跳行。

| 量 | 实测 |
|---|---|
| 窗口内 `executor_host` 行数 | 102 |
| 声明区间内部(不含两端端点)行数 | **0** |
| 断口前一行 | `2026-10-26T21:42:49.129096Z`(outcome=ok) |
| 断口后一行 | `2026-10-29T14:24:06.073895Z`(outcome=ok) |
| 缺口长度 | **64.69 h** |
| 全序列最大缺口 | **64.69 h**,两端正是上面那两行(`max_gap_is_the_claimed_window = true`) |
| 窗口内 > 6 h 的缺口数 | **1**(没有第二次断) |

⇒ **§Seth-1102g (c) 自核通过:10-26 21:42Z → 10-29 14:24Z 确实无行,64.7 小时,主机那段时间不在。**
这是「唯一一次断」—— 同一窗口(10-25→10-31)内没有第二次同量级中断。

### 3.3 (d) live 余额 +17.4 的出处 —— 找到了,在 `loop_attempt` 的心跳 detail 里

`executor_host` 心跳行的 `detail.balances.USDC` 带 live 余额(**302 行**带这个字段)。断口两侧各取最后一个有心跳余额的行:

| | 时刻(UTC) | USDC | mode | kind |
|---|---|---|---|---|
| 断线前 | `2026-10-26T20:42:38.550828Z` | **613.253615** | live | heartbeat |
| 断线后 | `2026-10-29T14:51:55.927834Z` | **630.643136** | live | heartbeat |
| **净值差** | | **+17.3895** | | |

⇒ **+17.4 的出处 = `loop_attempt` 心跳的 `detail.balances.USDC`:613.253615 → 630.643136,Δ=+17.3895。**
(Seth 11-02 的 `live_account_daily` 10-29 equity 630.64 与我这边断线后的心跳值 630.643136 **同一个数** ——
`live_account_daily` 的首行就是跳变**之后**的值,所以那张表里本来就不会有这一跳。口径对上了。)

⚠️ **但两处余额口径从 10-30 起分叉了(新发现,见 §4.2):**
心跳余额在 `2026-10-30T15:45:09Z` 变成 **338.105236**(`mode` 仍是 `live`,`kind` 仍是 `heartbeat`),
而 Seth 读的 `live_account_daily` 是 10-30 = 629.49、10-31 = 629.52 ⇒ **两个「live 权益」数从 10-30 起差 ≈ 291.4**。
本 key 读不到 `live_account_daily`(401),所以这一条**只报现象、不判对错**。

### 3.4 (e) 近 7 天超时类 error 的来源 —— 「约 50」不是幻觉,是宽口径;严格口径是 4 条

窗口:`at ≥ 2026-10-26T00:00:00Z` → 运行时刻(11-03)。该窗口内 `loop_attempt` 共 **13,312 行**,
`outcome` 分布:`ok 11,273` / `refused 1,894` / `error 143` / `panel_unavailable 2`。
(10-26 当天对下面三个计数贡献为 0,所以「近 7 天」与「近 8 天」口径在这三个数上没有差别。)

**宽口径(命中 `timeout` / `timed out` / `no response from supabase`)= 49 条 ≈ 卡上那个「约 50」。**
按来源拆开,49 = 42 + 4 + 1 + 2:

| 来源 | 条数 | 明细 |
|---|---|---|
| **写端连不上库**(「no response from Supabase after retries」) | **42** | `_forward_record_loop` 40 + `_signal_attribution_loop` 2;按日 10-30:10 / 10-31:7 / 11-01:11 / 11-02:14 |
| **循环级网络超时**(超时标记出现在 `reason` 字段) | **4** | `_tokenization_tilt_loop` ConnectTimeout ×2(`10-27T15:06:28Z`、`10-30T16:32:42Z`);`_public_cache_warm_loop` ReadTimeout ×2(`10-30T19:12:38Z` `/api/v1/protocols/universe`、`10-31T16:04:33Z` `/api/v1/cis/attribution?symbol=BTC&limit=8`) |
| **子请求超时**(标记只在嵌套 `detail` 里,循环自身不是网络挂死) | **1** | `_cis_inputs_loop` `10-29T14:31:36Z`:循环 `reason` = 「1 项失败:['tvl.AAVE']」,`detail.protocols.AAVE.error` = `ReadTimeout:` |
| **面板不可用**(重试耗尽,非本循环超时) | **2** | `_cg_panel_loop` `10-29T14:27:13Z`(137.7 s)、`11-02T08:14:32Z`(37.4 s) |

⇒ **§Seth-1102g (e) 的「只有 4 条」自核通过 —— 但口径要说清:**
**严格(循环级网络超时)= 4 条**,与 Seth 的数一致;**宽口径(含写端连不上库)= 49 条**,也就是当初「约 50」的来源。
两个数都对,差的是定义:「约 50」不是凭空推的,它是**写端连不上库**那 42 条的主体。
两处与 Seth 的日期差异:`_public_cache_warm_loop` 的两条分属 **10-30 与 10-31**(不是都在 10-31),
`_tokenization_tilt_loop` 的两条分属 **10-27 与 10-30**(不是都在 10-30)—— 计数相同,归日不同。

### 3.5 ⚠️ 那 42 条写端失败的含义:写前向记录的那个循环自己在熄火

`_forward_record_loop`(写前向记录的那个循环)按日成败:

| 日期 | ok | error |
|---|---|---|
| 10-26 | 10 | 0 |
| 10-27 | 7 | 0 |
| 10-28 | 5 | 0 |
| 10-29 | 13 | 1 |
| 10-30 | 4 | 11 |
| 10-31 | 1 | 7 |
| **11-01** | **0** | **10** |
| **11-02** | **0** | **13** |

失败原因(逐字):`stalled=[] problems=['refresh: no response from Supabase after retries', 'refresh returned NoneType None, not an int — the SQL contract says this is a row count or a negative refusal code. Unrecognised is NOT success.']`
(部分行带 `stalled=['depth-divergence forward record']`)。

⇒ **11-01、11-02 两天,写前向记录的循环一次都没成功过。** 而 §0 的 6 张按日前向表到 11-01 **仍然一天不缺** ——
差的那两天(11-02、11-03)由整段重算路径补上,补的时候 `computed_at` 全写成同一时刻。
**这是「日期齐 ≠ 记录连续」的机械证明:齐是天数算出来的,不是写出来的。**
也解释了为什么 §1 里 `core_cap_daily` 114 行的 `computed_at` 会是同一个 `2026-11-02T11:30:57` ——
那正是重算路径在 11-02 补的。

---

## 4. 这张表没有回答的

### 4.1 已知边界

- **「今天」= 2026-11-03 读到的状态。** 任何表在读完之后新增/改写的行不在账内
  (同一轮的三次跑之间 `loop_attempt` 就从 34,424 长到 34,475,窗口内行数 13,253 → 13,312;
  超时类的三个计数 49 / 5 / 42 三次跑完全一致 —— 增量落在别的 outcome 上)。
- **`computed_at` 是写入端自己写的。** 若写入端在重算时把 `computed_at` 一起刷新,判据本身失效 ——
  判据能证明的是「没有逐行时间戳证据」,不能证明「造假」。这是缺证据,不是指控。
- **41 % 的表在本 key 下不可见**(9 张 401 + 6 张点名 401 + 4 张日志表 0 行)。
- **未查市场数据表**(`ohlcv_daily` / `asset_mcap_daily` / `social_daily` / `macro_daily` / `protocol_tvl_daily` …):
  它们的连续性是另一条故事(行情源有 feather 归档与回填机制),不在「前向记录」的语义里。
- **`hl_book_daily` 的 40 天起点 2026-09-23 本身是可疑的**(首日 09-23 而非更早),
  但「更早为什么没有」需要写入口径与调度史,本卡读不到。

### 4.2 两个新发现(本轮才看见,卡上没问)

1. **两个「live 权益」口径从 10-30 起分叉**:心跳 `balances.USDC` = 338.105236(10-30 15:45 起,`mode=live`),
   `live_account_daily` = 629.49(10-30)/ 629.52(10-31) ⇒ 差 ≈ 291.4。本 key 读不到 `live_account_daily`(401),**未判对错**。
2. **`_forward_record_loop` 在 11-01/11-02 零成功**(§3.5)。这是本卡最重的一条:
   「记录连续」的写端已经熄了两天,而表面上的一天不缺是重算给的。

## 5. 复现

```bash
python3 docs/research/t217_record_continuity.py run   # → docs/research/t217_continuity.json
```

只读 SELECT。`Prefer: count=exact` 取精确行数;翻页全部带 `order=`;401/0 行如实报出,不推测、不用别的表顶替。
脚本按 §Seth-1102g 的授权范围读 `loop_attempt` / `regime_band_log` / `crowd_clock_log`;
`write_log` / `execution_*` / `agent_call_log` 仍是 0 行,按 RLS 如实报出。
