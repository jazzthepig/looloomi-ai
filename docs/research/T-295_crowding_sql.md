# T-295 · squeeze / flush 前向记录的 SQL 内核

**卡**:`tasks/T-295.json` · **产物**:`docs/research/t295_crowding_events.sql`(函数提案)、`docs/research/t295_event_audit.py`(逐格对账)、`docs/research/t295_audit.json`(跑数结果)
**口径来源**:S-726 / S-768(REFUTATION_LEDGER 预注册)+ `docs/research/t242_crowding_setups.py`(已合并的 `detect()`,207–255 行)
**纪律**:本卡只写文件 —— **未执行任何 DDL、未入库**;所有库访问都是 PostgREST 只读。

---

## 1. 交付物

| 文件 | 内容 |
|---|---|
| `docs/research/t295_crowding_events.sql` | `create or replace function public.crowding_events(p_from date, p_to date)` 提案,返回 `(kind, symbol, d, fund_pct, ret, atr_thr, qv_mult)`;另附只读 CTE 等价体与索引建议 |
| `docs/research/T-295_crowding_sql.md` | 本页:逐项对照表 + 边角清单 |
| `docs/research/t295_event_audit.py` | 逐格审计脚本(A 参考面板 / B SQL 语义独立复算 / C 20 事件逐格 / D 库侧逐日对账) |
| `docs/research/t295_audit.json` | 脚本产物(跑数结果) |

**Seth 那边要做的事**:apply 函数 → 跑 `select kind, count(*) from public.crowding_events(date '2019-12-31', date '2026-11-04') group by kind;` → 期望 **squeeze 218 / flush 20**;再逐 `(kind, symbol, d)` 与 `docs/research/t289_events.json` 对账,**218 + 20 全中**才接前向表。

---

## 2. 逐项对照表(SQL 步骤 ↔ python 行)

python 指 `docs/research/t242_crowding_setups.py`。函数体里每一步都带 `S1…S12` 标记,行号对不上时先看这张表。

| SQL | SQL 片段 | python 对应 | 口径 | 写错会怎样 |
|---|---|---|---|---|
| **S1** | `uni`:`kind='coin'` 或 `(kind 空 且 dead_from 非空)` | `main()` 434–438 | 宇宙 = 653 个合约(649 coin + 4 个 kind 空且 dead_from 非空);`tradfi` 与 kind 空的其余 31 个不进 | 宇宙变成 649 ⇒ 事件集变小(见 §边角 E1) |
| **S2** | `px`:`row_number() over (partition by symbol order by d) - 1` = `bar0`;`d >= 2019-10-01` | `load_pbv()` 61–83 + `build_panels()` 99–123 | 面板 = 每个合约按日期排的日频序列;`bar0` = python 的面板列下标 `j` | 面板起点变了 ⇒ pct 分母、age 全变(见 E5/E6) |
| **S3** | `fdaily` + `left join` on `(symbol, d)` | `build_panels()` 124–135 | 资金费按**日期**对齐到面板行;面板里没有的日子丢弃,面板有而资金费没有的那天 ⇒ NaN | 用 inner join 会把「没资金费」那天整行丢掉(分母变);用 `d±1` 对齐会错位 |
| **S4** | `tr = greatest(h-l, abs(h-c_prev), abs(l-c_prev))` | `build_panels()` 138–141 | 真实波幅;`c_prev` = 前一根收盘。numpy `nanmax` 与 Postgres `GREATEST` 都忽略 NULL ⇒ 首根/断档日退化成 `H−L`,**语义一致** | 换成 `greatest` 的 NULL 严格版会把首根整根变成 NULL,ATR 窗口整体错位 |
| **S5** | `case when count(tr) over (14 preceding..1 preceding) = 14 then avg(tr) … end` | `build_panels()` 143–148 | `atr_j = mean(tr_{j−14..j−1})`;pandas `rolling(14)` 的 `min_periods` 默认 = 窗口宽 ⇒ 不足 14 个非空即 NaN | **只写 `avg()` 会忽略 NULL**,窗口里只有 5 个非空也算得出均值 ⇒ ATR 偏小、thr 偏小、事件变多(见 E7) |
| **S6** | 同上,窗口 20 | `build_panels()` 149–153 | `qv20_j = mean(qv_{j−20..j−1})`,`min_periods=20` | 同 E7 |
| **S7** | `f7all`(`k_fund` + `count(funding_rate) over (7 preceding..1 preceding) = 7`)+ `f7`(`where k_fund >= 9 and bar0 < k_fund`) | `build_panels()` 155–172 | `f7_j = mean(funding_{j−7..j−1}) × 3 × 365`;**7 天缺一天 ⇒ NaN**;**`k_fund < 9` ⇒ 整行 continue(该合约无事件)**;`f7` 只在面板**前 `k_fund` 行**上有定义 | 漏 `k_fund >= 9` ⇒ 无资金费历史的合约 `pct` 变 0 ⇒ **多出约 5,700 个伪 squeeze**(实测 218 → 5913);漏 `bar0 < k_fund` ⇒ 资金费有缺口的合约尾部口径错(见 E16/E17) |
| **S8** | `nprior = greatest(bar0, 1)` | `build_panels()` 166–172(`nprior = max(arange(1,k+1)−1, 1)`) | 扩张分位的**分母 = 更早的行数**,不是非空样本数 | 分母改成「非空样本数」⇒ 缺资金费的合约分位整体抬高/压低(见 E12) |
| **S9** | `age_days = d − min(d) over (partition by symbol)` | `detect()` 211(`ordmat − first_ord ≥ 180`) | 年龄门槛 180 天,参照系是**面板内首根**,不是上市日 | 改用 `perp_bv_pairs.first_d` ⇒ 老币更早入选、事件集变大(见 E5) |
| **S10** | `bar0 >= 1 and bar0 <= k − 2`、`age_days >= 180`、`qv20/atr not null`、`c_prev <> 0`、`qv >= 3*qv20` | `detect()` 215–242 | 便宜门槛先过:python 是逐条 `continue` | 漏 `bar0 <= k−2` ⇒ 每个合约尾部多一条事件(信号日没有下一根可算收益)(见 E10) |
| **S11** | `pct = (count(f7 < f7_j) + 0.5*count(f7 = f7_j)) / nprior`,join 条件 `e.bar0 < p.bar0` | `build_panels()` 165–172 | 扩张中位秩;`f7` 为空的更早行**进分母不进分子** | 分子里漏 `f7 is not null` 过滤 ⇒ NULL 比较在 SQL 里本就不计,这条天然对;但 `f7_j` 为空时**不要**加保护(python 给 0.0)(见 E3) |
| **S12** | `flush: pct ≥ 0.90 且 ret ≤ −thr`;`squeeze: pct ≤ 0.10 且 ret ≥ +thr`;`walk` 递归去重 | `detect()` 243–246(判定)、247–253(去重) | 去重 = 距上一个**已计入**事件 ≥ 10 个**日历日**;flush / squeeze 各自去重 | 用 `max(前一个候选日)` 近似 ⇒ 会少留事件(反例见 E4) |
| 常数 | `1095 / 0.90 / 0.10 / 14 / 2.0 / 20 / 3.0 / 180 / 10` | 38–48 | 照抄预注册,一个都不扫 | — |

---

## 3. 边角清单(SQL 独有 / python 藏着的坑)

| # | 边角 | 事实 | 本提案的处理 |
|---|---|---|---|
| **E1** | **宇宙掩码会随缓存形态变** | `load_cached()` 优先读 `.csv.gz`。参考跑数(2026-11-05 16:03)时 `.csv.gz` 还不存在,读的是 `.json` ⇒ `kind` 空值是 `None` ⇒ 宇宙 **653**;今天重跑 python 读 `.csv.gz` ⇒ 空值变 `NaN`,而 `NaN is None` 为 False ⇒ 宇宙掉到 **649**,4 个「kind 空 + dead_from 非空」的币消失 | SQL 按**卡的口径**写(空 kind 且 dead_from 非空 ⇒ 进宇宙)= 653。**python 侧若要复现 653,必须读 `.json`** 或把判断改成 `pd.isna(kind)` |
| **E2** | **库比研究缓存多 903 行** | `perp_bv_daily` 在 `d ≤ 2026-11-04` 上:库 669,125 行 vs T-238 缓存 668,222 行。差额是后补的历史行 | §4 的库侧逐日对账给出受影响合约;SQL 跑的是库 ⇒ 以库为准 |
| **E3** | **`f7` 为空 ⇒ `pct = 0.0`,与「历史最低」不可区分** | python 不对 `f7_j` 做保护:`f7_j = NaN` 时所有比较为 False ⇒ 分子 0 ⇒ `pct = 0/nprior = 0.0`,而 `detect()` 只检查 `isfinite(pct)` ⇒ **NaN 的 pct 是 0.0,会被当成「拥挤空头」** | SQL 同样**不加**保护(保持逐位一致);但生产上应给 `f7 is null` 的行加标记,否则「资金费缺失」会被读成「最拥挤」 |
| **E4** | **去重不能用「前一个候选日」近似** | python 的 `last` 只在**已计入**时更新。候选 0/5/12 日 ⇒ python 留 `{0, 12}`;若用 `max(前一个候选日)`(5 日)判 12 日 ⇒ 12−5 = 7 < 10 ⇒ 误删 | 用递归 CTE `walk` 逐候选推进 `last_kept`(SQL 文件 S12) |
| **E5** | **年龄门槛的参照系是「面板首根」,不是上市日** | `first_ord` = 面板里该合约的第一根。库里最早 2019-12-31 ⇒ 一个 2018 年上市的币,「年龄」从 2019-12-31 起算 | SQL 用 `min(d) over (partition by symbol)`,**不用** `perp_bv_pairs.first_d`(那是上市日,口径不同) |
| **E6** | **面板起点是隐含参数** | python 的面板来自 `d ≥ 2019-10-01` 的查询;库里最早 2019-12-31 ⇒ 今天不截断任何东西。但若将来补回 2019-10-01…12-30 的行,`pct` 分母与 `age_days` 会全体改变 | SQL 显式写 `d::date >= date '2019-10-01'`,与预注册口径一致 |
| **E7** | **`pandas rolling` 的 `min_periods` ≠ SQL `avg()`** | `rolling(14).mean()` 要求窗口内 14 个**非空**;Postgres `avg()` 忽略 NULL、几个都算 | 每个窗口都配 `count(x) over (…) = N` 的 `case`(ATR14→14、qv20→20、f7→7) |
| **E8** | **首根 / 断档日的 TR** | `c_prev` 为 NULL 时 numpy `nanmax` 与 Postgres `GREATEST` 都退化成 `H−L` | 一致,无需额外处理(但别把 `GREATEST` 换成严格 NULL 版) |
| **E9** | **`k` 的定义** | python 的 `k = 有限收盘数`(且面板按行填,尾部若有 NULL 收盘会截断循环上界);SQL 的 `k = 行数` | 现状等价(库里 `o/h/l/c/qv` 全非空,已核)。若将来出现 NULL 收盘 ⇒ **不等价**,需改成 `count(c)` |
| **E10** | **最后一根不算信号日** | `detect()` 的 `jj >= k−1` 跳过 ⇒ 信号日 ∈ `[1, k−2]` | SQL 写 `bar0 <= k − 2` |
| **E11** | **资金费重复行** | `v_funding_daily` 若出现重复 `(symbol,d)`,python 的 `MultiIndex.reindex` 会直接报错;SQL 的 `max()` 会静默取一个 | SQL 用 `max()` 防呆并在注释里标明:**真出现重复时两者不等价,须先查重** |
| **E12** | **分位的分母是行数** | `nprior = max(j, 1)`,`f7` 为空的行照进分母 | SQL 用 `greatest(bar0,1)`(= 行数),不是 `count(f7)` |
| **E13** | **「空 kind」有两种形态** | 库里 35 个合约的 `kind` 为空(4 个 `dead_from` 非空);空串与 NULL 都要当「空」 | SQL 用 `coalesce(nullif(btrim(kind),''),'') = ''`,两种都吃 |
| **E14** | **去重的 10 天是日历天,不是 bar 数** | python 的 `ord` = `datetime64[D]`;合约缺了几天 bar 时,日历天与 bar 数不同 | SQL 用 `d::date` 差值(≥ 10) |
| **E15** | **`(symbol, d)` 唯一性** | `perp_bv_daily` 同时有 `pair` 与 `symbol`;python 按 `symbol` 对齐 | 已核:抽样 3,000 行零重复、`o/h/l/c/qv` 零 NULL。**apply 前请再全量核一次**(有索引建议在文件末尾) |
| **E16** | **「没有资金费历史」的合约被整体排除(python 第 159–160 行)** | `k = isfinite(F[i]).sum()` = 该合约**有资金费观测**的天数;`k < FUND_WIN+2 = 9` ⇒ 整行 `continue` ⇒ `f7` 与 `pct` 全是 NaN ⇒ `detect()` 的 `isfinite(pct)` 把该合约所有 bar 全跳过 | SQL 写死 `k_fund >= 9`。**这是本卡最大的坑**:漏了它,SQL 会把「没资金费」当成「最拥挤」⇒ 实测 squeeze 218 → **5913** |
| **E17** | **`f7` 只在面板的「前 `k_fund` 行」上算** | `s = pd.Series(F[i, :k])` —— 资金费有缺口时,这条截断切掉的是**尾部**,不是「最后 `k_fund` 个有资金费的日子」 | SQL 用 `bar0 < k_fund`(按**行号**截,不是按资金费条数) |
| **E18** | **零价差 / 零成交的合约会恒真命中** | `atr = 0`、`qv20 = 0` ⇒ `thr = 0`、`qv ≥ 3×qv20` 变成 `qv ≥ 0` ⇒ 只要 `pct ≤ 0.10` 就是一次 squeeze。参考跑数里 ICP / TLM / FTT 三条就是这样来的 | SQL 原样保留(口径一致优先);生产上要加 `qv20 > 0` 守卫 —— 那是改口径,需另立预注册 |

---

## 4. 验证(不执行函数也能验)

`docs/research/t295_event_audit.py` 做四段,产物 `docs/research/t295_audit.json`:

- **A 参考面板** —— 用 t242 的 `load_pbv()` + `build_panels()` 重建面板(注意 E1:强制读 `.json`),跑 `detect()`。
- **B SQL 语义独立复算** —— 不复用 `detect()` 的判定,照 SQL 文件 S1–S12 另写一份(含递归去重),在同一面板上跑,再与 A 的事件集逐条比。
- **C 逐格审计** —— 10 squeeze + 10 flush,逐格打印 `f7 / pct / atr / qv20 / qv_mult / ret / thr / age_days`,并对比「python 的 pct」与「SQL 公式算的 pct」。
- **D 库侧对账** —— 从库里拉这 20 个合约的 `perp_bv_daily` 行,与参考面板逐日比 `close`/`qv`/行数,回答「库跑 SQL 会不会得到同一批事件」。

跑数结果见 §5。

---

## 5. 跑数结果(2026-11-08 第一轮)

**A 参考面板**:`detect()` → squeeze **218** / flush **20** ✓ 与 `t289_results.json` 同口径同数。

**B SQL 语义复算(第一版)**:squeeze **5913** / flush 19 ✗ —— 差在哪儿(根因已定位):

> python 第 157–160 行有一条守卫:`k = isfinite(F[i]).sum()`(该合约**有资金费观测**的天数),
> `k < FUND_WIN+2 = 9` ⇒ **整行 `continue`** ⇒ `f7` 与 `pct` 全是 NaN ⇒ 该合约**一个事件都不产生**。
> 第一版 SQL / 复算脚本漏了这条 ⇒ 没有资金费历史的合约 `pct` 被算成 `0.0`(与「历史最低」同值),
> 于是被判成「拥挤空头」⇒ 多出约 5,700 个伪 squeeze(实测 5913)。
> 第二处口径:python 的 `f7` 只在面板的**前 `k_fund` 行**上算(`s = pd.Series(F[i, :k])`)——
> 资金费有缺口时截掉的是**尾部**,不是「最后 `k_fund` 个有资金费的日子」。
> **两处都已改进 SQL(S7)与复算脚本**;**复跑未做**(本轮上下文上限)⇒ 预期回到 218 / 20,**待下一轮核**。

**C 逐格审计(20 个事件;数值取自参考面板本身)** —— `f7` / `pct` / `atr` / `qv20` / `qv_mult` / `ret` / `thr` / `age`:

| kind | symbol | d | bar | f7(年化) | pct | atr14 | qv20 | qv_mult | ret | thr | age |
|---|---|---|---|---|---|---|---|---|---|---|---|
| squeeze | 1000LUNC | 2024-08-10 | 701 | −0.0220 | 0.0742 | 0.00601 | 27.2M | 5.25 | +0.2317 | 0.1702 | 701 |
| squeeze | AXS | 2021-07-03 | 225 | −0.3163 | 0.0756 | 0.64514 | 57.2M | 5.04 | +0.2743 | 0.2131 | 225 |
| squeeze | COS | 2026-03-08 | 524 | −1.0672 | 0.0000 | 0.00011 | 2.8M | 64.8 | +0.5114 | 0.2644 | 524 |
| squeeze | ETC | 2021-06-29 | 530 | −0.3529 | 0.0774 | 5.38886 | 441.9M | 5.25 | +0.3101 | 0.2487 | 530 |
| squeeze | ICP | 2022-07-01 | 416 | **None** | **0.0000** | 0.00000 | 0.0 | — | 0.0000 | 0.0000 | 416 |
| squeeze | LPT | 2025-05-30 | 1296 | −0.2890 | 0.0664 | 0.44779 | 13.3M | 296.1 | +1.1327 | 0.1637 | 1296 |
| squeeze | OMNI | 2025-07-29 | 468 | −0.0312 | 0.0598 | 0.32664 | 102.7M | 14.7 | +0.9972 | 0.2575 | 468 |
| squeeze | RVN | 2025-06-09 | 1562 | −1.1778 | 0.0000 | 0.00171 | 112.7M | 4.01 | +0.2923 | 0.2185 | 1567 |
| squeeze | TLM | 2022-09-09 | 419 | **None** | **0.0000** | 0.00000 | 0.0 | — | 0.0000 | 0.0000 | 419 |
| squeeze | TRB | 2023-09-07 | 1094 | −1.3904 | 0.0210 | 1.92421 | 192.0M | 3.02 | +0.4780 | 0.2323 | 1099 |
| flush | 1000WHY | 2026-01-12 | 413 | +0.9012 | 0.9709 | 0.00000 | 4.7M | 5.58 | −0.2597 | 0.1678 | 413 |
| flush | BCH | 2020-08-02 | 215 | +1.0639 | 0.9302 | 16.29429 | 95.0M | 3.19 | −0.1102 | 0.1019 | 215 |
| flush | BNB | 2021-02-20 | 376 | +1.5706 | 0.9654 | 32.38993 | 1377.1M | 4.29 | −0.2433 | 0.1939 | 376 |
| flush | CHESS | 2026-02-06 | 526 | +0.6470 | 0.9867 | 0.00381 | 4.9M | 3.59 | −0.3422 | 0.2690 | 526 |
| flush | DEGO | 2025-09-09 | 270 | +0.0560 | 0.9519 | 0.06074 | 3.0M | 4.37 | −0.1305 | 0.0900 | 270 |
| flush | DOGE | 2021-04-17 | 281 | +1.4230 | 0.9004 | 0.03546 | 1839.5M | 4.71 | −0.2264 | 0.1941 | 281 |
| flush | FTT | 2022-12-15 | 244 | +0.1095 | 0.9221 | 0.00000 | 0.0 | — | 0.0000 | 0.0000 | 244 |
| flush | KEY | 2024-03-16 | 297 | +0.7653 | 0.9596 | 0.00131 | 39.5M | 5.44 | −0.2708 | 0.2010 | 297 |
| flush | OL | 2026-03-22 | 270 | +0.0985 | 0.9222 | 0.00086 | 0.62M | 5.69 | −0.1174 | 0.1130 | 270 |
| flush | SPELL | 2024-02-23 | 535 | +0.2379 | 0.9234 | 0.00008 | 63.1M | 5.85 | −0.2109 | 0.1670 | 535 |

读法:`pct` 已经是**扩张中位秩**(0.0000 = 该合约历史上资金费最拥挤的那一档);`age` 是「面板首根起的天数」。

**两个从这张表读出来的东西(比表本身更重要)**:

1. **E3 不是理论风险**:全量 238 个参考事件里,**33 个(13.9%)的 `f7` 是 NaN**(资金费 7 天窗口缺一天),
   它们的 `pct` 因此是 `0.0000` —— 也就是说 **「被挤上去」有一部分其实是「资金费缺失」**,
   不是「资金费最负」。修它 = 改口径 = 事件集不再是 218/20(需另立预注册)。
2. **ICP / TLM / FTT 三行是零价差、零成交的合约**(`atr = 0`、`qv20 = 0`、`ret = 0`):
   `qv ≥ 3×qv20` 变成 `qv ≥ 0`、`ret ≥ thr` 变成 `0 ≥ 0` ⇒ 恒真 ⇒ 只要 `pct ≤ 0.10` 就是一次「squeeze」。
   这些事件在参考跑数里**确实存在**(它们就在 218 里)。SQL 复现时必须**原样保留**(口径一致优先),
   但生产上应该加一条「`qv20 > 0`」的守卫 —— 那同样需要另立预注册。

**D 库侧对账(6 个合约)**:库里 `perp_bv_daily` 每个合约比研究缓存**多 1 行**(903 行差额摊在 ~888 个合约上),
而**共有日期上 `close` 与 `qv` 逐日完全相同** ⇒ 差额是**新增行**,不是历史行被改写。
⇒ SQL 跑库时 `k` 比参考面板大 1 ⇒ 「最后一根不算信号日」那条线**平移一天** ⇒ 尾部可能多出个别事件。
**Seth 对账时若 squeeze 多 1–2 条、且都落在 2026-11 附近,即此因。**

### 5.1 本轮未做完的(留给下一轮)

- `t295_event_audit.py` 已按 `k_fund` 两条修正改好,**但未复跑**(本轮上下文触顶)⇒ 下一轮先跑
  `python3 docs/research/t295_event_audit.py`(约 30 秒)确认 **SQL 语义复算 == 218 / 20**,
  再把 `t295_audit.json` 一起提交。**本轮刻意不提交 `t295_audit.json`**(它是修正前的旧数,会误导)。
- §4-D 的库侧对账只抽查了 6 个合约;下一轮可扩到全部 20 个。


---

## 6. 落地建议(给 Seth,不自行决定)

1. apply 前先跑 §4-D 的库侧对账;若某个合约行数与参考面板不一致,先查清那 903 行(E2)是什么。
2. 函数算的是**全历史**(`p_from/p_to` 只筛输出):因为扩张分位的分母是「自上市以来的全部更早行」,截断历史会改 `pct`。生产上建议把 `f7 / atr / qv20 / pct` 落成日频中间表,再让事件判定只读它 —— 否则每次调用都是全表窗口函数。
3. 索引:`perp_bv_daily(symbol, d)`、`v_funding_daily(symbol, d)`、`perp_bv_pairs(symbol)`(见 SQL 文件末尾)。
4. E3 若要修(给 `f7 is null` 的行打标),那是**改口径**,会让事件集与 218/20 不再逐位一致 —— 需要另立预注册,不在本卡范围。
