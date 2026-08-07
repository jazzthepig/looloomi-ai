# MEMORY.md — long-term facts index (read at session start, 30s)

> **Rules:** ≤4KB, CI-enforced. Enter only what was EXPENSIVE to learn, will recur, and
> **has no guard of its own** — if a test already catches it, the test is the memory.
> Anything dated / any row count / any "current status" → PROJECT_STATE, not here.

## 💰 RETURN HIERARCHY — never evict (Jazz 2026-07-27; full `HIGH_DIM_ONTOLOGY.md` §5b)
- **① 吃 beta(持有 panel)→ ② beta+(持仓内超配,CIS 真岗位,tilt 非 L/S)→ ③ beta multiplier(0.7–1.3x)→ ④ pure alpha(最难最后)。优先级,非菜单。**
- **我们做反了:R76–R94 全是④(demean = 构造上扔掉 beta),①从未建过。连败是设定错误,不是运气。**
- 默认满仓多头:**tilt, don't neutralize**。**基准 = 等权持有本 panel;不是 0,也不是 BTC**(S-103:用 BTC 当基准给每一档扣了 2.16pp,t=3.96)。β-adj 只用于**归因**。
- **⓪层 OVERRIDE 凌驾四层**(`REGIME_OVERRIDE_SPEC.md`):转向时空仓/裸空优先于吃 beta;①是**条件性默认**。暴露 [−0.3,1.3]。**正交是归因工具,非建仓约束。**
- **Millennium**:edge 在**中心化风险分配**,不在单个 pod。**每个组件必须带 `max_dd_stop` 且回测带着止损跑。**

## 🧭 ONTOLOGY CORE — never evict (full `HIGH_DIM_ONTOLOGY.md` + `ARCHITECTURE.md`)
- 市场真实状态高维;全部工作 = 一连串**保结构的降维**;VDB 是几何基底。
- 最深对象是 **Entity/Decision**,影响力作向量场传播;CIS/价格是波前过后的**反射**;**edge = lag**。
- **Be water**:无冻结因子;regime 是**相**,只进 sizing 不做轮动。**Be quantum**:资产态是**分布**非标量(I5);扩散保持线性,不声称量子优势。
- 扩散作用于 **CHANGE(因)非 level(反射)** —— level 扩散已证伪(S-81)。
- 存储:**dense+many → pgvector HNSW;sparse+few → jsonb + NaN-aware 共享维余弦**(稀疏补 0 做稠密余弦是错误度量)。

## 不变量(违反即 P0)
- **I1 未测量 = NaN 绝不是 0,且必须传播** —— `max(0,min(1,nan))==1.0`,未测量市值会伪装成万亿资产。
- **I2 PIT · I3 β 分离 · I5 分布非标量 · I6 v1 维度不变。**
- **守卫必须观测真实制品** —— 断言硬编码字典的测试、返回静态字典的 /health、只进台账的教训,都是带绿勾的散文。
- **客户端超时 ≠ 超时**;**单飞锁须同时界定持有与等待时长**;**任何切断动作须有被证明的恢复路径**。
- **按天加权的 alpha/t 在事件计数前不是证据,是叙事**(S-101:+7.99 → +3.58 t=1.55)。
- **中性化是读数前的单位换算,不是发表前的合规动作**(S-103)。未中性化的 t **不是"待校正的证据",它不是证据**。
- **由大额对消得到的小数字比大数字危险**(S-103:+8.67 与 −9.03 对消出 +0.59)。

## 环境陷阱
- FUSE sandbox:git 写命令残留 `.git/index.lock` → **所有 git 走 Mac 侧**;`git unlock` 解卡。沙箱无任意出网;yfinance 已死。
- Supabase 在 **ap-southeast-2**;Postgres `http` 扩展可直连 Binance,Railway(US)被地理封锁。
- **RLS 开启后匿名读全封** ⇒ 回填脚本需 service_role,沙箱跑不了。**凭证只能对签发它的服务器验证,不能靠解码**(伪造 JWT 全本地检查皆过)。

## 数据法则(位置与陷阱,不记行数)
- **`ohlcv_daily` 多源**,键 `(symbol,trade_date,source)` ⇒ **回测读 `ohlcv_daily_canonical`**;价差在 `ohlcv_venue_spread`(先读 `spread_kind`)。
- **`signal_outcomes` 与 `signal_journal` 是同一测量的两个世代** ⇒ **读 `signal_outcomes_unified`**,单读任一表静默丢一半历史。
- 决策链:`market_state_vectors`→`similar_market_states()`→`strategy_response`(`sample_grade='none'` = 从未在此环境出现,一等信息)。
- `cis_scores` 无市场数据列 ⇒ 历史向量的市场维须重建或记 NaN。pillar_O 是**异常探测器**,大多不触发 ⇒ 持续性 L/S 用它是误用。

## 已验证(引台账,不重推)
- R62:raw `a_ret−b_ret` = 杠杆化 beta(β 1.4–2.4)。**S-103 是同一个错误在档位聚合上重演一次。**
- S-77:v5 双分数成立,**O 是离散度支柱**,F 是纯收益锚。S-80:**F_IC +0.197 且 12/12 年为正**。
- S-101/S-103:事件口径下**无一档显著为正**;中性化后**五档 |t| 全 <2**。⇒ 待检验:**CIS 测强度而非方向**。
- 风控:**事前波动率目标 > 事后止损**;收紧止损因高水位重置**加大**累计回撤;杠杆**乘** Sharpe 不造。
- 指标极性:**先定先行/同步/滞后,再定正反**(F&G 同步 ⇒ 确认不反向,用反了差 1,889bp)。

## 协作(常设)
- 台账 `S-`/`M-` 前缀从 76 起,R1–75 冻结;**只在 EOF 追加,先占标题再写正文**。Lesson 编号会撞车 —— **先到先得,后写者让号**。
- **绝不 `git add -A`**;只提交自己 lane 的路径。PROJECT_STATE 共编,预期被中途重写。
- 撞上基础设施故障**允许绕行,但必须在 OPEN RISKS 留带 `VERIFY:` 的条目** —— 绕行不留痕 = 把故障传给下一个失忆的自己(S-83:10.4h 宕机)。
