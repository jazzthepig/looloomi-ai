# T-217 —— 前向记录连续性账 + 超时来源对时间点(只读)

**读取时间**:2026-11-01T13:07Z ~ 13:26Z(UTC);**复核轮**:2026-11-01T13:22Z 起重跑主脚本 + 分类脚本,数字以复核轮为准
**再复核轮**:2026-11-01T13:53Z 第四次重跑主脚本 + 分类脚本 + 臂数核对 —— **所有结构性数字(首末日 / 缺失 / 最长缺口 / 臂数 46·102·111·168 / 表行数 1275·349·74·51)逐位复现**;唯一漂移是 24h 活体计数:三次重跑 **240 → 242 → 243**(窗口滚动,全部落在 `_perp_mcap_backfill_loop` 这个良性桶),§3 与 §7 的数字以最后一次(13:53Z)为准。**「24h 失败计数」本身在 30 分钟内就漂了 3 次 —— 这正是「近 7 天 ≈50 次」那个历史数字钉不死的直接证据。**
**通道**:① Supabase 直读 `/rest/v1/<表>`(publishable key,只读 SELECT,全部带 `order=` 翻页)—— 直读 11 张按日/事件表
② 公开接口 `/api/v1/portfolio/series?table=`、`/api/v1/proof/anchors`、`/api/v1/proof/books`
③ 只读数据库函数 `rpc/loop_attempt_health`、`rpc/write_health`
**没有**:改代码、改数据、DDL、读 `.env`、打印任何 key;未查卡面列明的 6 张 401 表的内容(只探了读权限状态)。
**本轮改动**:初稿只查了 7 张直读表;复核轮把**可读的按日表扫全**(补上 `cis_official_daily` / `risk_meter_history` / `beta_core_nav` / `signal_journal`),并修掉初稿的两处口径错(见 §2.5 与 §3.2 的「修正」框)。

---

## 0. 三句话结论

1. **日期轴:除 2 张表外全部零缺失;全量扫一遍有 1 处静默断档 + 1 处有据作废 + 1 张不是按日表。** 直读 8 张按日表(core_cap / cis_tilt / hl_book / core_variants / multiplier / r_money / short_paper / cis_official_daily)+ 公开接口 46 个臂(其中 37 个臂两边都可见、9 个臂只有接口可见),逐臂「行数 = 首末日跨度 + 1」全部成立,缺失 0、最长连续缺口 0;把可读的按日表**扫全**后出现三件事:①**`risk_meter_history` 中段 10-14→10-28 有 15 天空洞**(全表 18 天缺失)—— 这是本卡唯一的**静默断档**,且写端 `write_health` 无失败记录、看不出成因;②`beta_core_nav` 缺 13 天,但另有 **17 行带 `void_reason` 显式作废**(S-123/S-147/S-194/S-283)—— 缺口**有据可查**、不是静默;③`signal_journal` **不是按日表**(每行是一次信号事件,每符号 1~13 条),按日历天读它会算出 4598 天「缺失」的假象 —— 已从按日表集合里剔除。
2. **但「连续」不等于「未回填」,两者在这批表上被写入口径分开。** core_cap_daily 是**整段重算**(每臂 `computed_at` 只有一个时刻,最晚 d+30 天);cis_tilt_daily 与 core_variants/multiplier 的 `*_replay` 臂带着 2023→ 的历史行(晚于 d+2 的行 1378~1385 行);**逐行写且干净的表有两张** —— `r_money_daily`(13 行、13 个不同时刻、最大滞后 1 天)与 **`cis_official_daily`(59 个符号 × 22 天、每臂 22 个不同 `published_at`、最大滞后 1 天、0 晚写、0 correction)**,后者覆盖面远大于前者;**hl_book_daily 实测有 2 行写于 d+3、11 行带 S-490 correction**,这张表按卡面自己的判据就**不能**当作「未回填」的证据。
3. **超时与心跳:lane 侧读不到「≈50 次超时」这件事本身。** `loop_attempt` 直读返回 200 但 0 行(RLS 未给 anon policy)⇒ 逐条事件读不到;可读的 24h 聚合里失败 243 次,**其中 0 次原因含 timeout 类字样,88 次原因字符串为空**(最大两个源:`_executor_dry_run_loop` 73、`_forward_return_backfill_loop` 14);public schema 里**没有 `executor_host` 表**(PGRST205),`live_account_daily` 401 ⇒ 10-26 21:42Z→10-29 14:24Z 的心跳缺口与 live 余额 +17.4 在 lane 通道里都读不到。

---

## 1. 连续性总表

「首日 / 末日」= 该表所有臂的最早 / 最晚行日期;「缺失 / 最长缺口」= 逐臂核对后的合计(**除 `risk_meter_history` 与 `beta_core_nav` 外均为 0**)。

| 表 | 读法 | 首日 | 末日 | 臂 | 应有天数(首末跨度) | 缺失天数 | 最长连续缺口 | 写入口径(实测) | 第三方可当「自首日起连续未回填」的证据? |
|---|---|---|---|---|---|---|---|---|---|
| `core_cap_daily` | 直读 | 2026-10-02 | 2026-10-31 | 4 | 30 / 30 / 20 / 30 | 0 | 无 | **整段重算**(每臂 `computed_at` 单一时刻,最晚 d+30) | **否** —— 无逐行时间戳证据 |
| `cis_tilt_daily` | 直读 | 2023-01-02 | 2026-10-31 | 5 | 1399 / 1399 / 26 / 20 / 6 | 0 | 无 | 混合:`cis_a1` 26 行里 5 行晚于 d+2;`cis_a1_u`、`fund_a1_u` 干净;两个 `*_replay` 臂带 2023→ 历史 | **否**(前向臂部分可用,历史段不可) |
| `hl_book_daily` | 直读 | 2026-09-23 | 2026-10-31 | 1(内含 5 个子账) | 39 | 0 | 无 | 逐行 upsert:**2 行写于 d+3**(09-26、09-29)、**11 行 `correction` 非空** | **否** —— 实测有晚写与修正 |
| `core_variants_daily` | 直读 | 2019-01-01 | 2026-10-31 | 12 | 11×1399 + 1×2861 | 0 | 无 | 活臂逐行 upsert(多数 0 行晚于 d+2);`cap_pit24` 等重放段带历史 | 部分(仅前向段) |
| `multiplier_daily` | 直读 | 2023-01-02 | 2026-10-31 | 16 | 7×1399 + 2×78 + 23/19/8/8/15/11/11 | 0 | 无 | 活臂逐行 upsert;`mult_v1` 有 2 行晚于 d+2 | 部分(仅前向段) |
| `r_money_daily` | 直读 | 2026-10-19 | 2026-10-31 | 1 | 13 | 0 | 无 | 逐行 upsert,`computed_at` 13 个不同时刻,最大滞后 **1 天** | **是**(干净但只 13 天、只 1 个臂) |
| `short_paper_money` | 直读 | 2026-10-26 | 2026-10-31 | 2 | 6 / 6 | 0 | 无 | 逐行 upsert,每臂 1 行写于 **d+3** | **否** |
| `cis_official_daily` | 直读 | 2026-10-10 | 2026-10-31 | 59 | 56×22 + 2×21 + 1×1 | 0 | 无 | 逐行 upsert(`published_at` 每臂 22 个不同时刻,最大滞后 **1 天**,**0 行晚于 d+2**) | **是**(覆盖最广的干净表) |
| `risk_meter_history` | 直读 | 2026-08-24 | 2026-10-31 | 1 | 51 | **18** | **15 天(10-14 → 10-28)** | 逐行 upsert(`computed_at` 51 个不同时刻,滞后 0 天) | **否** —— 中段有 15 天空洞 |
| `beta_core_nav` | 直读 | 2026-08-08 | 2026-11-01 | 1 | 73(+1 个重复日) | **13** | 5 天(09-09 → 09-13) | `marked_at` 每行不同时刻、滞后 0 天;**17 行带 `void_reason` 显式作废** | **否** —— 缺口是「有据作废」,不是静默 |
| `signal_journal` | 直读 | 2026-05-25 | 2026-11-01 | 57 | 每符号 1~13 条 | 不适用 | 不适用 | **不是按日表** —— 每行是一次信号事件 | 不适用(不按日历读) |
| `portfolio_layer_daily` | 401 ⇒ 仅公开接口 | 2023-01-02 | 2026-10-31 | 5 | 1399×3 / 23 / 19 | 0(n=跨度) | 无 | **读不到** | 读不到 |
| `feature_arms_daily` | 401 ⇒ 仅公开接口 | 2025-05-12 | 2026-10-31 | 3 | 538×3 | 0(n=跨度) | 无 | **读不到** | 读不到 |
| `meta_allocator_daily` | 401 ⇒ 仅公开接口 | 2023-07-03 | 2026-10-31 | 1 | 1217 | 0(n=跨度) | 无 | **读不到** | 读不到 |

> 「n=跨度」= 用公开接口给的 `first` / `last` / `n` 做算术核对(`n == 末日−首日+1`),不读行内容;**46 个臂全部成立,无不连续臂**。
>
> **臂数口径(机器核对,`t217_armcount.py`)**:上表「臂」列求和 = **168**(含 `signal_journal` 的 57 个事件臂)。**按日口径**(剔除事件表 `signal_journal`)= **直读 102 个臂 + 公开接口 46 个臂,并集 111 个唯一 table+arm 对**;其中直读 102 = 原 7 张表 41 个 + `cis_official_daily` 59 + `risk_meter_history` 1 + `beta_core_nav` 1;公开接口 46 个与直读重叠 37 个,只有公开接口可见的 9 个臂属 3 张 401 表。

**第三方实际能验的是什么**(`/api/v1/proof/anchors`,唯一对外的哈希锚):

- 24 条日锚,`d` 从 **2026-10-07 到 2026-10-30**,**无缺失日**,每条带 `digest` + `n_rows` + `submitted_at` + 3 个 OpenTimestamps 日历;提交滞后:10-07~10-12 为 1 天,10-13~10-30 为 2 天。
- 覆盖不到「自首日起」:`core_cap` 前向起点是 10-02/10-03、`cis_a1` 是 10-06、`hl_book_daily` 是 09-23 —— **锚点从 10-07 才开始**;各账的末日 10-31 **在读取时尚未出锚**(10-30 的锚是 11-01T00:00 提交的)。
- 锚点是当天行的汇总哈希,不带表级 `computed_at`,所以**它无法区分「整段重算」与「逐日写」** —— 对 `core_cap_daily` / `cis_tilt_daily` 这类表,锚点连续 ≠ 记录是逐日产生的。

---

## 2. ① 按日前向表:逐臂明细

口径:
- **应有天数** = 末日 − 首日 + 1(自然日;这些表是加密市场,每日一根,周末也写)。
- **缺失天数 / 最长缺口**:在该臂的日期集合上补齐自然日,再统计连续空档。工作日口径同时统计(全为 0,说明没有「只在周末断」的情况)。
- **前向段**:以公开接口给的 `inception` 为准(`core_variants` / `multiplier` / `portfolio_layer` / `feature_arms` 的 `inception` 是 10-08 / 10-11 一类),`inception` 之前的历史行单列为「重放段」。

### 2.1 `core_cap_daily`(4 臂)

| 臂 | 首日 | 末日 | 行数 | 应有 | 缺失 | 最长缺口 | 写入口径 |
|---|---|---|---|---|---|---|---|
| cap_a05 | 2026-10-02 | 2026-10-31 | 30 | 30 | 0 | 无 | 整段重算(`computed_at` 单一时刻,最晚 d+30) |
| cap_a1 | 2026-10-02 | 2026-10-31 | 30 | 30 | 0 | 无 | 整段重算(同上) |
| cap_a1_u | 2026-10-12 | 2026-10-31 | 20 | 20 | 0 | 无 | 整段重算(最晚 d+20) |
| ew_a0 | 2026-10-02 | 2026-10-31 | 30 | 30 | 0 | 无 | 整段重算(最晚 d+30) |

**卡面口径结论**:四臂 `computed_at` 全同属一次写入 ⇒ **整段重算,无逐行时间戳证据**,不得判为回填,也不得据此声称「逐日产生」。

### 2.2 `cis_tilt_daily`(5 臂)

| 臂 | 首日 | 末日 | 行数 | 应有 | 缺失 | 最长缺口 | 写入口径 |
|---|---|---|---|---|---|---|---|
| cis_a1 | 2026-10-06 | 2026-10-31 | 26 | 26 | 0 | 无 | 逐行 upsert,**5 行晚于 d+2** |
| cis_a1_u | 2026-10-12 | 2026-10-31 | 20 | 20 | 0 | 无 | 逐行 upsert,无晚于 d+2 的行 |
| fund_a1_u | 2026-10-26 | 2026-10-31 | 6 | 6 | 0 | 无 | 逐行 upsert,无晚于 d+2 的行 |
| cis_a1_u_replay | 2023-01-02 | 2026-10-31 | 1399 | 1399 | 0 | 无 | 带 2023→ 历史(**1378 行晚于 d+2**) |
| fund_a1_u_replay | 2023-01-02 | 2026-10-31 | 1399 | 1399 | 0 | 无 | 带 2023→ 历史(**1385 行晚于 d+2**) |

注意 `cis_a1` 与 `cis_a1_u` 的差别:同一张表、同一写入口径(逐行 upsert),`cis_a1_u` 一行不晚,`cis_a1` 有 5 行晚于 d+2 —— 晚写是**逐臂**的,不是表级的。

### 2.3 `hl_book_daily`(卡面点名的唯一「逐行 upsert」表)

- 行数 39,2026-09-23 → 2026-10-31,缺失 0,最长缺口 无。
- **`computed_at` 晚于 d+2 天的行 = 2 行**:`d=2026-09-26`(写于 09-29,滞后 3 天)、`d=2026-09-29`(写于 10-02,滞后 3 天);其余 37 行滞后 1~2 天。
- **`correction` 列非空 = 11 行**,日期为 2026-09-25 ~ 2026-10-05。correction 内容(S-490,落款 2026-10-06T03:09:31Z):
  > 「09-25~09-28 的收益用了晚一天的 coingecko_pro_ohlc(S-436 修复前);决策照旧,只改账;之后的 NAV 顺延」

  即 **09-25~09-28 这 4 天的收益在 10-06 被改写**,并把 NAV 顺延到其后 11 天。修正本身有据可查(留了 `orig_nav` / `orig_ret`),但这 4 天的收益**在首次写入后被重算过**,所以「自首日起连续、未回填」这句话对这张表**不成立**。

### 2.4 `core_variants_daily`(12 臂)/ `multiplier_daily`(16 臂)/ `r_money_daily` / `short_paper_money`

- 两个重放大表的日期轴同样零缺失;但 11 / 7 个 `*_replay` 臂各自带 2023→(或 2026-08-15→)的历史行,历史行数合计 `core_variants` 11×1399 + 2861、`multiplier` 7×1399 + 2×78 ≈ 16,000 行,**这些行的 `computed_at` 晚于 d+2 天是必然的**(重算所致),不是回填事故 —— 判据上要把「重放段」与「前向段」分开。
- 前向段(≥ inception)本身仍零缺失:`core_variants` 活臂 10-08→10-31 = 24 天全在,`multiplier` 活臂 23/19/8/8/15/11/11 天全在。
- `r_money_daily`:13 行、13 个不同 `computed_at`、最大滞后 1 天、无 `correction` —— 符合「逐行写、未回填」的表之一。
- `short_paper_money`:2 臂 × 6 天,每臂有 1 行写于 d+3(滞后 3 天)。

### 2.5 补扫的 4 张按日表(初稿漏掉,本轮补上)

初稿只查了卡面点名的 3 张 + 顺手发现的 4 张;本轮把**能直读的按日表扫全**,补上 4 张 —— 其中一张是**真实的静默断档**。

#### 2.5.1 `cis_official_daily` —— 覆盖最广的干净表(59 个符号)

- 1275 行 / 59 个符号(`symbol` 为臂),日期列 `d`,时间戳列 **`published_at`**。
- 每个符号的**臂内跨度 0 缺失**:56 个符号 22 天(10-10 → 10-31)、2 个 21 天、1 个(MKR)只有 1 天。
- **`published_at` 每臂 22 个不同时刻,最大滞后 1 天,0 行晚于 d+2,无 `correction` 列** ⇒ **逐行写、未回填**。
- 两处末端不齐(不是内部空洞):**ETH 只到 10-30**(缺 10-31),**MKR 只有 10-10 一行**。

⇒ **这是本批「可作第三方『自首日起连续、未回填』证据」里覆盖最广的一张**(59 个符号 vs `r_money_daily` 的 1 个),比初稿说的「`r_money_daily` 唯一干净」更强。局限:只覆盖 22 天,且它记的是**分数**不是账。

#### 2.5.2 `risk_meter_history` —— 本卡唯一的**静默断档**

- 51 行,2026-08-24 → 2026-10-31,日期列 `d`,时间戳 `computed_at`(51 个不同时刻,**滞后 0 天**)。
- **缺失 18 天,3 段缺口**:`09-19..09-20`(2 天)、`10-04`(1 天)、**`10-14 .. 10-28`(15 天)**。
- 写入口径本身是干净的(逐行、每天一个时刻),**没有 `void_reason` 之类的作废标记** —— 与 `beta_core_nav` 不同,这里的 15 天是**静默消失**。
- 写端健康:`rpc/write_health` 里 `risk_meter_history` **last_ok = 2026-10-31T18:00:06、last_fail = null、24h 内 ok=1/fail=0** ⇒ **写端今天在跑、且没有记录过失败**,但历史缺口的原因在 lane 通道里看不到。
- 附带一个口径线索:缺口前 `d=2026-10-10/11/12/13` 的 `computed_at` 都落在**前一天**(18:00/18:00/19:00/19:00),而缺口后 `d=10-29/30/31` 的 `computed_at` 落在**当天**(16:00/17:00/18:00)⇒ 写端的**日期约定在缺口结束处换过一次**。

#### 2.5.3 `beta_core_nav` —— 缺口有据(作废而非静默)

- 74 行 / 73 个唯一 `mark_date`(有 1 个重复日),2026-08-08 → 2026-11-01,时间戳 `marked_at`(每行不同时刻,**滞后 0 天**)。
- **缺失 13 天**,最长缺口 5 天(09-09 → 09-13)。
- **关键:17 行带非空 `void_reason`,是显式作废**,落款分别是 S-123 / S-147 / S-194 / S-283 —— 例如 `S-283: VOID — (a) inception inheritance via unscoped Redis state key`、`S-194: marked 0.00% while the equal-weight panel moved +11.03%`。**作废连原因和事故编号都留了。**
- `interval_hours` 分布:43 行恰为 24,27 行为 null,另有 17.08 / 35.88 / 143.99 / 156.11 四个异常值 ⇒ **标称日频、实际间隔不齐**;`mark_source` 有 1 行是 `manual`。
- ⇒ 判据结论:**这张表的缺口「有据可查」**(作废留痕),不是静默断档;但它**不能**当第三方「未回填」的证据,因为作废本身就是事后处置。

#### 2.5.4 `signal_journal` —— **不是按日表,已从按日集合剔除**

- 349 行 / 57 个符号,每符号只有 **1~13 行**(不是每天一行)⇒ 每行是一次**信号事件**(有 `signal_date` / `recorded_at` / `outcome_30d` / `alpha_30d`)。
- **按日历天去读它,会算出「缺失 4598 天」的假象**(初稿脚本正是这么算的)—— 那是口径错误,不是连续性问题。
- 它的 `recorded_at` 滞后 0 天(`maxlag=0`)、`ts_n_lag_gt2=0`,写入口径本身干净;但**它不属于「按日前向记录」**,不参与本卡的连续性判定。

---

## 3. ② `loop_attempt` 与「近 7 天约 50 次超时类 error」

### 3.1 直读:读不到

`GET /rest/v1/loop_attempt?select=at,loop_name,outcome,reason,elapsed_ms&order=at.asc&limit=50` → **HTTP 200,0 行**。
表里确实有行(只读函数 `rpc/loop_attempt_health` 读得到 **97 个循环**),但 publishable key 的 RLS 没有放行直读 ⇒ **逐条事件读不到**(含 7 天窗口、含每次失败的 `reason` 与 `elapsed_ms`)。
按卡面纪律:这里写「读不到」,**不推测来源**。

### 3.2 可读通道(`rpc/loop_attempt_health`,24h 聚合)

近 24h:**成功 992 次 / 失败 243 次**,19 个循环有失败。

按每个循环的**末次** `last_reason` 归类(实测;规则见 `t217_classify_loops.py`,四桶互斥、可机器复核):

| 类别 | 循环(次数) | 小计 |
|---|---|---|
| **BENIGN**「无事可做」型标记 | `_perp_mcap_backfill_loop` 78(没有待补…)、`_hl_book_loop` 24(2026-10-31 已记录)、`_anchor_loop` 8(已锚过——只追加不覆盖)、`_r_tickets_paper_loop` 7(up to date)、`_tokenization_tilt_loop` 4(重算至…)、`_core_variants_loop` 1(回放至…)、`_multiplier_loop` 1(回放至…)、`_cis_tilt_loop` 1(重算至…) | 124 |
| **FROZEN** 有意冻结 | `_causal_paper` / `_dingge_paper` / `_combined_book` / `_scalable_book` / `_two_layer_paper` / `_fusion_paper`,各 4 次 | 24 |
| **EMPTY** 原因字符串为空 ⇒ **不可归类** | `_executor_dry_run_loop` 73、`_forward_return_backfill_loop` 14、`_public_cache_warm_loop` 1 | 88 |
| **OTHER** 有原因文本、需人工看 | `_forward_record_loop` 5(「refresh: no response from Supabase after retries」)、`_signal_attribution_loop` 2(信号变化计数) | 7 |
| **合计** | | **243** |

> **修正(本轮)**:初稿把 `_forward_return_backfill_loop` 的 14 次空原因算进了 BENIGN,又在 §3.4 里把同 14 次算进「不可归因」——**同一批次数被双算**,导致「158 次良性」的结论虚高。现已拆成独立的 EMPTY 桶:BENIGN+FROZEN = **148 次(60.9%)**,EMPTY = **88 次(36.2%)**,OTHER = **7 次**。
>
> **EMPTY 桶不做归因推测**:原因字段为空,从 lane 可读通道无法判断它是超时、失败还是正常的无输出。`_forward_return_backfill_loop` 名字里有 "backfill"、`_executor_dry_run_loop` 是执行器干跑,两者**有可能**与超时有关,但**本卡不推测**(见 §5 的代查清单)。

### 3.3 时间点

19 个循环的末次失败时间落在 **2026-10-31T16:04:11Z → 2026-11-01T13:53:39Z**,两簇最密:

- **2026-11-01T12:48:13~12:48:16Z**:6 个冻结 paper 循环**同一轮里各触发 1 次** —— 批量标记,不是独立故障。(各循环 `n_fail_24h=4`,合计 24 次。)
- **2026-11-01T13:05:50~13:05:51Z**:`_forward_return_backfill_loop`(14) / `_forward_record_loop`(5) 各 1 次(同一次调度)。

**计数里至少 24 次确定是批量标记**(冻结循环的那一轮),但**其余各次是不是独立事件,现有粒度判不了**:三个最大计数源 `_perp_mcap_backfill_loop` 78 / `_executor_dry_run_loop` 73 / `_hl_book_loop` 24,各自的**末次**失败时间分散在三个不同时刻(`13:53:39Z` / `06:13:36Z` / `12:53:38Z`);`rpc/loop_attempt_health` 只给**每循环的末次**时间与 24h 计数,不给逐条 `at`,所以「73 次是不是 73 个独立事件」**不能从这一层判定** —— 要逐条 `at`(见 §5 代查清单)。

### 3.4 对「≈50 次超时类 error」的判定

**复现不出来。** 24h 聚合里 **243 次失败中 0 次原因含 timeout / 超时 / deadline 字样**;**88 次(36.2%)的 `reason` 是空字符串**,最大两个源是 `_executor_dry_run_loop`(73)与 `_forward_return_backfill_loop`(14)—— 空原因意味着**从 lane 能读的通道无法把它们归到任何一类**。
唯一带网络超时语义的一条是 `_forward_record_loop`(5 次/24h)的原因「refresh: no response from Supabase after retries / refresh returned NoneType None, not an int」。
7 天窗口的**逐条时间点读不到**(表 0 行;`/internal/loop-attempts` 端点实测 404),所以「近 7 天 ≈50 次」这个数字在 lane 侧**既不能证实也不能否证**。

### 3.5 顺带量到的两条真错误(不是超时)

`rpc/write_health`(逐表 100 张,27 张有 `last_fail`,24h 失败合计 11 次),两条原因可见:

| 表 | 末次失败 | 24h 失败 | 原因 |
|---|---|---|---|
| `cis_backtest_results` | 2026-11-01T11:59:45Z | 2 | HTTP 400 `PGRST204`:Could not find the 'asset_count' column of 'cis_backtest_results' —— **schema 漂移** |
| `experiment_runs` | 2026-11-01T13:05:42Z | 3 | HTTP 409 `23505`:Key (run_id)=(signal_factory_20261101) already exists —— **唯一键冲突** |

其余 6 次分布在 3 张表:`treasury_decisions` 4 次、`ohlcv_daily` 1 次、`cis_signal_attribution` 1 次,`last_body` 均为空(不可归因)。

---

## 4. ③ `executor_host` 心跳缺口与 live 余额 +17.4

- **读不到(心跳源本身)**:public schema 的 181 张表里**没有 `executor_host`** —— `GET /rest/v1/executor_host` 返回 **404 `PGRST205`**(hint 指向 `public.execution_intents`)。心跳不在 Supabase,在别处(Mac 侧或主机侧文件),lane 无可读通道。
- **读不到(余额)**:卡面列明 401 的 6 张表,本轮只探了读权限状态,全部 **401 `42501` permission denied**:`beta_plus_daily`、`tokenization_tilt_daily`、`allocation_daily`、`allocation_nav_daily`、`live_account_daily`、`rr_matrix_daily`。
- 另有 7 张「有写入端但 lane 读不到行」的表(直读 200、样本为空 = 表空或被 RLS 全过滤):`execution_intents`、`execution_outcomes`、`decisions`、`vault_nav_tick`、`trade_results`、`wallet_profiles`、`nav_exceptions` —— 同样无法解释 +17.4。

**⇒ 10-26 21:42Z→10-29 14:24Z 期间的 live 余额 +17.4,在 lane 通道里没有任何可读来源,不推测成因。**

---

## 5. 需 Seth 代查(用 Supabase MCP 只读补)

| 项 | lane 侧实测 | 需要什么 |
|---|---|---|
| `live_account_daily` | 401 | 10-26→10-29 的每日 live 余额/权益,判断 +17.4 是净值变动还是资金进出 |
| `allocation_daily` / `allocation_nav_daily` | 401 | 同窗口的配置与净值,做交叉核对 |
| `beta_plus_daily` / `tokenization_tilt_daily` / `rr_matrix_daily` | 401 | 前向段的行数 / 首末日 / 缺失天数(卡面 6 张表的账) |
| `loop_attempt` 逐条 | 200 但 0 行 | 近 7 天逐条 `at` / `loop_name` / `reason` / `elapsed_ms` —— 才能把「≈50 次」和 88 次空原因落到时间点与循环上 |
| `loop_attempt.outcome` 取值分布 | 读不到(同上一行) | **7 天内 `outcome` 各取值的次数** —— §7.2 的读法(`n_fail_24h` 数的是「outcome ≠ ok」而非「错误」)要靠这个分布证伪/证实;顺带看 `elapsed_ms` 的长尾是否就是超时所在 |
| `executor_host` 心跳源 | Supabase 无此表 | 心跳实际写在哪儿(Mac 侧文件? Railway 日志?),才能核 10-26→10-29 的 64.7h 缺口 |
| **`risk_meter_history` 15 天空洞成因** | 表可读,缺口已定位(10-14→10-28);写端 `last_ok=10-31T18:00`、`last_fail=null` | **写端在 10-14~10-28 期间是没跑、跑了没写、还是写了被清掉?** lane 侧只能看到结果表,看不到写端历史;需要查 Railway/Mac 侧该循环的运行记录。另:该表的 `computed_at` 日期约定在缺口结束处换过一次(从「算前一天」变成「算当天」),像是换过实现 |
| `beta_core_nav` 的 17 行 `void_reason` | 表可读,作废原因已取到全文(S-123/S-147/S-194/S-283) | 只需确认这些作废是否已在别处登记(本卡只做只读核对,不做登记) |

---

## 6. 复现方法(本卡落的脚本)

| 文件 | 作用 |
|---|---|
| `docs/research/t217_final2.py` | 主脚本:直读 7 张按日表(带 `order=` 翻页)+ 公开接口 7 张表 + proof 端点 + `rpc/loop_attempt_health` + `rpc/write_health` + 401 表权限探测 → `t217_final2.json` |
| `docs/research/t217_verify.py` | 写 `write_health` 原始列名核对 + 「n == 跨度+1」算术核对(46 臂) |
| `docs/research/t217_anchors.py` | 锚点序列的日期覆盖 / 缺失 / 提交滞后 + `hl_book_daily` 的 `correction` 全文 |
| `docs/research/t217_detail.py` | `hl_book_daily` 晚写行逐行列出 + 循环失败原因清单 |
| `docs/research/t217_summary.py` | 把 `t217_final2.json` 压成可核对的紧凑表 |
| `docs/research/t217_armcount.py` | **臂数口径核对**:按日口径直读 102 / 公开接口 46 / 并集 111 个唯一 table+arm 对(含事件表则 168) |
| `docs/research/t217_extra_tables.py` | **补扫 4 张按日表**(`cis_official_daily` / `signal_journal` / `beta_core_nav` / `risk_meter_history`),显式指定日期/臂/时间戳列 + 翻页读 |
| `docs/research/t217_beta_core_nav.py` | `beta_core_nav` 写入口径:17 行 `void_reason` 全文 + `interval_hours` / `mark_source` 分布 |
| `docs/research/t217_risk_meter_gaps.py` | `risk_meter_history` 缺口**逐日**核对(3 段缺口)+ `computed_at` 时刻分布 |
| `docs/research/t217_classify_loops.py` | **§3.2 四桶分类**(BENIGN/FROZEN/EMPTY/OTHER,规则确定性、可复核) |
| `docs/research/t217_loops_check.py` | §3 数字复核:失败聚类、空原因计数、write_health 汇总 |
| `docs/research/t217_writehealth_check.py` | §3.5 复核:100 张表逐张、失败次数分布 |
| `docs/research/t217_write_health.py` | 单独重取 `rpc/write_health` → `t217_write_health.json`(主脚本偶发 RPC 空返时用它补) |

**踩过的坑(留给下一轮)**:
1. PostgREST 单页上限 1000 行。第一版脚本用 `limit=2000` 并以「返回行数 < limit」判断末页 ⇒ **每张表只拿到第一页**,`cis_tilt_daily` / `core_variants_daily` / `multiplier_daily` 的行数被截到 1000,缺口与臂数全错。修法:`limit=1000` 且「返回 == limit 就继续翻」。本报告所有数字来自修好后的 v2。
2. `rpc/write_health` 在复核轮**偶发空返**(HTTP 200 但 body 不是 list),主脚本的 `isinstance(tables, list)` 分支直接跳过 ⇒ 那一轮的 `write_health` 段是空的。修法:`t217_write_health.py` 单独重取并落盘,再用 `t217_writehealth_check.py` 复核。**空返 ≠ 没有失败**。
3. **`tests/test_research_paged_reads_have_order.py` 会把「单行探测」也判成违例。** 规则是「文件里出现 offset+limit,就查所有带 `select` 但没 `order` 的参数字典」—— 本卡的 `{"select": "*", "limit": "1"}` 单行探测(取列名 / 探 401 / 探表是否存在)也被命中。**真正的翻页循环本来就带 `order`(逐行核对过 `t217_final2.py:131`、`t217_extra_tables.py:106`),所以本报告的数据没有受「不带 order 会漏两成键」的影响。** 修法:探测调用去掉冗余的 `select=*`(PostgREST 不带 select 时默认返回全部列,语义不变),`t217_loop_attempt.py` 的探测则显式补 `order=at.asc`。改完后重跑主脚本 + 补扫脚本,行数与臂数逐位不变(1275/349/74/51、46/102/111)。

---

## 7. 探索性发现(**探索性 —— 需另立预注册、在新数据上过零信号对照**)

1. **「≈50 次超时」这个数字本身可能是把失败计数当成了错误计数。** 24h 聚合里 243 次失败中 124 次是「没有待补 / 已记录 / 已锚过 / up to date」这类**良性无操作标记**,24 次是**有意冻结**的循环在批量打标;两者合计 **148 次(60.9%)**。若历史统计把这些计入「error」,50 这个量级可以被完全解释掉,而**剩下的 95 次里还有 88 次原因字段为空**。**这条只是对既有口径的重新分类,不是对任何时间窗口的统计推断。**
2. **BENIGN 桶里有几条的 `reason` 其实是「做完的公告」而不是失败**:`_core_variants_loop`「回放至 2026-10-31」、`_multiplier_loop`「回放至…」、`_cis_tilt_loop`「重算至…(5 臂)」—— 这些是**成功完成后写的状态文本**,却被计入 `n_fail_24h`。说明该聚合计数器数的很可能是「outcome ≠ ok」的标记次数,而不是「错误次数」。**若这个读法成立,任何拿 `n_fail_24h` 当 error 数的口径都会系统性高估。**(**探索性 —— 需另立预注册、在新数据上过零信号对照**:需要在 7 天逐条 `outcome` 分布上验证「非 ok 但 reason 是完成公告」的占比。)
3. **`_executor_dry_run_loop` 24h 失败 73 次、`_forward_return_backfill_loop` 14 次,原因字段为空。** 空原因 = 从现有通道无法归因。若这两个循环在 7 天窗口里也占大头,那「≈50 次」的来源多半在这里。**需要逐条事件才能定论。**
4. **锚点序列的滞后在 10-13 之后从 1 天变成 2 天并保持**(10-07~10-12 为 1 天,10-13~10-30 为 2 天)。这与「前向段 10-08 才开始、之后行数增至 139」的扩容时点一致,但**没有做过零信号对照**,也可能只是任务调度相位变了。
5. **「可作第三方证据」的样板有两张,不是一张。** `cis_official_daily`(59 个符号 × 22 天、每臂 22 个不同 `published_at`、最大滞后 1 天、0 晚写、0 correction)与 `r_money_daily`(13 行、最大滞后 1 天)都满足「逐行写 + 无晚写 + 无 correction」,而**前者覆盖面远大于后者** —— 初稿说 `r_money_daily` 是「唯一」是漏扫所致。**但两者的共同短板是:都只有 13~22 天、且都不是对外账的净值序列。** 现有对外锚(`/api/v1/proof/anchors`)只有 10-07 → 10-30,既覆盖不到各账起点,**也不带表级 `computed_at`、无法区分「整段重算」与「逐日写」**。**是否值得单独做一版逐行时间戳的对外锚,需要 Jazz 拍板(对外口径)。**
6. **再复核轮新增的机制线索:24h 失败计数里至少 24 次(冻结 paper 循环)确定是「一轮批量打标」,其余各次的独立性判不了。** 6 个冻结循环的末次失败挤在 `12:48:13~12:48:16Z` 的 3 秒内,各 `n_fail_24h=4`;而三个最大计数源的末次失败时间分散在三个不同时刻。`rpc/loop_attempt_health` 只给每循环的**末次**时间,不给逐条 `at`,所以「73 次 = 73 个独立事件吗」在现有粒度下**无法判定**。**这条给 §7.2「计数器数的可能是 marker 次数」提供了同向的机制证据,但不是证明。**(**探索性 —— 需另立预注册、在新数据上过零信号对照**:需要在 7 天逐条 `at` 上做「同一秒内多行」的时间聚类,才能把批量标记与独立事件分开。)

---

**合规**:本报告不含任何买卖建议;信号一律用 STRONG OUTPERFORM / OUTPERFORM / NEUTRAL / UNDERPERFORM / UNDERWEIGHT 口径。
