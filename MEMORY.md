# MEMORY.md — long-term facts index (read at session start, 30s)

> **Rules:** ≤4KB, CI-enforced. One line per fact except the two never-evict blocks. Enter only
> what was EXPENSIVE to learn and will recur. **Anything dated / any row count / any "current
> status" → PROJECT_STATE, not here** — those decay, and a decayed MEMORY is worse than a short one.

## 💰 RETURN HIERARCHY — never evict (Jazz 2026-07-27; full: `HIGH_DIM_ONTOLOGY.md` §5b)
- **① 吃到 beta(持有 panel)→ ② beta+(持仓内超配,CIS 的真岗位,tilt 非 L/S)→ ③ beta multiplier(总暴露 0.7–1.3x)→ ④ pure alpha(中性,最难最后)。优先级,不是菜单。**
- **我们做反了:R76–R94 全是④(demean = 构造上扔掉 beta),①从未建过。连败是设定错误,不是运气。**
- 默认满仓多头:**tilt, don't neutralize**。基准是"等权持有本 panel",不是 0。β-adj 只用于**归因**,绝不用于中性化仓位。每个结果报 total / vs 持有 / 超额。
- **⓪层 OVERRIDE 凌驾四层**(`REGIME_OVERRIDE_SPEC.md`):周期转向时**空仓甚至裸空优先于吃 beta** —— ①是**条件性默认**。暴露区间 [−0.3, 1.3]。
- **正交是归因工具,不是建仓约束**(我曾写错)。ⓠ层判据不看 Sharpe,看**崩塌前 1/3 内是否降暴露**+ maxDD 改善 ≥10pp + 切换 ≤6/年 + 优于随机。
- **Millennium**:edge 在**中心化风险分配**,不在单个 pod。**每个组件必须有 `max_dd_stop`,且回测带着止损跑;无止损不进生产**(含ⓠ层自己)。

## 🧭 ONTOLOGY CORE — never evict (full: `HIGH_DIM_ONTOLOGY.md` + `ARCHITECTURE.md`)
- 市场真实状态高维;全部工作 = 一连串**保结构的降维**;VDB 是几何基底。
- 最深对象是 **Entity/Decision**,影响力作向量场传播;CIS/价格是波前过后的**反射**;**edge = lag**。
- **Be water**:无冻结因子,场算子随 embedding 重塑;regime 是场的**相**,只进 sizing 不做轮动。
- **Be quantum**:资产态是**分布**非标量(I5);`entanglement_delta = p−s`;CIS 快照是带 lag 的**测量塌缩**。
- 扩散作用于 **CHANGE(因)非 level(反射)** —— level 扩散已证伪(S-81)。
- 存储法则:**dense+many → pgvector HNSW;sparse+few → jsonb + NaN-aware 共享维余弦**(稀疏补 0 做稠密余弦是错误度量)。
- 量子钩子:扩散算子保持**线性**(→quantum walk);sleeve 选择是 QUBO。**不声称量子优势**。
- **VDB 做多**:六对象全向量化;终态 = 任何问题都是一次向量查询。

## 不变量(违反即 P0)
- **I1 未测量 = NaN,绝不是 0。** 且 NaN 必须**传播** —— `min/max` 会把 NaN 吞成边界(`max(0,min(1,nan))==1.0`),一个未测量的市值会伪装成万亿资产。
- **I2 PIT** · **I3 β 分离** · **I5 分布非标量** · **I6 v1 维度字节级不变**。
- **守卫必须观测真实制品。** 断言硬编码字典的测试、返回静态字典的 /health、只写进台账的教训 —— 都是带绿勾的散文。
- **客户端超时 ≠ 超时**:没有对应服务端超时的,是带安心日志的连接泄漏。
- **按天加权的 alpha/Sharpe/t 在事件计数前不是证据,是叙事**(S-101:+7.99 → +3.58 t=1.55)。
- **单飞锁必须同时界定"能被持有多久"和"调用方等多久"** —— 只做一个仍然会挂。
- **任何切断动作必须有被证明的恢复路径**(S-90 冻结不解冻 / 断路器 cooldown)。

## 环境陷阱
- FUSE sandbox:git 写命令会残留 `.git/index.lock` → **所有 git 走 Mac 侧**;`git unlock` 解卡。
- Supabase 在 **ap-southeast-2**;Postgres `http` 扩展可直连 Binance,Railway(US)被地理封锁。
- 沙箱无任意出网;yfinance 已死。
- `preflight.sh` 是唯一生产闸门;**py_compile 不够**(2026-07-13 曾 502 生产)。
- **RLS 开启后匿名读全封** ⇒ 任何回填脚本需 service_role,沙箱跑不了。

## 数据法则(位置与陷阱,不记行数)
- **`ohlcv_daily` 是多源表**,唯一键 `(symbol, trade_date, source)` ⇒ **回测必须读 `ohlcv_daily_canonical`**;价差在 `ohlcv_venue_spread`(先读 `spread_kind`,当前跨源差是口径不是套利)。
- **`signal_outcomes` 与 `signal_journal` 是同一测量的两个世代** ⇒ **读 `signal_outcomes_unified`**,单读任一表会静默丢一半历史。
- 决策链:`market_state_vectors` → `similar_market_states()` → `strategy_response`(`sample_grade='none'` = 从未在此环境出现,是一等信息)。
- `cis_scores` 无市场数据列 ⇒ 历史向量的市场维必须重建或记 NaN,不能用默认值。
- pillar_O 是**结构异常探测器**,设计上大多数时候不触发 ⇒ 持续性 L/S 用它是误用,正确用法是**条件性/探测器门控**。

## 已验证(引台账,不重推)
- R62:raw `a_ret−b_ret` = 杠杆化 beta(β 1.4–2.4),必须 β 调整。
- S-77:v5 双分数成立;**O 是离散度支柱**,F 是纯收益锚。S-80:**F_IC +0.197 且 12/12 年为正**。
- S-101(事件口径,473 事件):**无任何一档显著为正**;`OUTPERFORM` t=−6.88 显著为**负**;**U 形存活** ⇒ 待检验假说:**CIS 测强度而非方向**。
- 风控:**事前波动率目标 > 事后止损**;收紧止损会因高水位重置而**加大**累计回撤;杠杆是**乘** Sharpe 不是造 Sharpe。
- 指标极性:**先定先行/同步/滞后类,再定正反用**(F&G 同步 ⇒ 确认不反向,用反了差 1,889bp)。

## 协作(常设)
- 台账 `S-`/`M-` 前缀从 76 起,R1–75 冻结;**只在 EOF 追加,先占标题再写正文**。Lesson 编号同样会撞车 —— **先到先得,后写者让号**。
- **绝不 `git add -A`**;只提交自己 lane 的路径。PROJECT_STATE 是共编的 —— 锚定稳定标题,预期被中途重写。
- 撞上基础设施故障时**允许绕行,但必须在 OPEN RISKS 留一条带 `VERIFY:` 的条目** —— 绕行不留痕 = 把故障传给下一个失忆的自己(S-83 的代价:10.4 小时宕机)。
