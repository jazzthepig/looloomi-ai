# SPINE.md — 应用通路的结构基准

> **这份文件回答一个问题:一个能力,现在走哪条路?**
> 每个 agent(Seth / Austin / Minimax-A / Minimax-C / 未来的失忆的我)在重组记忆时读它,
> 用它对齐方向。**它不记录"是什么"(那是 ARCHITECTURE.md),不记录"现在几行"(那是
> PROJECT_STATE.md),只记录"哪条是活的、哪条已退役"。**
>
> **§2 的表由 `tests/test_spine_is_current.py` 校验 —— 它不是散文,写错会红。**

---

## §1 为什么需要这份文件

2026-09-16 一次排查,在**五个**地方找到同一个形状:

```
signal_outcomes 7743 行  ←→ signal_journal 290 行     → 早有 signal_outcomes_unified 视图,消费者不读
entities 1 行/decisions 0 ←→ treasury_* 102/893 行     → HNSW 索引着空的那个
market_state_vectors.vec ←→ .vec_full 582 行有值       → HNSW 索引着 NULL 列
similar_market_states()  ←→ regime_match.py            → 两个都对,两个都零调用
```

共同形状:**旧的那条路从来没有被退役,只是被绕过了。**

绕过不留痕迹。于是仪表、索引、注释、和下一个接手的 agent,全都指着已经没有数据的那半边。
**这不是谁不小心,是没有一个地方规定"哪条是活的"** —— 每个 agent 重组记忆时,
从它碰巧读到的那个压缩指针各自重建方向,于是各自建了一条新的、都对的、都没人用的路。

最后一条实例发生在写这份文件的当天:MEMORY.md 里白纸黑字写着
「读 `signal_outcomes_unified`,单读任一表静默丢一半历史」,而我读完之后,
仍然提议新建一个叫 `forward_record` 的视图 —— **同一个东西的第六个名字。**

**所以这份文件的判据不是"写得对",是"能不能挡住这件事再发生一次"。**

---

## §2 主干 —— 六段,每段一条活路

| # | 段 | 唯一活实现 | 消费者 | 状态 |
|---|---|---|---|---|
| 1 | 测量·价格 | `ohlcv_daily`(基表)→ `ohlcv_daily_canonical`(去重+量纲归一) | 23 处读基表 · `outcome_tracker` 读视图 | 🟢 **S-361 已修**(视图曾停 39 天) |
| 2 | 测量·CIS | `cis_scores` ← Mac T1 → `cis_push` → Redis → `cis_provider` | `/api/v1/cis/universe` | 🟢 |
| 3 | 几何·资产 | `asset_embeddings`(27 维,72 行) | `match_asset_embeddings()` | 🟢 |
| 4 | 几何·市场态 | `market_state_vectors.vec_full`(24 声明 / 15 实测,582 行) | `similar_market_states()` | 🟡 **S-361 写者已上日程**;剩余陈旧来自源(binance_hist 停 8 天) |
| 5a | 检索·**宏观**相位 | `similar_market_states()`(价格/宏观 15 实测维) | `/api/v1/regime/similar` | 🟡 **S-362 已修 z 化与排邻并接线**;底表停 42 天(见第 4 段) |
| 5b | 检索·**微观**相位 | `regime_match`(CIS 支柱 11 维 + 78 天人工判读) | `/api/v1/regime/similar` | 🟢 **S-362 已接线**;底表每日更新 |
| 6 | 判断·ⓠ | `beta_core_q_overlay`(乘数语义)| `beta_core_nav_q` 26 行,日更 | 🟡 **活的**;`regime_override_enforcer` 是**语义不同的旧实现**,见「已退役」;封顶 1.3x 与设计的 −0.5…3.3x 不符(归 Jazz) |
| 7 | 建仓·① | `beta_core_nav`(产品本体,兼所有 book 的基准) | 全部 book 的「超额」 | 🟢 |
| 7b | 组合·gross 预算 | **尚无实现** —— 相关性状态 → gross,见 §5 第 7 条 | — | 🔴 缺段 |
| 8 | 反馈 | `signal_outcomes_unified`(视图) | `refresh_signal_edge_map()` | 🟡 **S-365 已接**,双基准并存;journal 段仍薄(91 行有 alpha) |
| 9 | **实体/决策内核** | `entities` / `decisions`(ARCHITECTURE 的中央对象) | `entity_store.py` 在写 | 🔴 写者活着,落地 1 行 / **0 行** |

**2026-09-17 的通路状态 —— 早上只有第 7 段是通的:**

```
1 价格 🟢 → 2 CIS 🟢 → 3 资产 🟢 → 4 市场态 🟡(源断) → 5a 🟡 / 5b 🟢
  → 6 ⓠ 🟡(活的,乘数语义) → 7 建仓 🟢 → 8 反馈 🟡(双基准) → 9 内核 🔴
                                          7b 组合 gross 预算 🔴(缺段)
```

**主链已经连上了。** 剩下两个红都不是断线,是**结构性缺口**:
7b 从来没建(而它是 3.3x 的前提);第 9 段写者活着但 `decisions` 落地 0 行。

⚠️ **这段散文 CI 查不到。** 校验器只解析 §2 的表格 ——
它一度落后两批而全绿,补了反方向检查后才抓住表里的过期 🔴,
**但表格下面这段话仍然只能靠人改**。写下它的时候就知道它会过期,所以:
**更新 §2 表格时,连这段一起改;两者不一致时以表格为准。**

### 已退役 / 不得再被读写

| 退役的 | 由谁取代 | 备注 |
|---|---|---|
| `signal_outcomes`(直读) | `signal_outcomes_unified` | 原表保留,是唯一的一年期真实记录,**但只能经视图读** |
| `signal_journal`(直读) | `signal_outcomes_unified` | 同上 |
| `market_state_vectors.vec` `[DB]` | `.vec_full` | 582 行全 NULL,零读者;连同 `msv_hnsw` 一起删 |
| `regime_override_enforcer.apply_regime_override` | `beta_core_q_overlay`(乘数语义) | **不是"没人用所以该接上",是语义不同而且会抵消风控** —— 见下 |

> **⛔ 2026-09-17 第 6 段第二次判错 —— 而这次差点把一个风控关掉。**
> 我一小时前写「没有任何账本把 ⓠ 的 cap 施加到权重上」,**错了**:
> `beta_core_q_overlay` 第 6 行 `gross_total[t] = beta_capture_gross[t] × q_override[t]`
> —— cap 一直在被施加,`beta_core_nav_q` 26 行日更。**我又一次从 import 数推出了一个系统事实。**
>
> 两个实现对同一组数字的解释不同:
>
> ```
> enforcer  scaled = w * cap; 再归一化  → 最终 gross **等于** cap      ← 目标水平
> overlay   gross_total = baseline_gross × q_override → gross **乘以** cap  ← 乘数
> ```
>
> 只有基线 gross 恰好 1.0 时两者才一致。实测:`beta_core_nav.gross` **33 行里 16 行 ≠ 1.0**,
> 而 `vol_target_scalar` **33/33 行都 ≠ 1.0**(0.87–1.30)。
> 基线 0.5 遇 cap 1.3:enforcer 给 **1.3**,overlay 给 **0.65** —— **两倍暴露差**。
> 更要命的是 cap=1.0 时 enforcer 会把 gross 强行拉回 1.0,**抵消波动率目标,33/33 天**。
>
> CLAUDE.md 写的是「③ **beta multiplier**(time exposure 0.7x–1.3x)」—— 乘数。
> **所以活的那个是对的,enforcer 零导入是好事不是缺陷。**
> 我差一点"把它接上" —— 那会静默关掉一个风控。
> **「没人用」不等于「该接上」;先问它做的是不是同一件事。**

> **⛔ 2026-09-16 撤回一条:`entities` / `decisions` 曾被我列在这张表里,是错的。**
> Minimax-B 查出 `src/data/vector/entity_store.py:83/:104` **正在 POST**
> `/rest/v1/entities` 与 `/rest/v1/decisions` —— 那是**活跃写入端**,不是旧路。
> 我把**领域源**(`treasury_*` = Strategy 等 119 家公司的财库持仓)
> 当成了**内核主存**(`entities`/`decisions` = ARCHITECTURE.md 的中央对象)的替代品。
> 两者字段就不同:`decisions` 有 `direction / magnitude / half_life_d / targets / provenance`
> 这些**抽象出来的决策量**,`treasury_decisions` 只有 `holding_net_change / decision_type / coin_id`
> 这些**事件原貌**。**treasury 是喂给内核的一个源,不是内核的后继。**
> 正确位置见 §2 第 9 段。Minimax-C 的 Phase 0 也独立指出了同一点。
>
> **这条错在这份文件里,比错在别处更贵** —— SPINE 是方向基准,
> 一条错的退役注记会让下一个 agent 去删一个还活着的内核。
> 它能被查出来,是因为 B 的活是「逐处判定」而不是「照着执行」。

### 已知未清偿(`VERIFY:` 登记)

退役是个过程。**下面每一条都是"还在读旧路"的实测事实,登记在此才允许存在。**
CI 校验的是**这张表与代码一致**,不是"代码已经干净" ——
一个要求世界完美的检查会被关掉,一个要求文档诚实的检查不会。

登记一条要写:名字 · 还在读它的位置 · 谁负责 · `VERIFY:` 怎样算清偿。

**状态(B-S360-2 清偿后,2026-09-16):**

| 旧路 | 还在读它的代码 | 负责 | VERIFY | **2026-09-16 状态** |
|---|---|---|---|---|
| `signal_outcomes` | `h3_edge_map_backfill.py`(研究回填,合法) · `producer_freshness.py:302` SQL 监控(合法) · `refresh_signal_edge_map()`(**不合法**) | C / W1 | `refresh_signal_edge_map()` 的 `prosrc` 里出现 `signal_outcomes_unified` | 🟡 **C-S360-1 未结**(unified view 0 reader in src/,需 C 切线) |
| `signal_journal` | `routers/signals.py:716` (`get_signal_journal`) · `producer_freshness.py:304` SQL(合法) · `outcome_tracker.py:49` (**写入端,合法**) · `cis.py:33` · `mac_writes.py:65` (**写入端,合法**) | C / W1 | 读取端全部切视图;写入端不变 | 🟡 **`get_signal_journal` 仍直读基表**(应切 unified) |
| `market_state_vectors.vec` `[DB]` | 无代码读者(`market_state.py:359` 仅注释) | C / W2 | `select count(*) from information_schema.columns where table_name='market_state_vectors' and column_name='vec'` → 0 | 🟡 DB 验证待跑:`select` 列应返 0 行 |
| `entities` / `decisions` | `src/data/vector/entity_store.py:83` POST `/rest/v1/entities` · `:104` POST `/rest/v1/decisions` · `watch_census.py:158` SQL freshness 监控 | **Seth(已裁定)** | ~~退役~~ **撤回** —— B 判对了:`entity_store.py` 是内核的活跃写入端,`treasury_*` 是领域源不是后继。已移出「已退役」,建为 §2 **第 9 段**。新判据不再是"清偿",是 **`select count(*) from decisions` > 0** | ✅ **B-S360-2 结**(2026-09-16 采纳 B 的 (a) 方案)。**余下的是第 9 段本身的断点**:写者活着、`decisions` 落地 0 行 —— 见 §5 第 8 条 |

**`[DB]` 标记的行,CI 不做代码 grep,只要求这一行写明一条可跑的 SQL 判据。**

为什么要这个标记:`market_state_vectors.vec` 是**某张表上的一个列**,
而它的裸名 `vec` 在 `src/` 里是整个向量子系统的通用局部变量名
(`vec = []` / `for sym, vec in ...`,90+ 处)。
用裸名 grep 会**因为错误的理由变绿** —— 看起来在守卫,实际上什么都没查。

这是本次会话里第三次「检查因错误的理由通过」(前两次:S-342 的 grep 命中了测试自己的名字;
`test_production_can_write` 查的是旧契约的拼写而不是行为)。
**一个因错误理由变绿的检查,比红的更坏** —— 红的会被修,绿的会被信任。

**`signal_outcomes_unified`:S-365 起由 `refresh_signal_edge_map()` 读(DB 函数)。**
`src/` 侧仍为 0 —— `get_signal_journal` 还直读基表,见上表。
它曾经「建好了、MEMORY.md 记了、没有一行代码读」,那是本文件存在的直接理由。

---

## §3 两条法则

### 法则一:一个能力只能有一条活路

**先判"是不是同一个能力"** —— 判错了,这条法则就会把有用的角度当重复删掉。

判据:**两个东西能不能合理地给出不同答案,而那个分歧本身携带信息?**

- **能** ⇒ 是两个**角度**,各自成段,各自一条活路。分歧要有合成规则(不能下游随便挑)。
- **不能**(本该一致却不一致)⇒ 是**重复**,分歧只是 bug,按下面三步退役一个。

我 2026-09-16 判错过一次:把第 5a/5b 当成"同一个能力的两个实现",推出"二选一"。
实测同一天、同一方法(z 化 + 排邻 30 天)跑两边:

```
目标 2026-08-05
  宏观(价格 15 维)   2025-08-10 … 08-19   EASING / RISK_ON    0.595–0.641
  微观(CIS  11 维)   2026-06-06 … 07-04   Tightening          0.743–0.929
                      ↑ 零重叠,不同年份,不同 regime
```

**Jazz 的判断是对的,而且近乎正交。** 详见 §4。

新建一条路径**必须**同时做三件事,缺一不可:

1. 把旧的从 §2 移进「已退役」,并写明取代关系
2. 把旧的真正**关掉**(`DROP FUNCTION` / 删文件 / 删列),不是留着不用
3. 把消费者切到新的 —— **切换不完成,就不算新建完成**

**绕行是允许的,不退役不行。** 如果一时不能退役(别的 lane 在用、要等窗口),
在 PROJECT_STATE 的 OPEN RISKS 留一条带 `VERIFY:` 的记录。
**绕行不留痕 = 把故障传给下一个失忆的自己。**

### 法则二:结构变更要先改这份文件,再动代码

§2 的表是**方向**。改方向是 Jazz 的决定,不是执行细节:

- 加一段、删一段、换某段的唯一活实现 → **先在这里提修订,拿到确认再动手**
- 段内怎么实现 → agent 自己决定,不用问

这条是给我自己写的。S-349/S-351 我建了 `regime_daily` + `regime_match.py`,
**没有登记** —— 于是它和 MEMORY.md 指定的那条链
(`market_state_vectors → similar_market_states() → strategy_response`)
并存了三周,两个都对,两个都没人用。**登记的缺失是问题,建它本身不是。**

---

## §4 第 5 段是两个角度,不是两个实现(Jazz 2026-09-16 定)

> 「两个都留着。价格/宏观态和 CIS 支柱微观,是不同 angle。」

**这是方向裁定,已生效。** 第 5 段拆成 5a / 5b,各自一条活路,各自照法则一管。

| | **5a 宏观相位** | **5b 微观相位** |
|---|---|---|
| 问的问题 | 现在的**市场背景**像历史哪段 | 现在的**横截面内部**像历史哪段 |
| 数据 | `market_state_vectors.vec_full` | `regime_daily.features` |
| 维度 | 24 声明 / 15 实测(价格+宏观) | 11(CIS 支柱) |
| 覆盖 | 582 天,**停 42 天** | 474 天,每日更新 |
| z 化 | **有**(S-362 补) | 有(S-351) |
| 排邻 | **有**(S-362 补,30 天) | 有(30 天) |
| 人工判读 | 无 | **78 天冥想正文** |

两边架构本来就一致:jsonb 共享维余弦,不走 pgvector,符合 §4 存储法则(few+sparse)。
5a 曾缺 z 化和排邻 —— **那是 bug,不是角度差异**,S-362 已照 5b 的方式补上。

### 它们近乎正交 —— 实测,不是推断

同一天、同一方法(z 化 + 排邻 30 天),两边跑出来:

```
目标 2026-08-05
  5a 宏观   2025-08-10  2025-08-11  2025-08-14  2025-08-18  2025-08-19
            EASING / RISK_ON                        相似度 0.595–0.641
  5b 微观   2026-06-06  2026-06-07  2026-06-19  2026-06-20  2026-07-04
            Tightening                              相似度 0.743–0.929
```

**零重叠。一个指向一年前的宽松,一个指向两个月前的紧缩。**
如果它们给的是同一批日子,那才该按法则一删掉一个。

### 合成规则(ⓠ 层怎么用两个答案)

下游拿到两个排名,**不能随便挑一个,也不能把相似度平均或相加**。

⚠️ **跨角度的相似度数值不可比** —— 维度数不同(15 vs 11)、语料不同,
0.64 在宏观里是最像的,在微观里排不进前五。
把它们平均,就是 S-351 那个错误升了一维:**不同维度数的余弦不是同一个量。**
合成只能在**排名和一致性**上做,不能在原始数值上做。

所以:

- **两角度指向同一段历史** ⇒ 相位清晰 ⇒ 可以按那段当时跑得好的风格加大暴露
- **两角度分歧**(如上例:宏观说去年宽松、微观说两月前紧缩)⇒ **宏观背景与内部横截面脱钩**
  ⇒ 相位不清晰 ⇒ 这本身是降暴露 / 等待的信号

**分歧是信息,不是噪音。** 丢掉分歧去挑一个,等于把这一段最有价值的输出扔了 ——
而那正是 Jazz 说的「换着法子匹配当时跑得好的风格并做一定预判」里"预判"的来源。

---

## §5 当前断点

按依赖排序。细节在 `docs/VDB_UPGRADE_S360.md`,状态在 PROJECT_STATE。

0. **第 1 段(价格)— 最底层,先看这条。**

   ```
   ohlcv_daily            基表   552,394 行   ← 生产里 23 处直读
   ohlcv_daily_canonical  视图   485,352 行   ← 只有 outcome_tracker 一处读
                          差额    67,042 行
   ```

   视图做的是 `DISTINCT ON (symbol, trade_date)` 按源优先级去重,
   **并且按源归一 volume 单位**(`coingecko → usd_notional`,`eodhd/yfinance → shares`)。

   所以直读基表意味着:**同一个 (symbol, date) 可能出现多次,且 volume 不同量纲。**
   这正是 Rule 3b 警告过的「两条看起来同名、实则不同的序列」,
   而它在**最底层** —— 上面每一段都站在它上面。

   ⚠️ **不要据此断言那 23 处全错。** 写入端本来就该写基表;
   某些读取端可能自带去重。要做的是**逐处判定**并登记,不是一次性替换。
   这条排在最前不是因为最急,是因为**判错了会让上面所有段的结论都不可信**。

   ### ⛔ 2026-09-16 P0:上面这段的方向是反的 —— 视图才是断的那个

   ```
   ohlcv_daily            基表   最新 2026-09-16  ← 今天有数据
   ohlcv_daily_canonical  视图   最新 2026-08-08  ← 停 39 天
   ```

   **视图不会自己陈旧** —— 它在读取时计算。机制查明:
   近 7 天写入的 **1,770 行,`asset_id` 全是 NULL**,而视图
   `join assets a on a.asset_id = o.asset_id` 是 **INNER JOIN**,于是近期行被整批丢掉。

   断点是同时发生的 —— 所有源在同一周停止写 `asset_id`:

   ```
   binance_hist        最后一次带 asset_id  2026-08-08
   coingecko           最后一次带 asset_id  2026-08-07
   eodhd               最后一次带 asset_id  2026-08-06
   coingecko_pro_ohlc  从来没写过           (9,263 行 NULL)
   hyperliquid         从来没写过           (2,655 行 NULL)
   ```

   **所以那 23 处直读基表的代码拿到的是今天的价格,而唯一"守规矩"读视图的
   `outcome_tracker` 拿到的是 39 天前的。** 按本文件原来的建议把 23 处迁到视图,
   等于把生产整体迁到一个停更的源上 —— **一个方向基准把所有人指向了断掉的那一边。**

   Minimax-B 被要求「逐处判定」而不是「照着迁」,所以他在动 `vault/tick.py` 前
   停下来问覆盖 —— **那个停顿是这条 P0 被发现的唯一原因。**

   ### ✅ 2026-09-16 已修(S-361,`scripts/supabase_s361_canonical_p0.sql`)

   三步,顺序不能反:

   1. **回填** 18,310 / 18,460 行 —— canonical 立刻回到 2026-09-16,近 7 天标的数 **0 → 235**
   2. **视图 `LEFT JOIN` + `coalesce(a.class, o.asset_class)`**
      ⚠️ 只改 LEFT JOIN 不够:行回来了但 `asset_class` 变 NULL,而下游普遍写
      `where asset_class='Crypto'` —— **丢失会从 join 移到 filter,同样静默。**
      基表自己就有这一列且 100% 填着,所以连降级都不需要,原来只是没用它。
   3. **写入触发器**解析 `asset_id`(实测 `src/` 里没有任何写入端设过它 ——
      修某一个没用,第六个还会忘)。解析不出来留 NULL,由第 2 步承接:
      **解析不出来的会出现,不会消失。**

   剩 150 行 / 10 个 symbol 在 `assets` 里没条目(Hyperliquid 系,K 前缀是 1000x)。
   它们现在**出现在视图里**而不是消失;是否建 `assets` 条目属于准入,
   不该由一个 JOIN 顺手决定。

   守卫:`tests/test_canonical_keeps_up_with_base.py`(已接 preflight)查的是**后果**
   —— 视图落后基表 >1 天即红,`asset_class` 出现 NULL 即红。
   上面三步都是机制,机制会被下一次重构删掉;**后果查得住,机制换了也拦得住。**

   **现在可以把读取端迁到 canonical 了** —— 但仍照 §5.0.1 逐处判定,不要批量替换。

### §5.0.1 第 1 段 — 23 处直读基表的逐处判定(B-S360-1,Seth, 2026-09-16)

> **判据:** ① 它是不是读收盘价给收益/打标?② 有没有 `source=eq.X` 显式单源过滤?
> ③ 是不是 freshness/coverage/by-source 审计?**写入端写基表是合法的,
> 不在表里**(SPINE §3 法则一)。下面 23 处全部在 `src/` 内,
> grep `ohlcv_daily` 命中,**不含注释/docstring/纯字面量**。

#### A 类 — 写入端(6 处,保持写基表)

| # | 位置 | 写入形态 | 判据 |
|---|---|---|---|
| A1 | `src/api/routers/ohlcv.py:65` | POST upsert `on_conflict=symbol,trade_date,source` | 写基表是必要的,视图无主键可 upsert |
| A2 | `src/api/routers/ohlcv.py:350` | POST upsert(批量回填) | 同 A1 |
| A3 | `src/api/routers/ohlcv.py:386` | POST upsert(每日采集) | 同 A1 |
| A4 | `src/data/market/cg_pro_backfill.py:477` | `supabase_upsert_table("ohlcv_daily", ..., on_conflict=ON_CONFLICT)` | 同 A1 |
| A5 | `src/data/market/hyperliquid_collector.py:390` | `supabase_insert_table("ohlcv_daily", all_rows[i:i+2000])` | 同 A1 |
| A6 | `src/data/market/deep_panel_collector.py:398` | `supabase_insert_table("ohlcv_daily", all_rows[i:i+2000])` | 同 A1 |

#### B 类 — 读收盘价用于收益 / 打标(3 处)

| # | 位置 | 读的是哪个 | 该读哪个 | 判据 |
|---|---|---|---|---|
| B1 | `src/data/signals/outcome_tracker.py:238` | `ohlcv_daily_canonical` ✓ | `ohlcv_daily_canonical` | **唯一合规读者。** 视图像素优先级 = `native venue > aggregator > free`,与 `price_route.EXECUTION_VENUE=hyperliquid` 对齐;entry/exit 双腿同一来源,不触发 `UNMEASURABLE` 分支。**保持现状** |
| B2 | `src/data/vault/tick.py:103` | `ohlcv_daily` 过滤 `source=eq.binance_hist` | **改 `ohlcv_daily_canonical`** | vault 打标走的是 ① 的本子 —— `price_route.py` 已定 tradeable 必须 HL 优先,**binance_hist 是次优**。同一 symbol 在 vault NAV 里用 binance_hist、在 outcome_tracker 里用 canonical,意味着 `signal_outcomes.ret = vault_mark − entry` 这条链的两个端点**用了不同的源**。**判错会让 vault NAV 与信号回路用不同的价格**(S-193 那个洞) |
| B3 | `src/research/validation/s113_revisit_s108_s109_on_687asset.py:132` | `ohlcv_daily` 过滤 `source=eq.binance_hist`,`select=close` | **保持 `ohlcv_daily` + `source=eq.binance_hist`** | 研究员**显式选择** binance_hist 来构建 687-asset survivorship-free panel —— 跨标的同源才能做 N_eff / breadth 的横截面比较。canonical 视图会按优先级切换源,**会破坏面板同源性**。这是研究方法学的选择,不是 bug。判据:`source=eq.X` 是显式单源约束 → 基表 |

#### C 类 — 显式单源约束的读(4 处,保持读基表)

| # | 位置 | 用途 | 判据 |
|---|---|---|---|
| C1 | `src/data/market/coverage.py:178` | `group by symbol, source`,跨源覆盖审计 | 按源分别计数是审计目的,视图会折叠源、审计失真 |
| C2 | `src/data/market/source_freshness.py:287,291,294` | by-source freshness / 覆盖率 | 同 C1 |
| C3 | `src/data/vector/market_state_writer.py:288` | `source=eq.{PANEL_SOURCE}` (binance_hist) 单源 panel | 横截面统计量(breadth / corr / dispersion)在**同一组成员**上才可比 — 显式单源是设计,不是漏判 |
| C4 | `src/data/vector/market_state_writer.py:546` | 候选起点扫描,`source=eq.{source}` | 同 C3 |

#### D 类 — Freshness / 审计探针(2 处,保持读基表)

| # | 位置 | 用途 | 判据 |
|---|---|---|---|
| D1 | `src/api/store.py:922` (`supabase_ohlcv_daily_freshness()`) | `select=trade_date, order=desc, limit=1` 算 `age_seconds` | 这是 §BETA-METRIC-AGG 的 ship gate,**测的是写入者的存活**(`max(trade_date)`)。视图的 DISTINCT ON 会把多源折叠,反而把「这个写入者死了但那个还活」掩盖 —— 与 S-251 的「一个还活的写入者掩护 260 个死掉的」同形。**基表是必要的** |
| D2 | `src/data/signals/forward_record_keeper.py:368` (`check_pit_lag()`) | `select=trade_date, recorded_at, source=eq.coingecko_pro_ohlc` 算 PIT 滞后 | 需要 `recorded_at` 这个写入时间戳,**视图不带它**(视图只挑一行 close,不暴露 `recorded_at`)。基表 |

#### E 类 — 注释 / 字符串字面量 / 文档(8 处,不构成读)

| 位置 | 形式 |
|---|---|
| `src/api/routers/ohlcv.py:4, 197, 273, 415` | docstring 描述库的作用 |
| `src/api/routers/admin.py:5, 44, 271` | docstring / freshness 表清单 |
| `src/api/main.py:352, 1599, 2669, 2675, 2713, 2806, 2916` | docstring / verdict_note 字符串 |
| `src/api/routers/signals.py:1116, 1131, 1166, 1186, 1188` | 端点 docstring / response payload 字段名 |
| `src/api/loop_health.py:128, 143` | freshness 字段名 |
| `src/api/store.py:859, 861, 894, 909, 955` | freshness 函数 docstring + 错误码 |
| `src/api/main.py:2772, 2799` | response payload 字段名 |
| `src/mcp/cometcloud_mcp.py:1022, 1027, 1046` | MCP 工具 docstring |

`src/research/data/ohlcv_local.py` 8 处 + `r95_panel.py` 2 处 + `r96_panel.py` 2 处 + `simulate_paper_trade.py` 1 处 + `test_ohlcv_local_smoke.py` 1 处 = 14 处**全部读本地 SQLite**(`/tmp/cometcloud_data/ohlcv.db`),**不读 Supabase** — 与本表无关,SPINE 的 23 处是 Supabase 端计数。

#### F 类 — 校验/对账读(1 处,保持读基表)

| # | 位置 | 用途 | 判据 |
|---|---|---|---|
| F1 | `src/data/market/cg_pro_backfill.py:370` (`_verify_mapping()`) | 拿库里的 `coingecko` 收盘对照新写入的 `coingecko_pro_ohlc` 行,**同源对照** | 校验语义要求读与写同源,视图不适用 |

#### 总结

| 类型 | 处数 | 处理 |
|---|---|---|
| A 写入端 | 6 | **保持基表**(写必须写基表) |
| B 收益/打标 | 3 | **B1 已合规 · B2 应改 canonical · B3 显式单源,保持** |
| C 显式单源 | 4 | **保持基表**(审计/同源面板的硬约束) |
| D Freshness | 2 | **保持基表**(测写入者存活 + `recorded_at`) |
| E 注释/字面 | 8 | **非读,不处理** |
| F 校验 | 1 | **保持基表**(同源对照) |

**实际待改:1 处 —— `vault/tick.py:103` 由 `ohlcv_daily` 改 `ohlcv_daily_canonical`。**
其余 22 处**不是 bug**,只是它们在用基表 —— 而那些用法对它们的目的来说是对的。

1. **第 8 段(反馈)** — `signal_outcomes_unified` 停在 2026-07-26。
   追踪器是好的(待结算 0 条),断的是**基准**:157 条已结算里 **66 条没有
   `benchmark_symbol`** ⇒ 没有 `benchmark_return_30d` ⇒ 没有 `alpha_30d`
   ⇒ 被视图的 `where alpha is not null` 静默滤掉。
   **而按 MEMORY.md,基准 = 等权持有本 panel;没有基准的 OUTPERFORM 根本不是一个断言。**
   并且 `refresh_signal_edge_map()` 到现在还在直读 `signal_outcomes`,不读视图。

2. **第 4 段(市场态)** — ✅ **S-361 已上日程**(`_market_state_loop`,
   `main.py`,日频,含 `_beat`,已注册 `liveness` 48h)。
   写者 S-245 就存在且能写,**全仓库零个调用者** —— 又一次
   「建了这条 loop 的每一级,一级都没让它流动」。

   心跳**不经 `_classify`**:`RecomputeResult` 已经把「拒绝」(地板没过,没写,
   系统健康)和「失败」(写出错了)分开了,让分类器去猜一个已经分好的东西,
   是把 S-220 那条信息再丢一次。

   **剩余陈旧不在写者,在源。** 实测各源对地板(`MIN_DAYS=400` / `MIN_SYMBOLS=20`
   / `MIN_COVERAGE=0.90`)的能力:

   ```
   binance_hist        1709 天  262 标的  127 达标  停  8 天   ✓ 唯一过地板的
   coingecko           1706 天   25 标的    5 达标  停  0 天   ✗ 标的太少
   yfinance            1119 天   33 标的   33 达标  停 90 天   ✓ 但已死
   eodhd                289 天   33 标的   33 达标  停  1 天   ✗ 天数不够
   coingecko_pro_ohlc    72 天  203 标的  196 达标  停  0 天   ✗ 天数不够(还需约 330 天)
   hyperliquid           15 天  177 标的  177 达标  停 24 天   ✗
   ```

   所以部署后第 4 段会从停 42 天 → 停 8 天,**并在源恢复时自动追上**
   (全量重算是幂等的)。⚠️ `market_state_writer.py:104` 那条
   「binance_hist 天花板 343 天(M-91)」的注释**已过期** —— 实测 1709 天。

3. **binance_hist 停 8 天(2026-09-08 起)** — 现在它是第 4 段唯一的可用源,
   所以这 8 天直接变成第 4 段的陈旧度。`_deep_panel_loop` 已调度(`main.py:443`),
   `deep_panel_collector.py:59` 的注释停在 "262 个符号 (2026-09-08)" ——
   **正是数据停止那天**。心跳在 Redis(`loops:beat`),沙箱读不到,需线上查。
   归 Seth(Sense 段,Rule 3b)。

3. **第 5a 段(宏观相位)** — `similar_market_states()` 零调用者,且缺 z 化与排邻。
   实测未修时返回 0.964–0.970 窄带、五条全落在目标日前四周 ——
   **返回的是时间上的邻居,不是历史上的相位。** 照 5b 已修好的做法补。

4. **第 5b 段(微观相位)** — `regime_match` 零调用者。方法已验证(§4),差的只是接线。

5. **两段的合成规则**(§4 末)要在 ⓠ 层落地:按排名一致性用,**不许平均相似度数值**。

7. **第 7b 段(组合 gross 预算)— 这一段我们根本没有,而它是 3.3x 的前提。**

   Jazz 2026-09-16:「这是策略本位。叠加到策略风格矢量里再应用整个 portfolio
   就完全不一样了,就不是裸跑了。」**台账里所有否定杠杆的结论都是单腿裸跑的测试**
   (R41 的 3× 裸 MR −84.74%、S-87「杠杆只缩放风险」、挖矿成本 OOS IC 归零)。
   R41 自己的判词就写着「headline edge is refuted; **the structural allocation is kept**」。

   实测(三本活账本,51 天重叠):等权组合日波动 0.508% vs 单腿均值 0.729%,
   **比值 0.696** ⇒ 只用三本,同等风险下 gross 已可到 1.44x;① 与三本均**负相关**。
   **3.3x 组合 gross ≈ 2.3 倍单腿波动,与「3x 裸跑」不是同一个风险对象。**

   但按**面板收益**(外生)分段:压力天 ρ 从 0.43 升到 0.68,组合/单腿从 0.725 退到 0.810
   —— **分散在最需要的时候缩水**(n=5,迹象非结论)。

   所以缺的不是一个数字,是一段:**`gross_budget = f(相位, 实测相关性状态)`**,
   相关性收敛时自动收、发散时放开。它的输入正是第 5a/5b 段。
   **这就是为什么 VDB 不是锦上添花 —— 它是 3.3x 这个决定能否成立的前置条件。**

8. **第 9 段(实体/决策内核)** — 写者活着,产出近乎为零。
   `entity_store.py:83/:104` 在 POST `/rest/v1/entities` 和 `/rest/v1/decisions`,
   而 `entities` **1 行**、`decisions` **0 行**。
   **这不是"没建",是"建了、在跑、不落地"** —— S-334 那一类(写者返回 False 被吞)。
   先查写入返回,不要先怀疑数据源。`write_log`(S-352)就是为这个建的,去读它。

   与它相邻的 `treasury_entities` 102 行 / `treasury_decisions` 893 行是**领域源**,
   不是它的后继(见「已退役」表下面那条撤回)。**源是活的,内核是空的** ——
   所以缺的是 `treasury_* → entities/decisions` 的抽象那一跳:
   把 `holding_net_change / decision_type` 提炼成 `direction / magnitude / half_life_d`。

9. **第 6 段(ⓠ 层)** — `regime_override_enforcer` 在 `src/` 里**零个真实导入**。
   **S-366 查清了为什么:没有任何账本把 ⓠ 的 cap 施加到权重上。**
   `assign_band_hysteresis` 负责定档(在 `m_wo_q_o1`),enforcer 负责**施加** ——
   而 ⓠ 每天定出一个 cap、写进 `/tmp/.../regime_track.csv`(docstring 称其
   "authoritative local copy"),**Railway 上每次部署就清空**,一天好几次。
   决定在做,产出没有落脚处。

   **S-366 已接的那一半:** `beta_core_size.regime_band(vdb_distance)` 早就写好,
   而**传真值的调用方只有测试,生产传 None** —— 于是 sizing 每天落在
   「我不知道」那一档,**看起来和正常工作一模一样**(S-122:默认值越接近多数类
   越查不出)。现已把 5b 的相位距离填进 `beta_core_nav_q.vdb_distance`:
   25/26 行,band 分布 1=16 / 2=8 / 3=1(此前 band3×26)。

   **仍未做的两件:**(a) ⓠ 的每日决定要有持久归宿(不能是 `/tmp`);
   (b) 新行的 `vdb_distance` 要在写入时自动算,现在只回填了历史。

   唯一一处出现在 `fusion_paper_regime_track.py` 的 docstring 里,是一句描述,不是一次调用。
   **Jazz 说 ⓠ 是四层之上最重要的一层,而它现在没有接到任何东西上。**

   两件事要分开做,不要合成一件:
   - **接线**(C 的活):让 ⓠ 层真的被调用,并把第 5 段的输出登记进 `DECISION_INPUTS`。
   - **改区间**(Jazz 的活):`EXPOSURE_BANDS_V1` 现在封顶 1.3x、禁止做空,
     与设计的 −0.5…3x 差 2.3 倍区间。v1 注释写明 `v2 needs borrow-cost model` ——
     **做空成本模型是 −0.5x 能否成立的前提,不是它的后续。**
     C 交的是让 Jazz 能拍板的证据(见 VDB 方案 W5),**不自己改那个 dict**。
     曝险区间属策略层,maxdd 属组合管理层,不同工序。

9. **B-S360-2 清偿后的 DB 端清理**(代码已清,DB 未清):
   - `entities` / `decisions` 两表行数 = 0 → `DROP TABLE entities CASCADE;` + `DROP TABLE decisions CASCADE;`
     `entities_vec_hnsw` 索引由 `CASCADE` 自动覆盖。
   - `market_state_vectors.vec` 列是否还在:
     `select count(*) from information_schema.columns where table_name='market_state_vectors' and column_name='vec'` → 若 1,`ALTER TABLE market_state_vectors DROP COLUMN vec;`
   - 这两条都不在「已知未清偿」表里(代码不再读),但 DB 端的真清理
     **需要 Supabase console 直跑 SQL**,由 Minimax-C 拍板。
     ⚠️ **DROP 之前先 SELECT 验证两表 0 行 + 1 行无意义**,避免误删有数据的旧表。
     这是 C-W2 + C-W4 的收尾动作,**不归 Seth 做**(Rule 3)。

---

## §6 这份文件自己的防腐

**一条描述状态的注释,如果没有任何东西会在状态改变时改它,它就是一颗延时错误。**

实测:仓库里 10 个文件、12 行注释在断言 `signal_outcomes` 死了 80/122/123/125 天。
每一条在写下时都是真的。今天全部是假的。它们今天把我误导到了一个不存在的 P0 上。

所以 §2 的两张表由 `tests/test_spine_is_current.py` 校验:

- 「已退役」栏里的每个名字,在 `src/` 里必须**零命中**(注释和本文件除外)
- 「唯一活实现」栏里的每个名字,在 `src/` 里必须**至少一个消费者**
- 🟢 标记的段,**不允许**零消费者

**这份文件写错会让 preflight 红。** 它因此不能变成散文。
