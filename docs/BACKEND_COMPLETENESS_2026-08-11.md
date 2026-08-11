# 后端完成度检测 — 2026-08-11

全部为**实测**,不是自评。命令附在每节末尾,可复跑。

---

## 一句话

**智能层基本完成,证据层刚刚开始计时,用户层在第一步就是断的。**

不是「还差几个功能」,而是三条线处在**完全不同的阶段**,而对融资有约束力的那条
(前向记录)**是日历约束,不能靠加班压缩**。

---

## 1. 规模与质量(实测)

| 指标 | 数值 |
|---|---|
| API 端点 | **193** 个,分布在 28 个文件 |
| preflight 套件 | **26** 个,**267** 项检查,全绿 |
| 测试文件 / 断言 | 32 / **687** |
| `TODO/FIXME/HACK/XXX` | **357** 处(src/ 内) |
| 生产健康 | `/health` 200 · `status: healthy` · `pg_configured: true` · `degraded: false` |

端点分布最重的三个:`routers/market.py` 28、`main.py` 27、`routers/cis.py` 22。

> `bash scripts/preflight.sh` · `curl -s $API/health`

**读法:** 193 个端点和 267 项守卫说明**代码量和纪律都不缺**。357 处 TODO 是正常的技术债
密度,不是危险信号 —— 危险的是下面第 3 节那 9 处。

---

## 2. 智能层 — 基本完成 🟢

- CIS 脊柱端到端通:Mac T1 引擎 → `cis_push` → Redis → `cis_provider` T2 兜底 →
  `/api/v1/cis/universe` → 前端 T1 绿 / T2 琥珀
- 向量库落 Supabase pgvector,HNSW + `match_asset_embeddings` RPC,SCHEMA_VERSION 3(27 维)
- 深面板 2017+ `binance_hist` 已回填
- 数据源双路兜底:CoinGecko→Hyperliquid(crypto)、EODHD→yfinance(TradFi)
- 前端 10 个页面 + React(`dashboard/src/`)

**缺口(已知,已排队):**
- `market_state_vectors.regime_label` **582 天 100% NULL**(任务 #37)
- `asset_embeddings` 需在 SCHEMA_VERSION 3 下**重建**(任务 #35)
- 17 个 symbol 自 2026-07-27 **停止采集**,却仍标 `monitored`(任务 #31)

---

## 3. 证据层 — 刚开始计时 🟡 **这是真正的约束**

① 账本 v2 实测状态:

```
days = 3 · days_to_gate = 57 · as_of = 2026-08-11
exposure_cap = 0.5 · cap_source = regime_map · regime = TIGHTENING
excess_pct = -0.025 · annualization_is_meaningful = false
```

**好消息:③ 层今天第一次真的在咬**(S-130/S-133 修完之后),第一条差异化收益已落库。

**硬事实:60 天门槛还差 57 天,而这 57 天不能压缩。** 任何加速开发都不改变这个日期。
7 个 paper book 在并行积累前向记录(`causal / fusion / combined / scalable / dingge /
beta_core / two_layer`)。

**同时,这几天的研究把「我们在积累什么记录」这件事本身修正了两次:**
- **S-135:** ③ 的价值主要来自 **vol targeting**,不是 regime cap
  (hold-the-panel ret/DD 0.294 → cap 1.3 配 vol targeting **0.580**)
- **S-136:** ③ 的**目标写错了** —— 完美预知**回撤**并减仓,ret/DD 反而从 0.634 掉到
  **0.337**;完美预知**波动**才有 **+39.6%** 空间。`_REGIME_CAP` 现在的档位是按
  「回撤直觉」设的,**而回撤保护本身是负价值的**。

> **这意味着 57 天里我们不是干等 —— `_REGIME_CAP` 的映射该按波动分位重设,越早越好,
> 因为改了之后计时要不要重来是一个 inception 决策。**(见第 6 节)

**⚠️ 9 处 `supabase_insert_table` 仍在吞掉返回值**(任务 #33,S-126 同类)。
这一类的后果不是崩溃,是**账本看起来在跑而记录是空的** —— 对一个卖前向记录的产品,
这是唯一不能吸收的失败。① 已修,其余 book 未修。

---

## 4. 用户层 — 第一步就断 🔴

| 组件 | 状态 |
|---|---|
| `api_keys` 表 | 存在,但**发 key 会失败**(见下) |
| 限流 | ✅ `middleware/rate_limit.py`(同源 600rpm、internal-token 放行、30s key 缓存) |
| 认证 | API key + `X-Internal-Token`,**中间件式**,不是 per-endpoint 依赖 |
| `users` | 1 处引用 |
| `tenants` / `billing` / `audit_log` | **0 处引用 —— 不存在** |

**「Key storage failed」的根因已定位,是一个 schema 漂移:**

`scripts/supabase_all_tables.sql:232` 写的是

```sql
id  BIGSERIAL PRIMARY KEY
```

而**生产库里 `api_keys.id` 是 `bigint NOT NULL` 且 `column_default: null`** ——
**没有 sequence。** 建表脚本和实际表不一致(表早于此文件、或用别的方式建的)。
所以每次插入都因为 `id` 没有默认值而失败。修复是一条 ALTER,已备好:
`scripts/supabase_fix_api_keys_id_sequence.sql`。

**但这只解开第一颗扣子。** 客户可部署还差:多租户隔离、计费、审计轨迹 —— 三样都是 0。

---

## 5. 完成度,分线给分

| 线 | 完成度 | 约束类型 |
|---|---|---|
| 数据 / 智能层 | **~85%** | 工程,可加速 |
| 证据 / 前向记录 | **5%**(3/60 天) | **日历,不可加速** |
| 用户 / 商业化层 | **~15%** | 工程,可加速 |
| 合规语言 | **100%** | CI 强制(`test_compliance_language`) |

**"可以被客户部署" 的定义如果是「客户能自助拿 key、按量计费、看到自己的数据」——
现在是 15%。** 如果定义是「机构 LP 能看到一条可验证的前向曲线」—— 现在是 5%,
且 57 天后自动到 100%,前提是这 57 天里账本不断线。

---

## 6. 我的建议顺序(不是清单,是顺序)

1. **今天:重设 `_REGIME_CAP` 为波动分位**(S-136)。
   越晚改,越可能要重开 inception 重新计时 —— **这是唯一一件「早做省 60 天」的事。**
2. **今天:`api_keys` id sequence 一条 ALTER**(5 分钟,解开用户层第一步)。
3. **本周:9 处吞返回值的 `supabase_insert_table`**(任务 #33)。
   现在 7 个 book 在积累记录,而其中 6 个的写入失败是静默的。
4. **本周:① 断线告警**(任务 #29,`days_since_mark > 1` 必须呼叫)。
   57 天里最贵的事故是账本停跑而没人知道。
5. **之后:多租户 + 计费。** 这是纯工程,不抢 57 天的路。

**不建议现在做的:** 提高 regime 检测精度。S-136 说上界是 +39.6%,
但**在把目标从回撤改成波动之前,提高的是错方向的精度**。

---

## 复跑

```bash
bash scripts/preflight.sh
curl -s $API/health | jq '{status, pg:.data_layer.strategy_library.pg_configured}'
curl -s $API/api/v1/beta-core/curve | jq '{days,days_to_gate,exposure_cap,cap_source,regime,excess_pct}'
curl -s -H "X-Internal-Token: $INTERNAL_TOKEN" $API/internal/beta-core-probe | jq .diagnosis
python3 scripts/study_regime_layer_upper_bound.py
```
