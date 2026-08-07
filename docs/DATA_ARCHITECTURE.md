# 数据架构 — 分层契约

*Seth, 2026-08-07 · Jazz: "先做架构,再补充数据源,现在很多细节都不对的" + "我们是强筛选展示,但是我们跟踪要足够广"*

**这份文档的地位:** 在它落地之前,不再新增数据源。今天新建的三张表
(`ohlcv_hourly` / `funding_history` / `crypto_universe`)都是**反应式堆叠** ——
每一张都是上一个测量失败之后加的,不是从一个契约推出来的。堆叠的代价现在可测。

---

## 0. 先看错在哪(全部实测,不是意见)

| 检查 | 结果 | 后果 |
|---|---|---|
| **A1** `symbol` 跨表覆盖 | ohlcv 65 · cis 76 · vectors 72 · funding 10;**cis 有 1 个孤儿** | 连接键没有权威来源 |
| **A2** 同一资产带多个 `asset_class` | **24 个标的** | **`asset_class` 是行的属性,不是资产的属性** |
| **A3** 开盘跳空 >1% 的行占比 | Crypto 31.3% · L1 73.7% · L2 79.5% · **DeFi 83.5%** | 标签实际编码的是**数据源**,而源决定 K 线口径 |
| **A4** "D 日面板里有谁" | **无此表** | 每个回测都隐式用今天的成分 ⇒ **幸存者偏差不可测量** |

**A2 + A3 就是 S-106 那个伪影的根因。** 当时 `where asset_class='Crypto'` 我以为是在选资产类别,
实际是在选**数据源**;被排除的 L1/L2/DeFi 行是**同一批资产的另一个源**,口径不同,
于是"隔夜跳空 +12.30"是拼接两个源的产物。**不是数据脏,是身份模型错了。**

---

## 1. 三个宇宙 —— 跟踪 ≠ 投资 ≠ 展示

> Jazz:**强筛选展示,但跟踪要足够广。**

这不是偏好,是统计要求。今天三次分析撞同一堵墙(`N_eff=3.1` · S-108 的 n=20 · S-109 的 13 个 episode),
**因为我们只有一个宇宙,而它是按"能不能投"筛的。在窄域上算统计,就永远困在窄域的样本量里。**

| 宇宙 | 规模量级 | 用途 | 准入依据 |
|---|---|---|---|
| **COVERAGE 跟踪域** | 数百(Binance 682 永续中流动性 >$2M 的 363) | **所有统计、状态检测、基率、周期实例** | 有可靠行情即可 |
| **INVESTABLE 投资域** | 数十 | 配置与下单 | 流动性 + 托管 + 合规 + 容量 |
| **DISPLAY 展示域** | 十几 | LP / 前端 | 强筛选,叙事完整 |

**硬规则:统计在 COVERAGE 上算,配置在 INVESTABLE 上做,展示在 DISPLAY 上做。**
**用 DISPLAY 的样本去算基率是今天所有"测不出来"的共同结构。**

三个宇宙都必须有**时点成分历史**(见 L0),否则:
- 退市/归零的标的消失 ⇒ 幸存者偏差,而且**不可测量**(A4);
- 用今天的流动性做准入 ⇒ 把未来信息注入历史面板(违反 I2)。

---

## 2. 分层

```
L0  REGISTRY    资产身份 + 生命周期 + 三宇宙的时点成分
L1  OBSERVATION 原始观测,不可变,(asset, ts, source, field) —— source 是键的一部分
L2  CANONICAL   优先级解析后的唯一真值 + provenance
L3  FEATURE     PIT 安全的派生量,带版本
L4  STATE       资产相位 + 面板 regime(S-109 的对象)
L5  OUTCOME     前瞻量 —— 仅用于评估,永不作为输入
```

### L0 REGISTRY — 身份必须先于一切
今天没有这一层,`symbol` 直接当主键用,于是 A1/A2 必然发生。

- `assets(asset_id PK, symbol, name, class, listed_at, delisted_at, ...)`
  **`class` 只存在于这里**;任何观测行上出现 `asset_class` 都是 P0。
- `asset_aliases(asset_id, venue, venue_symbol)` —— `SOL` / `SOLUSDT` / CoinGecko id 是**别名**,不是身份。
- `universe_membership(asset_id, universe, valid_from, valid_to, reason)`
  **时点成分,区间表。** 回答"D 日谁在里面"是一次 `where valid_from <= D and (valid_to is null or valid_to > D)`。
  `reason` 记准入/剔除原因(流动性跌破 / 退市 / 合规),**因为剔除原因本身是研究素材**。

### L1 OBSERVATION — 源是键,不是备注
- 键 **必须** 含 `source`(已有教训:Lesson #76)。
- **一个 series 一张表,按频率分:** `obs_ohlcv_1d` / `obs_ohlcv_1h` / `obs_funding_8h`。
  频率是 series 的属性,不是"另开一族表"的理由 —— 但**不同频率不合并进一张表**,
  因为对齐规则不同,合并会把对齐错误藏进 NULL。
- **不可变。** 修正走新 `source` 或新行,不 UPDATE。

### L2 CANONICAL — 唯一真值 + 出处
- `(asset_id, ts, field)` 唯一,按源优先级解析(原生场所 > 聚合器,付费 > 免费)。
- **必带 `provenance`**(选了哪个源)与 `dispersion`(源间差异)。
  `ohlcv_venue_spread` 已经是这个形状 —— **跨源差异是特征,不是噪声**(Lesson #78)。
- **K 线口径必须在这一层被显式解析,不能靠 `asset_class` 隐式携带。**

### L3 FEATURE — PIT 是类型,不是纪律
- 每个特征声明 `lookback` 与 `available_at`;**`available_at > ts` 的行不得进入任何训练/检验**。
- 版本化(`feature_version`),因为特征定义会变而历史不该被静默重写。
- **禁止**:任何用到 `t` 之后信息的量出现在这一层(那属于 L5)。

### L4 STATE — S-109 要的对象
- `asset_state(asset_id, d, phase, confidence, detector_version)` —— 相位是**合取**而非单变量分档
  (S-109:分档排序会把双峰抹成一个不描述任何峰的均值)。
- `panel_state` = 现有 `market_state_vectors`。
- **状态必须能被事件计数**:相邻同相位天数属于同一 episode(Lesson #81)。
  ⇒ 表里直接存 `episode_id`,**不要让每个消费者自己切分** —— 今天我自己就漏切了一次。

### L5 OUTCOME — 单向阀
- `outcomes(asset_id, d, horizon, fwd_ret, fwd_mdd, benchmark, excess)`。
- **基准列必填**,且默认是**持有面板**(S-103:用 BTC 当基准会凭空制造显著性并翻转符号)。
- **L5 → L3/L4 是禁止的,这是唯一一条需要机器强制的方向性规则。**
  今天所有的假发现,机制上都是前瞻信息以某种形式回流到了判据里。

---

## 3. 不变量(违反即 P0)

1. **`class` 只在 L0。** 观测行上出现资产分类 = 身份模型漏了(A2/A3 的根因)。
2. **`source` 是 L1 的键的一部分**,不是注释。
3. **成分是时点区间,不是当前快照。** 没有 `universe_membership` 的回测,其幸存者偏差不可测量。
4. **L5 永不流入 L3/L4。**
5. **状态自带 `episode_id`。** 天不是事件。
6. **未测量 = NaN 且必须传播**(I1,已有守卫)。
7. **任何"完成"标记必须可验证。** `crypto_universe` 已带 `ohlcv_backfilled` / `funding_backfilled`
   布尔位,原因是 S-105:一个只落了一半的迁移被记成完成,藏了 12 天。

---

## 4. 迁移顺序(不并行,每步可验证)

| 步 | 内容 | 验证 |
|---|---|---|
| 1 | 建 L0:`assets` + `asset_aliases` + `universe_membership` | A1 孤儿数 = 0;A2 多类别标的 = 0 |
| 2 | 现有表加 `asset_id`,`asset_class` 从观测行**下线** | `select count(*) from obs_* where asset_class is not null` = 0 |
| 3 | L2 重建,显式解析 K 线口径,带 provenance | A3 各标签跳空占比收敛到同一水平 |
| 4 | `universe_membership` 回填(含已退市) | 能回答任意历史日的成分 |
| 5 | **此时才扩数据源**(COVERAGE 扩到 ~180 标的) | 每标的两个 backfilled 位为 true |
| 6 | L4 状态表 + `episode_id` | 事件计数不再由消费者自行切分 |

**第 5 步之前不加数据源。** 在错的身份模型上灌 4 倍数据,只会把 A2/A3 放大 4 倍。

---

## 5. 这份架构解决了今天的哪几个具体失败

| 今天的失败 | 被哪一条解决 |
|---|---|
| S-106 "隔夜 +12.30" 伪影 | L0 `class` 唯一 + L2 显式口径解析(A2/A3) |
| S-103 用 BTC 当基准 | L5 基准列必填且默认持有面板 |
| S-105 graveyard 在 24h 缓存 | L1 不可变 + 完成标记可验证 |
| S-109 日频分布表未做事件计数 | L4 自带 `episode_id` |
| 三次撞 `N_eff` / n=20 / 13 episodes | 三宇宙分离:**统计在 COVERAGE 上算** |
| "半个迁移被记成完成" | 显式 backfilled 位 + 每步验证 |

---

*本文档只写实测数字。重评前重跑 §0 的 A1–A4 四个查询。*
