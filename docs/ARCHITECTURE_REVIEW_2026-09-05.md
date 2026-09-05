# 架构自上而下核对 — 2026-09-05

> Jazz:「我们需要先 oversee 整个架构,然后再回到这里。」
>
> **本次纪律:每一条结论必须有一次 grep / curl / SQL 支撑。**
> 这个 session 的教训就是我对自己系统的记忆不可信 —— 一天之内,
> 「我们没有 CG Analyst」「HL 的失败是覆盖率拒绝」「守卫清单是对的」
> 三条凭记忆的断言全错。所以这份文档里没有一句「我认为」。

---

## 0. 头条:健康面板测的是「函数返回了」,不是「活干了」

`src/api/main.py` 的 14 个有心跳的循环里,**11 个写死 `ok=True`**
(AST 统计,不是目测):

    无条件 ok=True     11
    从返回值推导 ok     3

也就是说,只要采集函数**没有抛异常**,心跳就报健康 ——
它从不看 `rows_written`、不看 `resolved`、不看表有没有长。

### 这不是理论风险,是已经在发生的四条假绿灯

| 循环 | 心跳 | 它该写的表 | 实测 |
|---|---|---|---|
| `_outcome_tracker_loop` | **ok** (417s 前) | `signal_outcomes` | **停 125 天**(2026-05-03) |
| `_factor_tilt_loop` | **ok** | `factor_tilt_nav` | **0 行** |
| `_pod_aggregator_loop` | **ok** | `pod_aggregator_nav` | **0 行** |
| `_two_layer_paper_loop` | **ok** | `two_layer_paper_nav` | 停 **14 天** |

9 本纸面账里 **4 本的表是空的或陈旧的,而 4 本全部报 ok**。
面板上写的是「12/14 健康」。

`_outcome_tracker_loop` 是最干净的样本,整个机制在三行里:

    summary = await run_outcome_tracker(dry_run=False)
    print(f"[OUTCOME] ... written={summary.get('rows_written')}")
    await _beat("_outcome_tracker_loop", ok=True)

`rows_written` **被打印出来,然后被丢掉**。它就在那一行的上一行。

> **「循环成功」和「工作完成」是两个状态,而心跳只测第一个。**

这正是 Jazz 反复问的那句 ——「怎么都说健康,都说没问题,但就是没有做完?
总发现有东西停了?」—— 现在它有了数字:**11/14**。

### 为什么它躲过了这个 session 的每一次排查

S-278 建了 `producer_freshness`(事件时钟:表的内容新不新),
S-282 建了 `loop_beat`(写时钟:写入者活不活)。**两个都建了,而且都对。**
但健康面板读的是心跳,`_outcome_tracker_loop` 在心跳上永远是绿的,
于是**建好的事件时钟没有被接到判决上**。

又是「买了卡不插线」—— 这次是我在同一周里买的两块卡,插了一块。

---

## 1. Kernel 层 — 六个对象,两个是死的

ARCHITECTURE.md:「最深的对象不是 Asset,是 **Entity** 和 **Decision**。」

| 对象 | 表 | 行数 | 陈旧 |
|---|---|---:|---|
| Entity | **`entities`(规范表)** | **1** | **39 天** |
| Entity | `treasury_entities` | 96 | 0 天 ✓ |
| Decision | `treasury_decisions` | 891 | 3 天 ✓ |
| State | `corporate_treasury_history` | 428 | 0 天 ✓ |
| Quality | `cis_scores` | 148,062 | 0 天 ✓ |
| Regime | `regime_band_log` | 231 | 0 天 ✓ |
| **Outcome** | **`signal_outcomes`** | 7,743 | **125 天** |
| Outcome | `signal_track_record` | 1,291 | 0 天 ✓ |

### 1a. Entity 有两张表,规范的那张是空的

`entities` 是 kernel 的 Entity 对象,**1 行,39 天没动**。
本周 S-291/S-292 真正落地的实体数据全在 `treasury_entities`(96 行,今天)。

两张表叫同一个概念,一张活一张死 —— 而「规范」的是死的那张。
任何按 ARCHITECTURE.md 去找 Entity 的人(人或 agent)会读到 1 行。

### 1b. Outcome 死了 125 天,而 ARCHITECTURE.md 说它是产品

原文:

> 「在 A2A 市场里,稀缺资源是**可验证的前向 track record** —— 验证装置本身就是产品。」
> 「**一个我们没有跑过自己 loop 的信号,就是我们不能声称的信号。**」

`signal_outcomes` 是那个 loop 的产物,它 125 天没有新行。

**缓解事实(重要):** `signal_track_record`(今天,1,291 行)**不是**从
`signal_outcomes` 算的 —— 它由 Supabase RPC `refresh_signal_track_record`
从 `cis_scores × ohlcv_daily` 独立重算。所以对外的 track record
**没有**建在死表上。这条纪律守住了,是这次核对里最好的消息。

但 Outcome 这个 kernel 对象本身仍然是冻的。

### 1c. Propagation 层(北极星说的「前沿」)其实活着

| `cause_snapshots_daily` | 1,272 | 0 天 ✓ |
| `holder_concentration_history` | 104 | 5 天 |
| `narrative_snapshots` | 936 | 0 天 ✓ |
| `conviction_verdicts_daily` | 2,941 | 0 天 ✓ |

ARCHITECTURE.md 把 Entity/Decision/propagation 写成「前沿 / 还没到」。
**实测它已经到了** —— 文档比代码旧。这是一条正向错位:
我们比自己的北极星文档走得远,而文档没更新,于是这层的成果不被自己承认。

---

## 2. 数据脊柱 — 拦住了,没有接上

(今晚 S-296/S-297/S-298 的完整记录在 REFUTATION_LEDGER,这里只放结论)

| 源 | 标的 | 最新 |
|---|---:|---|
| `hyperliquid` | 177 | **2026-08-23**(被自己的策略守卫拦停 13 天) |
| `coingecko*` | 25 | 今天 ✓ |
| `funding_history` (binance_perp) | 10 | **2026-08-07**(停 29 天,无人知) |

**面板 262 个标的里 237 个没有日线来源。** 根因不是源选错了,
是 S-205 的守卫**只拦不导** —— 它说了「别在这里取」,没说「去哪里取」。

`funding_history` 停在 08-07 是本次核对新发现的第五条死产出者,
而它同样从来没有出现在任何告警里(它在心跳体系之外)。

---

## 3. Primitives / 表面积 — 与「我们只做一件事」的张力

    API routes   69
    MCP tools    76

ARCHITECTURE.md 的反冒充纪律:

> 「我们做**一件事**……护城河是 know-how + 证明,不是表面积。
> 每一个新能力必须能归约成一个扎根于 kernel 的 primitive,否则它不属于这里。」

**76 个 MCP 工具,没有任何一处记录它们各自归约到哪个 primitive。**
这不是说它们错 —— 是说这条纪律**没有被任何东西检查**,
所以我们无法回答「有几个能归约、几个不能」。

一条写在文档里、没有任何检查的纪律,和一条不存在的纪律,行为上是同一个东西。
(本周反复的那句话,这次指向的是我们最核心的自我约束。)

**没有验的:** 逐个工具的归约性。要验就是 76 次判断,得 Jazz 定优先级。

---

## 4. 北极星 vs 实建 — 错位表

| ARCHITECTURE.md 说 | 实测 | 方向 |
|---|---|---|
| Entity/Decision 是「前沿,还没到」 | 已落地并每日更新 | **文档落后于代码** |
| Outcome 是证明闭环 | 死 125 天,心跳报 ok | **代码落后于文档** |
| 「没跑过自己 loop 的信号不能声称」 | 对外 track record 独立重算,**没有**用死表 | ✓ 守住了 |
| 「不卖表面积」 | 69 路由 / 76 工具,归约性无人检查 | **纪律未被强制** |
| ① beta = HOLD | `beta_core_nav` 今天,28 行 ✓ | ✓ 在跑 |
| loop_health 测「电流还在流」 | 测的是「函数返回了」 | **测错了量** |

---

## 5. 结构性对策(少数几条,不是清单)

### ① 心跳必须由「工作量」推导,不能写死

    await _beat(name, ok=True)                      ← 现在,11 处
    await _beat(name, ok=bool(summary["rows_written"]))   ← 应当

配一条只减不增的预算(与 `NO_BEAT_BUDGET` 同模式):
`HARDCODED_OK_BUDGET = 11`,守卫禁止新增。
**0 行是合法的**(今天没有可解析的信号),所以判据不是「必须有行」,
而是「**连续 N 轮 0 行 = 事件时钟停了**」—— 那正是 `producer_freshness` 的活。

### ② ~~把事件时钟接到判决上~~ → **它已经接上了。这条我写错了。**

**订正(同日,实测):** 我在上一版写了「健康面板的总裁决只读心跳」。
**这是错的,而且我没查就写了** —— 就在这份要求「每条结论都有探针」的文档里。

实测 `/internal/data-freshness`:

    verdict        : producers_dead
    verdict_source : producers
    producers      : dead=['signal_outcomes','market_state_vectors'] stale=['trade_results']

事件时钟**已经**是顶层裁决的来源,而且它**已经**抓到了 `signal_outcomes` 死。

真正的缺口是**范围**,端点自己诚实地写着:

    verdict_scope: covers "14/71", n_not_covered 39
    "⚠️ 这个裁决只对 14/71 个对象成立"

9 本纸面账里**只有 `beta_core_nav` 在生产者集内**。
`factor_tilt_nav`(0 行)、`pod_aggregator_nav`(0 行)、
`two_layer_paper_nav`(停 14 天)三本都在集外 ——
**事件时钟看不见它们(不在集内),写时钟也看不见(心跳写死 ok)。
它们恰好落在两块表的缝里。**

> **一个诚实的范围声明,不等于覆盖。**
> 它比隐瞒好得多,但范围外的东西照样在死。

**已做(S-299):** 8 本账全部加进 `EXPECTED` 与线上 `producer_freshness()`,
生产者集 12 → 20。加完立刻可见:

    factor_tilt_nav       n=0  两个时钟都是 null  → empty
    pod_aggregator_nav    n=0  两个时钟都是 null  → empty
    two_layer_paper_nav   n=28 停在 2026-08-22   → dead(死亡线 5 天)

**顺带查出的漂移:** 仓里的 `PRODUCER_SQL` 与线上函数已经不一致 ——
线上有第五列 `n_future`(S-293 的 2099 污染行计数),镜像没有。
而守卫只比对**表名**,比对不出列。又是作用域差一格。已同步。

### ③ Entity 的两张表要合成一张

规范表 1 行、实际表 96 行,是一个会持续误导人和 agent 的状态。

### ④ 反冒充纪律要有检查

给每个 MCP 工具标注它归约到哪个 primitive,不能标注的进一张显式清单
(与 `NOT_WIRED_YET` 同模式)。**不是为了删工具,是为了让「表面积」这件事可测。**

---

## 6. 本次没有核对的(显式列出,不装作已覆盖)

- 前端逐页与后端的对应(上一次全量走查是 2026-09-03)
- Mac 侧 cis_v4_engine / scheduler 内部(不在本 lane,需 Minimax)
- 合规语言的当前全量扫描(有 CI,但本次没单独跑)
- ②③④ sleeve 的策略正确性(这是策略评审,不是架构评审)
- 76 个 MCP 工具逐个的 kernel 归约性
- `macro_brief` 上游停摆的 Mac 侧根因(已进 MINIMAX_SYNC)

---

## 7. 一句话

这个 session 从 S-274 排到 S-298,二十几条,**几乎每一条都是同一个形状:
两个不同的状态塌进一个表示。** 今晚自上而下看完,那个形状的最大一处
不在任何一个采集器里 —— 在**健康判决本身**:

> **11 个循环把「我没崩」报成了「我干完了」。**

修那 11 个 `ok=True` 比修任何一个采集器都重要,
因为在它被修好之前,**我们对系统的每一次「健康」判断都不能作数** ——
包括我今晚给出的那些。
