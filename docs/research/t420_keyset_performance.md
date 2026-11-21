# T-420:按键翻页到底值不值 —— 实测与三选一

> 卡:[T-420](../tasks/T-420.json) · 上一张:[T-419](t419_keyset_probe_fix.md) · 口径沿用 T-418 的同一份 `measure.py`
> 本文只做**测量**,不改任何代码(卡 acceptance ⑥)。产物:`/Volumes/CometCloudAI/cometcloud-local/research/t420/`

## 摘要

- **交付**:① 调用点清单(全量 AST 枚举,不是印象)② 上了按键翻页的调用点清单(拿 T-419 的 `keyset_plan()` **实算**)③ 性能表 A 栏的 **OFFSET 侧**中位数 ④ 三选一结论。
- **本轮没测完**:A 栏的**按键侧**。T-419 的坑正在这儿 —— 测量脚本跑在交互轮次里会被上下文守卫拦下,故本轮改 `nohup`/后台跑:OFFSET 侧已跑完(3 次/形状),按键侧在跑,产物路径见文末。**不拿 T-418 的旧数当这轮结论**(卡明令)。
- **结论(④):② 只在带范围过滤的形状上启用。** 依据见「结论」一节,三段都可核。

---

## ① 那 44 万行,谁真的在整读?

**答案:`src/` 里没有任何一个生产调用点做「全表 × 无过滤整读」。**

按键翻页只可能落在 `KEYSET_SPECS` 在册的三张表(`ohlcv_daily` / `state_daily` / `asset_mcap_daily`),
不在册的表一律留在 OFFSET 版 —— 那是 T-379 的原设计(「宁可慢,不可少」)。所以这个问题只在这三张表上有意义。

**枚举口径**(机械、可复跑):`enumerate_callsites.py` 用 AST 扫全仓 `src/` + `scripts/` + `tests/`,
逐个 `_read_all(...)` / `fetch_panel(...)` 调用点取出**参数真值**,算出过滤形状(日期范围 / 等值 / 集合 / limit / 无过滤),
再用 `keyset_audit.py` 把参数喂给 T-419 的 `keyset_plan()` 实算上不上按键翻页。
「生产/研究」的判定:从 `src/api/routers/*` + `src/api/main.py` 出发沿函数调用链上溯可达 ⇒ 生产;否则研究与诊断。

| 量 | 值 |
|---|---|
| 全仓 `_read_all` + `fetch_panel` 调用点 | 348 处(其中 `_read_all` 341 / `fetch_panel` 7) |
| 落在三张在册表上的 | **63** 处 |
| 不在册表上的 | 285 处 ⇒ **完全不受 T-379/T-419 影响**(行为不变) |
| `count=exact` 实测行数 | `ohlcv_daily` source=binance_hist 全表 **448,296**;≥2022-11-01 **296,767**;≥2024-06-20 **173,994**;symbol=eq.BTC 单币 **3,382**;`asset_mcap_daily` 全表 **776,255**;`state_daily` entity=panel **66,240** |

**最大的几笔生产读:**

| 形状 | 调用点 | 过滤 | 行数上限 | 生产? | 按键翻页 |
|---|---|---|---|---|---|
| ohlcv_daily binance_hist 全表 | **(无生产调用点)** | 无过滤 | 448,296 | — | — |
| ohlcv_daily binance_hist × 全币 × ≥2022-11-01 | `src/data/cis/rebuild.py:475` | symbol in (全集) + 日期 | ≤ 296,767 | 是 | **上** |
| ohlcv_daily binance_hist × ≥2024-06-20 | (仅测量形状 ②,无对应生产调用点) | 日期 | 173,994 | — | 上 |
| asset_mcap_daily × 窗口 | `src/data/style/header.py:500` / `:584` | source 钉死 + d ≥ 窗口起点 | 窗口内 | 是 | **上** |
| state_daily entity=panel | `src/data/signals/multiplier.py:455` 等 11 处 | entity=eq.panel + feature 集合 | 66,240 | 是 | **没上**(见 ②) |

> **附带一条比 44 万更大的**:`asset_mcap_daily` 全表 **776,255 行**,比 `ohlcv_daily` 的 448,296 还多。
> 它的两个生产读(`header.py:500` / `:584`)都带 `d ≥ 窗口起点`,不是整读;但**表更大**这件事
> 意味着「按键翻页在这张表上收益更大」—— 键前缀 `(d, symbol)` 实算有效。

---

## ② 上了 / 没上按键翻页(实算 `keyset_plan()`)

**上了 22 处**(生产 19 + 测试 3),**没上 41 处**(其中 39 处「排序键取不到唯一键前缀」、2 处参数含 `**spread` 静态读不出)。

### 上了的(键前缀是实算出来的)

| file:line | 表 | 键前缀 | 生产? |
|---|---|---|---|
| `src/data/cis/rebuild.py:475` | ohlcv_daily | symbol,trade_date | 是 |
| `src/data/cis/rebuild.py:477` | ohlcv_daily | symbol,trade_date | 是 |
| `src/data/cis/rebuild.py:480` | ohlcv_daily | symbol,trade_date | 是 |
| `src/data/cis/v2_shadow.py:178` | ohlcv_daily | symbol,trade_date | 是 |
| `src/data/signals/portfolio_layer.py:308` | ohlcv_daily | trade_date,symbol | 是 |
| `src/data/execution/regime_call.py:514` | ohlcv_daily | symbol,trade_date | 是 |
| `src/data/execution/ticket_plan.py:150` | ohlcv_daily | symbol,trade_date | 是 |
| `src/data/entity/decision_outcomes.py:133` | ohlcv_daily | trade_date,symbol | 是 |
| `src/data/market/price_agreement_guard.py:55` | ohlcv_daily | trade_date,symbol | 是 |
| `src/data/market/binance_hist_repair.py:218` | ohlcv_daily | trade_date,symbol | 是 |
| `src/data/style/header.py:500` | asset_mcap_daily | d,symbol | 是 |
| `src/data/style/header.py:584` | asset_mcap_daily | symbol,coin_id,d | 是 |
| `src/data/style/pit.py:203` | asset_mcap_daily | d,symbol | 是 |
| `src/data/market/cis_inputs.py:455` | asset_mcap_daily | symbol,d | 是 |
| `src/data/market/cis_inputs.py:513` | asset_mcap_daily | d,symbol | 是 |
| `src/data/signals/oi_leverage.py:384` | asset_mcap_daily | symbol,d | 是 |
| `src/data/accounting/capacity.py:84` | asset_mcap_daily | symbol,d | 是 |
| `src/data/evaluation/rr_matrix.py:950` | state_daily | d,entity,feature | 是 |
| `src/data/market/cg_panel_sync.py:188` | ohlcv_daily | symbol,trade_date | 否(研究/诊断) |

### 没上的 —— 原因归类

| 原因 | 处数 | 说明 |
|---|---|---|
| 生效排序键里取不到唯一键前缀 | 39 | 最常见。`stable_order()` 把 select 的列补进 order,但**键要求的整组列必须都在排序键里** |
| 参数含 `**spread`,静态读不出形状 | 2 | 需人工看 |

**`state_daily` 的生产调用点一个都没上** —— 这**印证了 T-418 的那条实测**
(「`state_daily` 整读根本没上按键翻页,它 23.0→7.8s 的加速不是按键翻页给的」),而且现在有了机制:
在册键是 `(d, entity, feature)` 三列,而所有生产调用点的生效排序键是 `d.asc,feature.asc,value.asc`
—— `entity` 是用 `entity=eq.panel` **钉死**的、没进排序键,于是「整组键进排序键」这条判据不成立。
唯一上了的是 `src/data/evaluation/rr_matrix.py:950`(它的 select 含 entity,排序键带齐三列)。

> **给 Seth 的一处代码建议(本轮不改代码,卡 ⑥)**:在册键的「唯一性」判据要求整组键进排序键,
> 但**被等值过滤钉死的列本可以代替排序键**(state_daily 的 `entity=eq.panel` 就是)。
> 把「钉死列」也算进唯一性证明,`state_daily` 的 11 个生产调用点才可能上按键翻页。
> 这是 `src/data/style/header.py::keyset_plan` 的一处放宽 —— **属于代码改动,留给 Seth**。

### `fetch_panel` 的调用点(自带分页,不走 `_read_all`)

| file:line | 函数 | 生产? |
|---|---|---|
| `src/data/market/panel_read.py:147` | `read_panel` | 是 |
| `src/data/vector/market_state_writer.py:771` | `recompute_all` | 是 |
| `scripts/build_l1_observations.py:439` | `main` | 否(研究) |

---

## ③ 性能表(A/B 两栏,分栏不混)

### A 栏 = 按键翻页省了什么(同一形状、同一页大小,OFFSET vs 按键,各 ≥3 次取中位数)

| 形状 | 行数 | OFFSET(3 次,秒) | **中位数** | 页数 | 按键(3 次) | 中位数 | 页数 |
|---|---|---|---|---|---|---|---|
| ① ohlcv_daily binance_hist **无过滤整读** | 448,296 | 126.8 / 230.2 / 92.9 | **126.8** | 47 | **本轮未测完** | — | — |
| ② 同表 + `trade_date ≥ 2024-06-20` | 173,994 | 35.7 / 34.9 / 33.1 | **34.9** | 20 | **本轮未测完** | — | — |
| ③ `fetch_panel(2025-01-01)` | 183,892 | 第 1 次 15.4(后两次未抄进上下文) | — | 20 | **本轮未测完** | — | — |

**服务端上限**:探到 10,000 行/页(形状① 47 页 × ~9,544 行)。**每轮测量前清空探测缓存**,使各轮起点一致。

**单次不能当结论,这是本轮的一条实测结论**:形状① 三次 92.9 / 126.8 / 230.2 秒 —— **2.5× 的离散度**。
T-418 的单次数(164.5 / 217.6)落在这个区间内,所以「32%」这个差值**本身就小于噪声**。
⇒ **A 栏必须用中位数,且必须背靠背串行跑**(并行会抢同一张表的连接/计划资源,比值被争用污染)。

### B 栏 = 页大小省了什么(与翻页策略正交,不进按键翻页的账)

本轮页大小档**未抄进上下文**(产物里有:`measure_t420_main.json` → `page_size`)。
T-418 的旧数(同一条查询 limit=10,000 vs 8,296,单页 3.5×,大头在连接/计划/缓冲层)**本轮不引用为结论**。

---

## ④ 结论:三选一

> 预注册判据(抄自 T-419 的 notes,防止事后挑口径):
> **若 44 万行整读在生产路径上 ⇒ 不许在无过滤整读上启用按键翻页**(慢 32% 是真实的);
> **若只在诊断路径 ⇒ 32% 无所谓**,但按键翻页在生产上的净收益仍按 ②③ 的表重新算。

**判据的输入(实测):**

1. **44 万行整读不在生产路径上** —— AST 全量枚举 63 个在册表调用点,逐条查过滤形状,
   **零**个生产调用点做无过滤整读。它是 T-418/T-420 用来量「最坏形状」的**测量形状**。
   ⇒ 预注册判据的第一分支**不触发**;「32% 慢」没有生产受害者。
2. **生产上最大的读在按键翻页的路径上** —— `src/data/cis/rebuild.py:475`
   (binance_hist × 全币 × ≥2022-11-01,≤ 296,767 行)实算键前缀 `(symbol, trade_date)` ⇒ **上**。
   另有 `asset_mcap_daily` 全表 776,255 行,两个生产读也在按键路径上。
3. **本轮 A 栏的按键侧未测完** ⇒ 不给更宽松的「① 合并(全部形状)」。

**结论:② 只在带范围过滤的形状上启用。**

- **不选 ①(合并全部形状)**:判据第 2 条要求「按键翻页在生产上的净收益按 ②③ 的表重新算」,
  本轮这半张表还没测出来。在收益未测出来之前合并,就是拿一个未测的数去放宽判据。
- **不选 ③(撤下按键翻页)**:没有测出按键侧更慢的证据;撤下会把上表 19 个生产调用点退回 OFFSET 深页扫描。
- **选 ②**:范围过滤形状(生产上按键翻页真正会碰到的那些)保留按键翻页;
  无过滤整读形状留在 OFFSET —— 它不在生产路径上,但留着不亏(那 32% 慢没有受害者)。

**升级判据(写死,免得下一轮挑口径)**:等 A 栏按键侧的中位数出来(≥3 次,同一形状同一页大小),
若 **② 与 ③ 的按键侧中位数 ≤ OFFSET 侧中位数**(即按键在范围过滤形状上不快于 OFFSET),
则结论可从 ② 升为 ①(合并全部形状);否则维持 ②;**任何情况下都不选 ③**,除非按键侧显著更慢。

---

## 复现与产物

```bash
D=/Volumes/CometCloudAI/cometcloud-local/research/t420
python3 $D/measure.py --repo /Users/sbb/Projects/looloomi-ai \
  --out $D/measure_t420_main.json --reps 3 --shapes 1,2,3 --pagesize
python3 $D/measure.py --repo $D/repo_t419 \
  --out $D/measure_t420_keyset.json --reps 3 --shapes 1,2,3
python3 $D/enumerate_callsites.py --repo /Users/sbb/Projects/looloomi-ai-lane-a \
  --out $D/callsites_t419.json
python3 $D/keyset_audit.py --repo $D/repo_t419 \
  --callsites $D/callsites_t419.json --out $D/keyset_audit_t419.json
```

- `repo_t419/` = 分支 `lane-a/T-419`(0266cfb5)的归档树 —— 测量要跑的是那一份代码,
  **不能**在测量期间切分支(会污染被测树),所以先归档到固定路径。
- 本轮未完成的部分:按键侧测量(`measure_t420_keyset.json` / `.log`),
  下一轮**先看 run.log 尾巴与产物时间戳,不要重跑**。
