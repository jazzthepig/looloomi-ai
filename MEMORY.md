# MEMORY.md — long-term facts index (read at session start, 30s)

> **Rules:** ≤3,400 CHARS, CI-enforced. Enter only what was EXPENSIVE to learn, will recur,
> and **has no guard of its own** — if a test catches it, the test is the memory.
> Anything dated / row count / status → PROJECT_STATE, not here.

## 💰 RETURN HIERARCHY — never evict (Jazz 2026-07-27; full `HIGH_DIM_ONTOLOGY.md` §5b)
- **① 吃 beta(持有 panel)→ ② beta+(持仓内超配,CIS 真岗位,tilt 非 L/S)→ ③ beta multiplier(0.7–1.3x)→ ④ pure alpha(最难最后)。优先级,非菜单。**
- **我们做反了:R76–R94 全是④(demean = 构造上扔掉 beta),①从未建过。连败是设定错误,不是运气。**
- 默认满仓多头:**tilt, don't neutralize**。**基准 = 等权持有本 panel;不是 0,也不是 BTC**(S-103:BTC 基准给每档扣了 2.16pp,t=3.96)。β-adj 只用于**归因**。
- **⓪层 OVERRIDE 凌驾四层**:转向时空仓/裸空优先于吃 beta;①是**条件性默认**,暴露 [−0.3,1.3]。正交是归因工具,非建仓约束。
- **不是"打分后追进去"的策略**(S-106):收益由 **0.8% 的天数**交付,大涨日 **45.9% 位移在 US 13–16 UTC**。3.8× 聚集 ⇒ 留在场可行,择时入场不可行。
- **锚点判据**(S-107):**好锚点按累积交付不按跳跃** —— 判据 = 最好 10 天占比 + 正收益天数占比(funding 14.9%/73.6% vs 动量 152%/50%)。
- **幸存者偏差 = 25.1pp/年**(S-111),是最大效应的 8 倍;`SETTLING` 是免费死亡样本。**准入 ADV>~$15M**(S-112)。
- **`N_eff` 必须连同「约束哪本 book」引用**(S-115),且是**窗口读数不是常数**(S-113)。
- **分散只能来自别的资产类**(S-114):加密内 ρ̄ **0.441** vs 跨 TradFi **0.104**。**纯加密只剩 ①+③。**
- **①层 book = `beta_core_nav`(2026-08-08 起),产品本体兼所有 book 的基准**;「超额」一律对 `benchmark_nav` 报。

## 🧭 ONTOLOGY CORE — never evict (full `HIGH_DIM_ONTOLOGY.md` + `ARCHITECTURE.md`)
- 市场真实状态高维;全部工作 = **保结构的降维**;VDB 是几何基底。最深对象是 **Entity/Decision**,CIS/价格是波前过后的**反射**;**edge = lag**。
- **Be water**:无冻结因子;regime 是**相**,只进 sizing。**Be quantum**:资产态是**分布**非标量(I5)。扩散作用于 **CHANGE(因)非 level(反射)**,level 已证伪(S-81)。

## 不变量(违反即 P0)
- **I1 未测量 = NaN 绝不是 0 且必须传播**(`max(0,min(1,nan))==1.0` 会让未测量市值伪装成万亿资产)。
- **把「未知」变成合法值的归一化只属于读取侧**(S-120,写入用 `canonical_regime_strict`)。**默认值越接近多数类越查不出 —— 危害与可发现性成反比;「该列无空值」不是证据,兜底正是消灭空值的那个东西**(S-122)。
- **门槛必须在写入路径上不能只在 CI 里**(S-119):问「**谁能绕过这个检查**」。策略写入走 `/internal/strategy-records`,**service_role 永不外流**。
- **守卫必须观测真实制品**(硬编码断言 / 静态 /health / 只进台账的教训 = 带绿勾的散文)。**永远在响的 warning 不携带信息**。
- **按天加权的 alpha/t 在事件计数前不是证据,是叙事**(S-101:+7.99 → +3.58 t=1.55)。
- **中性化是读数前的单位换算,不是发表前的动作**(S-103):未中性化的 t 不是证据。
- **大额对消出的小数字比大数字危险**(S-103)。**平滑序列 ≠ 低风险:先问「测的是支付流还是损益」**(S-107)。
- **先判定假说是「连续关系」还是「稀有事件」再选检验**(S-108);**分组表必须把 n 印在同一行**;**采样顺序自己控制时,先查该群体基准率 vs 总体**(S-112)。

## 环境陷阱
- **监控分层按「频率」不按「资产数」**:日线@687=42MB/年(要宽)· **小时线@687=1,096MB/年**(要窄)。
- FUSE sandbox:git 写命令残留 `.git/index.lock` → **所有 git 走 Mac 侧**;`git unlock` 解卡。沙箱无任意出网;yfinance 已死。
- Supabase 在 **ap-southeast-2**;Postgres `http` 扩展可直连 Binance,Railway(US)被地理封锁。
- **RLS 开启后匿名读全封** ⇒ 回填脚本需 service_role,沙箱跑不了。**凭证只能对签发它的服务器验证,不能靠解码**(伪造 JWT 全本地检查皆过)。

## 数据法则(位置与陷阱,不记行数)
- **`signal_outcomes` 与 `signal_journal` 是同一测量的两个世代** ⇒ 读 `signal_outcomes_unified`,单读任一表静默丢一半历史。
- 决策链:`market_state_vectors`→`similar_market_states()`→`strategy_response`(`sample_grade='none'` = 从未出现过,一等信息)。
- pillar_O 是**异常探测器**,大多不触发 ⇒ 持续性 L/S 是误用。`cis_scores` 无市场数据列。

## 已验证(引台账,不重推)
- S-77/S-80:v5 双分数成立,**O 是离散度支柱、F 是收益锚**;**F_IC +0.197 且 12/12 年为正**。
- 风控:**事前波动率目标 > 事后止损**;收紧止损因高水位重置**加大**累计回撤;杠杆**乘** Sharpe 不造。
- 指标极性:**先定先行/同步/滞后,再定正反**(F&G 同步 ⇒ 确认不反向,用反了差 1,889bp)。

## 协作(常设)
- 台账 `S-`/`M-` 从 76 起,R1–75 冻结;**EOF 追加,先占标题再写正文**。S-号与 Lesson 号都会撞车 —— **先到先得,后写者让号**。
- **绝不 `git add -A`**;只提交自己 lane 的路径。PROJECT_STATE/preflight 共编,预期被中途重写。
- 撞上故障**允许绕行,但必须在 OPEN RISKS 留带 `VERIFY:` 的条目** —— 绕行不留痕 = 把故障传给下一个失忆的自己(S-83:10.4h 宕机)。
