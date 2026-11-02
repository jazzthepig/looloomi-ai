# T-217 —— 前向记录连续性账:日期连续是有的,写时连续只有一张表

**一句话:6 张可读的按日前向表,日期层面 0 缺失日;但其中 5 张是整段重算(不是逐日记录),只有 `hl_book_daily` 有逐行写入的时间戳证据。**「自首日起连续、未回填」这个命题今天只有一张表答得上。

只读 SELECT(2026-11-02 实测)。脚本 `docs/research/t217_record_continuity.py` → `docs/research/t217_continuity.json`。
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

**读不到的(两张清单,见 §2)。**

| 类别 | 表 | 状态 |
|---|---|---|
| 按日前向表 · 401 | `forward_anchor_daily` · `portfolio_targets_daily` · `portfolio_layer_daily` · `book_style_exposure_daily` · `meta_allocator_daily` · `execution_quality_daily` · `feature_arms_daily` · `market_interpretation_daily` · `style_pit_coverage_daily` | **401** ×9 |
| 卡上点名的 401 表 | `beta_plus_daily` · `tokenization_tilt_daily` · `allocation_daily` · `allocation_nav_daily` · `live_account_daily` · `rr_matrix_daily` | **401** ×6(逐个实测) |
| 日志 / 心跳 / 执行 | `loop_attempt` · `agent_call_log` · `write_log` · `crowd_clock_log` · `regime_band_log` · `execution_intents` · `execution_outcomes` | HTTP 200 但 **0 行**(`Content-Range: */0`)×7 |

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
它是今天 11:30 一次性把 2026-10-02→11-01 的 31 天全写完的 —— 31 天一天不缺,却**没有一天是当天写的**。

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

---

## 2. 读不到的(需 Seth 用 Supabase MCP 只读补)

**① 9 张 401 的按日前向表**(上面的清单)—— 它们的连续性既不能证明也不能证伪。
**② 卡上点名的 6 张 401 表**(逐个实测确认 401):`beta_plus_daily` / `tokenization_tilt_daily` / `allocation_daily` /
`allocation_nav_daily` / `live_account_daily` / `rr_matrix_daily`。
**③ 7 张日志/心跳/执行表对本 key 是 0 行**:`loop_attempt` · `agent_call_log` · `write_log` · `crowd_clock_log` ·
`regime_band_log` · `execution_intents` · `execution_outcomes`(HTTP 200、`Content-Range: */0`)。
**本 key 分不出「表是空的」还是「这张表另有 RLS 把 publishable 过滤成 0 行」** —— 两种情况在这里读起来一模一样。
⚠️ 这一组和 S-405 实测的「`src/` 里有写入端却一行都没有」(`decisions` / `execution_intents` / `beta_core_nav_size` …)是同一类,
值得一起看:那 82 张表里 **28 张精确 0 行**,现在这张清单里的 `execution_intents` / `execution_outcomes` 就在其中。

---

## 3. ③ executor_host 心跳缺口与 live 余额

卡上给的事实:executor_host 心跳在 **10-26 21:42Z → 10-29 14:24Z** 无行,期间 live 余额 **+17.4**。
**本卡读不到,两条都写「读不到」:**
- 心跳行:`agent_call_log` / `loop_attempt` / `write_log` 对本 key 全部 0 行 ⇒ 无行这件事我无法独立复核
  (不能确认是「本来就没写」还是「写了我看不到」)。
- live 余额:`live_account_daily` **401** ⇒ +17.4 的口径与来源无法核对。

⇒ 这条只能由 @seth 用只读 MCP 补:(a) 上述心跳区间内 `agent_call_log` / `loop_attempt` 是否确实无行;
(b) `live_account_daily` 在该区间的余额与 +17.4 的计算口径。

---

## 4. 近 7 天约 50 次超时类 error 的来源

**读不到。** 承载错误/超时日志的表(`agent_call_log` · `write_log` · `crowd_clock_log` · `regime_band_log` · `loop_attempt`)
对本 key 全部 0 行,公开接口里也没找到等价的只读出口(`/api/v1/trading/loop-state`、`/api/v1/quant/status`
未能在本轮无人值守下取证)。**不推测来源** —— 交给 @seth 代查,清单同上。

---

## 5. 这张表没有回答的

- **「今天」= 2026-11-02 读到的状态。** 任何表在读完之后新增/改写的行不在账内。
- **`computed_at` 是写入端自己写的。** 若写入端在重算时把 `computed_at` 一起刷新,判据本身失效 ——
  判据能证明的是「没有逐行时间戳证据」,不能证明「造假」。这是缺证据,不是指控。
- **41 % 的表在本 key 下不可见**(9 张 401 + 7 张 0 行,外加 6 张点名 401)。
- **未查市场数据表**(`ohlcv_daily` / `asset_mcap_daily` / `social_daily` / `macro_daily` / `protocol_tvl_daily` …):
  它们的连续性是另一条故事(行情源有 feather 归档与回填机制),不在「前向记录」的语义里。
- **`hl_book_daily` 的 40 天起点 2026-09-23 本身是可疑的**(首日 09-23 而非更早),
  但「更早为什么没有」需要写入口径与调度史,本卡读不到。

## 6. 复现

```bash
python3 docs/research/t217_record_continuity.py run   # → docs/research/t217_continuity.json
```

只读 SELECT。`Prefer: count=exact` 取精确行数;翻页全部带 `order=`;401/0 行如实报出,不推测、不用别的表顶替。
