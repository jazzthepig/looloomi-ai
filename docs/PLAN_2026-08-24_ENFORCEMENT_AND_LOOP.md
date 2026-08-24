# 下一步规划 — 试错资产化 + 循环打通（Seth, 2026-08-24）

> Jazz:「趁我们还在新的认知记忆周期里面,做好下一步的规划,然后把任务拆开给 minimax 们去执行,
> **这几个月的试错价值不要丢失了**。」
>
> 这份文档只回答一个问题:**已经付过学费的东西,怎样才不会再付一次。**

---

## 0. 先量,再规划

「试错价值不丢失」不是态度问题,是一个**可以量出来的比例**。MEMORY.md 定了判据:
**「if a test already enforces it, the test is the memory」**。所以:

```
台账里写下的教训（S-* 标题）          102 条
其中有测试 / preflight 关卡强制执行的   76 条   ← 真正不会丢
只以散文形式存在的                     26 条   ← 会被重新学一遍
                                    ─────────
                              强制执行率  75%
```

**那 26 条就是我们下一次要重新付学费的清单。** 逐条看过,分三类:

| 类 | 条数 | 是什么 | 归谁 |
|---|---|---|---|
| **A 可直接变成关卡** | 11 | S-100/110/119/126/162/177/182/188/195/214/215/216 —— 全是工程教训,都有明显的可执行形式 | **Seth** |
| **B 策略事实,要变成准入/约束** | 9 | S-84/85（F&G 是确认指标,用反了差 1,889bp）· S-87（顺周期杠杆不产生风险调整后收益）· S-112（ADV>$15M 是**准入规则**不是空头账本）· S-128/129/135 | **Minimax-B**（Seth 只提供关卡外壳） |
| **C 已交付状态记录** | 6 | S-97/98/99 等,记录"建成了什么",无需强制 | 不动 |

**⚠️ 三条 A 类是我今天刚写的**（S-214/215/216）。**今天写下的教训,今天就已经在"会丢"的那一栏里。**
这说明缺的不是纪律,是缺一个让"写下"和"强制"不能脱节的机制 —— 见 §T0。

---

## T0 — 试错资产化（最高优先,因为它保护其余全部）

### T0.1 强制执行率变成 CI 指标,只能升不能降

`scripts/check_lesson_enforcement.sh`:统计 `台账标题 S-号` ∩ `tests/ + preflight 引用的 S-号`,
与 `scripts/lesson_enforcement_baseline.txt`（今日 76）比较。**低于基线 → 构建失败。**

和 `check_ledger_citations.sh` 同一个形状,同一个理由:**一个只能向好的方向移动的数字,
比任何"要记得写测试"的约定都有效。** 那个约定我们有,而它今天产出了三条新的未强制教训。

### T0.2 A 类 11 条补关卡

| S-号 | 教训 | 可执行形式 |
|---|---|---|
| S-119 | 写入门槛不可绕过 | 断言:所有写路径经过 role gate,无直连 |
| S-126 | v2 起算没落库 | 断言:schema 版本号来自常量,不是字面量（S-144 同源） |
| S-182 | 五个宏观框自上线起渲染破折号 | 断言:**前端展示的每个字段,后端存在写者** |
| S-188 | 装在"会坏的东西"内部的保险不是保险 | 断言:守卫不与被守对象同进程/同 except 块 |
| S-195 | CoinGecko 端点给不出收盘价 | 断言:`market_chart` 不出现在任何收益序列路径 |
| S-214 | 常量命名了表却没有写者 | 断言:**每个 `*_TABLE` 常量都有对应的写调用** |
| S-215 | 中性值同时表示"没测到" | 断言:默认值必须伴随 `*_source` / `*_measured` 字段 |
| S-216 | 建了每一段却没让它流动 | 断言:每个 store 在 loop_health 视野内 |
| S-100 / S-110 / S-162 / S-177 | 同概念拆两半 · 身份先于数据 · 便宜的检验 · 研究面板不在管子上 | 逐条设计,T0.2 第二批 |

**S-214 那条是通用的,值得单独说:** 一个 `*_TABLE = "..."` 常量是一个承诺。今天发现两个
承诺从未兑现（`pod_aggregator_nav` / `factor_tilt_nav` 各 0 行数周）。
**AST 扫一遍就能保证这类承诺不再空头。**

---

## T1 — VDB 循环打通（Seth 的 lane 本体）

Jazz 定义:「你要管好的是**矢量数据库**还有价值挖掘后,**系统工程打通**风格平衡的 loop。」

实测（2026-08-24,`/internal/vdb-health` 上线后可持续观测）:

```
① 挖掘 (Minimax-C)          93 文件 / 16 R#              ✅
② intake → experiment_runs   60 行,4 天前               ✅ 但 dsr 只有 2/60
③ asset_embeddings           72 行,停 31 天             ❌ 无调度写者
④ market_state_vectors      582 行,停 19 天,regime_label 0/582  ❌
⑤ strategy_records            0 行                       ❌ RLS 0 policies
⑥ similar_market_states() 决策链                          ❌ 上游全死
⑦ 风格平衡                    零个文件                     ❌ 不存在
```

| # | 任务 | 归谁 | 前置 |
|---|---|---|---|
| **S-220** | `asset_embeddings` 调度写者（现在只有手动 endpoint,写入是 CIS 周期的静默副作用） | Seth | — |
| **S-221** | `strategy_records` RLS policy（一条 migration,MCP 直接 apply） | Seth | — |
| **task #37** | `market_state_vectors.regime_label` 582 天全 NULL | Seth | S-209 先修写入端 canonicalise |
| **S-209** | regime 两种拼法同时在库 | Seth | — |

**③④⑤ 全部是我自己已关闭的绿色任务。造了器官,没造代谢** —— 所以这一轮的验收标准
不是"建好了",是 **`/internal/vdb-health` 连续 7 天 `overall: flowing`**。

---

## T2 — 风格平衡（S-222）

**先说清它不是什么,免得又跑偏成因子讨论:** 它不挑策略、不定阈值、不碰 sleeve 内容。
它只回答一个工程问题 —— **七本账本的 NAV 之间相关多少,风格暴露是不是同一个。**

MEMORY.md:加密内 ρ̄ **0.441** vs 跨 TradFi **0.104**;**「分散只能来自别的资产类」**。
如果七本账都是加密横截面,**它们是一个赌注,不是七个**,而没有任何东西在测这件事。

交付:跨账本 NAV 相关矩阵 + 风格暴露分解 → 接进 `loop_health`。归 Seth。
前置:S-214 的写者已补,但两本账取数走被封的 `fapi.binance.com`（见 §VERIFY）。

---

## T3 — 重启存活（S-210）

断电 / 断网 / 重部署后 loop 必须自愈。四条:**幂等 · 状态在 Postgres 不在进程内存 ·
启动时 reconcile 回补空洞 · 心跳 + `days_since_mark > 1` 告警**。
**先审计再设计** —— 我还没查 Mac 侧 scheduler 断电后是否自启。归 Seth,排在 T1 之后。

---

## 交给 Minimax 的任务包

### → Minimax-C（挖掘 / 研究）

**C1（高价值,直接对应「试错价值不要丢失」）:对全部 60 条 `experiment_runs` 补算 DSR。**
现在 **dsr 只有 2/60**。S-189 发现 R70 的 1.58 是 72 配置搜索出来的、DSR 0.27 未过 0.95 —— 
**那不是 R70 一个的问题,是 58 条实验从未被折价过。**
没有 DSR,我们分不清"survivor"和"搜出来的运气",**这几个月的挖掘就无法结算。**
工具已备:`src/research/validation/deflated_sharpe.py`（`deflated_sharpe` / `expected_max_sharpe` /
`required_sharpe`,阈值 0.95)。每条要填 `n_trials`（该实验搜索了多少配置)——
**没有 n_trials 的条目标 NULL,不要猜**（I1)。

**C2:`_reports/INDEX.md` 的 16 个 R# 与 `experiment_runs` 的 18 个 `ledger_ref` 对账。**
哪些挖出来了但没进库,哪些进库了但 INDEX 没有。**两边都不是全集,这是 ② 环节的漏。**

**C3:B 类 9 条策略事实,给出可执行的准入/约束形式**（S-84/85 F&G 极性 · S-87 顺周期杠杆 ·
S-112 ADV>$15M 准入 · S-128/129 F 在 TradFi 退化 · S-135 HAR-RV)。
Seth 提供关卡外壳,内容归你。

### → Minimax-B（策略构建）

**B1:dingge 阈值标定。** 顶格阈值继承自 Binance fapi（500–1170%/yr),**实测 HL 全场最高
SYRUP 270%/yr**,所以 40 天只开 2 仓。改成**场所相对**（横截面分位),不是绝对数。
⚠️ 名字不预先挑 —— 按 Jazz 的机制,**拥挤度自己会点名**。

**B2:`cause_proximity.py` 的 出圈 层是不是活的。** 模块七月就建了（`season`:
pre / momentum / stale),Jazz 08-24 关于「出圈抢买后容易又大跌」的观察是对它的细化。
**先查它有没有在跑、`stage` 有没有值,再谈改。**（我上一轮直接提议造新阈值而没 grep,是错的。)

**B3:R70 → 执行端。** 已冻结成可执行规则 `src/research/validation/rules/r70_rule.py`。
PIT 重放实测:70 天里 **55 天被 TIGHTENING 闸门挡住,2 天开火**。
**它不是执行有问题,是在这个 regime 下几乎不开火** —— 要不要接 paper book 是策略判断,归你。

### → Minimax-A（Mac 运维 / 协调)

**A1:`ohlcv_collector` 救活**（你的 task #43,已同意你接)。顺序不能反:先 collector,
再 `realized_return_7d` 回填。

**A2:T1 引擎可用性。** PIT 重放发现 **9 天**（`06-20→06-23`、`07-18→07-22`)
`cis_scores` 有 1450–1566 行、score/grade 100% 覆盖、**五根 pillar 全 NULL**,
source=`railway_t2_hourly`。**T1 掉线时 T2 顶上,写出来的东西看起来完全正常。**
你这边查 T1 为什么掉;我这边让 T2 拒绝写没有 pillar 的行。

**A3:部署后验 `pod_aggregator_nav` / `factor_tilt_nav` 是否真的开始长行。**
写者今天补上了,但**这两本账取数走 `fapi.binance.com`,该 host 从 Railway US 被地理封锁**。
**若仍 0 行,病在数据源不在写入者。** 这是 `VERIFY:` 条目。

**A4:`MINIMAX_SYNC.md` 已 104,785 字符,超 CLAUDE.md 的 80,000 上限。**
>5 天且已结的移去 `MINIMAX_SYNC_ARCHIVE.md`;**仍未结的要在 §IN-FLIGHT 重新提出,不能留在原地**。

**A5:S-号撞车。** S-217 今天被 §SIMULATION-60D 占用,署名同为 Seth —— **有两个 Seth lane
在并行写台账**。`check_ledger_citations.sh` 只挡"引用不存在的号",挡不住"两人写同一个号"。
需要加重复标题检测,归 Seth;协调归你。

---

## 验收（不是"做完了",是可观测的状态)

| 轨 | 判据 |
|---|---|
| T0 | `enforced_fraction` 基线 76 写进 CI 且只升不降;A 类 11 条补齐 |
| T1 | `/internal/vdb-health` **连续 7 天** `overall: flowing` |
| T2 | 跨账本相关矩阵进 `loop_health`,ρ̄ 有值 |
| T3 | 断电重启后 24h 内所有 loop 自愈,无人工介入 |
| C1 | `experiment_runs.dsr` 覆盖 ≥ 50%（`vdb_health` 的门槛已按此设) |

---

## 一句话

**这几个月的试错价值,等于它被强制执行的那一部分。今天是 75%。**
其余 25% 不是"记录不够详细",是**它只被写下来了** —— 而写下来的东西,
在下一个失忆的 session 里和不存在没有区别。
