# VDB 升级方案 S-360 — 给 Minimax-C 的执行单

> **状态** 2026-09-16 · 作者 Seth · 依据 C 的 VDB 审计报告(诊断采纳,处方重写)
> **新增组件数:0。** 不装 Qdrant,不训 FinGPT LoRA,不上 GraphSAGE / PatchTST,不建新表。
>
> **先读 `docs/SPINE.md`。** 那份文件说明**哪条路是活的**;本文件只说**怎么把断的接上**。
> 本文件里任何一处与 SPINE 冲突,以 SPINE 为准 ——
> 并且按 SPINE §3 法则二,改方向要先改 SPINE 再动代码。

---

## §0 先更正三条,包括我自己昨天说错的

C 的报告和我 9/16 上午给 Jazz 的口头判断里,有几条与库里的实测状态不符。
**在动手前必须更正,否则工单会朝错误的方向执行。**

| 我们以为 | 实测 | 证据 |
|---|---|---|
| `signal_outcomes` 死 136 天,`_outcome_tracker_loop` 每天失败 | **循环是好的。** `signal_journal` 290 行,最新 2026-09-14,待结算 **0** 条,最后一次结算 2026-09-15 | `select count(*) filter (where outcome_30d is null and signal_date < current_date-30) from signal_journal` → `0` |
| `entities`/`decisions` 是唯一没建的空间,要新建 | **已经在跑。** `treasury_entities` 102 行(更新于 9/15)、`treasury_decisions` **893 行**(更新于 9/11) | `src/data/entity/writer.py` 写的是 `treasury_*`,不是 `entities`/`decisions` |
| VDB 缺向量索引 | **有三个 HNSW,全部盖在空东西上** | `entities_vec_hnsw`(1 行)、`asset_embeddings_vec_hnsw`(72 行)、`msv_hnsw`(`vec` 在 582 行上全 NULL) |
| VDB 缺 regime 检索能力 | **库里早就有 `similar_market_states(target_day, k, min_shared)`,现在就能跑** | 见 §1b —— 它不但存在,还和我昨天独立写的 Python 版**犯了同样的两个错** |

我上午那条「P0 = 救活 signal_outcomes」是错的,错因是**我读了我们自己写的注释当现状**。
仓库里 **10 个文件、12 行**注释在断言 `signal_outcomes` 死了 80/122/123/125 天,
`main.py:889` 至今写着「循环活着、每天准时跑、每天失败」。
那句话在写下时是真的,现在不是了,而**没有任何东西会在它变假时改它**。
这正是 C 报告的同一个失效形状,发生在我身上。

---

## §1 真正的根因 —— 一个缺陷,不是五个任务

三次独立排查落在同一个形状上:

```
旧的一半(空/冻结)              活的一半(有数据)             谁在读
─────────────────────────────────────────────────────────────────────────────
signal_outcomes    7743 行      signal_journal   290 行       refresh_signal_edge_map()
  2025-05-03…2026-05-03           2026-05-25…2026-09-14         ← 只读旧的
entities  1 行 / decisions 0     treasury_entities  102 行     entities_vec_hnsw
                                 treasury_decisions 893 行       ← 只索引旧的
market_state_vectors.vec  NULL   .vec_full  582 行有值         msv_hnsw
                                                                 ← 只索引旧的
similar_market_states()          regime_match.py               生产调用者
  无 z 化、无时间排除              两个缺陷都已修                **两个都是 0**
```

**VDB「形式完整、效用几乎为零」的原因不是缺技术,是它读的是每一对里空的那一半**,
而第四对更彻底:两个实现都对、都没人调。

这四对的共同形状是:**旧的那个没有被退役,只是被绕过了。** 绕过不留痕迹,
于是仪表、索引、注释、以及下一个接手的人(包括 C 和我),全都指着旧的那半边。

C 的诊断对,处方错在于:它假设缺口要用新组件填。实测下来,五个空间里
**没有一个的瓶颈是检索能力**。加 Qdrant 是给这三对再添第四个空索引。

### 为什么不加索引(用 planner 自己的回答)

```sql
explain analyze
select symbol, 1-(vec <=> (select vec from asset_embeddings where symbol='BTC'))
from asset_embeddings where vec is not null order by 2 desc limit 5;

  ->  Seq Scan on asset_embeddings   (actual time=0.038..0.082 rows=72)
  Execution Time: 0.365 ms
```

**Postgres 拒绝走已有的 HNSW,选了全表扫描,0.365 毫秒给出精确解。**
HNSW 的全部理由是「几百万行不能扫」。我们是 1 / 72 / 474 / 582 行。
在这个量级索引是**负收益**:要维护、会丢召回、还多一个服务。

### §1b 检索层不但存在,还已经复现了我们刚修过的 bug

```sql
select * from similar_market_states(null, 5, 6);

  d           cosine   shared_dims   n_symbols
  2026-07-07  0.9701   15            75
  2026-07-09  0.9694   15            75
  2026-07-28  0.9677   15            58
  2026-07-31  0.9652   15            58
  2026-07-30  0.9646   15            58
```

这个 RPC **今天就能跑** —— 它读 `vec_full`(jsonb),不读那个全 NULL 的 `vec` 列,
而且用的是**共享维余弦 + `min_shared` 门槛**,正是 §4 存储法则要求的做法。
架构上它是对的,pgvector 从一开始就不是这条链需要的东西。

但它有两个缺陷,**和我昨天独立写的 `regime_match.py` 第一版一模一样**:

1. **没有逐维 z 化** → 0.964–0.970 的窄带,是全正向量未归一的典型签名。
   目标日是 2026-08-05,而这是原始值余弦被单个大量纲维支配的结果。
2. **没有时间排除** → 五条全部落在目标日前四周内(7/07…7/31)。
   **昨天当然像今天,那不是信息。** 我们要的是历史上的相位,不是时间上的邻居。

所以 W3 不是"建检索",是**在两个已存在的实现之间收敛到一个**,并把修好的那一版的
两个修正合并进去。

---

## §2 五张工单

每张都给 **为什么 / 做什么 / 验收 / 不做什么**。验收判据必须是一条能跑出来的查询或命令,
不接受「跑通了」。

---

### W1 — 统一前向记录(P0,其余四张的地基)

**为什么。** `signal_outcomes` 止于 2026-05-03,`signal_journal` 始于 2026-05-25 ——
**两段连续、不重叠、中间 22 天空洞。这是一条被迁移切成两半的记录,不是一张死表加一张活表。**
`refresh_signal_edge_map()` 只读前半段,所以 `signal_edge_map` 那 40 行建立在冻结的一年上,
而活的成绩在另一张表里堆积、无人读取。**没有统一的前向记录,W2–W5 全都无法被判对错。**

列是同一套语义换了名字:`signal_journal.alpha_30d` = `signal_outcomes.alpha`;
`benchmark_return_30d` = `b_ret`;`return_pct_30d` = `a_ret`。

⚠️ **这张单比我第一版写的小得多 —— 视图已经存在。**
我第一版提议新建一个叫 `forward_record` 的视图。**错了**:
`signal_outcomes_unified` 早就建好了(7834 行,带 `era` 列区分 legacy/journal,
`alpha_beta_adj` 在 journal 侧写 NULL 而非 0 —— I1 处理得是对的),
而且 **MEMORY.md 里白纸黑字写着「读 `signal_outcomes_unified`,单读任一表静默丢一半历史」**。
我读过 MEMORY.md,然后提议了同一个东西的第六个名字。
**这就是 `docs/SPINE.md` 要挡住的那件事,发生在写 SPINE 的人身上。**

**真正缺的是两处接线。**

**做什么。**
1. **`refresh_signal_edge_map()` 改读 `signal_outcomes_unified`。**
   它现在直读 `signal_outcomes`,所以 edge_map 那 40 行建立在 2026-05-03 就冻结的数据上。
   这是一处 `create or replace function`,不是新建。
2. **补基准 —— 这才是记录停住的真因。** 实测:
   ```
   signal_journal 已结算 outcome_30d      157 条
     其中缺 benchmark_symbol               66 条   ← 最新到 2026-08-16
     ⇒ 无 benchmark_return_30d ⇒ 无 alpha_30d
     ⇒ 被视图的 where alpha is not null 静默滤掉
   ```
   所以统一记录停在 **2026-07-26**,不是因为追踪器坏了,是因为**基准没被赋值**。
   按 MEMORY.md:**基准 = 等权持有本 panel,不是 0 也不是 BTC**
   (S-103:用 BTC 做基准给每档扣了 2.16pp,t=3.96)。
   **一个没有基准的 OUTPERFORM 根本不是一个断言** —— 它连被证伪的资格都没有。
3. **22 天空洞(2026-05-04…05-24):标注,不要补。** 补一段我们没测过的历史就是造第二个真相。
4. `src/` 里对 `signal_outcomes` / `signal_journal` 的**读取端**全部切到视图;
   **写入端不动**(`outcome_tracker.py` 本来就该写 `signal_journal`)。
   切完按 SPINE 法则一,把这两条从「已知未清偿」表里划掉。

**验收。**
```sql
select era, count(*), min(d), max(d) from signal_outcomes_unified group by era;
-- 期望:journal 那一档的 max(d) 推进到 ≥ 2026-08-16(现在是 2026-07-26)
select count(*) from signal_journal where outcome_30d is not null and benchmark_symbol is null;
-- 期望:0
```
`refresh_signal_edge_map()` 的 `prosrc` 里必须出现 `signal_outcomes_unified`;
跑完后 `signal_edge_map.n` 增加且 `computed_at` 是今天。

**不做什么。** **不要再建一个统一视图。** 已经有了。
不删 `signal_outcomes` 的历史 —— 那 7743 行是我们唯一的一年期真实前向记录,是资产。

---

### W2 — 让 `market_state_writer` 上日程,并补 `vec`

**为什么。** `src/data/vector/market_state_writer.py`(S-245)第 629 行确实在
`supabase_upsert_table("market_state_vectors", ...)`,但**全仓库零个调用者** ——
写者建好了,从没上过日程。所以表停在 2026-08-05(42 天),`vec` 在 582 行上全 NULL,
而 `msv_hnsw` 正盖在这个全空的列上。

**做什么。**
1. 照 `_outcome_tracker_loop`(`src/api/main.py:1095`)的形状把它接进日循环 ——
   **必须含 `_beat(...)` 心跳**,否则重演「循环有了但心跳没接」。
2. `measured_dims` 15 / `dims` 24 的差额要留在 `source_completeness` 里,**不要零填充**
   (§4 存储法则:稀疏向量补 0 再算稠密余弦是错误度量)。

**这张单只做新鲜度,不做 `vec` 回填。** 我第一版写的是"回填 `vec`",错了:
唯一的消费者 `similar_market_states()` 读的是 `vec_full`,**`vec` 列没有任何读者**。
回填它等于给一个没人读的列灌数据,再给一个 planner 不用的索引找存在理由。

**验收。**
```sql
select max(d), count(*) from market_state_vectors;
-- 期望:max(d) = 昨天
```
`loop_beat` 里有对应心跳;**次日再查一次,`max(d)` 必须又前进一天** ——
一次手动回填不算上日程,这是 `signal_outcomes` 那一课的具体形式。

**不做什么。** **`DROP INDEX msv_hnsw`,并把 `market_state_vectors.vec` 列一起删掉。**
582 行全 NULL、零读者、零写者,而它的存在让人以为检索走的是 pgvector ——
实际走的是 `vec_full` 上的 jsonb 共享维余弦。**一个空列加一个空索引,
是一条永远在撒谎的文档。** 同理检查 `entities_vec_hnsw` 是否也该删(见 W4)。

---

### W3 — 相位检索收敛到一个实现,并接进 ⓠ 层

**为什么。** 我们现在有**两个** regime 相似度实现,谁都没在生产里被调用:

| | `similar_market_states()` RPC | `src/data/vector/regime_match.py` |
|---|---|---|
| 数据 | `market_state_vectors.vec_full`,24 维声明 / 15 实测,582 天,停 42 天 | `regime_daily.features`,11 维 CIS,474 天,昨天还在更新 |
| 度量 | 共享维余弦(架构对) | 固定核心维余弦(架构对) |
| z 化 | **无** → 0.964–0.970 窄带 | **有**(S-351 修过) |
| 时间排除 | **无** → 返回目标日前四周 | **有**(`exclude_days=30`) |
| 人工判读 | 无 | **78 天带冥想正文** |
| 生产调用者 | 0 | 0 |

**先选一个,再接线。两个都留着就是第四对「旧的空 + 新的活」。**

⚠️ **这个选择不是 C 的,也不是我的 —— 按 `docs/SPINE.md` §3 法则二,它是方向变更,归 Jazz。**

因为 MEMORY.md 把决策链**指定**为
`market_state_vectors → similar_market_states() → strategy_response`。
那是现行方向。我 S-349/S-351 建 `regime_daily` + `regime_match.py` 时
**没有登记、也没有退役那条链** —— 于是"两个都对、两个都没人用"。
现在要么改方向(登记),要么回到指定的那条(补 z 化和时间排除)。
**不能靠"我建的那个更好"把方向悄悄换掉,那正是这次要根治的行为。**

我的读法(供 Jazz 判断,不是结论):`regime_match` 挂在每天更新的 `regime_daily` 上、
两个缺陷已修、带 78 天人工判读 —— 那是库里算不出来、也买不到的东西。
但 24 维价格/宏观态是否比 11 维 CIS 态更接近"风格",是策略判断,不是工程判断。

**做什么。**
1. **Jazz 拍板后**,退役另一个(RPC 就 `DROP FUNCTION`,Python 就删文件),
   同步更新 SPINE §2 与「已退役」表,并在 `REFUTATION_LEDGER` 记一条。
2. `GET /api/v1/regime/similar?d=<date>&k=5` → 返回 `(hits, diag)`,
   **`diag.n_excluded_incomplete` 必须原样透出** —— 那是覆盖缺口,不是"不像"。
3. 指挥台(`scripts/ops_console.py`)加一格:今天的 top-5 相位 + 当时 regime + 有无人工判读。
4. 登记进 `regime_override_enforcer.DECISION_INPUTS`,让 ⓠ 层的 band 决定
   **在案地**包含"当前像哪段历史"。

**验收。**
- `curl .../api/v1/regime/similar` 返回 5 条,且**没有一条落在目标日 ±30 天内**
  (这一条专门用来挡上面那个时间邻居的 bug 复现)。
- 相似度分布**不在 0.95 以上的窄带里** —— 如果又是 0.96–0.99,说明 z 化没生效。
- 落选的那个实现,`grep` 全仓库为 0 命中。

**不做什么。** 不要为了"更准"去换嵌入模型。这 11(或 15)个维度全是实测量,
**相似度在这里是可解释的,换成学出来的嵌入会把这个优势换掉。**

---

### W4 — `entities.vec` 从 `treasury_entities` 填充

**为什么。** `entities` 1 行、`decisions` 0 行,而 `treasury_entities` 102 行 /
`treasury_decisions` 893 行正在每天更新。`entities_vec_hnsw` 索引着那 1 行。
按 ARCHITECTURE.md,**Entity/Decision 才是最深的那个对象** —— 它是活的,只是向量侧没接。

**做什么。** 从 `treasury_decisions` 为每个 entity 算一个行为向量(持仓净变动的时序特征:
方向、频率、幅度、半衰期 —— `decisions` 表已经有 `direction / magnitude / half_life_d` 这几列
的设计意图),写进 `entities.vec`,并把 `entity_id` 对齐 `treasury_entities`。

**验收。**
```sql
select count(*) filter (where vec is not null) from entities;  -- 期望 ≥ 100
```
**加一次人判读:** 取一个已知实体(例 Strategy),看它的 top-5 近邻是否讲得通
(同为长期增持的财库实体应该聚在一起)。只看 count 不算验收 ——
S-351 的教训就是"有数字"和"数字有意义"是两件事。

⚠️ **检索函数要新建,库里没有。** 现有的只有三个:
`match_asset_embeddings(target, k, class_mode)` / `similar_market_states(target_day, k, min_shared)` /
`refresh_signal_edge_map()`。**没有 `match_entities`** —— 我第一版凭印象写了这个名字,
是我们反复吃亏的那个错(PostgREST 按参数名解析,猜名字会得到 `PGRST202`,
读起来像"没有这个函数",其实是"没有匹配这些参数名的重载")。
新建时**照 `similar_market_states` 的形状**:jsonb 共享维余弦,102 行不需要 HNSW。

**不做什么。** 不上 GraphSAGE。GraphSAGE 需要图,而 `decisions` 表里边的数量是 **0**;
`treasury_decisions` 是实体→资产的二部关系,不是需要图卷积的结构。
**先把向量填上,图的问题等到有边再谈。**
`entities.vec` 填完后同样跑一次 `explain analyze`:102 行几乎必然走 Seq Scan,
**那就把 `entities_vec_hnsw` 也删掉**(与 W2 同一条理由)。

---

### W5 — ⓠ 层的曝险区间与 Jazz 的设计对齐(**需 Jazz 拍板,C 只备料**)

**为什么。** Jazz 的设计是 **−0.5x 到 3x,核心是灵活**。代码里是:

```python
EXPOSURE_BANDS_V1 = {"CRISIS": 0.0, "CONTRACTION": 0.5, "NEUTRAL": 1.0,
                     "EXPANSION": 1.0, "HOT": 1.3}
# v1: only {0.5, 1.0, 1.3} — naked-short disabled (v2 needs borrow-cost model)
```

上限 1.3x,做空关闭。`validate_cap()` 会 raise 掉任何不在这个集合里的值 ——
**所以今天写 3x 会直接抛异常。** 这就是 Jazz 说的「设计被执行变形带偏」,它具体地住在这一个 dict 里。

但 v1 那行注释是有道理的,不是笔误:`v2 needs borrow-cost model`。
**做空的成本模型是 −0.5x 能否成立的前提,不是它的后续。**

**做什么(C 的部分,只是备料)。** 把 v2 的前提备齐,让 3x 和 −0.5x 变成**可选**:
1. 借币/资金费成本序列入库(perp funding 我们已有:①的 24 个名字上等权 funding
   年化 +23.07%,这个数已经量过)。
2. 在 `forward_record`(W1)上做一次条件回测:各 band 在不同 regime 下的实际表现。
3. 输出一张表:`band × regime × 净成本 × 实测 alpha`。

**验收。** 那张表能跑出来,且每格的 `n` 有标注(n 小于 30 的格子必须标出来,不能当结论用)。

**不做什么。** **C 不要自己改 `EXPOSURE_BANDS_V1`。** 曝险区间是策略层决定,属 Jazz;
maxdd 属组合管理层。不同工序,不可越俎代庖。C 交的是让 Jazz 能拍板的证据。

---

## §3 执行顺序与依赖

```
W1 统一前向记录 ────────→ W5 备料(条件回测需要 forward_record)

W3 相位检索选型 ──┬─(若选 RPC)→ W2 msv 上日程  ← 此时 W2 才是前置
                  └─(若选 regime_match)→ W2 降级为独立的清理单

W4 entities.vec ── 独立,可并行
```

**W1 必须先落。** 在一个还不能判断自己对错的系统上叠任何东西,都是叠在未验证之上。

**W3 的选型要先于 W2 的排期。** 如果选 `regime_match`(挂在每天更新的 `regime_daily` 上),
那 `market_state_vectors` 的 42 天陈旧就不再卡住任何人,W2 就只是一张清理单 ——
**先决定谁是真相,再决定给谁续命。反过来做就是给要退役的东西上日程。**

---

## §4 全局禁止项

| 禁止 | 理由(实测) |
|---|---|
| 装 Qdrant | planner 拒绝用我们已有的 HNSW,N 在几百行。再加一个是第四个空索引 |
| FinGPT LoRA | 5 个空间里 4 个的相似度是实测量可表达的;换成学出来的嵌入会丢掉可解释性 |
| GraphSAGE | `decisions` 表边数 = 0。**前提不存在** |
| PatchTST | 那是预测问题,不是检索问题,被夹带进了 VDB 路线图。单独立项,且卡在 W1 |
| 新建任何表 | 已有三对「旧的空 + 新的活」。第四对只会让下一个人再读错一次 |
| 加规则/加校验层去挡上面这些 | 「问题不是那条规则写错了,是想用再加一条规则去修它」 |

**保留 C 报告里的两条:** 诊断「形式完整、效用几乎为零」——对;7 VDB → 2 VDB 的收敛方向——对。

但两条我们都已经写过。`src/data/vector/vdb_health.py`(2026-08-24)开头就是:

> 「每一个都是我自己建完的。任务全部 closed green。
> **我建了这条 loop 的每一级,一级都没让它流动。**」

同一个文件第 160 行:「`similar_market_states()` 的余弦**照样返回一个数**,只是那个数没有意义。」

**三周前我们写下了完整的诊断,然后什么都没改,于是三周后花钱又买了一份同样的诊断。**
这张执行单唯一的意义是打破这个循环 —— 所以 §5 是强制项,不是收尾建议。

---

## §5 每张工单收尾时必须做的一件事

**改掉那条现在已经不成立的注释。**

仓库里 11 处注释在抱怨 `signal_outcomes` 死了 80/122/123/125 天。它们写下时是真的。
今天 `signal_journal` 待结算 0 条,而那些注释一个字没变 —— 它们把我(以及可能是 C)
误导到了一个不存在的 P0 上,花掉了半天。

**一条描述状态的注释,如果没有任何东西会在状态改变时改它,它就是一颗延时错误。**
写下一条教训和应用一条教训是两件事;让一条教训在过期时还在发言,是第三件事。

工单完成的定义包含:把它推翻掉的那些注释改掉,或者给它们加上测量日期。
