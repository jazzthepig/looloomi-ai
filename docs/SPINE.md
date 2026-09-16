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
| 1 | 测量·价格 | `ohlcv_daily_canonical`(入口收敛到 Seth lane,Rule 3b) | `outcome_tracker` **只此一处** | 🟡 生产里 23 处直读基表 `ohlcv_daily` |
| 2 | 测量·CIS | `cis_scores` ← Mac T1 → `cis_push` → Redis → `cis_provider` | `/api/v1/cis/universe` | 🟢 |
| 3 | 几何·资产 | `asset_embeddings`(27 维,72 行) | `match_asset_embeddings()` | 🟢 |
| 4 | 几何·市场态 | `market_state_vectors.vec_full`(24 声明 / 15 实测,582 行) | `similar_market_states()` | 🔴 停 42 天 |
| 5 | 检索·相位 | `similar_market_states()` | **无** | 🔴 零调用者 |
| 6 | 判断·ⓠ | `regime_override_enforcer`(`EXPOSURE_BANDS_V1`) | **无** | 🔴 零导入(唯一那处在 docstring 里);且封顶 1.3x,与设计的 −0.5…3x 不符 |
| 7 | 建仓·① | `beta_core_nav`(产品本体,兼所有 book 的基准) | 全部 book 的「超额」 | 🟢 |
| 8 | 反馈 | `signal_outcomes_unified`(视图) | `refresh_signal_edge_map()` **← 没接** | 🔴 停 2026-07-26 |

**🔴 的四段是连着的,这就是"没有应用通路"的准确位置:**

```
第4段 停42天 → 第5段 零调用 → 第6段 零导入 → 第7段 建仓 → 第8段 停7/26
   市场态断         检索断         ⓠ层断        (只有这段活)      反馈断
```

第 4 段停了 ⇒ 第 5 段即使修好也在读 42 天前的世界 ⇒ 第 6 段拿不到"当前像哪段历史"
⇒ 第 8 段收不回判据 ⇒ **没有任何东西能告诉我们第 6 段的决定是对是错。**

**中间四段全断,只有第 7 段(建仓)是通的** —— 这正是现在的实际状态:
一个「因子-regime 策略 paper trade 跟踪器」。不是 VDB 没用起来,
是**除了建仓那一段,整条通路就没有连过**。VDB 在第 5 段,两头都不通,
一个两端断开的中间件,内部再完整,效用必然为零。

`src/data/signals/forward_record_keeper.py` 的 docstring 把这件事说得最准:

> **「Building the thing feels like finishing it, and a scheduler disagrees.」**

### 已退役 / 不得再被读写

| 退役的 | 由谁取代 | 备注 |
|---|---|---|
| `signal_outcomes`(直读) | `signal_outcomes_unified` | 原表保留,是唯一的一年期真实记录,**但只能经视图读** |
| `signal_journal`(直读) | `signal_outcomes_unified` | 同上 |
| `entities` / `decisions` | `treasury_entities` / `treasury_decisions` | 空表待删,先删 `entities_vec_hnsw` |
| `market_state_vectors.vec` `[DB]` | `.vec_full` | 582 行全 NULL,零读者;连同 `msv_hnsw` 一起删 |

### 已知未清偿(`VERIFY:` 登记)

退役是个过程。**下面每一条都是"还在读旧路"的实测事实,登记在此才允许存在。**
CI 校验的是**这张表与代码一致**,不是"代码已经干净" ——
一个要求世界完美的检查会被关掉,一个要求文档诚实的检查不会。

登记一条要写:名字 · 还在读它的位置 · 谁负责 · `VERIFY:` 怎样算清偿。

| 旧路 | 还在读它的代码 | 负责 | VERIFY |
|---|---|---|---|
| `signal_outcomes` | `h3_edge_map_backfill.py`(研究回填,合法) · `producer_freshness.py`(监控,合法) · `refresh_signal_edge_map()`(**不合法**) | C / W1 | `refresh_signal_edge_map()` 的 `prosrc` 里出现 `signal_outcomes_unified` |
| `signal_journal` | `routers/signals.py` · `routers/admin.py` · `outcome_tracker.py`(**写入端,合法**) | C / W1 | 读取端全部切视图;写入端不变 |
| `entities` / `decisions` | `entity/writer.py` · `entity/collect.py` · `watch_census.py` | C / W4 | 两表行数 = 0 且 `entities_vec_hnsw` 已 drop |
| `market_state_vectors.vec` `[DB]` | 无代码读者 | C / W2 | `select count(*) from information_schema.columns where table_name='market_state_vectors' and column_name='vec'` → 0 |

**`[DB]` 标记的行,CI 不做代码 grep,只要求这一行写明一条可跑的 SQL 判据。**

为什么要这个标记:`market_state_vectors.vec` 是**某张表上的一个列**,
而它的裸名 `vec` 在 `src/` 里是整个向量子系统的通用局部变量名
(`vec = []` / `for sym, vec in ...`,90+ 处)。
用裸名 grep 会**因为错误的理由变绿** —— 看起来在守卫,实际上什么都没查。

这是本次会话里第三次「检查因错误的理由通过」(前两次:S-342 的 grep 命中了测试自己的名字;
`test_production_can_write` 查的是旧契约的拼写而不是行为)。
**一个因错误理由变绿的检查,比红的更坏** —— 红的会被修,绿的会被信任。

**`signal_outcomes_unified` 当前 `src/` 代码命中数 = 0。**
视图建好了、MEMORY.md 记了、没有一行代码读它 —— 这是本文件存在的直接理由。

---

## §3 两条法则

### 法则一:一个能力只能有一条活路

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

这条是给我自己写的。S-349/S-351 我建了 `regime_daily` + `regime_match.py` ——
一个新的第 5 段实现,**没有登记,也没有退役 MEMORY.md 里写明的那条决策链**
(`market_state_vectors → similar_market_states() → strategy_response`)。
结果就是今天的第四对:两个都对,两个都没人用。

---

## §4 待决:第 4/5 段用哪个几何

这是当前**唯一**的开放方向问题,需要 Jazz 拍板,C 不要自己选:

| | 现行(MEMORY.md 指定) | 候选(S-349/S-351 新建) |
|---|---|---|
| 数据 | `market_state_vectors.vec_full` | `regime_daily.features` |
| 维度 | 24 声明 / 15 实测(价格+宏观) | 11(CIS 支柱) |
| 覆盖 | 582 天,**停 42 天** | 474 天,**昨天还在更新** |
| 度量 | 共享维余弦(架构对) | 固定核心维余弦(架构对) |
| z 化 | **无** → 实测 0.964–0.970 窄带 | 有(S-351 修过) |
| 时间排除 | **无** → 实测返回目标日前四周 | 有(30 天) |
| 人工判读 | 无 | **78 天冥想正文** |

两边的**架构都是对的** —— 都是 jsonb 共享维余弦,都没用 pgvector,符合 §4 存储法则
(few + sparse 不走 HNSW)。差别在**输入**:价格/宏观态 vs CIS 支柱态。

选定之后,另一个按法则一**退役**。两个都留着就是第五对。

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

1. **第 8 段(反馈)** — `signal_outcomes_unified` 停在 2026-07-26。
   追踪器是好的(待结算 0 条),断的是**基准**:157 条已结算里 **66 条没有
   `benchmark_symbol`** ⇒ 没有 `benchmark_return_30d` ⇒ 没有 `alpha_30d`
   ⇒ 被视图的 `where alpha is not null` 静默滤掉。
   **而按 MEMORY.md,基准 = 等权持有本 panel;没有基准的 OUTPERFORM 根本不是一个断言。**
   并且 `refresh_signal_edge_map()` 到现在还在直读 `signal_outcomes`,不读视图。

2. **第 4 段(市场态)** — `market_state_writer.py` 存在且能写(S-245,第 629 行),
   **全仓库零个调用者**,从没上过日程。

3. **第 5 段(检索)** — 待 §4 决定。

4. **第 6 段(ⓠ 层)** — `regime_override_enforcer` 在 `src/` 里**零个真实导入**:
   唯一一处出现在 `fusion_paper_regime_track.py` 的 docstring 里,是一句描述,不是一次调用。
   **Jazz 说 ⓠ 是四层之上最重要的一层,而它现在没有接到任何东西上。**

   两件事要分开做,不要合成一件:
   - **接线**(C 的活):让 ⓠ 层真的被调用,并把第 5 段的输出登记进 `DECISION_INPUTS`。
   - **改区间**(Jazz 的活):`EXPOSURE_BANDS_V1` 现在封顶 1.3x、禁止做空,
     与设计的 −0.5…3x 差 2.3 倍区间。v1 注释写明 `v2 needs borrow-cost model` ——
     **做空成本模型是 −0.5x 能否成立的前提,不是它的后续。**
     C 交的是让 Jazz 能拍板的证据(见 VDB 方案 W5),**不自己改那个 dict**。
     曝险区间属策略层,maxdd 属组合管理层,不同工序。

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
