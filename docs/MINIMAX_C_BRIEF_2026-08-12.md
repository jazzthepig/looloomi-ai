# Minimax-C 任务简报 — 2026-08-12(先入库,再验证)

> Jazz:整段复制给 Minimax-C。
> 权威版本在 `MINIMAX_SYNC.md` §C-INTAKE-2026-08-12(gitignored,Mac 侧同步)。

---

Minimax-C,

R66C 的压测我先不验 —— **不是质疑结果,是我现在验不了**。先把三个我实测到的数字摆出来,
你就知道为什么。这一节在我要求你做任何事之前写,上一轮我们改了共享面才说,让 A 查了
一晚上不相干的代码,那次是我们的流程错。

---

## 一、我实测的三个数字(2026-08-12,live Supabase)

**1. 策略库在系统记录里是空的。**

```
strategy_records (Postgres)          0 行
_data/strategy_records.json (本地)   117 条
.gitignore:16                        _data/
```

策略库的全部内容**既不在系统记录里,也不在版本控制里**。换台机器 checkout,它是空的。

⚠️ **Redis 我够不到。** `strategy:records` 存不存在、TTL 多少,我不知道 —— **请你实测回报**。
如果它带 TTL,这 117 条离消失只差一次驱逐,而这正是 S-105(策略库在 24h TTL 的 Redis key
里待了 12 天)的原样重演。

**2. 那 117 条里,纪律字段命中 0/117。**

`base_rate` · `oos_survival` · `oos_window` · `paper_trade_days` · `deployable_notional_usd`
· `value_added_usd_yr` · `notional_basis` · `deflated_sharpe` · `n_trials` · `pbo` ·
`regime_reported` —— **全部 0/117**。

verdict:`hold` 67 · `refute` 32 · `doctrine` 13 · **`ship` 5**。

**五条 verdict=ship,没有一条带着 SHIP 门槛要求的任何一个字段。**
这些记录**早于**门槛(S-132/S-133 是这周才落的),所以不是谁造假 —— **是它们从没被评过分**。
但结果一样:我们现在无法区分「通过了门槛的 ship」和「门槛存在之前就写着 ship 的字符串」。

**3. `experiment_runs` 43 行,关键列从来没写过。**

```
cost_bps      0/43   ← 一次都没有
dsr           1/43
ledger_ref    5/43
n_obs         1/24   (在 24 条 factory_batch 里)
```

**一个列存在、被显示、从来没被写过** —— 这是我们这周修了四次的同一个形状。
而这次它落在**成本**上:成本可行性是 MECHANISM_SPEC 的 **BINARY 淘汰项**,
43 次实验没有一次记过成本。

---

## 二、所以先入库。两个具体理由,不是手续

1. **我没有可比对象。** 「R66C 比之前好」现在**无法被检验** —— 库里的「之前」没有成本、
   没有样本量、没有 ledger_ref。
2. **证据放在会消失的地方。** 原来在 `/tmp`(macOS 会清);
   `_data/research/r66c_pitch_2026-08-12/` 好一级,但 `_data/` 是 gitignored,
   **而且按新政策它会一直是** —— 不会被系统清掉,但永远不进版本库、不进备份、
   不进任何人的 checkout。六个月后 LP 问「你们当时怎么压的」,答案还是文件没了。
   **所以数据库不是副本,是正本。**

> 顺带:那个目录我这边看到是**空的**,拷贝可能没成功,先确认。

---

## 三、落地位置:三层,不要混

> **⚠️ 政策更新(Jazz,2026-08-12):挖掘出来的策略内容不进 git。**
> 所以下面的表和你可能预期的不一样 —— **持久性不靠 git,靠数据库。**

| 东西 | 放哪 | 为什么 |
|---|---|---|
| 结论 + 方法(`.md`) | **`_data/research/<M-##>/`,gitignored** | 边缘不进版本库 |
| **结构化记录** | **`experiment_runs`** + **`strategy_records`** | ⭐ **这是唯一的持久层** |
| 原始 bootstrap 路径 711 KB | 同上,**但 seed + git sha 写进 `experiment_runs.params`** | 大文件不存,**能重算就不必存** |

**这个政策把入库从「应该做」变成「唯一的机制」。** 之前 MD 进 `docs/` 还能兜底,
现在不进了 —— **所以一条没入库的结论,就是一条不存在的结论。**
它只活在某台机器的某个 gitignored 目录里,换台机器 checkout 就没有了。

第三行是关键:**种子和代码版本记在库里,那 711 KB 就是缓存,删了无所谓;
没记,它就是唯一证据,而它在一个永远不会被备份的目录里。** 差别全在 `params` 那一列。

> **但注意边界:「策略内容」不进 git,「production 接线」必须进。**
> `src/data/signals/beta_core_q_overlay.py` / `beta_core_size.py` 被
> `src/api/main.py` import,`beta_core_q_hook.py` 被 `beta_core_paper.py` import。
> **Railway 从 git 部署 —— 不在 git 里的模块不在服务器上。**
> 如果边缘要离开 git,它以**参数**的形式离开(阈值、cell 表 → Supabase 或 env),
> **不是以 import 目标的形式**。已在 `.gitignore` 里写清楚。

---

## 四、「入对」的定义 —— 最低字段

**`experiment_runs` 每行:** `kind` `hypothesis` `universe` `verdict` `n_obs` `cost_bps`
`window` `params`(含 **seed** + **git sha**)`ledger_ref`

- **`cost_bps` 不能留空。** 零成本就写 `0` 并在 notes 说明。
  **`NULL` 和 `0` 的区别是「没测」和「测了是零」** —— 现在这两个长得一样,而其中一个是淘汰项。
- **`n_obs` 写独立事件数,不是天数。** 933 个重叠日 ≠ 933 个观测。

**`strategy_records` 每条(尤其那 5 条 `ship`):**

| 字段 | 要求 |
|---|---|
| `base_rate` | 因 + 基准率。不是「历史上有效」,是「**为什么**有效、在**多大比例**的情况下有效」 |
| `oos_survival` | ⚠️ **`None` ≠ `False`**。没测写 `None`;写 `False` 是把「未测」记成「已否证」,那比空着更糟,因为它看起来像结论 |
| `oos_window` | 真实留出窗口 `YYYY-MM-DD→YYYY-MM-DD` |
| `paper_trade_days` | SHIP 要 ≥ 60 |
| `deployable_notional_usd` / `value_added_usd_yr` / `notional_basis` | 百分比 alpha 会被竞争掉、且不预测自己(Berk & Green 2004);能持续约十年的是**美元**(Berk & van Binsbergen 2015)。`"assumed"` **不算基准**。⚠️ **ADV 覆盖不全时不要取子集的最小值 —— 那是上界,不是容量** |
| `deflated_sharpe` / `n_trials` | **`n_trials` 要含被丢弃的设定** —— 它是 DSR 的分母。少报它等于自己给自己发合格证 |
| `regime_reported` | 分 regime 报,不要只报聚合 |

门槛实现:`src/data/vector/strategy_schema.py::validate_record()`。
最低可部署规模 `MIN_MEANINGFUL_NOTIONAL_USD = 1_000_000`,**单一来源,别在别处重定义**。

---

## 五、编号:`R66C` 不合规

`R1…R75` 是冻结历史,而 R64–R72 那段已经因为两条 lane 撞号被
`§LEDGER-RECONCILIATION-MAP` 收拾过一次。**在一个已经收拾过的冻结号上加后缀,
等于往同一个地方再加一层歧义。**

按 `docs/R_NUMBERING_CONVENTION.md`(2026-07-23 已批准):**Minimax lane 用 `M-76+`,
forward-only,先占标题再写正文。** 给这次压测一个 `M-##`,MD 文件名和 `ledger_ref` 跟着改。

---

## 六、入库之后我按四条验,顺序不能换

1. **反向对照(先跑这条)。** 一个只在「应该通过」的场景上跑的压力测试,和不跑,
   通过方式相同。**要有一个你构造的、必须失败的场景,而它确实失败了。**
   我这周在 HAR-RV 上连错三次设定,就是靠合成对照才发现的。

2. **那 10,000 条 bootstrap 是怎么抽的。** 如果是对日收益 **IID bootstrap**,
   它会摧毁自相关和波动聚集 —— 而这两者正是回撤的来源。结果必然低估尾部,
   **且低估方向永远是「策略更安全」**。要 **block bootstrap**(块长 ≥ 波动聚集半衰期)
   或 **stationary bootstrap**。
   ⚠️ **这条错了,4 套情景和扇形图全部重跑 —— 请先自查,不要等我验完。**

3. **样本外是不是真样本外。** 参数、阈值、universe 选择,有没有任何一个在测试窗口上
   看过一眼。连同 `n_trials` 一起报。

4. **度量的是账本还是中间量。** S-135:HAR-RV 的**预测**显著更好,而**账本不更好**。
   压测压 ret/DD 和实现回撤,**不是信号的 IC**。

**外加一条方向性的:① 账本是 long-only beta 捕获,基准是「持有面板」,永远不是 0。**
S-136 用**完美预知**测过「在回撤前减仓」:ret/DD 从 0.634 掉到 **0.337**,
**比什么都不做还差 47%** —— 回撤后面跟着反弹。**该预测的是波动,不是回撤**
(完美预知波动有 +39.6% 空间)。如果 R66C 的压力场景是按「避开回撤」设计的,先跟我说。

---

## 七、优先级与回执

| # | 事项 | 优先级 | 期望 |
|---|---|---|---|
| C1 | Redis `strategy:records` 存在性 + TTL 实测回报 | 🔴 P0 | 今天 |
| C2 | 117 条落 `strategy_records`;5 条 `ship` 补齐纪律字段 | 🔴 P0 | 本周 |
| C3 | 补 `experiment_runs` 缺失列;`cost_bps` 起不得为 NULL | 🔴 P0 | 本周 |
| C4 | R66C 改 `M-##`,MD 进 `docs/`,seed + git sha 进 `params` | 🟡 P1 | 入库时 |
| C5 | bootstrap 抽法自查(第六节第 2 条) | 🔴 P0 | 先于我验证 |

**三件请直接说,不要按我写的做:**

1. **Redis 那条我确实不知道** —— 你的实测覆盖我的假设
2. **第四节的字段里,有没有哪一条在你的流程里拿不到** —— 拿不到就说拿不到,
   我改门槛或改采集,**不要填一个看起来像数的值**
3. **第六节第 2 条,如果你本来就用 block bootstrap,说一声我跳过这条**
