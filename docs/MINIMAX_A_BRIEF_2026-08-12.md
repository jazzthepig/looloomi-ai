# Minimax-A 任务简报 — 2026-08-12

> Jazz:整段复制给 Minimax-A 即可。
> 里面既有**要他做的事**,也有**要他改文档的事**(有几处我们之前写错了)。

---

Minimax-A,

这是一次**结构对齐 + 补齐欠账**的任务包。先讲清楚我们的设计,再给你排期。
如果任何一条和你手上的东西冲突,**先回执再动手** —— 上一轮就是我们没先说清楚,
才导致你查了一晚上心跳代码而问题根本不在那里。那次是我们的流程错,不是你的。

---

## 一、先对齐设计:三条现在生效的结构约束

### 1. 写入侧只有一个主人(`APP_ROLE`,S-149)

仓库里 `src/api/store.py` 的两个写函数(`supabase_insert_batch` / `supabase_insert_table`)
现在会先问角色:

```
APP_ROLE=production   → 可写。Railway 显式设 ENVIRONMENT=production,映射过来,行为不变
未设置 / 其他          → replica,写入被拒(返回 False,不抛异常),日志说一次原因
APP_ROLE=dev          → 拒绝启动(还没有私有命名空间)
```

**为什么。** 本地跑这个 app 会起 20+ 后台 loop,十几个写 Supabase、共用同一批
Redis state key。两个进程会在同一天用不同面板、不同时点 mark `beta_core_nav` ——
**前向记录会变成「谁先醒」的函数**。之前唯一挡住它的是本地 `SUPABASE_KEY` 恰好是空的。
而且旧默认值 `ENVIRONMENT` 缺省 `"production"`,**任何不设变量的机器都是生产写入者**。

**边界是「谁可以写」,不是「谁可以连」。** 从生产读数据到你本地,有用且无害;
写才是必须唯一的那一半。

**对你的实测影响:零。** 我逐个查过你的四个写库脚本,全部自带 Supabase 客户端:

| 脚本 | 受影响 |
|---|---|
| `asset_embeddings_history_push.py` | ❌ |
| `risk_meter_history_push.py` | ❌ |
| `signal_outcome_tracker.py` | ❌ |
| `export_backtest_to_supabase.py` | ❌ |

**但请记住这条线:以后任何 Mac 侧脚本 `from src.api.store import ...`,
会静默写不进去**(返回 False,不报错)。自检:

```bash
python3 -c "from src.api.runtime_role import ROLE, is_writer; print(ROLE, is_writer())"
```

如果你确实需要某个 Mac 脚本走仓库的 store,**先跟我们说** —— 因为
「两个 production 写入者」正是这条闸门要消除的东西本身。

---

### 2. 版本号必须 import,不能写字面量(S-144)

`embedder.SCHEMA_VERSION` 8-09 从 2 升到 3(v3 修了 pillar 维 0..4 在每条存量向量里恒为 0)。
但三处写入方各自钉死了 `2`,其中一处的注释还写着 `# embedder.SCHEMA_VERSION`。

结果:**写入从来没停过,它一直在成功地写错版本。** 库里 72 行全 v2,同一个版本号下混着
18 维和 27 维两种形状,读路径按 v3 过滤全部落空,**整个矢量层暗了 18 天而没有任何报错**。

**规则:任何落 `schema_version` 的地方**

```python
from src.data.vector.embedder import SCHEMA_VERSION
```

**不要写数字。** 守卫 `tests/test_vector_schema_version_is_single_sourced.py` 扫整个 `src/`。

⚠️ **这条直接影响你**:`asset_embeddings_history_push.py:88` import 了这个 embedder,
所以你产出的向量形状跟着这个常量走。见任务 A2。

---

### 3. 不得宣称没有测量过的东西(S-141)

`cause_proximity.out_of_circle_risk` 现在是**四值**:`low / elevated / high / unmeasured`。
`unmeasured` 出现的条件是:**D3 holder stage 和 D4 attention diffusion 都缺**。
实测 58 个资产里 46 个是 `unmeasured`。

改之前那 46 个和有真实数据的 12 个**都显示 `low`**,driver 还写着
「no out-of-circle stress **detected**」—— **一个不存在的检测给出的否定结论**。
ARCHITECTURE.md 第 164 行:「一个我们没有跑过自己回路的信号,是我们不得宣称的信号。」

**对 `risk_meter_history_push.py` 的实测影响:零。** 你读的是
`float(cp.get("risk_score") or 0.0)`,数值路径。异常分支我从 `0.0` 改成 `None`,
而 `None or 0.0` → `0.0`,行为不变。

**但如果你以后要读 band:`unmeasured` 不是「低风险」,是「没测」。**

---

## 二、任务

### 🔴 A1 — Mac 引擎的三个「全局量被按条目获取」(P0,本周)

这两天在 Railway 侧修了三个 bug,**是同一个形状**。你的引擎跑同一批数据源,
大概率有同款。请自查并修:

| 症状 | 根因 | 我们的修法 |
|---|---|---|
| GitHub `403 rate limit exceeded` × 25/轮 | 请求**未带 token**,未认证配额 60 次/小时,一轮打光 | `GITHUB_TOKEN`(classic PAT,**不需要任何 scope**)→ 5,000/hr |
| CryptoPanic `429` × 20+/轮 | **一个全局 RSS** 被按资产逐个拉 | feed 单独缓存 + 429 断路器 |
| yfinance DXY/VIX/TNX 每 10 秒刷屏 | **三个全局因子**在按资产的 `_betas_in_thread` 里每次重拉,24×3=**72 次/轮** | 全局缓存 + **负缓存** + 断路器,实测 **72 → 1** |

**共同根因:缓存装在网络调用的下游** —— 它只去重了解析,从来没去重请求。

**自查方法(一句话):任何「对所有资产都一样」的数据,它的 fetch 是不是在按资产的循环里面。**

**负缓存是关键的一半**:上游答「没有」也是一个关于上游的真实答案,
再问 71 次不会改变它。没有负缓存,一次 Yahoo 故障的代价是每轮 72 次尝试,
而**重试压力在日志里和故障本身长得一模一样**。

---

### 🟡 A2 — `asset_embeddings_history_push.py` 对齐 v3(本周)

1. 确认它落库时的 `schema_version` 是 **import** 来的,不是字面量
2. 如果它此前写过 v2 行,**不要删** —— 加 `superseded_reason` 标注(我们仓库侧的
   72 行就是这么处理的:保留审计,读路径排除)
3. 跑一次 v3 重建。仓库侧新增了 `POST /internal/asset-vectors/rebuild`
   (INTERNAL_TOKEN 守卫)可以参考,或者你用自己的 RPC

**为什么要有重建入口:** 版本升级之后没有自动回路 —— 旧行被版本过滤掉,
新行要等下一次成功周期,**而那个周期本身可能就是坏的那个**。

---

### 🟡 A3 — 帮我们确认 Mac 侧 `.env` 的完整性(本周,10 分钟)

我们发现仓库的 `.env` 从 8-02 起就缺一半(那次伪造 service_role key 清除留下的空位),
而**没有任何东西记录这个文件应该包含什么** —— `.env` 是 gitignored 且没有 `.env.example`。
所以「缺了一个键」和「本来就不需要」**无法区分**。

请回报 Mac 侧 `/Volumes/CometCloudAI/cometcloud-local/.env` **只报键名和状态,不要贴值**:

```bash
python3 - <<'EOF'
import pathlib
p = pathlib.Path("/Volumes/CometCloudAI/cometcloud-local/.env")
print("exists:", p.exists())
if p.exists():
    for ln in p.read_text().splitlines():
        ln = ln.strip()
        if "=" in ln and not ln.startswith("#"):
            k, _, v = ln.partition("=")
            print(f"  {k.strip():<28} {'set('+str(len(v.strip()))+')' if v.strip() else 'EMPTY'}")
EOF
```

**三种状态要分清:`set` / `EMPTY` / `absent`。**
`SUPABASE_KEY=`(有键无值)对代码里每一个 `os.environ.get` 来说都像「已配置」,
然后什么都不写 —— **那个第三态就是我们昨晚的代价**。

顺带:`cis_scheduler.py:25` 是 `if _dotenv_path.exists():` —— **文件不存在时静默跳过**。
建议改成缺失时 **loud fail 或至少 WARNING**,否则调度器会带着空环境安静地跑。

---

### 🟢 A4 — 文档更正(我们之前写错的,请你在文档上改)

这几条是**我们的错**,但文档在你那边或双方共用,请一并更正:

1. **`MINIMAX_SYNC.md` §BETA-CORE-BOOK(8-08)** 说 ① 账本由 `macro_regime` 决定 cap。
   **已不成立。** 8-11 起改为**滚动波动三分位**驱动(S-137)。
   实测 902 天 OOS:hold-the-panel ret/DD 0.319 · 恒定 cap 1.3 = 0.634 ·
   波动三分位 = 0.780 · 未来波动 ORACLE = 0.885。
   `regime` 仍然**记录在每一行**,但**不再给账本定仓位** ——
   我们测过波动状态值多少钱,从没测过 regime 值多少钱。

2. **同上,ⓠ 的判准写错了方向。** 原文是「敞口有没有在回撤前三分之一降下来」。
   S-136 用**完美预知**测过这个目标:ret/DD 从 0.634 掉到 **0.337**,
   **比什么都不做还差 47%** —— 回撤后面跟着反弹,在回撤前减仓等于在反弹前也减了仓,
   而 ① 是 long-only beta 捕获,**放弃上行的代价大于避开下行的收益**。
   完美预知**波动**才有 +39.6% 空间。**该预测的是波动,不是回撤。**

3. **① 账本的 inception 记录**:v1 VOID(23 天陈旧 regime)· v2 SUPERSEDED
   (策略变更,非作废,3 条 mark 是诚实的)· **v3 第 1 天 VOID**
   (S-147:面板只加载 120 天 → 91 个波动观测 < 250 门槛,滚动分位数从未启动,
   账本以 1.3 倍满杠杆开在冻结的 2019–2022 阈值上,而当时波动 0.325 低于那个标定区间下沿)。
   面板已加深到 900 天,seed 模式不再取最高档。

4. **`§OHLCV-EXTENSION` 里如果写了「120 天面板足够」之类的话,请改。**
   任何要算**分布统计量**(分位数、terciles)的地方,面板深度必须
   ≥ 窗口 + lookback。加深几乎不要钱:`load_binance_panel` 分页上限 1000 根,
   **120 天和 900 天是同样的 HTTP 调用次数**。

---

## 三、你可能会问的两件事

**Q: 为什么不直接给 Mac 侧 `APP_ROLE=production`?**
因为那样就有两个 production 写入者。Mac 的正常出口是**推给 Railway**
(`/internal/cis-scores`,`X-Internal-Token`),Railway 是唯一写入者。
你现有的四个脚本自带客户端、写的是各自专属的表,不冲突 —— 保持现状即可。

**Q: `APP_ROLE=dev` 什么时候有?**
还没排期。Redis 写入散在 **6 个不同的 `_redis_set` 定义**里,没有收口点,
所以给不了它私有命名空间。**我们让它拒绝启动,而不是让它看起来可用** ——
一个共用生产 state key 的 "dev" 写入者,正是这条闸门要消除的隐患本身。
Phase 2 = 一个 Redis 写入 helper(按角色加 key 前缀)+ 一个 Supabase 分支。

---

## 四、优先级与回执

| # | 任务 | 优先级 | 期望 |
|---|---|---|---|
| A1 | 三个「全局量按条目获取」自查并修 | 🔴 P0 | 本周 |
| A2 | `asset_embeddings_history_push` 对齐 v3 | 🟡 P1 | 本周 |
| A3 | Mac `.env` 键名清单回报 + dotenv 缺失改 loud | 🟡 P1 | 10 分钟 |
| A4 | 文档四处更正 | 🟢 P2 | 下周前 |

**请先回执三件:**

1. `APP_ROLE` 那条边界你**确认理解**(尤其:以后 import 仓库 store 会静默失败)
2. A1 三个形状里,你的引擎**实际中了哪几个**
3. A4 里有没有哪一条**你认为我们仍然写错了** —— 上一轮的教训是,
   我们改了共享面却没先说,所以这一次**你不同意就直接说,不要按我们的写**

MD
echo "written"